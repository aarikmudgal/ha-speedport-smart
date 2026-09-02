"""Offline administrator HTTP transfer boundaries and bounded multipart parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import BodyPartReader, StreamReader
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID, KEY_HASS_USER
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized

from custom_components.speedport_smart.file_transfer import (
    FILE_TRANSFER_CONTRACTS,
)
from custom_components.speedport_smart.file_transfer_http import (
    FileTransferExecuteView,
    FileTransferPrepareView,
    _bounded_multipart_reader,
    _BoundedStream,
    async_register_file_transfer_views,
)
from custom_components.speedport_smart.file_transfer_io import FileTransferResult
from custom_components.speedport_smart.file_transfer_session import FileTransferSession

_ACTION = "system_backup_restore"


@pytest.fixture(autouse=True)
def _mock_multipart_reader() -> Iterator[None]:
    """Keep parser-unit scenarios independent from aiohttp stream construction."""
    with patch(
        "custom_components.speedport_smart.file_transfer_http._bounded_multipart_reader",
        side_effect=lambda request: (request.multipart.return_value, MagicMock()),
    ):
        yield


class _Request(dict):
    def __init__(
        self, user: Any, *, body: bytes = b"", parts: list[Any] | None = None
    ) -> None:
        super().__init__({KEY_HASS_USER: user, KEY_HASS_REFRESH_TOKEN_ID: "login-a"})
        self.headers = {}
        self.content_length = None
        self.content_type = (
            "multipart/form-data" if parts is not None else "application/json"
        )
        self.content = SimpleNamespace(read=AsyncMock(side_effect=[body, b""]))
        self.multipart = AsyncMock(
            return_value=SimpleNamespace(
                next=AsyncMock(side_effect=[*(parts or []), None])
            )
        )


def _context() -> tuple[Any, Any, Any]:
    user = SimpleNamespace(id="user-a", is_admin=True, is_active=True)
    hub = SimpleNamespace(
        file_transfer_session=FileTransferSession(), _check_settings_access=MagicMock()
    )
    entry = SimpleNamespace(
        domain="speedport_smart", state=ConfigEntryState.LOADED, runtime_data=hub
    )
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(register_view=MagicMock()),
        auth=SimpleNamespace(
            async_get_refresh_token=MagicMock(return_value=SimpleNamespace(user=user))
        ),
        config_entries=SimpleNamespace(async_get_entry=MagicMock(return_value=entry)),
    )
    return hass, hub, user


def _approval(action: str = _ACTION) -> dict[str, Any]:
    size = 4 if FILE_TRANSFER_CONTRACTS[action].file_field else 0
    return {
        "action": action,
        "size": size,
        "sha256": hashlib.sha256(b"file").hexdigest() if size else None,
        "confirmed": True,
        "confirmation_text": FILE_TRANSFER_CONTRACTS[action].confirmation,
    }


def _grant(hub: Any, action: str = _ACTION) -> str:
    data = _approval(action)
    return hub.file_transfer_session.prepare(
        **data, requester=("user-a", "login-a"), entry_id="entry-a"
    )["grant"]


def _part(name: str, data: bytes, filename: str | None = None, **headers: str) -> Any:
    part = MagicMock(spec=BodyPartReader)
    part.name = name
    part.filename = filename
    part.headers = headers
    part.read_chunk = AsyncMock(side_effect=[data, b""])
    return part


def _parts(grant: str, *, action: str = _ACTION, file: bytes = b"file") -> list[Any]:
    parts = [
        _part(
            "metadata",
            json.dumps({"action": action, "grant": grant, "password": ""}).encode(),
        )
    ]
    if FILE_TRANSFER_CONTRACTS[action].file_field:
        parts.append(_part("file", file, "private-original.bin"))
    return parts


async def test_prepare_exact_schema_and_server_owned_identity() -> None:
    """The client cannot supply another user's ID or receive file/secret data."""
    hass, hub, user = _context()
    view = FileTransferPrepareView(hass, asyncio.Lock())
    response = await view.post(
        _Request(user, body=json.dumps(_approval()).encode()), "entry-a"
    )
    data = json.loads(response.body)
    assert response.status == 200
    assert set(data) == {"action", "grant", "expires_in"}
    assert response.headers["Cache-Control"] == "no-store, private"
    assert "user-a" not in response.text
    grant = hub.file_transfer_session.consume(
        data["grant"],
        action=_ACTION,
        requester=("user-a", "login-a"),
        entry_id="entry-a",
    )
    assert grant.size == 4


@pytest.mark.parametrize(
    "change",
    [
        {"requester": "other"},
        {"size": True},
        {"confirmed": False},
        {"confirmation_text": "SAVE"},
        {"sha256": None},
        {"action": "http://evil.invalid"},
    ],
)
async def test_prepare_rejects_unreviewed_schema_without_router_io(
    change: dict[str, Any],
) -> None:
    """Only a typed approved action, size and digest can issue an opaque grant."""
    hass, _, user = _context()
    response = await FileTransferPrepareView(hass, asyncio.Lock()).post(
        _Request(user, body=json.dumps({**_approval(), **change}).encode()), "entry-a"
    )
    assert response.status == 400
    assert set(json.loads(response.body)) == {"error"}


async def test_admin_decorator_and_loaded_entry_domain_are_enforced() -> None:
    """HTTP does not widen the existing loaded Speedport administrator boundary."""
    hass, _, user = _context()
    view = FileTransferPrepareView(hass, asyncio.Lock())
    user.is_admin = False
    with pytest.raises(Unauthorized):
        await view.post(_Request(user), "entry-a")
    user.is_admin = True
    entry = hass.config_entries.async_get_entry.return_value
    for field, value in (("domain", "other"), ("state", ConfigEntryState.NOT_LOADED)):
        before = getattr(entry, field)
        setattr(entry, field, value)
        response = await view.post(
            _Request(user, body=json.dumps(_approval()).encode()), "entry-a"
        )
        assert response.status == 400
        setattr(entry, field, before)


async def test_revoked_or_wrong_refresh_identity_rejected() -> None:
    """An admin flag alone does not replace the active HA refresh-token binding."""
    hass, _, user = _context()
    view = FileTransferPrepareView(hass, asyncio.Lock())
    hass.auth.async_get_refresh_token.return_value = None
    assert (await view.post(_Request(user), "entry-a")).status == 400
    hass.auth.async_get_refresh_token.return_value = SimpleNamespace(
        user=SimpleNamespace(id="other", is_admin=True, is_active=True)
    )
    assert (await view.post(_Request(user), "entry-a")).status == 400


async def test_execute_verifies_digest_then_clears_buffer_and_never_reuses_grant() -> (
    None
):
    """Only exact bytes reach the I/O layer, and the owned mutable buffer is cleared."""
    hass, hub, user = _context()
    token = _grant(hub)
    view = FileTransferExecuteView(hass, asyncio.Lock())
    seen: list[bytes] = []

    async def execute(*_args: Any, **kwargs: Any) -> FileTransferResult:
        seen.append(bytes(kwargs["upload"]))
        kwargs["check_requester"]()
        return FileTransferResult({"status": "reconnect_required"})

    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(side_effect=execute),
    ) as call:
        response = await view.post(_Request(user, parts=_parts(token)), "entry-a")
        assert response.status == 200
        assert seen == [b"file"]
        assert call.call_args.kwargs["upload"] == bytearray()
        assert json.loads(response.body)["result"]["status"] == "reconnect_required"
        second = await view.post(_Request(user, parts=_parts(token)), "entry-a")
        assert second.status == 400
        assert call.await_count == 1


@pytest.mark.parametrize(
    "case",
    [
        "digest",
        "oversize",
        "short",
        "extra",
        "duplicate",
        "encoded",
        "nested",
        "metadata_after_file",
    ],
)
async def test_invalid_multipart_never_reaches_any_router_request(case: str) -> None:
    """Malformed, conflicting and compressed upload bodies consume no router I/O."""
    hass, hub, user = _context()
    token = _grant(hub)
    parts = _parts(token)
    if case in {"digest", "oversize", "short"}:
        parts[1] = _part(
            "file",
            {"digest": b"evil", "oversize": b"extra", "short": b"f"}[case],
            "file.bin",
        )
    elif case in {"extra", "duplicate"}:
        parts.append(
            _part("file" if case == "duplicate" else "unknown", b"x", "file.bin")
        )
    elif case == "encoded":
        parts[1].headers = {"Content-Transfer-Encoding": "base64"}
    elif case == "nested":
        parts[1] = SimpleNamespace(name="file")
    else:
        parts.reverse()
    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(),
    ) as call:
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=parts), "entry-a"
        )
        assert response.status == 400
        call.assert_not_awaited()


async def test_huge_and_duplicate_metadata_are_rejected_before_file_read() -> None:
    """A multipart metadata part cannot become an unbounded memory allocation."""
    hass, hub, user = _context()
    token = _grant(hub)
    for data in (b"x" * 4097, b'{"action":"one","action":"two"}'):
        parts = [_part("metadata", data), _part("file", b"file", "file.bin")]
        with patch(
            "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
            AsyncMock(),
        ) as call:
            response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
                _Request(user, parts=parts), "entry-a"
            )
        assert response.status == 400
        parts[1].read_chunk.assert_not_awaited()
        call.assert_not_awaited()
    hub.file_transfer_session.consume(
        token, action=_ACTION, requester=("user-a", "login-a"), entry_id="entry-a"
    )


async def test_download_response_is_binary_private_with_fixed_filename() -> None:
    """Router-supplied names, passwords and headers never enter the browser response."""
    hass, hub, user = _context()
    action = "system_backup_download"
    token = _grant(hub, action)
    result = FileTransferResult({"status": "downloaded"}, b"PRIVATE BACKUP")
    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(return_value=result),
    ):
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=_parts(token, action=action)), "entry-a"
        )
    assert response.body == b"PRIVATE BACKUP"
    assert response.content_type == "application/octet-stream"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="speedport-backup.bin"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize("book", range(6))
async def test_phonebook_download_private_attachment_has_fixed_book_filename(
    book: int,
) -> None:
    """The server owns the finite filename; no router names or CSV enter JSON."""
    hass, hub, user = _context()
    action = f"phonebook_export_{book}"
    token = _grant(hub, action)
    result = FileTransferResult({"status": "downloaded"}, b"PRIVATE CSV")
    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(return_value=result),
    ):
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=_parts(token, action=action)), "entry-a"
        )
    assert response.body == b"PRIVATE CSV"
    assert response.content_type == "application/octet-stream"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="speedport-phonebook-{book + 1}.csv"'
    )
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize(
    ("action", "filename"),
    [
        ("system_log_download", "speedport-system-log.txt"),
        ("system_router_pass_download", "speedport-router-pass.txt"),
    ],
)
async def test_private_text_download_has_fixed_filename_and_no_store(
    action: str, filename: str
) -> None:
    """Generated credentials and native logs never become inline HTML or JSON."""
    hass, hub, user = _context()
    token = _grant(hub, action)
    result = FileTransferResult({"status": "downloaded"}, b"PRIVATE TEXT")
    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(return_value=result),
    ):
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=_parts(token, action=action)), "entry-a"
        )
    assert response.body == b"PRIVATE TEXT"
    assert response.content_type == "application/octet-stream"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="{filename}"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response.headers["Cache-Control"]


async def test_logout_during_download_prevents_private_body_release() -> None:
    """The browser user is checked once more after the asynchronous router exchange."""
    hass, hub, user = _context()
    action = "system_backup_download"
    token = _grant(hub, action)

    async def execute(*_args: Any, **_kwargs: Any) -> FileTransferResult:
        hass.auth.async_get_refresh_token.return_value = None
        return FileTransferResult({"status": "downloaded"}, b"PRIVATE BACKUP")

    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(side_effect=execute),
    ):
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=_parts(token, action=action)), "entry-a"
        )
    assert response.status == 400
    assert b"PRIVATE" not in response.body


async def test_global_memory_slot_blocks_second_transfer_without_reading_body() -> None:
    """All entries share one active in-memory file exchange."""
    hass, hub, user = _context()
    lock = asyncio.Lock()
    token = _grant(hub)
    request = _Request(user, parts=_parts(token))
    async with lock:
        response = await FileTransferExecuteView(hass, lock).post(request, "entry-a")
    assert response.status == 503
    request.multipart.assert_not_awaited()
    hub.file_transfer_session.consume(
        token, action=_ACTION, requester=("user-a", "login-a"), entry_id="entry-a"
    )


async def test_private_exception_text_is_never_returned() -> None:
    """Unexpected errors are reduced to a fixed code, with buffers still cleared."""
    hass, hub, user = _context()
    token = _grant(hub)
    with patch(
        "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
        AsyncMock(side_effect=RuntimeError("PRIVATE password + filename")),
    ) as call:
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            _Request(user, parts=_parts(token)), "entry-a"
        )
    assert response.status == 400
    assert "PRIVATE" not in response.text
    assert call.call_args.kwargs["upload"] == bytearray()


def test_http_views_register_once_and_share_one_memory_slot() -> None:
    """Repeated panel registration does not multiply handlers or upload capacity."""
    hass, _, _ = _context()
    async_register_file_transfer_views(hass)
    async_register_file_transfer_views(hass)
    assert hass.http.register_view.call_count == 2
    views = [call.args[0] for call in hass.http.register_view.call_args_list]
    assert views[0].memory_lock is views[1].memory_lock
    assert all(view.requires_auth for view in views)


async def test_raw_multipart_stream_bounds_chunked_header_framing() -> None:
    """Header lines cannot grow an unbounded list before the metadata part exists."""
    source = SimpleNamespace(
        readline=AsyncMock(return_value=b"header: value\r\n" * 2000)
    )
    stream = _BoundedStream(source)
    with pytest.raises(ValueError, match="invalid_transfer_file"):
        await stream.readline()


async def test_raw_stream_counts_prefetch_but_refunds_boundary_pushback() -> None:
    """A tightened grant limit includes bytes prefetched while parsing metadata."""
    source = SimpleNamespace(
        read=AsyncMock(return_value=b"1234"),
        unread_data=MagicMock(),
        at_eof=lambda: False,
    )
    stream = _BoundedStream(source)
    assert await stream.read(100_000) == b"1234"
    source.read.assert_awaited_once_with(65_536)
    stream.unread_data(b"34")
    stream.limit(2)
    assert stream.at_eof() is False
    with pytest.raises(ValueError, match="invalid_transfer_file"):
        stream.limit(1)


async def test_real_multipart_parser_accepts_browser_form_through_bounded_stream() -> (
    None
):
    """Exercise real aiohttp framing and boundary pushback, not only part mocks."""
    hass, hub, user = _context()
    token = _grant(hub)
    metadata = json.dumps({"action": _ACTION, "grant": token, "password": ""}).encode()
    raw = (
        b'--boundary\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
        + metadata
        + b'\r\n--boundary\r\nContent-Disposition: form-data; name="file"; '
        b'filename="fixture.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'
        b"file\r\n--boundary--\r\n"
    )
    request = _Request(user, parts=[])
    request.headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
    request.content_length = len(raw)
    request.content = StreamReader(MagicMock(_reading_paused=False), 65_536)
    request.content.feed_data(raw)
    request.content.feed_eof()
    seen: list[bytes] = []

    async def execute(*_args: Any, **kwargs: Any) -> FileTransferResult:
        seen.append(bytes(kwargs["upload"]))
        return FileTransferResult({"status": "outcome_unknown"})

    with (
        patch(
            "custom_components.speedport_smart.file_transfer_http._bounded_multipart_reader",
            side_effect=_bounded_multipart_reader,
        ),
        patch(
            "custom_components.speedport_smart.file_transfer_http.async_execute_file_transfer",
            AsyncMock(side_effect=execute),
        ),
    ):
        response = await FileTransferExecuteView(hass, asyncio.Lock()).post(
            request, "entry-a"
        )
    assert response.status == 200
    assert seen == [b"file"]
