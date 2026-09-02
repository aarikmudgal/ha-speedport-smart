"""Diagnostics support for Speedport Smart."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from .const import REDACTED

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import SpeedportConfigEntry

_MAC_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])"
)
_IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
    r"(?:/(?:3[0-2]|[12]?\d))?(?![\d.])"
)
_IPV6_PATTERN = re.compile(
    r"(?<![0-9a-fA-F:])"
    r"(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"
    r"(?:/(?:12[0-8]|1[01]\d|\d?\d))?"
    r"(?![0-9a-fA-F:])"
)
_SECRET_KEY_PARTS = frozenset(
    {
        "credential",
        "dect_pin",
        "password",
        "pin_code",
        "private_key",
        "public_key",
        "preshared",
        "secret",
        "sim_pin",
        "sim_puk",
        "sip_auth",
        "token",
        "wireguard_key",
    }
)
_IDENTIFIER_KEY_PARTS = frozenset(
    {
        "client_mac",
        "fingerprint",
        "hardware_address",
        "hostname",
        "imei",
        "imsi",
        "mac_address",
        "serial",
        "serial_number",
        "ssid",
    }
)
_IDENTIFIER_KEYS = frozenset(
    {"device_id", "id", "router_id", "source_row_id", "uid", "uuid"}
)
_CHILD_LABEL_KEYS = frozenset(
    {
        "access_point",
        "label",
        "mesh_parent",
        "mesh_node",
        "name",
        "parent",
        "parental_profile",
        "ssid",
        "target",
        "title",
    }
)
_LOCATION_KEYS = frozenset({"cell_id", "cellid"})
_VERSION_METADATA_KEYS = frozenset(
    {
        "firmware",
        "firmware_version",
        "hardware_version",
        "hw_version",
        "latest_firmware",
        "model",
        "sw_version",
        "version",
    }
)
_ADDRESS_KEYS = frozenset(
    {
        "address",
        "dns",
        "ddns_domain",
        "ddns_update_server",
        "domain",
        "domain_name",
        "external_ip",
        "gateway",
        "host",
        "hostname",
        "ip",
        "ip_address",
        "ipv4",
        "ipv4_address",
        "ipv4_network",
        "ipv4_prefix",
        "ipv6",
        "ipv6_address",
        "ipv6_gua",
        "ipv6_network",
        "ipv6_prefix",
        "ipv6_ula",
        "network",
        "network_address",
        "owner_ip_address",
        "prefix",
        "public_ip",
        "public_ipv4",
        "public_ipv6",
        "subnet",
        "subnet_mask",
        "ula_address",
        "update_server",
        "usable_ipv6_range",
        "wan_ip",
    }
)
_PHONE_KEY_PARTS = frozenset(
    {
        "assigned_number",
        "called_number",
        "caller",
        "calling_number",
        "contact_address",
        "contact_name",
        "contact_number",
        "incoming_number",
        "number_assignment",
        "outgoing_number",
        "phone_number",
        "telephone_number",
    }
)
_PHONE_KEYS = frozenset({"callee", "destination", "number", "phone", "telephone"})
_RAW_LOG_KEYS = frozenset({"event_log", "logs", "security_log", "system_log"})
_UNTRUSTED_TEXT_KEYS = frozenset(
    {
        "error_reason",
        "failure_reason",
        "message",
        "reason",
        "status_message",
    }
)
_ERROR_CLASS_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def safe_error_class_name(error: object) -> str:
    """Return one bounded ASCII exception class without its message."""
    if isinstance(error, BaseException):
        candidate = type(error).__name__
    elif isinstance(error, str):
        candidate = error.partition(":")[0]
    else:
        return "UnknownError"
    if _ERROR_CLASS_PATTERN.fullmatch(candidate):
        return candidate
    return "UnknownError"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SpeedportConfigEntry
) -> dict[str, Any]:
    """Return fully redacted diagnostics for a config entry."""
    del hass
    hub = entry.runtime_data
    diagnostics = {
        "config_entry": {
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": hub.diagnostics(),
    }
    return cast("dict[str, Any]", _redact(diagnostics))


def _redact(value: Any, *, key: str = "") -> Any:
    """Recursively redact credentials and subscriber-identifying information."""
    normalized_key = key.casefold()
    if normalized_key in _RAW_LOG_KEYS or normalized_key in _UNTRUSTED_TEXT_KEYS:
        return REDACTED
    if any(part in normalized_key for part in _SECRET_KEY_PARTS):
        return REDACTED
    if normalized_key in _IDENTIFIER_KEYS or any(
        part in normalized_key for part in _IDENTIFIER_KEY_PARTS
    ):
        return REDACTED
    if normalized_key in _CHILD_LABEL_KEYS or normalized_key in _LOCATION_KEYS:
        return REDACTED
    if normalized_key in _ADDRESS_KEYS:
        return REDACTED
    if any(part in normalized_key for part in _PHONE_KEY_PARTS):
        return REDACTED
    if normalized_key in _PHONE_KEYS:
        return REDACTED

    if isinstance(value, Mapping):
        return {
            str(item_key): _redact(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact(item, key=key) for item in value]
    if isinstance(value, str):
        return _redact_string(value, key=normalized_key)
    return value


def _redact_string(value: str, *, key: str = "") -> str:
    """Redact address-like values even when nested inside raw API text."""
    if key in _VERSION_METADATA_KEYS:
        return value
    candidate = value.strip().strip("[]")
    if _is_address_or_network(candidate):
        return REDACTED
    redacted = _MAC_PATTERN.sub(REDACTED, value)
    redacted = _IPV4_PATTERN.sub(_redact_address_match, redacted)
    return _IPV6_PATTERN.sub(_redact_address_match, redacted)


def _redact_address_match(match: re.Match[str]) -> str:
    """Redact only regex candidates that parse as an IP address or network."""
    candidate = match.group()
    return REDACTED if _is_address_or_network(candidate) else candidate


def _is_address_or_network(value: str) -> bool:
    """Return whether a complete value is an IPv4/IPv6 address or CIDR network."""
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True
