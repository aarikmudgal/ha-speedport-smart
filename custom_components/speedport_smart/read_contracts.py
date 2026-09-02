"""
Explicit contracts for normalized fields exposed as native entities.

The registry is intentionally independent from the platform descriptions it
classifies. It does not create entities, fetch router data, or authorize writes.
Adding or changing a fixed native sensor requires an explicit contract update,
which makes accidental read-surface growth visible in review.

Collection-child entities, device-tracker attributes, update metadata, local
coordinator health, and the administrator-only structured projection are
separate surfaces and are deliberately outside this scalar registry.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class NativeReadPlatform(StrEnum):
    """Home Assistant platforms covered by normalized scalar contracts."""

    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"


@dataclass(frozen=True, slots=True)
class NativeScalarReadContract:
    """One exact normalized field exposed through a fixed native entity."""

    platform: NativeReadPlatform
    entity_key: str
    data_path: str
    capabilities: tuple[str, ...]


type NativeReadContractId = tuple[NativeReadPlatform, str]


def _group(
    platform: NativeReadPlatform,
    capabilities: tuple[str, ...],
    fields: Mapping[str, str],
) -> tuple[NativeScalarReadContract, ...]:
    """Build a compact group of contracts with identical capability gates."""
    return tuple(
        NativeScalarReadContract(
            platform=platform,
            entity_key=entity_key,
            data_path=data_path,
            capabilities=capabilities,
        )
        for entity_key, data_path in fields.items()
    )


def _build_registry(
    contracts: Iterable[NativeScalarReadContract],
) -> Mapping[NativeReadContractId, NativeScalarReadContract]:
    """Build an immutable exact registry and reject ambiguous declarations."""
    registry: dict[NativeReadContractId, NativeScalarReadContract] = {}
    paths: set[str] = set()
    for contract in contracts:
        contract_id = (contract.platform, contract.entity_key)
        if contract_id in registry:
            msg = f"Duplicate native read contract: {contract_id!r}"
            raise ValueError(msg)
        if contract.data_path in paths:
            msg = f"Duplicate native read path: {contract.data_path}"
            raise ValueError(msg)
        if (
            not contract.entity_key
            or not contract.data_path
            or not contract.capabilities
            or len(set(contract.capabilities)) != len(contract.capabilities)
        ):
            msg = f"Invalid native read contract: {contract_id!r}"
            raise ValueError(msg)
        registry[contract_id] = contract
        paths.add(contract.data_path)
    return MappingProxyType(registry)


_DECLARED_NATIVE_SCALAR_READ_CONTRACTS: Final = (
    *_group(
        NativeReadPlatform.SENSOR,
        ("wan",),
        {
            "wan_bytes_received": "wan.bytes_received",
            "wan_bytes_sent": "wan.bytes_sent",
            "wan_packets_received": "wan.packets_received",
            "wan_packets_sent": "wan.packets_sent",
            "wan_errors_received": "wan.errors_received",
            "wan_errors_sent": "wan.errors_sent",
            "wan_discarded_packets_received": "wan.discard_packets_received",
            "wan_discarded_packets_sent": "wan.discard_packets_sent",
            "wan_download_rate": "wan.download_rate_bps",
            "wan_upload_rate": "wan.upload_rate_bps",
            "wan_download_utilization": "wan.download_utilization",
            "wan_upload_utilization": "wan.upload_utilization",
            "wan_interface": "wan.interface.name",
            "wan_interface_status": "wan.interface.status",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("internet",),
        {
            "wan_download_capacity": "internet.download_capacity_bps",
            "wan_upload_capacity": "internet.upload_capacity_bps",
            "internet_uptime": "internet.uptime_seconds",
            "wan_mtu": "internet.mtu",
            "public_ipv4": "internet.ipv4_address",
            "public_ipv6_prefix": "internet.ipv6_prefix",
            "internet_ip_stack": "internet.ip_stack",
            "internet_privacy_level": "internet.privacy_level",
            "internet_provisioning_code": "internet.provisioning_code",
            "internet_provider_family": "internet.provider_family",
            "internet_error_code": "internet.error_code",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("dsl",),
        {
            "dsl_downstream": "dsl.downstream_bps",
            "dsl_upstream": "dsl.upstream_bps",
            "dsl_attainable_downstream": "dsl.attainable_downstream_bps",
            "dsl_attainable_upstream": "dsl.attainable_upstream_bps",
            "dsl_snr_downstream": "dsl.snr_downstream_db",
            "dsl_snr_upstream": "dsl.snr_upstream_db",
            "dsl_attenuation_downstream": "dsl.attenuation_downstream_db",
            "dsl_attenuation_upstream": "dsl.attenuation_upstream_db",
            "dsl_crc_errors": "dsl.crc_errors",
            "dsl_fec_errors": "dsl.fec_errors",
            "dsl_error_seconds": "dsl.error_seconds",
            "dsl_profile": "dsl.profile",
            "dsl_error_code": "dsl.error_code",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("mobile",),
        {
            "mobile_network_type": "mobile.network_type",
            "mobile_status_code": "mobile.status_code",
            "mobile_nr_signal": "mobile.nr.signal_dbm",
            "mobile_nr_band": "mobile.nr.band_code",
            "mobile_lte_signal": "mobile.lte.signal_dbm",
            "mobile_lte_band": "mobile.lte.band_code",
            "mobile_operator": "mobile.operator",
            "mobile_rsrp": "mobile.rsrp_dbm",
            "mobile_rsrq": "mobile.rsrq_db",
            "mobile_sinr": "mobile.sinr_db",
            "mobile_rssi": "mobile.rssi_dbm",
            "mobile_band": "mobile.band",
            "mobile_frequency": "mobile.frequency_mhz",
            "mobile_cell_id": "mobile.cell_id",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("receiver",),
        {
            "receiver_mode": "receiver.mode",
            "receiver_model": "receiver.model",
            "receiver_led_mode": "receiver.led_mode",
            "receiver_firmware_version": "receiver.firmware_version",
            "receiver_latest_firmware": "receiver.latest_firmware",
            "receiver_firmware_update_time": "receiver.firmware_update_time",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("hybrid",),
        {
            "lte_tunnel_bytes_received": "hybrid.lte_tunnel_bytes_received",
            "lte_tunnel_bytes_sent": "hybrid.lte_tunnel_bytes_sent",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("wifi",),
        {
            "wifi_2_4_clients": "wifi.radio_2_4.client_count",
            "wifi_5_clients": "wifi.radio_5.client_count",
            "wifi_guest_clients": "wifi.guest.client_count",
            "wifi_guest_2_4_clients": "wifi.guest.radio_2_4_client_count",
            "wifi_guest_5_clients": "wifi.guest.radio_5_client_count",
            "wifi_guest_wifi_4_clients": "wifi.guest.wifi_4_client_count",
            "wifi_guest_wifi_5_clients": "wifi.guest.wifi_5_client_count",
            "wifi_guest_wifi_6_clients": "wifi.guest.wifi_6_client_count",
            "wifi_office_clients": "wifi.office.client_count",
            "wifi_guest_remaining_time": "wifi.guest.remaining_minutes",
            "wifi_2_4_channel": "wifi.radio_2_4.channel",
            "wifi_5_channel": "wifi.radio_5.channel",
            "wifi_5_channel_width": "wifi.radio_5.channel_width_mode",
            "wifi_band_mode": "wifi.band_mode",
            "wifi_wps_state_code": "wifi.wps_state_code",
            "wifi_2_4_encryption_mode": "wifi.radio_2_4.encryption_mode",
            "wifi_5_encryption_mode": "wifi.radio_5.encryption_mode",
            "wifi_guest_encryption_mode": "wifi.guest.encryption_mode",
            "wifi_office_encryption_mode": "wifi.office.encryption_mode",
            "wifi_schedule_mode": "wifi.schedule.mode",
            "wifi_schedule_daily_from": "wifi.schedule.daily_from",
            "wifi_schedule_daily_to": "wifi.schedule.daily_to",
            "wifi_schedule_weekly": "wifi.schedule.weekly_day_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("mesh", "mesh_topology"),
        {
            "mesh_nodes": "mesh.nodes",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("mesh",),
        {
            "mesh_clients": "mesh.client_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("clients",),
        {
            "connected_clients": "clients.connected_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("dhcp",),
        {
            "dhcp_leases": "dhcp.leases",
            "dhcp_pool_size": "dhcp.pool_size",
            "dhcp_lease_duration_code": "dhcp.lease_duration_code",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("lan",),
        {
            "lan_linked_ports": "lan.linked_port_count",
            "lan_port_1_speed": "lan.ports.port_1.speed_bps",
            "lan_port_2_speed": "lan.ports.port_2.speed_bps",
            "lan_port_3_speed": "lan.ports.port_3.speed_bps",
            "lan_port_4_speed": "lan.ports.port_4.speed_bps",
            "lan_ipv4_address": "lan.ipv4_address",
            "lan_subnet_mask": "lan.subnet_mask",
            "lan_ula_address": "lan.ula_address",
            "lan_usable_ipv6_range": "lan.usable_ipv6_range",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("nat",),
        {
            "port_forward_rules": "nat.port_forward_rules",
            "upnp_mappings": "nat.upnp_mappings",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("ddns",),
        {
            "ddns_provider": "ddns.provider",
            "ddns_update_protocol": "ddns.update_protocol",
            "ddns_update_port": "ddns.update_port",
            "ddns_status": "ddns.status_code",
            "ddns_last_update": "ddns.last_update",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("vpn",),
        {
            "vpn_peers": "vpn.peers",
            "vpn_connected_peers": "vpn.connected_peer_count",
            "vpn_type": "vpn.type",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("parental",),
        {
            "parental_profiles": "parental.profiles",
            "parental_blocked_clients": "parental.blocked_client_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("security",),
        {
            "dns_rebind_exceptions": "security.dns_rebind_exception_count",
            "port_block_rules": "security.port_block_rule_count",
            "active_port_block_rules": "security.active_port_block_rule_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("qos",),
        {
            "qos_prioritized_clients": "qos.prioritized_client_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("telephony",),
        {
            "telephone_numbers_registered": "telephony.registered_number_count",
            "telephony_voip_policy": "telephony.voip_policy",
            "telephony_provisioning_code": "telephony.provisioning_code",
            "telephony_provider_family": "telephony.provider_family",
            "telephony_providers": "telephony.provider_count",
            "telephony_configured_numbers": "telephony.configured_number_count",
            "telephony_registered_voip_numbers": (
                "telephony.registered_voip_number_count"
            ),
            "telephony_inactive_voip_numbers": "telephony.inactive_voip_number_count",
            "telephony_warning_voip_numbers": "telephony.warning_voip_number_count",
            "telephony_failed_lines": "telephony.failed_line_count",
            "missed_calls": "telephony.missed_call_count",
            "last_call": "telephony.last_call.timestamp",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("pbx",),
        {
            "ip_phones": "pbx.ip_phones",
            "pbx_configured_clients": "pbx.configured_client_count",
            "pbx_disconnected_clients": "pbx.disconnected_client_count",
            "pbx_registered_clients": "pbx.registered_client_count",
            "pbx_locked_clients": "pbx.locked_client_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("dect",),
        {
            "dect_handsets": "dect.handset_count",
            "dect_repeaters": "dect.repeater_count",
            "phonebooks": "dect.phonebooks",
            "phonebook_entries": "dect.phonebook_entry_count",
            "dect_paging_handsets": "dect.paging_handset_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("usb",),
        {
            "usb_devices": "usb.items",
            "usb_tethering_status": "usb.tethering_status_code",
            "usb_storage_devices": "usb.storage_device_count",
            "usb_storage_total": "usb.storage_total_bytes",
            "usb_storage_used": "usb.storage_used_bytes",
            "usb_storage_free": "usb.storage_free_bytes",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("usb", "media_server"),
        {
            "media_server_folders": "usb.media_share_count",
            "media_server_active_folders": "usb.active_media_share_count",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("system",),
        {
            "system_uptime": "system.uptime_seconds",
            "system_operating_mode": "system.operating_mode",
            "system_temperature": "system.temperature_celsius",
            "system_cpu": "system.cpu_percent",
            "system_memory": "system.memory_percent",
            "firmware_update_time": "system.update_time",
        },
    ),
    *_group(
        NativeReadPlatform.SENSOR,
        ("diagnostics",),
        {
            "request_latency": "diagnostics.request_latency_ms",
            "update_failures": "diagnostics.update_failures",
            "last_successful_update": "diagnostics.last_successful_update",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("internet",),
        {
            "internet_connected": "internet.state",
            "internet_bng_configured": "internet.bng_configured",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("dsl",),
        {
            "dsl_connected": "dsl.state",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("hybrid",),
        {
            "hybrid_connected": "hybrid.connected",
            "hybrid_enabled": "hybrid.enabled",
            "hybrid_dsl_tunnel": "hybrid.dsl_tunnel",
            "hybrid_lte_tunnel": "hybrid.lte_tunnel",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("mobile",),
        {
            "mobile_connected": "mobile.connected",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("receiver",),
        {
            "receiver_external_modem_enabled": "receiver.external_modem_enabled",
            "receiver_external_wan_link": "receiver.external_wan_link",
            "receiver_esim_supported": "receiver.esim_supported",
            "receiver_lte_enabled": "receiver.lte_enabled",
            "receiver_firmware_automatic_updates": "receiver.firmware_auto_update",
            "receiver_firmware_update_available": "receiver.firmware_update_available",
            "receiver_firmware_update_planned": "receiver.firmware_update_planned",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("wifi",),
        {
            "wifi_enabled": "wifi.enabled",
            "wifi_2_4_enabled": "wifi.radio_2_4.enabled",
            "wifi_5_enabled": "wifi.radio_5.enabled",
            "guest_wifi_enabled": "wifi.guest.enabled",
            "office_wifi_enabled": "wifi.office.enabled",
            "wifi_wps_active": "wifi.wps_status",
            "wifi_mac_filter_enabled": "wifi.mac_filter_enabled",
            "wifi_schedule_enabled": "wifi.schedule_enabled",
            "wifi_wps_enabled": "wifi.wps_enabled",
            "wifi_wps_disabled_by_firmware": "wifi.wps_disabled_by_firmware",
            "wifi_allow_all_devices": "wifi.allow_all_devices",
            "wifi_2_4_visible": "wifi.radio_2_4.visible",
            "wifi_5_visible": "wifi.radio_5.visible",
            "guest_wifi_wps_enabled": "wifi.guest.wps_enabled",
            "guest_wifi_display_key_enabled": "wifi.guest.display_key_enabled",
            "office_wifi_wps_enabled": "wifi.office.wps_enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("mesh",),
        {
            "mesh_enabled": "mesh.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("dhcp",),
        {
            "dhcp_enabled": "dhcp.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("lan",),
        {
            "lan_ipv6_enabled": "lan.ipv6_enabled",
            "lan_port_1_connected": "lan.ports.port_1.connected",
            "lan_port_2_connected": "lan.ports.port_2.connected",
            "lan_port_3_connected": "lan.ports.port_3.connected",
            "lan_port_4_connected": "lan.ports.port_4.connected",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("lan", "dsl"),
        {
            "dsl_modem_lan_link": "dsl.modem_lan_link",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("nat",),
        {
            "upnp_enabled": "nat.upnp_enabled",
            "port_forwarding_enabled": "nat.port_forwarding_enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("ddns",),
        {
            "ddns_enabled": "ddns.enabled",
            "ddns_connected": "ddns.connected",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("vpn",),
        {
            "vpn_connected": "vpn.connected",
            "vpn_enabled": "vpn.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("parental",),
        {
            "parental_controls_enabled": "parental.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("telephony",),
        {
            "telephony_registered": "telephony.registered",
            "active_call": "telephony.active_call",
            "telephony_voip_possible": "telephony.voip_possible",
            "telephony_hd_voice_active": "telephony.hd_voice_active",
            "telephony_manual_configuration_available": (
                "telephony.manual_configuration_available"
            ),
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("dect",),
        {
            "dect_enabled": "dect.enabled",
            "dect_scan_active": "dect.scan_active",
            "dect_paging_active": "dect.paging_active",
            "dect_smart_home_enabled": "dect.smart_home_enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("system",),
        {
            "smarthome_linked": "smarthome.linked",
            "firmware_update_available": "system.update_available",
            "firmware_update_planned": "system.update_planned",
            "firmware_automatic_updates": "system.automatic_updates_enabled",
            "remote_support_active": "system.remote_support_active",
            "easy_support_enabled": "system.easy_support_enabled",
            "settings_write_blocked": "system.settings_write_blocked",
            "device_password_changed": "system.device_password_changed",
            "initial_setup_completed": "system.initial_setup_completed",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("pbx",),
        {
            "pbx_enabled": "pbx.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("security",),
        {
            "firewall_enabled": "security.firewall_enabled",
            "dns_rebind_protection": "security.dns_rebind_protection",
            "remote_management": "security.remote_management",
            "router_https_enabled": "security.router_https_enabled",
            "port_blocking_enabled": "security.port_blocking_enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("usb",),
        {
            "usb_connected": "usb.connected",
            "media_server_enabled": "usb.media_server_enabled",
            "usb_port_enabled": "usb.port_enabled",
            "usb_tethering_enabled": "usb.tethering_enabled",
            "usb_tethering_connected": "usb.tethering_connected",
            "usb_printer_connected": "usb.printer_connected",
            "nas_enabled": "usb.nas_enabled",
            "nas_secure": "usb.nas_secure",
            "nas_read_only": "usb.nas_read_only",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("wan",),
        {
            "wan_interface_enabled": "wan.interface.enabled",
        },
    ),
    *_group(
        NativeReadPlatform.BINARY_SENSOR,
        ("diagnostics",),
        {
            "router_problem": "diagnostics.problem",
        },
    ),
)

NATIVE_SCALAR_READ_CONTRACTS: Final[
    Mapping[NativeReadContractId, NativeScalarReadContract]
] = _build_registry(_DECLARED_NATIVE_SCALAR_READ_CONTRACTS)

NATIVE_SCALAR_READ_PATHS: Final = frozenset(
    contract.data_path for contract in NATIVE_SCALAR_READ_CONTRACTS.values()
)
