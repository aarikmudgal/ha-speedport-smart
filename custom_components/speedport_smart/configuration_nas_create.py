"""Create the router's NAS share only from a proven empty sentinel form."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, boolean
from .configuration_media import storage_absolute_path
from .configuration_storage import nas_share_fields
from .nas_management import (
    NAS_SHARE_ENDPOINT,
    NAS_SHARE_REFERER,
    NasShareContractError,
    NasShareEdit,
    NasShareLimits,
    build_nas_share_create_write,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

NAS_CREATE_SETTING_ID: Final = "storage_nas_share_create"
_USB: Final = boolean("use_usb", "USB enabled")
_ACTIVE: Final = boolean("nas_active", "Share enabled")
_PRINTER: Final = boolean("printer_connected", "Printer connected")
_FIELDS: Final = tuple(
    replace(field, minimum=0) if field.name == "nas_folder_name" else field
    for field in nas_share_fields()
)
_LIMITS: Final = NasShareLimits(512, 6, 32, 8, 32)
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")


def _empty_form(raw: SettingValues) -> dict[str, Any]:
    """Require actual sentinel, disabled state and empty path; absence is not empty."""
    if (
        not _USB.read(raw)
        or raw.get("sid") != "-1"
        or _ACTIVE.read(raw)
        or raw.get("nas_folder_name") != ""
        or _PRINTER.read(raw)
    ):
        raise ConfigurationError("setting_unavailable")
    return {field.name: field.read(raw) for field in _FIELDS if field.kind != "secret"}


def nas_share_create_payload(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Apply explicit creation fields through the existing NAS conditional validator."""
    values = {**_empty_form(raw), **changes}
    if not set(changes) <= {field.name for field in _FIELDS}:
        raise ConfigurationError("invalid_settings")
    storage_absolute_path(values.get("nas_folder_name"))
    try:
        write = build_nas_share_create_write(
            edit=NasShareEdit(
                enabled=values.get("nas_active"),
                folder_name=values.get("nas_folder_name"),
                read_only=values.get("nas_folder_nur_lesen"),
                secure=values.get("nas_secure"),
                username=changes.get("nas_user_name"),
                password=changes.get("nas_user_pwd"),
            ),
            limits=_LIMITS,
        )
        return dict(write.consume_payload())
    except NasShareContractError:
        raise ConfigurationError("invalid_settings") from None


def verify_nas_share_creation(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    """Require a fresh share ID and every independently readable submitted field."""
    payload = nas_share_create_payload(before, changes)
    sid = after.get("sid")
    if not isinstance(sid, str) or _ID.fullmatch(sid) is None or not _USB.read(after):
        return False
    for field in _FIELDS:
        if field.name in payload and field.kind != "secret":
            expected = payload[field.name]
            if field.kind == "boolean":
                expected = bool(expected)
            if field.read(after) != expected:
                return False
    return True


NAS_CREATE_SETTINGS: Final = (
    SettingsContract(
        NAS_CREATE_SETTING_ID,
        "Create NAS share",
        "Storage",
        NAS_SHARE_ENDPOINT,
        NAS_SHARE_REFERER,
        _FIELDS,
        reader=_empty_form,
        builder=nas_share_create_payload,
        payload_keys=frozenset({"sid", *(field.name for field in _FIELDS)}),
        revision_fields=(
            "sid",
            "nas_folder_name",
            "nas_active",
            "nas_secure",
            "nas_folder_nur_lesen",
            "nas_user_name",
            "use_usb",
            "printer_connected",
        ),
        verifier=verify_nas_share_creation,
        verifier_owns_fields=True,
        acknowledgement="readback",
        warning=(
            "This shares the selected existing folder with your network. Without "
            "login protection other network users may access it. No files or "
            "directories are created or deleted."
        ),
        confirmation="CREATE NAS SHARE",
    ),
)
