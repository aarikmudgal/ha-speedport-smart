"""
Pure, fixed-path LAN IPv4 commands; this module performs no router I/O.

The public LAN page posts eleven fields, including four IPv6 fields even when
only IPv4 changes. Preserve those IPv6 values and the DHCP suffix range from a
fresh authenticated snapshot. Authentication, exact router identity, explicit
positive ACK, reconnect, fresh readback, and logout remain the caller's duties.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from ipaddress import IPv4Address, IPv4Network
from types import MappingProxyType
from typing import Final

LAN_ENDPOINT: Final = "data/LAN.json"
LAN_REFERER: Final = "html/content/network/lan.html"
LAN_MUTATION_FIELDS: Final = (
    "lan_ipv4_1",
    "lan_ipv4_2",
    "lan_ipv4_3",
    "lan_ipv4_4",
    "lan_mask_2",
    "lan_mask_3",
    "lan_mask_4",
    "lan_ip_v6_used",
    "lan_ip_v6",
    "lan_ip_v6_pext",
    "lan_ip_v6_arec",
)
_PRIVATE_NETWORKS: Final = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)
_OCTET_MAX: Final = 255
_MAX_IPV6_FIELD_LENGTH: Final = 128
_DECIMAL_OCTET: Final = re.compile(r"(?:0|[1-9][0-9]{0,2})")


class LanManagementValidationError(ValueError):
    """LAN data cannot safely produce or verify the fixed mutation contract."""


def _wire_integer(value: object, *, maximum: int = _OCTET_MAX) -> int:
    """Accept only canonical router decimal strings or exact integers."""
    if type(value) is int:
        parsed = value
    elif type(value) is str and _DECIMAL_OCTET.fullmatch(value):
        parsed = int(value)
    else:
        raise LanManagementValidationError("LAN field is not a canonical integer")
    if not 0 <= parsed <= maximum:
        raise LanManagementValidationError("LAN integer is outside its bounds")
    return parsed


def _ipv4_network(address: object, mask: object) -> tuple[IPv4Address, IPv4Network]:
    """Validate canonical private IPv4, contiguous mask, and usable host."""
    if type(address) is not str or type(mask) is not str:
        raise LanManagementValidationError("LAN IPv4 and mask must be strings")
    try:
        ip = IPv4Address(address)
        network = IPv4Network(f"{address}/{mask}", strict=False)
    except ValueError:
        raise LanManagementValidationError("LAN IPv4 or mask is invalid") from None
    if str(ip) != address or str(network.netmask) != mask:
        raise LanManagementValidationError("LAN IPv4 and mask must be canonical")
    if not any(network.subnet_of(private) for private in _PRIVATE_NETWORKS):
        raise LanManagementValidationError("LAN subnet must remain entirely private")
    if ip in (network.network_address, network.broadcast_address):
        raise LanManagementValidationError("LAN address must be a usable host")
    return ip, network


@dataclass(frozen=True, slots=True, repr=False)
class LanSnapshot:
    """Complete typed LAN preflight, excluding unrelated router response fields."""

    ipv4_address: str
    subnet_mask: str
    ipv6_enabled: int
    ipv6_address: str
    ipv6_pext: int
    ipv6_arec: int
    dhcp_from: int
    dhcp_to: int

    def __post_init__(self) -> None:
        """Validate host/subnet/pool relationships even for direct construction."""
        ip, network = _ipv4_network(self.ipv4_address, self.subnet_mask)
        for flag in (self.ipv6_enabled, self.ipv6_pext, self.ipv6_arec):
            if type(flag) is not int or flag not in (0, 1):
                raise LanManagementValidationError("LAN IPv6 flags must be binary")
        if (
            type(self.ipv6_address) is not str
            or len(self.ipv6_address) > _MAX_IPV6_FIELD_LENGTH
            or not self.ipv6_address.isascii()
            or (self.ipv6_address != "" and not self.ipv6_address.isprintable())
        ):
            raise LanManagementValidationError("LAN preserved IPv6 field is invalid")
        for octet in (self.dhcp_from, self.dhcp_to):
            if type(octet) is not int or not 0 <= octet <= _OCTET_MAX:
                raise LanManagementValidationError("LAN DHCP suffix is invalid")
        if self.dhcp_from > self.dhcp_to:
            raise LanManagementValidationError("LAN DHCP range is reversed")
        # Firmware keeps the DHCP suffixes but uses the proposed IPv4 prefix.
        prefix = self.ipv4_address.rsplit(".", 1)[0]
        first = IPv4Address(f"{prefix}.{self.dhcp_from}")
        last = IPv4Address(f"{prefix}.{self.dhcp_to}")
        if any(
            endpoint not in network
            or endpoint in (network.network_address, network.broadcast_address)
            for endpoint in (first, last)
        ):
            raise LanManagementValidationError("LAN DHCP range leaves usable subnet")
        if first <= ip <= last:
            raise LanManagementValidationError("LAN DHCP range includes the router")


def parse_lan_snapshot(raw: Mapping[str, object]) -> LanSnapshot:
    """Parse a flattened fresh LAN response; never default missing fields."""
    if not isinstance(raw, Mapping):
        raise LanManagementValidationError("LAN snapshot must be a mapping")
    if not {*LAN_MUTATION_FIELDS, "lan_dhcp_from", "lan_dhcp_to"} <= raw.keys():
        raise LanManagementValidationError("LAN snapshot is incomplete")
    ipv4 = ".".join(
        str(_wire_integer(raw[f"lan_ipv4_{index}"])) for index in range(1, 5)
    )
    mask = "255." + ".".join(
        str(_wire_integer(raw[f"lan_mask_{index}"])) for index in range(2, 5)
    )
    ipv6 = raw["lan_ip_v6"]
    if type(ipv6) is not str:
        raise LanManagementValidationError("LAN preserved IPv6 field must be a string")
    return LanSnapshot(
        ipv4_address=ipv4,
        subnet_mask=mask,
        ipv6_enabled=_wire_integer(raw["lan_ip_v6_used"], maximum=1),
        ipv6_address=ipv6,
        ipv6_pext=_wire_integer(raw["lan_ip_v6_pext"], maximum=1),
        ipv6_arec=_wire_integer(raw["lan_ip_v6_arec"], maximum=1),
        dhcp_from=_wire_integer(raw["lan_dhcp_from"]),
        dhcp_to=_wire_integer(raw["lan_dhcp_to"]),
    )


@dataclass(frozen=True, slots=True, repr=False)
class LanIPv4Command:
    """Immutable private expectation for one fixed-path LAN IPv4 mutation."""

    before: LanSnapshot
    expected: LanSnapshot

    def __post_init__(self) -> None:
        """Reject forged commands that change preserved fields or do nothing."""
        if (
            type(self.before) is not LanSnapshot
            or type(self.expected) is not LanSnapshot
        ):
            raise LanManagementValidationError("LAN command requires typed snapshots")
        preserved = replace(
            self.expected,
            ipv4_address=self.before.ipv4_address,
            subnet_mask=self.before.subnet_mask,
        )
        if preserved != self.before:
            raise LanManagementValidationError("LAN command changes preserved fields")
        if self.before == self.expected:
            raise LanManagementValidationError("LAN command would not change IPv4")

    @property
    def endpoint(self) -> str:
        """Return the only mutation endpoint; callers cannot supply a path."""
        return LAN_ENDPOINT

    @property
    def referer(self) -> str:
        """Return the exact LAN page context."""
        return LAN_REFERER

    @property
    def payload(self) -> Mapping[str, str]:
        """Return exactly eleven wire fields, never unrelated preflight data."""
        state = self.expected
        payload = {
            f"lan_ipv4_{index}": value
            for index, value in enumerate(state.ipv4_address.split("."), start=1)
        }
        payload.update(
            {
                f"lan_mask_{index}": value
                for index, value in enumerate(state.subnet_mask.split(".")[1:], start=2)
            }
        )
        payload.update(
            {
                "lan_ip_v6_used": str(state.ipv6_enabled),
                "lan_ip_v6": state.ipv6_address,
                "lan_ip_v6_pext": str(state.ipv6_pext),
                "lan_ip_v6_arec": str(state.ipv6_arec),
            }
        )
        return MappingProxyType(payload)


def build_lan_ipv4_command(
    snapshot: LanSnapshot, *, ipv4_address: str, subnet_mask: str
) -> LanIPv4Command:
    """Build a validated IPv4-only command while preserving every other field."""
    if type(snapshot) is not LanSnapshot:
        raise LanManagementValidationError("LAN command requires a typed snapshot")
    return LanIPv4Command(
        before=snapshot,
        expected=replace(snapshot, ipv4_address=ipv4_address, subnet_mask=subnet_mask),
    )


def lan_readback_matches(command: LanIPv4Command, fresh: LanSnapshot) -> bool:
    """
    Compare all eleven submitted fields and the two preserved DHCP suffixes.

    This proves only equality. The caller must require a positive mutation ACK,
    obtain this snapshot independently after the write, and verify router identity.
    A POST response echo or a cached snapshot is not independent readback.
    """
    return (
        type(command) is LanIPv4Command
        and type(fresh) is LanSnapshot
        and fresh == command.expected
    )
