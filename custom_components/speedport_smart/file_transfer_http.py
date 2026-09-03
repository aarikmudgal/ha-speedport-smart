"""Administrator-only bounded binary HTTP transfers, never base64 WebSocket files."""

# Protocol checks deliberately raise inside the same private HTTP error boundary.
# ruff: noqa: TRY301

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any, Final, cast

from aiohttp import BodyPartReader, MultipartReader, web
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID, KEY_HASS_USER
from homeassistant.components.http.decorators import require_admin
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.http import HomeAssistantView

from .const import DOMAIN
from .file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
    transfer_download_filename,
)
from .file_transfer_io import async_execute_file_transfer
from .file_transfer_session import FileTransferSession

if TYPE_CHECKING:
    from aiohttp import StreamReader
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub

_RUNTIME: Final = f"{DOMAIN}_file_transfer_views"
_PREFIX: Final = f"/api/{DOMAIN}/file_transfer/{{entry_id}}"
_JSON_LIMIT: Final = 4096
_BODY_OVERHEAD: Final = 16 * 1024
_CHUNK: Final = 64 * 1024
_TIMEOUT: Final = 120
_BAD_REQUEST: Final = 400
_BUSY: Final = 503
_MAX_BODY: Final = (
    max(item.maximum_bytes for item in FILE_TRANSFER_CONTRACTS.values())
    + _BODY_OVERHEAD
)
_PRIVATE_HEADERS: Final = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class _BoundedStream:
    """Bound raw multipart bytes and framing, including chunked hostile headers."""

    def __init__(self, stream: StreamReader) -> None:
        self.stream = stream
        self.total = 0
        self.framing = 0
        self.maximum = _MAX_BODY

    def _account(self, data: bytes) -> bytes:
        self.total += len(data)
        if self.total > self.maximum:
            raise FileTransferError("invalid_transfer_file")
        return data

    def limit(self, maximum: int) -> None:
        self.maximum = maximum
        if self.total > maximum:
            raise FileTransferError("invalid_transfer_file")

    async def read(self, size: int = -1) -> bytes:
        bounded = min(size, _CHUNK) if size >= 0 else _CHUNK
        return self._account(await self.stream.read(bounded))

    async def readline(self, *, max_line_length: int | None = None) -> bytes:
        # New aiohttp multipart readers pass a per-header limit. Enforce it here
        # without forwarding a keyword unsupported by older StreamReader versions.
        data = await self.stream.readline()
        self.framing += len(data)
        if self.framing > _BODY_OVERHEAD or (
            max_line_length is not None and len(data) > max_line_length
        ):
            raise FileTransferError("invalid_transfer_file")
        return self._account(data)

    def unread_data(self, data: bytes) -> None:
        self.total -= len(data)
        self.stream.unread_data(data)

    def at_eof(self) -> bool:
        return self.stream.at_eof()


def _bounded_multipart_reader(
    request: web.Request,
) -> tuple[MultipartReader, _BoundedStream]:
    stream = _BoundedStream(request.content)
    return MultipartReader(request.headers, cast("StreamReader", stream)), stream


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FileTransferError
        result[key] = value
    return result


def _json(data: bytes | bytearray) -> dict[str, Any]:
    try:
        result = json.loads(data, object_pairs_hook=_object)
    except (ValueError, UnicodeError):
        raise FileTransferError from None
    if type(result) is not dict:
        raise FileTransferError
    return result


async def _small_body(request: web.Request) -> dict[str, Any]:
    if request.content_type != "application/json" or request.headers.get(
        "Content-Encoding"
    ):
        raise FileTransferError
    data = bytearray()
    try:
        while chunk := await request.content.read(_JSON_LIMIT + 1):
            if len(data) + len(chunk) > _JSON_LIMIT:
                raise FileTransferError
            data.extend(chunk)
        return _json(data)
    finally:
        data.clear()


async def _part_bytes(part: BodyPartReader, limit: int) -> bytearray:
    if part.headers.get("Content-Encoding") or part.headers.get(
        "Content-Transfer-Encoding"
    ):
        raise FileTransferError
    data = bytearray()
    try:
        while chunk := await part.read_chunk(_CHUNK):
            if len(data) + len(chunk) > limit:
                raise FileTransferError("invalid_transfer_file")
            data.extend(chunk)
    except BaseException:
        data.clear()
        raise
    else:
        return data


class _TransferView(HomeAssistantView):
    requires_auth = True

    def __init__(self, hass: HomeAssistant, memory_lock: asyncio.Lock) -> None:
        self.hass = hass
        self.memory_lock = memory_lock

    def _hub(self, entry_id: str) -> SpeedportHub:
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise FileTransferError("transfer_unavailable")
        hub = getattr(entry, "runtime_data", None)
        if hub is None or not isinstance(
            getattr(hub, "file_transfer_session", None), FileTransferSession
        ):
            raise FileTransferError("transfer_unavailable")
        return cast("SpeedportHub", hub)

    def _requester(self, request: web.Request) -> tuple[str, str]:
        user = request.get(KEY_HASS_USER)
        refresh_id = request.get(KEY_HASS_REFRESH_TOKEN_ID)
        user_id = getattr(user, "id", None)
        if type(user_id) is not str or type(refresh_id) is not str:
            raise FileTransferError("transfer_unavailable")
        token = self.hass.auth.async_get_refresh_token(refresh_id)
        if (
            token is None
            or token.user.id != user_id
            or not token.user.is_active
            or not token.user.is_admin
        ):
            raise FileTransferError("transfer_unavailable")
        return user_id, refresh_id

    def _error(self, error: FileTransferError) -> web.Response:
        status = _BUSY if error.code == "transfer_busy" else _BAD_REQUEST
        return self.json({"error": error.code}, status, headers=_PRIVATE_HEADERS)


class FileTransferPrepareView(_TransferView):
    """Bind a reviewed action and file digest to a single-use in-memory grant."""

    url = _PREFIX + "/prepare"
    name = f"api:{DOMAIN}:file_transfer:prepare"

    @require_admin
    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Issue only exact, explicitly confirmed transfers for a loaded router."""
        try:
            requester = self._requester(request)
            hub = self._hub(entry_id)
            async with asyncio.timeout(_TIMEOUT):
                data = await _small_body(request)
            if set(data) != {
                "action",
                "size",
                "sha256",
                "confirmed",
                "confirmation_text",
            }:
                raise FileTransferError
            action = data["action"]
            if type(action) is not str or action not in FILE_TRANSFER_CONTRACTS:
                raise FileTransferError
            if self._hub(entry_id) is not hub or self._requester(request) != requester:
                raise FileTransferError("transfer_unavailable")
            hub._check_settings_access(  # noqa: SLF001
                write=FILE_TRANSFER_CONTRACTS[action].file_field is not None
            )
            result = hub.file_transfer_session.prepare(
                action,
                requester=requester,
                entry_id=entry_id,
                size=data["size"],
                sha256=data["sha256"],
                confirmed=data["confirmed"],
                confirmation_text=data["confirmation_text"],
            )
            return self.json(result, headers=_PRIVATE_HEADERS)
        except FileTransferError as error:
            return self._error(error)
        except Exception:  # noqa: BLE001 - Never expose private transport/parser errors.
            return self._error(FileTransferError())


class FileTransferExecuteView(_TransferView):
    """Consume one grant, read one bounded multipart upload, then send once."""

    url = _PREFIX + "/execute"
    name = f"api:{DOMAIN}:file_transfer:execute"

    @require_admin
    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Keep all file bytes in memory and clear them on every completion path."""
        upload = bytearray()
        metadata: dict[str, Any] = {}
        try:
            requester = self._requester(request)
            hub = self._hub(entry_id)
            if self.memory_lock.locked():
                raise FileTransferError("transfer_busy")
            async with self.memory_lock, asyncio.timeout(_TIMEOUT):
                if request.content_type != "multipart/form-data" or request.headers.get(
                    "Content-Encoding"
                ):
                    raise FileTransferError
                if (
                    request.content_length is not None
                    and request.content_length > _MAX_BODY
                ):
                    raise FileTransferError("invalid_transfer_file")
                reader, bounded = _bounded_multipart_reader(request)
                part = await reader.next()
                if (
                    not isinstance(part, BodyPartReader)
                    or part.name != "metadata"
                    or part.filename is not None
                ):
                    raise FileTransferError
                encoded = await _part_bytes(part, _JSON_LIMIT)
                try:
                    metadata = _json(encoded)
                finally:
                    encoded.clear()
                if (
                    not {"action", "grant"}
                    <= set(metadata)
                    <= {"action", "grant", "password"}
                ):
                    raise FileTransferError
                grant = hub.file_transfer_session.consume(
                    metadata["grant"],
                    action=metadata["action"],
                    requester=requester,
                    entry_id=entry_id,
                )
                bounded.limit(grant.size + _BODY_OVERHEAD)
                if (
                    request.content_length is not None
                    and request.content_length > grant.size + _BODY_OVERHEAD
                ):
                    raise FileTransferError("invalid_transfer_file")
                contract = FILE_TRANSFER_CONTRACTS[grant.action]
                part = await reader.next()
                filename = None
                if contract.file_field is None:
                    if part is not None:
                        raise FileTransferError("invalid_transfer_file")
                else:
                    if (
                        not isinstance(part, BodyPartReader)
                        or part.name != "file"
                        or part.filename is None
                    ):
                        raise FileTransferError("invalid_transfer_file")
                    filename = part.filename
                    upload = await _part_bytes(part, grant.size)
                    if (
                        len(upload) != grant.size
                        or not hmac.compare_digest(
                            hashlib.sha256(upload).hexdigest(), grant.sha256 or ""
                        )
                        or await reader.next() is not None
                    ):
                        raise FileTransferError("invalid_transfer_file")

                def check_requester() -> None:
                    if (
                        self._hub(entry_id) is not hub
                        or self._requester(request) != requester
                    ):
                        raise FileTransferError("transfer_unavailable")

                check_requester()
                result = await async_execute_file_transfer(
                    hub,
                    grant,
                    password=metadata.get("password", ""),
                    filename=filename,
                    upload=upload,
                    check_requester=check_requester,
                )
                check_requester()
                if result.download is not None:
                    download_name = transfer_download_filename(grant.action)
                    return web.Response(
                        body=result.download,
                        content_type="application/octet-stream",
                        headers={
                            **_PRIVATE_HEADERS,
                            "Content-Disposition": (
                                f'attachment; filename="{download_name}"'
                            ),
                        },
                    )
                return self.json(
                    {"action": grant.action, "result": result.result},
                    headers=_PRIVATE_HEADERS,
                )
        except FileTransferError as error:
            return self._error(error)
        except Exception:  # noqa: BLE001 - Never expose private transport/parser errors.
            return self._error(FileTransferError())
        finally:
            upload.clear()
            metadata.clear()


def async_register_file_transfer_views(hass: HomeAssistant) -> None:
    """Register once, sharing one process-wide in-memory transfer slot."""
    if _RUNTIME in hass.data:
        return
    lock = asyncio.Lock()
    hass.data[_RUNTIME] = lock
    hass.http.register_view(FileTransferPrepareView(hass, lock))
    hass.http.register_view(FileTransferExecuteView(hass, lock))
