"""Offline final-send authorization, context isolation, expiry, and cleanup proof."""

# ruff: noqa: D103, SLF001

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.speedport_smart.api import DEFAULT_KEY, SpeedportClient
from custom_components.speedport_smart.password_change_io import PasswordChangeClient
from custom_components.speedport_smart.private_authorization import (
    PrivateAuthorizationError,
    check_private_authorization,
    private_authorization,
)


def _denied() -> None:
    raise RuntimeError("synthetic private authorization detail")


def _client(cls: type[SpeedportClient] = SpeedportClient) -> SpeedportClient:
    client = cls(MagicMock(), "router.invalid")
    client._authenticated = True
    client._login_key = DEFAULT_KEY
    client._encrypted_mode = False
    return client


def test_unscoped_work_unchanged_and_errors_do_not_expose_checker_text() -> None:
    check_private_authorization()
    with (
        private_authorization(_denied),
        pytest.raises(PrivateAuthorizationError) as error,
    ):
        check_private_authorization()
    assert "synthetic" not in str(error.value)
    assert error.value.__suppress_context__
    check_private_authorization()


def test_nested_authorization_cannot_replace_outer_scope_and_resets_after_exit() -> (
    None
):
    outer, inner = MagicMock(return_value=None), MagicMock(return_value=None)
    with private_authorization(outer):
        with private_authorization(inner):
            check_private_authorization()
        check_private_authorization()
    assert outer.call_count == 2
    inner.assert_called_once()
    with (
        private_authorization(_denied),
        private_authorization(lambda: None),
        pytest.raises(PrivateAuthorizationError),
    ):
        check_private_authorization()
    check_private_authorization()


async def test_child_task_cannot_mutate_after_request_scope_ends() -> None:
    release = asyncio.Event()

    async def escaped() -> None:
        await release.wait()
        check_private_authorization()

    with private_authorization(lambda: None):
        child = asyncio.create_task(escaped())
    release.set()
    with pytest.raises(PrivateAuthorizationError):
        await child
    check_private_authorization()


async def test_parallel_requests_have_independent_scopes() -> None:
    release = asyncio.Event()

    async def request(checker: Any) -> bool:
        with private_authorization(checker):
            await release.wait()
            try:
                check_private_authorization()
            except PrivateAuthorizationError:
                return False
            return True

    denied = asyncio.create_task(request(_denied))
    allowed = asyncio.create_task(request(lambda: None))
    release.set()
    assert await asyncio.gather(denied, allowed) == [False, True]
    check_private_authorization()


async def test_cancelled_scope_resets_and_revokes_escaped_children() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    child: asyncio.Task[None] | None = None

    async def escaped() -> None:
        await release.wait()
        check_private_authorization()

    async def request() -> None:
        nonlocal child
        try:
            with private_authorization(lambda: None):
                child = asyncio.create_task(escaped())
                entered.set()
                await asyncio.Event().wait()
        finally:
            check_private_authorization()

    task = asyncio.create_task(request())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    assert child is not None
    with pytest.raises(PrivateAuthorizationError):
        await child


@pytest.mark.parametrize("boundary", ["client_lock", "authentication", "token"])
async def test_each_await_before_final_json_send_rechecks_authorization(
    boundary: str,
) -> None:
    client = _client()
    entered, release = asyncio.Event(), asyncio.Event()
    valid = True

    def authorize() -> None:
        if not valid:
            _denied()

    async def waited(*_args: Any) -> str:
        entered.set()
        await release.wait()
        return "123"

    async def request() -> dict:
        with private_authorization(authorize):
            if boundary == "client_lock":
                entered.set()
            return await client._post_ephemeral_action(
                "data/Energy.json",
                {"led": "1"},
                referer="html/content/config/energy.html",
            )

    if boundary == "client_lock":
        await client._lock.acquire()
    with (
        patch.object(
            client,
            "_ensure_authenticated_unlocked",
            AsyncMock(side_effect=waited if boundary == "authentication" else None),
        ),
        patch.object(
            client,
            "_get_http_token_unlocked",
            AsyncMock(
                side_effect=waited if boundary == "token" else None, return_value="123"
            ),
        ),
        patch.object(
            client, "_request_text_unlocked", AsyncMock(return_value='{"status":"ok"}')
        ) as wire,
    ):
        task = asyncio.create_task(request())
        await entered.wait()
        valid = False
        release.set()
        if boundary == "client_lock":
            client._lock.release()
        with pytest.raises(PrivateAuthorizationError):
            await task
    wire.assert_not_awaited()


@pytest.mark.parametrize(
    "fields",
    [
        {"getChallenge": "1"},
        {"showpw": "0", "password": "synthetic-hash"},
        {
            "password": "synthetic-old",
            "new_password": "synthetic-new",
            "new_pw_repeat": "synthetic-new",
            "httoken": "123",
        },
    ],
)
async def test_password_login_and_change_posts_share_final_gate(fields: dict) -> None:
    client = _client(PasswordChangeClient)
    with (
        private_authorization(_denied),
        patch.object(client, "_request_text_unlocked", AsyncMock()) as wire,
        pytest.raises(PrivateAuthorizationError),
    ):
        await client._post_json_unlocked(
            "data/Login.json",
            fields,
            authenticated=True,
            referer=None,
            ensure_auth=False,
            resolve_http_token=False,
        )
    wire.assert_not_awaited()


async def test_only_exact_owned_logout_bypasses_revoked_authorization() -> None:
    client = _client()
    key = b"z" * 16
    client._session_cleanup_key = key
    with (
        private_authorization(_denied),
        patch.object(client, "_get_http_token_unlocked", AsyncMock(return_value="123")),
        patch.object(
            client,
            "_request_text_unlocked",
            AsyncMock(return_value='{"logout":"success"}'),
        ) as wire,
        patch("custom_components.speedport_smart.api.client._LOGOUT_SETTLE_SECONDS", 0),
    ):
        await client._logout_unlocked(require_confirmation=True)
    wire.assert_awaited_once()
    assert client._session_cleanup_key is None

    for fields, request_key in (
        ({"logout": "byby"}, None),
        ({"logout": "byby", "new_password": "x"}, key),
    ):
        client._session_cleanup_key = key
        with private_authorization(_denied), pytest.raises(PrivateAuthorizationError):
            await client._post_json_unlocked(
                "data/Login.json",
                fields,
                authenticated=False,
                referer=None,
                ensure_auth=False,
                request_key=request_key,
            )


async def test_unscoped_native_json_write_keeps_existing_behavior() -> None:
    client = _client()
    with patch.object(
        client, "_request_text_unlocked", AsyncMock(return_value='{"status":"ok"}')
    ) as wire:
        assert await client._post_json_unlocked(
            "data/Energy.json",
            {"led": "1"},
            authenticated=True,
            referer=None,
            ensure_auth=False,
        ) == {"status": "ok"}
    wire.assert_awaited_once()
