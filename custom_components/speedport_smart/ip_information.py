"""Private, read-only IPData projection from the native IP-information page."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import IPv4Address, IPv6Address, IPv6Interface
from typing import Any, Final

from .configuration import ConfigurationError, normalize_configuration_payload

IP_INFORMATION_ENDPOINT: Final = "data/IPData.json"
IP_INFORMATION_REFERER: Final = "html/content/internet/con_ipdata.html"
_MAX_ADDRESS_LENGTH: Final = 128
# Exact var bindings in con_ipdata.html; values never enter normalized hub data.
_IPV4_FIELDS: Final = {
    "public_ip_v4": "address",
    "gateway_ip_v4": "gateway",
    "dns_v4": "dns_primary",
    "sec_dns_v4": "dns_secondary",
}
_IPV6_FIELDS: Final = {
    "transmitted_ip_v6_pool_for_lan": "delegated_prefix",
    "used_ip_v6_lan": "lan_prefix",
    "public_ip_v6": "address",
    "gateway_ip_v6": "gateway",
    "dns_v6": "dns_primary",
    "sec_dns_v6": "dns_secondary",
}


def _address(value: object, *, ipv6: bool, prefix: bool) -> str | None:
    """Accept only bounded address syntax; missing values are not invented."""
    if value is None or value == "":
        return None
    if (
        not isinstance(value, str)
        or len(value) > _MAX_ADDRESS_LENGTH
        or not value.isprintable()
        or "%" in value
    ):
        raise ConfigurationError("ip_information_unavailable")
    try:
        if not ipv6:
            return str(IPv4Address(value))
        if prefix and "/" in value:
            # Preserve any host portion returned by the router; do not synthesize
            # a network address or an absent prefix length for display.
            return str(IPv6Interface(value))
        return str(IPv6Address(value))
    except ValueError:
        raise ConfigurationError("ip_information_unavailable") from None


def read_ip_information(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the exact native address fields, without caching or mutation."""
    data = normalize_configuration_payload(raw)
    if not any(key in data for key in (*_IPV4_FIELDS, *_IPV6_FIELDS)):
        # Global authenticated fallback data is not an empty IP-information page.
        raise ConfigurationError("ip_information_unavailable")
    result: dict[str, Any] = {"ipv4": {}, "ipv6": {}}
    for version, fields in (("ipv4", _IPV4_FIELDS), ("ipv6", _IPV6_FIELDS)):
        for wire_name, name in fields.items():
            address = _address(
                data.get(wire_name),
                ipv6=version == "ipv6",
                prefix=name in {"delegated_prefix", "lan_prefix"},
            )
            if address is not None:
                result[version][name] = address
    return result
