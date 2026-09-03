"""Tests for privacy-safe native panel metadata."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized

from custom_components.speedport_smart import panel as panel_module
from custom_components.speedport_smart.panel import (
    _PANEL_ADMIN_READ_WS_TYPE,
    _PROTECTED_READ_ONLY_GROUP_BY_KEY,
    _PUBLIC_STATUS_KEYS,
    _access_source_for_entity,
    _capability_panel_data,
    _entity_panel_data,
    _entry_panel_data,
    _permission_scoped_access_sources,
    _section_for_entity,
    websocket_panel_admin_read,
)

_EXPECTED_PUBLIC_STATUS_KEYS = {
    "ddns_connected",
    "ddns_status",
    "device_password_changed",
    "dns_rebind_protection",
    "dsl_connected",
    "dsl_downstream",
    "dsl_error_code",
    "dsl_upstream",
    "firewall_enabled",
    "hybrid_connected",
    "hybrid_dsl_tunnel",
    "hybrid_enabled",
    "hybrid_lte_tunnel",
    "initial_setup_completed",
    "internet_bng_configured",
    "internet_connected",
    "internet_connected_since",
    "internet_error_code",
    "internet_privacy_level",
    "internet_provider_family",
    "internet_provisioning_code",
    "internet_uptime",
    "lan_linked_ports",
    "lan_port_1_connected",
    "lan_port_1_speed",
    "lan_port_2_connected",
    "lan_port_2_speed",
    "lan_port_3_connected",
    "lan_port_3_speed",
    "lan_port_4_connected",
    "lan_port_4_speed",
    "mobile_band",
    "mobile_connected",
    "mobile_lte_band",
    "mobile_lte_signal",
    "mobile_network_type",
    "mobile_nr_band",
    "mobile_nr_signal",
    "mobile_rsrp",
    "mobile_status_code",
    "parental_controls_enabled",
    "port_blocking_enabled",
    "receiver_esim_supported",
    "receiver_external_modem_enabled",
    "receiver_external_wan_link",
    "receiver_lte_enabled",
    "receiver_mode",
    "remote_support_active",
    "receiver_model",
    "router_https_enabled",
    "settings_write_blocked",
    "smarthome_linked",
    "easy_support_enabled",
    "system_operating_mode",
    "telephony_hd_voice_active",
    "telephony_manual_configuration_available",
    "telephony_provider_family",
    "telephony_provisioning_code",
    "wan_download_capacity",
    "wan_upload_capacity",
    "wifi_2_4_clients",
    "wifi_5_channel_width",
    "wifi_5_clients",
    "wifi_guest_clients",
    "wifi_guest_2_4_clients",
    "wifi_guest_5_clients",
    "wifi_guest_wifi_4_clients",
    "wifi_guest_wifi_5_clients",
    "wifi_guest_wifi_6_clients",
    "wifi_guest_remaining_time",
    "wifi_office_clients",
}
_EXPECTED_PROTECTED_READ_ONLY_GROUPS = {
    "internet_bng_configured": "connection_internet",
    "internet_provisioning_code": "connection_internet",
    "internet_provider_family": "connection_internet",
    "internet_error_code": "connection_internet",
    "internet_privacy_level": "connection_privacy",
    "mobile_connected": "mobile_connection",
    "mobile_status_code": "mobile_connection",
    "mobile_nr_signal": "mobile_signal",
    "mobile_lte_signal": "mobile_signal",
    "mobile_nr_band": "mobile_radio",
    "mobile_lte_band": "mobile_radio",
    "wifi_band_mode": "wireless_radios",
    "wifi_wps_state_code": "wireless_wps",
    "wifi_2_4_encryption_mode": "wireless_2_4",
    "wifi_guest_encryption_mode": "wireless_guest",
    "wifi_office_encryption_mode": "wireless_office",
    "wifi_schedule_mode": "wireless_schedule",
    "wifi_schedule_daily_from": "wireless_schedule",
    "wifi_schedule_daily_to": "wireless_schedule",
    "wifi_schedule_weekly": "wireless_schedule",
    "wifi_enabled": "wireless_general",
    "lan_ipv4_address": "clients_lan",
    "lan_subnet_mask": "clients_lan",
    "lan_ipv6_enabled": "clients_lan",
    "dhcp_pool_size": "clients_dhcp",
    "ddns_provider": "system_ddns",
    "ddns_status": "system_ddns",
    "receiver_mode": "mobile_receiver_status",
    "receiver_model": "mobile_receiver_status",
    "receiver_esim_supported": "mobile_receiver_status",
    "receiver_external_wan_link": "mobile_receiver_status",
    "receiver_led_mode": "mobile_receiver_status",
    "receiver_firmware_version": "mobile_receiver_firmware",
    "receiver_latest_firmware": "mobile_receiver_firmware",
    "receiver_firmware_update_time": "mobile_receiver_firmware",
    "usb_tethering_status": "system_usb_tethering",
    "usb_storage_devices": "system_nas",
    "usb_storage_total": "system_nas",
    "usb_storage_used": "system_nas",
    "usb_storage_free": "system_nas",
    "media_server_folders": "system_usb",
    "media_server_active_folders": "system_usb",
    "dns_rebind_exceptions": "system_security_dns",
    "firewall_enabled": "system_security",
    "dns_rebind_protection": "system_security",
    "router_https_enabled": "system_security",
    "port_block_rules": "system_security_port_block",
    "active_port_block_rules": "system_security_port_block",
    "qos_prioritized_clients": "system_security_qos",
    "dect_repeaters": "telephony_dect",
    "phonebook_entries": "telephony_phonebooks",
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
    "system_operating_mode": "system_health",
    "settings_write_blocked": "system_health",
    "device_password_changed": "system_health",
    "initial_setup_completed": "system_health",
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
    "port_blocking_enabled": "system_security_port_block",
    "dect_scan_active": "telephony_dect",
    "dect_smart_home_enabled": "telephony_dect",
    "telephony_voip_possible": "telephony_voip",
    "firmware_update_planned": "system_firmware",
    "firmware_automatic_updates": "system_firmware",
    "remote_support_active": "system_support",
    "easy_support_enabled": "system_support",
}
_PUBLIC_STATUS_PLACEMENT_KEYS = {
    "device_password_changed",
    "dns_rebind_protection",
    "firewall_enabled",
    "initial_setup_completed",
    "internet_bng_configured",
    "internet_error_code",
    "internet_provider_family",
    "internet_provisioning_code",
    "mobile_connected",
    "mobile_lte_band",
    "mobile_lte_signal",
    "mobile_nr_band",
    "mobile_nr_signal",
    "mobile_status_code",
    "receiver_esim_supported",
    "receiver_external_wan_link",
    "receiver_model",
    "router_https_enabled",
    "settings_write_blocked",
    "system_operating_mode",
}
_PROTECTED_BINARY_KEYS = {
    "device_password_changed",
    "dns_rebind_protection",
    "firewall_enabled",
    "wifi_enabled",
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
    "port_blocking_enabled",
    "dect_scan_active",
    "dect_smart_home_enabled",
    "telephony_voip_possible",
    "firmware_update_planned",
    "firmware_automatic_updates",
    "remote_support_active",
    "easy_support_enabled",
    "lan_ipv6_enabled",
    "initial_setup_completed",
    "internet_bng_configured",
    "mobile_connected",
    "receiver_esim_supported",
    "receiver_external_wan_link",
    "router_https_enabled",
    "settings_write_blocked",
}


async def test_panel_registration_uses_current_schema_cache_key() -> None:
    """The panel URL and config force stale frontend modules onto current schema."""
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()

    with (
        patch.object(panel_module.websocket_api, "async_register_command"),
        patch.object(
            panel_module.panel_custom,
            "async_register_panel",
            AsyncMock(),
        ) as register_panel,
    ):
        await panel_module.async_register_panel(hass)

    assert panel_module.PANEL_SCHEMA_VERSION == 24
    register_panel.assert_awaited_once()
    assert register_panel.await_args.kwargs["module_url"] == (
        "/speedport_smart_frontend/speedport-smart-panel.js?schema=24"
    )
    assert register_panel.await_args.kwargs["config"] == {"schema_version": 24}


def test_powerline_child_entities_use_the_lan_section() -> None:
    """Powerline node entities belong to the network/LAN capability area."""
    assert (
        _section_for_entity(
            "powerline_download_link_speed",
            "sensor",
            "powerline_node",
        )
        == "clients"
    )


@pytest.mark.parametrize(
    "key",
    [
        "endpoint_failures",
        "fast_polling_health",
        "normal_polling_health",
        "slow_polling_health",
    ],
)
def test_polling_diagnostics_are_local_management_health(key: str) -> None:
    """Integration health never masquerades as protected router data."""
    assert _section_for_entity(key, "sensor", None) == "management"
    assert (
        _access_source_for_entity(key, "sensor", None, is_control=False)
        == "integration"
    )


def _admin_read_message() -> dict[str, object]:
    """Return one valid admin read command message."""
    return {
        "id": 7,
        "type": _PANEL_ADMIN_READ_WS_TYPE,
        "entry_id": "entry-1",
    }


def test_admin_read_websocket_requires_home_assistant_admin() -> None:
    """Non-admin users cannot reach config-entry or cached router data."""
    hass = MagicMock()
    connection = MagicMock()
    connection.user.is_admin = False

    with pytest.raises(Unauthorized):
        websocket_panel_admin_read(hass, connection, _admin_read_message())

    hass.config_entries.async_get_entry.assert_not_called()
    connection.send_result.assert_not_called()


def test_admin_read_websocket_returns_cached_projection_without_router_io() -> None:
    """Admin reads use only the loaded hub snapshot and never its client."""
    client = MagicMock()
    hub = SimpleNamespace(
        capability_report=SimpleNamespace(),
        client=client,
        data={"clients": {"items": ({"name": "Laptop", "connected": True},)}},
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    connection = MagicMock()
    connection.user.is_admin = True

    websocket_panel_admin_read(hass, connection, _admin_read_message())

    connection.send_result.assert_called_once_with(
        7,
        {
            "schema_version": 2,
            "entry_id": "entry-1",
            "sections": [
                {
                    "id": "clients",
                    "source": "protected_json",
                    "rows": [{"name": "Laptop", "connected": True}],
                    "truncated": False,
                }
            ],
        },
    )
    assert client.mock_calls == []


@pytest.mark.parametrize(
    ("entry", "error_code"),
    [
        (None, "entry_not_found"),
        (
            SimpleNamespace(
                entry_id="entry-1",
                domain="another_domain",
                state=ConfigEntryState.LOADED,
            ),
            "entry_not_found",
        ),
        (
            SimpleNamespace(
                entry_id="entry-1",
                domain="speedport_smart",
                state=ConfigEntryState.NOT_LOADED,
            ),
            "entry_not_loaded",
        ),
    ],
)
def test_admin_read_websocket_rejects_invalid_or_unloaded_entries(
    entry: object,
    error_code: str,
) -> None:
    """The admin endpoint is scoped to one currently loaded integration entry."""
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    connection = MagicMock()
    connection.user.is_admin = True

    websocket_panel_admin_read(hass, connection, _admin_read_message())

    connection.send_error.assert_called_once()
    assert connection.send_error.call_args.args[:2] == (7, error_code)
    connection.send_result.assert_not_called()


def test_admin_read_websocket_rejects_loaded_entry_without_runtime_hub() -> None:
    """A transitional loaded state cannot expose a missing runtime snapshot."""
    entry = SimpleNamespace(
        entry_id="entry-1",
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=None,
    )
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    connection = MagicMock()
    connection.user.is_admin = True

    websocket_panel_admin_read(hass, connection, _admin_read_message())

    connection.send_error.assert_called_once_with(
        7,
        "entry_not_loaded",
        "Speedport Smart config entry is not loaded",
    )
    connection.send_result.assert_not_called()


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


def test_panel_router_identity_exposes_safe_runtime_fields_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Panel identity includes versions but never stable or serial identifiers."""
    hub = SimpleNamespace(
        capabilities=set(),
        capability_report=object(),
        router_identity=SimpleNamespace(
            firmware="010152.5.0.001.0",
            hardware_version="R01",
            identifier="private-router-identifier",
            model="Speedport Smart 4R Typ A",
            serial_number="private-router-serial",
        ),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        runtime_data=hub,
        state=ConfigEntryState.LOADED,
        title="My Speedport",
    )
    connection = MagicMock()
    connection.user.is_admin = True
    monkeypatch.setattr(
        panel_module.er,
        "async_entries_for_config_entry",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        panel_module,
        "_capability_panel_data",
        lambda _hub: ([], []),
    )
    monkeypatch.setattr(
        panel_module,
        "_management_panel_data",
        lambda _hub: {"state": "available"},
    )

    metadata = _entry_panel_data(entry, connection, MagicMock(), MagicMock())

    assert metadata is not None
    assert metadata["model"] == "Speedport Smart 4R Typ A"
    assert metadata["firmware"] == "010152.5.0.001.0"
    assert metadata["hardware_version"] == "R01"
    serialized = json.dumps(metadata)
    assert "private-router-identifier" not in serialized
    assert "private-router-serial" not in serialized
    assert "identifier" not in metadata
    assert "serial_number" not in metadata


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
    assert metadata["control_supported"] is True
    assert metadata["section"] == "controls"
    assert metadata["mutates_router"] is True
    assert metadata["risk"] == "normal"
    assert metadata["confirmation"] == "none"
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
    assert metadata["control_supported"] is True
    assert metadata["section"] == "controls"
    assert metadata["access_source"] == "router_control"
    assert metadata["mutates_router"] is True
    connection.user.permissions.check_entity.assert_called_once_with(
        "text.speedport_client_name", "control"
    )


@pytest.mark.parametrize(
    ("domain", "translation_key"),
    [
        ("button", "capture_read_only_inventory"),
        ("button", "reboot_router"),
        ("button", "reconnect_internet"),
        ("button", "retry_protected_data"),
        ("button", "wps"),
        ("select", "internet_privacy_level_control"),
        ("select", "receiver_led_mode_control"),
        ("switch", "client_fixed_dhcp"),
        ("switch", "guest_wifi"),
        ("switch", "hybrid_bonding"),
        ("switch", "office_wifi"),
        ("switch", "port_forward_rule"),
        ("switch", "wifi"),
        ("text", "client_name"),
    ],
)
def test_every_reviewed_control_retains_semantics_without_control_permission(
    domain: str,
    translation_key: str,
) -> None:
    """Control identity remains visible without granting an executable action."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = False
    connection.user.permissions.check_entity.return_value = False
    entity_id = f"{domain}.speedport_{translation_key}"
    entry = SimpleNamespace(
        entity_id=entity_id,
        translation_key=translation_key,
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control_supported"] is True
    assert metadata["control"] is False
    assert metadata["section"] == "controls"
    assert metadata["access_source"] in {"integration", "router_control"}
    connection.user.permissions.check_entity.assert_called_once_with(
        entity_id, "control"
    )


@pytest.mark.parametrize(
    ("domain", "translation_key", "feature_id"),
    [
        (
            "button",
            "capture_read_only_inventory",
            "home_assistant_capability_inventory",
        ),
        ("button", "reboot_router", "system_reboot"),
        ("button", "reconnect_internet", "internet_reconnect"),
        ("button", "retry_protected_data", "home_assistant_session_recovery"),
        ("button", "wps", "network_wifi_wps_start"),
        ("select", "internet_privacy_level_control", "internet_privacy"),
        ("select", "receiver_led_mode_control", "internet_receiver_led"),
        ("switch", "client_fixed_dhcp", "network_client_fixed_dhcp"),
        ("switch", "guest_wifi", "network_wifi_guest"),
        ("switch", "hybrid_bonding", "internet_hybrid_bonding"),
        ("switch", "office_wifi", "network_wifi_office"),
        ("switch", "port_forward_rule", "internet_port_forward_toggle"),
        ("switch", "wifi", "network_wifi_main"),
        ("text", "client_name", "network_client_rename"),
    ],
)
def test_every_reviewed_control_has_one_backend_feature_id(
    domain: str,
    translation_key: str,
    feature_id: str,
) -> None:
    """Administration placement follows backend semantics, not display names."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True
    entry = SimpleNamespace(
        entity_id=f"{domain}.speedport_{translation_key}",
        translation_key=translation_key,
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["management_feature"] == feature_id


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
        assert metadata["risk"] == (
            "disruptive"
            if translation_key == "internet_privacy_level_control"
            else "normal"
        )
        assert metadata["confirmation"] == (
            "confirm" if translation_key == "internet_privacy_level_control" else "none"
        )
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
    assert metadata["control_supported"] is True
    assert metadata["section"] == "controls"
    assert metadata["access_source"] == "router_control"
    assert metadata["mutates_router"] is True
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
    assert metadata["risk"] == "disruptive"
    assert metadata["confirmation"] == "confirm"


def test_main_wifi_control_reports_lockout_and_typed_confirmation() -> None:
    """Dashboard can distinguish a possible local-management lockout."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True
    entry = SimpleNamespace(
        entity_id="switch.speedport_wifi",
        translation_key="wifi",
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is True
    assert metadata["mutates_router"] is True
    assert metadata["risk"] == "lockout"
    assert metadata["confirmation"] == "typed"
    assert metadata["disruptive"] is True


def test_panel_never_promotes_an_unreviewed_entity_domain_to_control() -> None:
    """A switch-shaped registry entry is not itself a write authorization."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True
    entry = SimpleNamespace(
        entity_id="switch.speedport_factory_reset",
        translation_key="factory_reset",
        entity_category="config",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    assert metadata["control_supported"] is False
    assert metadata["mutates_router"] is False
    assert metadata["section"] != "controls"
    assert metadata["risk"] == "normal"
    assert metadata["confirmation"] == "confirm"


def test_retry_protected_data_control_requires_exact_button_registry_key() -> None:
    """Recovery stays limited to its real button registry entry."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True

    for entity_id, translation_key, expected_control in (
        ("button.speedport_retry_protected_data", "retry_protected_data", True),
        ("button.retry_protected_data", None, False),
        ("switch.speedport_retry_protected_data", "retry_protected_data", False),
        ("text.speedport_retry_protected_data", "retry_protected_data", False),
        ("update.speedport_retry_protected_data", "retry_protected_data", False),
    ):
        entry = SimpleNamespace(
            entity_id=entity_id,
            translation_key=translation_key,
            entity_category="diagnostic",
            supported_features=0,
            name=None,
        )

        metadata = _entity_panel_data(entry, None, connection)

        assert metadata["control"] is expected_control
        assert (metadata["section"] == "controls") is expected_control
        assert metadata["mutates_router"] is False


def test_read_only_inventory_control_requires_exact_button_registry_key() -> None:
    """Capability capture stays limited to its real diagnostic button."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = True

    for entity_id, translation_key, expected_control in (
        (
            "button.speedport_capture_read_only_inventory",
            "capture_read_only_inventory",
            True,
        ),
        ("button.capture_read_only_inventory", None, False),
        (
            "switch.speedport_capture_read_only_inventory",
            "capture_read_only_inventory",
            False,
        ),
        (
            "text.speedport_capture_read_only_inventory",
            "capture_read_only_inventory",
            False,
        ),
        (
            "update.speedport_capture_read_only_inventory",
            "capture_read_only_inventory",
            False,
        ),
    ):
        entry = SimpleNamespace(
            entity_id=entity_id,
            translation_key=translation_key,
            entity_category="diagnostic",
            supported_features=0,
            name=None,
        )

        metadata = _entity_panel_data(entry, None, connection)

        assert metadata["control"] is expected_control
        assert (metadata["section"] == "controls") is expected_control
        assert metadata["access_source"] == "integration"
        assert metadata["mutates_router"] is False
        assert metadata["risk"] == "normal"
        assert metadata["disruptive"] is False


def test_read_only_inventory_control_requires_entity_control_permission() -> None:
    """Read access alone never grants capability capture through the panel."""
    connection = MagicMock()
    connection.user.permissions.access_all_entities.return_value = False
    connection.user.permissions.check_entity.return_value = False
    entry = SimpleNamespace(
        entity_id="button.speedport_capture_read_only_inventory",
        translation_key="capture_read_only_inventory",
        entity_category="diagnostic",
        supported_features=0,
        name=None,
    )

    metadata = _entity_panel_data(entry, None, connection)

    assert metadata["control"] is False
    assert metadata["control_supported"] is True
    assert metadata["section"] == "controls"
    assert metadata["access_source"] == "integration"
    assert metadata["mutates_router"] is False
    connection.user.permissions.check_entity.assert_called_once_with(
        "button.speedport_capture_read_only_inventory", "control"
    )


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


def test_public_status_failure_does_not_hide_healthy_wan_source() -> None:
    """The shared fast coordinator does not merge independent source health."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: (
        capability
        in {
            "status",
            "wan_counters",
        }
    )
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {"status": "SpeedportProtocolError"}
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
            "slow": {"available": True},
        }
    }

    sources, _families = _capability_panel_data(hub)

    public_source = next(
        source for source in sources if source["id"] == "public_status"
    )
    wan_source = next(source for source in sources if source["id"] == "wan_counters")
    assert public_source["available"] is False
    assert wan_source["available"] is True


def test_protected_source_is_unavailable_when_normal_polling_fails() -> None:
    """Normal protected polling failure marks the combined source unhealthy."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: (
        capability == "authenticated_json"
    )
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {}
    hub.wan_counter_telemetry = {}
    hub.diagnostics.return_value = {
        "polling": {
            "fast": {"available": True},
            "normal": {"available": False},
            "slow": {"available": True},
        }
    }

    sources, _families = _capability_panel_data(hub)

    protected = next(source for source in sources if source["id"] == "protected_json")
    assert protected["available"] is False


def test_protected_source_is_unavailable_when_slow_polling_fails() -> None:
    """Slow protected polling failure marks the combined source unhealthy."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: (
        capability == "authenticated_json"
    )
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {}
    hub.wan_counter_telemetry = {}
    hub.diagnostics.return_value = {
        "polling": {
            "fast": {"available": True},
            "normal": {"available": True},
            "slow": {"available": False},
        }
    }

    sources, _families = _capability_panel_data(hub)

    protected = next(source for source in sources if source["id"] == "protected_json")
    assert protected["available"] is False


def test_protected_source_is_available_when_both_poll_groups_are_healthy() -> None:
    """Protected source is healthy only when normal and slow reads are healthy."""
    hub = MagicMock()
    hub.capability_report = SimpleNamespace(feature_endpoints={})
    hub.has_capability.side_effect = lambda capability: (
        capability == "authenticated_json"
    )
    hub.get.return_value = {"state": "available"}
    hub.endpoint_errors = {}
    hub.wan_counter_telemetry = {}
    hub.diagnostics.return_value = {
        "polling": {
            "fast": {"available": True},
            "normal": {"available": True},
            "slow": {"available": True},
        }
    }

    sources, _families = _capability_panel_data(hub)

    protected = next(source for source in sources if source["id"] == "protected_json")
    assert protected["available"] is True


def test_new_management_entities_are_explicitly_grouped_and_read_only() -> None:
    """Every management summary has an explicit group and remains read-only."""
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
        assert metadata["access_source"] == (
            "public_status"
            if translation_key in _PUBLIC_STATUS_KEYS
            else "protected_json"
        )
        assert metadata["control"] is False
        assert metadata["mutates_router"] is False
        assert metadata["disruptive"] is False
        expected_section = {
            "connection": "connection",
            "wireless": "wireless",
            "mobile": "mobile",
            "telephony": "telephony",
            "clients": "clients",
        }.get(group.partition("_")[0], "system")
        assert metadata["section"] == expected_section


def test_public_status_source_keys_are_exact_and_win_over_group_metadata() -> None:
    """Only proven Status.json reads survive a competing browser session."""
    assert _PUBLIC_STATUS_KEYS == _EXPECTED_PUBLIC_STATUS_KEYS

    for translation_key in _PUBLIC_STATUS_KEYS:
        assert (
            _access_source_for_entity(
                translation_key,
                "sensor",
                None,
                is_control=False,
            )
            == "public_status"
        )

    # DECT paging is normalized from authenticated DECTInfo.json, not Status.json.
    assert (
        _access_source_for_entity(
            "dect_paging_active",
            "binary_sensor",
            None,
            is_control=False,
        )
        == "protected_json"
    )


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
    asset_keys = (
        _EXPECTED_PROTECTED_READ_ONLY_GROUPS.keys() - _PUBLIC_STATUS_PLACEMENT_KEYS
    )
    protected_sensor_keys = asset_keys - _PROTECTED_BINARY_KEYS
    protected_binary_keys = asset_keys & _PROTECTED_BINARY_KEYS

    for catalog in catalogs:
        assert catalog["entity"]["sensor"].keys() >= protected_sensor_keys
        assert catalog["entity"]["binary_sensor"].keys() >= protected_binary_keys
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
    assert icons["binary_sensor"].keys() >= protected_binary_keys
