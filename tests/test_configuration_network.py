"""Offline network form checks; no router requests or writes."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_network import NETWORK_SETTINGS

_CONTRACTS = {contract.id: contract for contract in NETWORK_SETTINGS}


def _dhcp() -> dict[str, object]:
    """Synthetic complete DHCP state."""
    return {
        "lan_use_dhcp": "1",
        "lan_dhcp_from": "100",
        "lan_dhcp_to": "200",
        "lan_dhcp_validtime": "4",
        "lan_ipv4_1": "192",
        "lan_ipv4_2": "168",
        "lan_ipv4_3": "2",
        "lan_ipv4_4": "1",
        "lan_mask_2": "255",
        "lan_mask_3": "255",
        "lan_mask_4": "0",
    }


def _radio() -> dict[str, object]:
    """Synthetic complete radio state."""
    return {
        "wlan_band": "0",
        "wlan_power": "0",
        "wlan_mode": "3",
        "wlan_speed": "1",
        "wlan_channel": "6",
        "wlan_channel_dir": "0",
        "wlan_5ghz_mode": "2",
        "wlan_5ghz_speed": "2",
        "wlan_5ghz_channel": "36",
    }


def _identity() -> dict[str, object]:
    """Synthetic private names and key, never sourced from a router."""
    return {
        "wlan_ssid": "Synthetic",
        "wlan_visible": "1",
        "wlan_5ghz_ssid": "Synthetic5",
        "wlan_5ghz_visible": "1",
        "wlan_enc": "4",
        "wlan_pmf": "1",
        "wlan_wpa_key": "Synthetic-Test-Key",
        "wlan_display_key": "1",
        "wlan_guest_ssid": "Guest",
        "wlan_office_ssid": "Office",
    }


def _ddns() -> dict[str, object]:
    """Synthetic DDNS state with a deliberately private embedded token."""
    return {
        "use_dyndns": "1",
        "dyndns_provider": "4",
        "dyndns_domain": "unit.example",
        "dyndns_user": "unit-user",
        "dyndns_password": "Synthetic-Password",
        "dyndns_updsrv": "update.example",
        "dyndns_updprot": "1",
        "dyndns_updport": "443",
        "dyndns_updurl": "/update?token=SYNTHETIC-TOKEN",
    }


def _schedule() -> dict[str, object]:
    """Synthetic schedule with hidden flags distinct from real clock fields."""
    result: dict[str, object] = {
        "wlan_timerule": "2",
        "wlan_dfrom": "08:00",
        "wlan_dto": "22:00",
        "wlan_fdis": "0",
    }
    for day in ("mo", "di", "mi", "do", "fr", "sa", "so"):
        result[f"wlan_time_{day}_from"] = "08:00"
        result[f"wlan_time_{day}_to"] = "22:00"
        result[f"wlan_time_{day}_use"] = "1"
    return result


def test_schedule_payload_matches_active_branch() -> None:
    """Hidden inactive fields and weekday-use checkboxes are never submitted."""
    contract = _CONTRACTS["wifi_schedule"]
    assert contract.build(_schedule(), {"wlan_timerule": "0"}) == {"wlan_timerule": "0"}
    daily = contract.build(_schedule(), {"wlan_timerule": "1"})
    assert set(daily) == {"wlan_timerule", "wlan_dfrom", "wlan_dto", "wlan_fdis"}
    weekly = contract.build(_schedule(), {"wlan_fdis": True})
    assert len(weekly) == 16
    assert not any(key.endswith("_use") for key in weekly)
    assert weekly["wlan_fdis"] == "1"


def test_schedule_accepts_end_of_day_and_nonoverlapping_overnight() -> None:
    """24:00 is an end notation; an overnight interval can stop before next start."""
    contract = _CONTRACTS["wifi_schedule"]
    assert (
        contract.build(_schedule(), {"wlan_time_mo_to": "24:00"})["wlan_time_mo_to"]
        == "24:00"
    )
    assert (
        contract.build(
            _schedule(), {"wlan_time_mo_from": "22:00", "wlan_time_mo_to": "07:00"}
        )["wlan_time_mo_to"]
        == "07:00"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"wlan_time_mo_from": "24:00"},
        {"wlan_time_mo_to": "24:01"},
        {"wlan_time_mo_from": "8:00"},
        {"wlan_time_mo_from": "08:60"},
        {"wlan_time_mo_from": "22:00", "wlan_time_mo_to": "09:00"},
        {"wlan_time_so_from": "22:00", "wlan_time_so_to": "09:00"},
        {"wlan_timerule": "0", "wlan_dfrom": "10:00"},
        {"wlan_timerule": "1", "wlan_time_mo_to": "10:00"},
        {"wlan_time_mo_use": False},
        {"wlan_timerule": "3"},
    ],
)
def test_schedule_rejects_invalid_or_overlapping_times(
    changes: dict[str, object],
) -> None:
    """Strict time grammar, closed branches and Sunday wraparound are checked."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["wifi_schedule"].build(_schedule(), changes)


def test_ddns_preserves_private_path_on_unrelated_edit() -> None:
    """The hidden update path must not be dropped when editing another field."""
    payload = _CONTRACTS["dynamic_dns"].build(
        _ddns(), {"dyndns_domain": "other.example"}
    )
    assert payload["dyndns_updurl"] == "/update?token=SYNTHETIC-TOKEN"
    assert payload["dyndns_updsrv"] == "update.example"
    assert payload["dyndns_password"] == _ddns()["dyndns_password"]
    assert "dyndns_update_path" not in payload


def test_ddns_read_never_exposes_password_or_update_path() -> None:
    """Custom URL query credentials and ordinary passwords stay out of UI reads."""
    result = _CONTRACTS["dynamic_dns"].read(_ddns())
    assert "dyndns_password" not in result
    assert "dyndns_update_path" not in result
    assert "SYNTHETIC-TOKEN" not in str(result)


def test_ddns_unconfigured_off_state_is_readable_not_postable() -> None:
    """Absent inactive values are UI sentinels, never implicit write defaults."""
    contract = _CONTRACTS["dynamic_dns"]
    raw = {"use_dyndns": "0", "dyndns_provider": "unknown-provider"}
    current = contract.read(raw)
    assert current["dyndns_provider"] == ""
    assert current["dyndns_updport"] == 0
    assert current["dyndns_updprot"] == ""
    assert "dyndns_password" not in current
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"use_dyndns": True})
    payload = contract.build(
        raw,
        {
            "use_dyndns": True,
            "dyndns_provider": "0",
            "dyndns_updprot": "1",
            "dyndns_domain": "unit.example",
            "dyndns_user": "unit",
            "dyndns_password": "Synthetic-new-password",
        },
    )
    assert payload["use_dyndns"] == "1"
    assert payload["dyndns_provider"] == "0"
    assert set(payload) == {
        "use_dyndns",
        "dyndns_provider",
        "dyndns_updprot",
        "dyndns_domain",
        "dyndns_user",
        "dyndns_password",
    }


def test_ddns_active_unknown_provider_is_not_normalized() -> None:
    """Unknown enabled configurations remain evidence-gated."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["dynamic_dns"].read({**_ddns(), "dyndns_provider": "unknown"})


def test_ddns_standard_reader_does_not_require_inactive_custom_values() -> None:
    """A missing private update path is fine for a standard provider read."""
    result = _CONTRACTS["dynamic_dns"].read(
        {
            **_ddns(),
            "dyndns_provider": "0",
            "dyndns_updport": "",
            "dyndns_updsrv": None,
            "dyndns_updurl": None,
        }
    )
    assert result["dyndns_updport"] == 0
    assert result["dyndns_updsrv"] == ""


def test_ddns_standard_provider_omits_hidden_custom_text() -> None:
    """Hidden protocol select remains; hidden host, port and path are not sent."""
    payload = _CONTRACTS["dynamic_dns"].build(
        {**_ddns(), "dyndns_provider": "0"}, {"dyndns_domain": "other.example"}
    )
    assert set(payload) == {
        "use_dyndns",
        "dyndns_provider",
        "dyndns_updprot",
        "dyndns_domain",
        "dyndns_user",
        "dyndns_password",
    }


def test_ddns_disabled_custom_branch_preserves_preaction_location() -> None:
    """Native custom preaction supplies host/path even when text fields hide."""
    payload = _CONTRACTS["dynamic_dns"].build(_ddns(), {"use_dyndns": False})
    assert set(payload) == {
        "use_dyndns",
        "dyndns_provider",
        "dyndns_updprot",
        "dyndns_updsrv",
        "dyndns_updurl",
    }
    assert "dyndns_password" not in payload


def test_ddns_protocol_change_sets_native_default_port() -> None:
    """Native transport selection resets the port unless explicitly supplied."""
    assert (
        _CONTRACTS["dynamic_dns"].build(_ddns(), {"dyndns_updprot": "0"})[
            "dyndns_updport"
        ]
        == 80
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"dyndns_provider": "5"},
        {"dyndns_domain": "bad/name"},
        {"dyndns_provider": "0"},
        {"dyndns_updsrv": "other.example"},
        {"dyndns_update_path": "https://other.example/path"},
        {"dyndns_update_path": "//other.example/path"},
        {"dyndns_update_path": "/path#fragment"},
        {"dyndns_update_path": "********"},
        {"dyndns_update_path": "/********"},
        {"dyndns_updport": 0},
        {"dyndns_password": "********"},
        {"use_dyndns": False, "dyndns_domain": "other.example"},
    ],
)
def test_ddns_rejects_unsafe_or_ambiguous_changes(changes: dict[str, object]) -> None:
    """Reject invalid enums, implicit credential transfers and unknown paths."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["dynamic_dns"].build(_ddns(), changes)


def test_ddns_new_server_requires_explicit_private_replacements() -> None:
    """Credential transfer to a different update host requires explicit inputs."""
    payload = _CONTRACTS["dynamic_dns"].build(
        _ddns(),
        {
            "dyndns_updsrv": "other.example",
            "dyndns_update_path": "/new?token=NEW",
            "dyndns_password": "New-Synthetic-Password",
        },
    )
    assert payload["dyndns_updsrv"] == "other.example"
    assert payload["dyndns_updurl"] == "/new?token=NEW"


@pytest.mark.parametrize("path", [None, "/********", "//other.example/path"])
def test_ddns_does_not_default_missing_or_masked_path(path: object) -> None:
    """Current hidden path must be explicit and safe before preservation."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["dynamic_dns"].build(
            {**_ddns(), "dyndns_updurl": path}, {"dyndns_domain": "other.example"}
        )


def test_lan_adapter_uses_exact_standalone_contract() -> None:
    """The shared settings editor cannot add arbitrary fields to a LAN write."""
    raw = {
        **_dhcp(),
        "lan_ip_v6_used": "0",
        "lan_ip_v6": "",
        "lan_ip_v6_pext": "0",
        "lan_ip_v6_arec": "1",
    }
    contract = _CONTRACTS["lan_ipv4"]
    assert contract.readback_policy == "reconnect_required"
    assert contract.read(raw) == {
        "ipv4_address": "192.168.2.1",
        "subnet_mask": "255.255.255.0",
    }
    payload = contract.build(raw, {"ipv4_address": "192.168.3.1"})
    assert len(payload) == 11
    assert payload["lan_ipv4_3"] == "3"
    assert payload["lan_ip_v6_arec"] == "1"


def test_revision_dependencies_include_hidden_preserved_context() -> None:
    """Consent must become stale after subnet, sibling SSID or path changes."""
    assert "lan_ipv4_1" in _CONTRACTS["dhcp"].revision_fields
    assert "lan_mask_4" in _CONTRACTS["dhcp"].revision_fields
    assert "wlan_guest_ssid" in _CONTRACTS["wifi_identity"].revision_fields
    assert "dyndns_updurl" in _CONTRACTS["dynamic_dns"].revision_fields
    assert "lan_ip_v6_arec" in _CONTRACTS["lan_ipv4"].revision_fields


def test_dhcp_exact_four_field_payload() -> None:
    """Changing one enabled DHCP field preserves the other three only."""
    assert _CONTRACTS["dhcp"].build(_dhcp(), {"lan_dhcp_from": 101}) == {
        "lan_use_dhcp": "1",
        "lan_dhcp_from": 101,
        "lan_dhcp_to": 200,
        "lan_dhcp_validtime": "4",
    }


def test_dhcp_disabled_branch_omits_text_pool_but_keeps_select() -> None:
    """Match the template engine's hidden text versus retained select behavior."""
    assert _CONTRACTS["dhcp"].build(_dhcp(), {"lan_use_dhcp": False}) == {
        "lan_use_dhcp": "0",
        "lan_dhcp_validtime": "4",
    }
    with pytest.raises(ConfigurationError, match="inactive_settings_field"):
        _CONTRACTS["dhcp"].build(_dhcp(), {"lan_use_dhcp": False, "lan_dhcp_from": 101})


@pytest.mark.parametrize(
    "changes",
    [
        {"lan_dhcp_from": 0},
        {"lan_dhcp_from": 1},
        {"lan_dhcp_from": 201},
        {"lan_dhcp_to": 255},
        {"lan_dhcp_to": 99},
        {"lan_dhcp_validtime": "10"},
        {"lan_dhcp_from": True},
        {"lan_use_dhcp": 1},
        {"endpoint": "data/Other.json"},
    ],
)
def test_dhcp_rejects_invalid_inputs(changes: dict[str, object]) -> None:
    """Pool safety, exact primitive types and closed field names are enforced."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["dhcp"].build(_dhcp(), changes)


def test_dhcp_rejects_pool_outside_subnet() -> None:
    """A valid suffix still cannot leave a narrower current subnet."""
    with pytest.raises(ConfigurationError, match="invalid_dhcp_range"):
        _CONTRACTS["dhcp"].build(
            {**_dhcp(), "lan_mask_4": "128"}, {"lan_dhcp_from": 101}
        )


def test_radio_preserves_all_nine_fields() -> None:
    """Select fields remain present regardless of their visible band branch."""
    assert _CONTRACTS["wifi_radio"].build(_radio(), {"wlan_power": "1"}) == {
        **_radio(),
        "wlan_power": "1",
    }


@pytest.mark.parametrize(
    ("channel", "direction"),
    [("0", "2"), ("1", "0"), ("4", "0"), ("10", "1"), ("13", "1")],
)
def test_radio_derives_forced_direction(channel: str, direction: str) -> None:
    """The native UI computes a fixed direction at channel boundaries."""
    payload = _CONTRACTS["wifi_radio"].build(_radio(), {"wlan_channel": channel})
    assert payload["wlan_channel_dir"] == direction


@pytest.mark.parametrize(
    "changes",
    [
        {"wlan_channel": "14"},
        {"wlan_channel": 6},
        {"wlan_mode": "1"},
        {"wlan_channel": "1", "wlan_channel_dir": "1"},
        {"wlan_5ghz_speed": "2", "wlan_5ghz_channel": "40"},
        {"wlan_5ghz_speed": "3", "wlan_5ghz_channel": "52"},
        {"wlan_5ghz_mode": "0", "wlan_5ghz_speed": "3"},
        {"wlan_5ghz_channel": "128"},
    ],
)
def test_radio_rejects_unreviewed_or_incompatible_enums(
    changes: dict[str, object],
) -> None:
    """Closed enums and width-dependent channel bundles are enforced."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["wifi_radio"].build(_radio(), changes)


def test_radio_clamps_width_and_resets_unavailable_channel_like_ui() -> None:
    """Mode/width changes cannot retain an invalid channel bundle."""
    payload = _CONTRACTS["wifi_radio"].build(_radio(), {"wlan_5ghz_mode": "0"})
    assert payload["wlan_5ghz_speed"] == "1"
    payload = _CONTRACTS["wifi_radio"].build(
        {**_radio(), "wlan_5ghz_channel": "100"}, {"wlan_5ghz_speed": "3"}
    )
    assert payload["wlan_5ghz_channel"] == "0"


def test_identity_read_does_not_expose_key() -> None:
    """Private key never appears in typed values or metadata."""
    contract = _CONTRACTS["wifi_identity"]
    assert "wlan_wpa_key" not in contract.read(_identity())
    assert "Synthetic-Test-Key" not in str(contract.metadata())


def test_identity_preserves_key_and_clears_display_when_name_changes() -> None:
    """A name edit resends only a valid unmasked key and clears key display."""
    payload = _CONTRACTS["wifi_identity"].build(_identity(), {"wlan_ssid": "New"})
    assert len(payload) == 8
    assert payload["wlan_wpa_key"] == "Synthetic-Test-Key"
    assert payload["wlan_display_key"] == "0"
    assert "br_active" not in payload


def test_identity_wpa3_omits_hidden_pmf() -> None:
    """PMF is a separately editable checkbox only for WPA2."""
    assert "wlan_pmf" not in _CONTRACTS["wifi_identity"].build(
        _identity(), {"wlan_enc": "6"}
    )


def test_identity_open_branch_never_replays_key() -> None:
    """Open mode omits password, display and PMF even if a prior key is masked."""
    payload = _CONTRACTS["wifi_identity"].build(
        {**_identity(), "wlan_wpa_key": "********"}, {"wlan_enc": "0"}
    )
    assert set(payload) == {
        "wlan_ssid",
        "wlan_visible",
        "wlan_5ghz_ssid",
        "wlan_5ghz_visible",
        "wlan_enc",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"wlan_ssid": "Guest"},
        {"wlan_ssid": "office"},
        {"wlan_ssid": "Telekom"},
        {"wlan_ssid": ""},
        {"wlan_ssid": "x" * 33},
        {"wlan_ssid": "é"},
        {"wlan_wpa_key": "********"},
        {"wlan_wpa_key": "short"},
        {"wlan_wpa_key": "x" * 64},
        {"wlan_wpa_key": "unicode-é-key"},
        {"wlan_enc": "0", "wlan_wpa_key": "Replacement-Key"},
        {"wlan_enc": "6", "wlan_pmf": False},
        {"br_active": False},
    ],
)
def test_identity_rejects_invalid_names_secrets_or_inactive_inputs(
    changes: dict[str, object],
) -> None:
    """Names, secret replacement and active branch rules fail closed."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["wifi_identity"].build(_identity(), changes)


def test_identity_masked_key_requires_explicit_replacement() -> None:
    """A display mask must never become the actual new Wi-Fi credential."""
    raw = {**_identity(), "wlan_wpa_key": "********"}
    with pytest.raises(ConfigurationError):
        _CONTRACTS["wifi_identity"].build(raw, {"wlan_ssid": "New"})
    assert (
        _CONTRACTS["wifi_identity"].build(raw, {"wlan_wpa_key": "Replacement-Key"})[
            "wlan_wpa_key"
        ]
        == "Replacement-Key"
    )


@pytest.mark.parametrize(
    ("contract_id", "factory", "changed"),
    [
        ("dhcp", _dhcp, {"lan_dhcp_from": 101}),
        ("wifi_radio", _radio, {"wlan_power": "1"}),
        ("wifi_identity", _identity, {"wlan_visible": False}),
    ],
)
def test_unrelated_preflight_fields_never_enter_payload(
    contract_id: str, factory: object, changed: dict[str, object]
) -> None:
    """No pass-through of arbitrary router data to fixed configuration forms."""
    raw = factory()  # type: ignore[operator]
    raw["unrelated_private_field"] = "DO-NOT-POST"
    assert "unrelated_private_field" not in _CONTRACTS[contract_id].build(raw, changed)
