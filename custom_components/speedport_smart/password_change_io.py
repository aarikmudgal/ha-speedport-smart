"""
Private, isolated password-change transaction; no HA credential persistence.

The owner holds its hub operation lock and has consumed an administrator-bound,
short-lived approval before calling this module. This module holds the existing
client lock throughout, releases its old session, and uses separate cookie jars
for the entered old credential and the new-credential proof. Only the exact
password form is sent, once. A transport error or ambiguous ACK never authorizes
another credential attempt. No callback, return metadata, or exception contains
credentials, router identity, challenges or response bodies.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import aiohttp

from .api.client import SpeedportClient
from .api.codec import decode_payload, is_encrypted_payload
from .models import normalize_status
from .password_change import (
    PASSWORD_CHANGE_ENDPOINT,
    PASSWORD_CHANGE_REFERER,
    PasswordChangeError,
    PasswordChangeIdentity,
    PasswordChangeRequest,
    password_change_identity,
    validate_password_login_response,
)
from .private_authorization import private_authorization

_LOGIN_FIELDS: Final = (
    "login",
    "status",
    "reason",
    "login_other",
    "login_locked",
    "error",
    "errors",
)
_CHALLENGE: Final = re.compile(r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{48}|[0-9a-fA-F]{64})")
_READY_ENDPOINT: Final = "data/SecureStatus.json"
_READY_REFERER: Final = "html/content/overview/index.html"


def _scalar(raw: Mapping[str, Any], name: str) -> object:
    """Reject aliases and compound values, including identical ACK duplicates."""
    if [key for key in raw if str(key).casefold() == name.casefold()] not in (
        [],
        [name],
    ):
        raise PasswordChangeError("password_change_preflight_failed")
    value = raw.get(name)
    if value is not None and type(value) not in {str, int, bool}:
        raise PasswordChangeError("password_change_preflight_failed")
    return value


def _fresh_identity(raw: Mapping[str, Any]) -> PasswordChangeIdentity:
    """Bind actual fresh serial, never a configured host fallback or browser ID."""
    for names in (
        ("device_name", "model_name", "product_name"),
        ("firmware_version", "firmware", "sw_version"),
        ("serial_number", "serial", "serialno"),
    ):
        values = [_scalar(raw, key) for key in names if key in raw]
        if (
            not values
            or any(type(value) is not str or not value.strip() for value in values)
            or len({str(value).strip() for value in values}) != 1
        ):
            raise PasswordChangeError("password_change_preflight_failed")
        # Case variants cannot silently supersede the canonical read field.
        for key in names:
            _scalar(raw, key)
    info = normalize_status(raw).info
    return password_change_identity(
        model=info.model, firmware=info.firmware, router_identifier=info.serial_number
    )


class PasswordChangeClient(SpeedportClient):
    """Actual protocol client retaining only bounded, private login-proof fields."""

    _proof_response: dict[str, Any] | None = None
    _proof_challenge: str | None = None
    _required_response_key: bytes | None = None

    async def _request_text_unlocked(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: str | None = None,
        allow_error_body: bool = False,
    ) -> str:
        text = await super()._request_text_unlocked(
            method, url, headers=headers, data=data, allow_error_body=allow_error_body
        )
        if self._required_response_key is not None:
            # Generic reads permit the public-key fallback. A credential proof
            # must instead authenticate with this fresh session's challenge key.
            if not is_encrypted_payload(text):
                raise PasswordChangeError("password_change_outcome_unknown")
            decode_payload(text, self._required_response_key)
        return text

    async def _post_json_unlocked(
        self,
        endpoint: str,
        data: Mapping[str, str | int | bool],
        *,
        authenticated: bool,
        referer: str | None,
        ensure_auth: bool = True,
        resolve_http_token: bool = True,
        request_key: bytes | None = None,
        response_key: bytes | None = None,
    ) -> dict[str, Any]:
        login_proof = endpoint == PASSWORD_CHANGE_ENDPOINT and set(data) == {
            "showpw",
            "password",
        }
        password_form = endpoint == PASSWORD_CHANGE_ENDPOINT and "new_password" in data
        self._required_response_key = (
            response_key if login_proof else self._login_key if password_form else None
        )
        try:
            raw = await super()._post_json_unlocked(
                endpoint,
                data,
                authenticated=authenticated,
                referer=referer,
                ensure_auth=ensure_auth,
                resolve_http_token=resolve_http_token,
                request_key=request_key,
                response_key=response_key,
            )
        finally:
            self._required_response_key = None
        if endpoint == PASSWORD_CHANGE_ENDPOINT and set(data) == {"getChallenge"}:
            challenge = _scalar(raw, "challenge")
            if type(challenge) is not str or _CHALLENGE.fullmatch(challenge) is None:
                raise PasswordChangeError("password_change_preflight_failed")
            # Never send even a login proof into an ambiguous competing session.
            probe = {key: _scalar(raw, key) for key in _LOGIN_FIELDS}
            probe["login"] = "success"
            validate_password_login_response(probe)
            self._proof_challenge = challenge
        elif login_proof:
            try:
                # Preserve the legacy client's own rejection/ownership handling;
                # apply the stricter success gate only after login() completes.
                self._proof_response = {key: _scalar(raw, key) for key in _LOGIN_FIELDS}
            except PasswordChangeError:
                self._proof_response = None
        return raw

    async def fresh_identity(self) -> PasswordChangeIdentity:
        """Fetch public identity once, without generic recovery or a login retry."""
        async with self._lock:
            raw = await self._get_json_unlocked(
                "data/Status.json", authenticated=False, referer=None
            )
            if self._encrypted_mode is not True:
                raise PasswordChangeError("password_change_preflight_failed")
            return _fresh_identity(raw)

    async def authenticate_once(self) -> None:
        """Run the existing challenge protocol once, requiring exact login success."""
        if self.is_authenticated or self._session_cleanup_key is not None:
            raise PasswordChangeError("password_change_preflight_failed")
        self._proof_response = self._proof_challenge = None
        await self.login()
        validate_password_login_response(self._proof_response)
        if self._proof_challenge is None:
            raise PasswordChangeError("password_verification_failed")

    async def ready_state(self) -> str:
        """Use a proven, independent status GET, never GET the password action."""
        async with self._lock:
            if not self.is_authenticated:
                raise PasswordChangeError("password_change_preflight_failed")
            raw = await self._get_json_unlocked(
                _READY_ENDPOINT, authenticated=True, referer=_READY_REFERER
            )
            if _scalar(raw, "router_state") != "OK":
                raise PasswordChangeError("password_change_preflight_failed")
        return "OK"

    async def change_password_once(
        self, draft: PasswordChangeRequest, *, check_requester: Callable[[], None]
    ) -> str:
        """Fresh readiness/token then consume immediately before the one form POST."""
        identity = await self.fresh_identity()
        state = await self.ready_state()
        async with self._lock:
            if not self.is_authenticated:
                raise PasswordChangeError("password_change_preflight_failed")
            token = await self._get_http_token_unlocked(PASSWORD_CHANGE_REFERER)
            check_requester()
            payload = draft.take_payload(
                page_token=token,
                current_identity=identity,
                router_state=state,
                current_password_authenticated=True,
            )
            try:
                # No _ensure_authenticated recovery or generic action retry.
                raw = await self._post_json_unlocked(
                    PASSWORD_CHANGE_ENDPOINT,
                    payload,
                    authenticated=True,
                    referer=PASSWORD_CHANGE_REFERER,
                    ensure_auth=False,
                    resolve_http_token=False,
                )
                return draft.record_acknowledgement(raw)
            finally:
                payload.clear()

    def forget_private_proof(self) -> None:
        """Drop references after transport cleanup; immutable strings cannot zeroize."""
        self._proof_response = self._proof_challenge = self._required_response_key = (
            None
        )
        self._password = None


async def create_password_change_client(
    owner_client: SpeedportClient, password: str
) -> PasswordChangeClient:
    """Create a fresh actual aiohttp session using only the owner's transport setup."""
    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True), trust_env=False
    )
    try:
        return PasswordChangeClient(
            session,
            owner_client.configuration_url,
            password,
            verify_ssl=owner_client._verify_ssl,  # noqa: SLF001
            request_timeout=owner_client._timeout.total or 10.0,  # noqa: SLF001
            max_busy_retries=0,
            owns_session=False,
            endpoint_candidates={},
        )
    except Exception:  # noqa: BLE001
        await session.close()
        raise PasswordChangeError("password_change_preflight_failed") from None


class VerifiedPasswordCredential:
    """One-use private credential, released only after a separate successful login."""

    __slots__ = ("_cleanup_confirmed", "_credential", "_finished", "_taken")

    def __init__(self, credential: str, *, cleanup_confirmed: bool) -> None:
        """Retain a credential only after the request's verification gate."""
        self._credential: str | None = credential
        self._cleanup_confirmed = cleanup_confirmed
        self._taken = self._finished = False

    def __repr__(self) -> str:
        """Never serialize a proven credential through object repr."""
        return "<VerifiedPasswordCredential private>"

    def take_credential(self) -> str:
        """Supply exactly once to server-side HA config-entry persistence."""
        if self._taken or self._finished or self._credential is None:
            raise PasswordChangeError("stale_password_change")
        value = self._credential
        self._credential = None
        self._taken = True
        return value

    def finish(self, *, credential_persisted: bool) -> dict[str, Any]:
        """Return a public outcome after the owner actually completes persistence."""
        if (
            self._finished
            or type(credential_persisted) is not bool
            or (credential_persisted and not self._taken)
        ):
            raise PasswordChangeError("stale_password_change")
        self.clear()
        if not credential_persisted:
            return {
                "status": "outcome_unknown",
                "verification": "credential_update_required",
                "credential_verified": True,
                "retry_safe": False,
            }
        return {
            "status": "verified" if self._cleanup_confirmed else "outcome_unknown",
            "verification": "new_credential"
            if self._cleanup_confirmed
            else "session_cleanup_failed",
            "credential_updated": True,
            "retry_safe": False,
        }

    def clear(self) -> None:
        """Release references if persistence is abandoned or fails."""
        self._credential = None
        self._finished = True


@dataclass(slots=True)
class PasswordChangeTransactionResult:
    """Only result is public; never JSON encode the private proof object."""

    result: dict[str, Any]
    proof: VerifiedPasswordCredential | None = field(default=None, repr=False)


async def _release(client: PasswordChangeClient) -> bool:
    """Attempt ownership-bound logout, then close the independently owned session."""
    confirmed = True
    try:
        await client.logout_ephemeral()
    except Exception:  # noqa: BLE001
        confirmed = False
    finally:
        try:
            # Logout's finally clears the key even if its ACK is uncertain. Do
            # not introduce another logout/retry from close() after that attempt.
            client._clear_session_state()  # noqa: SLF001
            client.forget_private_proof()
            await client.close()
        except Exception:  # noqa: BLE001
            confirmed = False
        finally:
            try:
                await client._session.close()  # noqa: SLF001
            except Exception:  # noqa: BLE001
                confirmed = False
    return confirmed


async def _new_client(
    factory: Callable[[str], PasswordChangeClient | Awaitable[PasswordChangeClient]],
    password: str,
    owner: SpeedportClient,
    previous: PasswordChangeClient | None = None,
) -> PasswordChangeClient:
    created = factory(password)
    candidate = await created if inspect.isawaitable(created) else created
    if not isinstance(candidate, PasswordChangeClient):
        raise PasswordChangeError("password_change_preflight_failed")
    forbidden = (owner,) if previous is None else (owner, previous)
    shares_transport = any(
        candidate is item or candidate._session is item._session  # noqa: SLF001
        for item in forbidden
    )
    shares_cookies = any(
        candidate._session.cookie_jar is item._session.cookie_jar  # noqa: SLF001
        for item in forbidden
    )
    invalid = (
        shares_transport
        or shares_cookies
        or candidate.configuration_url != owner.configuration_url
        or candidate._verify_ssl is not owner._verify_ssl  # noqa: SLF001
        or candidate._session.closed  # noqa: SLF001
        or candidate._closed  # noqa: SLF001
        or candidate.is_authenticated
        or candidate._login_key is not None  # noqa: SLF001
        or candidate._session_cleanup_key is not None  # noqa: SLF001
        or len(candidate._session.cookie_jar) != 0  # noqa: SLF001
    )
    if invalid:
        # The candidate has not been accepted as an owned router session. Close
        # its separate HTTP transport, without an unproven/possibly foreign logout.
        if not shares_transport:
            candidate.forget_private_proof()
            candidate._clear_session_state()  # noqa: SLF001
            await candidate._session.close()  # noqa: SLF001
        raise PasswordChangeError("password_change_preflight_failed") from None
    return candidate


async def async_execute_password_change(
    draft: PasswordChangeRequest,
    *,
    owner_client: SpeedportClient,
    check_requester: Callable[[], None],
    client_factory: Callable[
        [str], PasswordChangeClient | Awaitable[PasswordChangeClient]
    ]
    | None = None,
) -> PasswordChangeTransactionResult:
    """Keep the owner's live authorization attached to every isolated client send."""
    with private_authorization(check_requester):
        return await _async_execute_password_change(
            draft,
            owner_client=owner_client,
            check_requester=check_requester,
            client_factory=client_factory,
        )


async def _async_execute_password_change(
    draft: PasswordChangeRequest,
    *,
    owner_client: SpeedportClient,
    check_requester: Callable[[], None],
    client_factory: Callable[
        [str], PasswordChangeClient | Awaitable[PasswordChangeClient]
    ]
    | None = None,
) -> PasswordChangeTransactionResult:
    """
    Release the old owner; perform one change and at most one fresh new login.

    Caller already owns the hub operation lock. It must suspend protected polling
    on an uncertain result, and store a returned proof only after checking that
    the entry/user approval still belongs to this operation. Never save the old
    or new password speculatively, and never retry this transaction automatically.
    """
    factory = client_factory or (
        lambda password: create_password_change_client(owner_client, password)
    )
    old: PasswordChangeClient | None = None
    new: PasswordChangeClient | None = None
    cleanup_confirmed = True
    verified: str | None = None
    error: str | None = None
    cancelled = False
    try:
        await owner_client._lock.acquire()  # noqa: SLF001
    except asyncio.CancelledError:
        draft.clear()
        raise
    try:
        try:
            check_requester()
            # Keep this lock held so normal polling cannot reuse the stored old
            # credential while an isolated change/new-password proof is running.
            try:
                await owner_client._logout_unlocked(require_confirmation=True)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                cleanup_confirmed = False
                raise PasswordChangeError("password_change_preflight_failed") from None
            old = await _new_client(factory, draft.current_password(), owner_client)
            draft.validate_identity(await old.fresh_identity())
            await old.authenticate_once()
            acknowledgement = await old.change_password_once(
                draft, check_requester=check_requester
            )
            if acknowledgement == "accepted":
                cleanup_confirmed = await _release(old)
                if cleanup_confirmed:
                    new = await _new_client(
                        factory, draft.verification_password(), owner_client, old
                    )
                    draft.validate_identity(await new.fresh_identity())
                    await new.authenticate_once()
                    identity = await new.fresh_identity()
                    state = await new.ready_state()
                    draft.verify_new_login(
                        response=new._proof_response,  # noqa: SLF001
                        current_identity=identity,
                        router_state=state,
                        old_session_released=True,
                        isolated_new_session=True,
                        fresh_challenge_requested=True,
                        new_challenge=new._proof_challenge,  # noqa: SLF001
                    )
                    verified = draft.credential_for_storage()
        except asyncio.CancelledError:
            cancelled = True
        except PasswordChangeError as exc:
            error = exc.code
        except Exception:  # noqa: BLE001
            error = "password_change_preflight_failed"
        finally:
            # Shield cleanup from caller cancellation; a second cancellation is
            # recorded but cannot abandon an independently owned router session.
            async def cleanup() -> bool:
                confirmed = cleanup_confirmed
                for client in (old, new):
                    if client is not None and not client._closed:  # noqa: SLF001
                        confirmed = await _release(client) and confirmed
                return confirmed

            cleanup_task = asyncio.create_task(cleanup())
            while not cleanup_task.done():
                try:
                    cleanup_confirmed = await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    cancelled = True
            cleanup_confirmed = cleanup_task.result()
            result = draft.result(
                credential_persisted=False, cleanup_confirmed=cleanup_confirmed
            )
            if error and result["status"] == "not_started":
                result["error"] = error
            if not cleanup_confirmed and verified is None:
                result = {
                    "status": "outcome_unknown",
                    "verification": "session_cleanup_failed",
                    "retry_safe": False,
                }
            draft.clear()
    finally:
        draft.clear()
        owner_client._lock.release()  # noqa: SLF001
    if cancelled:
        verified = None
        raise asyncio.CancelledError
    proof = (
        VerifiedPasswordCredential(verified, cleanup_confirmed=cleanup_confirmed)
        if verified is not None
        else None
    )
    return PasswordChangeTransactionResult(result, proof)
