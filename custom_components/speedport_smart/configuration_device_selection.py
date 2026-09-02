"""Closed Wi-Fi access/QoS editors using preserved SID compound bindings."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from .configuration import ConfigurationError, SettingsContract, SettingsField, choice

if TYPE_CHECKING:
    from .configuration import SettingValues

_MAX_DEVICES: Final = 253  # Reviewed firmware maxPCdev, not a write-time guess.
_MAX_QOS_DEVICES: Final = 2
_Family = Literal["wlan", "qos"]
_MODE: Final = choice(
    "wlan_allow_all",
    "Wi-Fi access",
    (("0", "Allow all devices"), ("1", "Only selected devices")),
)
_WIFI_IDS: Final = SettingsField(
    "allowed_devices",
    "Allowed Wi-Fi devices",
    "identifiers",
    maximum=_MAX_DEVICES,
    dynamic_choices=True,
    description=(
        "Editable only in restricted mode; "
        "the administrator device must remain allowed."
    ),
)
_QOS_IDS: Final = SettingsField(
    "prioritized_devices",
    "Priority devices",
    "identifiers",
    maximum=_MAX_QOS_DEVICES,
    dynamic_choices=True,
    description=(
        "Select up to two current devices. Voice priority is a separate setting."
    ),
)
_SID: Final = SettingsField("sid", "Device ID", "identifiers", maximum=1)
_LABEL: Final = SettingsField("label", "Device name", "text", maximum=256)
_LABEL_SEPARATOR_LENGTH: Final = 3
_MAC: Final = re.compile(
    r"(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}"
)


@dataclass(frozen=True, slots=True, repr=False)
class _SelectionState:
    """Private exact inventory; row order is serialization context, SID is identity."""

    devices: tuple[tuple[str, str], ...]
    identities: tuple[tuple[str, str, str], ...]
    selected: frozenset[str]
    mode: str | None
    administrator_sid: str | None


def _sid(value: object) -> str:
    """Use the shared closed identifier grammar without coercion."""
    validated = _SID.validate([value])
    if not isinstance(validated, list):
        raise ConfigurationError("invalid_device_identifier")
    return validated[0]


def _state(raw: SettingValues, family: _Family) -> _SelectionState:
    """Reject missing, duplicate, mixed or incomplete compound/device inventories."""
    container = raw.get(f"{family}_add")
    inventory = raw.get(f"{family}_addmdevice")
    if isinstance(inventory, Mapping):
        # Generic normalization represents a single template as one mapping.
        inventory = [inventory]
    if (
        not isinstance(container, Mapping)
        or container.get("id") != "1"
        or type(inventory) is not list
        or not 1 <= len(inventory) <= _MAX_DEVICES
    ):
        raise ConfigurationError("incomplete_device_selection")
    devices: list[tuple[str, str]] = []
    identities: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in inventory:
        if not isinstance(row, Mapping):
            raise ConfigurationError("incomplete_device_selection")
        sid = _sid(row.get("sid"))
        label = _LABEL.validate(row.get("mdevice_name"))
        mac = row.get("mdevice_mac")
        if type(label) is not str or sid in seen:
            raise ConfigurationError("ambiguous_device_selection")
        if type(mac) is not str or not _MAC.fullmatch(mac):
            raise ConfigurationError("incomplete_device_identity")
        # Duplicate or blank hostnames must not make target choices ambiguous.
        label_limit = _LABEL.maximum - len(sid) - _LABEL_SEPARATOR_LENGTH
        display_label = f"{label[:label_limit]} ({sid})" if label else sid
        devices.append((sid, display_label))
        identities.append((sid, label, mac.lower().replace("-", ":")))
        seen.add(sid)
    bindings = container.get("sid")
    if isinstance(bindings, Mapping):
        bindings = [bindings]
    if type(bindings) is not list or len(bindings) != len(devices):
        raise ConfigurationError("missing_device_selection_compounds")
    covered: set[str] = set()
    selected: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != {"sid", "mdevice_name"}:
            raise ConfigurationError("missing_device_selection_compounds")
        sid = _sid(binding["sid"])
        flag = binding["mdevice_name"]
        if (
            sid not in seen
            or sid in covered
            or type(flag) is not str
            or flag not in {"0", "1"}
        ):
            raise ConfigurationError("ambiguous_device_selection")
        covered.add(sid)
        if flag == "1":
            selected.add(sid)
    if covered != seen:
        raise ConfigurationError("incomplete_device_selection")
    mode: str | None = None
    administrator_sid: str | None = None
    if family == "wlan":
        value = _MODE.read(container)
        if type(value) is not str:
            raise ConfigurationError("invalid_access_mode")
        mode = value
        login = raw.get("loginedSid")
        if login not in (None, ""):
            administrator_sid = _sid(login)
    elif len(selected) > _MAX_QOS_DEVICES:
        raise ConfigurationError("too_many_priority_devices")
    return _SelectionState(
        tuple(devices), tuple(identities), frozenset(selected), mode, administrator_sid
    )


def _selected(
    field: SettingsField, state: _SelectionState, changes: SettingValues
) -> frozenset[str]:
    """Resolve a full typed selection against the current exact SID inventory."""
    value = (
        field.validate(changes[field.name])
        if field.name in changes
        else sorted(state.selected)
    )
    if not isinstance(value, list) or not set(value) <= {
        sid for sid, _ in state.devices
    }:
        raise ConfigurationError("unknown_selected_device")
    return frozenset(value)


def _wire(
    state: _SelectionState, selected: frozenset[str], *, mode: str | None
) -> dict[str, str | int | bool]:
    """Emit only the fixed native indexed SID/checkbox key pairs."""
    payload: dict[str, str | int | bool] = {}
    for index, (sid, _) in enumerate(state.devices, 1):
        suffix = f"{index}1"
        payload[f"sid[{suffix}]"] = sid
        if mode != "0":
            payload[f"mdevice_name[{suffix}]"] = "1" if sid in selected else "0"
    if mode is not None:
        payload["wlan_allow_all"] = mode
    return payload


def _wifi_change(
    state: _SelectionState, changes: SettingValues
) -> tuple[str, frozenset[str]]:
    """Never silently relax membership or lock the current administrator out."""
    mode = (
        _MODE.validate(changes["wlan_allow_all"])
        if "wlan_allow_all" in changes
        else state.mode
    )
    if type(mode) is not str or mode not in {"0", "1"}:
        raise ConfigurationError("invalid_access_mode")
    if mode == "0" and "allowed_devices" in changes:
        raise ConfigurationError("inactive_settings_field")
    selected = _selected(_WIFI_IDS, state, changes)
    if mode == "1":
        if not selected:
            raise ConfigurationError("empty_wifi_allowlist")
        if state.administrator_sid is None or state.administrator_sid not in selected:
            raise ConfigurationError("administrator_wifi_lockout")
    return mode, selected


def _read_wifi(raw: SettingValues) -> dict[str, object]:
    state = _state(raw, "wlan")
    return {"wlan_allow_all": state.mode, "allowed_devices": sorted(state.selected)}


def _read_qos(raw: SettingValues) -> dict[str, object]:
    return {"prioritized_devices": sorted(_state(raw, "qos").selected)}


def _wifi_choices(raw: SettingValues) -> dict[str, tuple[tuple[str, str], ...]]:
    return {"allowed_devices": _state(raw, "wlan").devices}


def _qos_choices(raw: SettingValues) -> dict[str, tuple[tuple[str, str], ...]]:
    return {"prioritized_devices": _state(raw, "qos").devices}


def _wifi_revision(raw: SettingValues) -> dict[str, object]:
    return {"identities": _state(raw, "wlan").identities}


def _qos_revision(raw: SettingValues) -> dict[str, object]:
    return {"identities": _state(raw, "qos").identities}


def _build_wifi(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    if not changes or not changes.keys() <= {"wlan_allow_all", "allowed_devices"}:
        raise ConfigurationError
    state = _state(raw, "wlan")
    mode, selected = _wifi_change(state, changes)
    return _wire(state, selected, mode=mode)


def _build_qos(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    if set(changes) != {"prioritized_devices"}:
        raise ConfigurationError
    state = _state(raw, "qos")
    return _wire(state, _selected(_QOS_IDS, state, changes), mode=None)


def _validate_payload(
    raw: SettingValues, payload: SettingValues, family: _Family
) -> bool:
    """Require the complete exact key set and correct SID at every fresh row index."""
    try:
        state = _state(raw, family)
        mode = payload.get("wlan_allow_all") if family == "wlan" else None
        if family == "wlan" and (type(mode) is not str or mode not in {"0", "1"}):
            return False
        selected: set[str] = set()
        for index, (sid, _) in enumerate(state.devices, 1):
            suffix = f"{index}1"
            if payload.get(f"sid[{suffix}]") != sid:
                return False
            if mode != "0":
                flag = payload.get(f"mdevice_name[{suffix}]")
                if type(flag) is not str or flag not in {"0", "1"}:
                    return False
                if flag == "1":
                    selected.add(sid)
        expected = _wire(state, frozenset(selected), mode=mode)
        if dict(payload) != expected:
            return False
        if family == "wlan" and mode == "1":
            return bool(selected) and state.administrator_sid in selected
        return family == "wlan" or len(selected) <= _MAX_QOS_DEVICES
    except ConfigurationError:
        return False


def _validate_wifi_payload(raw: SettingValues, payload: SettingValues) -> bool:
    return _validate_payload(raw, payload, "wlan")


def _validate_qos_payload(raw: SettingValues, payload: SettingValues) -> bool:
    return _validate_payload(raw, payload, "qos")


def _verify_wifi(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    """Readback matches exact membership and unchanged available-device identities."""
    try:
        previous = _state(before, "wlan")
        current = _state(after, "wlan")
        mode, selected = _wifi_change(previous, changes)
        return (
            set(previous.identities) == set(current.identities)
            and current.mode == mode
            and current.selected == selected
        )
    except ConfigurationError:
        return False


def _verify_qos(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        previous = _state(before, "qos")
        current = _state(after, "qos")
        return set(previous.identities) == set(
            current.identities
        ) and current.selected == _selected(_QOS_IDS, previous, changes)
    except ConfigurationError:
        return False


DEVICE_SELECTION_SETTINGS: Final = (
    SettingsContract(
        "wifi_access",
        "Wi-Fi access control",
        "Wi-Fi",
        "data/WLANAccess.json",
        "html/content/network/wlan_access.html",
        (_MODE, _WIFI_IDS),
        reader=_read_wifi,
        builder=_build_wifi,
        field_choices=_wifi_choices,
        payload_validator=_validate_wifi_payload,
        verifier=_verify_wifi,
        revision_fields=("wlan_add", "loginedSid"),
        revision_values=_wifi_revision,
        confirmation="CHANGE WIFI ACCESS",
        warning=(
            "Restricting access can disconnect Wi-Fi devices. The current "
            "administrator device must remain allowed. Stored selections are "
            "preserved when allowing all devices. MAC-based filtering is not "
            "a replacement for strong Wi-Fi encryption."
        ),
    ),
    SettingsContract(
        "qos_devices",
        "Priority devices",
        "Network",
        "data/QOS.json",
        "html/content/network/qos.html",
        (_QOS_IDS,),
        reader=_read_qos,
        builder=_build_qos,
        field_choices=_qos_choices,
        payload_validator=_validate_qos_payload,
        verifier=_verify_qos,
        revision_fields=("qos_add",),
        revision_values=_qos_revision,
        confirmation="CHANGE PRIORITY DEVICES",
        warning=(
            "Up to two selected devices receive priority. "
            "Other devices may receive less bandwidth."
        ),
    ),
)
