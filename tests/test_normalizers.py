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


def test_vpn_profile_enabled_state_is_not_connection_state() -> None:
    """A profile's vpn_status flag must not claim a connected tunnel."""
    vpn = normalize_feature_payload("vpn", {"vpn_status": "1"})["vpn"]

    assert vpn["enabled"] is True
    assert "connected" not in vpn


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
        "ex5g_eid": "PRIVATE-EID",
        "ex5g_imei": "PRIVATE-IMEI",
        "receiver_hostname": "PRIVATE-RECEIVER-HOSTNAME",
    }

    mobile = normalize_feature_payload("mobile", raw)["mobile"]
    receiver = normalize_feature_payload("receiver", raw)["receiver"]

    for payload in (mobile, receiver):
        assert payload["external_modem_enabled"] is True
        assert (payload.get("receiver_mode") or payload.get("mode")) == 3
        assert payload["lte_enabled"] is True
        assert payload["led_mode"] == 2
        assert payload["firmware_auto_update"] is True
        assert payload["firmware_update_available"] is True
        assert payload["firmware_version"] == "010152.5.0.001.0"
        assert payload["latest_firmware"] == "010152.6.0.001.0"
        assert payload["firmware_update_planned"] is True
    rendered = repr({"mobile": mobile, "receiver": receiver})
    for private_value in (
        "PRIVATE-EID",
        "PRIVATE-IMEI",
        "PRIVATE-RECEIVER-HOSTNAME",
    ):
        assert private_value not in rendered


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
    ],
)
def test_management_missing_fields_do_not_become_false(family: str) -> None:
    """An absent firmware field remains absent rather than becoming false or zero."""
    assert normalize_feature_payload(family, {}) == {}
