"""Closed port-blocking CRUD using native full forms and exact device compounds."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_rule_devices import (
    MAX_RULE_DEVICES,
    rule_devices,
    rule_id,
    rule_rows,
    rule_selection,
    rule_selection_payload,
)

if TYPE_CHECKING:
    from .configuration import SettingValues
    from .configuration_rule_devices import RuleDevices

_ENDPOINT: Final = "data/ExtendedRules.json"
_REFERER: Final = "html/content/internet/portblocking.html"
_COLLECTION: Final = "addextra"
_INVENTORY: Final = "extrarule_addmdevice"
_MAX_RULES: Final = 64
_MAX_PORT: Final = 65535
_MAX_CHARACTER: Final = 255
_PORT_LIST: Final = re.compile(
    r"[0-9]{1,5}(?:-[0-9]{1,5})?(?:,[0-9]{1,5}(?:-[0-9]{1,5})?)*"
)
_NAME: Final = SettingsField("extrule_name", "Rule name", "text", maximum=20)
_ACTIVE: Final = boolean("extendedrule_active", "Enable port blocking")
_TCP: Final = SettingsField(
    "extrule_tcp",
    "Blocked TCP ports",
    "text",
    maximum=255,
    description=(
        "Comma-separated ports or ranges, for example 80,443,8000-8080. "
        "0-65535 blocks all TCP ports."
    ),
)
_UDP: Final = SettingsField(
    "extrule_udp",
    "Blocked UDP ports",
    "text",
    maximum=255,
    description="Comma-separated ports or ranges. Leave empty to preserve UDP access.",
)
_DEVICES: Final = SettingsField(
    "selected_devices",
    "Devices subject to this rule",
    "identifiers",
    maximum=MAX_RULE_DEVICES,
    dynamic_choices=True,
)
_DELETE: Final = boolean("delete_entry", "Delete this exact port-blocking rule")
_FIELDS: Final = (_NAME, _ACTIVE, _TCP, _UDP, _DEVICES)
_WARNING: Final = (
    "This rule blocks the selected ports for the exact selected devices and can "
    "interrupt Internet access. Unrelated rules and device settings are preserved."
)


@dataclass(frozen=True, slots=True)
class PortBlockingTargetSpec:
    """Describe a closed existing-rule target to the shared dispatcher."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


PORT_BLOCKING_TARGET_SPECS: Final = MappingProxyType(
    {
        "port_blocking_edit": PortBlockingTargetSpec(
            "port_blocking_edit",
            "Edit port-blocking rule",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "extrule_name",
            _FIELDS,
        ),
        "port_blocking_delete": PortBlockingTargetSpec(
            "port_blocking_delete",
            "Delete port-blocking rule",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "extrule_name",
            (_DELETE,),
        ),
    }
)


def _name(value: object) -> str:
    value = _NAME.validate(value)
    if (
        type(value) is not str
        or not value
        or any(ord(char) > _MAX_CHARACTER or char in "<>" for char in value)
    ):
        raise ConfigurationError("invalid_port_blocking_name")
    return value


def _ports(field: SettingsField, value: object) -> str:
    value = field.validate(value)
    if type(value) is not str or (value and not _PORT_LIST.fullmatch(value)):
        raise ConfigurationError("invalid_blocked_ports")
    intervals: list[tuple[int, int]] = []
    for part in value.split(",") if value else ():
        values = part.split("-")
        start, end = int(values[0]), int(values[-1])
        if end > _MAX_PORT or (len(values) > 1 and start >= end):
            raise ConfigurationError("invalid_blocked_ports")
        if any(start <= last and end >= first for first, last in intervals):
            raise ConfigurationError("duplicate_blocked_ports")
        intervals.append((start, end))
    return value


def _devices(raw: SettingValues) -> RuleDevices:
    return rule_devices(raw, _INVENTORY)


def _rules(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    devices = _devices(raw)
    result = []
    seen: set[str] = set()
    for row in rule_rows(raw.get(_COLLECTION, []), _MAX_RULES):
        identifier = rule_id(row.get("id"))
        selected = rule_selection(row, devices)
        tcp, udp = (
            _ports(_TCP, row.get("extrule_tcp")),
            _ports(_UDP, row.get("extrule_udp")),
        )
        # Static v12 has no selected preset option; the first (custom) option is 0.
        preset = row.get("portsp_template", "0")
        if (
            identifier in seen
            or not selected
            or not (tcp or udp)
            or type(preset) is not str
            or preset not in {str(index) for index in range(14)}
        ):
            raise ConfigurationError("ambiguous_port_blocking_rule")
        seen.add(identifier)
        result.append(
            {
                "id": identifier,
                "extrule_name": _name(row.get("extrule_name")),
                "extendedrule_active": _ACTIVE.read(row),
                "extrule_tcp": tcp,
                "extrule_udp": udp,
                "selected_devices": sorted(selected),
                "portsp_template": preset,
            }
        )
    return tuple(result)


def _map(raw: SettingValues) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _rules(raw)}


def _choices(raw: SettingValues) -> dict[str, tuple[tuple[str, str], ...]]:
    return {"selected_devices": _devices(raw).choices}


def _revision(raw: SettingValues) -> dict[str, object]:
    return {"devices": _devices(raw).identities}


def _proposed(
    raw: SettingValues, changes: SettingValues, current: SettingValues | None = None
) -> dict[str, Any]:
    row = {
        **(
            current
            or {
                "id": "-1",
                "extrule_name": "",
                "extendedrule_active": False,
                "extrule_tcp": "",
                "extrule_udp": "",
                "selected_devices": [],
                "portsp_template": "0",
            }
        ),
        **changes,
    }
    row["extrule_name"] = _name(row["extrule_name"])
    row["extrule_tcp"], row["extrule_udp"] = (
        _ports(_TCP, row["extrule_tcp"]),
        _ports(_UDP, row["extrule_udp"]),
    )
    selected = _DEVICES.validate(row["selected_devices"])
    if (
        not isinstance(selected, list)
        or not selected
        or not set(selected) <= _devices(raw).sids
        or not (row["extrule_tcp"] or row["extrule_udp"])
    ):
        raise ConfigurationError("incomplete_port_blocking_rule")
    row["selected_devices"] = sorted(selected)
    return row


def _wire(
    raw: SettingValues, row: SettingValues, ordinal: int
) -> dict[str, str | int | bool]:
    return {
        **{
            key: row[key]
            for key in (
                "id",
                "extrule_name",
                "extrule_tcp",
                "extrule_udp",
                "portsp_template",
            )
        },
        "extendedrule_active": "1" if row["extendedrule_active"] else "0",
        **rule_selection_payload(
            _devices(raw), frozenset(row["selected_devices"]), ordinal
        ),
    }


def _read_create(raw: SettingValues) -> dict[str, Any]:
    _rules(raw)
    return {
        "extrule_name": "",
        "extendedrule_active": False,
        "extrule_tcp": "",
        "extrule_udp": "",
        "selected_devices": [],
    }


def _build_create(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    rows = _rules(raw)
    if len(rows) >= _MAX_RULES:
        raise ConfigurationError("port_blocking_rule_limit")
    return _wire(raw, _proposed(raw, changes), len(rows) + 1)


def _payload_changes(
    raw: SettingValues, payload: SettingValues, ordinal: int
) -> dict[str, Any]:
    changes = {
        field.name: payload[field.name]
        for field in _FIELDS
        if field.name != "selected_devices"
    }
    changes["extendedrule_active"] = _ACTIVE.read(changes)
    selected = []
    for index, (sid, _, _) in enumerate(_devices(raw).identities, 1):
        suffix = f"[{index}{ordinal}]"
        if payload.get("sid" + suffix) != sid or payload.get(
            "mdevice_name" + suffix
        ) not in {"0", "1"}:
            raise ConfigurationError("invalid_rule_device_payload")
        if payload["mdevice_name" + suffix] == "1":
            selected.append(sid)
    changes["selected_devices"] = selected
    return changes


def _validate_create(raw: SettingValues, payload: SettingValues) -> bool:
    try:
        return _build_create(
            raw, _payload_changes(raw, payload, len(_rules(raw)) + 1)
        ) == dict(payload)
    except (ConfigurationError, KeyError, TypeError):
        return False


def _stable(before: SettingValues, after: SettingValues) -> bool:
    return set(_devices(before).identities) == set(_devices(after).identities)


def _verify_create(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _build_create(before, changes)
        previous, current = _map(before), _map(after)
        created = current.keys() - previous.keys()
        if (
            not _stable(before, after)
            or len(created) != 1
            or len(current) != len(previous) + 1
            or any(current.get(key) != row for key, row in previous.items())
        ):
            return False
        identifier = next(iter(created))
        return current[identifier] == {**_proposed(before, changes), "id": identifier}
    except ConfigurationError:
        return False


def port_blocking_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """Return only current stable rule IDs and labels for target selection."""
    if setting_id not in PORT_BLOCKING_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        {"id": row["id"], "extrule_name": row["extrule_name"]} for row in _rules(raw)
    )


def port_blocking_target_metadata() -> list[dict[str, Any]]:
    """Expose static metadata without inventing an existing selected rule."""
    return [
        {
            **port_blocking_target_contract(spec.id, "0").metadata(),
            "requires_target": True,
        }
        for spec in PORT_BLOCKING_TARGET_SPECS.values()
    ]


def port_blocking_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind editing or deletion to an exact current outer rule ID."""
    spec = PORT_BLOCKING_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    target_id = rule_id(target_id)
    deleting = setting_id == "port_blocking_delete"

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _map(raw).get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return row

    def read(raw: SettingValues) -> dict[str, Any]:
        if deleting:
            return {"delete_entry": target_id not in _map(raw)}
        row = selected(raw)
        return {field.name: row[field.name] for field in _FIELDS}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        current = selected(raw)
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        ordinal = next(
            index for index, row in enumerate(_rules(raw), 1) if row["id"] == target_id
        )
        return _wire(raw, _proposed(raw, changes, current), ordinal)

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            if deleting:
                changes = {"delete_entry": True}
            else:
                ordinal = next(
                    index
                    for index, row in enumerate(_rules(raw), 1)
                    if row["id"] == target_id
                )
                changes = _payload_changes(raw, payload, ordinal)
            return build(raw, changes) == dict(payload)
        except (ConfigurationError, KeyError, TypeError, StopIteration):
            return False

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            expected = _map(before)
            if deleting:
                expected.pop(target_id)
            else:
                expected[target_id] = _proposed(before, changes, selected(before))
            return _stable(before, after) and _map(after) == expected
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Network",
        _ENDPOINT,
        _REFERER,
        spec.fields,
        reader=read,
        builder=build,
        payload_validator=validate_payload,
        verifier=verify,
        field_choices=None if deleting else _choices,
        revision_values=_revision,
        revision_fields=(_COLLECTION,),
        warning=_WARNING,
        confirmation="DELETE PORT BLOCKING" if deleting else "SAVE PORT BLOCKING",
    )


PORT_BLOCKING_SETTINGS: Final = (
    SettingsContract(
        "port_blocking_create",
        "Add port-blocking rule",
        "Network",
        _ENDPOINT,
        _REFERER,
        _FIELDS,
        reader=_read_create,
        builder=_build_create,
        payload_validator=_validate_create,
        verifier=_verify_create,
        verifier_owns_fields=True,
        field_choices=_choices,
        revision_values=_revision,
        revision_fields=(_COLLECTION,),
        warning=_WARNING,
        confirmation="ADD PORT BLOCKING",
    ),
)
