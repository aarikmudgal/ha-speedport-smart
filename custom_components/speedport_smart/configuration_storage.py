"""Target-bound existing NAS share editors; no row creation or path guessing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_media import storage_absolute_path
from .nas_management import (
    NAS_SHARE_ENDPOINT,
    NAS_SHARE_REFERER,
    NasShareContractError,
    NasShareEdit,
    NasShareLimits,
    build_nas_share_write,
    nas_share_fingerprint,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

NAS_SHARE_SETTING_ID: Final = "storage_nas_share"
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_USB: Final = boolean("use_usb", "USB storage")
# Firmware English validation strings prove username 6-32 and password 8-32.
# The authenticated HTML validator also proves a 512-character folder bound.
_LIMITS: Final = NasShareLimits(512, 6, 32, 8, 32)
_FIELDS: Final = (
    boolean("nas_active", "Share enabled"),
    SettingsField(
        "nas_folder_name",
        "Shared folder path",
        "text",
        minimum=1,
        maximum=512,
        description="Use an existing absolute folder path on the attached storage.",
    ),
    boolean("nas_folder_nur_lesen", "Read-only file access"),
    boolean("nas_secure", "Require login"),
    SettingsField(
        "nas_user_name",
        "Username",
        "text",
        minimum=0,
        maximum=32,
        description="A login-protected share requires 6-32 supported characters.",
    ),
    SettingsField(
        "nas_user_pwd",
        "New password",
        "secret",
        minimum=8,
        maximum=32,
        description=(
            "Re-enter the password for every save while sharing requires login. "
            "The stored password is never displayed or reused."
        ),
    ),
)
_TITLE: Final = "Existing NAS share"
_WARNING: Final = (
    "Changing access may disconnect file transfers. Removing login protection "
    "allows network users to access the shared folder. Changing the folder "
    "changes what is shared; this editor does not create or delete files or shares."
)
_CONFIRMATION: Final = "SAVE SHARE SETTINGS"


def nas_share_fields() -> tuple[SettingsField, ...]:
    """Reuse the reviewed field schema for the separate new-share lifecycle."""
    return _FIELDS


def nas_share_settings_metadata() -> dict[str, Any]:
    """Describe the target-required editor without inventing a share identity."""
    return {
        "id": NAS_SHARE_SETTING_ID,
        "title": _TITLE,
        "section": "Storage",
        "fields": [item.metadata() for item in _FIELDS],
        "warning": _WARNING,
        "confirmation": _CONFIRMATION,
        "requires_target": True,
        "live_write_verified": False,
    }


def nas_share_settings(target_id: str) -> SettingsContract:
    """
    Bind a reviewed editor to one server-resolved existing share identity.

    The caller must independently select this exact row from a complete current
    NASFolder response and carry its USB prerequisite flag into the raw mapping.
    It must use the same bound contract for revision/read/preflight/write/readback.
    This factory is deliberately absent from the scalar settings registry.
    """
    if not isinstance(target_id, str) or _ID.fullmatch(target_id) is None:
        raise ConfigurationError("invalid_settings_target")

    def read(raw: SettingValues) -> dict[str, Any]:
        if not _USB.read(raw):
            raise ConfigurationError("setting_unavailable")
        sid = raw.get("sid")
        if type(sid) is int and sid >= 0:
            sid = str(sid)
        if sid != target_id:
            raise ConfigurationError("stale_settings")
        try:
            nas_share_fingerprint(raw)
        except NasShareContractError:
            raise ConfigurationError("setting_unavailable") from None
        source = dict(raw)
        # Empty usernames are legitimate for an existing unprotected share.
        # Their strict active/secure constraints are checked by the builder.
        if source.get("nas_user_name") in (None, ""):
            source["nas_user_name"] = ""
        return source

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        read(raw)
        if "nas_folder_name" in changes:
            storage_absolute_path(changes["nas_folder_name"])
        try:
            write = build_nas_share_write(
                raw,
                expected_share_id=target_id,
                expected_fingerprint=nas_share_fingerprint(raw),
                edit=NasShareEdit(
                    enabled=changes.get("nas_active"),
                    read_only=changes.get("nas_folder_nur_lesen"),
                    secure=changes.get("nas_secure"),
                    folder_name=changes.get("nas_folder_name"),
                    username=changes.get("nas_user_name"),
                    password=changes.get("nas_user_pwd"),
                ),
                limits=_LIMITS,
            )
            return dict(write.consume_payload())
        except NasShareContractError:
            raise ConfigurationError("invalid_settings") from None

    return SettingsContract(
        NAS_SHARE_SETTING_ID,
        _TITLE,
        "Storage",
        NAS_SHARE_ENDPOINT,
        NAS_SHARE_REFERER,
        _FIELDS,
        reader=read,
        builder=build,
        payload_keys=frozenset(
            {*(item.name for item in _FIELDS), "sid", "nas_folder_name"}
        ),
        revision_fields=(
            "sid",
            "id",
            "nas_folder_name",
            "use_usb",
            "printer_connected",
        ),
        acknowledgement="readback",
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )
