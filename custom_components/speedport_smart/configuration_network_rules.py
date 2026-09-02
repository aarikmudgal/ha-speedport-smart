"""Closed network-rule CRUD with exact IDs and complete collection readback."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_port_rules import (
    PORT_RULE_SETTINGS,
    PORT_RULE_TARGET_SPECS,
    port_rule_target_contract,
    port_rule_target_rows,
)

if TYPE_CHECKING:
    from .configuration import SettingValues
    from .configuration_port_rules import PortRuleTargetSpec

_DNS_ENDPOINT: Final = "data/DNSExcept.json"
_DNS_REFERER: Final = "html/content/network/dns_rebind.html"
_DNS_COLLECTION: Final = "adddnsexcept"
_MAX_DNS_EXCEPTIONS: Final = 10
_DNS_FIELD: Final = SettingsField(
    "dns_except",
    "Domain exempted from DNS rebind protection",
    "text",
    maximum=255,
    description="Enter a plain DNS domain name, not a URL, wildcard or IP address.",
)
_DELETE: Final = boolean("delete_entry", "Delete this exact exception")
_DNS_ENABLED: Final = boolean("use_dnsrebind", "DNS rebind protection")
_ID: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_DOMAIN_LABEL: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_MAX_ID: Final = 2**31 - 1
_DOMAIN_MAX: Final = 253
_DNS_WARNING: Final = (
    "An exception disables DNS rebind protection for its domain. "
    "Only add domains you trust. The global protection setting is preserved."
)


@dataclass(frozen=True, slots=True)
class NetworkRuleTargetSpec:
    """Static existing-row binding used by the shared target dispatcher."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


NETWORK_RULE_TARGET_SPECS: Final[
    Mapping[str, NetworkRuleTargetSpec | PortRuleTargetSpec]
] = MappingProxyType(
    {
        **PORT_RULE_TARGET_SPECS,
        "dns_exception_edit": NetworkRuleTargetSpec(
            "dns_exception_edit",
            "Edit DNS rebind exception",
            _DNS_ENDPOINT,
            _DNS_REFERER,
            _DNS_COLLECTION,
            "dns_except",
            (_DNS_FIELD,),
        ),
        "dns_exception_delete": NetworkRuleTargetSpec(
            "dns_exception_delete",
            "Delete DNS rebind exception",
            _DNS_ENDPOINT,
            _DNS_REFERER,
            _DNS_COLLECTION,
            "dns_except",
            (_DELETE,),
        ),
    }
)


def _identifier(value: object) -> str:
    if type(value) is int:
        value = str(value)
    if type(value) is not str or not _ID.fullmatch(value) or int(value) > _MAX_ID:
        raise ConfigurationError("invalid_network_rule_id")
    return value


def _domain(value: object) -> str:
    """Use a conservative literal DNS-name slice of the firmware text field."""
    value = _DNS_FIELD.validate(value)
    if type(value) is not str or not value or len(value.rstrip(".")) > _DOMAIN_MAX:
        raise ConfigurationError("invalid_dns_exception")
    domain = value.rstrip(".")
    if value.endswith("..") or not all(
        _DOMAIN_LABEL.fullmatch(part) for part in domain.split(".")
    ):
        raise ConfigurationError("invalid_dns_exception")
    if all(part.isdigit() for part in domain.split(".")):
        raise ConfigurationError("invalid_dns_exception")
    return domain.lower()


def _dns_rows(raw: SettingValues) -> tuple[dict[str, str], ...]:
    """Require the protection flag to prove the captured empty response shape."""
    _DNS_ENABLED.read(raw)
    value = raw.get(_DNS_COLLECTION, [])
    if isinstance(value, Mapping) and value:
        value = [value]
    if type(value) is not list or len(value) > _MAX_DNS_EXCEPTIONS:
        raise ConfigurationError("incomplete_dns_exceptions")
    result = []
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ConfigurationError("incomplete_dns_exceptions")
        identifier = _identifier(row.get("id"))
        if identifier in seen:
            raise ConfigurationError("ambiguous_dns_exception")
        seen.add(identifier)
        result.append({"id": identifier, "dns_except": _domain(row.get("dns_except"))})
    return tuple(result)


def network_rule_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """Return bounded exact targets, never an index masquerading as an ID."""
    if setting_id in PORT_RULE_TARGET_SPECS:
        return port_rule_target_rows(setting_id, raw)
    if setting_id not in NETWORK_RULE_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return _dns_rows(raw)


def _dns_selected(raw: SettingValues, target_id: str) -> dict[str, str]:
    matches = [row for row in _dns_rows(raw) if row["id"] == target_id]
    if len(matches) != 1:
        raise ConfigurationError("stale_settings")
    return matches[0]


def _dns_map(raw: SettingValues) -> dict[str, str]:
    return {row["id"]: row["dns_except"] for row in _dns_rows(raw)}


def _dns_unique(raw: SettingValues, domain: str, target_id: str | None = None) -> None:
    if any(
        row["dns_except"] == domain and row["id"] != target_id for row in _dns_rows(raw)
    ):
        raise ConfigurationError("duplicate_dns_exception")


def _dns_create_read(raw: SettingValues) -> dict[str, str]:
    _dns_rows(raw)
    return {"dns_except": ""}


def _dns_create_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    if set(changes) != {"dns_except"}:
        raise ConfigurationError
    if len(_dns_rows(raw)) >= _MAX_DNS_EXCEPTIONS:
        raise ConfigurationError("dns_exception_limit")
    domain = _domain(changes["dns_except"])
    _dns_unique(raw, domain)
    # The static empty-template hidden ID is explicitly -1 in v7 capture.
    return {"id": "-1", "dns_except": domain}


def _dns_create_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        domain = _dns_create_build(before, changes)["dns_except"]
        previous, current = _dns_map(before), _dns_map(after)
        created = current.keys() - previous.keys()
        return (
            _DNS_ENABLED.read(before) == _DNS_ENABLED.read(after)
            and len(created) == 1
            and len(current) == len(previous) + 1
            and all(current.get(key) == value for key, value in previous.items())
            and current[next(iter(created))] == domain
        )
    except ConfigurationError:
        return False


def network_rule_target_metadata() -> list[dict[str, Any]]:
    """Describe existing-rule editors without inventing a target row."""
    return [
        {
            **network_rule_target_contract(
                spec.id, getattr(spec, "metadata_target", "0")
            ).metadata(),
            "requires_target": True,
        }
        for spec in NETWORK_RULE_TARGET_SPECS.values()
    ]


def network_rule_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind one existing exception to an exact immutable target ID."""
    if setting_id in PORT_RULE_TARGET_SPECS:
        return port_rule_target_contract(setting_id, target_id)
    spec = NETWORK_RULE_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    target_id = _identifier(target_id)
    deleting = setting_id == "dns_exception_delete"

    def read(raw: SettingValues) -> dict[str, Any]:
        if deleting:
            return {"delete_entry": target_id not in _dns_map(raw)}
        return {"dns_except": _dns_selected(raw, target_id)["dns_except"]}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        _dns_selected(raw, target_id)
        if deleting:
            if set(changes) != {"delete_entry"} or changes["delete_entry"] is not True:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        if set(changes) != {"dns_except"}:
            raise ConfigurationError
        domain = _domain(changes["dns_except"])
        _dns_unique(raw, domain, target_id)
        return {"id": target_id, "dns_except": domain}

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            payload = build(before, changes)
            expected = _dns_map(before)
            if deleting:
                expected.pop(target_id)
            else:
                expected[target_id] = str(payload["dns_except"])
            return (
                _DNS_ENABLED.read(before) == _DNS_ENABLED.read(after)
                and _dns_map(after) == expected
            )
        except ConfigurationError:
            return False

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            _dns_selected(raw, target_id)
            if deleting:
                return dict(payload) == {"id": target_id, "deleteEntry": "delete"}
            return (
                set(payload) == {"id", "dns_except"}
                and payload["id"] == target_id
                and _domain(payload["dns_except"]) == payload["dns_except"]
            )
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Network",
        spec.endpoint,
        spec.referer,
        spec.fields,
        reader=read,
        builder=build,
        payload_validator=validate_payload,
        verifier=verify,
        revision_fields=(_DNS_COLLECTION, "use_dnsrebind"),
        warning=_DNS_WARNING,
        confirmation=("DELETE DNS EXCEPTION" if deleting else "SAVE DNS EXCEPTION"),
    )


NETWORK_RULE_SETTINGS: Final = (
    *PORT_RULE_SETTINGS,
    SettingsContract(
        "dns_exception_create",
        "Add DNS rebind exception",
        "Network",
        _DNS_ENDPOINT,
        _DNS_REFERER,
        (_DNS_FIELD,),
        reader=_dns_create_read,
        builder=_dns_create_build,
        payload_keys=frozenset({"id", "dns_except"}),
        verifier=_dns_create_verify,
        verifier_owns_fields=True,
        revision_fields=(_DNS_COLLECTION, "use_dnsrebind"),
        warning=_DNS_WARNING,
        confirmation="ADD DNS EXCEPTION",
    ),
)
