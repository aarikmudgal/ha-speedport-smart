"""Bundled full-page frontend panel for Speedport Smart."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.websocket_api.decorators import (
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .management import ManagementRisk, get_entity_write_contract
from .panel_read import admin_read_payload

if TYPE_CHECKING:
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH: Final = "speedport-smart"
PANEL_COMPONENT_NAME: Final = "speedport-smart-panel"
PANEL_TITLE: Final = "Telekom Speedport Smart"
PANEL_ICON: Final = "mdi:router-network"
PANEL_SCHEMA_VERSION: Final = 12

_STATIC_URL: Final = "/speedport_smart_frontend"
_FRONTEND_DIR: Final = Path(__file__).parent / "frontend"
_FRONTEND_FILE: Final = "speedport-smart-panel.js"
_PANEL_DATA_KEY: Final = f"{DOMAIN}_frontend_panel"
_PANEL_WS_TYPE: Final = f"{DOMAIN}/panel"
_PANEL_ADMIN_READ_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/admin_read"

_PUBLIC_STATUS_KEYS: Final = frozenset(
    {
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
)
_WAN_COUNTER_KEYS: Final = frozenset(
    {
        "wan_bytes_received",
        "wan_bytes_sent",
        "wan_discarded_packets_received",
        "wan_discarded_packets_sent",
        "wan_download_rate",
        "wan_download_utilization",
        "wan_errors_received",
        "wan_errors_sent",
        "wan_interface",
        "wan_interface_enabled",
        "wan_interface_status",
        "wan_fastest_proven_interval",
        "wan_last_sample",
        "wan_packets_received",
        "wan_packets_sent",
        "wan_polling_interval",
        "wan_polling_mode",
        "wan_polling_state",
        "wan_upload_rate",
        "wan_upload_utilization",
    }
)
_TOTR64_KEYS: Final = frozenset(
    {
        "dsl_attainable_downstream",
        "dsl_attainable_upstream",
        "dsl_attenuation_downstream",
        "dsl_attenuation_upstream",
        "dsl_snr_downstream",
        "dsl_snr_upstream",
    }
)
_INTEGRATION_KEYS: Final = frozenset(
    {
        "capture_read_only_inventory",
        "last_successful_update",
        "management_access",
        "request_latency",
        "retry_protected_data",
        "router_problem",
        "update_failures",
    }
)
_NON_MUTATING_BUTTON_KEYS: Final = frozenset(
    {
        "capture_read_only_inventory",
        "retry_protected_data",
    }
)
_CHILD_SECTIONS: Final = {
    "client": "clients",
    "dect_handset": "telephony",
    "dect_repeater": "telephony",
    "ip_phone": "telephony",
    "mesh_node": "wireless",
    "powerline_node": "clients",
    "receiver": "mobile",
    "telephone_line": "telephony",
    "usb_device": "system",
}
_PROTECTED_READ_ONLY_GROUP_BY_KEY: Final = {
    # Public overview connection diagnostics. The group map is independent of
    # transport source; `_PUBLIC_STATUS_KEYS` keeps these browser-independent.
    "internet_bng_configured": "connection_internet",
    "internet_provisioning_code": "connection_internet",
    "internet_provider_family": "connection_internet",
    "internet_error_code": "connection_internet",
    # Internet privacy.
    "internet_privacy_level": "connection_privacy",
    # Public overview mobile state and receiver identity class.
    "mobile_connected": "mobile_connection",
    "mobile_status_code": "mobile_connection",
    "mobile_nr_signal": "mobile_signal",
    "mobile_lte_signal": "mobile_signal",
    "mobile_nr_band": "mobile_radio",
    "mobile_lte_band": "mobile_radio",
    # Wi-Fi radios, access policy, WPS, and schedule metadata.
    "wifi_enabled": "wireless_general",
    "wifi_band_mode": "wireless_radios",
    "wifi_2_4_encryption_mode": "wireless_2_4",
    "wifi_2_4_visible": "wireless_2_4",
    "wifi_5_visible": "wireless_5",
    "wifi_allow_all_devices": "wireless_access",
    "wifi_wps_state_code": "wireless_wps",
    "wifi_wps_enabled": "wireless_wps",
    "wifi_wps_disabled_by_firmware": "wireless_wps",
    "guest_wifi_wps_enabled": "wireless_wps",
    "wifi_schedule_mode": "wireless_schedule",
    "wifi_schedule_daily_from": "wireless_schedule",
    "wifi_schedule_daily_to": "wireless_schedule",
    "wifi_schedule_weekly": "wireless_schedule",
    "wifi_guest_encryption_mode": "wireless_guest",
    "wifi_office_encryption_mode": "wireless_office",
    # LAN and DHCP addressing summaries.
    "lan_ipv4_address": "clients_lan",
    "lan_subnet_mask": "clients_lan",
    "lan_ipv6_enabled": "clients_lan",
    "dhcp_pool_size": "clients_dhcp",
    # DDNS status.
    "ddns_provider": "system_ddns",
    "ddns_status": "system_ddns",
    # External mobile receiver status and firmware.
    "receiver_mode": "mobile_receiver_status",
    "receiver_model": "mobile_receiver_status",
    "receiver_esim_supported": "mobile_receiver_status",
    "receiver_external_wan_link": "mobile_receiver_status",
    "receiver_led_mode": "mobile_receiver_status",
    "receiver_external_modem_enabled": "mobile_receiver_status",
    "receiver_lte_enabled": "mobile_receiver_status",
    "receiver_firmware_version": "mobile_receiver_firmware",
    "receiver_latest_firmware": "mobile_receiver_firmware",
    "receiver_firmware_update_time": "mobile_receiver_firmware",
    "receiver_firmware_automatic_updates": "mobile_receiver_firmware",
    "receiver_firmware_update_available": "mobile_receiver_firmware",
    "receiver_firmware_update_planned": "mobile_receiver_firmware",
    # USB, tethering, and NAS/storage summaries.
    "usb_port_enabled": "system_usb",
    "usb_printer_connected": "system_usb",
    "usb_tethering_status": "system_usb_tethering",
    "usb_tethering_enabled": "system_usb_tethering",
    "usb_tethering_connected": "system_usb_tethering",
    "usb_storage_devices": "system_nas",
    "usb_storage_total": "system_nas",
    "usb_storage_used": "system_nas",
    "usb_storage_free": "system_nas",
    "media_server_folders": "system_usb",
    "media_server_active_folders": "system_usb",
    "nas_enabled": "system_nas",
    "nas_secure": "system_nas",
    "nas_read_only": "system_nas",
    # Network security configuration summaries.
    "firewall_enabled": "system_security",
    "dns_rebind_protection": "system_security",
    "router_https_enabled": "system_security",
    "dns_rebind_exceptions": "system_security_dns",
    "port_block_rules": "system_security_port_block",
    "active_port_block_rules": "system_security_port_block",
    "port_blocking_enabled": "system_security_port_block",
    "qos_prioritized_clients": "system_security_qos",
    # DECT, PBX, and VoIP summaries.
    "dect_repeaters": "telephony_dect",
    "phonebook_entries": "telephony_phonebooks",
    "dect_scan_active": "telephony_dect",
    "dect_smart_home_enabled": "telephony_dect",
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
    "telephony_voip_possible": "telephony_voip",
    # Router firmware and support status.
    "system_operating_mode": "system_health",
    "settings_write_blocked": "system_health",
    "device_password_changed": "system_health",
    "initial_setup_completed": "system_health",
    "firmware_update_time": "system_firmware",
    "firmware_update_planned": "system_firmware",
    "firmware_automatic_updates": "system_firmware",
    "remote_support_active": "system_support",
    "easy_support_enabled": "system_support",
}


class _ChildDevicePanelData(TypedDict):
    """Permission-scoped child-device metadata exposed to the panel."""

    device_id: str
    kind: str
    name: str
    model: str | None


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register static assets, metadata API, and one global sidebar panel."""
    panel_state: dict[str, bool] = hass.data.setdefault(_PANEL_DATA_KEY, {})

    if not panel_state.get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _STATIC_URL,
                    str(_FRONTEND_DIR),
                    cache_headers=False,
                )
            ]
        )
        panel_state["static_registered"] = True

    if not panel_state.get("websocket_registered"):
        websocket_api.async_register_command(hass, websocket_panel_info)
        websocket_api.async_register_command(hass, websocket_panel_admin_read)
        panel_state["websocket_registered"] = True

    if panel_state.get("panel_owned"):
        return

    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        _LOGGER.warning(
            "Cannot register Speedport Smart panel: sidebar path %s is already used",
            PANEL_URL_PATH,
        )
        return

    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT_NAME,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=(f"{_STATIC_URL}/{_FRONTEND_FILE}?schema={PANEL_SCHEMA_VERSION}"),
        embed_iframe=False,
        trust_external=False,
        config={"schema_version": PANEL_SCHEMA_VERSION},
        require_admin=False,
    )
    panel_state["panel_owned"] = True


def async_unregister_panel(hass: HomeAssistant) -> None:
    """
    Remove only the panel owned by this integration.

    Static routes and WebSocket commands intentionally remain process-scoped because
    Home Assistant does not provide supported unregister APIs for them. Config-entry
    reloads should therefore leave the global panel registered.
    """
    panel_state: dict[str, bool] | None = hass.data.get(_PANEL_DATA_KEY)
    if not panel_state or not panel_state.get("panel_owned"):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    panel_state["panel_owned"] = False


@websocket_command({vol.Required("type"): _PANEL_WS_TYPE})
@callback
def websocket_panel_info(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return permission-filtered panel metadata without router I/O."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    routers = []
    for entry in sorted(
        hass.config_entries.async_entries(DOMAIN),
        key=lambda candidate: candidate.title.casefold(),
    ):
        router = _entry_panel_data(
            entry,
            connection,
            entity_registry,
            device_registry,
        )
        if router is not None:
            routers.append(router)

    connection.send_result(
        msg["id"],
        {
            "schema_version": PANEL_SCHEMA_VERSION,
            "routers": routers,
        },
    )


@websocket_command(
    {
        vol.Required("type"): _PANEL_ADMIN_READ_WS_TYPE,
        vol.Required("entry_id"): str,
    }
)
@require_admin
@callback
def websocket_panel_admin_read(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return an administrator-only projection of cached normalized lists."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            "entry_not_found",
            "Speedport Smart config entry not found",
        )
        return
    if entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"],
            "entry_not_loaded",
            "Speedport Smart config entry is not loaded",
        )
        return
    hub = _loaded_hub(entry)
    if hub is None:
        connection.send_error(
            msg["id"],
            "entry_not_loaded",
            "Speedport Smart config entry is not loaded",
        )
        return
    connection.send_result(
        msg["id"],
        admin_read_payload(hub.data, entry_id=entry.entry_id),
    )


def _entry_panel_data(
    entry: ConfigEntry[Any],
    connection: ActiveConnection,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> dict[str, Any] | None:
    """Build one config entry's local UI model."""
    entities = []
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.disabled_by is not None or not _can_read_entity(
            connection, entity_entry.entity_id
        ):
            continue
        entities.append(
            _entity_panel_data(
                entity_entry,
                _child_device_panel_data(entity_entry, device_registry),
                connection,
            )
        )
    entities.sort(key=_entity_panel_sort_key)

    if not entities and not connection.user.is_admin:
        return None

    hub = _loaded_hub(entry)
    model: str | None = None
    capabilities: list[str] = []
    management: dict[str, Any] | None = None
    access_sources: list[dict[str, Any]] = []
    capability_families: list[dict[str, str]] = []
    if hub is not None:
        model = hub.router_identity.model
        source_data, family_data = _capability_panel_data(hub)
        if connection.user.is_admin:
            capabilities = sorted(hub.capabilities)
            management = _management_panel_data(hub)
            access_sources = source_data
            capability_families = family_data
        else:
            access_sources = _permission_scoped_access_sources(source_data, entities)
            if any(
                entity["translation_key"] == "management_access" for entity in entities
            ):
                management = _management_panel_data(hub)

    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "model": model,
        "entry_state": entry.state.value,
        "management": management,
        "access_sources": access_sources,
        "capabilities": capabilities,
        "capability_families": capability_families,
        "entities": entities,
    }


def _permission_scoped_access_sources(
    access_sources: list[dict[str, Any]], entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Expose source health only for entity families the user may read."""
    readable_sources = {str(entity["access_source"]) for entity in entities}
    return [
        source
        for source in access_sources
        if str(source.get("id", "")) in readable_sources
    ]


def _loaded_hub(entry: ConfigEntry[Any]) -> SpeedportHub | None:
    """Return runtime data only for a loaded entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not hasattr(runtime_data, "capability_report"):
        return None
    return cast("SpeedportHub", runtime_data)


def _entity_panel_data(
    entity_entry: er.RegistryEntry,
    child_device: _ChildDevicePanelData | None,
    connection: ActiveConnection,
) -> dict[str, Any]:
    """Return stable display metadata for one supported entity."""
    entity_id = entity_entry.entity_id
    entity_domain = entity_id.partition(".")[0]
    translation_key = entity_entry.translation_key or entity_id.partition(".")[2]
    child_kind = child_device["kind"] if child_device is not None else None
    protected_read_only = translation_key in _PROTECTED_READ_ONLY_GROUP_BY_KEY
    write_contract = (
        get_entity_write_contract(entity_domain, translation_key)
        if entity_entry.translation_key is not None
        else None
    )
    is_non_mutating_control = (
        entity_domain == "button"
        and entity_entry.translation_key in _NON_MUTATING_BUTTON_KEYS
    )
    supports_control = not protected_read_only and (
        is_non_mutating_control or write_contract is not None
    )
    is_control = supports_control and _can_control_entity(
        connection,
        entity_id,
    )
    access_source = _access_source_for_entity(
        translation_key,
        entity_domain,
        child_kind,
        is_control=is_control,
    )
    panel_data: dict[str, Any] = {
        "entity_id": entity_id,
        "domain": entity_domain,
        "translation_key": translation_key,
        "entity_category": (
            str(entity_entry.entity_category)
            if entity_entry.entity_category is not None
            else None
        ),
        "section": (
            "controls"
            if is_control
            else _section_for_entity(translation_key, entity_domain, child_kind)
        ),
        "access_source": access_source,
        "control": is_control,
        "mutates_router": is_control and write_contract is not None,
        "risk": write_contract.risk.value if write_contract is not None else "normal",
        "confirmation": (
            write_contract.confirmation.value
            if write_contract is not None
            else "confirm"
        ),
        "disruptive": write_contract is not None
        and write_contract.risk
        in {
            ManagementRisk.DISRUPTIVE,
            ManagementRisk.LOCKOUT,
            ManagementRisk.DESTRUCTIVE,
        },
    }
    if capability_group := _PROTECTED_READ_ONLY_GROUP_BY_KEY.get(translation_key):
        panel_data["capability_group"] = capability_group
    if entity_entry.name:
        panel_data["custom_name"] = entity_entry.name
    if child_device is not None:
        panel_data["child_device"] = child_device
    return panel_data


def _entity_panel_sort_key(entity: dict[str, Any]) -> tuple[str, int, str, str, str]:
    """Keep router summaries first, then child entities grouped by display name."""
    child_device = entity.get("child_device")
    if isinstance(child_device, Mapping):
        child_order = 1
        child_name = str(child_device.get("name", "")).casefold()
    else:
        child_order = 0
        child_name = ""
    return (
        str(entity["section"]),
        child_order,
        child_name,
        str(entity["translation_key"]),
        str(entity["entity_id"]),
    )


def _section_for_entity(
    translation_key: str,
    entity_domain: str,
    child_kind: str | None,
) -> str:
    """Group an entity using stable semantic keys, never display names."""
    if child_kind is not None:
        return _CHILD_SECTIONS.get(child_kind, "system")
    key = translation_key.casefold()
    if entity_domain == "device_tracker" or key.startswith(
        ("client_", "connected_clients", "dhcp_", "lan_")
    ):
        return "clients"
    if key.startswith("lte_tunnel_"):
        return "mobile"
    if key.startswith("wan_"):
        return "bandwidth"
    if key.startswith(("internet_", "public_ipv")) or key == "internet_connected":
        return "connection"
    if key.startswith("dsl_") or key == "dsl_connected":
        return "dsl"
    if key.startswith(("hybrid_", "mobile_", "receiver_", "lte_", "5g_")):
        return "mobile"
    if key.startswith(("wifi_", "guest_wifi", "office_wifi", "mesh_", "wps")):
        return "wireless"
    if key.startswith(("port_forward", "nat_", "upnp_")):
        return "clients"
    if key.startswith(
        (
            "telephone_",
            "telephony_",
            "active_call",
            "missed_call",
            "last_call",
            "ip_phone",
            "dect_",
            "pbx_",
            "phonebook",
        )
    ):
        return "telephony"
    if key in {
        "last_successful_update",
        "management_access",
        "request_latency",
        "router_problem",
        "update_failures",
    }:
        return "management"
    return "system"


def _access_source_for_entity(
    translation_key: str,
    entity_domain: str,
    child_kind: str | None,
    *,
    is_control: bool,
) -> str:
    """Classify whether an entity survives a competing browser session."""
    key = translation_key.casefold()
    if key in _INTEGRATION_KEYS:
        return "integration"
    if is_control:
        return "router_control"
    if child_kind is not None or entity_domain == "device_tracker":
        return "protected_json"
    if key in _PUBLIC_STATUS_KEYS:
        return "public_status"
    if key in _PROTECTED_READ_ONLY_GROUP_BY_KEY:
        return "protected_json"
    if key in _WAN_COUNTER_KEYS:
        return "wan_counters"
    if key in _TOTR64_KEYS:
        return "totr64"
    return "protected_json"


def _child_device_panel_data(
    entity_entry: er.RegistryEntry,
    device_registry: dr.DeviceRegistry,
) -> _ChildDevicePanelData | None:
    """Return safe registry metadata only for an integration child device."""
    if entity_entry.device_id is None:
        return None
    device = device_registry.async_get(entity_entry.device_id)
    if device is None or device.via_device_id is None:
        return None
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        _router, separator, child = identifier.partition(":")
        if not separator:
            continue
        kind, separator, _identifier = child.partition(":")
        if separator and kind:
            return {
                "device_id": device.id,
                "kind": kind,
                "name": str(device.name_by_user or device.name or kind),
                "model": str(device.model) if device.model is not None else None,
            }
    return None


def _can_read_entity(connection: ActiveConnection, entity_id: str) -> bool:
    """Respect the connected Home Assistant user's entity permissions."""
    user = connection.user
    permissions = user.permissions
    return permissions.access_all_entities(POLICY_READ) or permissions.check_entity(
        entity_id, POLICY_READ
    )


def _can_control_entity(connection: ActiveConnection, entity_id: str) -> bool:
    """Return whether the connected Home Assistant user may control an entity."""
    user = connection.user
    permissions = user.permissions
    return permissions.access_all_entities(POLICY_CONTROL) or permissions.check_entity(
        entity_id, POLICY_CONTROL
    )


def _management_panel_data(hub: SpeedportHub) -> dict[str, Any]:
    """Return actionable management state without owner or credential data."""
    value: object = hub.get("management.access", {})
    if not isinstance(value, Mapping):
        return {
            "state": "unavailable",
            "browser_logout_required": False,
            "controls_available": False,
            "retry_after_seconds": None,
            "last_successful_update": None,
        }
    return {
        "state": value.get("state", "unknown"),
        "browser_logout_required": bool(value.get("browser_logout_required", False)),
        "controls_available": hub.management_controls_available,
        "retry_after_seconds": value.get("retry_after_seconds"),
        "last_successful_update": value.get("last_successful_update"),
    }


def _empty_access_sources() -> list[dict[str, Any]]:
    """Return stable unavailable source cards for an unloaded entry."""
    return [
        {
            "id": "public_status",
            "label": "Browser-independent status",
            "supported": False,
            "available": False,
        },
        {
            "id": "protected_json",
            "label": "Protected router data",
            "supported": False,
            "available": False,
        },
        {
            "id": "totr64",
            "label": "TR-064 line data",
            "supported": False,
            "available": False,
        },
        {
            "id": "wan_counters",
            "label": "Live WAN counters",
            "supported": False,
            "available": False,
        },
    ]


def _capability_panel_data(
    hub: SpeedportHub,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Group proven capability families by their non-mutating access source."""
    report = hub.capability_report
    if report is None:
        return _empty_access_sources(), []

    diagnostics = hub.diagnostics()
    endpoint_errors = hub.endpoint_errors
    wan_telemetry = hub.wan_counter_telemetry
    polling = diagnostics.get("polling", {})
    fast_available = _poll_group_available(polling, "fast")
    normal_available = _poll_group_available(polling, "normal")
    slow_available = _poll_group_available(polling, "slow")
    management: Any = hub.get("management.access", {})
    management_available = (
        isinstance(management, Mapping) and management.get("state") == "available"
    )
    public_supported = hub.has_capability("status")
    protected_supported = hub.has_capability("authenticated_json")
    totr64_supported = hub.has_capability("dsl_metrics")
    wan_supported = hub.has_capability("wan_counters")
    access_sources = [
        {
            "id": "public_status",
            "label": "Browser-independent status",
            "supported": public_supported,
            "available": public_supported and fast_available,
        },
        {
            "id": "protected_json",
            "label": "Protected router data",
            "supported": protected_supported,
            "available": (
                protected_supported
                and management_available
                and normal_available
                and slow_available
            ),
        },
        {
            "id": "totr64",
            "label": "TR-064 line data",
            "supported": totr64_supported,
            "available": (
                totr64_supported
                and normal_available
                and "dsl_metrics" not in endpoint_errors
            ),
        },
        {
            "id": "wan_counters",
            "label": "Live WAN counters",
            "supported": wan_supported,
            "polling_available": fast_available,
            "available": (
                wan_supported
                and fast_available
                and "wan_counters" not in endpoint_errors
            ),
            "effective_interval_seconds": wan_telemetry.get(
                "effective_interval_seconds"
            ),
            "mode": wan_telemetry.get("mode"),
            "state": wan_telemetry.get("state"),
            "target_interval_seconds": wan_telemetry.get("target_interval_seconds"),
            "runtime_floor_seconds": wan_telemetry.get("runtime_floor_seconds"),
            "last_stable_interval_seconds": wan_telemetry.get(
                "last_stable_interval_seconds"
            ),
            "retrying": wan_telemetry.get("retrying", False),
            "retry_in_seconds": wan_telemetry.get("retry_in_seconds"),
            "last_sampled_at": wan_telemetry.get("last_sampled_at"),
        },
    ]
    families = []
    for name, capability in sorted(report.feature_endpoints.items()):
        if capability.endpoint == "data/Status.json":
            source = "public_status"
        elif capability.authenticated:
            source = "protected_json"
        else:
            source = "public_json"
        families.append({"name": str(name), "source": source})
    return access_sources, families


def _poll_group_available(polling: object, group: str) -> bool:
    """Return current coordinator health from the UI-safe diagnostic snapshot."""
    if not isinstance(polling, Mapping):
        return False
    group_state = polling.get(group)
    return isinstance(group_state, Mapping) and group_state.get("available") is True
