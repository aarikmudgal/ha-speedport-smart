"""Pure builders for the reviewed INetIP form; never perform router I/O."""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_OCTET_SUFFIXES: Final = ("hb", "mhb", "mlb", "lb")
_TELEKOM_BASE: Final = (
    "t_number",
    "t_mbnr0",
    "t_mbnr1",
    "t_mbnr2",
    "t_mbnr3",
    "t_password",
    "t_callident",
)
_OTHER_BASE: Final = frozenset(
    {
        "other_name",
        "other_user",
        "other_password",
        "other_MTU",
        "other_vlan",
        "other_ip",
    }
)
_ZUSTART_BASE: Final = frozenset({"zustart_user", "zustart_password"})
_ADDRESS_PREFIXES: Final = {
    "fixed_ipv4_address": "other_ip",
    "dns_ipv4_primary": "other_dns",
    "dns_ipv4_secondary": "other_sdns",
}
_FIELDS: Final = (
    choice(
        "isp_selection",
        "Internet provider",
        (
            ("0", "Telekom manual"),
            ("89", "Telekom Zuhause Start"),
            ("1", "Other PPPoE provider"),
            ("99", "Telekom automatic (when provisioned)"),
        ),
    ),
    SettingsField(
        "t_number",
        "Telekom access number",
        "text",
        maximum=12,
        description="1-12 digits when Telekom manual is selected.",
    ),
    *(
        SettingsField(
            f"t_mbnr{index}",
            f"Telekom co-user digit {index + 1}",
            "text",
            maximum=1,
            description="One digit when Telekom manual is selected.",
        )
        for index in range(4)
    ),
    SettingsField("t_password", "Telekom password", "secret", minimum=1, maximum=8),
    SettingsField(
        "t_callident",
        "Telekom connection ID",
        "text",
        maximum=12,
        description="1-12 digits when Telekom manual is selected.",
    ),
    SettingsField(
        "zustart_user",
        "Zuhause Start user",
        "text",
        maximum=56,
        description="1-56 digits when Zuhause Start is selected.",
    ),
    SettingsField(
        "zustart_password", "Zuhause Start password", "secret", minimum=1, maximum=32
    ),
    SettingsField("other_name", "Other provider name", "text", maximum=255),
    SettingsField("other_user", "PPPoE user", "text", maximum=255),
    SettingsField("other_password", "PPPoE password", "secret", minimum=1, maximum=255),
    SettingsField(
        "other_MTU",
        "PPPoE MTU",
        "integer",
        maximum=1492,
        description="1440-1492 when this provider is selected; 0 is inactive.",
    ),
    boolean("other_vlan", "Use VLAN (other provider)"),
    SettingsField(
        "other_vlanid",
        "VLAN ID",
        "integer",
        maximum=4094,
        description="1-4094 when VLAN is enabled; 0 is inactive.",
    ),
    boolean("other_ip", "Use fixed IPv4 (other provider)"),
    SettingsField("fixed_ipv4_address", "Fixed IPv4 address", "text", maximum=15),
    boolean("other_dns", "Use preferred IPv4 DNS"),
    SettingsField("dns_ipv4_primary", "Primary IPv4 DNS", "text", maximum=15),
    SettingsField(
        "dns_ipv4_secondary", "Secondary IPv4 DNS (optional)", "text", maximum=15
    ),
    boolean("other_dns6", "Use preferred IPv6 DNS"),
    SettingsField("other_dns6_prim", "Primary IPv6 DNS", "text", maximum=39),
    SettingsField(
        "other_dns6_sek", "Secondary IPv6 DNS (optional)", "text", maximum=39
    ),
)
_BY_NAME: Final = {field.name: field for field in _FIELDS}
_WIRE_KEYS: Final = frozenset(
    {
        *(field.name for field in _FIELDS if field.name not in _ADDRESS_PREFIXES),
        *(
            f"{prefix}_{suffix}"
            for prefix in _ADDRESS_PREFIXES.values()
            for suffix in _OCTET_SUFFIXES
        ),
    }
)
_MIN_MTU: Final = 1440


def _value(name: str, raw: SettingValues, changes: SettingValues) -> str | int | bool:
    """Read one exact reviewed field without coercing a proposed value."""
    field = _BY_NAME[name]
    value = field.validate(changes[name]) if name in changes else field.read(raw)
    if isinstance(value, list):
        raise ConfigurationError("invalid_contract_field")
    return value


def _active_names(values: SettingValues) -> set[str]:
    """Mirror provider, check-parent and hide-parent form visibility."""
    names = {"isp_selection", "other_dns", "other_dns6"}
    if values["isp_selection"] == "1":
        names.update(_OTHER_BASE)
        if values["other_vlan"]:
            names.add("other_vlanid")
        if values["other_ip"]:
            names.add("fixed_ipv4_address")
    elif values["isp_selection"] == "89":
        names.update(_ZUSTART_BASE)
    elif values["isp_selection"] == "0":
        names.update(_TELEKOM_BASE)
    if values["other_dns"]:
        names.update({"dns_ipv4_primary", "dns_ipv4_secondary"})
    if values["other_dns6"]:
        names.update({"other_dns6_prim", "other_dns6_sek"})
    return names


def _toggles(raw: SettingValues, changes: SettingValues) -> dict[str, str | int | bool]:
    """Read branch prerequisites before any hidden field is considered."""
    values = {
        name: _value(name, raw, changes)
        for name in ("isp_selection", "other_dns", "other_dns6")
    }
    if values["isp_selection"] == "1":
        values.update(
            {name: _value(name, raw, changes) for name in ("other_vlan", "other_ip")}
        )
    return values


def _ip(value: object, *, version: int, optional: bool = False) -> str:
    """Permit literal unicast addresses only; no URLs, scopes or ambiguous octets."""
    if value == "" and optional:
        return ""
    if type(value) is not str or "%" in value:
        raise ConfigurationError("invalid_internet_address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ConfigurationError("invalid_internet_address") from None
    if (
        address.version != version
        or address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or address.is_link_local
        or (
            isinstance(address, ipaddress.IPv4Address)
            and int(address) >= int(ipaddress.IPv4Address("240.0.0.0"))
        )
    ):
        raise ConfigurationError("invalid_internet_address")
    return str(address)


def _read_octets(raw: SettingValues, prefix: str, *, optional: bool = False) -> str:
    """Combine the four exact form fields; never substitute absent components."""
    parts = [raw.get(f"{prefix}_{suffix}") for suffix in _OCTET_SUFFIXES]
    if optional and parts == ["", "", "", ""]:
        return ""
    if any(type(part) not in {str, int} for part in parts):
        raise ConfigurationError("incomplete_internet_address")
    text = ".".join(str(part) for part in parts)
    return _ip(text, version=4)


def _read_internet(raw: SettingValues) -> dict[str, str | int | bool]:
    """Read active typed fields and explicit empty inactive presentation values."""
    toggles = _toggles(raw, {})
    names = _active_names(toggles)
    result: dict[str, str | int | bool] = {}
    for field in _FIELDS:
        if field.kind == "secret":
            continue
        name = field.name
        if name not in names:
            result[name] = (
                False
                if field.kind == "boolean"
                else (0 if field.kind == "integer" else "")
            )
        elif name in _ADDRESS_PREFIXES:
            result[name] = _read_octets(
                raw, _ADDRESS_PREFIXES[name], optional=name == "dns_ipv4_secondary"
            )
        elif name in {"other_dns6_prim", "other_dns6_sek"}:
            result[name] = _ip(
                field.read(raw), version=6, optional=name == "other_dns6_sek"
            )
        else:
            result[name] = _value(name, raw, {})
    return result


def _build_internet(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Build one full INetIP POST; never issue Connect, retries or side effects."""
    values = _toggles(raw, changes)
    provider = values["isp_selection"]
    previous = _BY_NAME["isp_selection"].read(raw)
    if provider == "99":
        provision = raw.get("provis_inet")
        if type(provision) is not str or provision[1:2] != "4":
            raise ConfigurationError("automatic_provider_unavailable")
    if provider != previous:
        required = (
            _OTHER_BASE
            if provider == "1"
            else (
                _ZUSTART_BASE
                if provider == "89"
                else (frozenset(_TELEKOM_BASE) if provider == "0" else frozenset())
            )
        )
        if not required <= changes.keys():
            raise ConfigurationError("new_provider_requires_credentials")
    names = _active_names(values)
    if not changes.keys() <= names:
        raise ConfigurationError("inactive_settings_field")
    for toggle, branch_fields in (
        ("other_vlan", {"other_vlanid"}),
        ("other_ip", {"fixed_ipv4_address"}),
        ("other_dns", {"dns_ipv4_primary"}),
        ("other_dns6", {"other_dns6_prim"}),
    ):
        if toggle not in values or not values[toggle]:
            continue
        branch_changed = toggle in {"other_vlan", "other_ip"} and provider != previous
        was_enabled = False if branch_changed else _BY_NAME[toggle].read(raw)
        if not was_enabled and not branch_fields <= changes.keys():
            raise ConfigurationError("new_branch_requires_settings")
    activated_dns = {
        "dns_ipv4_secondary": values["other_dns"]
        and not _BY_NAME["other_dns"].read(raw),
        "other_dns6_sek": values["other_dns6"] and not _BY_NAME["other_dns6"].read(raw),
    }
    for name in names - values.keys():
        if activated_dns.get(name) and name not in changes:
            # The editor displays an empty optional secondary while disabled.
            # Enabling cannot silently resurrect a hidden previous resolver.
            values[name] = ""
        elif name in _ADDRESS_PREFIXES:
            values[name] = (
                _ip(changes[name], version=4, optional=name == "dns_ipv4_secondary")
                if name in changes
                else (
                    _read_octets(
                        raw,
                        _ADDRESS_PREFIXES[name],
                        optional=name == "dns_ipv4_secondary",
                    )
                )
            )
        else:
            values[name] = _value(name, raw, changes)
    if provider == "1":
        if int(values["other_MTU"]) < _MIN_MTU or (
            values["other_vlan"] and int(values["other_vlanid"]) < 1
        ):
            raise ConfigurationError("invalid_internet_link_settings")
    elif provider == "89" and not re.fullmatch(r"[0-9]+", str(values["zustart_user"])):
        raise ConfigurationError("incomplete_provider_identity")
    elif provider == "0":
        for name in _TELEKOM_BASE:
            if name != "t_password" and not re.fullmatch(r"[0-9]+", str(values[name])):
                raise ConfigurationError("invalid_telekom_identity")
    for user, password in (
        ("other_user", "other_password"),
        ("zustart_user", "zustart_password"),
        *((name, "t_password") for name in _TELEKOM_BASE if name != "t_password"),
    ):
        if (
            user in changes
            and changes[user] != raw.get(user)
            and password not in changes
        ):
            raise ConfigurationError("new_identity_requires_password")
    for name in ("other_dns6_prim", "other_dns6_sek"):
        if name in values:
            values[name] = _ip(values[name], version=6, optional=name.endswith("sek"))
    payload = {
        name: ("1" if value else "0") if type(value) is bool else value
        for name, value in values.items()
        if name not in _ADDRESS_PREFIXES
    }
    for name, prefix in _ADDRESS_PREFIXES.items():
        if name in values:
            parts = str(values[name]).split(".") if values[name] else [""] * 4
            payload.update(
                {
                    f"{prefix}_{suffix}": part
                    for suffix, part in zip(_OCTET_SUFFIXES, parts, strict=True)
                }
            )
    return payload


INTERNET_SETTINGS: Final = (
    SettingsContract(
        "internet_connection",
        "Internet provider, PPPoE and DNS",
        "Internet",
        "data/INetIP.json",
        "html/content/internet/connection.html",
        _FIELDS,
        builder=_build_internet,
        reader=_read_internet,
        payload_keys=_WIRE_KEYS,
        revision_fields=(*sorted(_WIRE_KEYS), "provis_inet"),
        readback_policy="reconnect_required",
        confirmation="CHANGE INTERNET SETTINGS",
        warning=(
            "Provider, VLAN, fixed address and DNS changes may disconnect Internet "
            "and telephony. Provider switches require explicit credentials. "
            "This saves settings only; it does not automatically connect or retry. "
            "Empty inactive fields and zero inactive numbers are not sent."
        ),
    ),
)
