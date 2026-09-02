"""Exact powerline rename form bound to fresh inventory identity; no network I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField
from .configuration_rule_devices import MAX_RULE_DEVICES, rule_id, rule_rows

if TYPE_CHECKING:
    from .configuration import SettingValues

_ENDPOINT: Final = "data/PWLineDevice.json"
_READ_ENDPOINT: Final = "data/DeviceList.json"
_REFERER: Final = "html/content/network/devices.html"
_COLLECTION: Final = "addpwlinedevice"
_MAC: Final = re.compile(
    r"(?:(?:[0-9A-Fa-f]{2}:){5}|(?:[0-9A-Fa-f]{2}-){5})[0-9A-Fa-f]{2}"
)
_NAME: Final = SettingsField(
    "pwline_name",
    "Powerline device name",
    "text",
    minimum=1,
    maximum=28,
    description="Use letters A-Z, digits and hyphens; at most 28 characters.",
)
_NAME_PATTERN: Final = re.compile(r"[0-9A-Za-z-]{1,28}")
_SPEED_FIELDS: Final = ("pwline_downspeed", "pwline_upspeed")
_SPEED: Final = SettingsField("speed", "Current link speed", "text", maximum=64)


@dataclass(frozen=True, slots=True)
class PowerlineTargetSpec:
    """Describe an inventory read; the returned contract owns its separate POST."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


POWERLINE_TARGET_SPECS: Final = MappingProxyType(
    {
        "powerline_rename": PowerlineTargetSpec(
            "powerline_rename",
            "Rename powerline device",
            _READ_ENDPOINT,
            _REFERER,
            _COLLECTION,
            "pwline_name",
            (_NAME,),
        )
    }
)


def _mac(value: object) -> str:
    if type(value) is not str or not _MAC.fullmatch(value):
        raise ConfigurationError("invalid_powerline_identity")
    return value.lower().replace("-", ":")


def _rows(raw: SettingValues) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rule_rows(raw.get(_COLLECTION, []), MAX_RULE_DEVICES):
        identity = _mac(row.get("pwline_mac"))
        if identity in result:
            raise ConfigurationError("ambiguous_powerline_identity")
        result[identity] = {
            # V5's existing-device hidden input has explicit value=0. JSON may
            # replace it; absence retains that native default, not a new row ID.
            "id": rule_id(row.get("id", "0")),
            "pwline_mac": row["pwline_mac"],
            "pwline_name": _NAME.validate(row.get("pwline_name")),
            **{field: _SPEED.validate(row.get(field)) for field in _SPEED_FIELDS},
        }
    return result


def _revision(raw: SettingValues) -> dict[str, Any]:
    """Preserve all exact physical identities and names, not changing link rates."""
    return {
        _COLLECTION: {
            identity: {
                "id": row["id"],
                "pwline_mac": identity,
                "pwline_name": row["pwline_name"],
            }
            for identity, row in _rows(raw).items()
        }
    }


def powerline_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """Use the physical MAC as target even when multiple native hidden IDs are 0."""
    if setting_id not in POWERLINE_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        {"id": identity, "pwline_name": f"{row['pwline_name']} ({identity})"}
        for identity, row in _rows(raw).items()
    )


def powerline_target_metadata() -> list[dict[str, Any]]:
    """Describe the closed editor without asserting a real physical target."""
    return [
        {
            **powerline_target_contract(
                "powerline_rename", "00:00:00:00:00:00"
            ).metadata(),
            "requires_target": True,
        }
    ]


def powerline_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind a rename to one complete, fresh DeviceList powerline inventory row."""
    spec = POWERLINE_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    target_id = _mac(target_id)

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _rows(raw).get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return row

    def read(raw: SettingValues) -> dict[str, Any]:
        return {"pwline_name": selected(raw)["pwline_name"]}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        current = selected(raw)
        if set(changes) != {"pwline_name"}:
            raise ConfigurationError("invalid_powerline_change")
        name = _NAME.validate(changes["pwline_name"])
        if type(name) is not str or not _NAME_PATTERN.fullmatch(name):
            raise ConfigurationError("invalid_powerline_name")
        return {**current, "pwline_name": name}

    def valid(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            return build(raw, {"pwline_name": payload["pwline_name"]}) == dict(payload)
        except (ConfigurationError, KeyError, TypeError):
            return False

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            payload = build(before, changes)
            expected = _revision(before)
            expected[_COLLECTION][target_id]["pwline_name"] = payload["pwline_name"]
            return _revision(after) == expected
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Network",
        _ENDPOINT,
        _REFERER,
        spec.fields,
        read_endpoint=_READ_ENDPOINT,
        reader=read,
        builder=build,
        payload_validator=valid,
        verifier=verify,
        revision_values=_revision,
        warning=(
            "Rename this exact powerline device. Its current ID, physical address "
            "and fresh native link-rate fields are preserved. No pairing, removal "
            "or identify action is performed."
        ),
        confirmation="RENAME POWERLINE DEVICE",
    )
