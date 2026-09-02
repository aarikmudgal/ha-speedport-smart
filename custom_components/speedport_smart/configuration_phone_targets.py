"""Exact target-bound telephone forms with ordered assignment preservation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
    normalize_configuration_payload,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_PHONE: Final = "html/content/phone/"
_MAX_ROWS: Final = 64  # Defensive response bound, not a claimed firmware capacity.
_MAX_LABEL: Final = 128
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_NAME: Final = re.compile(r"[\x20-\x3B\x3D\x3F-\x7E\x80-\xFF]+")
_PASSWORD: Final = re.compile(r"[0-9A-Za-z!'$&~()=*+,._-]{8,16}")
_BUSY: Final = boolean("reject_on_busy", "Reject incoming calls when busy")
_CLIR: Final = boolean("clir", "Hide caller ID for outgoing calls")
_LINE: Final = choice(
    "line", "Parallel calls", (("0", "Multiple calls"), ("1", "Single call"))
)
_PLUG_TYPE: Final = choice(
    "plug_type",
    "Connected equipment",
    (
        ("0", "Telephone"),
        ("1", "Answering machine"),
        ("2", "Fax"),
        ("3", "Multi-function device"),
    ),
)
_PLUG_CALL_WAITING: Final = boolean("plug_use_out_of_order_signaling", "Call waiting")
_DECT_CALL_WAITING: Final = boolean("dect_cws", "Call waiting")
_IP_STATUS: Final = choice(
    "ipclient_status",
    "IP phone state",
    (("0", "Disconnected"), ("1", "Connected"), ("2", "Locked")),
)
_IP_PASSWORD: Final = SettingsField(
    "ipclient_password",
    "IP phone password",
    "secret",
    minimum=8,
    maximum=16,
    description=(
        "Leave blank only when the router supplies a readable current password. "
        "Masked or missing passwords must be re-entered."
    ),
)
_OUTGOING: Final = SettingsField(
    "plug_outgoing",
    "Number for outgoing calls",
    "enum",
    dynamic_choices=True,
)
_INCOMING: Final = SettingsField(
    "ring_incoming",
    "Numbers that ring this device",
    "identifiers",
    minimum=0,
    maximum=_MAX_ROWS,
    dynamic_choices=True,
    description=(
        "Selecting no numbers prevents this device from ringing for incoming calls."
    ),
)


@dataclass(frozen=True, slots=True)
class PhoneTargetSpec:
    """One closed page/collection binding for the client target dispatcher."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


PHONE_TARGET_SPECS: Final = MappingProxyType(
    {
        "telephony_line_options": PhoneTargetSpec(
            "telephony_line_options",
            "Telephone number call options",
            "data/PhoneLineset.json",
            _PHONE + "phone_lineset.html",
            "addphonenumber",
            "phone_number",
            (_LINE, _BUSY, _CLIR),
        ),
        "telephony_analog_socket": PhoneTargetSpec(
            "telephony_analog_socket",
            "Analog telephone socket",
            "data/PhonePlugs.json",
            _PHONE + "phone_analog.html",
            "phone_plugs",
            "plug_name",
            (
                SettingsField(
                    "plug_name", "Socket name", "text", minimum=1, maximum=22
                ),
                _PLUG_TYPE,
                _PLUG_CALL_WAITING,
                _OUTGOING,
                _INCOMING,
            ),
        ),
        "telephony_dect_handset": PhoneTargetSpec(
            "telephony_dect_handset",
            "DECT handset settings",
            "data/DECTStation.json",
            _PHONE + "phone_dect_mobiles.html",
            "adddect",
            "dect_mobile_name",
            (
                SettingsField(
                    "dect_mobile_name", "Handset name", "text", minimum=1, maximum=15
                ),
                _DECT_CALL_WAITING,
                _OUTGOING,
                _INCOMING,
            ),
        ),
        "telephony_ip_phone": PhoneTargetSpec(
            "telephony_ip_phone",
            "Existing IP phone settings",
            "data/IPPBX.json",
            _PHONE + "phone_ippbx.html",
            "addipclient",
            "ipclient_name",
            (
                SettingsField(
                    "ipclient_name", "IP phone name", "text", minimum=1, maximum=15
                ),
                _IP_PASSWORD,
                _OUTGOING,
                _INCOMING,
            ),
        ),
    }
)
_WARNING: Final = (
    "Changing these settings may interrupt calls or prevent incoming calls. "
    "Only the selected existing device or number is edited. Other numbers and "
    "assignments are preserved and checked by a fresh read."
)
_CONFIRMATION: Final = "SAVE PHONE SETTINGS"


def phone_target_metadata() -> list[dict[str, Any]]:
    """Describe target-required editors without reading private telephone data."""
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
        for spec in PHONE_TARGET_SPECS.values()
    ]


def _identifier(value: object) -> str:
    if type(value) is int and value >= 0:
        value = str(value)
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ConfigurationError("settings_target_unavailable")
    return value


def _rows(value: object, *, identity: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, Mapping) and value:
        value = [value]
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ConfigurationError("settings_inventory_unavailable")
    result = []
    identifiers = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        row = normalize_configuration_payload(raw)
        identifier = _identifier(row.get(identity))
        if identifier in identifiers:
            raise ConfigurationError("settings_inventory_unavailable")
        identifiers.add(identifier)
        row[identity] = identifier
        result.append(row)
    return tuple(result)


def phone_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Return exact ordered rows; missing collections never imply empty inventory."""
    spec = PHONE_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    return _rows(raw.get(spec.collection), identity="id")


def _selected(
    spec: PhoneTargetSpec, target_id: str, raw: SettingValues
) -> tuple[int, dict[str, Any]]:
    rows = phone_target_rows(spec.id, raw)
    matches = [
        (index, row) for index, row in enumerate(rows, 1) if row["id"] == target_id
    ]
    if len(matches) != 1:
        raise ConfigurationError("stale_settings")
    return matches[0]


def _assignments(row: SettingValues) -> tuple[dict[str, Any], ...]:
    # Private configuration decoding preserves compound SID fields. Flattened
    # SID strings cannot prove incoming assignments and must never be submitted.
    numbers = _rows(row.get("sid"), identity="sid")
    for number in numbers:
        number["ring_incoming"] = boolean("ring_incoming", "Incoming").read(number)
        # The automatic outgoing choice is the literal zero, never an invented number.
        if number["sid"] == "0":
            raise ConfigurationError("settings_inventory_unavailable")
    return numbers


def _read_row(spec: PhoneTargetSpec, row: SettingValues) -> dict[str, Any]:
    if spec.id == "telephony_line_options":
        return {item.name: item.read(row) for item in spec.fields}
    values = {
        item.name: item.read(row)
        for item in spec.fields
        if item.kind not in {"secret", "identifiers"} and not item.dynamic_choices
    }
    if _NAME.fullmatch(str(values[spec.label_key])) is None:
        raise ConfigurationError("invalid_settings")
    numbers = _assignments(row)
    outgoing = _identifier(row.get("plug_outgoing"))
    if outgoing != "0" and outgoing not in {number["sid"] for number in numbers}:
        raise ConfigurationError("settings_inventory_unavailable")
    values["plug_outgoing"] = outgoing
    values["ring_incoming"] = [
        number["sid"] for number in numbers if number["ring_incoming"]
    ]
    return values


def _choices(
    spec: PhoneTargetSpec, target_id: str, raw: SettingValues
) -> dict[str, tuple[tuple[str, str], ...]]:
    if spec.id == "telephony_line_options":
        return {}
    _, row = _selected(spec, target_id, raw)
    inventory_key = (
        "addphonenumber"
        if spec.id == "telephony_analog_socket"
        else "outgoing_addphonenumber"
    )
    inventory = _rows(raw.get(inventory_key), identity="sid")
    labels = {number["sid"]: number.get("phone_number") for number in inventory}
    assignments = _assignments(row)
    if set(labels) != {number["sid"] for number in assignments}:
        raise ConfigurationError("settings_inventory_unavailable")
    choices = []
    for number in assignments:
        label = labels[number["sid"]]
        if (
            not isinstance(label, str)
            or not label
            or len(label) > _MAX_LABEL
            or not label.isprintable()
        ):
            label = f"Telephone number {number['sid']}"
        choices.append((number["sid"], label))
    return {
        "ring_incoming": tuple(choices),
        "plug_outgoing": (("0", "Automatic"), *choices),
    }


def _changed_row(
    spec: PhoneTargetSpec, row: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    values = {**_read_row(spec, row), **changes}
    if spec.id == "telephony_line_options":
        # The firmware click handler forces the radio whenever busy rejection changes.
        if "reject_on_busy" in changes:
            derived = "1" if values["reject_on_busy"] else "0"
            if "line" in changes and changes["line"] != derived:
                raise ConfigurationError("invalid_settings")
            values["line"] = derived
        if values["reject_on_busy"] and values["line"] != "1":
            raise ConfigurationError("invalid_settings")
        return values
    if _NAME.fullmatch(values[spec.label_key]) is None:
        raise ConfigurationError("invalid_settings")
    numbers = _assignments(row)
    known = {number["sid"] for number in numbers}
    incoming = values["ring_incoming"]
    if (
        not isinstance(incoming, list)
        or any(type(value) is not str for value in incoming)
        or len(set(incoming)) != len(incoming)
        or not set(incoming) <= known
        or values["plug_outgoing"] not in known | {"0"}
    ):
        raise ConfigurationError("invalid_settings")
    values["ring_incoming"] = sorted(incoming)
    if (
        spec.id == "telephony_analog_socket"
        and changes.get("plug_type") == "0"
        and "plug_use_out_of_order_signaling" not in changes
    ):
        # The firmware's equipment-type click handler defaults telephone call
        # waiting to enabled; the user can explicitly override it afterwards.
        values["plug_use_out_of_order_signaling"] = True
    if (
        spec.id == "telephony_analog_socket"
        and values["plug_type"] != "0"
        and "plug_use_out_of_order_signaling" in changes
    ):
        raise ConfigurationError("inactive_settings_field")
    return values


def _payload(
    spec: PhoneTargetSpec, target_id: str, raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    ordinal, row = _selected(spec, target_id, raw)
    values = _changed_row(spec, row, changes)
    result: dict[str, str | int | bool] = {}
    if spec.id == "telephony_line_options":
        for index, sibling in enumerate(phone_target_rows(spec.id, raw), 1):
            current = values if sibling["id"] == target_id else _read_row(spec, sibling)
            result[f"id[{index}]"] = sibling["id"]
            for name in ("line", "reject_on_busy", "clir"):
                value = current[name]
                result[f"{name}[{index}]"] = (
                    int(value) if type(value) is bool else value
                )
        return result
    result.update(id=target_id, plug_outgoing=values["plug_outgoing"])
    result[spec.label_key] = values[spec.label_key]
    if spec.id == "telephony_analog_socket":
        result["plug_type"] = values["plug_type"]
        if values["plug_type"] == "0":
            result["plug_use_out_of_order_signaling"] = int(
                values["plug_use_out_of_order_signaling"]
            )
    elif spec.id == "telephony_dect_handset":
        result["dect_cws"] = int(values["dect_cws"])
    else:
        password = (
            _IP_PASSWORD.validate(changes["ipclient_password"])
            if "ipclient_password" in changes
            else _IP_PASSWORD.read(row)
        )
        if not isinstance(password, str) or _PASSWORD.fullmatch(password) is None:
            raise ConfigurationError("invalid_settings")
        # phone_ippbx.js prevalidate requires at least two character classes.
        if (
            sum(
                bool(re.search(pattern, password))
                for pattern in (r"[0-9]", r"[a-z]", r"[A-Z]", r"[!'$&~()=*+,._-]")
            )
            < 2  # noqa: PLR2004 - Firmware's explicit password-class threshold.
        ):
            raise ConfigurationError("invalid_settings")
        result["ipclient_password"] = password
        status = _IP_STATUS.read(row)
        if not isinstance(status, str):
            raise ConfigurationError("invalid_settings")
        result["ipclient_status"] = status
    incoming = set(values["ring_incoming"])
    numbers = _assignments(row)
    result["selectall_deselectnone"] = int(
        bool(numbers) and len(incoming) == len(numbers)
    )
    for index, number in enumerate(numbers, 1):
        # cloneWithIDSuffix concatenates outer/inner template ordinals before
        # removeTemplateId strips the final inner suffix: [1] -> [12][2] -> [12].
        suffix = f"{ordinal}{index}"
        result[f"sid[{suffix}]"] = number["sid"]
        result[f"ring_incoming[{suffix}]"] = int(number["sid"] in incoming)
    return result


def _payload_keys(
    spec: PhoneTargetSpec, target_id: str, raw: SettingValues
) -> set[str]:
    ordinal, row = _selected(spec, target_id, raw)
    if spec.id == "telephony_line_options":
        return {
            f"{name}[{index}]"
            for index, _ in enumerate(phone_target_rows(spec.id, raw), 1)
            for name in ("id", "line", "clir", "reject_on_busy")
        }
    keys = {"id", spec.label_key, "plug_outgoing", "selectall_deselectnone"}
    keys.update(
        f"{name}[{ordinal}{index}]"
        for index, _ in enumerate(_assignments(row), 1)
        for name in ("sid", "ring_incoming")
    )
    if spec.id == "telephony_analog_socket":
        keys.update(("plug_type", "plug_use_out_of_order_signaling"))
    elif spec.id == "telephony_dect_handset":
        keys.add("dect_cws")
    else:
        keys.update(("ipclient_password", "ipclient_status"))
    return keys


def _verify(
    spec: PhoneTargetSpec,
    target_id: str,
    before: SettingValues,
    changes: SettingValues,
    after: SettingValues,
) -> bool:
    expected = {}
    actual = {}
    for row in phone_target_rows(spec.id, before):
        values = (
            _changed_row(spec, row, changes)
            if row["id"] == target_id
            else _read_row(spec, row)
        )
        values.pop("ipclient_password", None)
        if "ring_incoming" in values:
            values["ring_incoming"] = sorted(values["ring_incoming"])
        expected[row["id"]] = (values, _identity_dependencies(spec, row))
    for row in phone_target_rows(spec.id, after):
        values = _read_row(spec, row)
        if "ring_incoming" in values:
            values["ring_incoming"] = sorted(values["ring_incoming"])
        actual[row["id"]] = (values, _identity_dependencies(spec, row))
    return actual == expected


def _identity_dependencies(spec: PhoneTargetSpec, row: SettingValues) -> dict[str, Any]:
    """Do not verify a reused target ID belonging to a different telephone number."""
    if spec.id == "telephony_line_options":
        return {
            name: row.get(name) for name in ("sid", "phone_number", "phone_number_type")
        }
    return {}


def phone_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind one exact existing row while preserving the complete submitted form."""
    spec = PHONE_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    if type(target_id) is not str:
        raise ConfigurationError("settings_target_unavailable")
    target_id = _identifier(target_id)

    def read(raw: SettingValues) -> dict[str, Any]:
        return _read_row(spec, _selected(spec, target_id, raw)[1])

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        allowed = _payload_keys(spec, target_id, raw)
        if spec.id == "telephony_analog_socket" and payload.get("plug_type") != "0":
            allowed.remove("plug_use_out_of_order_signaling")
        return set(payload) == allowed

    def expected(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
        result = _changed_row(spec, _selected(spec, target_id, raw)[1], changes)
        result.pop("ipclient_password", None)
        return result

    return SettingsContract(
        spec.id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        reader=read,
        builder=lambda raw, changes: _payload(spec, target_id, raw, changes),
        revision_fields=(spec.collection, "addphonenumber", "outgoing_addphonenumber")
        if spec.id != "telephony_line_options"
        else (spec.collection,),
        payload_validator=validate_payload,
        field_choices=(lambda raw: _choices(spec, target_id, raw))
        if spec.id != "telephony_line_options"
        else None,
        expected_values=expected,
        verifier=lambda before, changes, after: _verify(
            spec, target_id, before, changes, after
        ),
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )
