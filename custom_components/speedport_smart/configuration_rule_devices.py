"""Shared strict device identity and compound selection for closed rule forms."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsField

if TYPE_CHECKING:
    from .configuration import SettingValues

MAX_RULE_DEVICES: Final = 253
_SID: Final = SettingsField("sid", "Device ID", "identifiers", maximum=1)
_NAME: Final = SettingsField("name", "Device name", "text", maximum=256)
_MAC: Final = re.compile(
    r"(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}"
)
_ID: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_MAX_ID: Final = 2**31 - 1


@dataclass(frozen=True, slots=True, repr=False)
class RuleDevices:
    """Keep full identities private; only SID and bounded label become choices."""

    identities: tuple[tuple[str, str, str], ...]

    @property
    def sids(self) -> frozenset[str]:
        """Return exact current identifiers without position aliases."""
        return frozenset(sid for sid, _, _ in self.identities)

    @property
    def choices(self) -> tuple[tuple[str, str], ...]:
        """Disambiguate repeated names while keeping MAC addresses private."""
        return tuple(
            (sid, f"{label[: 253 - len(sid)]} ({sid})" if label else sid)
            for sid, label, _ in self.identities
        )


def rule_rows(value: object, maximum: int) -> list[Mapping[str, Any]]:
    """Accept codec singleton/list representations, never malformed empty objects."""
    if isinstance(value, Mapping) and value:
        value = [value]
    if (
        type(value) is not list
        or len(value) > maximum
        or any(not isinstance(item, Mapping) for item in value)
    ):
        raise ConfigurationError("incomplete_rule_collection")
    return value


def rule_id(value: object) -> str:
    """Normalize only a bounded canonical numeric router ID."""
    if type(value) is int:
        value = str(value)
    if type(value) is not str or not _ID.fullmatch(value) or int(value) > _MAX_ID:
        raise ConfigurationError("invalid_rule_id")
    return value


def _sid(value: object) -> str:
    result = _SID.validate([value])
    if not isinstance(result, list):
        raise ConfigurationError("invalid_device_identifier")
    return result[0]


def rule_devices(raw: SettingValues, inventory_key: str) -> RuleDevices:
    """Validate exact stable inventory; callers supply a reviewed constant key."""
    seen: set[str] = set()
    result = []
    for row in rule_rows(raw.get(inventory_key), MAX_RULE_DEVICES):
        sid = _sid(row.get("sid"))
        label = _NAME.validate(row.get("mdevice_name"))
        mac = row.get("mdevice_mac")
        if (
            sid in seen
            or type(label) is not str
            or type(mac) is not str
            or not _MAC.fullmatch(mac)
        ):
            raise ConfigurationError("ambiguous_rule_device")
        seen.add(sid)
        result.append((sid, label, mac.lower().replace("-", ":")))
    return RuleDevices(tuple(result))


def rule_selection(row: SettingValues, devices: RuleDevices) -> frozenset[str]:
    """Require exactly one complete SID/checkbox compound per available device."""
    selected: set[str] = set()
    seen: set[str] = set()
    accepted = devices.sids
    for item in rule_rows(row.get("sid"), MAX_RULE_DEVICES):
        if set(item) != {"sid", "mdevice_name"}:
            raise ConfigurationError("missing_rule_compounds")
        sid = _sid(item["sid"])
        flag = item["mdevice_name"]
        if (
            sid in seen
            or sid not in accepted
            or type(flag) is not str
            or flag not in {"0", "1"}
        ):
            raise ConfigurationError("ambiguous_rule_compounds")
        seen.add(sid)
        if flag == "1":
            selected.add(sid)
    if seen != accepted:
        raise ConfigurationError("incomplete_rule_compounds")
    return frozenset(selected)


def rule_selection_payload(
    devices: RuleDevices, selected: frozenset[str], ordinal: int
) -> dict[str, str]:
    """Serialize inventory-first cloning: device ordinal followed by rule ordinal."""
    if not selected <= devices.sids:
        raise ConfigurationError("unknown_rule_device")
    return {
        key: value
        for index, (sid, _, _) in enumerate(devices.identities, 1)
        for key, value in (
            (f"sid[{index}{ordinal}]", sid),
            (f"mdevice_name[{index}{ordinal}]", "1" if sid in selected else "0"),
        )
    }
