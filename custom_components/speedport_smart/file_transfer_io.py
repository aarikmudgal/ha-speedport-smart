"""Native file requests under the existing hub/client locks, never automatic retries."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode

import aiohttp
from aiohttp.payload import Payload

from .admin_actions import SPEEDPORT_SMART_4R_TYP_A_010152
from .file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
    build_router_pass,
    classify_phonebook_import_response,
    classify_router_firmware_progress,
    classify_upload_response,
    prepare_file_transfer,
    validate_phonebook_transfer_preflight,
    validate_transfer_preflight,
)
from .models import normalize_status
from .private_authorization import check_private_authorization, private_authorization

if TYPE_CHECKING:
    from aiohttp.abc import AbstractStreamWriter

    from .api.client import SpeedportClient
    from .file_transfer import FileTransferContract, FileTransferPlan, TransferOutcome
    from .file_transfer_session import FileTransferGrant
    from .hub import SpeedportHub

_CHUNK: Final = 64 * 1024
_TRANSFER_TIMEOUT: Final = 120
_HTTP_OK: Final = 200
_MAX_TOKEN_LENGTH: Final = 32
_MAX_IMPORT_RESPONSE: Final = 64 * 1024


@dataclass(slots=True)
class FileTransferResult:
    """Only outcome metadata may be JSON encoded; a backup is private binary data."""

    result: dict[str, Any]
    download: bytes | None = field(default=None, repr=False)


class _PrivateUpload(Payload):
    """Send bounded in-memory bytes in chunks without a full second file copy."""

    def __init__(self, data: bytearray) -> None:
        super().__init__(data, content_type="application/octet-stream")
        self._size = len(data)

    async def write(self, writer: AbstractStreamWriter) -> None:
        view = memoryview(self._value)
        try:
            for offset in range(0, len(view), _CHUNK):
                await writer.write(view[offset : offset + _CHUNK])
        finally:
            view.release()

    def decode(self, encoding: str = "utf-8", errors: str = "strict") -> str:  # noqa: ARG002
        return "[private router upload]"


async def _read_backup(
    response: aiohttp.ClientResponse,
    maximum: int,
    *,
    phonebook: bool = False,
    system_log: bool = False,
) -> bytes:
    """Accept only a bounded attachment, never a login/error page as a backup."""
    if (
        response.status != _HTTP_OK
        or response.headers.get("Content-Disposition", "")
        .split(";", 1)[0]
        .strip()
        .lower()
        != "attachment"
        or (
            phonebook
            and response.content_type
            not in {"text/csv", "application/csv", "application/octet-stream"}
        )
        or (
            system_log
            and response.content_type not in {"text/plain", "application/octet-stream"}
        )
        or (
            not phonebook
            and not system_log
            and response.content_type.startswith("text/")
        )
        or response.content_type
        in {"application/json", "application/xml", "application/xhtml+xml"}
        or (
            response.content_length is not None
            and not 0 < response.content_length <= maximum
        )
    ):
        raise FileTransferError("transfer_download_failed")
    data = bytearray()
    try:
        async for chunk in response.content.iter_chunked(_CHUNK):
            if len(data) + len(chunk) > maximum:
                raise FileTransferError("transfer_download_failed")
            data.extend(chunk)
        if (
            not data
            or (
                response.content_length is not None
                and len(data) != response.content_length
            )
            or bytes(data[:256])
            .removeprefix(b"\xef\xbb\xbf")
            .lstrip()
            .lower()
            .startswith((b"<!doctype", b"<html", b"<script", b"<?xml"))
        ):
            raise FileTransferError("transfer_download_failed")
        if system_log:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeError:
                raise FileTransferError("transfer_download_failed") from None
            if any(not char.isprintable() and char not in "\n\r\t" for char in text):
                raise FileTransferError("transfer_download_failed")
            # Native log lines may start with a bracketed timestamp. Reject an
            # actual JSON error document, not ordinary bracketed log text.
            if text.lstrip().startswith(("{", "[")):
                try:
                    json.loads(text)
                except ValueError:
                    pass
                else:
                    raise FileTransferError("transfer_download_failed")
        return bytes(data)
    finally:
        data.clear()


async def _read_import_response(
    client: SpeedportClient, response: aiohttp.ClientResponse
) -> FileTransferResult:
    """Decode one bounded native CCM reply without retaining private router text."""
    from .api.client import _decode_response  # noqa: PLC0415

    if response.status != _HTTP_OK or (
        response.content_length is not None
        and not 0 < response.content_length <= _MAX_IMPORT_RESPONSE
    ):
        return FileTransferResult(_outcome("outcome_unknown"))
    data = bytearray()
    try:
        async for chunk in response.content.iter_chunked(_CHUNK):
            if len(data) + len(chunk) > _MAX_IMPORT_RESPONSE:
                return FileTransferResult(_outcome("outcome_unknown"))
            data.extend(chunk)
        if response.content_length is not None and len(data) != response.content_length:
            return FileTransferResult(_outcome("outcome_unknown"))
        raw = _decode_response(data.decode("utf-8"), client._login_key)  # noqa: SLF001
        return FileTransferResult(classify_phonebook_import_response(raw))
    finally:
        data.clear()


async def _native_request(
    client: SpeedportClient,
    plan: FileTransferPlan,
    upload: bytearray,
    *,
    private_password: object = "",
) -> FileTransferResult:
    """Perform exactly one native request; the caller already holds client lock."""
    base_url = client.configuration_url
    if plan.action == "system_router_pass_download":
        raw = await client._get_json_unlocked(  # noqa: SLF001
            "data/WLANBasicAss.json", authenticated=True, referer=plan.referer
        )
        return FileTransferResult(
            {"status": "downloaded"},
            build_router_pass(raw, router_url=base_url, password=private_password),
        )
    url = f"{base_url}/{plan.endpoint}"
    kwargs: dict[str, Any] = {
        "headers": {"Referer": f"{base_url}/{plan.referer}", "Accept": "*/*"},
        "allow_redirects": False,
        "timeout": aiohttp.ClientTimeout(total=_TRANSFER_TIMEOUT),
    }
    if base_url.startswith("https://") and not client._verify_ssl:  # noqa: SLF001
        kwargs["ssl"] = False
    if plan.file_field is None:
        if plan.parameters:
            url += "?" + urlencode(plan.parameters)
    else:
        form = aiohttp.FormData()
        for name, value in plan.parameters.items():
            form.add_field(name, value)
        form.add_field(plan.file_field, _PrivateUpload(upload), filename=plan.filename)
        kwargs["data"] = form
    check_private_authorization()
    async with client._session.request(plan.method, url, **kwargs) as response:  # noqa: SLF001
        contract = FILE_TRANSFER_CONTRACTS[plan.action]
        if plan.file_field is None:
            return FileTransferResult(
                {"status": "downloaded"},
                await _read_backup(
                    response,
                    contract.maximum_bytes,
                    phonebook=contract.phonebook_id is not None,
                    system_log=plan.action == "system_log_download",
                ),
            )
        if contract.phonebook_id is not None:
            return await _read_import_response(client, response)
        outcome = classify_upload_response(
            plan.action,
            http_status=response.status,
            location=response.headers.get("Location"),
            router_base_url=base_url,
        )
        # Do not read, log or return the redirect/error body.
        return FileTransferResult(_outcome(outcome))


def _outcome(outcome: TransferOutcome) -> dict[str, Any]:
    if outcome == "rejected":
        return {"status": "rejected", "retry_safe": False}
    if outcome == "reconnect_required":
        return {
            "status": "reconnect_required",
            "acknowledged": True,
            "verification": "reconnect_required",
            "retry_safe": False,
        }
    return {
        "status": "outcome_unknown",
        "verification": outcome,
        "retry_safe": False,
    }


async def _fresh_preflight(
    client: SpeedportClient,
    contract: FileTransferContract,
    phonebook_inventory: dict[str, Any] | None = None,
) -> tuple[object, object, str | None]:
    """Recheck public firmware identity plus authenticated page-scoped readiness."""
    status = await client._get_json_unlocked(  # noqa: SLF001
        "data/Status.json", authenticated=False, referer=None
    )
    identity = normalize_status(status).info
    if not SPEEDPORT_SMART_4R_TYP_A_010152.matches(identity.model, identity.firmware):
        raise FileTransferError("unsupported_router")
    await client._ensure_authenticated_unlocked()  # noqa: SLF001
    if contract.id in {"system_log_download", "system_router_pass_download"}:
        return identity.model, identity.firmware, None
    if contract.phonebook_id is not None:
        inventory = phonebook_inventory or {}
        content, books = inventory.get("content"), inventory.get("books")
        if not isinstance(content, dict) or not isinstance(books, dict):
            raise FileTransferError("transfer_preflight_failed")
        validate_phonebook_transfer_preflight(contract.id, content, books=books)
        # Exact export form has only sel_idx; import uses only its indexed file.
        return identity.model, identity.firmware, None
    token = await client._get_http_token_unlocked(contract.referer)  # noqa: SLF001
    if (
        type(token) is not str
        or not token.isascii()
        or not token.isdecimal()
        or len(token) > _MAX_TOKEN_LENGTH
    ):
        raise FileTransferError("transfer_token_unavailable")
    raw = await client._get_json_unlocked(  # noqa: SLF001
        contract.preflight_endpoint + "?" + urlencode({"_tn": token}),
        authenticated=True,
        referer=contract.referer,
        preserve_compounds=True,
    )
    validate_transfer_preflight(contract.id, raw)
    return identity.model, identity.firmware, token


async def async_execute_file_transfer(
    hub: SpeedportHub,
    grant: FileTransferGrant,
    *,
    password: object,
    filename: object,
    upload: bytearray,
    check_requester: Callable[[], None],
) -> FileTransferResult:
    """Bind the HTTP owner's live checker through preflight and native sends."""
    with private_authorization(check_requester):
        return await _async_execute_file_transfer(
            hub,
            grant,
            password=password,
            filename=filename,
            upload=upload,
            check_requester=check_requester,
        )


async def _async_execute_file_transfer(
    hub: SpeedportHub,
    grant: FileTransferGrant,
    *,
    password: object,
    filename: object,
    upload: bytearray,
    check_requester: Callable[[], None],
) -> FileTransferResult:
    """Execute one validated file approval and clean up before returning any backup."""
    contract = FILE_TRANSFER_CONTRACTS[grant.action]
    session = hub.file_transfer_session
    session.check_current(grant)
    if len(upload) != grant.size or (
        contract.file_field is not None
        and not hmac.compare_digest(
            hashlib.sha256(upload).hexdigest(), grant.sha256 or ""
        )
    ):
        raise FileTransferError("invalid_transfer_file")
    result: FileTransferResult | None = None
    attempted = False
    cleaned = False
    async with hub._operation_lock:  # noqa: SLF001
        hub._check_settings_access(write=contract.file_field is not None)  # noqa: SLF001
        session.check_current(grant)
        check_requester()
        try:
            client = hub.client
            inventory = None
            if contract.phonebook_id is not None:
                # This existing strict read-only query owns the client lock. The
                # hub operation lock prevents another integration write between
                # this proof and the one native file request below.
                inventory = await client._phonebook_transfer_inventory(  # noqa: SLF001
                    contract.phonebook_id
                )
            async with client._lock:  # noqa: SLF001
                client._ensure_open()  # noqa: SLF001
                model, firmware, token = await _fresh_preflight(
                    client, contract, inventory
                )
                session.check_current(grant)
                plan = prepare_file_transfer(
                    grant.action,
                    model=model,
                    firmware=firmware,
                    confirmed=True,
                    confirmation_text=grant.confirmation_text,
                    token=token if contract.file_field is None else None,
                    password=password,
                    filename=filename,
                    size=grant.size,
                )
                session.check_current(grant)
                check_requester()
                attempted = True
                result = await _native_request(
                    client,
                    plan,
                    upload,
                    private_password=password
                    if contract.id == "system_router_pass_download"
                    else "",
                )
                if contract.file_field is None:
                    session.check_current(grant)
                    check_requester()
                if (
                    grant.action == "system_firmware_upload"
                    and result.result.get("verification") == "processing"
                ):
                    for delay in (0.0, 0.5, 1.0, 2.0):
                        if delay:
                            await asyncio.sleep(delay)
                        session.check_current(grant)
                        check_requester()
                        raw = await client._get_json_unlocked(  # noqa: SLF001
                            "data/FirmwareUpdateCheck.json?"
                            + urlencode({"_tn": token}),
                            authenticated=True,
                            referer=contract.referer,
                        )
                        outcome = classify_router_firmware_progress(raw)
                        result = FileTransferResult(_outcome(outcome))
                        if outcome != "processing":
                            break
        except asyncio.CancelledError:
            raise
        except FileTransferError:
            if not attempted:
                raise
            if contract.file_field is None:
                raise FileTransferError("transfer_download_failed") from None
            result = FileTransferResult(_outcome("outcome_unknown"))
        except Exception:  # noqa: BLE001 - POST failures must never expose private data.
            if not attempted or contract.file_field is None:
                raise FileTransferError("transfer_unavailable") from None
            result = FileTransferResult(_outcome("outcome_unknown"))
        finally:
            try:
                if (
                    attempted
                    and contract.file_field is not None
                    and (
                        contract.phonebook_id is not None
                        or result is None
                        or result.result.get("status") != "rejected"
                    )
                ):
                    hub.invalidate_file_transfer_state()
            except Exception:  # noqa: BLE001 - A post-send callback failure is unknown.
                result = FileTransferResult(_outcome("outcome_unknown"))
            finally:
                try:
                    cleaned = await hub._async_cleanup_admin_session()  # noqa: SLF001
                except Exception:  # noqa: BLE001 - Withhold success and private files.
                    cleaned = False
    if not cleaned:
        if result is not None:
            result.download = None
        return FileTransferResult(
            {
                "status": "outcome_unknown",
                "verification": "session_cleanup_failed",
                "retry_safe": False,
            }
        )
    if result is None:
        raise FileTransferError("transfer_unavailable")
    return result
