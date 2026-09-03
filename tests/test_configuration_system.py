"""Offline proof of the fixed system-setting forms and their privacy boundary."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    SettingsContract,
)
from custom_components.speedport_smart.configuration_system import SYSTEM_SETTINGS

_CONTRACTS = {item.id: item for item in SYSTEM_SETTINGS}
_LED = {"led_mode": "1", "led_from": "23:30", "led_to": "07:30"}
_ENERGY = {
    "use_wlan": "1",
    "wlan_band": "0",
    "wlan_power": "1",
    "use_usb": "1",
    "config_connection": "0",
}


def test_system_contracts_have_exact_independent_transport_bindings() -> None:
    """Read sources do not silently become mutation endpoints."""
    assert {
        item.id: (item.endpoint, item.read_endpoint or item.endpoint, item.referer)
        for item in SYSTEM_SETTINGS
    } == {
        "system_led_schedule": (
            "data/Energy.json",
            "data/Energy.json",
            "html/content/config/energy.html",
        ),
        "system_energy": (
            "data/Energy.json",
            "data/Energy.json",
            "html/content/config/energy.html",
        ),
        "system_https": (
            "data/Protect.json",
            "data/Energy.json",
            "html/content/config/protect.html",
        ),
        "system_external_modem": (
            "data/ExtModem.json",
            "data/ExtModem.json",
            "html/content/config/external_modem.html",
        ),
        "system_cloud_backup": (
            "data/BackupRestore.json",
            "data/BackupRestore.json",
            "html/content/config/save_settings.html",
        ),
        "system_extended_logging": (
            "data/Modules.json",
            "data/SystemMessages.json",
            "html/content/config/system_log.html",
        ),
    }


def test_system_acknowledgements_and_reconnect_policies_match_static_callbacks() -> (
    None
):
    """A callback without a status check is never positive acknowledgement proof."""
    assert {
        item.id: (item.acknowledgement, item.readback_policy)
        for item in SYSTEM_SETTINGS
    } == {
        "system_led_schedule": ("status_ok", "exact"),
        "system_energy": ("status_ok", "exact"),
        "system_https": ("readback", "reconnect_required"),
        "system_external_modem": ("readback", "reconnect_required"),
        "system_cloud_backup": ("readback", "exact"),
        "system_extended_logging": ("readback", "exact"),
    }


def test_system_hidden_prerequisites_are_revision_bound_not_displayed() -> None:
    """A target grant binds prerequisite state without leaking it into the editor."""
    contract = _CONTRACTS["system_cloud_backup"]
    first = {"br_active": "0", "easy_support_deactive": "0"}
    second = {**first, "easy_support_deactive": "1"}
    assert contract.read(first) == contract.read(second) == {"br_active": False}
    assert contract.revision(first) != contract.revision(second)
    assert "easy_support_deactive" not in repr(contract.metadata())


def test_led_schedule_preserves_the_other_time_and_supports_cross_midnight() -> None:
    """Only the LED form is sent, not the unrelated energy controls."""
    contract = _CONTRACTS["system_led_schedule"]
    raw = {**_LED, **_ENERGY, "PRIVATE": "must-not-leave"}
    assert contract.build(raw, {"led_from": "22:15"}) == {
        "led_mode": "1",
        "led_from": "22:15",
        "led_to": "07:30",
    }
    assert contract.read(raw) == _LED
    assert raw["led_from"] == "23:30"


def test_disabling_led_schedule_omits_hidden_time_inputs() -> None:
    """The firmware hides time inputs when all LEDs are selected."""
    contract = _CONTRACTS["system_led_schedule"]
    assert contract.build(_LED, {"led_mode": "0"}) == {"led_mode": "0"}
    with pytest.raises(ConfigurationError):
        contract.build(_LED, {"led_mode": "0", "led_to": "08:00"})


@pytest.mark.parametrize("value", ["24:01", "7:30", "12:60", "-1:00", "07:30\n", 730])
def test_led_time_validation_is_closed(value: object) -> None:
    """Only the explicitly supported canonical daily time format is accepted."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_led_schedule"].build(_LED, {"led_to": value})


def test_led_timehhmm_preserves_end_of_day_and_rejects_equal_times() -> None:
    """The exact LED validator permits24:00 but scheduled endpoints must differ."""
    contract = _CONTRACTS["system_led_schedule"]
    assert contract.build(_LED, {"led_to": "24:00"})["led_to"] == "24:00"
    assert contract.read({**_LED, "led_to": "24:00"})["led_to"] == "24:00"
    with pytest.raises(ConfigurationError):
        contract.build(_LED, {"led_to": "23:30"})


@pytest.mark.parametrize("field", ["led_mode", "led_from", "led_to"])
def test_led_build_requires_complete_fresh_state_even_for_full_replacement(
    field: str,
) -> None:
    """Client changes cannot bypass a missing current-form proof."""
    raw = dict(_LED)
    raw.pop(field)
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_led_schedule"].build(raw, _LED)


def test_energy_preserves_every_shared_field_and_never_copies_led_state() -> None:
    """USB changes keep both Wi-Fi settings and global Wi-Fi state intact."""
    assert _CONTRACTS["system_energy"].build(
        {**_ENERGY, **_LED, "wlan_wpa_key": "PRIVATE"}, {"use_usb": False}
    ) == {"use_wlan": "1", "wlan_band": "0", "wlan_power": "1", "use_usb": "0"}


def test_energy_wired_wifi_disable_matches_hidden_radio_serialization() -> None:
    """Hidden selects are preserved; the hidden band radio is omitted."""
    assert _CONTRACTS["system_energy"].build(_ENERGY, {"use_wlan": False}) == {
        "use_wlan": "0",
        "wlan_power": "1",
        "use_usb": "1",
    }


@pytest.mark.parametrize("connection", [None, "1", 1, False, 0.0, "PRIVATE"])
def test_energy_wifi_disable_requires_exact_wired_connection_proof(
    connection: object,
) -> None:
    """The firmware's separate wireless-disconnect action is not guessed."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_energy"].build(
            {**_ENERGY, "config_connection": connection}, {"use_wlan": False}
        )


@pytest.mark.parametrize("field", ["wlan_band", "wlan_power"])
def test_energy_rejects_hidden_wifi_edits_while_disabled(field: str) -> None:
    """The editor cannot silently discard a requested hidden-field change."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_energy"].build({**_ENERGY, "use_wlan": "0"}, {field: "2"})


def test_energy_can_enable_wifi_with_complete_band_and_power_state() -> None:
    """Enabling Wi-Fi restores the visible complete energy form."""
    assert _CONTRACTS["system_energy"].build(
        {**_ENERGY, "use_wlan": "0"}, {"use_wlan": True, "wlan_band": "2"}
    ) == {"use_wlan": "1", "wlan_band": "2", "wlan_power": "1", "use_usb": "1"}


@pytest.mark.parametrize("field", ["wlan_band", "wlan_power"])
@pytest.mark.parametrize("value", ["3", "unknown", True, 0.0, None])
def test_energy_read_rejects_unreviewed_enum_state(field: str, value: object) -> None:
    """An unknown current mode cannot be preserved as a guessed wire value."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_energy"].read({**_ENERGY, field: value})


@pytest.mark.parametrize(
    ("contract_id", "changes"),
    [
        ("system_led_schedule", _LED),
        (
            "system_energy",
            {"use_wlan": True, "wlan_band": "0", "wlan_power": "0", "use_usb": True},
        ),
        ("system_https", {"use_https": True}),
        ("system_external_modem", {"auto_external_modem": True}),
        ("system_cloud_backup", {"br_active": True}),
        ("system_extended_logging", {"use_extendlog": True}),
    ],
)
def test_every_system_builder_requires_fresh_current_fields(
    contract_id: str, changes: dict[str, Any]
) -> None:
    """Supplying all new values never substitutes for a readable current form."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS[contract_id].build({}, changes)


@pytest.mark.parametrize(
    ("contract_id", "raw", "changes", "expected"),
    [
        ("system_https", {"use_https": "0"}, {"use_https": True}, {"use_https": "1"}),
        (
            "system_external_modem",
            {"auto_external_modem": "1", "use_lte": "0"},
            {"auto_external_modem": False},
            {"auto_external_modem": "0"},
        ),
        (
            "system_cloud_backup",
            {"br_active": "0", "easy_support_deactive": "0"},
            {"br_active": True},
            {"br_active": "1"},
        ),
        (
            "system_extended_logging",
            {"use_extendlog": "0", "message": "PRIVATE"},
            {"use_extendlog": True},
            {"use_extendlog": "1"},
        ),
    ],
)
def test_system_switches_emit_only_the_exact_fixed_wire_field(
    contract_id: str,
    raw: dict[str, Any],
    changes: dict[str, Any],
    expected: dict[str, str],
) -> None:
    """No private source field can leak into a switch payload or read result."""
    contract = _CONTRACTS[contract_id]
    assert contract.build(raw, changes) == expected
    assert "PRIVATE" not in repr(contract.read(raw))
    assert "PRIVATE" not in repr(contract.metadata())


@pytest.mark.parametrize(
    ("contract_id", "raw", "changes", "prerequisite"),
    [
        (
            "system_external_modem",
            {"auto_external_modem": "0"},
            {"auto_external_modem": True},
            "use_lte",
        ),
        (
            "system_cloud_backup",
            {"br_active": "0"},
            {"br_active": True},
            "easy_support_deactive",
        ),
    ],
)
@pytest.mark.parametrize("value", [None, "1", True, "unknown", "PRIVATE", 1.0])
def test_system_switch_prerequisites_fail_closed_without_hiding_safe_read_state(
    contract_id: str,
    raw: dict[str, Any],
    changes: dict[str, Any],
    prerequisite: str,
    value: object,
) -> None:
    """Blocked controls still permit their bounded current state to be read."""
    contract = _CONTRACTS[contract_id]
    source = {**raw, prerequisite: value}
    assert contract.read(source) == {next(iter(changes)): False}
    with pytest.raises(ConfigurationError) as error:
        contract.build(source, changes)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("contract", SYSTEM_SETTINGS, ids=lambda item: item.id)
def test_system_contracts_reject_unknown_fields_and_unproven_raw_state(
    contract: SettingsContract,
) -> None:
    """Neither arbitrary fields nor missing preflight state can become writes."""
    with pytest.raises(ConfigurationError):
        contract.build({}, {"PRIVATE": "value"})
    with pytest.raises(ConfigurationError):
        contract.build({}, {})
    assert contract.payload_keys
    assert contract.metadata()["live_write_verified"] is False
    assert "endpoint" not in contract.metadata()


@pytest.mark.parametrize("value", [0, 1, "0", "1", "false", None, 0.0])
def test_https_change_requires_a_real_boolean(value: object) -> None:
    """Wire decoding is allowed only for reads, never for administrator input."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_https"].build({"use_https": "0"}, {"use_https": value})
