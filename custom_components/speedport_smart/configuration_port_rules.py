"""
Closed port-forward forms with exact target and complete collection proof.

Only synthetic tests exercise writes. No code here performs network I/O.
"""

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
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_ENDPOINT: Final = "data/PortuwMain.json"
_REFERER: Final = "html/content/internet/portforwarding.html"
_COLLECTION: Final = "addportuw"
_MAX_RULES: Final = 32
_MAX_RANGES: Final = 32
_MAX_DEVICES: Final = 253
_MAX_PORT: Final = 65535
_MAX_CHARACTER: Final = 255
_MAX_LABEL: Final = 256
_FIRST_PRINTABLE: Final = 32
_DELETE_CHARACTER: Final = 127
_MAX_RESERVED_TEXT: Final = 8192
_ID: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_SID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_MAC: Final = re.compile(
    r"(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}"
)
_RESERVED: Final = re.compile(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*")
_NAME: Final = SettingsField("portuw_name", "Rule name", "text", maximum=20)
_DEVICE: Final = SettingsField(
    "portuw_device", "Destination device", "enum", dynamic_choices=True
)
_ACTIVE: Final = boolean("portuw_active", "Enable forwarding")
_DELETE: Final = boolean("delete_entry", "Delete this exact forwarding rule")
_DELETE_RANGE: Final = boolean("delete_entry", "Delete this exact forwarding range")
_WARNING: Final = (
    "Port forwarding exposes services on the selected device to the Internet. "
    "Use only necessary ports and a secured destination. Existing unrelated "
    "rules are preserved. Live writes have not been verified."
)
_EDIT_FIELDS: Final = (_NAME, _DEVICE, _ACTIVE)
_RANGE_PROTOCOL: Final = choice(
    "protocol", "Protocol", (("tcp", "TCP"), ("udp", "UDP"))
)
_RANGE_FIELDS: Final = tuple(
    SettingsField(name, label, "integer", maximum=_MAX_PORT, description=description)
    for name, label, description in (
        ("public_start", "Public start", "1-65535; 0 means not configured."),
        (
            "public_end",
            "Public end",
            "0 for a single port; otherwise greater than the start.",
        ),
        (
            "destination_start",
            "Destination start",
            "1-65535; range width matches public ports.",
        ),
    )
)
_RANGE_TARGET: Final = re.compile(r"([0-9]+):(tcp|udp):([0-9]+)")
_CREATE_FIELDS: Final = (
    *_EDIT_FIELDS,
    *(
        field
        for protocol in ("tcp", "udp")
        for field in (
            boolean(f"{protocol}_enabled", f"Add {protocol.upper()} range"),
            SettingsField(
                f"{protocol}_public_from",
                f"{protocol.upper()} public start",
                "integer",
                maximum=_MAX_PORT,
                description="1-65535 when enabled; 0 means not configured.",
            ),
            SettingsField(
                f"{protocol}_public_to",
                f"{protocol.upper()} public end",
                "integer",
                maximum=_MAX_PORT,
                description="0 for a single port; otherwise greater than the start.",
            ),
            SettingsField(
                f"{protocol}_private_dest",
                f"{protocol.upper()} destination start",
                "integer",
                maximum=_MAX_PORT,
                description="1-65535 when enabled; range width matches public ports.",
            ),
        )
    ),
)


@dataclass(frozen=True, slots=True)
class PortRuleTargetSpec:
    """Provide the same closed target metadata seam as other family modules."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]
    metadata_target: str = "0"


PORT_RULE_TARGET_SPECS: Final = MappingProxyType(
    {
        "port_forward_edit": PortRuleTargetSpec(
            "port_forward_edit",
            "Edit forwarding rule",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "portuw_name",
            _EDIT_FIELDS,
        ),
        "port_forward_delete": PortRuleTargetSpec(
            "port_forward_delete",
            "Delete forwarding rule",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "portuw_name",
            (_DELETE,),
        ),
        "port_forward_range_create": PortRuleTargetSpec(
            "port_forward_range_create",
            "Add range to forwarding rule",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "portuw_name",
            (_RANGE_PROTOCOL, *_RANGE_FIELDS),
        ),
        "port_forward_range_edit": PortRuleTargetSpec(
            "port_forward_range_edit",
            "Edit forwarding range",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "portuw_name",
            _RANGE_FIELDS,
            "0:tcp:0",
        ),
        "port_forward_range_delete": PortRuleTargetSpec(
            "port_forward_range_delete",
            "Delete forwarding range",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "portuw_name",
            (_DELETE_RANGE,),
            "0:tcp:0",
        ),
    }
)


def _id(value: object) -> str:
    if type(value) is int:
        value = str(value)
    if type(value) is not str or not _ID.fullmatch(value) or int(value) > 2**31 - 1:
        raise ConfigurationError("invalid_port_rule_id")
    return value


def _sid(value: object) -> str:
    if type(value) is not str or not _SID.fullmatch(value) or value == "0":
        raise ConfigurationError("invalid_port_device")
    return value


def _name(value: object) -> str:
    value = _NAME.validate(value)
    if (
        type(value) is not str
        or not value
        or any(ord(char) > _MAX_CHARACTER or char in "<>" for char in value)
    ):
        raise ConfigurationError("invalid_port_rule_name")
    return value


def _rows(value: object, maximum: int) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and value:
        value = [value]
    if (
        type(value) is not list
        or len(value) > maximum
        or any(not isinstance(row, Mapping) for row in value)
    ):
        raise ConfigurationError("incomplete_port_rules")
    return value


def _inventory(raw: SettingValues) -> tuple[tuple[str, str, str], ...]:
    result: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in _rows(raw.get("portuw_addmdevice"), _MAX_DEVICES):
        sid, label, mac = (
            _sid(row.get("sid")),
            row.get("mdevice_name"),
            row.get("mdevice_mac"),
        )
        if (
            sid in seen
            or type(label) is not str
            or len(label) > _MAX_LABEL
            or any(
                ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER
                for char in label
            )
            or type(mac) is not str
            or not _MAC.fullmatch(mac)
        ):
            raise ConfigurationError("ambiguous_port_device")
        seen.add(sid)
        result.append((sid, label, mac.lower().replace("-", ":")))
    return tuple(result)


def _port(value: object, *, optional: bool = False) -> int:
    if optional and value == "":
        return 0
    if type(value) is str and re.fullmatch(r"[0-9]{1,5}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= _MAX_PORT:
        raise ConfigurationError("invalid_port_range")
    return value


def _reserved(raw: SettingValues, protocol: str) -> tuple[tuple[int, int], ...]:
    value = raw.get(f"{protocol}reservedports")
    if (
        type(value) is not str
        or len(value) > _MAX_RESERVED_TEXT
        or (value and not _RESERVED.fullmatch(value))
    ):
        raise ConfigurationError("incomplete_reserved_ports")
    result = []
    for entry in value.split(",") if value else ():
        parts = entry.split("-")
        start, end = _port(parts[0]), _port(parts[-1])
        if end < start:
            raise ConfigurationError("invalid_reserved_ports")
        result.append((start, end))
    return tuple(result)


def _ranges(row: SettingValues, protocol: str) -> tuple[dict[str, str], ...]:
    result = []
    seen: set[str] = set()
    for item in _rows(row.get(f"add{protocol}portuw", []), _MAX_RANGES):
        identifier = _id(item.get(f"portuw{protocol}_id"))
        start = _port(item.get(f"{protocol}_public_from"))
        end = _port(item.get(f"{protocol}_public_to"), optional=True)
        destination = _port(item.get(f"{protocol}_private_dest"))
        destination_end = destination + (end - start if end else 0)
        if identifier in seen or (end and end < start) or destination_end > _MAX_PORT:
            raise ConfigurationError("ambiguous_port_range")
        if f"{protocol}_private_to" in item and _port(
            item[f"{protocol}_private_to"], optional=True
        ) != (destination_end if end else 0):
            raise ConfigurationError("invalid_derived_port_range")
        seen.add(identifier)
        result.append(
            {
                f"portuw{protocol}_id": identifier,
                f"{protocol}_public_from": str(start),
                f"{protocol}_public_to": str(end) if end else "",
                f"{protocol}_private_dest": str(destination),
                f"{protocol}_private_to": str(destination_end) if end else "",
            }
        )
    return tuple(result)


def _rules(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    _inventory(raw)
    _reserved(raw, "tcp")
    _reserved(raw, "udp")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _rows(raw.get(_COLLECTION, []), _MAX_RULES):
        identifier = _id(row.get("id"))
        tcp, udp = _ranges(row, "tcp"), _ranges(row, "udp")
        if identifier in seen or not (tcp or udp):
            raise ConfigurationError("ambiguous_port_rule")
        template = row.get("portuw_template")
        if template is not None and (
            type(template) is not str or template not in {"-1", *map(str, range(10))}
        ):
            raise ConfigurationError("unknown_port_template")
        seen.add(identifier)
        result.append(
            {
                "id": identifier,
                "portuw_name": _name(row.get("portuw_name")),
                "portuw_active": _ACTIVE.read(row),
                "portuw_device": _sid(row.get("portuw_device")),
                "portuw_template": template,
                "addtcpportuw": tcp,
                "addudpportuw": udp,
            }
        )
    return tuple(result)


def _map(raw: SettingValues) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _rules(raw)}


def _choices(raw: SettingValues) -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        "portuw_device": (
            ("0", "Select a destination device"),
            *(
                (sid, f"{label[: 253 - len(sid)]} ({sid})" if label else sid)
                for sid, label, _ in _inventory(raw)
            ),
        )
    }


def _revision(raw: SettingValues) -> dict[str, object]:
    return {"devices": _inventory(raw)}


def _range_change(changes: SettingValues, protocol: str) -> dict[str, str] | None:
    fields = {field.name: field for field in _CREATE_FIELDS}
    enabled = changes.get(f"{protocol}_enabled", False)
    names = tuple(
        f"{protocol}_{suffix}"
        for suffix in ("public_from", "public_to", "private_dest")
    )
    if enabled is not True:
        if any(name in changes for name in names):
            raise ConfigurationError("inactive_settings_field")
        return None
    values = {name: fields[name].validate(changes.get(name, 0)) for name in names}
    start, end, destination = (values[name] for name in names)
    if (
        type(start) is not int
        or type(end) is not int
        or type(destination) is not int
        or not start
        or not destination
    ):
        raise ConfigurationError("incomplete_port_range")
    if end and end <= start:
        raise ConfigurationError("invalid_port_range")
    destination_end = destination + (end - start if end else 0)
    if destination_end > _MAX_PORT:
        raise ConfigurationError("invalid_port_range")
    return {
        f"portuw{protocol}_id": "-1",
        names[0]: str(start),
        names[1]: str(end) if end else "",
        names[2]: str(destination),
        f"{protocol}_private_to": str(destination_end) if end else "",
    }


def _collisions(
    raw: SettingValues, ranges: SettingValues, target_id: str | None = None
) -> None:
    for protocol in ("tcp", "udp"):
        existing = list(_reserved(raw, protocol))
        for row in _rules(raw):
            if row["id"] != target_id:
                existing.extend(
                    (
                        int(item[f"{protocol}_public_from"]),
                        int(
                            item[f"{protocol}_public_to"]
                            or item[f"{protocol}_public_from"]
                        ),
                    )
                    for item in row[f"add{protocol}portuw"]
                )
        for item in ranges[f"add{protocol}portuw"]:
            start = int(item[f"{protocol}_public_from"])
            end = int(item[f"{protocol}_public_to"] or start)
            if any(
                start <= other_end and end >= other_start
                for other_start, other_end in existing
            ):
                raise ConfigurationError("port_range_in_use")
            existing.append((start, end))


def _create_row(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
    if len(_rules(raw)) >= _MAX_RULES:
        raise ConfigurationError("port_rule_limit")
    if not {"portuw_name", "portuw_device"} <= changes.keys():
        raise ConfigurationError("incomplete_port_rule")
    device = _sid(changes["portuw_device"])
    if device not in {sid for sid, _, _ in _inventory(raw)}:
        raise ConfigurationError("invalid_port_device")
    result: dict[str, Any] = {
        "id": "-1",
        "portuw_name": _name(changes["portuw_name"]),
        "portuw_device": device,
        "portuw_active": changes.get("portuw_active", False),
        "portuw_template": "-1",
    }
    for protocol in ("tcp", "udp"):
        item = _range_change(changes, protocol)
        result[f"add{protocol}portuw"] = (item,) if item else ()
    if not result["addtcpportuw"] and not result["addudpportuw"]:
        raise ConfigurationError("empty_port_rule")
    _collisions(raw, result)
    return result


def _wire(
    row: SettingValues, ordinal: int, *, creating: bool
) -> dict[str, str | int | bool]:
    result: dict[str, str | int | bool] = {
        name: row[name]
        for name in ("id", "portuw_name", "portuw_device", "portuw_template")
    }
    result["portuw_active"] = "1" if row["portuw_active"] else "0"
    for protocol in ("tcp", "udp"):
        entries = row[f"add{protocol}portuw"]
        if creating and not entries:
            # Native new-row handler adds one empty row for each protocol.
            entries = (
                {
                    f"portuw{protocol}_id": "-1",
                    **{
                        f"{protocol}_{suffix}": ""
                        for suffix in (
                            "public_from",
                            "public_to",
                            "private_dest",
                            "private_to",
                        )
                    },
                },
            )
        for index, entry in enumerate(entries, 1):
            for key, value in entry.items():
                # v10 HTML disables both derived text inputs; the shared
                # serializer excludes disabledTextfield before collecting data.
                if key == f"{protocol}_private_to":
                    continue
                result[f"{key}[{ordinal}{index}]"] = value
    return result


def _create_read(raw: SettingValues) -> dict[str, object]:
    _rules(raw)
    return {
        field.name: (
            False
            if field.kind == "boolean"
            else 0
            if field.kind == "integer"
            else "0"
            if field.name == "portuw_device"
            else ""
        )
        for field in _CREATE_FIELDS
    }


def _create_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    return _wire(_create_row(raw, changes), len(_rules(raw)) + 1, creating=True)


def _semantic(row: SettingValues) -> dict[str, Any]:
    return {
        **{key: row[key] for key in ("portuw_name", "portuw_active", "portuw_device")},
        **{
            f"add{protocol}portuw": tuple(
                {
                    key: value
                    for key, value in item.items()
                    if key != f"portuw{protocol}_id"
                }
                for item in row[f"add{protocol}portuw"]
            )
            for protocol in ("tcp", "udp")
        },
    }


def _stable(before: SettingValues, after: SettingValues) -> bool:
    return set(_inventory(before)) == set(_inventory(after)) and all(
        _reserved(before, protocol) == _reserved(after, protocol)
        for protocol in ("tcp", "udp")
    )


def _create_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        expected = _create_row(before, changes)
        previous, current = _map(before), _map(after)
        created = current.keys() - previous.keys()
        return (
            _stable(before, after)
            and len(created) == 1
            and len(current) == len(previous) + 1
            and all(current.get(key) == value for key, value in previous.items())
            and _semantic(current[next(iter(created))]) == _semantic(expected)
        )
    except ConfigurationError:
        return False


def port_rule_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """Expose only exact outer IDs and bounded rule labels to target selection."""
    if setting_id not in PORT_RULE_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    if setting_id in {"port_forward_range_edit", "port_forward_range_delete"}:
        return tuple(
            {
                "id": f"{row['id']}:{protocol}:{item[f'portuw{protocol}_id']}",
                "portuw_name": (
                    f"{row['portuw_name']}: {protocol.upper()} "
                    f"{item[f'{protocol}_public_from']}"
                    + (
                        f"-{item[f'{protocol}_public_to']}"
                        if item[f"{protocol}_public_to"]
                        else ""
                    )
                    + f" (ID {item[f'portuw{protocol}_id']})"
                ),
            }
            for row in _rules(raw)
            for protocol in ("tcp", "udp")
            for item in row[f"add{protocol}portuw"]
        )
    return tuple(
        {"id": row["id"], "portuw_name": row["portuw_name"]} for row in _rules(raw)
    )


def port_rule_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind one full rule; edits preserve all nested range IDs and values."""
    spec = PORT_RULE_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    if setting_id.startswith("port_forward_range_"):
        return _range_contract(setting_id, target_id)
    target_id = _id(target_id)
    deleting = setting_id == "port_forward_delete"

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _map(raw).get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return row

    def read(raw: SettingValues) -> dict[str, Any]:
        if deleting:
            return {"delete_entry": target_id not in _map(raw)}
        row = selected(raw)
        return {field.name: row[field.name] for field in _EDIT_FIELDS}

    def edited(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
        row = {**selected(raw), **changes}
        row["portuw_name"] = _name(row["portuw_name"])
        if row["portuw_template"] is None:
            raise ConfigurationError("missing_preserved_port_template")
        if row["portuw_device"] not in {sid for sid, _, _ in _inventory(raw)}:
            raise ConfigurationError("invalid_port_device")
        _collisions(raw, row, target_id)
        return row

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        selected(raw)
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        rows = _rules(raw)
        ordinal = next(
            index for index, row in enumerate(rows, 1) if row["id"] == target_id
        )
        return _wire(edited(raw, changes), ordinal, creating=False)

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            expected = _map(before)
            if deleting:
                expected.pop(target_id)
            else:
                expected[target_id] = edited(before, changes)
            return _stable(before, after) and _map(after) == expected
        except ConfigurationError:
            return False

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            changes = {
                field.name: payload[field.name]
                for field in spec.fields
                if field.name in payload
            }
            if deleting:
                changes = {"delete_entry": True}
            elif "portuw_active" in changes:
                changes["portuw_active"] = _ACTIVE.read(changes)
            return build(raw, changes) == dict(payload)
        except (ConfigurationError, KeyError):
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
        verifier=verify,
        payload_validator=validate_payload,
        field_choices=None if deleting else _choices,
        revision_values=_revision,
        revision_fields=(_COLLECTION, "tcpreservedports", "udpreservedports"),
        warning=_WARNING,
        confirmation="DELETE PORT FORWARD" if deleting else "SAVE PORT FORWARD",
    )


def _range_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind a parent rule and, for updates, an exact protocol/range ID tuple."""
    spec = PORT_RULE_TARGET_SPECS[setting_id]
    creating = setting_id == "port_forward_range_create"
    deleting = setting_id == "port_forward_range_delete"
    protocol: str | None = None
    range_id: str | None = None
    if creating:
        parent_id = _id(target_id)
    else:
        match = _RANGE_TARGET.fullmatch(target_id)
        if match is None:
            raise ConfigurationError("invalid_port_range_target")
        parent_id, protocol, range_id = _id(match[1]), match[2], _id(match[3])

    def parent(raw: SettingValues) -> dict[str, Any]:
        row = _map(raw).get(parent_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return row

    def range_row(raw: SettingValues) -> dict[str, str] | None:
        return next(
            (
                item
                for item in parent(raw)[f"add{protocol}portuw"]
                if item[f"portuw{protocol}_id"] == range_id
            ),
            None,
        )

    def read(raw: SettingValues) -> dict[str, Any]:
        parent(raw)
        if creating:
            return {"protocol": "tcp", **{field.name: 0 for field in _RANGE_FIELDS}}
        item = range_row(raw)
        if deleting:
            return {"delete_entry": item is None}
        if item is None:
            raise ConfigurationError("stale_settings")
        return {
            "public_start": int(item[f"{protocol}_public_from"]),
            "public_end": int(item[f"{protocol}_public_to"] or 0),
            "destination_start": int(item[f"{protocol}_private_dest"]),
        }

    def changed(
        raw: SettingValues, changes: SettingValues
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        row = parent(raw)
        if row["portuw_template"] is None:
            raise ConfigurationError("missing_preserved_port_template")
        if row["portuw_device"] not in {sid for sid, _, _ in _inventory(raw)}:
            raise ConfigurationError("invalid_port_device")
        selected_protocol = (
            str(changes.get("protocol", "tcp")) if creating else str(protocol)
        )
        if selected_protocol not in {"tcp", "udp"}:
            raise ConfigurationError("invalid_port_protocol")
        key = f"add{selected_protocol}portuw"
        entries = list(row[key])
        if creating:
            if len(entries) >= _MAX_RANGES:
                raise ConfigurationError("port_range_limit")
            values = {**read(raw), **changes}
            position = len(entries)
        else:
            item = range_row(raw)
            if item is None:
                raise ConfigurationError("stale_settings")
            position = next(
                index
                for index, value in enumerate(entries)
                if value[f"portuw{selected_protocol}_id"] == range_id
            )
            values = {**read(raw), **changes}
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            if sum(len(row[f"add{item}portuw"]) for item in ("tcp", "udp")) <= 1:
                raise ConfigurationError("delete_empty_parent_rule_instead")
            wire_entries = [*entries]
            wire_entries[position] = {
                f"portuw{selected_protocol}_id": str(range_id),
                **{
                    f"{selected_protocol}_{suffix}": ""
                    for suffix in (
                        "public_from",
                        "public_to",
                        "private_dest",
                        "private_to",
                    )
                },
            }
            entries.pop(position)
            return (
                selected_protocol,
                {**row, key: tuple(entries)},
                {**row, key: tuple(wire_entries)},
            )
        item = _range_change(
            {
                f"{selected_protocol}_enabled": True,
                f"{selected_protocol}_public_from": values["public_start"],
                f"{selected_protocol}_public_to": values["public_end"],
                f"{selected_protocol}_private_dest": values["destination_start"],
            },
            selected_protocol,
        )
        if item is None:
            raise ConfigurationError("incomplete_port_range")
        if creating:
            entries.append(item)
        else:
            item[f"portuw{selected_protocol}_id"] = str(range_id)
            entries[position] = item
        expected = {**row, key: tuple(entries)}
        _collisions(raw, expected, parent_id)
        return selected_protocol, expected, expected

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        _, _, wire_row = changed(raw, changes)
        ordinal = next(
            index for index, row in enumerate(_rules(raw), 1) if row["id"] == parent_id
        )
        return _wire(wire_row, ordinal, creating=False)

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            selected_protocol, expected_row, _ = changed(before, changes)
            previous, current = _map(before), _map(after)
            if not _stable(before, after) or previous.keys() != current.keys():
                return False
            if any(
                current[key] != row for key, row in previous.items() if key != parent_id
            ):
                return False
            current_row = current[parent_id]
            if not creating:
                return current_row == expected_row
            collection = f"add{selected_protocol}portuw"
            identity = f"portuw{selected_protocol}_id"
            old_ids = {item[identity] for item in previous[parent_id][collection]}
            new = [
                item
                for item in current_row[collection]
                if item[identity] not in old_ids
            ]
            if len(new) != 1:
                return False
            expected_entries = [*expected_row[collection]]
            expected_entries[-1] = {**expected_entries[-1], identity: new[0][identity]}
            return current_row == {**expected_row, collection: tuple(expected_entries)}
        except ConfigurationError:
            return False

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            if deleting:
                changes: dict[str, Any] = {"delete_entry": True}
            else:
                row = parent(raw)
                ordinal = next(
                    index
                    for index, item in enumerate(_rules(raw), 1)
                    if item["id"] == parent_id
                )
                if creating:
                    protocols = [
                        item
                        for item in ("tcp", "udp")
                        if payload.get(
                            f"portuw{item}_id[{ordinal}"
                            f"{len(row[f'add{item}portuw']) + 1}]"
                        )
                        == "-1"
                    ]
                    if len(protocols) != 1:
                        return False
                    selected_protocol = protocols[0]
                    position = len(row[f"add{selected_protocol}portuw"]) + 1
                else:
                    selected_protocol = str(protocol)
                    position = next(
                        index
                        for index, item in enumerate(row[f"add{protocol}portuw"], 1)
                        if item[f"portuw{protocol}_id"] == range_id
                    )
                suffix = f"[{ordinal}{position}]"
                changes = {
                    "public_start": _port(
                        payload[f"{selected_protocol}_public_from{suffix}"]
                    ),
                    "public_end": _port(
                        payload[f"{selected_protocol}_public_to{suffix}"], optional=True
                    ),
                    "destination_start": _port(
                        payload[f"{selected_protocol}_private_dest{suffix}"]
                    ),
                }
                if creating:
                    changes["protocol"] = selected_protocol
            return build(raw, changes) == dict(payload)
        except (ConfigurationError, KeyError, StopIteration):
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
        verifier=verify,
        verifier_owns_fields=creating,
        payload_validator=validate_payload,
        revision_values=_revision,
        revision_fields=(_COLLECTION, "tcpreservedports", "udpreservedports"),
        warning=_WARNING
        + (
            " The final range must be removed by deleting its parent rule."
            if deleting
            else ""
        ),
        confirmation="DELETE PORT RANGE"
        if deleting
        else "ADD PORT RANGE"
        if creating
        else "SAVE PORT RANGE",
    )


def _create_payload_valid(raw: SettingValues, payload: SettingValues) -> bool:
    """Reconstruct only reviewed typed changes, then require the exact native map."""
    try:
        changes: dict[str, Any] = {
            field.name: payload[field.name] for field in _EDIT_FIELDS
        }
        changes["portuw_active"] = _ACTIVE.read(changes)
        ordinal = len(_rules(raw)) + 1
        for protocol in ("tcp", "udp"):
            names = tuple(
                f"{protocol}_{suffix}"
                for suffix in ("public_from", "public_to", "private_dest")
            )
            enabled = payload[names[0] + f"[{ordinal}1]"] != ""
            changes[f"{protocol}_enabled"] = enabled
            if enabled:
                changes.update(
                    {
                        name: _port(
                            payload[name + f"[{ordinal}1]"],
                            optional=name.endswith("_to"),
                        )
                        for name in names
                    }
                )
        return _create_build(raw, changes) == dict(payload)
    except (ConfigurationError, KeyError):
        return False


PORT_RULE_SETTINGS: Final = (
    SettingsContract(
        "port_forward_create",
        "Add forwarding rule",
        "Network",
        _ENDPOINT,
        _REFERER,
        _CREATE_FIELDS,
        reader=_create_read,
        builder=_create_build,
        field_choices=_choices,
        revision_values=_revision,
        payload_validator=_create_payload_valid,
        verifier=_create_verify,
        verifier_owns_fields=True,
        revision_fields=(_COLLECTION, "tcpreservedports", "udpreservedports"),
        warning=_WARNING + " Each new rule can contain one TCP and one UDP range.",
        confirmation="ADD PORT FORWARD",
    ),
)
