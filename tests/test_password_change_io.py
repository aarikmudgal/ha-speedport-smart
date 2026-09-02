"""Offline encrypted-transport tests for the private password transaction."""

# ruff: noqa: D103, SLF001

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Self
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import aiohttp
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.speedport_smart.admin_actions import (
    SPEEDPORT_SMART_4R_TYP_A_010152,
)
from custom_components.speedport_smart.api import (
    DEFAULT_KEY,
    SpeedportClient,
    encode_payload,
)
from custom_components.speedport_smart.password_change import (
    PASSWORD_CHANGE_CONFIRMATION,
    PasswordChangeError,
    PasswordChangeRequest,
    password_change_identity,
)
from custom_components.speedport_smart.password_change_io import (
    PasswordChangeClient,
    async_execute_password_change,
    create_password_change_client,
)

OLD = "old-private-password"
NEW = "new-private-password"
SERIAL = "synthetic-serial"
TARGET = SPEEDPORT_SMART_4R_TYP_A_010152
STATUS = {
    "device_name": TARGET.model,
    "firmware_version": TARGET.firmware,
    "serial_number": SERIAL,
}


@dataclass(slots=True)
class _Response:
    owner: _Session
    body: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def text(self, *, errors: str) -> str:
        assert errors == "replace"
        return self.body


class _Session:
    """Offline session: no sockets, DNS resolver, cookies or router calls."""

    def __init__(self, key: bytes = b"o" * 16) -> None:
        self.closed = False
        self.cookie_jar: dict[str, str] = {}
        self.key = key
        self.status_data: dict[str, object] = dict(STATUS)
        self.challenge: dict[str, object] = {"challenge": key.hex()}
        self.login: dict[str, object] = {"status": "ok", "login": "success"}
        self.ack: dict[str, object] = {"status": "ok", "login": "success"}
        self.ready: dict[str, object] = {"router_state": "OK"}
        self.logout: dict[str, object] = {"logout": "success"}
        self.page = '<input type="hidden" name="httoken" value="123456">'
        self.responses: dict[str, str | BaseException] = {}
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.forms: list[dict[str, str]] = []

    async def close(self) -> None:
        self.closed = True

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.requests.append((method, url, kwargs))
        if method == "GET":
            if "/data/Status.json?" in url:
                kind, body = "status", _encrypted(DEFAULT_KEY, **self.status_data)
            elif "/data/SecureStatus.json?" in url:
                kind, body = "ready", _encrypted(self.key, **self.ready)
            elif ".html" in url:
                kind, body = "page", self.page
            else:
                raise AssertionError(f"Unexpected offline GET: {url}")
        else:
            try:
                form = _body(kwargs, self.key)
            except InvalidTag:
                form = _body(kwargs, DEFAULT_KEY)
            self.forms.append(form)
            if set(form) == {"getChallenge"}:
                kind, body = "challenge", _encrypted(DEFAULT_KEY, **self.challenge)
            elif "new_password" in form:
                kind, body = "change", _encrypted(self.key, **self.ack)
            elif "showpw" in form:
                kind, body = "login", _encrypted(self.key, **self.login)
            elif "logout" in form:
                kind, body = "logout", _encrypted(self.key, **self.logout)
            else:
                raise AssertionError("Unexpected offline POST")
        override = self.responses.get(kind)
        if isinstance(override, BaseException):
            raise override
        if override is not None:
            body = override
        return _Response(self, body)


def _document(**values: object) -> str:
    return json.dumps(
        [{"varid": name, "varvalue": value} for name, value in values.items()]
    )


def _encrypted(key: bytes, **values: object) -> str:
    return encode_payload(_document(**values), key)


def _body(fields: dict[str, Any], key: bytes) -> dict[str, str]:
    plaintext = (
        AESCCM(key, tag_length=16)
        .decrypt(key[:8], bytes.fromhex(fields["data"]), None)
        .decode()
    )
    return {name: values[-1] for name, values in parse_qs(plaintext).items()}


def _draft(serial: str = SERIAL) -> PasswordChangeRequest:
    identity = password_change_identity(
        model=TARGET.model, firmware=TARGET.firmware, router_identifier=serial
    )
    return PasswordChangeRequest(
        {"password": OLD, "new_password": NEW, "new_pw_repeat": NEW},
        identity=identity,
        confirmed=True,
        confirmation_text=PASSWORD_CHANGE_CONFIRMATION,
        recovery_ready=True,
    )


async def _owner(*, authenticated: bool = True) -> tuple[SpeedportClient, _Session]:
    session = _Session()
    client = SpeedportClient(session, "speedport.ip", "stored-password")
    client._encrypted_mode = True
    if authenticated:
        client._authenticated = True
        client._login_key = b"o" * 16
        client._session_cleanup_key = b"o" * 16
    return client, session


def _factory(
    sessions: list[_Session], credentials: list[str], *, ack: dict[str, object]
) -> Any:
    keys = [b"a" * 16, b"b" * 16]

    def factory(password: str) -> PasswordChangeClient:
        index = len(sessions)
        key = keys[index]
        session = _Session(key)
        sessions.append(session)
        credentials.append(password)
        if index == 0:
            session.ack = ack
        return PasswordChangeClient(
            session,
            "speedport.ip",
            password,
            max_busy_retries=0,
            endpoint_candidates={},
        )

    return factory


@pytest.fixture(autouse=True)
def _no_logout_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "custom_components.speedport_smart.api.client._LOGOUT_SETTLE_SECONDS", 0
    )


async def test_success_uses_isolated_jars_one_change_and_private_one_use_proof() -> (
    None
):
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    checks = 0

    def check() -> None:
        nonlocal checks
        checks += 1

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=check,
        client_factory=_factory(
            sessions, credentials, ack={"status": "ok", "login": "success"}
        ),
    )
    try:
        assert result.result == {
            "status": "outcome_unknown",
            "verification": "credential_update_required",
            "credential_verified": True,
            "retry_safe": False,
        }
        assert result.proof is not None
        assert repr(result.proof) == "<VerifiedPasswordCredential private>"
        assert NEW not in repr(result)
        assert result.proof.take_credential() == NEW
        with pytest.raises(PasswordChangeError):
            result.proof.take_credential()
        assert result.proof.finish(credential_persisted=True) == {
            "status": "verified",
            "verification": "new_credential",
            "credential_updated": True,
            "retry_safe": False,
        }
    finally:
        await owner_session.close()
    assert credentials == [OLD, NEW]
    # Initial/form checks plus a fresh gate for all five non-cleanup JSON POSTs.
    assert checks == 7
    assert all(session.closed for session in sessions)
    assert (
        len({id(owner_session.cookie_jar), *(id(item.cookie_jar) for item in sessions)})
        == 3
    )
    password_posts = [
        request
        for session in sessions
        for request in session.requests
        if request[0] == "POST" and "new_password" in str(request[2].get("data", ""))
    ]
    # The wire body is encrypted, so inspect all old-session Login POSTs instead.
    login_posts = [
        request
        for request in sessions[0].requests
        if request[0] == "POST" and request[1].endswith("/data/Login.json")
    ]
    assert password_posts == []
    assert len(login_posts) == 4  # challenge, login proof, one change, one logout
    assert [form for form in sessions[0].forms if "new_password" in form] == [
        {
            "password": OLD,
            "new_password": NEW,
            "new_pw_repeat": NEW,
            "httoken": "123456",
        }
    ]
    for session in (owner_session, *sessions):
        assert all(
            request[2]["allow_redirects"] is False for request in session.requests
        )


async def test_unknown_ack_never_tries_new_password_or_retries_change() -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=_factory(sessions, credentials, ack={"status": "ok"}),
    )
    try:
        assert result.result["status"] == "outcome_unknown"
        assert result.result["acknowledged"] is False
        assert result.proof is None
        assert credentials == [OLD]
        login_posts = [
            request for request in sessions[0].requests if request[0] == "POST"
        ]
        assert len(login_posts) == 4
    finally:
        await owner_session.close()


async def test_serial_mismatch_stops_before_login_or_change() -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    result = await async_execute_password_change(
        _draft("different-serial"),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=_factory(
            sessions, credentials, ack={"status": "ok", "login": "success"}
        ),
    )
    try:
        assert result.result["status"] == "not_started"
        assert result.result["error"] == "password_change_preflight_failed"
        assert len(sessions) == 1
        assert sessions[0].requests[0][0] == "GET"
        assert not any(request[0] == "POST" for request in sessions[0].requests)
    finally:
        await owner_session.close()


async def test_expired_requester_after_fresh_token_sends_no_change() -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    calls = 0

    def check() -> None:
        nonlocal calls
        calls += 1
        if sessions and any(
            method == "GET" and url.endswith("config/change_password.html")
            for method, url, _ in sessions[0].requests
        ):
            raise RuntimeError("private external text must not escape")

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=check,
        client_factory=_factory(
            sessions, credentials, ack={"status": "ok", "login": "success"}
        ),
    )
    try:
        assert result.result == {
            "status": "not_started",
            "retry_safe": False,
            "error": "password_change_preflight_failed",
        }
        assert result.proof is None
        posts = [request for request in sessions[0].requests if request[0] == "POST"]
        assert len(posts) == 3  # challenge, proof, logout only
        assert "private external" not in repr(result)
    finally:
        await owner_session.close()


async def test_factory_reusing_owner_transport_is_rejected_without_closing_owner() -> (
    None
):
    owner, owner_session = await _owner(authenticated=False)

    def bad_factory(password: str) -> PasswordChangeClient:
        return PasswordChangeClient(owner_session, "speedport.ip", password)

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=bad_factory,
    )
    try:
        assert result.result["status"] == "not_started"
        assert result.proof is None
        assert not owner_session.closed
        assert owner_session.requests == []
    finally:
        await owner_session.close()


@pytest.mark.parametrize(
    ("ack", "status"),
    [
        ({"status": "ok", "login": ["success", "success"]}, "outcome_unknown"),
        ({"status": "ok", "login": "success", "Login": "failure"}, "outcome_unknown"),
        (
            {"status": "ok", "login": "success", "error": "private error"},
            "outcome_unknown",
        ),
        ({"status": "ok", "login": "failure", "reason": "-1"}, "rejected"),
        ({"status": "ok", "login": "failure", "reason": "-2"}, "rejected"),
        ({"status": "error"}, "rejected"),
    ],
)
async def test_nonacceptance_does_not_open_new_session(ack: dict, status: str) -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=_factory(sessions, credentials, ack=ack),
    )
    await owner_session.close()
    assert result.result["status"] == status
    assert result.proof is None
    assert credentials == [OLD]
    assert len([form for form in sessions[0].forms if "new_password" in form]) == 1
    assert "private error" not in repr(result)


@pytest.mark.parametrize(
    ("stage", "values"),
    [
        ("status_data", {**STATUS, "serial_number": ""}),
        ("status_data", {**STATUS, "serial_number": None}),
        ("status_data", {**STATUS, "serial_number": [SERIAL, SERIAL]}),
        ("status_data", {**STATUS, "serial": "another-router"}),
        ("status_data", {**STATUS, "Serial_Number": "another-router"}),
        ("status_data", {**STATUS, "firmware_version": "wrong-firmware"}),
        ("challenge", {"challenge": "a1" * 16, "login_other": "private foreign owner"}),
        ("challenge", {"challenge": "a1" * 16, "login_locked": "5"}),
        ("challenge", {"challenge": ["a1" * 16, "a1" * 16]}),
        ("challenge", {"challenge": " a1"}),
        ("login", {"status": "ok"}),
        ("login", {"login": "ok"}),
        ("login", {"login": "success", "Login": "failure"}),
        ("ready", {"router_state": "REBOOT"}),
        ("ready", {"router_state": ["OK", "OK"]}),
    ],
)
async def test_failed_fresh_preflight_never_sends_password_form(
    stage: str, values: dict
) -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    factory = _factory(sessions, credentials, ack={"status": "ok", "login": "success"})

    def modified(password: str) -> PasswordChangeClient:
        client = factory(password)
        setattr(sessions[-1], stage, values)
        return client

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=modified,
    )
    await owner_session.close()
    assert result.result["status"] == "not_started"
    assert result.proof is None
    assert credentials == [OLD]
    assert not any("new_password" in form for form in sessions[0].forms)
    if stage in {"status_data", "challenge"}:
        assert not any("showpw" in form for form in sessions[0].forms)
    assert "private foreign owner" not in repr(result)
    assert all(session.closed for session in sessions)


@pytest.mark.parametrize("stage", ["login", "change"])
@pytest.mark.parametrize("wire", ["plaintext", "public_key", "timeout"])
async def test_credentials_require_challenge_key_responses(
    stage: str, wire: str
) -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    factory = _factory(sessions, credentials, ack={"status": "ok", "login": "success"})

    def modified(password: str) -> PasswordChangeClient:
        client = factory(password)
        sessions[-1].responses[stage] = {
            "plaintext": _document(status="ok", login="success"),
            "public_key": _encrypted(DEFAULT_KEY, status="ok", login="success"),
            "timeout": TimeoutError("private credential error"),
        }[wire]
        return client

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=modified,
    )
    await owner_session.close()
    assert result.result["status"] == (
        "not_started" if stage == "login" else "outcome_unknown"
    )
    assert result.proof is None
    assert credentials == [OLD]
    assert len([form for form in sessions[0].forms if "new_password" in form]) == (
        stage == "change"
    )
    assert "private credential" not in repr(result)


@pytest.mark.parametrize("which", ["owner", "old", "new"])
async def test_cleanup_failure_never_claims_verified_without_persistence(
    which: str,
) -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    factory = _factory(sessions, credentials, ack={"status": "ok", "login": "success"})
    if which == "owner":
        owner_session.logout = {"status": "error"}

    def modified(password: str) -> PasswordChangeClient:
        client = factory(password)
        if (which == "old" and password == OLD) or (which == "new" and password == NEW):
            sessions[-1].logout = {"status": "error"}
        return client

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=modified,
    )
    await owner_session.close()
    assert result.result["status"] == "outcome_unknown"
    if which == "new":
        assert result.proof is not None
        assert result.proof.take_credential() == NEW
        assert result.proof.finish(credential_persisted=True) == {
            "status": "outcome_unknown",
            "verification": "session_cleanup_failed",
            "credential_updated": True,
            "retry_safe": False,
        }
    else:
        assert result.proof is None
        assert credentials == ([] if which == "owner" else [OLD])
    assert all(session.closed for session in sessions)


@pytest.mark.parametrize("stage", ["status_data", "login", "ready"])
async def test_new_credential_failure_never_cycles_back_to_old(stage: str) -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    factory = _factory(sessions, credentials, ack={"status": "ok", "login": "success"})

    def modified(password: str) -> PasswordChangeClient:
        client = factory(password)
        if password == NEW:
            setattr(
                sessions[-1],
                stage,
                {
                    "status_data": {**STATUS, "serial_number": "changed-router"},
                    "login": {"login": "failure"},
                    "ready": {"router_state": "REBOOT"},
                }[stage],
            )
        return client

    result = await async_execute_password_change(
        _draft(),
        owner_client=owner,
        check_requester=lambda: None,
        client_factory=modified,
    )
    await owner_session.close()
    assert result.result["status"] == "outcome_unknown"
    assert result.result["acknowledged"] is True
    assert result.proof is None
    assert credentials == [OLD, NEW]
    assert (
        sum("new_password" in form for session in sessions for form in session.forms)
        == 1
    )
    assert all(session.closed for session in sessions)


async def test_cancellation_after_post_cleans_session_and_consumes_draft() -> None:
    owner, owner_session = await _owner()
    sessions: list[_Session] = []
    credentials: list[str] = []
    factory = _factory(sessions, credentials, ack={"status": "ok", "login": "success"})
    draft = _draft()

    def modified(password: str) -> PasswordChangeClient:
        client = factory(password)
        sessions[-1].responses["change"] = asyncio.CancelledError()
        return client

    with pytest.raises(asyncio.CancelledError):
        await async_execute_password_change(
            draft,
            owner_client=owner,
            check_requester=lambda: None,
            client_factory=modified,
        )
    await owner_session.close()
    assert credentials == [OLD]
    assert sessions[0].closed
    assert sum("new_password" in form for form in sessions[0].forms) == 1
    assert any("logout" in form for form in sessions[0].forms)
    assert not owner._lock.locked()
    with pytest.raises(PasswordChangeError, match="stale_password_change"):
        draft.current_password()


async def test_default_factory_is_actual_client_with_fresh_server_owned_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, owner_session = await _owner(authenticated=False)
    owner._verify_ssl = False
    owner._timeout = aiohttp.ClientTimeout(total=17)
    session = _Session()
    constructor = MagicMock(return_value=session)
    monkeypatch.setattr("aiohttp.ClientSession", constructor)
    client = await create_password_change_client(owner, OLD)
    assert isinstance(client, PasswordChangeClient)
    assert isinstance(client, SpeedportClient)
    assert client.configuration_url == owner.configuration_url
    assert client._verify_ssl is False
    assert client._timeout.total == 17
    assert client._max_busy_retries == 0
    assert client._session is not owner._session
    assert not client.is_authenticated
    assert constructor.call_args.kwargs["trust_env"] is False
    assert isinstance(constructor.call_args.kwargs["cookie_jar"], aiohttp.CookieJar)
    await client.close()
    await session.close()
    await owner_session.close()


async def test_cancel_while_waiting_for_owner_lock_clears_credentials_without_io() -> (
    None
):
    owner, owner_session = await _owner(authenticated=False)
    draft = _draft()
    entered = asyncio.Event()

    async def run() -> None:
        entered.set()
        await async_execute_password_change(
            draft,
            owner_client=owner,
            check_requester=lambda: None,
        )

    await owner._lock.acquire()
    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    owner._lock.release()
    await owner_session.close()
    assert owner_session.requests == []
    with pytest.raises(PasswordChangeError, match="stale_password_change"):
        draft.current_password()
