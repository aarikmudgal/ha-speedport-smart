"""
Closed native-form file-transfer policy; this module performs no I/O.

The HTTP owner must authorize the administrator and loaded entry, bind a
short-lived one-use approval to the requester, entry, action and upload digest,
and recheck that digest while reading the bounded file body. The owner also
provides a fresh page token, authenticates/preflights the router, serializes all
operations, sends at most once without redirects/retries, clears private buffers,
and attempts session cleanup. A request plan is private transport data, never a
dashboard/diagnostic/log/Recorder object.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html import unescape
from types import MappingProxyType
from typing import Any, Final, Literal
from urllib.parse import parse_qs, urljoin, urlsplit

from .admin_actions import SPEEDPORT_SMART_4R_TYP_A_010152

TransferOutcome = Literal[
    "processing", "reconnect_required", "rejected", "outcome_unknown"
]
_MIN_BACKUP_PASSWORD: Final = 8
_MAX_PASSWORD: Final = 255
_MAX_FILENAME_BYTES: Final = 255
_MAX_LOCATION: Final = 2048
_MAX_MESH_ROWS: Final = 64
_FIRST_PRINTABLE: Final = 32
_DELETE_CHARACTER: Final = 127
_GET: Final = "GET"
_POST: Final = "POST"
_REDIRECTS: Final = frozenset({302, 303})
_HTTP: Final = 80
_HTTPS: Final = 443
_TOKEN: Final = re.compile(r"[0-9]{1,32}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_BACKUP_PASSWORD: Final = re.compile(r'[0-9a-zA-Z!"§$%&/()=*+#,;.:_-]*')
_PHONEBOOK_BYTES: Final = 2_097_152
_PHONEBOOK_REFERER: Final = "html/content/phone/phone_book_entries.html"
_MAX_PASS_FIELD: Final = 128


class FileTransferError(ValueError):
    """A fixed, value-free rejection safe to expose to an administrator."""

    def __init__(self, code: str = "invalid_file_transfer") -> None:
        """Never retain a filename, password, token, router body or Location."""
        if code not in {
            "invalid_file_transfer",
            "unsupported_router",
            "confirmation_required",
            "invalid_transfer_password",
            "invalid_transfer_file",
            "transfer_token_unavailable",
            "transfer_preflight_failed",
            "transfer_unavailable",
            "transfer_download_failed",
            "transfer_busy",
            "phonebook_empty",
            "phonebook_full",
            "phonebook_linked",
        }:
            raise ValueError("Unknown file-transfer error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FileTransferContract:
    """One exact native HTML form, not an arbitrary HTTP proxy."""

    id: str
    title: str
    endpoint: str
    referer: str
    preflight_endpoint: str
    file_field: str | None
    maximum_bytes: int
    password_field: str | None
    confirmation: str
    warning: str
    phonebook_id: int | None = None

    def metadata(self) -> dict[str, Any]:
        """Return only static UI requirements, never a transfer's private data."""
        return {
            "id": self.id,
            "title": self.title,
            "execution_policy": "file_transfer",
            "direction": "upload" if self.file_field else "download",
            "maximum_bytes": self.maximum_bytes,
            "password": None
            if self.password_field is None
            else {
                "label": (
                    "Router password to include (optional; not verified)"
                    if self.id == "system_router_pass_download"
                    else "Backup password (empty for an unprotected backup)"
                ),
                "minimum_when_nonempty": (
                    _MIN_BACKUP_PASSWORD
                    if self.password_field == "save_pwd"  # noqa: S105
                    else 1
                ),
                "maximum": _MAX_PASSWORD,
            },
            "confirmation": self.confirmation,
            "warning": (
                self.warning + " Native file transfers use the configured HTTP or "
                "HTTPS connection, not JSON-message encryption. HTTP adds no "
                "transport encryption for files or backup passwords."
            ),
            "preflight_required": True,
            "live_write_verified": False,
            "phonebook_id": self.phonebook_id,
        }


def _phonebook_contracts() -> tuple[FileTransferContract, ...]:
    """Bind finite native book IDs; fresh membership, not an index, proves existence."""
    return tuple(
        FileTransferContract(
            id=f"phonebook_{direction}_{book}",
            title=f"{'Import into' if upload else 'Export'} local phonebook {book + 1}",
            endpoint=f"data/PhoneBook{'Import' if upload else 'Export'}.json",
            referer=_PHONEBOOK_REFERER,
            preflight_endpoint="data/PhoneBook.json",
            file_field=f"importfile-{book}" if upload else None,
            maximum_bytes=_PHONEBOOK_BYTES,
            password_field=None,
            confirmation=(
                f"{'IMPORT INTO' if upload else 'EXPORT'} PHONEBOOK {book + 1}"
            ),
            warning=(
                "This imports a compatible CSV into the selected local phonebook. "
                "Existing contacts may be affected. Export a backup first. The "
                "router validates the CSV format; this integration does not claim "
                "a proven CSV schema. An accepted response and its total/ignored "
                "counters do not verify every imported contact. Inspect the book "
                "before repeating an import."
                if upload
                else "This downloads the router's private phonebook CSV, including "
                "contact details. Keep it private. The CSV format has not been "
                "validated with a populated book. Empty books cannot be exported. "
                "Treat spreadsheet formulas in untrusted contact data as unsafe. "
                "Downloads are bounded to the reviewed 2 MiB import limit."
            ),
            phonebook_id=book,
        )
        for book in range(6)
        for direction, upload in (("import", True), ("export", False))
    )


FILE_TRANSFER_CONTRACTS: Final[Mapping[str, FileTransferContract]] = MappingProxyType(
    {
        item.id: item
        for item in (
            FileTransferContract(
                "system_backup_download",
                "Download private configuration backup",
                "data/Backup.json",
                "html/content/config/save_settings.html",
                "data/BackupRestore.json",
                None,
                6_291_456,
                "save_pwd",
                "DOWNLOAD PRIVATE BACKUP",
                "The file contains private router configuration and may contain "
                "credentials. Keep it private. A password is optional; an empty "
                "password does not protect the backup. Downloading does not prove "
                "that the file can be restored. The integration bounds downloads to "
                "the reviewed restore-upload limit.",
            ),
            FileTransferContract(
                "system_backup_restore",
                "Restore configuration backup",
                "data/Backup.json",
                "html/content/config/save_settings.html",
                "data/BackupRestore.json",
                "backupfile",
                6_291_456,
                "restore_pwd",
                "RESTORE ROUTER BACKUP",
                "Restoring replaces router settings and restarts the router. Use a "
                "compatible backup and keep physical access and a recovery plan. "
                "The restored address, HTTPS mode or administrator password may "
                "change. Home Assistant does not follow a new address or claim "
                "successful restoration from the upload response.",
            ),
            FileTransferContract(
                "system_firmware_upload",
                "Install router firmware file",
                "data/FirmwareUpdate.json",
                "html/content/config/check_for_updates.html",
                "data/FirmwareUpdate.json",
                "firmwarefile",
                82_428_800,
                None,
                "INSTALL ROUTER FIRMWARE",
                "Use the official firmware image matching this router model. Keep "
                "power and cabling connected and retain physical access and a "
                "recovery plan. Local size checks do not prove image compatibility "
                "or authenticity. Router validation and a later version check are "
                "required; an upload acknowledgement is not installation proof.",
            ),
            FileTransferContract(
                "system_mesh_firmware_upload",
                "Install mesh firmware file",
                "data/FirmwareUpdateMesh.json",
                "html/content/config/check_for_updates_mesh.html",
                "data/FirmwareUpdateMesh.json",
                "meshfirmwarefile",
                20_971_520,
                None,
                "INSTALL MESH FIRMWARE",
                "The router distributes the file to supported connected mesh "
                "devices; this is not an individual-node upload. Devices marked "
                "for local updates use their own interface. Use the matching "
                "official image and keep power connected. A timer or vanished "
                "device does not prove installation; inspect all affected versions "
                "after recovery.",
            ),
            *_phonebook_contracts(),
            FileTransferContract(
                "system_log_download",
                "Download private system log",
                "data/Syslog.json",
                "html/content/config/system_log.html",
                "data/SystemMessages.json",
                None,
                2_097_152,
                None,
                "DOWNLOAD PRIVATE SYSTEM LOG",
                "The log can include addresses, device names, telephone numbers "
                "and other private details. Keep it private. Downloading does not "
                "clear the log or change its filter. Downloads are bounded to 2 MiB.",
            ),
            FileTransferContract(
                "system_router_pass_download",
                "Download private Router-Pass",
                "data/WLANBasicAss.json",
                "html/login/index.html",
                "data/WLANBasicAss.json",
                None,
                16_384,
                "router_password",
                "DOWNLOAD PRIVATE ROUTER PASS",
                "This creates a private text card from fresh Wi-Fi settings, "
                "including the Wi-Fi password. An optional router password you "
                "enter is sent to Home Assistant only to create this download; "
                "it is never sent to or verified by the router. Use an HTTPS "
                "Home Assistant connection when entering passwords. Keep the "
                "file private. Nothing is written to the router.",
            ),
        )
    }
)


@dataclass(frozen=True, slots=True)
class FileTransferPlan:
    """Private request description; the caller streams bytes separately."""

    action: str
    method: Literal["GET", "POST"]
    endpoint: str
    referer: str
    file_field: str | None
    size: int
    parameters: Mapping[str, str] = field(repr=False)
    filename: str | None = field(repr=False)


def _contract(action: str) -> FileTransferContract:
    if type(action) is not str or action not in FILE_TRANSFER_CONTRACTS:
        raise FileTransferError
    return FILE_TRANSFER_CONTRACTS[action]


def _printable(value: str) -> bool:
    return not any(
        ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER for char in value
    )


def _password(contract: FileTransferContract, value: object) -> str:
    if type(value) is not str or not _printable(value):
        raise FileTransferError("invalid_transfer_password")
    try:
        # Native maxlength is measured in UTF-16 code units.
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeError:
        raise FileTransferError("invalid_transfer_password") from None
    if length > _MAX_PASSWORD or (contract.password_field is None and value):
        raise FileTransferError("invalid_transfer_password")
    if (
        contract.password_field == "save_pwd"  # noqa: S105
        and value
        and (length < _MIN_BACKUP_PASSWORD or _BACKUP_PASSWORD.fullmatch(value) is None)
    ):
        raise FileTransferError("invalid_transfer_password")
    return value


def validate_upload_descriptor(action: str, *, size: object, sha256: object) -> None:
    """
    Validate bounds/format, not trust in a client-supplied digest.

    The HTTP owner must compute the actual body digest and compare it with the
    approved value before sending any bytes to the router.
    """
    contract = _contract(action)
    if (
        contract.file_field is None
        or type(size) is not int
        or not 0 < size <= contract.maximum_bytes
        or type(sha256) is not str
        or _SHA256.fullmatch(sha256) is None
    ):
        raise FileTransferError("invalid_transfer_file")


def _filename(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or not _printable(value)
        or any(char in value for char in '/\\";')
    ):
        raise FileTransferError("invalid_transfer_file")
    try:
        if len(value.encode("utf-8")) > _MAX_FILENAME_BYTES:
            raise FileTransferError("invalid_transfer_file")
    except UnicodeError:
        raise FileTransferError("invalid_transfer_file") from None
    return value


def _scalar(raw: Mapping[str, Any], name: str) -> object:
    value = raw.get(name)
    if (
        isinstance(value, list)
        and value
        and all(type(item) is type(value[0]) and item == value[0] for item in value)
    ):
        return value[0]
    return value


def validate_transfer_preflight(action: str, raw: Mapping[str, Any]) -> None:
    """Require fresh ready-router state; mesh also requires a supported live node."""
    _contract(action)
    if _scalar(raw, "router_state") != "OK":
        raise FileTransferError("transfer_preflight_failed")
    if action != "system_mesh_firmware_upload":
        return
    source = raw.get("addmeshdevice")
    if isinstance(source, Mapping):
        rows = [source] if source else []
    elif isinstance(source, list):
        rows = source
    else:
        raise FileTransferError("transfer_preflight_failed")
    if len(rows) > _MAX_MESH_ROWS:
        raise FileTransferError("transfer_preflight_failed")
    eligible = False
    for row in rows:
        if not isinstance(row, Mapping):
            raise FileTransferError("transfer_preflight_failed")
        connected = _scalar(row, "mesh_connected")
        local = _scalar(row, "mesh_upd_local")
        if type(connected) is not str or connected not in {"0", "1"}:
            raise FileTransferError("transfer_preflight_failed")
        if type(local) is not str or local not in {"0", "1"}:
            raise FileTransferError("transfer_preflight_failed")
        eligible |= connected == "1" and local == "0"
    if not eligible:
        raise FileTransferError("transfer_preflight_failed")


def prepare_file_transfer(
    action: str,
    *,
    model: object,
    firmware: object,
    confirmed: object,
    confirmation_text: object,
    token: object = None,
    password: object = "",
    filename: object = None,
    size: object = 0,
) -> FileTransferPlan:
    """
    Build only reviewed fields after explicit approval and exact firmware gating.

    Parameters are normal native-form fields, not CCM JSON. For downloads they
    become backend-only GET query parameters. The HA/browser request must use a
    private POST body so the password never enters browser history or an HA URL.
    """
    contract = _contract(action)
    target = SPEEDPORT_SMART_4R_TYP_A_010152
    if model != target.model or firmware != target.firmware:
        raise FileTransferError("unsupported_router")
    if confirmed is not True or confirmation_text != contract.confirmation:
        raise FileTransferError("confirmation_required")
    private_password = _password(contract, password)
    if contract.file_field is None:
        if action in {"system_log_download", "system_router_pass_download"}:
            if token is not None:
                raise FileTransferError("invalid_file_transfer")
            fields = {}
        elif contract.phonebook_id is not None:
            if token is not None:
                raise FileTransferError("invalid_file_transfer")
            fields = {"sel_idx": str(contract.phonebook_id)}
        elif type(token) is str and _TOKEN.fullmatch(token) is not None:
            fields = {"_tn": token}
        else:
            raise FileTransferError("transfer_token_unavailable")
        if filename is not None or type(size) is not int or size != 0:
            raise FileTransferError("invalid_transfer_file")
        safe_filename = None
    else:
        # The captured upload forms contain no addTokenField() call or token
        # input. They use the authenticated session's native multipart POST.
        if token is not None:
            raise FileTransferError("invalid_file_transfer")
        if type(size) is not int or not 0 < size <= contract.maximum_bytes:
            raise FileTransferError("invalid_transfer_file")
        safe_filename = _filename(filename)
        fields = {}
    if contract.password_field and action != "system_router_pass_download":
        fields[contract.password_field] = private_password
    return FileTransferPlan(
        action=contract.id,
        method=_POST if contract.file_field else _GET,
        endpoint=contract.endpoint,
        referer=contract.referer,
        file_field=contract.file_field,
        size=size,
        parameters=MappingProxyType(fields),
        filename=safe_filename,
    )


def _redirect_status(
    contract: FileTransferContract, base_url: object, location: object
) -> str | None:
    if (
        type(base_url) is not str
        or type(location) is not str
        or not location
        or len(location) > _MAX_LOCATION
        or not _printable(location)
        or "\\" in location
        or location.startswith("//")
    ):
        return None
    try:
        origin = urlsplit(base_url)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            return None
        target = urlsplit(
            urljoin(base_url.rstrip("/") + "/" + contract.endpoint, location)
        )
        default_port = _HTTPS if origin.scheme == "https" else _HTTP
        if (
            target.scheme != origin.scheme
            or target.hostname != origin.hostname
            or (target.port or default_port) != (origin.port or default_port)
            or target.username is not None
            or target.password is not None
            or target.path != "/" + contract.referer
            or target.fragment
        ):
            return None
        query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True)
    except (TypeError, ValueError):
        return None
    if set(query) != {"status"} or len(query["status"]) != 1:
        return None
    return query["status"][0]


def classify_upload_response(
    action: str, *, http_status: object, location: object, router_base_url: object
) -> TransferOutcome:
    """Inspect a redirect without following it; never claim restored/installed."""
    contract = _contract(action)
    if contract.file_field is None:
        raise FileTransferError
    if contract.phonebook_id is not None:
        # Phonebook imports use an authenticated JSON body, never redirects.
        return "outcome_unknown"
    if type(http_status) is not int or http_status not in _REDIRECTS:
        return "outcome_unknown"
    status = _redirect_status(contract, router_base_url, location)
    if action == "system_backup_restore":
        if status == "ok":
            return "reconnect_required"
        return "rejected" if status in {"failed", "nofile"} else "outcome_unknown"
    if action == "system_firmware_upload":
        if status == "ok":
            return "reconnect_required"
        if status == "wait":
            return "processing"
        if status in {"nofile", "noinfo", "nomodel", "wrongfile"}:
            return "rejected"
        return "outcome_unknown"
    if status == "wait":
        # This mesh callback only starts a countdown, not a version check.
        return "processing"
    return "rejected" if status in {"nofile", "wrongfile"} else "outcome_unknown"


def classify_router_firmware_progress(raw: Mapping[str, Any]) -> TransferOutcome:
    """Classify FirmwareUpdateCheck.json without conflating validation and install."""
    status = _scalar(raw, "firmware_status")
    if status == "wait":
        return "processing"
    if status == "ok":
        return "reconnect_required"
    if status == "wrongfile":
        return "rejected"
    return "outcome_unknown"


def validate_phonebook_transfer_preflight(
    action: str, inventory: Mapping[str, Any], *, books: Mapping[str, Any] | None = None
) -> None:
    """Require a complete fresh search of the exact local book before transfer."""
    from .configuration import ConfigurationError  # noqa: PLC0415
    from .configuration_phonebook_accounts import (  # noqa: PLC0415
        phonebook_account_rows,
    )
    from .configuration_phonebook_lifecycle import phonebook_inventory  # noqa: PLC0415

    contract = _contract(action)
    if contract.phonebook_id is None:
        raise FileTransferError
    try:
        rows = phonebook_inventory(inventory, phonebook_id=contract.phonebook_id)
        matches = [
            row
            for row in phonebook_account_rows(books or {})
            if row["onlbuch_nr"] == str(contract.phonebook_id)
        ]
    except ConfigurationError:
        raise FileTransferError("transfer_preflight_failed") from None
    if len(matches) != 1:
        raise FileTransferError("transfer_preflight_failed")
    if contract.file_field is not None and matches[0]["onlbuch_sync"] != "0":
        raise FileTransferError("phonebook_linked")
    if contract.file_field is None and not rows:
        raise FileTransferError("phonebook_empty")
    if contract.file_field is not None and inventory["free_entries"] < 1:
        raise FileTransferError("phonebook_full")


def classify_phonebook_import_response(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only bounded native status/counters; acceptance is not content proof."""
    unknown: dict[str, Any] = {"status": "outcome_unknown", "retry_safe": False}
    status = _scalar(raw, "status")
    if type(status) is not str or status not in {str(index) for index in range(9)}:
        return unknown
    counters = {}
    for source, target in (
        ("totalNum", "reported_total"),
        ("ignoreNum", "reported_ignored"),
        ("fullNum", "reported_full"),
    ):
        value = _scalar(raw, source)
        if value is None:
            continue
        if (
            type(value) is not str
            or re.fullmatch(r"0|[1-9][0-9]{0,6}", value) is None
            or int(value) > _PHONEBOOK_BYTES
        ):
            return unknown
        counters[target] = int(value)
    if status != "0":
        return {
            "status": "rejected",
            "router_status": int(status),
            "retry_safe": False,
            **counters,
        }
    if (
        not {"reported_total", "reported_ignored"} <= counters.keys()
        or counters["reported_ignored"] > counters["reported_total"]
    ):
        return unknown
    return {
        "status": "import_accepted",
        "router_status": 0,
        "acknowledged": True,
        "verification": "contents_unverified",
        "retry_safe": False,
        **counters,
    }


def transfer_download_filename(action: str) -> str:
    """Return only a locally defined attachment name, never router input."""
    contract = _contract(action)
    if contract.file_field is not None:
        raise FileTransferError
    if contract.phonebook_id is not None:
        return f"speedport-phonebook-{contract.phonebook_id + 1}.csv"
    if action == "system_log_download":
        return "speedport-system-log.txt"
    if action == "system_router_pass_download":
        return "speedport-router-pass.txt"
    return "speedport-backup.bin"


def build_router_pass(
    raw: Mapping[str, Any], *, router_url: str, password: object
) -> bytes:
    """Create bounded plain text from the exact overview print fields, not HTML."""
    contract = _contract("system_router_pass_download")
    entered = _password(contract, password)
    try:
        url = urlsplit(router_url)
        invalid_url = (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or len(router_url) > _MAX_LOCATION
            or not _printable(router_url)
        )
    except (TypeError, ValueError):
        raise FileTransferError("transfer_preflight_failed") from None
    if invalid_url:
        raise FileTransferError("transfer_preflight_failed")
    values = {}
    for key in ("serial_number", "wlan_ssid", "wlan_5ghz_ssid"):
        value = _scalar(raw, key)
        if type(value) is not str:
            raise FileTransferError("transfer_preflight_failed")
        value = unescape(value)
        if not value or len(value) > _MAX_PASS_FIELD or not _printable(value):
            raise FileTransferError("transfer_preflight_failed")
        values[key] = value
    visible = _scalar(raw, "wlan_visible")
    visible5 = _scalar(raw, "wlan_5ghz_visible")
    encryption = _scalar(raw, "wlan_enc")
    modes = {"0": "Open", "4": "WPA2", "5": "WPA2 / WPA3", "6": "WPA3"}
    if (
        type(encryption) is not str
        or encryption not in modes
        or type(visible) is not str
        or visible not in {"0", "1"}
        or type(visible5) is not str
        or visible5 not in {"0", "1"}
    ):
        raise FileTransferError("transfer_preflight_failed")
    wifi_key = "Not used (open network)"
    if encryption != "0":
        secret = _scalar(raw, "wlan_wpa_key")
        if type(secret) is not str:
            raise FileTransferError("transfer_preflight_failed")
        secret = unescape(secret)
        if (
            not secret
            or len(secret) > _MAX_PASS_FIELD
            or not _printable(secret)
            or re.fullmatch(r"[*•●]+|(?:\[|<)?redacted(?:\]|>)?", secret, re.IGNORECASE)
        ):
            raise FileTransferError("transfer_preflight_failed")
        wifi_key = secret
    lines = [
        "PRIVATE ROUTER-PASS",
        "Keep this file private. It contains Wi-Fi credentials.",
        f"Router URL: {router_url}",
        f"Serial number: {values['serial_number']}",
        f"2.4 GHz Wi-Fi name: {values['wlan_ssid']}",
        f"2.4 GHz name visible: {'Yes' if visible == '1' else 'No'}",
        f"5 GHz Wi-Fi name: {values['wlan_5ghz_ssid']}",
        f"5 GHz name visible: {'Yes' if visible5 == '1' else 'No'}",
        f"Wi-Fi security: {modes[encryption]}",
        f"Wi-Fi password: {wifi_key}",
        f"Router password (user-entered; not verified): {entered}"
        if entered
        else "Router password: Not included",
    ]
    result = ("\n".join(lines) + "\n").encode("utf-8")
    if len(result) > contract.maximum_bytes:
        raise FileTransferError("transfer_download_failed")
    return result
