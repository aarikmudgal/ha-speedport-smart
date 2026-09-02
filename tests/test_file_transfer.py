"""Offline proof of exact native backup and firmware transfer contracts."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
    build_router_pass,
    classify_phonebook_import_response,
    classify_router_firmware_progress,
    classify_upload_response,
    prepare_file_transfer,
    validate_phonebook_transfer_preflight,
    validate_transfer_preflight,
    validate_upload_descriptor,
)


def _args(action: str) -> dict[str, Any]:
    contract = FILE_TRANSFER_CONTRACTS[action]
    return {
        "model": "Speedport Smart 4R Typ A",
        "firmware": "010152.5.0.001.0",
        "confirmed": True,
        "confirmation_text": contract.confirmation,
        "token": None
        if contract.file_field
        or contract.phonebook_id is not None
        or action in {"system_log_download", "system_router_pass_download"}
        else "12345678",
        "filename": "private-backup.bin" if contract.file_field else None,
        "size": 4 if contract.file_field else 0,
    }


@pytest.mark.parametrize("action", FILE_TRANSFER_CONTRACTS)
def test_transfer_exact_native_fields_and_private_representation(action: str) -> None:
    """Only backup GET includes _tn; native multipart never invents a JSON token."""
    contract = FILE_TRANSFER_CONTRACTS[action]
    args = _args(action)
    if contract.password_field:
        args["password"] = "private-passphrase"  # noqa: S105
    plan = prepare_file_transfer(action, **args)
    assert plan.endpoint == contract.endpoint
    assert plan.referer == contract.referer
    assert plan.method == ("POST" if contract.file_field else "GET")
    assert set(plan.parameters) == (
        (
            {contract.password_field}
            if contract.password_field and action != "system_router_pass_download"
            else set()
        )
        | (
            ({"sel_idx"} if contract.phonebook_id is not None else {"_tn"})
            if contract.file_field is None
            and action not in {"system_log_download", "system_router_pass_download"}
            else set()
        )
    )
    assert "private-" not in repr(plan)
    assert "12345678" not in repr(plan)
    assert "private-" not in repr(contract.metadata())
    with pytest.raises(TypeError):
        plan.parameters["arbitrary"] = "field"  # type: ignore[index]


@pytest.mark.parametrize("action", FILE_TRANSFER_CONTRACTS)
@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "Speedport Smart 4"},
        {"firmware": "010152.5.0.002.0"},
        {"confirmed": 1},
        {"confirmed": False},
        {"confirmation_text": "SAVE"},
    ],
)
def test_transfer_requires_exact_firmware_and_typed_approval(
    action: str, overrides: dict[str, Any]
) -> None:
    """A neighboring router or implicit approval never reaches a request plan."""
    with pytest.raises(FileTransferError):
        prepare_file_transfer(action, **{**_args(action), **overrides})


@pytest.mark.parametrize(
    "password", ["", "abcdefgh", 'A9!"§$%&/()=*+#,;.:_-', "a" * 255]
)
def test_backup_password_exact_static_alphabet(password: str) -> None:
    """Optional backup encryption uses the captured native form validator."""
    assert (
        prepare_file_transfer(
            "system_backup_download",
            **_args("system_backup_download"),
            password=password,
        ).parameters["save_pwd"]
        == password
    )


@pytest.mark.parametrize(
    "password", [None, 1, "short", "eight words", "å" * 8, "a" * 256, "a\n1234567"]
)
def test_backup_rejects_unreviewed_passwords(password: object) -> None:
    """Failure text is fixed and never embeds an entered password."""
    with pytest.raises(FileTransferError, match=r"^invalid_transfer_password$"):
        prepare_file_transfer(
            "system_backup_download",
            **_args("system_backup_download"),
            password=password,
        )


@pytest.mark.parametrize(
    "filename",
    [
        None,
        "",
        "..",
        "../private",
        "/absolute/private",
        "C:\\private",
        "bad\nname",
        'bad"name',
        "bad;name",
        "x" * 256,
    ],
)
def test_upload_rejects_path_or_header_injection(filename: object) -> None:
    """Names are never used as paths or reflected into a response header."""
    args = {**_args("system_backup_restore"), "filename": filename}
    with pytest.raises(FileTransferError, match=r"^invalid_transfer_file$"):
        prepare_file_transfer("system_backup_restore", **args)


@pytest.mark.parametrize(
    "action", [key for key, item in FILE_TRANSFER_CONTRACTS.items() if item.file_field]
)
def test_upload_bounds_digest_and_token_exclusion(action: str) -> None:
    """Bounds are inclusive; a digest is only a binding format, not authenticity."""
    maximum = FILE_TRANSFER_CONTRACTS[action].maximum_bytes
    for size in (1, maximum):
        validate_upload_descriptor(action, size=size, sha256="a" * 64)
        prepare_file_transfer(action, **{**_args(action), "size": size})
    for size in (0, -1, maximum + 1, True, "4"):
        with pytest.raises(FileTransferError):
            validate_upload_descriptor(action, size=size, sha256="a" * 64)
    for digest in (None, "a" * 63, "A" * 64, "z" * 64):
        with pytest.raises(FileTransferError):
            validate_upload_descriptor(action, size=4, sha256=digest)
    with pytest.raises(FileTransferError):
        prepare_file_transfer(action, **{**_args(action), "token": "12345"})


@pytest.mark.parametrize(
    ("action", "status", "outcome"),
    [
        ("system_backup_restore", "ok", "reconnect_required"),
        ("system_backup_restore", "failed", "rejected"),
        ("system_backup_restore", "nofile", "rejected"),
        ("system_backup_restore", "wait", "outcome_unknown"),
        ("system_firmware_upload", "wait", "processing"),
        ("system_firmware_upload", "ok", "reconnect_required"),
        ("system_firmware_upload", "nomodel", "rejected"),
        ("system_mesh_firmware_upload", "wait", "processing"),
        ("system_mesh_firmware_upload", "wrongfile", "rejected"),
        ("system_mesh_firmware_upload", "ok", "outcome_unknown"),
    ],
)
def test_redirect_status_never_claims_restored_or_installed(
    action: str, status: str, outcome: str
) -> None:
    """Only the exact form's same-origin redirect can select a known phase."""
    page = FILE_TRANSFER_CONTRACTS[action].referer
    assert (
        classify_upload_response(
            action,
            http_status=302,
            location=f"/{page}?status={status}",
            router_base_url="http://speedport.ip",
        )
        == outcome
    )


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.invalid/html/content/config/save_settings.html?status=ok",
        "//speedport.ip/html/content/config/save_settings.html?status=ok",
        "http://user@speedport.ip/html/content/config/save_settings.html?status=ok",
        "/html/content/config/save_settings.html?status=ok&status=failed",
        "/html/content/config/save_settings.html?status=ok&private=value",
        "/html/content/config/save_settings.html?status=ok#fragment",
        "/html/content/config/save_settings.html?status=ok\n",
        "/html/content/config/check_for_updates.html?status=ok",
        "/html/login/index.html?status=ok",
        None,
    ],
)
def test_unsafe_or_wrong_redirect_is_unknown(location: object) -> None:
    """No redirect is followed or reflected, including ambiguous success strings."""
    assert (
        classify_upload_response(
            "system_backup_restore",
            http_status=302,
            location=location,
            router_base_url="http://speedport.ip",
        )
        == "outcome_unknown"
    )


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("wait", "processing"),
        ("ok", "reconnect_required"),
        ("wrongfile", "rejected"),
        ("success", "outcome_unknown"),
        (None, "outcome_unknown"),
        (["ok", "failed"], "outcome_unknown"),
    ],
)
def test_firmware_validation_is_not_installation_proof(
    status: object, outcome: str
) -> None:
    """A later installed-version check remains necessary after router validation."""
    assert classify_router_firmware_progress({"firmware_status": status}) == outcome


def test_transfer_preflight_rejects_busy_router_or_unsupported_mesh_inventory() -> None:
    """A complete fresh mesh inventory must include a connected non-local target."""
    validate_transfer_preflight("system_backup_download", {"router_state": "OK"})
    for raw in ({}, {"router_state": "MODEM"}, {"router_state": ["OK", "BUSY"]}):
        with pytest.raises(FileTransferError):
            validate_transfer_preflight("system_backup_restore", raw)
    good = {"mesh_connected": "1", "mesh_upd_local": "0"}
    validate_transfer_preflight(
        "system_mesh_firmware_upload", {"router_state": "OK", "addmeshdevice": [good]}
    )
    for rows in (
        None,
        [],
        [None],
        [{**good, "mesh_connected": "0"}],
        [{**good, "mesh_upd_local": "1"}],
        [good, {}],
    ):
        with pytest.raises(FileTransferError):
            validate_transfer_preflight(
                "system_mesh_firmware_upload",
                {"router_state": "OK", "addmeshdevice": rows},
            )


@pytest.mark.parametrize("book", range(6))
def test_phonebook_transfer_exact_bound_index_and_native_fields(book: int) -> None:
    """Local book identity is bound into the grant action, never caller URL fields."""
    export_id = f"phonebook_export_{book}"
    export = prepare_file_transfer(export_id, **_args(export_id))
    assert export.parameters == {"sel_idx": str(book)}
    assert export.endpoint == "data/PhoneBookExport.json"
    import_id = f"phonebook_import_{book}"
    imported = prepare_file_transfer(import_id, **_args(import_id))
    assert imported.file_field == f"importfile-{book}"
    assert imported.parameters == {}
    assert imported.endpoint == "data/PhoneBookImport.json"
    assert FILE_TRANSFER_CONTRACTS[import_id].maximum_bytes == 2_097_152
    for direction in ("import", "export"):
        metadata = FILE_TRANSFER_CONTRACTS[f"phonebook_{direction}_{book}"].metadata()
        assert metadata["phonebook_id"] == book
        assert metadata["live_write_verified"] is False
        assert str(book + 1) in metadata["confirmation"]


@pytest.mark.parametrize(
    "action",
    [
        "phonebook_import_6",
        "phonebook_export_100",
        "phonebook_export_00",
        "phonebook_import_-1",
        "phonebook_export_0?evil=1",
    ],
)
def test_phonebook_rejects_online_aliases_and_arbitrary_targets(action: str) -> None:
    """Only the five reviewed local books may enter native request plans."""
    with pytest.raises(FileTransferError):
        prepare_file_transfer(action, **_args("phonebook_export_0"))


def _book_inventory() -> dict[str, Any]:
    return {
        "phonebook_id": 2,
        "entries": [{"contact_id": "42"}],
        "total": 1,
        "free_entries": 999,
        "truncated": False,
        "prefix": "",
    }


def _book_rows() -> dict[str, Any]:
    return {
        "addonlbuchentry": [
            {
                "id": "b",
                "onlbuch_nr": "2",
                "onlbuch_name": "Book",
                "onlbuch_bname": "",
                "onlbuch_sync": "0",
            }
        ]
    }


def test_phonebook_export_empty_and_import_full_reject_before_native_request() -> None:
    """Known empty exports and known full import targets produce clear safe errors."""
    for action in ("phonebook_export_2", "phonebook_import_2"):
        validate_phonebook_transfer_preflight(
            action, _book_inventory(), books=_book_rows()
        )
    with pytest.raises(FileTransferError, match="phonebook_empty"):
        validate_phonebook_transfer_preflight(
            "phonebook_export_2",
            {**_book_inventory(), "entries": [], "total": 0},
            books=_book_rows(),
        )
    with pytest.raises(FileTransferError, match="phonebook_full"):
        validate_phonebook_transfer_preflight(
            "phonebook_import_2",
            {**_book_inventory(), "free_entries": 0},
            books=_book_rows(),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"phonebook_id": 1},
        {"phonebook_id": True},
        {"total": 2},
        {"truncated": True},
        {"prefix": "a"},
        {"entries": None},
        {"entries": [{"contact_id": "42"}, {"contact_id": "42"}], "total": 2},
    ],
)
def test_phonebook_transfer_needs_complete_exact_book_proof(
    changes: dict[str, Any],
) -> None:
    """Filtered, duplicate or mismatched lists never authorize a transfer."""
    with pytest.raises(FileTransferError, match="transfer_preflight_failed"):
        validate_phonebook_transfer_preflight(
            "phonebook_export_2", {**_book_inventory(), **changes}, books=_book_rows()
        )


def test_phonebook_transfer_requires_real_book_and_no_online_import() -> None:
    """A successful empty search cannot invent an unused book or overwrite a link."""
    with pytest.raises(FileTransferError, match="transfer_preflight_failed"):
        validate_phonebook_transfer_preflight(
            "phonebook_export_2", _book_inventory(), books={"addonlbuchentry": []}
        )
    books = _book_rows()
    books["addonlbuchentry"][0]["onlbuch_sync"] = "1"
    with pytest.raises(FileTransferError, match="phonebook_linked"):
        validate_phonebook_transfer_preflight(
            "phonebook_import_2", _book_inventory(), books=books
        )
    validate_phonebook_transfer_preflight(
        "phonebook_export_2", _book_inventory(), books=books
    )


@pytest.mark.parametrize("status", [str(value) for value in range(1, 9)])
def test_phonebook_native_failure_statuses_are_bounded_rejections(status: str) -> None:
    """No raw body is echoed; rejection does not imply zero side effects."""
    result = classify_phonebook_import_response({"status": status, "private": "SECRET"})
    assert result == {
        "status": "rejected",
        "router_status": int(status),
        "retry_safe": False,
    }


def test_phonebook_success_is_acceptance_not_verified_import_count() -> None:
    """Native counters remain separate from verified contact state."""
    result = classify_phonebook_import_response(
        {
            "status": "0",
            "totalNum": "25",
            "ignoreNum": "3",
            "fullNum": "0",
            "private": "SECRET",
        }
    )
    assert result["status"] == "import_accepted"
    assert result["reported_total"] == 25
    assert result["reported_ignored"] == 3
    assert result["reported_full"] == 0
    assert result["verification"] == "contents_unverified"
    assert "imported" not in result
    assert "SECRET" not in repr(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "ok"},
        {"status": 0},
        {"status": "9"},
        {"status": ["0", "1"]},
        {"totalNum": None},
        {"ignoreNum": None},
        {"ignoreNum": "26"},
        {"totalNum": "2097153"},
        {"totalNum": "01"},
        {"fullNum": "-1"},
        {"ignoreNum": "SECRET"},
    ],
)
def test_phonebook_ambiguous_acknowledgement_never_claims_acceptance(
    changes: dict[str, Any],
) -> None:
    """Missing, conflicting, oversized or malformed counters remain unknown."""
    result = classify_phonebook_import_response(
        {"status": "0", "totalNum": "25", "ignoreNum": "3", **changes}
    )
    assert result == {"status": "outcome_unknown", "retry_safe": False}


def _pass_fields() -> dict[str, str]:
    return {
        "serial_number": "PRIVATE-SERIAL",
        "wlan_ssid": "PRIVATE-SSID",
        "wlan_5ghz_ssid": "Five &amp; GHz",
        "wlan_visible": "1",
        "wlan_5ghz_visible": "0",
        "wlan_enc": "5",
        "wlan_wpa_key": "PRIVATE-WIFI",
    }


def test_private_router_pass_never_sends_print_password_to_router() -> None:
    """Entered print passwords never appear in router query/form parameters."""
    action = "system_router_pass_download"
    private_password = "PRIVATE-ADMIN"  # noqa: S105
    plan = prepare_file_transfer(action, **_args(action), password=private_password)
    assert plan.parameters == {}
    assert "PRIVATE-ADMIN" not in repr(plan)
    data = build_router_pass(
        _pass_fields(), router_url="http://router.invalid", password=private_password
    )
    assert b"Five & GHz" in data
    assert b"PRIVATE-WIFI" in data
    assert b"PRIVATE-ADMIN" in data
    assert b"not verified" in data
    assert b"Not included" in build_router_pass(
        _pass_fields(), router_url="http://router.invalid", password=""
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"wlan_wpa_key": "********"},
        {"wlan_wpa_key": "[redacted]"},
        {"wlan_visible": ["0", "1"]},
        {"wlan_enc": "unknown"},
        {"wlan_ssid": "bad\nfield"},
        {"serial_number": ""},
    ],
)
def test_router_pass_unknown_or_masked_fields_fail_closed(
    changes: dict[str, Any],
) -> None:
    """Do not print masked credentials or format control characters as real data."""
    with pytest.raises(FileTransferError):
        build_router_pass(
            {**_pass_fields(), **changes},
            router_url="http://router.invalid",
            password="",
        )


def test_router_pass_open_wifi_requires_no_secret_and_untrusted_urls_rejected() -> None:
    """No invented password for open networks and no credential-bearing URLs."""
    raw = {**_pass_fields(), "wlan_enc": "0"}
    raw.pop("wlan_wpa_key")
    assert b"Not used (open network)" in build_router_pass(
        raw, router_url="https://router.invalid", password=""
    )
    with pytest.raises(FileTransferError):
        build_router_pass(
            raw, router_url="https://user:secret@router.invalid", password=""
        )
