"""Offline proof for the exact LAN IPv4 command; no router writes or reads."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from custom_components.speedport_smart.lan_management import (
    LAN_ENDPOINT,
    LAN_MUTATION_FIELDS,
    LAN_REFERER,
    LanIPv4Command,
    LanManagementValidationError,
    build_lan_ipv4_command,
    lan_readback_matches,
    parse_lan_snapshot,
)


def _raw(**overrides: object) -> dict[str, object]:
    """Return a synthetic complete flattened LAN snapshot."""
    return {
        "lan_ipv4_1": "192",
        "lan_ipv4_2": "168",
        "lan_ipv4_3": "2",
        "lan_ipv4_4": "1",
        "lan_mask_2": "255",
        "lan_mask_3": "255",
        "lan_mask_4": "0",
        "lan_ip_v6_used": "1",
        "lan_ip_v6": "fd12:3456:789a::1",
        "lan_ip_v6_pext": "1",
        "lan_ip_v6_arec": "0",
        "lan_dhcp_from": "100",
        "lan_dhcp_to": "200",
        **overrides,
    }


def _command() -> LanIPv4Command:
    """Build one synthetic subnet migration."""
    return build_lan_ipv4_command(
        parse_lan_snapshot(_raw()),
        ipv4_address="192.168.3.1",
        subnet_mask="255.255.255.0",
    )


def test_exact_endpoint_payload_and_preservation() -> None:
    """Only seven IPv4 fields change; all four IPv6 fields remain intact."""
    raw = _raw(unknown_field="DO-NOT-POST", action="DO-NOT-POST", lan_mask_1="255")
    command = build_lan_ipv4_command(
        parse_lan_snapshot(raw),
        ipv4_address="10.20.30.1",
        subnet_mask="255.255.0.0",
    )
    assert command.endpoint == LAN_ENDPOINT == "data/LAN.json"
    assert command.referer == LAN_REFERER == "html/content/network/lan.html"
    assert set(command.payload) == set(LAN_MUTATION_FIELDS)
    assert len(command.payload) == 11
    assert dict(command.payload) == {
        "lan_ipv4_1": "10",
        "lan_ipv4_2": "20",
        "lan_ipv4_3": "30",
        "lan_ipv4_4": "1",
        "lan_mask_2": "255",
        "lan_mask_3": "0",
        "lan_mask_4": "0",
        "lan_ip_v6_used": "1",
        "lan_ip_v6": "fd12:3456:789a::1",
        "lan_ip_v6_pext": "1",
        "lan_ip_v6_arec": "0",
    }
    assert command.expected.dhcp_from == 100
    assert command.expected.dhcp_to == 200
    assert raw["lan_ipv4_1"] == "192"


@pytest.mark.parametrize(
    "missing", [*LAN_MUTATION_FIELDS, "lan_dhcp_from", "lan_dhcp_to"]
)
def test_missing_preflight_field_is_not_defaulted(missing: str) -> None:
    """Every preserved or validated field must be available before construction."""
    raw = _raw()
    del raw[missing]
    with pytest.raises(LanManagementValidationError, match="incomplete"):
        parse_lan_snapshot(raw)


@pytest.mark.parametrize(
    "value", [True, False, None, 1.0, "01", " 1", "+1", "\u0661", "-1", "256", {}]
)
def test_reject_noncanonical_octets(value: object) -> None:
    """Do not coerce booleans, non-ASCII text, floats, or malformed router data."""
    with pytest.raises(LanManagementValidationError):
        parse_lan_snapshot(_raw(lan_ipv4_4=value))


@pytest.mark.parametrize(
    "field", ["lan_ip_v6_used", "lan_ip_v6_pext", "lan_ip_v6_arec"]
)
@pytest.mark.parametrize("value", [True, None, 2, "2", "true", "", "01"])
def test_reject_unknown_preserved_flags(field: str, value: object) -> None:
    """Undocumented flags may only preserve explicit binary values."""
    with pytest.raises(LanManagementValidationError):
        parse_lan_snapshot(_raw(**{field: value}))


@pytest.mark.parametrize("value", [None, 1, "\n", "\x7f", "é", "x" * 129])
def test_reject_unsafe_preserved_ipv6(value: object) -> None:
    """Missing, oversized, or control-bearing IPv6 state cannot be preserved."""
    with pytest.raises(LanManagementValidationError):
        parse_lan_snapshot(_raw(lan_ip_v6=value))


def test_preserve_disabled_empty_ipv6_without_inventing_value() -> None:
    """An explicitly empty disabled IPv6 field is not replaced by a default."""
    state = parse_lan_snapshot(_raw(lan_ip_v6_used=0, lan_ip_v6=""))
    command = build_lan_ipv4_command(
        state, ipv4_address="192.168.3.1", subnet_mask="255.255.255.0"
    )
    assert command.payload["lan_ip_v6"] == ""
    assert command.payload["lan_ip_v6_used"] == "0"


@pytest.mark.parametrize(
    ("address", "mask"),
    [
        ("192.168.3.0", "255.255.255.0"),
        ("192.168.3.255", "255.255.255.0"),
        ("192.168.3.1", "255.255.255.254"),
        ("192.168.3.1", "255.255.255.255"),
        ("192.168.3.1", "255.255.0.255"),
        ("192.168.3.1", "0.0.0.255"),
        ("192.168.3.1", "24"),
        ("192.168.3.1", "255.0.0.0"),
        ("172.16.3.1", "255.0.0.0"),
        ("172.32.3.1", "255.255.255.0"),
        ("8.8.8.8", "255.255.255.0"),
        ("127.0.0.1", "255.255.255.0"),
        ("169.254.3.1", "255.255.255.0"),
        ("fd12::1", "255.255.255.0"),
        ("192.168.003.1", "255.255.255.0"),
        ("192.168.3.1/path", "255.255.255.0"),
    ],
)
def test_reject_invalid_or_unsafe_subnet(address: str, mask: str) -> None:
    """Private hosts and contiguous entirely private subnets are mandatory."""
    with pytest.raises(LanManagementValidationError):
        build_lan_ipv4_command(
            parse_lan_snapshot(_raw()), ipv4_address=address, subnet_mask=mask
        )


@pytest.mark.parametrize(
    ("address", "mask"),
    [
        ("10.20.30.1", "255.0.0.0"),
        ("172.16.3.1", "255.240.0.0"),
        ("172.31.3.1", "255.255.255.0"),
        ("192.168.3.1", "255.255.0.0"),
    ],
)
def test_accept_private_address_families(address: str, mask: str) -> None:
    """All three firmware private IPv4 families have a validated path."""
    assert (
        build_lan_ipv4_command(
            parse_lan_snapshot(_raw()), ipv4_address=address, subnet_mask=mask
        ).expected.ipv4_address
        == address
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"lan_dhcp_from": "200", "lan_dhcp_to": "100"},
        {"lan_dhcp_from": "0"},
        {"lan_dhcp_to": "255"},
        {"lan_dhcp_from": "1"},
        {"lan_dhcp_from": None},
    ],
)
def test_reject_invalid_current_pool(overrides: dict[str, object]) -> None:
    """Even the preflight must have a safe, ordered pool excluding the router."""
    with pytest.raises(LanManagementValidationError):
        parse_lan_snapshot(_raw(**overrides))


@pytest.mark.parametrize(
    ("address", "mask"),
    [
        ("192.168.3.150", "255.255.255.0"),
        ("192.168.3.1", "255.255.255.128"),
        ("192.168.3.254", "255.255.255.128"),
    ],
)
def test_reject_change_conflicting_with_preserved_pool(address: str, mask: str) -> None:
    """Rebase unchanged suffixes onto the new prefix before checking the pool."""
    with pytest.raises(LanManagementValidationError):
        build_lan_ipv4_command(
            parse_lan_snapshot(_raw()), ipv4_address=address, subnet_mask=mask
        )


def test_wider_subnet_may_use_last_octet_zero_and_255() -> None:
    """A suffix is not itself a network or broadcast address outside a /24."""
    state = parse_lan_snapshot(
        _raw(lan_mask_3="0", lan_dhcp_from="100", lan_dhcp_to="255")
    )
    assert state.dhcp_to == 255


def test_noop_rejected() -> None:
    """Do not initiate a disruptive operation with no requested difference."""
    with pytest.raises(LanManagementValidationError, match="would not change"):
        build_lan_ipv4_command(
            parse_lan_snapshot(_raw()),
            ipv4_address="192.168.2.1",
            subnet_mask="255.255.255.0",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"ipv6_enabled": 0},
        {"ipv6_address": "fd12::2"},
        {"ipv6_pext": 0},
        {"ipv6_arec": 1},
        {"dhcp_from": 101},
        {"dhcp_to": 201},
    ],
)
def test_command_cannot_change_preserved_fields(overrides: dict[str, Any]) -> None:
    """Direct construction cannot bypass the IPv4-only builder boundary."""
    command = _command()
    with pytest.raises(LanManagementValidationError, match="preserved"):
        LanIPv4Command(command.before, replace(command.expected, **overrides))


def test_readback_compares_all_fields_and_rejects_stale_state() -> None:
    """Fresh matching state is necessary; stale or missing state cannot succeed."""
    command = _command()
    fresh = parse_lan_snapshot(
        {**command.payload, "lan_dhcp_from": 100, "lan_dhcp_to": 200}
    )
    assert lan_readback_matches(command, fresh)
    assert not lan_readback_matches(command, command.before)
    assert not lan_readback_matches(command, None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides",
    [
        {"ipv4_address": "192.168.3.2"},
        {"subnet_mask": "255.255.0.0"},
        {"ipv6_enabled": 0},
        {"ipv6_address": "fd12::2"},
        {"ipv6_pext": 0},
        {"ipv6_arec": 1},
        {"dhcp_from": 101},
        {"dhcp_to": 201},
    ],
)
def test_readback_mismatch_is_not_success(overrides: dict[str, Any]) -> None:
    """Changes to requested or untouched state prevent a success verdict."""
    command = _command()
    assert not lan_readback_matches(command, replace(command.expected, **overrides))


def test_values_are_immutable_and_not_in_repr() -> None:
    """Private network state cannot mutate or leak through routine repr output."""
    command = _command()
    with pytest.raises(FrozenInstanceError):
        command.expected.ipv4_address = "192.168.99.1"  # type: ignore[misc]
    with pytest.raises(TypeError):
        command.payload["lan_ipv4_3"] = "99"  # type: ignore[index]
    assert "192.168" not in repr(command)
    assert "fd12" not in repr(command.expected)


def test_error_does_not_echo_invalid_private_input() -> None:
    """Validation errors remain safe for logs and administrator responses."""
    with pytest.raises(LanManagementValidationError) as raised:
        build_lan_ipv4_command(
            parse_lan_snapshot(_raw()),
            ipv4_address="PRIVATE-INVALID-HOST",
            subnet_mask="255.255.255.0",
        )
    assert "PRIVATE-INVALID-HOST" not in str(raised.value)
