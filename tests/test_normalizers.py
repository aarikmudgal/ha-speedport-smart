"""Tests for router payload normalization contracts."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.normalizers import normalize_feature_payload


@pytest.mark.parametrize(
    ("global_state", "band_mode", "expected_2_4", "expected_5"),
    [
        ("1", "0", True, True),
        ("1", "1", True, False),
        ("1", "2", False, True),
        ("0", "0", False, False),
        ("0", "1", False, False),
        ("0", "2", False, False),
    ],
)
def test_wifi_band_mode_controls_per_radio_state(
    global_state: str,
    band_mode: str,
    expected_2_4: bool,  # noqa: FBT001
    expected_5: bool,  # noqa: FBT001
) -> None:
    """Global Wi-Fi plus wlan_band matches the firmware UI's radio contract."""
    wifi = normalize_feature_payload(
        "wifi",
        {"use_wlan": global_state, "wlan_band": band_mode},
    )["wifi"]

    assert wifi["radio_2_4"]["enabled"] is expected_2_4
    assert wifi["radio_5"]["enabled"] is expected_5


def test_explicit_wifi_radio_state_overrides_band_fallback() -> None:
    """Dedicated per-radio fields remain authoritative when firmware supplies them."""
    wifi = normalize_feature_payload(
        "wifi",
        {
            "use_wlan": "1",
            "wlan_band": "2",
            "use_wlan_2ghz": "1",
            "use_wlan_5ghz": "0",
        },
    )["wifi"]

    assert wifi["radio_2_4"]["enabled"] is True
    assert wifi["radio_5"]["enabled"] is False


def test_client_access_possible_is_read_only_allowed_state() -> None:
    """Firmware client allowance is not inverted into an unproven pause state."""
    client = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [
                {
                    "id": "row-1",
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "access_possible": "1",
                }
            ]
        },
    )["clients"]["items"][0]

    assert client["internet_access_allowed"] is True
    assert "internet_paused" not in client


def test_ddns_uses_firmware_enabled_field() -> None:
    """The firmware's use_dyndns field drives the DDNS enabled sensor."""
    ddns = normalize_feature_payload("ddns", {"use_dyndns": "1"})["ddns"]

    assert ddns["enabled"] is True


def test_ddns_provider_and_status_use_exact_firmware_fields() -> None:
    """DynDNS provider and registration state stay nonsecret and bounded."""
    ddns = normalize_feature_payload(
        "ddns",
        {
            "use_dyndns": "1",
            "dyndns_provider": "4",
            "dyndns_status": "2",
            "dyndns_domain": "PRIVATE-DOMAIN",
            "dyndns_user": "PRIVATE-USER",
            "dyndns_password": "PRIVATE-PASSWORD",
        },
    )["ddns"]

    assert ddns == {
        "enabled": True,
        "connected": True,
        "provider": "4",
        "status_code": 2,
    }
    assert "PRIVATE" not in repr(ddns)


def test_lan_and_dhcp_exact_octets_create_bounded_read_only_state() -> None:
    """LAN and DHCP pages share one payload without losing either root."""
    raw = {
        "lan_ipv4_1": "10",
        "lan_ipv4_2": "168",
        "lan_ipv4_3": "10",
        "lan_ipv4_4": "1",
        "lan_mask_2": "255",
        "lan_mask_3": "255",
        "lan_mask_4": "0",
        "lan_ip_v6_used": "1",
        "lan_use_dhcp": "1",
        "lan_dhcp_from": "20",
        "lan_dhcp_to": "200",
        "lan_ip_v6": "PRIVATE-IPV6",
        "lan_ip_v6_range": "PRIVATE-RANGE",
    }

    expected = {
        "lan": {
            "ipv4_address": "10.168.10.1",
            "subnet_mask": "255.255.255.0",
            "ipv6_enabled": True,
        },
        "dhcp": {
            "enabled": True,
            "pool_start_ipv4": "10.168.10.20",
            "pool_end_ipv4": "10.168.10.200",
            "pool_size": 181,
        },
    }
    assert normalize_feature_payload("lan", raw) == expected
    assert normalize_feature_payload("dhcp", raw) == expected
    assert "PRIVATE" not in repr(expected)


def test_vpn_profile_enabled_state_is_not_connection_state() -> None:
    """A profile's vpn_status flag must not claim a connected tunnel."""
    vpn = normalize_feature_payload("vpn", {"vpn_status": "1"})["vpn"]

    assert vpn["enabled"] is True
    assert "connected" not in vpn


def test_detail_family_normalizers_are_scoped_to_owned_fields() -> None:
    """Additive detail families cannot claim unrelated base-family fields."""
    wifi = normalize_feature_payload(
        "wifi_schedule",
        {
            "use_wlan": "0",
            "wlan_guest_active": "1",
            "wlan_timerule": "1",
            "wlan_dfrom": "07:30",
            "wlan_dto": "22:15",
        },
    )
    vpn = normalize_feature_payload(
        "vpn_details",
        {
            "enabled": "0",
            "status": "0",
            "vpn_status": "1",
            "vpn_connected": "1",
            "addpeer": [{"connected": "1"}, {"connected": "0"}],
        },
    )
    dect = normalize_feature_payload(
        "dect_repeater",
        {
            "use_dect": "0",
            "adddectdevice": [{"id": "handset-1"}],
            "addrepeater": [{"id": "1"}, {"id": "2"}],
        },
    )
    mesh = normalize_feature_payload(
        "mesh_topology",
        {
            "use_dhcp": "1",
            "wlan_active": "1",
            "addmeshdevice": [
                {
                    "id": "mesh-1",
                    "mesh_connect_to": "r",
                }
            ],
        },
    )

    assert wifi == {
        "wifi": {
            "schedule_enabled": True,
            "schedule": {
                "mode": 1,
                "daily_from": "07:30",
                "daily_to": "22:15",
            },
        }
    }
    assert vpn == {
        "vpn": {
            "enabled": True,
            "connected": True,
            "peers": [{"connected": True}, {"connected": False}],
            "connected_peer_count": 1,
        }
    }
    assert dect == {"dect": {"repeater_count": 2}}
    assert mesh == {"mesh": {"nodes": [{"id": "mesh-1", "parent": "r"}]}}


def test_connection_privacy_is_scoped_and_identifier_free() -> None:
    """The privacy endpoint exposes only its bounded policy level."""
    normalized = normalize_feature_payload(
        "internet_privacy",
        {
            "lan_privacy_policy": "2",
            "public_ip": "203.0.113.44",
            "device_name": "PRIVATE-ROUTER-NAME",
        },
    )

    assert normalized == {"internet": {"privacy_level": 2}}


def test_wifi_management_metadata_omits_network_credentials() -> None:
    """Wi-Fi settings retain safe modes and schedules, never SSIDs or keys."""
    normalized = normalize_feature_payload(
        "wlan_configuration",
        {
            "use_wlan": "1",
            "wlan_band": "1",
            "wlan_visible": "0",
            "wlan_5ghz_visible": "1",
            "wlan_enc": "6",
            "wlan_allow_all": "0",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_wps_state": "1",
            "wlan_timerule": "2",
            "wlan_dfrom": "07:30",
            "wlan_dto": "22:15",
            "wlan_time_mo_from": "08:00",
            "wlan_time_mo_to": "21:00",
            "wlan_guest_ssid": "PRIVATE-GUEST-SSID",
            "wlan_guest_key": "PRIVATE-GUEST-KEY",
            "wlan_office_ssid": "PRIVATE-OFFICE-SSID",
            "wlan_office_key": "PRIVATE-OFFICE-KEY",
            "wps_pin": "12345670",
        },
    )
    wifi = normalized["wifi"]

    assert wifi["band_mode"] == 1
    assert wifi["allow_all_devices"] is False
    assert wifi["wps_enabled"] is True
    assert wifi["wps_disabled_by_firmware"] is False
    assert wifi["wps_state_code"] == 1
    assert wifi["radio_2_4"]["visible"] is False
    assert wifi["radio_2_4"]["encryption_mode"] == 6
    assert wifi["radio_5"]["visible"] is True
    assert wifi["schedule_enabled"] is True
    assert wifi["schedule"] == {
        "mode": 2,
        "daily_from": "07:30",
        "daily_to": "22:15",
        "weekly": {"monday": {"from": "08:00", "to": "21:00"}},
        "weekly_day_count": 1,
    }
    rendered = repr(normalized)
    for private_value in (
        "PRIVATE-GUEST-SSID",
        "PRIVATE-GUEST-KEY",
        "PRIVATE-OFFICE-SSID",
        "PRIVATE-OFFICE-KEY",
        "12345670",
    ):
        assert private_value not in rendered


def test_mobile_and_receiver_management_fields_are_constrained() -> None:
    """Receiver management adds enums and versions without hardware identity."""
    raw = {
        "auto_external_modem": "1",
        "extwan_typ": "3",
        "use_lte": "1",
        "ex5g_led_mode": "2",
        "auto_update": "true",
        "ex5g_fwupd_avail": "1",
        "ex5g_fw_version": "010152.5.0.001.0",
        "ex5g_fwupd_version": "010152.6.0.001.0",
        "ex5g_fwupd_planned": "1",
        "mobile_network_type": "5G",
        "ex5g_eid": "PRIVATE-EID",
        "ex5g_imei": "PRIVATE-IMEI",
        "receiver_hostname": "PRIVATE-RECEIVER-HOSTNAME",
    }

    mobile_payload = normalize_feature_payload("mobile", raw)
    receiver_payload = normalize_feature_payload("receiver", raw)
    mobile = mobile_payload["mobile"]
    mobile_receiver = mobile_payload["receiver"]
    receiver = receiver_payload["receiver"]

    assert mobile == {"network_type": "5G"}
    assert receiver_payload["mobile"] == mobile
    for payload in (mobile_receiver, receiver):
        assert payload["external_modem_enabled"] is True
        assert payload["mode"] == 3
        assert payload["lte_enabled"] is True
        assert payload["led_mode"] == 2
        assert payload["firmware_auto_update"] is True
        assert payload["firmware_update_available"] is True
        assert payload["firmware_version"] == "010152.5.0.001.0"
        assert payload["latest_firmware"] == "010152.6.0.001.0"
        assert payload["firmware_update_planned"] is True
    rendered = repr(
        {
            "mobile": mobile,
            "mobile_receiver": mobile_receiver,
            "receiver": receiver,
        }
    )
    for private_value in (
        "PRIVATE-EID",
        "PRIVATE-IMEI",
        "PRIVATE-RECEIVER-HOSTNAME",
    ):
        assert private_value not in rendered


def test_receiver_child_keeps_link_speed_under_receiver_root() -> None:
    """Receiver inventory exposes link speed once through its child record."""
    normalized = normalize_feature_payload(
        "receiver",
        {
            "addreceiver": [
                {
                    "id": "receiver-1",
                    "name": "Outdoor receiver",
                    "link_speed": "1000000000",
                }
            ]
        },
    )

    assert normalized == {
        "receiver": {
            "items": [
                {
                    "id": "receiver-1",
                    "name": "Outdoor receiver",
                    "link_speed_bps": 1_000_000_000,
                }
            ]
        }
    }


def test_managed_client_safe_network_metadata_uses_exact_varids() -> None:
    """Managed rows separate directional link speeds from Wi-Fi generation."""
    normalized = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [
                {
                    "id": "row-1",
                    "mdevice_mac": "AA:BB:CC:DD:EE:FF",
                    "mdevice_ipv4": "192.168.2.40",
                    "mdevice_reservedip": "55",
                    "mdevice_downspeed": "1000000000",
                    "mdevice_upspeed": "500000000",
                    "mdevice_wifi": "6",
                }
            ]
        },
    )["clients"]["items"][0]

    assert normalized["reserved_ipv4"] == "192.168.2.55"
    assert normalized["download_link_speed_bps"] == 1_000_000_000
    assert normalized["upload_link_speed_bps"] == 500_000_000
    assert normalized["wifi_generation"] == 6
    assert "download_rate_bps" not in normalized
    assert "upload_rate_bps" not in normalized
    assert "medium" not in normalized


def test_wifi_generation_never_implies_radio_band() -> None:
    """Wi-Fi generation 5 is not counted as a proven 5 GHz connection."""
    ambiguous = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [
                {
                    "id": "row-1",
                    "mdevice_connected": "1",
                    "mdevice_wifi": "5",
                }
            ]
        },
    )

    assert ambiguous["clients"]["items"][0]["wifi_generation"] == 5
    assert "medium" not in ambiguous["clients"]["items"][0]
    assert "wifi" not in ambiguous

    proven_band = normalize_feature_payload(
        "clients",
        {
            "addmwlan5device": [
                {
                    "id": "row-2",
                    "mdevice_connected": "1",
                    "mdevice_wifi": "4",
                }
            ]
        },
    )
    assert proven_band["clients"]["items"][0]["medium"] == "wifi_5"
    assert proven_band["clients"]["items"][0]["wifi_generation"] == 4
    assert proven_band["wifi"]["radio_5"]["client_count"] == 1


def test_explicit_client_throughput_remains_distinct_from_link_speed() -> None:
    """Explicit traffic-rate fields coexist with firmware directional speeds."""
    client = normalize_feature_payload(
        "clients",
        {
            "device": [
                {
                    "id": "row-1",
                    "download_rate_bps": "80000000",
                    "upload_rate_bps": "12000000",
                    "downspeed": "1000000000",
                    "upspeed": "500000000",
                }
            ]
        },
    )["clients"]["items"][0]

    assert client["download_rate_bps"] == 80_000_000
    assert client["upload_rate_bps"] == 12_000_000
    assert client["download_link_speed_bps"] == 1_000_000_000
    assert client["upload_link_speed_bps"] == 500_000_000


def test_mesh_exact_topology_fields_are_bounded() -> None:
    """Mesh topology retains exact safe status and direct UI speed units."""
    mesh = normalize_feature_payload(
        "mesh",
        {
            "addmeshdevice": [
                {
                    "id": "mesh-1",
                    "mesh_connect_to": "r",
                    "mesh_device_type": "2",
                    "mesh_downspeed": "1200000000",
                    "mesh_upspeed": "600000000",
                    "mesh_ipv4": "192.168.2.2",
                    "mesh_lan1": "1000",
                    "mesh_lan2": "0",
                    "mesh_use_wlan": "1",
                }
            ]
        },
    )["mesh"]["nodes"][0]

    assert mesh == {
        "id": "mesh-1",
        "parent": "r",
        "device_type": 2,
        "ipv4": "192.168.2.2",
        "wifi_enabled": True,
        "download_link_speed_bps": 1_200_000_000,
        "upload_link_speed_bps": 600_000_000,
        "linked_lan_port_count": 1,
    }


def test_usb_tethering_and_nas_are_aggregate_only() -> None:
    """USB/NAS management retains booleans and capacity, not paths or users."""
    tethering = normalize_feature_payload(
        "usb_tethering",
        {
            "use_usb": "1",
            "use_tethering": "1",
            "tethering_status": "2",
            "nas_user_name": "PRIVATE-NAS-USER",
        },
    )["usb"]
    nas = normalize_feature_payload(
        "nas_storage",
        {
            "use_usb": "1",
            "printer_connected": "0",
            "nas_active": "1",
            "nas_secure": "1",
            "nas_folder_nur_lesen": "0",
            "addnasdevice": [
                {
                    "serial": "PRIVATE-DISK-SERIAL",
                    "nas_device_name": "PRIVATE-DISK-NAME",
                    "nas_device_type": "NAS",
                    "nas_device_total": "2048",
                    "nas_device_used": "512",
                    "path": "/PRIVATE/PATH",
                    "nas_user_name": "PRIVATE-NAS-USER",
                }
            ],
        },
    )["usb"]

    assert tethering == {
        "port_enabled": True,
        "tethering_enabled": True,
        "tethering_status_code": 2,
        "tethering_connected": True,
    }
    assert nas == {
        "port_enabled": True,
        "printer_connected": False,
        "nas_enabled": True,
        "nas_secure": True,
        "nas_read_only": False,
        "storage_device_count": 1,
        "storage_total_bytes": 2_097_152,
        "storage_used_bytes": 524_288,
        "storage_free_bytes": 1_572_864,
    }
    rendered = repr(nas)
    for private_value in (
        "PRIVATE-DISK-SERIAL",
        "PRIVATE-DISK-NAME",
        "/PRIVATE/PATH",
        "PRIVATE-NAS-USER",
    ):
        assert private_value not in rendered


def test_security_and_qos_management_expose_counts_not_rule_identity() -> None:
    """DNS, port-blocking, and QoS payloads collapse to safe counts."""
    dns = normalize_feature_payload(
        "dns_rebind",
        {
            "adddnsexcept": [
                {"hostname": "private-a.example"},
                {"hostname": "private-b.example"},
            ]
        },
    )["security"]
    blocking = normalize_feature_payload(
        "portblocking",
        {
            "addextra": [
                {
                    "id": "PRIVATE-RULE-1",
                    "extendedrule_active": "1",
                    "extrule_tcp": "PRIVATE-PORT-LIST",
                },
                {"id": "PRIVATE-RULE-2", "extendedrule_active": "0"},
            ]
        },
    )["security"]
    qos = normalize_feature_payload(
        "qos",
        {
            "qos_pc[1]": "1",
            "qos_pc[2]": "0",
            "hostname": "PRIVATE-QOS-HOST",
            "mac": "AA:BB:CC:DD:EE:FF",
        },
    )["qos"]

    assert dns == {"dns_rebind_exception_count": 2}
    assert blocking == {
        "port_block_rule_count": 2,
        "active_port_block_rule_count": 1,
    }
    assert qos == {"prioritized_client_count": 1}
    rendered = repr({"dns": dns, "blocking": blocking, "qos": qos})
    for private_value in (
        "private-a.example",
        "private-b.example",
        "PRIVATE-RULE-1",
        "PRIVATE-PORT-LIST",
        "PRIVATE-QOS-HOST",
        "AA:BB:CC:DD:EE:FF",
    ):
        assert private_value not in rendered


def test_telephony_management_keeps_status_counts_only() -> None:
    """DECT, PBX, and VoIP management never add contact or credential fields."""
    dect = normalize_feature_payload(
        "dect",
        {
            "use_dect": "1",
            "dect_detect_status": "0",
            "DECT_real_count": "2",
            "addrepeater": [{"id": "PRIVATE-REPEATER-ID"}],
            "dect_pin": "PRIVATE-DECT-PIN",
        },
    )["dect"]
    pbx = normalize_feature_payload(
        "pbx",
        {
            "use_ippbx": "1",
            "addipclient": [
                {
                    "id": "PRIVATE-PBX-ID-1",
                    "ipclient_status": "1",
                    "ipclient_mdevice_ipv4": "192.0.2.10",
                    "ipclient_password": "PRIVATE-PBX-PASSWORD",
                },
                {"id": "PRIVATE-PBX-ID-2", "ipclient_status": "2"},
                {"id": "PRIVATE-PBX-ID-3", "ipclient_status": "0"},
            ],
        },
    )["pbx"]
    telephony = normalize_feature_payload(
        "telephony",
        {
            "phone_vosip_policy": "2",
            "vosip_possible": "1",
            "addipphoneprovider": [{"id": "PRIVATE-PROVIDER-ID"}],
            "addipnumber": [
                {"ip_number": "PRIVATE-PHONE-1", "number_status": "ok"},
                {"ip_number": "PRIVATE-PHONE-2", "number_status": "inactive"},
            ],
            "contact_name": "PRIVATE-CONTACT",
            "call_record": "PRIVATE-CALL-RECORD",
        },
    )["telephony"]

    assert dect["enabled"] is True
    assert dect["scan_active"] is False
    assert dect["handset_count"] == 2
    assert dect["repeater_count"] == 1
    assert pbx == {
        "enabled": True,
        "configured_client_count": 3,
        "disconnected_client_count": 1,
        "registered_client_count": 1,
        "locked_client_count": 1,
    }
    assert telephony == {
        "voip_possible": True,
        "voip_policy": 2,
        "provider_count": 1,
        "configured_number_count": 2,
        "registered_voip_number_count": 1,
        "inactive_voip_number_count": 1,
        "warning_voip_number_count": 0,
    }
    rendered = repr({"dect": dect, "pbx": pbx, "telephony": telephony})
    for private_value in (
        "PRIVATE-REPEATER-ID",
        "PRIVATE-DECT-PIN",
        "PRIVATE-PBX-ID-1",
        "PRIVATE-PBX-PASSWORD",
        "192.0.2.10",
        "PRIVATE-PROVIDER-ID",
        "PRIVATE-PHONE-1",
        "PRIVATE-CONTACT",
        "PRIVATE-CALL-RECORD",
    ):
        assert private_value not in rendered


def test_client_time_fields_are_not_router_global() -> None:
    """ClientTime-only values remain absent without a per-client read contract."""
    normalized = normalize_feature_payload(
        "parental",
        {
            "addprofile": [{"id": "profile-1"}],
            "actual_time": "09:15",
            "trule_from": "08:00",
            "trule_to": "10:00",
            "trule_from2": "14:30",
            "trule_to2": "16:00",
            "trule_from3": "bad",
            "trule_to3": "21:00",
            "remainingtime": "45 min",
            "mdevice_name": "PRIVATE-CLIENT",
        },
    )

    assert normalized == {"parental": {"profiles": 1}}
    assert "PRIVATE-CLIENT" not in repr(normalized)


def test_dect_handset_count_preserves_stable_handset_inventory() -> None:
    """Aggregate count coexists with child records used by handset entities."""
    normalized = normalize_feature_payload(
        "dect",
        {
            "adddectdevice": [
                {"id": "handset-1", "name": "Office"},
                {"id": "handset-2", "name": "Living room"},
            ]
        },
    )["dect"]

    assert normalized["handset_count"] == 2
    assert normalized["handsets"] == [
        {"id": "handset-1", "name": "Office"},
        {"id": "handset-2", "name": "Living room"},
    ]


def test_dect_paging_is_privacy_safe_and_phonebook_entries_are_withheld() -> None:
    """Paging remains readable while unsupported contact counts stay absent."""
    dect = normalize_feature_payload(
        "phonebook",
        {
            "adddectdevice": [{"id": "1", "name": "Office"}],
            "PagingStat1": "1",
            "num_entries": "42",
            "contact_name": "PRIVATE-CONTACT",
            "phone_number": "PRIVATE-NUMBER",
        },
    )["dect"]

    assert dect["handsets"] == [{"id": "1", "name": "Office", "paging": True}]
    assert "phonebook_entry_count" not in dect
    assert "PRIVATE-CONTACT" not in repr(dect)
    assert "PRIVATE-NUMBER" not in repr(dect)


def test_firmware_and_easy_support_states_are_nonsecret() -> None:
    """Firmware and EasySupport expose bounded states, not router identity."""
    firmware = normalize_feature_payload(
        "firmware",
        {
            "fwupd_avail": "1",
            "fwupd_version": "010152.6.0.001.0",
            "fwupd_planned": "0",
            "autofw_deactive": "0",
            "serial": "PRIVATE-ROUTER-SERIAL",
            "device_name": "PRIVATE-ROUTER-NAME",
        },
    )["system"]
    easy_support = normalize_feature_payload(
        "easy_support",
        {
            "easy_support_deactive": "1",
            "br_active": "0",
            "acs_password": "PRIVATE-ACS-PASSWORD",
        },
    )["system"]

    assert firmware == {
        "update_available": True,
        "latest_firmware": "010152.6.0.001.0",
        "update_planned": False,
        "automatic_updates_enabled": True,
    }
    assert easy_support == {
        "remote_support_active": False,
        "easy_support_enabled": False,
    }
    rendered = repr({"firmware": firmware, "easy_support": easy_support})
    for private_value in (
        "PRIVATE-ROUTER-SERIAL",
        "PRIVATE-ROUTER-NAME",
        "PRIVATE-ACS-PASSWORD",
    ):
        assert private_value not in rendered


@pytest.mark.parametrize(
    "family",
    [
        "connection_privacy",
        "wifi_configuration",
        "wifi_access",
        "wps",
        "mobile",
        "receiver",
        "usb_tethering",
        "nas",
        "dns_rebind",
        "port_blocking",
        "qos",
        "dect",
        "pbx",
        "telephony",
        "firmware",
        "easy_support",
        "system_services",
    ],
)
def test_management_missing_fields_do_not_become_false(family: str) -> None:
    """An absent firmware field remains absent rather than becoming false or zero."""
    assert normalize_feature_payload(family, {}) == {}
