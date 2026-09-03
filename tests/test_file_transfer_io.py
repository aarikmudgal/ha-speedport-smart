"""Mock-only native file I/O: exact fields, fresh gates, no replay and cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.api.codec import encode_payload
from custom_components.speedport_smart.file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
)
from custom_components.speedport_smart.file_transfer_io import (
    _native_request,
    async_execute_file_transfer,
)
from custom_components.speedport_smart.file_transfer_session import FileTransferSession
from custom_components.speedport_smart.private_authorization import (
    check_private_authorization,
)

_STATUS = {
    "device_name": "Speedport Smart 4R Typ A",
    "firmware_version": "010152.5.0.001.0",
}


def _setup(
    action: str, *, location_status: str = "ok", cleanup: bool = True
) -> tuple[Any, Any, Any]:
    contract = FILE_TRANSFER_CONTRACTS[action]
    session = MagicMock()
    response = MagicMock()
    response.status = 302
    response.headers = {"Location": f"/{contract.referer}?status={location_status}"}
    session.request.return_value.__aenter__.return_value = response
    client = SpeedportClient(session, "speedport.ip")
    preflight: dict[str, Any] = {"router_state": "OK"}
    if action == "system_mesh_firmware_upload":
        preflight["addmeshdevice"] = [{"mesh_connected": "1", "mesh_upd_local": "0"}]
    client._get_json_unlocked = AsyncMock(side_effect=[_STATUS, preflight])  # noqa: SLF001
    client._ensure_authenticated_unlocked = AsyncMock()  # noqa: SLF001
    client._get_http_token_unlocked = AsyncMock(return_value="12345678")  # noqa: SLF001
    if contract.phonebook_id is not None:
        client._phonebook_transfer_inventory = AsyncMock(  # noqa: SLF001
            return_value={
                "content": {
                    "phonebook_id": contract.phonebook_id,
                    "prefix": "",
                    "entries": [{"contact_id": "1", "first_name": "Fixture"}],
                    "total": 1,
                    "free_entries": 999,
                    "truncated": False,
                },
                "books": {
                    "addonlbuchentry": [
                        {
                            "id": "b",
                            "onlbuch_nr": str(contract.phonebook_id),
                            "onlbuch_name": "Book",
                            "onlbuch_bname": "",
                            "onlbuch_sync": "0",
                        }
                    ]
                },
            }
        )
    grants = FileTransferSession(clock=lambda: 100.0)
    size = 4 if contract.file_field else 0
    issued = grants.prepare(
        action,
        requester=("user-a", "login-a"),
        entry_id="entry-a",
        size=size,
        sha256=hashlib.sha256(b"file").hexdigest() if size else None,
        confirmed=True,
        confirmation_text=contract.confirmation,
    )
    grant = grants.consume(
        issued["grant"],
        action=action,
        requester=("user-a", "login-a"),
        entry_id="entry-a",
    )
    hub = SimpleNamespace(
        client=client,
        file_transfer_session=grants,
        _operation_lock=asyncio.Lock(),
        _check_settings_access=MagicMock(),
        _async_cleanup_admin_session=AsyncMock(return_value=cleanup),
        invalidate_file_transfer_state=MagicMock(side_effect=grants.clear),
    )
    return hub, grant, response


def _arguments(grant: Any) -> dict[str, Any]:
    upload = FILE_TRANSFER_CONTRACTS[grant.action].file_field is not None
    return {
        "password": "",
        "filename": "private-file.bin" if upload else None,
        "upload": bytearray(b"file") if upload else bytearray(),
        "check_requester": lambda: None,
    }


@pytest.mark.parametrize(
    "action",
    [key for key, value in FILE_TRANSFER_CONTRACTS.items() if value.file_field],
)
async def test_upload_exact_one_native_request_no_token_or_ccm(action: str) -> None:
    """Fresh Status/page/preflight reads precede one multipart POST under both locks."""
    hub, grant, response = _setup(action)
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    request = hub.client._session.request  # noqa: SLF001
    assert request.call_count == 1
    args, kwargs = request.call_args
    assert args == (
        "POST",
        f"http://speedport.ip/{FILE_TRANSFER_CONTRACTS[action].endpoint}",
    )
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Referer"].endswith(
        FILE_TRANSFER_CONTRACTS[action].referer
    )
    payload = kwargs["data"]()
    writer = SimpleNamespace(write=AsyncMock())
    await payload.write(writer)
    transmitted = b"".join(bytes(call.args[0]) for call in writer.write.await_args_list)
    assert (
        b'name="' + FILE_TRANSFER_CONTRACTS[action].file_field.encode() + b'"'
        in transmitted
    )
    assert b"file" in transmitted
    assert b"_tn" not in transmitted
    assert b"httoken" not in transmitted
    assert (
        b"restore_pwd" in transmitted
        if action == "system_backup_restore"
        else b"restore_pwd" not in transmitted
    )
    response.text.assert_not_called()
    assert result.download is None
    assert result.result["status"] != "verified"
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_called_once()
    assert not hub._operation_lock.locked()  # noqa: SLF001
    assert not hub.client._lock.locked()  # noqa: SLF001


@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE"), RuntimeError("PRIVATE")])
async def test_post_failure_is_unknown_once_and_clears_protected_state(
    failure: Exception,
) -> None:
    """Transport ambiguity cannot retry a POST or leak exception detail."""
    hub, grant, _ = _setup("system_backup_restore")
    hub.client._session.request.side_effect = failure  # noqa: SLF001
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == "outcome_unknown"
    assert "PRIVATE" not in repr(result)
    assert hub.client._session.request.call_count == 1  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_called_once()
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_digest_mismatch_never_touches_router() -> None:
    """Even a direct internal caller cannot bypass the approved byte digest."""
    hub, grant, _ = _setup("system_backup_restore")
    with pytest.raises(FileTransferError, match="invalid_transfer_file"):
        await async_execute_file_transfer(
            hub, grant, **{**_arguments(grant), "upload": bytearray(b"evil")}
        )
    hub.client._get_json_unlocked.assert_not_awaited()  # noqa: SLF001
    hub.client._session.request.assert_not_called()  # noqa: SLF001


async def test_fresh_firmware_gate_rejects_before_login_or_upload() -> None:
    """Cached hub identity does not authorize a newly changed firmware revision."""
    hub, grant, _ = _setup("system_backup_restore")
    hub.client._get_json_unlocked.side_effect = [  # noqa: SLF001
        {**_STATUS, "firmware_version": "other"}
    ]
    with pytest.raises(FileTransferError):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub.client._ensure_authenticated_unlocked.assert_not_awaited()  # noqa: SLF001
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_revocation_during_preflight_blocks_native_request() -> None:
    """The HA user/login is checked after all awaits immediately before sending."""
    hub, grant, _ = _setup("system_backup_restore")

    revoked = MagicMock(side_effect=[None, FileTransferError("transfer_unavailable")])

    with pytest.raises(FileTransferError):
        await async_execute_file_transfer(
            hub, grant, **{**_arguments(grant), "check_requester": revoked}
        )
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    assert revoked.call_count == 2
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_final_multipart_revocation_blocks_send_but_allows_cleanup() -> None:
    """The file transaction carries its checker through to the direct native send."""
    hub, grant, _ = _setup("system_backup_restore")
    active = True

    def authorize() -> None:
        if not active:
            raise FileTransferError("transfer_unavailable")

    async def delayed_native(*args: Any, **kwargs: Any) -> Any:
        nonlocal active
        active = False
        return await _native_request(*args, **kwargs)

    with patch(
        "custom_components.speedport_smart.file_transfer_io._native_request",
        side_effect=delayed_native,
    ):
        result = await async_execute_file_transfer(
            hub, grant, **{**_arguments(grant), "check_requester": authorize}
        )
    assert result.result["status"] == "outcome_unknown"
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    check_private_authorization()  # The completed request cannot poison later work.


async def test_router_validation_reads_do_not_replay_upload() -> None:
    """Known wait status triggers bounded read-only checks, not a second upload."""
    hub, grant, _ = _setup("system_firmware_upload", location_status="wait")
    hub.client._get_json_unlocked.side_effect = [  # noqa: SLF001
        _STATUS,
        {"router_state": "OK"},
        {"firmware_status": "wait"},
        {"firmware_status": "ok"},
    ]
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == "reconnect_required"
    assert hub.client._session.request.call_count == 1  # noqa: SLF001
    reads = hub.client._get_json_unlocked.await_args_list  # noqa: SLF001
    assert len(reads) == 4
    assert "FirmwareUpdateCheck.json?_tn=" in reads[-1].args[0]


async def test_definite_rejection_does_not_claim_recovery_or_invalidate() -> None:
    """A known wrong-file reply is a rejection, not a successful installation."""
    hub, grant, _ = _setup("system_firmware_upload", location_status="wrongfile")
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result == {"status": "rejected", "retry_safe": False}
    hub.invalidate_file_transfer_state.assert_not_called()


async def _chunks(values: list[bytes]) -> AsyncIterator[bytes]:
    for value in values:
        yield value


@pytest.mark.parametrize("cleanup", [True, False])
async def test_backup_private_attachment_requires_cleanup_before_release(
    *,
    cleanup: bool,
) -> None:
    """Download passwords remain backend-only and cleanup failure withholds the file."""
    hub, grant, response = _setup("system_backup_download", cleanup=cleanup)
    response.status = 200
    response.headers = {"Content-Disposition": 'attachment; filename="PRIVATE.bin"'}
    response.content_type = "application/octet-stream"
    response.content_length = 4
    response.content.iter_chunked.return_value = _chunks([b"BACK"])
    result = await async_execute_file_transfer(
        hub, grant, **{**_arguments(grant), "password": "private-passphrase"}
    )
    args, _ = hub.client._session.request.call_args  # noqa: SLF001
    assert args == (
        "GET",
        "http://speedport.ip/data/Backup.json?_tn=12345678&save_pwd=private-passphrase",
    )
    assert "private-passphrase" not in repr(result)
    assert "PRIVATE" not in repr(result)
    assert result.download == (b"BACK" if cleanup else None)
    assert result.result["status"] == ("downloaded" if cleanup else "outcome_unknown")
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"content_type": "text/html"},
        {"headers": {}},
        {"content_length": 6_291_457},
        {"status": 302},
        {"content_length": 3},
    ],
)
async def test_backup_rejects_html_redirects_missing_attachment_and_bounds(
    overrides: dict[str, Any],
) -> None:
    """A successful HTTP connection never turns an error document into a backup."""
    hub, grant, response = _setup("system_backup_download")
    response.status = 200
    response.headers = {"Content-Disposition": "attachment"}
    response.content_type = "application/octet-stream"
    response.content_length = 4
    response.content.iter_chunked.return_value = _chunks([b"BACK"])
    for key, value in overrides.items():
        setattr(response, key, value)
    with pytest.raises(FileTransferError):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_cancelled_upload_invalidates_and_cleans_without_retry() -> None:
    """Client cancellation does not make a sent mutation safe to replay."""
    hub, grant, _ = _setup("system_backup_restore")
    hub.client._session.request.side_effect = asyncio.CancelledError()  # noqa: SLF001
    with pytest.raises(asyncio.CancelledError):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub.invalidate_file_transfer_state.assert_called_once()
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_post_send_callback_failure_still_cleans_and_stays_unknown() -> None:
    """Publication failures cannot skip cleanup or imply router rejection."""
    hub, grant, _ = _setup("system_backup_restore")
    hub.invalidate_file_transfer_state.side_effect = RuntimeError("PRIVATE")
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == "outcome_unknown"
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_post_send_cleanup_exception_withholds_positive_acknowledgement() -> None:
    """Unexpected cleanup exceptions have the same safe boundary as negative cleanup."""
    hub, grant, _ = _setup("system_backup_restore")
    hub._async_cleanup_admin_session.side_effect = RuntimeError("PRIVATE")  # noqa: SLF001
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result == {
        "status": "outcome_unknown",
        "verification": "session_cleanup_failed",
        "retry_safe": False,
    }


@pytest.mark.parametrize("book", range(6))
async def test_phonebook_export_fixed_index_and_private_csv(book: int) -> None:
    """Only one exact export GET follows a complete target-bound private search."""
    hub, grant, response = _setup(f"phonebook_export_{book}")
    response.status = 200
    response.headers = {"Content-Disposition": 'attachment; filename="PRIVATE.csv"'}
    response.content_type = "text/csv"
    response.content_length = 4
    response.content.iter_chunked.return_value = _chunks([b"CSV\n"])
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.download == b"CSV\n"
    assert hub.client._session.request.call_args.args == (  # noqa: SLF001
        "GET",
        f"http://speedport.ip/data/PhoneBookExport.json?sel_idx={book}",
    )
    hub.client._phonebook_transfer_inventory.assert_awaited_once_with(book)  # noqa: SLF001
    hub.client._get_http_token_unlocked.assert_not_awaited()  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    assert "PRIVATE" not in repr(result)


async def test_empty_book_export_never_requests_native_export() -> None:
    """Avoid the router's known HTTP500 on empty local book export."""
    hub, grant, _ = _setup("phonebook_export_0")
    inventory = hub.client._phonebook_transfer_inventory.return_value["content"]  # noqa: SLF001
    inventory.update(entries=[], total=0)
    with pytest.raises(FileTransferError, match="phonebook_empty"):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE"), asyncio.CancelledError()])
async def test_book_query_failure_never_sends_file_and_cleans(
    failure: BaseException,
) -> None:
    """Cancellation or private query failure cannot bypass target proof or cleanup."""
    hub, grant, _ = _setup("phonebook_import_0")
    hub.client._phonebook_transfer_inventory.side_effect = failure  # noqa: SLF001
    expected = (
        asyncio.CancelledError
        if isinstance(failure, asyncio.CancelledError)
        else FileTransferError
    )
    with pytest.raises(expected):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("status", ["0", "3", "8"])
async def test_phonebook_import_decodes_native_ccm_and_invalidates_even_rejection(
    status: str,
) -> None:
    """One file POST yields bounded metadata only; rejection can still be partial."""
    hub, grant, response = _setup("phonebook_import_2")
    encoded = encode_payload(
        json.dumps(
            {"status": status, "totalNum": "3", "ignoreNum": "1", "fullNum": "0"}
        )
    ).encode()
    response.status = 200
    response.content_length = len(encoded)
    response.content.iter_chunked.return_value = _chunks([encoded])
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == (
        "import_accepted" if status == "0" else "rejected"
    )
    assert result.result["reported_total"] == 3
    assert result.result["reported_ignored"] == 1
    assert result.result["retry_safe"] is False
    assert hub.client._session.request.call_count == 1  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_called_once()
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("body", [b"PRIVATE malformed", b"x" * 65537])
async def test_phonebook_import_corrupt_or_oversized_ack_unknown_without_replay(
    body: bytes,
) -> None:
    """An import was attempted; parse/limit failure cannot turn it into safe retry."""
    hub, grant, response = _setup("phonebook_import_0")
    response.status = 200
    response.content_length = None
    response.content.iter_chunked.return_value = _chunks([body])
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == "outcome_unknown"
    assert "PRIVATE" not in repr(result)
    assert hub.client._session.request.call_count == 1  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


async def test_phonebook_import_cleanup_failure_withholds_acceptance() -> None:
    """Positive JSON status cannot bypass existing session cleanup policy."""
    hub, grant, response = _setup("phonebook_import_1", cleanup=False)
    encoded = encode_payload('{"status":"0","totalNum":"1","ignoreNum":"0"}').encode()
    response.status = 200
    response.content_length = len(encoded)
    response.content.iter_chunked.return_value = _chunks([encoded])
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert result.result["status"] == "outcome_unknown"
    assert result.result["verification"] == "session_cleanup_failed"


@pytest.mark.parametrize(
    "content_type", ["text/html", "application/json", "text/plain"]
)
async def test_phonebook_export_never_relabels_error_document_as_csv(
    content_type: str,
) -> None:
    """A CSV extension is not proof of a bounded native CSV attachment."""
    hub, grant, response = _setup("phonebook_export_0")
    response.status = 200
    response.headers = {"Content-Disposition": "attachment"}
    response.content_type = content_type
    response.content_length = 4
    response.content.iter_chunked.return_value = _chunks([b"text"])
    with pytest.raises(FileTransferError, match="transfer_download_failed"):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("cleanup", [True, False])
async def test_system_log_download_is_one_fixed_get_without_filter_post(
    *, cleanup: bool
) -> None:
    """Private native log attachment has no filter mutation or password query."""
    hub, grant, response = _setup("system_log_download", cleanup=cleanup)
    data = b"[2026-01-01 12:00:00] PRIVATE device connected\n"
    response.status = 200
    response.headers = {"Content-Disposition": 'attachment; filename="PRIVATE.log"'}
    response.content_type = "text/plain"
    response.content_length = len(data)
    response.content.iter_chunked.return_value = _chunks([data])
    result = await async_execute_file_transfer(hub, grant, **_arguments(grant))
    request = hub.client._session.request  # noqa: SLF001
    request.assert_called_once()
    assert request.call_args.args == ("GET", "http://speedport.ip/data/Syslog.json")
    assert "data" not in request.call_args.kwargs
    hub.client._get_http_token_unlocked.assert_not_awaited()  # noqa: SLF001
    assert hub.client._get_json_unlocked.await_count == 1  # noqa: SLF001
    assert result.download == (data if cleanup else None)
    assert result.result["status"] == ("downloaded" if cleanup else "outcome_unknown")
    assert "PRIVATE" not in repr(result)
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_not_called()


@pytest.mark.parametrize(
    "body", [b"<html>PRIVATE</html>", b'{"error":"PRIVATE"}', b"binary\x00log", b"\xff"]
)
async def test_system_log_rejects_error_documents_and_binary(body: bytes) -> None:
    """A text attachment must still be text, not a relabelled router error."""
    hub, grant, response = _setup("system_log_download")
    response.status = 200
    response.headers = {"Content-Disposition": "attachment"}
    response.content_type = "text/plain"
    response.content_length = len(body)
    response.content.iter_chunked.return_value = _chunks([body])
    with pytest.raises(FileTransferError, match="transfer_download_failed"):
        await async_execute_file_transfer(hub, grant, **_arguments(grant))
    assert hub.client._session.request.call_count == 1  # noqa: SLF001
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001


@pytest.mark.parametrize("cleanup", [True, False])
async def test_router_pass_reads_fields_and_generates_locally_without_password_request(
    *, cleanup: bool
) -> None:
    """The optional print password is never sent to any router endpoint."""
    hub, grant, _ = _setup("system_router_pass_download", cleanup=cleanup)
    hub.client._get_json_unlocked.side_effect = [  # noqa: SLF001
        _STATUS,
        {
            "serial_number": "PRIVATE-SERIAL",
            "wlan_ssid": "PRIVATE-SSID",
            "wlan_5ghz_ssid": "PRIVATE-5G",
            "wlan_visible": "1",
            "wlan_5ghz_visible": "0",
            "wlan_enc": "4",
            "wlan_wpa_key": "PRIVATE-WIFI",
        },
    ]
    result = await async_execute_file_transfer(
        hub, grant, **{**_arguments(grant), "password": "PRIVATE-ADMIN"}
    )
    reads = hub.client._get_json_unlocked.await_args_list  # noqa: SLF001
    assert len(reads) == 2
    assert reads[-1].args == ("data/WLANBasicAss.json",)
    assert reads[-1].kwargs == {
        "authenticated": True,
        "referer": "html/login/index.html",
    }
    assert "PRIVATE" not in repr(reads)
    hub.client._session.request.assert_not_called()  # noqa: SLF001
    hub.client._get_http_token_unlocked.assert_not_awaited()  # noqa: SLF001
    assert "PRIVATE" not in repr(result)
    if cleanup:
        assert result.download is not None
        assert b"PRIVATE-WIFI" in result.download
        assert b"PRIVATE-ADMIN" in result.download
    else:
        assert result.download is None
    hub._async_cleanup_admin_session.assert_awaited_once()  # noqa: SLF001
    hub.invalidate_file_transfer_state.assert_not_called()
