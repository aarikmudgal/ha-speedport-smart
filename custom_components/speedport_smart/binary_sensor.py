"""Capability-gated binary sensors for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .coordinator import PollGroup
from .entity import SpeedportDevice, SpeedportEntity
from .platform_helpers import (
    as_bool,
    as_wps_active,
    child_collection,
    child_item,
    coordinator,
    speedport_child_device,
    stable_id,
    supported,
    value,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


@dataclass(frozen=True, kw_only=True)
class SpeedportBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a normalized Speedport binary sensor."""

    data_path: str
    capability: str | tuple[str, ...]
    coordinator_group: PollGroup


@dataclass(frozen=True, slots=True)
class SpeedportChildBinarySensorDescription:
    """Describe one optional boolean field on a router child device."""

    key: str
    name: str
    field: str
    device_class: BinarySensorDeviceClass | None = None


@dataclass(frozen=True, slots=True)
class SpeedportChildBinarySensorCollection:
    """Describe one normalized collection of router child devices."""

    kind: str
    data_paths: tuple[str, ...]
    coordinator_group: PollGroup
    fields: tuple[SpeedportChildBinarySensorDescription, ...]


FAST = PollGroup.FAST
NORMAL = PollGroup.NORMAL
SLOW = PollGroup.SLOW

_CONNECTED = SpeedportChildBinarySensorDescription(
    key="connected",
    name="Connected",
    field="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)
_ACTIVE_CALL = SpeedportChildBinarySensorDescription(
    key="active_call",
    name="Active call",
    field="active_call",
    device_class=BinarySensorDeviceClass.RUNNING,
)

CHILD_BINARY_SENSOR_COLLECTIONS: tuple[SpeedportChildBinarySensorCollection, ...] = (
    SpeedportChildBinarySensorCollection(
        kind="client",
        data_paths=("clients.items",),
        coordinator_group=NORMAL,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="internet_paused",
                name="Internet paused",
                field="internet_paused",
            ),
            SpeedportChildBinarySensorDescription(
                key="internet_access_allowed",
                name="Internet access allowed",
                field="internet_access_allowed",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            SpeedportChildBinarySensorDescription(
                key="uses_dhcp",
                name="Uses DHCP",
                field="uses_dhcp",
            ),
            SpeedportChildBinarySensorDescription(
                key="web_interface_available",
                name="Web interface available",
                field="has_web_ui",
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="mesh_node",
        data_paths=("mesh.nodes",),
        coordinator_group=NORMAL,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="mesh_wifi_enabled",
                name="Mesh Wi-Fi",
                field="wifi_enabled",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="telephone_line",
        data_paths=("telephony.numbers",),
        coordinator_group=NORMAL,
        fields=(
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            SpeedportChildBinarySensorDescription(
                key="enabled",
                name="Enabled",
                field="enabled",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
            _ACTIVE_CALL,
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="dect_handset",
        data_paths=("dect.handsets",),
        coordinator_group=SLOW,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            _ACTIVE_CALL,
            SpeedportChildBinarySensorDescription(
                key="charging",
                name="Charging",
                field="charging",
                device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
            ),
            SpeedportChildBinarySensorDescription(
                key="paging",
                name="Paging",
                field="paging",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="dect_repeater",
        data_paths=("dect.repeaters",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="ip_phone",
        data_paths=("pbx.ip_phones",),
        coordinator_group=SLOW,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            _ACTIVE_CALL,
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="usb_device",
        data_paths=("usb.items",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildBinarySensorDescription(
                key="connected",
                name="Connected",
                field="connected",
                device_class=BinarySensorDeviceClass.PLUG,
            ),
            SpeedportChildBinarySensorDescription(
                key="mounted",
                name="Mounted",
                field="mounted",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="receiver",
        data_paths=("receiver.items", "receiver"),
        coordinator_group=NORMAL,
        fields=(_CONNECTED,),
    ),
)

BINARY_SENSOR_DESCRIPTIONS: tuple[SpeedportBinarySensorEntityDescription, ...] = (
    SpeedportBinarySensorEntityDescription(
        key="internet_connected",
        translation_key="internet_connected",
        data_path="internet.state",
        capability="internet",
        coordinator_group=FAST,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="internet_bng_configured",
        translation_key="internet_bng_configured",
        data_path="internet.bng_configured",
        capability="internet",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dsl_connected",
        translation_key="dsl_connected",
        data_path="dsl.state",
        capability="dsl",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="hybrid_connected",
        translation_key="hybrid_connected",
        data_path="hybrid.connected",
        capability="hybrid",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="hybrid_enabled",
        translation_key="hybrid_enabled",
        data_path="hybrid.enabled",
        capability="hybrid",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="hybrid_dsl_tunnel",
        translation_key="hybrid_dsl_tunnel",
        data_path="hybrid.dsl_tunnel",
        capability="hybrid",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="hybrid_lte_tunnel",
        translation_key="hybrid_lte_tunnel",
        data_path="hybrid.lte_tunnel",
        capability="hybrid",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="mobile_connected",
        translation_key="mobile_connected",
        data_path="mobile.connected",
        capability="mobile",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_external_modem_enabled",
        translation_key="receiver_external_modem_enabled",
        data_path="receiver.external_modem_enabled",
        capability="receiver",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_external_wan_link",
        translation_key="receiver_external_wan_link",
        data_path="receiver.external_wan_link",
        capability="receiver",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_esim_supported",
        translation_key="receiver_esim_supported",
        data_path="receiver.esim_supported",
        capability="receiver",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_lte_enabled",
        translation_key="receiver_lte_enabled",
        data_path="receiver.lte_enabled",
        capability="receiver",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_firmware_automatic_updates",
        translation_key="receiver_firmware_automatic_updates",
        data_path="receiver.firmware_auto_update",
        capability="receiver",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_firmware_update_available",
        translation_key="receiver_firmware_update_available",
        data_path="receiver.firmware_update_available",
        capability="receiver",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="receiver_firmware_update_planned",
        translation_key="receiver_firmware_update_planned",
        data_path="receiver.firmware_update_planned",
        capability="receiver",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_enabled",
        translation_key="wifi_enabled",
        data_path="wifi.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_2_4_enabled",
        translation_key="wifi_2_4_enabled",
        data_path="wifi.radio_2_4.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_5_enabled",
        translation_key="wifi_5_enabled",
        data_path="wifi.radio_5.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="guest_wifi_enabled",
        translation_key="guest_wifi_enabled",
        data_path="wifi.guest.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="office_wifi_enabled",
        translation_key="office_wifi_enabled",
        data_path="wifi.office.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_wps_active",
        translation_key="wifi_wps_active",
        data_path="wifi.wps_status",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_mac_filter_enabled",
        translation_key="wifi_mac_filter_enabled",
        data_path="wifi.mac_filter_enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_schedule_enabled",
        translation_key="wifi_schedule_enabled",
        data_path="wifi.schedule_enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_wps_enabled",
        translation_key="wifi_wps_enabled",
        data_path="wifi.wps_enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_wps_disabled_by_firmware",
        translation_key="wifi_wps_disabled_by_firmware",
        data_path="wifi.wps_disabled_by_firmware",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_allow_all_devices",
        translation_key="wifi_allow_all_devices",
        data_path="wifi.allow_all_devices",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_2_4_visible",
        translation_key="wifi_2_4_visible",
        data_path="wifi.radio_2_4.visible",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_5_visible",
        translation_key="wifi_5_visible",
        data_path="wifi.radio_5.visible",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="guest_wifi_wps_enabled",
        translation_key="guest_wifi_wps_enabled",
        data_path="wifi.guest.wps_enabled",
        capability="wifi",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="guest_wifi_display_key_enabled",
        translation_key="guest_wifi_display_key_enabled",
        data_path="wifi.guest.display_key_enabled",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="office_wifi_wps_enabled",
        translation_key="office_wifi_wps_enabled",
        data_path="wifi.office.wps_enabled",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="mesh_enabled",
        translation_key="mesh_enabled",
        data_path="mesh.enabled",
        capability="mesh",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dhcp_enabled",
        translation_key="dhcp_enabled",
        data_path="dhcp.enabled",
        capability="dhcp",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="lan_ipv6_enabled",
        translation_key="lan_ipv6_enabled",
        data_path="lan.ipv6_enabled",
        capability="lan",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dsl_modem_lan_link",
        translation_key="dsl_modem_lan_link",
        data_path="dsl.modem_lan_link",
        capability=("lan", "dsl"),
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        SpeedportBinarySensorEntityDescription(
            key=f"lan_port_{port}_connected",
            translation_key=f"lan_port_{port}_connected",
            data_path=f"lan.ports.port_{port}.connected",
            capability="lan",
            coordinator_group=NORMAL,
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for port in range(1, 5)
    ),
    SpeedportBinarySensorEntityDescription(
        key="upnp_enabled",
        translation_key="upnp_enabled",
        data_path="nat.upnp_enabled",
        capability="nat",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="port_forwarding_enabled",
        translation_key="port_forwarding_enabled",
        data_path="nat.port_forwarding_enabled",
        capability="nat",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="ddns_enabled",
        translation_key="ddns_enabled",
        data_path="ddns.enabled",
        capability="ddns",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="ddns_connected",
        translation_key="ddns_connected",
        data_path="ddns.connected",
        capability="ddns",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="vpn_connected",
        translation_key="vpn_connected",
        data_path="vpn.connected",
        capability="vpn",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="vpn_enabled",
        translation_key="vpn_enabled",
        data_path="vpn.enabled",
        capability="vpn",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="parental_controls_enabled",
        translation_key="parental_controls_enabled",
        data_path="parental.enabled",
        capability="parental",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="telephony_registered",
        translation_key="telephony_registered",
        data_path="telephony.registered",
        capability="telephony",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="active_call",
        translation_key="active_call",
        data_path="telephony.active_call",
        capability="telephony",
        coordinator_group=FAST,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    SpeedportBinarySensorEntityDescription(
        key="telephony_voip_possible",
        translation_key="telephony_voip_possible",
        data_path="telephony.voip_possible",
        capability="telephony",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="telephony_hd_voice_active",
        translation_key="telephony_hd_voice_active",
        data_path="telephony.hd_voice_active",
        capability="telephony",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="telephony_manual_configuration_available",
        translation_key="telephony_manual_configuration_available",
        data_path="telephony.manual_configuration_available",
        capability="telephony",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dect_enabled",
        translation_key="dect_enabled",
        data_path="dect.enabled",
        capability="dect",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dect_scan_active",
        translation_key="dect_scan_active",
        data_path="dect.scan_active",
        capability="dect",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dect_paging_active",
        translation_key="dect_paging_active",
        data_path="dect.paging_active",
        capability="dect",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dect_smart_home_enabled",
        translation_key="dect_smart_home_enabled",
        data_path="dect.smart_home_enabled",
        capability="dect",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="smarthome_linked",
        translation_key="smarthome_linked",
        data_path="smarthome.linked",
        capability="system",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="pbx_enabled",
        translation_key="pbx_enabled",
        data_path="pbx.enabled",
        capability="pbx",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firewall_enabled",
        translation_key="firewall_enabled",
        data_path="security.firewall_enabled",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dns_rebind_protection",
        translation_key="dns_rebind_protection",
        data_path="security.dns_rebind_protection",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="remote_management",
        translation_key="remote_management",
        data_path="security.remote_management",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="router_https_enabled",
        translation_key="router_https_enabled",
        data_path="security.router_https_enabled",
        capability="security",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="port_blocking_enabled",
        translation_key="port_blocking_enabled",
        data_path="security.port_blocking_enabled",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_connected",
        translation_key="usb_connected",
        data_path="usb.connected",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.PLUG,
    ),
    SpeedportBinarySensorEntityDescription(
        key="media_server_enabled",
        translation_key="media_server_enabled",
        data_path="usb.media_server_enabled",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_port_enabled",
        translation_key="usb_port_enabled",
        data_path="usb.port_enabled",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_tethering_enabled",
        translation_key="usb_tethering_enabled",
        data_path="usb.tethering_enabled",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_tethering_connected",
        translation_key="usb_tethering_connected",
        data_path="usb.tethering_connected",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_printer_connected",
        translation_key="usb_printer_connected",
        data_path="usb.printer_connected",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.PLUG,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wan_interface_enabled",
        translation_key="wan_interface_enabled",
        data_path="wan.interface.enabled",
        capability="wan",
        coordinator_group=FAST,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firmware_update_available",
        translation_key="firmware_update_available",
        data_path="system.update_available",
        capability="system",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firmware_update_planned",
        translation_key="firmware_update_planned",
        data_path="system.update_planned",
        capability="system",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firmware_automatic_updates",
        translation_key="firmware_automatic_updates",
        data_path="system.automatic_updates_enabled",
        capability="system",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="remote_support_active",
        translation_key="remote_support_active",
        data_path="system.remote_support_active",
        capability="system",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="easy_support_enabled",
        translation_key="easy_support_enabled",
        data_path="system.easy_support_enabled",
        capability="system",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="settings_write_blocked",
        translation_key="settings_write_blocked",
        data_path="system.settings_write_blocked",
        capability="system",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="device_password_changed",
        translation_key="device_password_changed",
        data_path="system.device_password_changed",
        capability="system",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="initial_setup_completed",
        translation_key="initial_setup_completed",
        data_path="system.initial_setup_completed",
        capability="system",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="router_problem",
        translation_key="router_problem",
        data_path="diagnostics.problem",
        capability="diagnostics",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _discoverable_fixed_binary_sensor_descriptions(
    hub: SpeedportHub,
    group: PollGroup,
    known: set[str],
) -> tuple[SpeedportBinarySensorEntityDescription, ...]:
    """Return newly supported fixed binary sensors for one polling group."""
    return tuple(
        description
        for description in BINARY_SENSOR_DESCRIPTIONS
        if description.coordinator_group is group
        and description.key not in known
        and supported(hub, description.capability, description.data_path)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up supported binary sensors."""
    del hass
    hub = entry.runtime_data
    known_fixed: set[str] = set()

    @callback
    def discover_fixed_binary_sensors(group: PollGroup) -> None:
        descriptions = _discoverable_fixed_binary_sensor_descriptions(
            hub, group, known_fixed
        )
        if not descriptions:
            return
        known_fixed.update(description.key for description in descriptions)
        async_add_entities(
            SpeedportBinarySensor(hub, description) for description in descriptions
        )

    for group in {
        description.coordinator_group for description in BINARY_SENSOR_DESCRIPTIONS
    }:
        discover_fixed_binary_sensors(group)

        @callback
        def rediscover_fixed(group: PollGroup = group) -> None:
            discover_fixed_binary_sensors(group)

        entry.async_on_unload(
            coordinator(hub, group).async_add_listener(rediscover_fixed)
        )

    known: set[tuple[str, str, str]] = set()

    @callback
    def discover_child_binary_sensors(group: PollGroup) -> None:
        new_entities: list[SpeedportChildBinarySensor] = []
        for child_spec in CHILD_BINARY_SENSOR_COLLECTIONS:
            if child_spec.coordinator_group is not group:
                continue
            for item in child_collection(hub, child_spec.data_paths):
                identifier = stable_id(item)
                if identifier is None:
                    continue
                for field in child_spec.fields:
                    marker = (child_spec.kind, identifier, field.key)
                    if (
                        marker in known
                        or field.field not in item
                        or item[field.field] is None
                    ):
                        continue
                    device = speedport_child_device(child_spec.kind, item)
                    if device is None:
                        continue
                    known.add(marker)
                    new_entities.append(
                        SpeedportChildBinarySensor(
                            hub,
                            child_spec,
                            field,
                            identifier,
                            device,
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    for group in {spec.coordinator_group for spec in CHILD_BINARY_SENSOR_COLLECTIONS}:
        discover_child_binary_sensors(group)

        @callback
        def rediscover(group: PollGroup = group) -> None:
            discover_child_binary_sensors(group)

        entry.async_on_unload(coordinator(hub, group).async_add_listener(rediscover))


class SpeedportBinarySensor(SpeedportEntity, BinarySensorEntity):
    """Binary sensor backed by normalized hub data."""

    _attr_entity_registry_enabled_default = True
    entity_description: SpeedportBinarySensorEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportBinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return normalized boolean state."""
        transform = (
            as_wps_active
            if self.entity_description.key == "wifi_wps_active"
            else as_bool
        )
        return value(self.hub, self.entity_description.data_path, transform)

    @property
    def available(self) -> bool:
        """Hide live WAN interface state while its ToTR64 source is degraded."""
        if not super().available:
            return False
        if self.entity_description.key != "wan_interface_enabled":
            return True
        return not self.hub.has_endpoint_error("wan_counters")


class SpeedportChildBinarySensor(SpeedportEntity, BinarySensorEntity):
    """Enabled state sensor for one stable router child."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        hub: SpeedportHub,
        collection_spec: SpeedportChildBinarySensorCollection,
        description: SpeedportChildBinarySensorDescription,
        identifier: str,
        device: SpeedportDevice,
    ) -> None:
        """Initialize a boolean field-backed child sensor."""
        self._missing_child_means_off = (
            collection_spec.kind == "client" and description.key == "connected"
        )
        super().__init__(
            hub,
            coordinator(hub, collection_spec.coordinator_group),
            description.key,
            data_path=(
                collection_spec.data_paths[0] if self._missing_child_means_off else None
            ),
            device=device,
        )
        self._collection_spec = collection_spec
        self._field_description = description
        self._child_identifier = identifier
        self._attr_translation_key = description.key
        self._attr_device_class = description.device_class

    @property
    def _item(self) -> Mapping[str, Any] | None:
        """Return the current normalized child payload."""
        return child_item(
            self.hub,
            self._collection_spec.data_paths,
            self._child_identifier,
        )

    @property
    def available(self) -> bool:
        """Return whether this field remains available on the child."""
        if not super().available:
            return False
        item = self._item
        if item is None:
            return self._missing_child_means_off
        return (
            self._field_description.field in item
            and item[self._field_description.field] is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return the normalized current boolean field."""
        item = self._item
        if item is None:
            return False if self._missing_child_means_off else None
        raw = item.get(self._field_description.field)
        if raw is None:
            return None
        try:
            return as_bool(raw)
        except (TypeError, ValueError):
            return None
