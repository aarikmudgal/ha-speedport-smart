"""Offline guest/prioritized Wi-Fi complete form and privacy contracts."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    settings_contracts,
)


def _raw(kind: str = "guest") -> dict:
    prefix = f"wlan_{kind}_"
    return {
        "use_wlan": "1",
        "use_wps": "1",
        "wlan_ssid": "Home",
        "wlan_5ghz_ssid": "Home 5",
        "wlan_guest_ssid": "Visitors",
        "wlan_office_ssid": "Office",
        prefix + "active": "1",
        prefix + "enc": "4",
        prefix + "pmf": "0",
        prefix + "key": "SyntheticKey123",
        prefix + "time": "120",
        prefix + "fdis": "0",
        prefix + "inet": "1",
        prefix + "wps": "0",
        prefix + "display_key": "1",
    }


@pytest.mark.parametrize("kind", ["guest", "office"])
def test_complete_encrypted_payload_and_secret_exclusion(kind: str) -> None:
    """The full visible form is preserved without exposing stored credentials."""
    contract = settings_contracts()[f"wifi_{kind}_settings"]
    raw = _raw(kind)
    prefix = f"wlan_{kind}_"
    payload = contract.build(raw, {prefix + "ssid": "Changed"})
    assert payload[prefix + "ssid"] == "Changed"
    assert payload[prefix + "key"] == "SyntheticKey123"
    assert payload[prefix + "pmf"] == "0"
    assert payload[prefix + "enc"] == "4"
    assert prefix + "key" not in contract.read(raw)
    if kind == "guest":
        assert payload[prefix + "display_key"] == "0"
        assert payload[prefix + "inet"] == "1"
    else:
        assert set(payload) == {
            prefix + name for name in ("active", "ssid", "enc", "pmf", "key")
        }


@pytest.mark.parametrize("kind", ["guest", "office"])
def test_disable_preserves_hidden_selects_not_hidden_text(kind: str) -> None:
    """Hidden selects still submit while hidden text inputs do not."""
    contract = settings_contracts()[f"wifi_{kind}_settings"]
    prefix = f"wlan_{kind}_"
    payload = contract.build(_raw(kind), {prefix + "active": False})
    expected = {prefix + "active": "0", prefix + "enc": "4"}
    if kind == "guest":
        expected[prefix + "time"] = "120"
    assert payload == expected
    with pytest.raises(ConfigurationError, match="inactive_settings_field"):
        contract.build(_raw(kind), {prefix + "active": False, prefix + "ssid": "New"})


@pytest.mark.parametrize("encryption", ["0", "5", "6"])
def test_encryption_specific_hidden_fields(encryption: str) -> None:
    """WPA-specific dependencies match the native field visibility rules."""
    contract = settings_contracts()["wifi_guest_settings"]
    payload = contract.build(_raw(), {"wlan_guest_enc": encryption})
    assert "wlan_guest_pmf" not in payload
    assert ("wlan_guest_key" in payload) is (encryption != "0")
    assert ("wlan_guest_wps" in payload) is (encryption != "6")
    with pytest.raises(ConfigurationError, match="inactive_settings_field"):
        contract.build(_raw(), {"wlan_guest_enc": encryption, "wlan_guest_pmf": True})


@pytest.mark.parametrize("kind", ["guest", "office"])
@pytest.mark.parametrize(
    "value", ["Home", "HOME 5", "", "école", "x" * 33, "bad\nname"]
)
def test_ssid_validation_and_cross_network_collision(kind: str, value: str) -> None:
    """Invalid and duplicate names are rejected before any write."""
    with pytest.raises(ConfigurationError):
        settings_contracts()[f"wifi_{kind}_settings"].build(
            _raw(kind), {f"wlan_{kind}_ssid": value}
        )


@pytest.mark.parametrize("value", ["********", "short", "é" * 10, "a" * 64])
def test_masked_or_invalid_current_secret_never_reused(value: str) -> None:
    """A masked credential cannot silently replace the router's existing key."""
    with pytest.raises(ConfigurationError):
        settings_contracts()["wifi_guest_settings"].build(
            {**_raw(), "wlan_guest_key": value}, {"wlan_guest_time": "60"}
        )


def test_guest_display_can_be_explicitly_kept_after_key_change() -> None:
    """An explicit display choice overrides the native key-change default."""
    payload = settings_contracts()["wifi_guest_settings"].build(
        _raw(),
        {
            "wlan_guest_key": "NewSynthetic123",
            "wlan_guest_display_key": True,
        },
    )
    assert payload["wlan_guest_display_key"] == "1"


def test_no_secondary_network_write_with_main_wifi_disabled() -> None:
    """Unavailable guest and office form fields cannot be written."""
    with pytest.raises(ConfigurationError, match="wifi_disabled"):
        settings_contracts()["wifi_guest_settings"].build(
            {**_raw(), "use_wlan": "0"}, {"wlan_guest_active": True}
        )


def test_wps_requires_global_support_and_no_unknown_fields() -> None:
    """The editor cannot enable unavailable WPS or inject other operations."""
    contract = settings_contracts()["wifi_guest_settings"]
    raw = {**_raw(), "use_wps": "0"}
    assert "wlan_guest_wps" not in contract.build(raw, {"wlan_guest_time": "60"})
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"wlan_guest_wps": True})
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"rescan": True})
