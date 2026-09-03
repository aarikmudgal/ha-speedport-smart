"""Targeted edits of the firmware's two complete telephone assignment matrices."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

_ENDPOINT: Final = "data/PhoneNumberAssignment.json"
_REFERER: Final = "html/content/phone/phone_number.html"
_MAX_ROWS: Final = 64
_ID: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_INCOMING: Final = "telephony_incoming_assignment"
_OUTGOING: Final = "telephony_outgoing_assignment"
ASSIGNMENT_TARGET_SPECS: Final = MappingProxyType(
    {
        _INCOMING: PhoneTargetSpec(
            _INCOMING,
            "Incoming telephone number assignment",
            _ENDPOINT,
            _REFERER,
            "addglobalplug",
            "plug_name",
            (
                SettingsField(
                    "incoming",
                    "Numbers that ring this device",
                    "identifiers",
                    maximum=_MAX_ROWS,
                    dynamic_choices=True,
                ),
            ),
        ),
        _OUTGOING: PhoneTargetSpec(
            _OUTGOING,
            "Outgoing telephone number assignment",
            _ENDPOINT,
            _REFERER,
            "addglobalplug",
            "plug_name",
            (
                SettingsField(
                    "outgoing", "Outgoing number", "enum", dynamic_choices=True
                ),
                SettingsField(
                    "plug_alternative_number",
                    "Alternative outgoing number",
                    "enum",
                    dynamic_choices=True,
                    description=(
                        "Used when an Internet telephone number is unavailable. "
                        "Zero means no alternative."
                    ),
                ),
            ),
        ),
    }
)
_WARNING: Final = (
    "Changing assignments can prevent incoming or outgoing calls. Only the selected "
    "device is changed, while all other device assignments in the form are preserved."
)
_CONFIRMATION: Final = "SAVE PHONE ASSIGNMENTS"


def _id(value: object, *, zero: bool = True) -> str:
    if (
        not isinstance(value, str)
        or not _ID.fullmatch(value)
        or (not zero and int(value) == 0)
    ):
        raise ConfigurationError("settings_target_unavailable")
    return value


def _rows(value: object, key: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, Mapping) and value:
        value = [value]
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ConfigurationError("settings_inventory_unavailable")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        identifier = _id(item.get(key))
        if identifier in seen:
            raise ConfigurationError("settings_inventory_unavailable")
        seen.add(identifier)
        result.append(dict(item))
    return tuple(result)


def assignment_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Return existing global plugs without inventing a missing collection."""
    if setting_id not in ASSIGNMENT_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return _rows(raw.get("addglobalplug"), "id")


def _numbers(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    result = _rows(raw.get("addphonenumber"), "id")
    for row in result:
        _id(row["id"], zero=False)
        label = row.get("phone_number")
        kind = row.get("phone_number_type")
        if (
            not isinstance(label, str)
            or not label
            or not label.isprintable()
            or not isinstance(kind, str)
        ):
            raise ConfigurationError("settings_inventory_unavailable")
    return result


def _read(row: SettingValues, raw: SettingValues) -> dict[str, Any]:
    known = {number["id"] for number in _numbers(raw)}
    compound = _rows(row.get("sid"), "sid")
    if {item["sid"] for item in compound} != known:
        raise ConfigurationError("settings_inventory_unavailable")
    incoming = sorted(
        item["sid"] for item in compound if boolean("outg", "Incoming").read(item)
    )
    outgoing = _id(row.get("plug_outgoing"))
    alternative = _id(row.get("plug_alternative_number"))
    if outgoing not in known | {"0"} or alternative not in known | {"0"}:
        raise ConfigurationError("settings_inventory_unavailable")
    return {
        "incoming": incoming,
        "outgoing": outgoing,
        "plug_alternative_number": alternative,
    }


def _selected(setting_id: str, target_id: str, raw: SettingValues) -> dict[str, Any]:
    matching = [
        row for row in assignment_target_rows(setting_id, raw) if row["id"] == target_id
    ]
    if len(matching) != 1:
        raise ConfigurationError("settings_target_unavailable")
    return matching[0]


def _changed(
    row: SettingValues, raw: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    values = {**_read(row, raw), **changes}
    numbers = {number["id"]: number for number in _numbers(raw)}
    values["incoming"] = sorted(values["incoming"])
    selected = numbers.get(values["outgoing"])
    has_alternative = (
        selected is not None
        and selected["phone_number_type"] == "IP"
        and len(numbers) > 1
    )
    if "plug_alternative_number" in changes and not has_alternative:
        raise ConfigurationError("inactive_settings_field")
    if has_alternative and values["plug_alternative_number"] == values["outgoing"]:
        raise ConfigurationError("invalid_settings")
    return values


def _payload(
    setting_id: str, target_id: str, raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _selected(setting_id, target_id, raw)
    result: dict[str, str | int | bool] = {}
    for row in assignment_target_rows(setting_id, raw):
        values = (
            _changed(row, raw, changes) if row["id"] == target_id else _read(row, raw)
        )
        identifier = row["id"]
        if setting_id == _INCOMING:
            for number in _numbers(raw):
                result[f"incoming[{identifier}][{number['id']}]"] = int(
                    number["id"] in values["incoming"]
                )
        else:
            result[f"outgoing[{identifier}]"] = values["outgoing"]
            result[f"plug_alternative_number[{identifier}]"] = values[
                "plug_alternative_number"
            ]
    return result


def _choices(
    setting_id: str, raw: SettingValues
) -> dict[str, tuple[tuple[str, str], ...]]:
    values = tuple((number["id"], number["phone_number"]) for number in _numbers(raw))
    if setting_id == _INCOMING:
        return {"incoming": values}
    return {
        "outgoing": (("0", "Automatic"), *values),
        "plug_alternative_number": (("0", "No alternative"), *values),
    }


def _verify(
    setting_id: str,
    target_id: str,
    before: SettingValues,
    changes: SettingValues,
    after: SettingValues,
) -> bool:
    if {row["id"]: row for row in _numbers(before)} != {
        row["id"]: row for row in _numbers(after)
    }:
        return False
    expected = {
        row["id"]: (
            _changed(row, before, changes)
            if row["id"] == target_id
            else _read(row, before),
            row.get("plug_name"),
            row.get("plug_type"),
        )
        for row in assignment_target_rows(setting_id, before)
    }
    actual = {
        row["id"]: (_read(row, after), row.get("plug_name"), row.get("plug_type"))
        for row in assignment_target_rows(setting_id, after)
    }
    return actual == expected


def assignment_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Resolve one of two fixed matrix forms, bound to a current exact plug ID."""
    spec = ASSIGNMENT_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    target_id = _id(target_id)

    def read(raw: SettingValues) -> dict[str, Any]:
        values = _read(_selected(setting_id, target_id, raw), raw)
        return {item.name: values[item.name] for item in spec.fields}

    def validate(raw: SettingValues, payload: SettingValues) -> bool:
        rows = assignment_target_rows(setting_id, raw)
        if setting_id == _INCOMING:
            keys = {
                f"incoming[{row['id']}][{number['id']}]"
                for row in rows
                for number in _numbers(raw)
            }
        else:
            keys = {
                f"{name}[{row['id']}]"
                for row in rows
                for name in ("outgoing", "plug_alternative_number")
            }
        return set(payload) == keys

    return SettingsContract(
        spec.id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        reader=read,
        builder=lambda raw, changes: _payload(setting_id, target_id, raw, changes),
        field_choices=lambda raw: _choices(setting_id, raw),
        payload_validator=validate,
        revision_fields=("addglobalplug", "addphonenumber"),
        verifier=lambda before, changes, after: _verify(
            setting_id, target_id, before, changes, after
        ),
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )


def assignment_target_metadata() -> list[dict[str, Any]]:
    """Describe actual matrix forms without exposing current devices or numbers."""
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "section": "Telephony",
            "fields": [item.metadata() for item in spec.fields],
            "warning": _WARNING,
            "confirmation": _CONFIRMATION,
            "requires_target": True,
            "live_write_verified": False,
        }
        for spec in ASSIGNMENT_TARGET_SPECS.values()
    ]
