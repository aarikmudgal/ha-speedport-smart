"""Tests for privacy-safe native panel metadata."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.speedport_smart.panel import (
    _PROTECTED_READ_ONLY_GROUP_BY_KEY,
    _access_source_for_entity,
    _capability_panel_data,
    _entity_panel_data,
    _permission_scoped_access_sources,
)

_EXPECTED_PROTECTED_READ_ONLY_GROUPS = {
    "internet_privacy_level": "connection_privacy",
    "wifi_band_mode": "wireless_radios",
    "wifi_wps_state_code": "wireless_wps",
    "wifi_2_4_encryption_mode": "wireless_2_4",
    "wifi_guest_encryption_mode": "wireless_guest",
    "wifi_office_encryption_mode": "wireless_office",
    "wifi_schedule_mode": "wireless_schedule",
    "wifi_schedule_daily_from": "wireless_schedule",
    "wifi_schedule_daily_to": "wireless_schedule",
    "receiver_mode": "mobile_receiver_status",
    "receiver_led_mode": "mobile_receiver_status",
    "receiver_firmware_version": "mobile_receiver_firmware",
    "receiver_latest_firmware": "mobile_receiver_firmware",
    "receiver_firmware_update_time": "mobile_receiver_firmware",
    "usb_tethering_status": "system_usb_tethering",
    "usb_storage_devices": "system_nas",
    "usb_storage_total": "system_nas",
    "usb_storage_used": "system_nas",
    "usb_storage_free": "system_nas",
    "dns_rebind_exceptions": "system_security_dns",
    "port_block_rules": "system_security_port_block",
    "active_port_block_rules": "system_security_port_block",
    "qos_prioritized_clients": "system_security_qos",
    "dect_repeaters": "telephony_dect",
    "pbx_configured_clients": "telephony_pbx",
    "pbx_disconnected_clients": "telephony_pbx",
    "pbx_registered_clients": "telephony_pbx",
    "pbx_locked_clients": "telephony_pbx",
    "telephony_voip_policy": "telephony_voip",
    "telephony_providers": "telephony_voip",
    "telephony_configured_numbers": "telephony_voip",
    "telephony_registered_voip_numbers": "telephony_voip",
    "telephony_inactive_voip_numbers": "telephony_voip",
    "telephony_warning_voip_numbers": "telephony_voip",
    "firmware_update_time": "system_firmware",
    "wifi_wps_enabled": "wireless_wps",
    "wifi_wps_disabled_by_firmware": "wireless_wps",
    "wifi_allow_all_devices": "wireless_access",
    "wifi_2_4_visible": "wireless_2_4",
    "wifi_5_visible": "wireless_5",
    "guest_wifi_wps_enabled": "wireless_wps",
    "receiver_external_modem_enabled": "mobile_receiver_status",
    "receiver_lte_enabled": "mobile_receiver_status",
    "receiver_firmware_automatic_updates": "mobile_receiver_firmware",
    "receiver_firmware_update_available": "mobile_receiver_firmware",
    "receiver_firmware_update_planned": "mobile_receiver_firmware",
    "usb_port_enabled": "system_usb",
    "usb_tethering_enabled": "system_usb_tethering",
    "usb_tethering_connected": "system_usb_tethering",
    "usb_printer_connected": "system_usb",
    "nas_enabled": "system_nas",
    "nas_secure": "system_nas",
    "nas_read_only": "system_nas",
    "port_blocking_enabled": "system_security_port_block",
    "dect_scan_active": "telephony_dect",
    "dect_smart_home_enabled": "telephony_dect",
    "telephony_voip_possible": "telephony_voip",
    "firmware_update_planned": "system_firmware",
    "firmware_automatic_updates": "system_firmware",
    "remote_support_active": "system_support",
    "easy_support_enabled": "system_support",
}
_PROTECTED_BINARY_KEYS = {
    "wifi_wps_enabled",
    "wifi_wps_disabled_by_firmware",
    "wifi_allow_all_devices",
    "wifi_2_4_visible",
    "wifi_5_visible",
    "guest_wifi_wps_enabled",
    "receiver_external_modem_enabled",
    "receiver_lte_enabled",
    "receiver_firmware_automatic_updates",
    "receiver_firmware_update_available",
    "receiver_firmware_update_planned",
    "usb_port_enabled",
    "usb_tethering_enabled",
    "usb_tethering_connected",
    "usb_printer_connected",
    "nas_enabled",
    "nas_secure",
    "nas_read_only",
    "port_blocking_enabled",
    "dect_scan_active",
    "dect_smart_home_enabled",
    "telephony_voip_possible",
    "firmware_update_planned",
    "firmware_automatic_updates",
    "remote_support_active",
    "easy_support_enabled",
}


def test_panel_metadata_prefers_only_explicit_user_entity_name() -> None:
    """Expose a user override while leaving integration names per-user localized."""
    connection = MagicMock()
    entry = SimpleNamespace(
        entity_id="sensor.speedport_wan_download_rate",
        translation_key="wan_download_rate",
        entity_category=None,
        supported_features=0,
        name="My WAN rate",
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["custom_name"] == "My WAN rate"

    entry.name = None
    metadata = _entity_panel_data(entry, None, connection)

    assert "custom_name" not in metadata


def test_panel_metadata_allowlists_only_proven_text_control() -> None:
    """Expose client rename, but never arbitrary text entities, as controls."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True
    entry = SimpleNamespace(
        entity_id="text.speedport_client_name",
        translation_key="client_name",
        entity_category=None,
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is True
    assert metadata["section"] == "controls"
    assert metadata["mutates_router"] is True
    assert "value" not in metadata
    assert "pattern" not in metadata

    entry.translation_key = "router_password"
    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    assert metadata["section"] != "controls"

    entry.translation_key = None
    entry.entity_id = "text.client_name"
    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False


def test_panel_text_control_requires_entity_control_permission() -> None:
    """Read access alone never grants client-name control through the panel."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = False
    connection.user.permissions.check_entity.return_value = False
    entry = SimpleNamespace(
        entity_id="text.speedport_client_name",
        translation_key="client_name",
        entity_category=None,
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    connection.user.permissions.check_entity.assert_called_once_with(
        "text.speedport_client_name", "control"
    )


def test_panel_metadata_allowlists_only_reviewed_select_controls() -> None:
    """Expose exact typed selects without leaking router transport details."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True

    for translation_key, disruptive in (
        ("internet_privacy_level_control", True),
        ("receiver_led_mode_control", False),
    ):
        entry = SimpleNamespace(
            entity_id=f"select.speedport_{translation_key}",
            translation_key=translation_key,
            entity_category="config",
            supported_features=0,
            name=None,
        )

        metadata = _entity_panel_data(entry, None, connection)

        assert metadata["control"] is True
        assert metadata["section"] == "controls"
        assert metadata["access_source"] == "router_control"
        assert metadata["mutates_router"] is True
        assert metadata["disruptive"] is disruptive
        assert "options" not in metadata
        assert "endpoint" not in metadata
        assert "payload" not in metadata

    entry.translation_key = "router_raw_endpoint"
    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    assert metadata["section"] != "controls"
    assert metadata["mutates_router"] is False


def test_select_control_requires_entity_control_permission() -> None:
    """Read access alone cannot expose an allowlisted select as interactive."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = False
    connection.user.permissions.check_entity.return_value = False
    entry = SimpleNamespace(
        entity_id="select.speedport_internet_privacy_level_control",
        translation_key="internet_privacy_level_control",
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    assert metadata["mutates_router"] is False
    connection.user.permissions.check_entity.assert_called_once_with(
        entry.entity_id, "control"
    )


def test_hybrid_bonding_is_a_disruptive_control() -> None:
    """Changing hybrid bonding receives the dashboard's disruptive warning."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True
    entry = SimpleNamespace(
        entity_id="switch.speedport_hybrid_bonding",
        translation_key="hybrid_bonding",
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is True
    assert metadata["disruptive"] is True


def test_panel_source_health_is_limited_to_readable_entity_families() -> None:
    """Do not reveal router-wide source health to restricted panel users."""
    sources = [
        {"id": "public_status", "supported": True, "available": True},
        {"id": "protected_json", "supported": True, "available": True},
        {"id": "wan_counters", "supported": True, "available": False},
    ]
    entities = [
        {"access_source": "public_status"},
        {"access_source": "wan_counters"},
    ]

    assert _permission_scoped_access_sources(sources, entities) == [
        sources[0],
        sources[2],
    ]


def test_every_wan_interface_entity_uses_wan_counter_source() -> None:
    """WAN interface and scheduler entities never appear as protected JSON."""
    for key, domain in (
        ("wan_interface", "sensor"),
        ("wan_interface_status", "sensor"),
        ("wan_interface_enabled", "binary_sensor"),
        ("wan_polling_mode", "sensor"),
        ("wan_polling_interval", "sensor"),
        ("wan_polling_state", "sensor"),
        ("wan_fastest_proven_interval", "sensor"),
        ("wan_last_sample", "sensor"),
    ):
        assert (
            _access_source_for_entity(key, domain, None, is_control=False)
            == "wan_counters"
        )


def test_wan_source_metadata_exposes_retry_cadence_and_sample_time() -> None:
    """The panel receives UI-safe telemetry freshness without router I/O."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: capability == "wan_counters"
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {"wan_counters": "SpeedportSessionBusyError"}
    hub.wan_counter_telemetry = {
        "effective_interval_seconds": 3.0,
        "mode": "auto",
        "state": "learning",
        "target_interval_seconds": 1.0,
        "runtime_floor_seconds": 1.0,
        "last_stable_interval_seconds": 4.0,
        "retrying": True,
        "retry_in_seconds": 2.0,
        "last_sampled_at": "2026-09-01T10:00:00+00:00",
    }
    hub.diagnostics.return_value = {
        "polling": {
            "fast": {"available": True},
            "normal": {"available": True},
        },
    }

    sources, _families = _capability_panel_data(hub)

    wan_source = next(source for source in sources if source["id"] == "wan_counters")
    assert wan_source == {
        "id": "wan_counters",
        "label": "Live WAN counters",
        "supported": True,
        "polling_available": True,
        "available": False,
        "effective_interval_seconds": 3.0,
        "mode": "auto",
        "state": "learning",
        "target_interval_seconds": 1.0,
        "runtime_floor_seconds": 1.0,
        "last_stable_interval_seconds": 4.0,
        "retrying": True,
        "retry_in_seconds": 2.0,
        "last_sampled_at": "2026-09-01T10:00:00+00:00",
    }


def test_any_wan_endpoint_error_marks_source_unavailable() -> None:
    """A non-busy WAN failure is still distinct from rate warm-up."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: capability == "wan_counters"
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {"wan_counters": "SpeedportProtocolError"}
    hub.wan_counter_telemetry = {
        "state": "stable",
        "retrying": False,
        "effective_interval_seconds": 4.0,
        "last_sampled_at": "2026-09-01T10:00:00+00:00",
    }
    hub.diagnostics.return_value = {
        "polling": {
            "fast": {"available": True},
            "normal": {"available": True},
        }
    }

    sources, _families = _capability_panel_data(hub)

    wan_source = next(source for source in sources if source["id"] == "wan_counters")
    assert wan_source["available"] is False
    assert wan_source["retrying"] is False
    assert wan_source["state"] == "stable"


def test_new_management_entities_are_explicitly_grouped_and_read_only() -> None:
    """Every proven management summary stays protected data, never a control."""
    assert _PROTECTED_READ_ONLY_GROUP_BY_KEY == _EXPECTED_PROTECTED_READ_ONLY_GROUPS
    connection = MagicMock()

    for translation_key, group in _EXPECTED_PROTECTED_READ_ONLY_GROUPS.items():
        entry = SimpleNamespace(
            entity_id=f"switch.speedport_{translation_key}",
            translation_key=translation_key,
            entity_category=None,
            supported_features=0,
            name=None,
        )

        metadata = _entity_panel_data(entry, None, connection)

        assert metadata["capability_group"] == group
        assert metadata["access_source"] == "protected_json"
        assert metadata["control"] is False
        assert metadata["mutates_router"] is False
        assert metadata["disruptive"] is False
        expected_section = {
            "connection": "connection",
            "wireless": "wireless",
            "mobile": "mobile",
            "telephony": "telephony",
        }.get(group.partition("_")[0], "system")
        assert metadata["section"] == expected_section


def test_new_management_entities_have_labels_and_icons() -> None:
    """Every new dashboard item has complete locale shape and an explicit icon."""
    root = Path(__file__).parents[1] / "custom_components" / "speedport_smart"
    catalogs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (
            root / "strings.json",
            root / "translations" / "en.json",
            root / "translations" / "de.json",
        )
    ]
    icons = json.loads((root / "icons.json").read_text(encoding="utf-8"))["entity"]
    protected_sensor_keys = (
        _EXPECTED_PROTECTED_READ_ONLY_GROUPS.keys() - _PROTECTED_BINARY_KEYS
    )

    for catalog in catalogs:
        assert catalog["entity"]["sensor"].keys() >= protected_sensor_keys
        assert catalog["entity"]["binary_sensor"].keys() >= _PROTECTED_BINARY_KEYS
        assert catalog["entity"]["sensor"]["internet_privacy_level"][
            "state"
        ].keys() == {"off", "level_1", "level_2"}
        assert catalog["entity"]["sensor"]["wifi_band_mode"]["state"].keys() == {
            "both_bands",
            "2_4_ghz_only",
            "5_ghz_only",
        }
        assert catalog["entity"]["sensor"]["wifi_wps_state_code"]["state"].keys() == {
            "failed",
            "successful",
            "in_progress",
        }
        assert catalog["entity"]["sensor"]["wifi_schedule_mode"]["state"].keys() == {
            "disabled",
            "daily",
            "weekly",
        }
        assert catalog["entity"]["sensor"]["receiver_led_mode"]["state"].keys() == {
            "use_leds",
            "off_after_timeout",
            "disabled",
        }
        assert catalog["entity"]["sensor"]["telephony_voip_policy"]["state"].keys() == {
            "off",
            "level_1",
            "level_2",
        }
        assert "state" not in catalog["entity"]["sensor"]["receiver_mode"]
        assert "state" not in catalog["entity"]["sensor"]["usb_tethering_status"]
    assert icons["sensor"].keys() >= protected_sensor_keys
    assert icons["binary_sensor"].keys() >= _PROTECTED_BINARY_KEYS
