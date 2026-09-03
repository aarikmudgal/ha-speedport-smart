"""Exact full-matrix DECT handset phonebook assignments."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

PHONEBOOK_ASSIGN_SETTING_ID: Final = "telephony_handset_phonebook"
PHONEBOOK_LIST_ENDPOINT: Final = "data/PhoneOnlbuch.json"
_REFERER: Final = "html/content/phone/phone_book_assign.html"
_MAX_ROWS: Final = 5
_MAX_LABEL: Final = 128
_ID: Final = re.compile(r"[0-9]{1,3}")
_FIELD: Final = SettingsField(
    "phonebook", "Assigned phonebook", "enum", dynamic_choices=True
)
_WARNING: Final = (
    "This changes the phonebook available on the selected handset. Other "
    "handset assignments are preserved. No contacts are deleted."
)


@dataclass(frozen=True, slots=True)
class PhonebookAssignmentSpec(PhoneTargetSpec):
    """Assignment writes and handset reads use separate fixed endpoints."""

    read_endpoint: str


PHONEBOOK_ASSIGN_TARGET_SPECS: Final = MappingProxyType(
    {
        PHONEBOOK_ASSIGN_SETTING_ID: PhonebookAssignmentSpec(
            PHONEBOOK_ASSIGN_SETTING_ID,
            "Handset phonebook assignment",
            "data/DECTSettings.json",
            _REFERER,
            "adddectmobiles",
            "dect_mobile_name",
            (_FIELD,),
            "data/DECTMobiles.json",
        )
    }
)


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ConfigurationError("settings_inventory_unavailable")
    return value


def _rows(raw: SettingValues, key: str, identity: str) -> tuple[dict[str, Any], ...]:
    names = [name for name in raw if str(name).casefold() == key]
    if names != [key]:
        raise ConfigurationError("settings_inventory_unavailable")
    value = raw[key]
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ConfigurationError("settings_inventory_unavailable")
    seen = set()
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        identifier = _identifier(item.get(identity))
        if identifier in seen:
            raise ConfigurationError("settings_inventory_unavailable")
        seen.add(identifier)
        result.append(dict(item))
    return tuple(result)


def _books(raw: SettingValues) -> tuple[tuple[str, str], ...]:
    source = raw.get("phonebooks")
    if not isinstance(source, Mapping):
        raise ConfigurationError("settings_prerequisites_unavailable")
    result = []
    for row in _rows(source, "addonlbuchentry", "onlbuch_nr"):
        label = row.get("onlbuch_name")
        if (
            not isinstance(label, str)
            or not 0 < len(label) <= _MAX_LABEL
            or not label.isprintable()
        ):
            raise ConfigurationError("settings_inventory_unavailable")
        result.append((row["onlbuch_nr"], label))
    if len(result) <= 1:
        raise ConfigurationError("setting_unavailable")
    return tuple(result)


def phonebook_assignment_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Require every existing handset assignment to refer to a known current book."""
    if setting_id != PHONEBOOK_ASSIGN_SETTING_ID:
        raise ConfigurationError("setting_unavailable")
    books = {value for value, _label in _books(raw)}
    rows = _rows(raw, "adddectmobiles", "id")
    if any(_identifier(row.get("dect_onlbuch")) not in books for row in rows):
        raise ConfigurationError("settings_inventory_unavailable")
    return rows


def phonebook_assignment_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Change one handset while submitting the firmware's complete radio matrix."""
    if setting_id != PHONEBOOK_ASSIGN_SETTING_ID:
        raise ConfigurationError("setting_unavailable")
    _identifier(target_id)

    def read(raw: SettingValues) -> dict[str, str]:
        matches = [
            row
            for row in phonebook_assignment_rows(setting_id, raw)
            if row["id"] == target_id
        ]
        if len(matches) != 1:
            raise ConfigurationError("settings_target_unavailable")
        return {"phonebook": matches[0]["dect_onlbuch"]}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        read(raw)
        value = changes.get("phonebook")
        if value not in {key for key, _label in _books(raw)}:
            raise ConfigurationError("invalid_settings")
        return {
            f"dect_onlbuch_{row['id']}": value
            if row["id"] == target_id
            else row["dect_onlbuch"]
            for row in phonebook_assignment_rows(setting_id, raw)
        }

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        expected = {
            row["id"]: dict(row)
            for row in phonebook_assignment_rows(setting_id, before)
        }
        expected[target_id]["dect_onlbuch"] = changes["phonebook"]
        actual = {
            row["id"]: row for row in phonebook_assignment_rows(setting_id, after)
        }
        return actual == expected and _books(before) == _books(after)

    return SettingsContract(
        setting_id,
        "Handset phonebook assignment",
        "Telephony",
        "data/DECTSettings.json",
        _REFERER,
        (_FIELD,),
        read_endpoint="data/DECTMobiles.json",
        reader=read,
        builder=build,
        payload_validator=lambda raw, payload: (
            set(payload)
            == {
                f"dect_onlbuch_{row['id']}"
                for row in phonebook_assignment_rows(setting_id, raw)
            }
        ),
        field_choices=lambda raw: {"phonebook": _books(raw)},
        revision_fields=("adddectmobiles", "phonebooks"),
        verifier=verify,
        warning=_WARNING,
        confirmation="ASSIGN HANDSET PHONEBOOK",
    )


def phonebook_assignment_metadata() -> list[dict[str, Any]]:
    """Describe the private selector without current book or handset labels."""
    return [
        {
            "id": PHONEBOOK_ASSIGN_SETTING_ID,
            "title": "Handset phonebook assignment",
            "section": "Telephony",
            "fields": [_FIELD.metadata()],
            "warning": _WARNING,
            "confirmation": "ASSIGN HANDSET PHONEBOOK",
            "requires_target": True,
            "live_write_verified": False,
        }
    ]
