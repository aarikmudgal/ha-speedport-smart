"""Exact mesh-node forms and one-shot identification, with private target binding."""

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
    normalize_configuration_payload,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

MESH_READ_ENDPOINT: Final = "data/DeviceList.json"
MESH_REFERER: Final = "html/content/network/devices.html"
_MAX_ROWS: Final = 64
_ID: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_MAC: Final = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_NAME: Final = re.compile(r"[0-9A-Za-z-]{1,28}")
_NAME_FIELD: Final = SettingsField(
    "mesh_name",
    "Mesh node name",
    "text",
    minimum=1,
    maximum=28,
    description="The router accepts only ASCII letters, digits and hyphens.",
)
_EXECUTE: Final = boolean(
    "execute",
    "Send this one-shot request",
    description="This is approval to send a request, not a reported device state.",
)
_HIDDEN_FIELDS: Final = (
    "id",
    "mesh_device_type",
    "mesh_connected",
    "mesh_mac",
    "mesh_mac_wlan",
    "mesh_mac_wlan5",
    "mesh_type",
    "mesh_ipv4",
    "mesh_downspeed",
    "mesh_upspeed",
    "mesh_rssi",
    "mesh_serial",
)
_STABLE_FIELDS: Final = (
    "id",
    "mesh_mac",
    "mesh_serial",
    "mesh_name",
    "mesh_connected",
)


@dataclass(frozen=True, slots=True)
class MeshTargetSpec:
    """Fixed target source; target IDs never select a URL or payload field."""

    id: str
    title: str
    endpoint: str
    fields: tuple[SettingsField, ...]
    confirmation: str
    warning: str
    referer: str = MESH_REFERER
    read_endpoint: str = MESH_READ_ENDPOINT
    collection: str = "addmeshdevice"
    label_key: str = "mesh_name"


MESH_TARGET_SPECS: Final = MappingProxyType(
    {
        "network_mesh_node_rename": MeshTargetSpec(
            "network_mesh_node_rename",
            "Rename mesh node",
            "data/MeshDevice.json",
            (_NAME_FIELD,),
            "RENAME MESH NODE",
            "This renames only the selected existing mesh node. Its private identity "
            "is checked again before sending. All other mesh node names are preserved.",
        ),
        "network_mesh_node_delete": MeshTargetSpec(
            "network_mesh_node_delete",
            "Delete disconnected mesh node",
            "data/MeshDevice.json",
            (_EXECUTE,),
            "DELETE MESH NODE",
            "This removes the selected disconnected node from the router's mesh list. "
            "It does not factory-reset the node. The entire list is read independently "
            "to verify its removal and preservation of the other nodes.",
        ),
        "network_mesh_identify_start": MeshTargetSpec(
            "network_mesh_identify_start",
            "Start mesh node identification",
            "data/ActiveNode.json",
            (_EXECUTE,),
            "IDENTIFY MESH NODE",
            "This sends one identification request to the selected connected node. "
            "Inspect its LEDs physically. The firmware exposes no proven paging-state "
            "readback, so the integration cannot verify that identification started. "
            "Use Stop identification explicitly when finished.",
        ),
        "network_mesh_identify_stop": MeshTargetSpec(
            "network_mesh_identify_stop",
            "Stop mesh node identification",
            "data/ActiveNode.json",
            (_EXECUTE,),
            "STOP MESH IDENTIFICATION",
            "This sends one stop-identification request to the selected connected "
            "node. Inspect its LEDs physically; no proven independent paging-state "
            "readback is available. Navigation does not send an automatic "
            "stop request.",
        ),
    }
)


def mesh_identifier(value: object) -> str:
    """Validate a private firmware row ID without printing its value."""
    if type(value) is int:
        value = str(value)
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ConfigurationError("invalid_mesh_target")
    return value


def _text(value: object, maximum: int, *, empty: bool = False) -> str:
    if (
        type(value) is not str
        or len(value) > maximum
        or (not empty and not value)
        or (value and not value.isprintable())
    ):
        raise ConfigurationError("incomplete_mesh_inventory")
    return value


def mesh_flag(raw: SettingValues, name: str) -> bool:
    """Read an exact 0/1 scalar, including identical codec duplicates."""
    return bool(boolean(name, name).read(normalize_configuration_payload(raw)))


def _mac(value: object, *, empty: bool = False) -> str:
    text = _text(value, 17, empty=empty).replace("-", ":")
    if not (empty and text == "") and _MAC.fullmatch(text) is None:
        raise ConfigurationError("incomplete_mesh_inventory")
    return text.lower()


def mesh_rows(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Require a whole explicit collection; never silently drop malformed nodes."""
    source = normalize_configuration_payload(raw)
    if source.get("router_state") != "OK" or any(
        name in source and source[name] not in (False, 0, "0", None, "")
        for name in ("truncated", "has_more", "next_page", "next_cursor")
    ):
        raise ConfigurationError("incomplete_mesh_inventory")
    # v16 captured an empty DeviceList with no template and exact mesh_exist='0'.
    # Missing templates without this positive empty-state evidence still fail.
    if "addmeshdevice" not in source and source.get("mesh_exist") == "0":
        return ()
    value = source.get("addmeshdevice")
    if isinstance(value, Mapping):
        if not value:
            value = []
        elif any(isinstance(item, list) for item in value.values()):
            if not all(isinstance(item, list) for item in value.values()):
                raise ConfigurationError("incomplete_mesh_inventory")
            lengths = {len(item) for item in value.values()}
            if len(lengths) != 1 or lengths.pop() > _MAX_ROWS:
                raise ConfigurationError("incomplete_mesh_inventory")
            value = [
                dict(zip(value, items, strict=True))
                for items in zip(*value.values(), strict=True)
            ]
        else:
            value = [value]
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ConfigurationError("incomplete_mesh_inventory")
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    macs: set[str] = set()
    serials: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigurationError("incomplete_mesh_inventory")
        row = normalize_configuration_payload(item)
        identifier = mesh_identifier(row.get("id"))
        connected = mesh_flag(row, "mesh_connected")
        mac = _mac(row.get("mesh_mac"), empty=True)
        serial = _text(row.get("mesh_serial"), 128, empty=True)
        # global.js getMeshCount ignores only explicit empty-MAC template slots.
        # A connected slot or an identity-bearing slot must not disappear here.
        if not mac:
            if connected or serial:
                raise ConfigurationError("incomplete_mesh_inventory")
            continue
        if not serial or identifier in ids or mac in macs or serial in serials:
            raise ConfigurationError("ambiguous_mesh_inventory")
        ids.add(identifier)
        macs.add(mac)
        serials.add(serial)
        name = _text(row.get("mesh_name"), 128)
        result.append(
            {
                **row,
                "id": identifier,
                "mesh_mac": mac,
                "mesh_serial": serial,
                "mesh_name": name,
                "mesh_connected": "1" if connected else "0",
            }
        )
    return tuple(result)


def mesh_identity(raw: SettingValues) -> dict[str, Any]:
    """Return private stable revision material, excluding live traffic telemetry."""
    return {
        row["id"]: {name: row[name] for name in _STABLE_FIELDS}
        for row in mesh_rows(raw)
    }


def mesh_target_rows(setting_id: str, raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Filter eligible targets only after validating the entire collection."""
    if setting_id not in MESH_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    rows = mesh_rows(raw)
    if setting_id == "network_mesh_node_delete":
        return tuple(row for row in rows if row["mesh_connected"] == "0")
    if setting_id.startswith("network_mesh_identify_"):
        return tuple(row for row in rows if row["mesh_connected"] == "1")
    return rows


def _selected(setting_id: str, target_id: str, raw: SettingValues) -> dict[str, Any]:
    matches = [
        row for row in mesh_target_rows(setting_id, raw) if row["id"] == target_id
    ]
    if len(matches) != 1:
        raise ConfigurationError("stale_settings")
    return matches[0]


def _rename_payload(
    row: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    if set(changes) != {"mesh_name"} or not isinstance(changes["mesh_name"], str):
        raise ConfigurationError
    name = changes["mesh_name"]
    if _NAME.fullmatch(name) is None:
        raise ConfigurationError("invalid_mesh_name")
    # The firmware serializes every hidden field of this exact form. Preserve
    # them from the fresh private read; no client may supply these identifiers.
    payload: dict[str, str | int | bool] = {
        key: _text(row.get(key), 255, empty=True) for key in _HIDDEN_FIELDS
    }
    for key in ("mesh_mac_wlan", "mesh_mac_wlan5"):
        _mac(payload[key], empty=True)
    payload["mesh_name"] = name
    return payload


def mesh_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind one closed form to an opaque server-owned target selection."""
    spec = MESH_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    target_id = mesh_identifier(target_id)
    rename = setting_id == "network_mesh_node_rename"
    identify = setting_id.startswith("network_mesh_identify_")

    def read(raw: SettingValues) -> dict[str, Any]:
        row = _selected(setting_id, target_id, raw)
        if rename:
            # Validate existing names for editing without disclosing other rows.
            if _NAME.fullmatch(row["mesh_name"]) is None:
                raise ConfigurationError("invalid_mesh_name")
            _rename_payload(row, {"mesh_name": row["mesh_name"]})
            return {"mesh_name": row["mesh_name"]}
        return {"execute": False}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        row = _selected(setting_id, target_id, raw)
        if rename:
            return _rename_payload(row, changes)
        if set(changes) != {"execute"} or changes["execute"] is not True:
            raise ConfigurationError("confirmation_required")
        if identify:
            return {
                "mesh_paging": "1" if setting_id.endswith("_start") else "0",
                "mesh_mac": row["mesh_mac"],
            }
        return {"deleteEntry": "delete", "mesh_serial_number": row["mesh_serial"]}

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        previous, current = mesh_identity(before), mesh_identity(after)
        if target_id not in previous:
            return False
        expected = {identifier: dict(row) for identifier, row in previous.items()}
        if rename:
            expected[target_id]["mesh_name"] = build(before, changes)["mesh_name"]
        else:
            del expected[target_id]
        # Connectivity may change independently, but no identity or sibling name
        # may disappear/change while proving the selected rename/removal.
        for collection in (expected, current):
            for row in collection.values():
                row.pop("mesh_connected", None)
        return expected == current

    return SettingsContract(
        spec.id,
        spec.title,
        "Home network",
        spec.endpoint,
        spec.referer,
        spec.fields,
        read_endpoint=spec.read_endpoint,
        reader=read,
        builder=build,
        payload_keys=frozenset(
            (*_HIDDEN_FIELDS, "mesh_name")
            if rename
            else ("mesh_paging", "mesh_mac")
            if identify
            else ("deleteEntry", "mesh_serial_number")
        ),
        revision_values=mesh_identity,
        acknowledgement="status_ok" if rename else "readback",
        readback_policy="manual_required" if identify else "exact",
        verifier=None if identify else verify,
        verifier_owns_fields=not identify,
        warning=spec.warning,
        confirmation=spec.confirmation,
    )


def mesh_target_metadata() -> list[dict[str, Any]]:
    """Describe target editors without emitting any router identity or value."""
    return [
        {**mesh_target_contract(spec.id, "0").metadata(), "requires_target": True}
        for spec in MESH_TARGET_SPECS.values()
    ]
