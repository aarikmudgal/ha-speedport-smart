"""Exact existing DLNA media-folder forms with complete sibling preservation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

MEDIA_ENDPOINT: Final = "data/NASMediaReplay.json"
MEDIA_REFERER: Final = "html/content/network/nas_mediareplay.html"
MEDIA_INDEX_ENDPOINT: Final = "data/NASFileCount.json"
MEDIA_SETTING_ID: Final = "storage_media_folder"
MEDIA_DELETE_SETTING_ID: Final = "storage_media_folder_delete"
MEDIA_MAX_ROWS: Final = 16
_PATH_MAXIMUM: Final = 512
_STATUS_MAXIMUM: Final = 64
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_NAME: Final = re.compile(r"[\x20-\x3B\x3D\x3F-\x7E\x80-\xFF]{1,20}")
_USB: Final = boolean("use_usb", "USB enabled")
_ACTIVE: Final = boolean("mediareplay_active", "Media folder enabled")
_DELETE: Final = boolean("execute", "Remove this media-folder configuration")
_FIELDS: Final = (
    _ACTIVE,
    SettingsField(
        "mediareplay_name", "Media folder name", "text", minimum=1, maximum=20
    ),
    SettingsField(
        "mediareplay_folder",
        "Folder path",
        "text",
        minimum=1,
        maximum=512,
        description="Use an existing absolute folder path on the attached storage.",
    ),
)
MEDIA_TARGET_SPECS: Final = MappingProxyType(
    {
        MEDIA_SETTING_ID: PhoneTargetSpec(
            MEDIA_SETTING_ID,
            "Existing media folder",
            MEDIA_ENDPOINT,
            MEDIA_REFERER,
            "addnasmediareplay",
            "mediareplay_name",
            _FIELDS,
        ),
        MEDIA_DELETE_SETTING_ID: PhoneTargetSpec(
            MEDIA_DELETE_SETTING_ID,
            "Remove media folder",
            MEDIA_ENDPOINT,
            MEDIA_REFERER,
            "addnasmediareplay",
            "mediareplay_name",
            (_DELETE,),
        ),
    }
)
_WARNING: Final = (
    "Changing or disabling a media folder may interrupt playback and restart "
    "indexing. Files are not deleted. Other media folders are preserved."
)
_CONFIRMATION: Final = "SAVE MEDIA FOLDER"


def storage_absolute_path(value: object) -> str:
    """Validate a literal bounded router path without normalizing its identity."""
    if (
        not isinstance(value, str)
        or not 1 < len(value) <= _PATH_MAXIMUM
        or not value.startswith("/")
        or not value.isprintable()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value[1:].split("/"))
    ):
        raise ConfigurationError("invalid_settings")
    return value


def media_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Read a complete explicit folder collection; an omitted list is unknown."""
    if setting_id not in MEDIA_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    if not _USB.read(raw):
        raise ConfigurationError("setting_unavailable")
    value = raw.get("addnasmediareplay")
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, list) or len(value) > MEDIA_MAX_ROWS:
        raise ConfigurationError("settings_inventory_unavailable")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        identifier = item.get("id")
        if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
            raise ConfigurationError("settings_inventory_unavailable")
        if identifier in seen:
            raise ConfigurationError("settings_inventory_unavailable")
        seen.add(identifier)
        result.append(dict(item))
    return tuple(result)


def _read_row(row: SettingValues) -> dict[str, Any]:
    result = {field.name: field.read(row) for field in _FIELDS}
    name = result["mediareplay_name"]
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ConfigurationError("invalid_settings")
    storage_absolute_path(result["mediareplay_folder"])
    status = row.get("mediareplay_status")
    if (
        not isinstance(status, str)
        or len(status) > _STATUS_MAXIMUM
        or (status and not status.isprintable())
    ):
        raise ConfigurationError("settings_inventory_unavailable")
    return result


def _selected(target_id: str, raw: SettingValues) -> dict[str, Any]:
    matches = [
        row
        for row in media_target_rows(MEDIA_SETTING_ID, raw)
        if row["id"] == target_id
    ]
    if len(matches) != 1:
        raise ConfigurationError("stale_settings")
    return matches[0]


def _values(
    target_id: str, raw: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    values = {**_read_row(_selected(target_id, raw)), **changes}
    values = {field.name: field.validate(values[field.name]) for field in _FIELDS}
    if _NAME.fullmatch(values["mediareplay_name"]) is None:
        raise ConfigurationError("invalid_settings")
    storage_absolute_path(values["mediareplay_folder"])
    for row in media_target_rows(MEDIA_SETTING_ID, raw):
        if row["id"] != target_id:
            sibling = _read_row(row)
            if any(
                values[name] == sibling[name]
                for name in ("mediareplay_name", "mediareplay_folder")
            ):
                raise ConfigurationError("invalid_settings")
    return values


def _payload(
    target_id: str, raw: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    row = _selected(target_id, raw)
    values = _values(target_id, raw, changes)
    return {
        "id": target_id,
        "mediareplay_status": row["mediareplay_status"],
        **values,
        "mediareplay_active": int(values["mediareplay_active"]),
    }


def _verify(
    target_id: str, before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    expected = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, before)
    }
    expected[target_id] = _values(target_id, before, changes)
    actual = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, after)
    }
    return actual == expected


def media_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind a complete form to one exact current media-folder identity."""
    if (
        setting_id not in MEDIA_TARGET_SPECS
        or not isinstance(target_id, str)
        or _ID.fullmatch(target_id) is None
    ):
        raise ConfigurationError("invalid_settings_target")
    if setting_id == MEDIA_DELETE_SETTING_ID:
        return _delete_contract(target_id)
    return SettingsContract(
        setting_id,
        "Existing media folder",
        "Storage",
        MEDIA_ENDPOINT,
        MEDIA_REFERER,
        _FIELDS,
        reader=lambda raw: _read_row(_selected(target_id, raw)),
        builder=lambda raw, changes: _payload(target_id, raw, changes),
        payload_keys=frozenset(
            {"id", "mediareplay_status", *(field.name for field in _FIELDS)}
        ),
        revision_fields=("use_usb", "addnasmediareplay"),
        verifier=lambda before, changes, after: _verify(
            target_id, before, changes, after
        ),
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )


def media_target_metadata() -> list[dict[str, Any]]:
    """Describe the editor without choosing an invented folder row."""
    return [
        {
            "id": MEDIA_SETTING_ID,
            "title": "Existing media folder",
            "section": "Storage",
            "fields": [field.metadata() for field in _FIELDS],
            "warning": _WARNING,
            "confirmation": _CONFIRMATION,
            "requires_target": True,
            "live_write_verified": False,
        },
        {
            "id": MEDIA_DELETE_SETTING_ID,
            "title": "Remove media folder",
            "section": "Storage",
            "fields": [_DELETE.metadata()],
            "warning": _DELETE_WARNING,
            "confirmation": "REMOVE MEDIA FOLDER",
            "requires_target": True,
            "live_write_verified": False,
        },
    ]


_DELETE_WARNING: Final = (
    "This removes the selected media-folder configuration and stops sharing it "
    "through the media server. The files in the folder are not deleted."
)


def _delete_contract(target_id: str) -> SettingsContract:
    def read(raw: SettingValues) -> dict[str, bool]:
        _read_row(_selected(target_id, raw))
        return {"execute": False}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        read(raw)
        if changes != {"execute": True}:
            raise ConfigurationError("invalid_settings")
        return {"id": target_id, "deleteEntry": "delete"}

    def verify(
        before: SettingValues, _changes: SettingValues, after: SettingValues
    ) -> bool:
        read(before)
        expected = {
            row["id"]: _read_row(row)
            for row in media_target_rows(MEDIA_SETTING_ID, before)
            if row["id"] != target_id
        }
        actual = {
            row["id"]: _read_row(row)
            for row in media_target_rows(MEDIA_SETTING_ID, after)
        }
        return actual == expected

    return SettingsContract(
        MEDIA_DELETE_SETTING_ID,
        "Remove media folder",
        "Storage",
        MEDIA_ENDPOINT,
        MEDIA_REFERER,
        (_DELETE,),
        reader=read,
        builder=build,
        payload_keys=frozenset({"id", "deleteEntry"}),
        revision_fields=("use_usb", "addnasmediareplay"),
        verifier=verify,
        verifier_owns_fields=True,
        warning=_DELETE_WARNING,
        confirmation="REMOVE MEDIA FOLDER",
    )


def media_index_status(raw: SettingValues) -> dict[str, Any]:
    """Expose exact indexing metrics, without inventing a time estimate."""
    status, remaining = raw.get("DLNA_IndexStatus"), raw.get("DLNA_IndexFileLeft")
    if (
        not isinstance(status, str)
        or status not in {"Finished", "Counting", "Indexing", "reScanning"}
        or not isinstance(remaining, str)
        or re.fullmatch(r"[0-9]{1,10}", remaining) is None
    ):
        raise ConfigurationError("setting_unavailable")
    return {"status": status, "files_remaining": int(remaining)}


def media_reindex_payload(raw: SettingValues) -> dict[str, str]:
    """Start indexing only with a complete enabled folder prerequisite."""
    rows = media_target_rows(MEDIA_SETTING_ID, raw)
    if not any(_read_row(row)["mediareplay_active"] for row in rows):
        raise ConfigurationError("setting_unavailable")
    return {"makeindex": "true"}


MEDIA_CREATE_SETTING_ID: Final = "storage_media_folder_create"
MEDIA_REINDEX_SETTING_ID: Final = "storage_media_reindex"
_CREATE_FIELDS: Final = tuple(
    replace(field, minimum=0) if field.kind == "text" else field for field in _FIELDS
)
_REINDEX: Final = boolean("execute", "Rebuild the media index")


def _create_read(raw: SettingValues) -> dict[str, Any]:
    rows = media_target_rows(MEDIA_SETTING_ID, raw)
    if len(rows) >= MEDIA_MAX_ROWS:
        raise ConfigurationError("settings_capacity_reached")
    return {
        "mediareplay_name": "",
        "mediareplay_folder": "",
        "mediareplay_active": False,
    }


def _create_payload(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    values = {**_create_read(raw), **changes}
    values = {field.name: field.validate(values[field.name]) for field in _FIELDS}
    name = values["mediareplay_name"]
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise ConfigurationError("invalid_settings")
    storage_absolute_path(values["mediareplay_folder"])
    for row in media_target_rows(MEDIA_SETTING_ID, raw):
        sibling = _read_row(row)
        if any(
            values[key] == sibling[key]
            for key in ("mediareplay_name", "mediareplay_folder")
        ):
            raise ConfigurationError("invalid_settings")
    # The authenticated v17 new-row template explicitly supplies both literals.
    return {
        "id": "-1",
        "mediareplay_status": "success",
        **values,
        "mediareplay_active": int(values["mediareplay_active"]),
    }


def _verify_create(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    payload = _create_payload(before, changes)
    previous = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, before)
    }
    current = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, after)
    }
    added = set(current) - set(previous)
    if len(added) != 1 or len(current) != len(previous) + 1:
        return False
    if any(current.get(identifier) != row for identifier, row in previous.items()):
        return False
    expected = {field.name: field.read(payload) for field in _FIELDS}
    return current[added.pop()] == expected


def _index_read(raw: SettingValues) -> dict[str, bool]:
    media_reindex_payload(raw)
    index = raw.get("index")
    if (
        not isinstance(index, Mapping)
        or media_index_status(index)["status"] != "Finished"
    ):
        raise ConfigurationError("setting_unavailable")
    return {"execute": False}


def _index_payload(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _index_read(raw)
    if changes != {"execute": True}:
        raise ConfigurationError("invalid_settings")
    return dict(media_reindex_payload(raw))


def _verify_index(
    before: SettingValues, _changes: SettingValues, after: SettingValues
) -> bool:
    _index_read(before)
    previous = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, before)
    }
    current = {
        row["id"]: _read_row(row) for row in media_target_rows(MEDIA_SETTING_ID, after)
    }
    index = after.get("index")
    if previous != current or not isinstance(index, Mapping):
        return False
    # A Finished -> Finished sample alone cannot prove a new job actually ran.
    return media_index_status(index)["status"] in {"Counting", "Indexing", "reScanning"}


MEDIA_CREATE_SETTINGS: Final = (
    SettingsContract(
        MEDIA_CREATE_SETTING_ID,
        "Create media folder",
        "Storage",
        MEDIA_ENDPOINT,
        MEDIA_REFERER,
        _CREATE_FIELDS,
        reader=_create_read,
        builder=_create_payload,
        payload_keys=frozenset(
            {"id", "mediareplay_status", *(field.name for field in _FIELDS)}
        ),
        revision_fields=("use_usb", "addnasmediareplay"),
        verifier=_verify_create,
        verifier_owns_fields=True,
        warning=(
            "This adds an existing folder to the media server configuration. "
            "Enabling it shares its media files on your network and starts "
            "indexing. No files are created or deleted."
        ),
        confirmation="CREATE MEDIA FOLDER",
    ),
    SettingsContract(
        MEDIA_REINDEX_SETTING_ID,
        "Rebuild media index",
        "Storage",
        MEDIA_ENDPOINT,
        MEDIA_REFERER,
        (_REINDEX,),
        reader=_index_read,
        builder=_index_payload,
        payload_keys=frozenset({"makeindex"}),
        revision_fields=("use_usb", "addnasmediareplay", "index"),
        verifier=_verify_index,
        verifier_owns_fields=True,
        warning=(
            "Rebuilding the media index may interrupt playback and increase "
            "storage activity. If indexing finishes before its state can be "
            "observed, the outcome is reported as uncertain; it is never "
            "retried automatically."
        ),
        confirmation="REBUILD MEDIA INDEX",
    ),
)
