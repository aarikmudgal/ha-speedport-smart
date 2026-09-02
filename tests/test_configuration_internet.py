"""Synthetic offline Internet form tests; no router requests or live writes."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_internet import INTERNET_SETTINGS

_CONTRACT = INTERNET_SETTINGS[0]


def _raw() -> dict[str, object]:
    """Complete synthetic state with distinguishable branch credentials."""
    return {
        "isp_selection": "1",
        "provis_inet": "043",
        "other_name": "Synthetic ISP",
        "other_user": "synthetic-user",
        "other_password": "Synthetic-PPPoE-Password",
        "other_MTU": "1492",
        "other_vlan": "1",
        "other_vlanid": "7",
        "other_ip": "1",
        "other_ip_hb": "198",
        "other_ip_mhb": "51",
        "other_ip_mlb": "100",
        "other_ip_lb": "23",
        "other_dns": "1",
        "other_dns_hb": "192",
        "other_dns_mhb": "0",
        "other_dns_mlb": "2",
        "other_dns_lb": "53",
        "other_sdns_hb": "",
        "other_sdns_mhb": "",
        "other_sdns_mlb": "",
        "other_sdns_lb": "",
        "other_dns6": "1",
        "other_dns6_prim": "2001:db8::53",
        "other_dns6_sek": "",
        "zustart_user": "1234567890",
        "zustart_password": "Synthetic-Zuhause-Password",
        "t_number": "123456789012",
        "t_mbnr0": "0",
        "t_mbnr1": "0",
        "t_mbnr2": "0",
        "t_mbnr3": "1",
        "t_password": "12345678",
        "t_callident": "123456789012",
        "unrelated_private": "NEVER-POST",
    }


def test_other_provider_full_payload_preserves_untouched_values() -> None:
    """The exact 24-field active form excludes unrelated/provider hidden values."""
    raw = _raw()
    payload = _CONTRACT.build(raw, {"other_MTU": 1480})
    assert len(payload) == 24
    assert payload["other_MTU"] == 1480
    assert payload["other_password"] == raw["other_password"]
    assert payload["other_vlanid"] == 7
    assert payload["other_dns6_prim"] == "2001:db8::53"
    assert "fixed_ipv4_address" not in payload
    assert "t_password" not in payload
    assert "zustart_password" not in payload
    assert "unrelated_private" not in payload
    assert _CONTRACT.endpoint == "data/INetIP.json"
    assert _CONTRACT.referer == "html/content/internet/connection.html"
    assert _CONTRACT.readback_policy == "reconnect_required"


def test_other_provider_disabled_advanced_branches_have_exact_nine_fields() -> None:
    """Hidden checkbox-attached text fields do not become empty overwrites."""
    payload = _CONTRACT.build(
        _raw(),
        {
            "other_vlan": False,
            "other_ip": False,
            "other_dns": False,
            "other_dns6": False,
        },
    )
    assert set(payload) == {
        "isp_selection",
        "other_name",
        "other_user",
        "other_password",
        "other_MTU",
        "other_vlan",
        "other_ip",
        "other_dns",
        "other_dns6",
    }
    assert payload["other_vlan"] == "0"
    assert payload["other_dns"] == "0"


def test_automatic_provider_requires_prerequisite_and_never_includes_secrets() -> None:
    """The automatic branch contains only provider and global DNS toggles."""
    raw = {**_raw(), "other_dns": "0", "other_dns6": "0"}
    assert _CONTRACT.build(raw, {"isp_selection": "99"}) == {
        "isp_selection": "99",
        "other_dns": "0",
        "other_dns6": "0",
    }
    for provision in (None, "", "003", 43, ["043"]):
        with pytest.raises(ConfigurationError, match="automatic_provider_unavailable"):
            _CONTRACT.build({**raw, "provis_inet": provision}, {"isp_selection": "99"})


def test_zuhause_start_preserves_its_credentials_only() -> None:
    """A DNS toggle on the active two-field provider cannot copy Other secrets."""
    raw = {**_raw(), "isp_selection": "89", "other_dns": "0", "other_dns6": "0"}
    payload = _CONTRACT.build(raw, {"other_dns6": False})
    assert set(payload) == {
        "isp_selection",
        "zustart_user",
        "zustart_password",
        "other_dns",
        "other_dns6",
    }
    assert payload["zustart_password"] == raw["zustart_password"]


@pytest.mark.parametrize(
    "changes",
    [
        {"zustart_user": ""},
        {"zustart_user": "not-numeric"},
        {"zustart_user": "1" * 57},
        {"zustart_password": ""},
        {"zustart_password": "x" * 33},
        {"zustart_password": "********"},
    ],
)
def test_zuhause_start_exact_numeric_identity_and_password_bounds(
    changes: dict[str, object],
) -> None:
    """The v6 Pattern.Numeric and 1-56/1-32 bounds are enforced."""
    with pytest.raises(ConfigurationError):
        _CONTRACT.build({**_raw(), "isp_selection": "89"}, changes)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("other_MTU", (1440, 1492)),
        ("other_vlanid", (1, 4094)),
    ],
)
def test_link_setting_exact_boundary_values(
    field: str, values: tuple[int, int]
) -> None:
    """Both documented native numeric boundaries are accepted."""
    for value in values:
        assert _CONTRACT.build(_raw(), {field: value})[field] == value


def test_provider_switch_requires_explicit_complete_credentials() -> None:
    """Stored inactive credentials must not silently become newly active."""
    with pytest.raises(ConfigurationError, match="new_provider_requires_credentials"):
        _CONTRACT.build(_raw(), {"isp_selection": "89"})
    payload = _CONTRACT.build(
        _raw(),
        {
            "isp_selection": "89",
            "zustart_user": "9876543210",
            "zustart_password": "New-Synthetic-Password",
        },
    )
    assert payload["zustart_user"] == "9876543210"
    assert payload["zustart_password"] == "New-Synthetic-Password"  # noqa: S105


def test_switch_to_other_requires_explicit_link_prerequisites() -> None:
    """Old hidden flags and MTU are never silently reused across providers."""
    raw = {**_raw(), "isp_selection": "99"}
    with pytest.raises(ConfigurationError, match="new_provider_requires_credentials"):
        _CONTRACT.build(raw, {"isp_selection": "1", "other_password": "New-key"})
    payload = _CONTRACT.build(
        raw,
        {
            "isp_selection": "1",
            "other_name": "New ISP",
            "other_user": "new-user",
            "other_password": "New-Synthetic-Password",
            "other_MTU": 1492,
            "other_vlan": False,
            "other_ip": False,
        },
    )
    assert "other_vlanid" not in payload
    assert "other_ip_hb" not in payload


def test_manual_telekom_preserves_exact_seven_current_fields() -> None:
    """Existing manual credentials are preserved without copying other branches."""
    raw = {**_raw(), "isp_selection": "0", "other_dns": "0", "other_dns6": "0"}
    payload = _CONTRACT.build(raw, {"other_dns": False})
    assert len(payload) == 10
    for name in (
        "t_number",
        "t_mbnr0",
        "t_mbnr1",
        "t_mbnr2",
        "t_mbnr3",
        "t_password",
        "t_callident",
    ):
        assert payload[name] == raw[name]
    with pytest.raises(ConfigurationError, match="new_provider_requires_credentials"):
        _CONTRACT.build(_raw(), {"isp_selection": "0"})
    with pytest.raises(ConfigurationError):
        _CONTRACT.build(raw, {"t_number": "OTHER"})


def test_manual_telekom_switch_requires_all_seven_explicit_credentials() -> None:
    """Switching to manual setup requires the complete exact captured form."""
    changes = {name: value for name, value in _raw().items() if name.startswith("t_")}
    changes["isp_selection"] = "0"
    payload = _CONTRACT.build(_raw(), changes)
    assert all(payload[name] == value for name, value in changes.items())
    assert "other_password" not in payload
    assert "zustart_password" not in payload


@pytest.mark.parametrize(
    "changes",
    [
        {"t_number": ""},
        {"t_number": "x"},
        {"t_number": "1" * 13},
        {"t_callident": ""},
        {"t_callident": "1" * 13},
        {"t_callident": "abc"},
        {"t_mbnr0": ""},
        {"t_mbnr1": "12"},
        {"t_mbnr2": "x"},
        {"t_password": "x" * 9},
        {"t_password": ""},
        {"t_number": "456"},
    ],
)
def test_manual_telekom_captured_lengths_and_explicit_password(
    changes: dict[str, object],
) -> None:
    """Reject invalid lengths and silent account swaps; preserve leading zeros."""
    with pytest.raises(ConfigurationError):
        _CONTRACT.build({**_raw(), "isp_selection": "0"}, changes)


def test_manual_telekom_identity_can_change_with_explicit_password() -> None:
    """Typed manual administration works with an explicitly supplied credential."""
    payload = _CONTRACT.build(
        {**_raw(), "isp_selection": "0"},
        {
            "t_number": "00001234",
            "t_password": "87654321",
        },
    )
    assert payload["t_number"] == "00001234"
    assert payload["t_password"] == "87654321"  # noqa: S105 - synthetic fixture.


def test_other_provider_optional_identity_fields_match_native_minimum_zero() -> None:
    """Native empty label/user is permitted with an explicitly supplied password."""
    payload = _CONTRACT.build(
        _raw(),
        {"other_name": "", "other_user": "", "other_password": "Synthetic-Password"},
    )
    assert payload["other_name"] == ""
    assert payload["other_user"] == ""


@pytest.mark.parametrize("value", [None, "", "********", "[REDACTED]", "bad\nsecret"])
def test_manual_preservation_never_replays_missing_or_masked_password(
    value: object,
) -> None:
    """Fresh credential values are required even when the field is not edited."""
    with pytest.raises(ConfigurationError):
        _CONTRACT.build(
            {**_raw(), "isp_selection": "0", "t_password": value}, {"other_dns": False}
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"other_MTU": 1439},
        {"other_MTU": 1493},
        {"other_MTU": True},
        {"other_MTU": "1492"},
        {"other_vlanid": 0},
        {"other_vlanid": 4095},
        {"other_vlanid": "7"},
        {"other_vlan": 1},
        {"other_user": ""},
        {"other_user": "different-user"},
        {"other_password": "********"},
        {"other_password": "[REDACTED]"},
        {"other_password": "x" * 256},
        {"other_name": "x" * 256},
        {"isp_selection": "2"},
        {"isp_selection": 1},
        {"endpoint": "data/Connect.json"},
        {"req_connect": "online"},
        {"other_dns": False, "dns_ipv4_primary": "192.0.2.1"},
        {"other_vlan": False, "other_vlanid": 7},
        {"other_ip": False, "fixed_ipv4_address": "198.51.100.12"},
        {"other_dns6": False, "other_dns6_prim": "2001:db8::1"},
        {"zustart_user": "hidden-other-provider"},
    ],
)
def test_invalid_or_inactive_changes_are_rejected(changes: dict[str, object]) -> None:
    """Closed names, primitive types, exact bounds and branch ownership fail closed."""
    with pytest.raises(ConfigurationError):
        _CONTRACT.build(_raw(), changes)


@pytest.mark.parametrize(
    "address",
    [
        "",
        "192.0.2.01",
        "256.0.0.1",
        "0.0.0.0",  # noqa: S104 - invalid-address test, no socket.
        "127.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "255.255.255.255",
        "1.2.3",
        "1.2.3.4/24",
        "https://1.2.3.4",
        "2001:db8::1",
        "192.0.2.1\n",
        123,
        True,
    ],
)
def test_fixed_ipv4_and_dns_reject_nonliteral_or_nonunicast(address: object) -> None:
    """Router-bound addresses cannot be hostnames, URLs or ambiguous literals."""
    for field in ("fixed_ipv4_address", "dns_ipv4_primary"):
        with pytest.raises(ConfigurationError):
            _CONTRACT.build(_raw(), {field: address})


@pytest.mark.parametrize(
    "address",
    [
        "",
        "::",
        "::1",
        "ff02::1",
        "fe80::1",
        "fe80::1%eth0",
        "2001:db8::1/64",
        "[2001:db8::1]",
        "192.0.2.1",
        "2001:db8::gg",
        "https://[2001:db8::1]",
    ],
)
def test_ipv6_dns_requires_literal_unicast(address: str) -> None:
    """No scoped addresses, multicast or alternate URL syntaxes."""
    with pytest.raises(ConfigurationError):
        _CONTRACT.build(_raw(), {"other_dns6_prim": address})


def test_read_excludes_all_credentials_and_normalizes_addresses() -> None:
    """No current active or inactive password is exposed in public values."""
    raw = _raw()
    values = _CONTRACT.read(raw)
    assert values["fixed_ipv4_address"] == "198.51.100.23"
    assert values["dns_ipv4_secondary"] == ""
    assert values["zustart_user"] == ""
    assert not any("password" in name for name in values)
    assert "12345678" not in str(values)
    assert "Synthetic-PPPoE-Password" not in str(_CONTRACT.metadata())


def test_inactive_values_are_explicit_empty_and_never_required_for_read_or_write() -> (
    None
):
    """Automatic state needs no credentials or inactive fixed-IP/DNS values."""
    raw = {
        "isp_selection": "99",
        "provis_inet": "043",
        "other_dns": "0",
        "other_dns6": "0",
    }
    values = _CONTRACT.read(raw)
    assert values["other_MTU"] == 0
    assert values["other_vlanid"] == 0
    assert values["other_user"] == ""
    assert _CONTRACT.build(raw, {"other_dns": False}) == {
        "isp_selection": "99",
        "other_dns": "0",
        "other_dns6": "0",
    }


def test_readback_projection_matches_changed_address_and_disabled_branch() -> None:
    """The session can project exact expected typed readback from the wire payload."""
    raw = _raw()
    payload = _CONTRACT.build(
        raw, {"fixed_ipv4_address": "198.51.100.44", "other_dns6": False}
    )
    expected = _CONTRACT.read({**raw, **payload})
    assert expected["fixed_ipv4_address"] == "198.51.100.44"
    assert expected["other_dns6_prim"] == ""


@pytest.mark.parametrize(
    ("toggle", "field", "value"),
    [
        ("other_vlan", "other_vlanid", 7),
        ("other_ip", "fixed_ipv4_address", "198.51.100.10"),
        ("other_dns", "dns_ipv4_primary", "192.0.2.53"),
        ("other_dns6", "other_dns6_prim", "2001:db8::53"),
    ],
)
def test_enabling_hidden_branch_requires_explicit_visible_settings(
    toggle: str,
    field: str,
    value: object,
) -> None:
    """Hidden old values cannot silently become active from a switch-only edit."""
    raw = {**_raw(), toggle: "0"}
    with pytest.raises(ConfigurationError, match="new_branch_requires_settings"):
        _CONTRACT.build(raw, {toggle: True})
    assert _CONTRACT.build(raw, {toggle: True, field: value})[toggle] == "1"


def test_enabling_dns_does_not_restore_hidden_optional_secondary() -> None:
    """An unedited empty secondary means absent, not an undisplayed old resolver."""
    raw = {
        **_raw(),
        "other_dns": "0",
        "other_dns6": "0",
        "other_sdns_hb": "198",
        "other_sdns_mhb": "51",
        "other_sdns_mlb": "100",
        "other_sdns_lb": "53",
        "other_dns6_sek": "2001:db8::999",
    }
    payload = _CONTRACT.build(
        raw,
        {
            "other_dns": True,
            "other_dns6": True,
            "dns_ipv4_primary": "192.0.2.53",
            "other_dns6_prim": "2001:db8::53",
        },
    )
    assert payload["other_sdns_hb"] == ""
    assert payload["other_dns6_sek"] == ""


def test_missing_active_prerequisites_or_addresses_fail_closed() -> None:
    """Absent fields cannot become zeros or guessed settings."""
    for key in (
        "other_vlan",
        "other_ip",
        "other_dns",
        "other_dns6",
        "other_MTU",
        "other_dns_hb",
        "other_ip_lb",
        "other_password",
    ):
        raw = _raw()
        raw.pop(key)
        with pytest.raises(ConfigurationError):
            _CONTRACT.build(raw, {"other_name": "Renamed"})


def test_revision_binds_all_payload_dependencies_but_not_runtime_status() -> None:
    """Consent binds hidden provider secrets and link prerequisites, not uptime."""
    fields = set(_CONTRACT.revision_fields)
    assert {
        "provis_inet",
        "t_password",
        "other_password",
        "zustart_password",
        "other_ip_lb",
        "other_dns6_prim",
        "other_vlanid",
    } <= fields
    assert "onlinestatus" not in fields
    before = _CONTRACT.revision(_raw())
    assert before != _CONTRACT.revision({**_raw(), "t_password": "new-secret"})
