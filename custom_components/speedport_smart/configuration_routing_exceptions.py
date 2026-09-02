"""Closed existing hybrid-routing exception controls; no guessed create form."""

from __future__ import annotations

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
from .configuration_rule_devices import rule_devices, rule_id, rule_rows, rule_selection

if TYPE_CHECKING:
    from .configuration import SettingValues

_ENDPOINT: Final = "data/Except.json"
_READ_ENDPOINT: Final = "data/INetExcept.json"
_REFERER: Final = "html/content/internet/except.html"
_COLLECTION: Final = "addexceptentry"
_INVENTORY: Final = "except_addmdevice"
_MAX_RULES: Final = 64
_NAME: Final = SettingsField("except_name", "Rule name", "text", minimum=1, maximum=45)
_ACTIVE: Final = boolean("except_status", "Enable this routing exception")
_DELETE: Final = boolean("delete_entry", "Delete this exact routing exception")
_TYPE: Final = choice(
    "except_type",
    "Routing exception type",
    (
        ("0", "LAN devices"),
        ("1", "Target domain"),
        ("2", "Target IP address"),
        ("3", "Target IPv4 range"),
        ("4", "Fixed target port"),
        ("5", "Marked IP traffic (DiffServ)"),
    ),
)
_CONTEXT: Final = SettingsField("context", "Current rule value", "text", maximum=512)
_CONTEXT_FIELDS: Final = (
    "except_url",
    "except_ip_type",
    "except_port",
    "except_target_port",
    *(f"except_ip4_p{index}" for index in range(1, 5)),
    *(f"except_ip6_p{index}" for index in range(1, 5)),
    *(
        f"except_iprange_{side}{index}"
        for side in ("from", "to")
        for index in range(1, 5)
    ),
)


@dataclass(frozen=True, slots=True)
class RoutingExceptionTargetSpec:
    """Describe the complete inventory source, not an arbitrary mutation endpoint."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


ROUTING_EXCEPTION_TARGET_SPECS: Final = MappingProxyType(
    {
        "routing_exception_enabled": RoutingExceptionTargetSpec(
            "routing_exception_enabled",
            "Enable or disable routing exception",
            _READ_ENDPOINT,
            _REFERER,
            _COLLECTION,
            "except_name",
            (_ACTIVE,),
        ),
        "routing_exception_delete": RoutingExceptionTargetSpec(
            "routing_exception_delete",
            "Delete routing exception",
            _READ_ENDPOINT,
            _REFERER,
            _COLLECTION,
            "except_name",
            (_DELETE,),
        ),
    }
)


def _state(raw: SettingValues) -> dict[str, Any]:
    devices = rule_devices(raw, _INVENTORY)
    rules: dict[str, dict[str, Any]] = {}
    for row in rule_rows(raw.get(_COLLECTION, []), _MAX_RULES):
        identifier = rule_id(row.get("id"))
        if identifier in rules:
            raise ConfigurationError("ambiguous_routing_exception")
        entry = {
            "id": identifier,
            "except_name": _NAME.validate(row.get("except_name")),
            "except_status": _ACTIVE.read(row),
            "except_type": _TYPE.read(row),
            **{
                name: _CONTEXT.validate(row[name])
                for name in _CONTEXT_FIELDS
                if name in row
            },
        }
        if entry["except_type"] == "0" or "sid" in row:
            selected = rule_selection(row, devices)
            if entry["except_type"] == "0" and not selected:
                raise ConfigurationError("empty_routing_exception_devices")
            entry["selected_devices"] = sorted(selected)
        rules[identifier] = entry
    return {"devices": devices.identities, _COLLECTION: rules}


def routing_exception_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """Return exact stable rule IDs and names; keep routing context private."""
    if setting_id not in ROUTING_EXCEPTION_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        {"id": row["id"], "except_name": row["except_name"]}
        for row in _state(raw)[_COLLECTION].values()
    )


def routing_exception_target_metadata() -> list[dict[str, Any]]:
    """Publish only reviewed actions; create and full-form edit remain unavailable."""
    return [
        {
            **routing_exception_target_contract(spec.id, "0").metadata(),
            "requires_target": True,
        }
        for spec in ROUTING_EXCEPTION_TARGET_SPECS.values()
    ]


def routing_exception_target_contract(
    setting_id: str, target_id: str
) -> SettingsContract:
    """Bind the native direct toggle or generic deletion to one exact current ID."""
    spec = ROUTING_EXCEPTION_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    target_id = rule_id(target_id)
    deleting = setting_id == "routing_exception_delete"

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _state(raw)[_COLLECTION].get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return dict(row)

    def read(raw: SettingValues) -> dict[str, Any]:
        return (
            {"delete_entry": target_id not in _state(raw)[_COLLECTION]}
            if deleting
            else {"except_status": selected(raw)["except_status"]}
        )

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        selected(raw)
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        if set(changes) != {"except_status"}:
            raise ConfigurationError("invalid_routing_exception_change")
        active = _ACTIVE.validate(changes["except_status"])
        return {"id": target_id, "except_status": 1 if active else 0}

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            expected = _state(before)
            if deleting:
                expected[_COLLECTION].pop(target_id)
            else:
                expected[_COLLECTION][target_id]["except_status"] = changes[
                    "except_status"
                ]
            return _state(after) == expected
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Internet",
        _ENDPOINT,
        _REFERER,
        spec.fields,
        read_endpoint=_READ_ENDPOINT,
        reader=read,
        builder=build,
        payload_keys=frozenset({"id", "deleteEntry" if deleting else "except_status"}),
        acknowledgement="readback",
        verifier=verify,
        revision_values=_state,
        warning=(
            "This changes the exact existing hybrid routing exception and can "
            "interrupt matching traffic. The rule's destination, device selection "
            "and every other rule are preserved unless this rule is deleted."
        ),
        confirmation="DELETE ROUTING EXCEPTION"
        if deleting
        else "CHANGE ROUTING EXCEPTION",
    )
