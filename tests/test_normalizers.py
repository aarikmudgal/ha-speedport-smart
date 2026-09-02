"""Tests for router payload normalization contracts."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart import normalizers as normalizer_module
from custom_components.speedport_smart.models import normalize_status
from custom_components.speedport_smart.normalizers import (
    normalize_feature_payload,
    normalize_status_payload,
)


def test_internet_connected_since_is_distinct_from_uptime_duration() -> None:
    """Firmware connection timestamp and duration remain independent reads."""
    normalized, capabilities = normalize_status_payload(
        normalize_status(
            {
                "inet_uptime": "2026-09-02T08:15:30+02:00",
                "days_online": "2",
                "time_online": "03:04:05",
            }
        )
    )
    internet = normalized["internet"]

    assert internet["connected_since"] == "2026-09-02T08:15:30+02:00"
    assert internet["uptime_seconds"] == 183_845
    assert "internet" in capabilities


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-02T08:15:30",
        "02.09.2026 08:15:30",
        "09/02/2026 08:15:30",
        "2026-09-02",
        "2026-09-02T08:15:30+25:00",
        "2026-09-02T08:15:30+02:60",
        "2026-09-02T08:15:30-24:00",
        1_788_332_130,
        True,
        "",
    ],
)
def test_internet_connected_since_rejects_timezone_or_locale_ambiguity(
    value: object,
) -> None:
    """A timestamp without an explicit valid UTC offset remains absent."""
    assert normalize_feature_payload("internet", {"inet_uptime": value}) == {}


def test_internet_connected_since_accepts_explicit_utc_designator() -> None:
    """ISO UTC designator is normalized to Home Assistant's aware form."""
    internet = normalize_feature_payload(
        "internet",
        {"inet_uptime": "2026-09-02T06:15:30Z"},
    )["internet"]

    assert internet["connected_since"] == "2026-09-02T06:15:30+00:00"


def test_internet_uptime_duration_does_not_fabricate_connection_timestamp() -> None:
    """Duration-only firmware state never depends on the current clock."""
    internet = normalize_feature_payload(
        "internet",
        {"days_online": "1", "time_online": "00:01:30"},
    )["internet"]

    assert internet == {"uptime_seconds": 86_490}


def test_public_status_domain_name_is_bounded_raw_technical_text() -> None:
    """The firmware field is preserved exactly without assigning semantics."""
    normalized, capabilities = normalize_status_payload(
        normalize_status({"domain_name": "speedport.ip"})
    )

    assert normalized["system"]["domain_name"] == "speedport.ip"
    assert "system" in capabilities


@pytest.mark.parametrize(
    "value",
    [
        "x" * 257,
        "router\x00name",
        {"nested": "router"},
        ["router"],
        123,
        True,
        "",
    ],
)
def test_public_status_domain_name_rejects_unbounded_or_untyped_values(
    value: object,
) -> None:
    """Unknown types and unbounded text never enter the technical read model."""
    normalized, _ = normalize_status_payload(normalize_status({"domain_name": value}))

    assert normalized.get("system", {}).get("domain_name") is None


def test_domain_name_is_owned_only_by_public_status() -> None:
    """Protected and feature payloads cannot populate a public-status field."""
    assert normalize_feature_payload("system", {"domain_name": "speedport.ip"}) == {}
    assert normalize_feature_payload("internet", {"domain_name": "speedport.ip"}) == {}


@pytest.mark.parametrize("value", ["user", "net", "dsl", "router"])
def test_public_status_failure_reason_preserves_only_firmware_codes(
    value: str,
) -> None:
    """The public status read keeps the exact closed firmware reason code."""
    normalized, capabilities = normalize_status_payload(
        normalize_status({"fail_reason": value})
    )

    assert normalized["internet"]["failure_reason"] == value
    assert "internet" in capabilities


@pytest.mark.parametrize(
    "value",
    ["USER", " net", "timeout", "account@example.net", 1, True, None],
)
def test_public_status_failure_reason_rejects_unproven_values(value: object) -> None:
    """Unknown, coerced, or potentially sensitive failure text stays absent."""
    normalized, _ = normalize_status_payload(normalize_status({"fail_reason": value}))

    assert normalized.get("internet", {}).get("failure_reason") is None


def test_subscriber_and_session_metadata_never_enters_feature_data() -> None:
    """Exact sensitive fields are removed in object and firmware-varid forms."""
    raw = {
        "loginstate": "private-session-state",
        "t_callident": "private-call-id",
        "t_number": "+49 30 123456",
        "t_password": "private-password",
        "rows": [
            {"varid": "t_number", "varvalue": "+49 30 123456"},
            {"varid": "t_callident", "varvalue": "private-call-id"},
        ],
    }

    safe = normalizer_module._safe_mapping(raw)  # noqa: SLF001
    rendered = repr(safe)
    assert "private-call-id" not in rendered
    assert "+49 30 123456" not in rendered
    assert "private-password" not in rendered
    assert "private-session-state" not in rendered


def test_router_diagnostics_cannot_inject_integration_owned_failure_metadata() -> None:
    """Router payloads cannot forge coordinator or endpoint health fields."""
    diagnostics = normalize_feature_payload(
        "diagnostics",
        {
            "problem": "1",
            "failed_group": "slow",
            "last_error": "InjectedError",
            "endpoint_errors": {"status": "InjectedError"},
            "polling": {"fast": {"available": False}},
        },
    )["diagnostics"]

    assert diagnostics == {"problem": True}


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
    """DynDNS safe configuration stays visible; credentials stay absent."""
    ddns = normalize_feature_payload(
        "ddns",
        {
            "use_dyndns": "1",
            "dyndns_provider": "4",
            "dyndns_status": "2",
            "dyndns_domain": "private.example.net",
            "dyndns_updsrv": "updates.example.net",
            "dyndns_updprot": "https",
            "dyndns_updport": "443",
            "dyndns_user": "PRIVATE-USER",
            "dyndns_password": "PRIVATE-PASSWORD",
        },
    )["ddns"]

    assert ddns == {
        "enabled": True,
        "connected": True,
        "provider": "4",
        "domain": "private.example.net",
        "update_server": "updates.example.net",
        "update_protocol": "https",
        "update_port": 443,
        "status_code": 2,
    }
    assert "PRIVATE-USER" not in repr(ddns)
    assert "PRIVATE-PASSWORD" not in repr(ddns)


@pytest.mark.parametrize("port", [1, 65_535])
def test_ddns_update_port_accepts_only_real_port_numbers(port: int) -> None:
    """The DDNS update endpoint retains the complete valid port range."""
    ddns = normalize_feature_payload(
        "ddns",
        {"dyndns_updport": str(port)},
    )["ddns"]

    assert ddns["update_port"] == port


@pytest.mark.parametrize(
    "port",
    ["0", "65536", "not-a-port", "443garbage", "x443y", " 443", "+443"],
)
def test_ddns_update_port_rejects_impossible_values(port: str) -> None:
    """Impossible firmware port values remain absent."""
    assert normalize_feature_payload("ddns", {"dyndns_updport": port}) == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dyndns_domain", "user:secret@example.net"),
        ("dyndns_domain", "https://subscriber.example.net"),
        ("dyndns_domain", "single-label"),
        ("dyndns_domain", "broken..example.net"),
        ("dyndns_updsrv", "https://user:secret@updates.example.net"),
        ("dyndns_updsrv", "https://updates.example.net/private-token"),
        ("dyndns_updsrv", "https://updates.example.net/?token=secret"),
        ("dyndns_updsrv", "ftp://updates.example.net"),
        ("dyndns_updprot", "https?token=secret"),
        ("dyndns_updprot", "file"),
    ],
)
def test_ddns_identity_fields_reject_credentials_and_malformed_values(
    field: str,
    value: str,
) -> None:
    """DDNS identity state cannot retain arbitrary or credential-bearing text."""
    assert normalize_feature_payload("ddns", {field: value}) == {}


def test_ddns_update_server_accepts_bounded_host_only_https_url() -> None:
    """A reviewed host-only HTTPS URL remains visible in the admin projection."""
    ddns = normalize_feature_payload(
        "ddns",
        {
            "dyndns_updsrv": "https://updates.example.net/",
            "dyndns_updprot": "HTTPS",
        },
    )["ddns"]

    assert ddns == {
        "update_server": "https://updates.example.net/",
        "update_protocol": "https",
    }


@pytest.mark.parametrize("value", ["x" * 129, "fd00::1\nprivate"])
def test_lan_ipv6_text_rejects_oversize_or_control_characters(value: str) -> None:
    """Router-controlled address text cannot become unbounded sensor state."""
    assert (
        normalize_feature_payload(
            "lan",
            {"lan_ip_v6": value, "lan_ip_v6_range": value},
        )
        == {}
    )


def test_public_overview_exact_fields_create_bounded_read_only_state() -> None:
    """Observed overview fields normalize without inferring write capability."""
    normalized = normalize_feature_payload(
        "security",
        {
            "router_state": "DECTUPD",
            "save_fails": "1",
            "router_firewall_active": "true",
            "dns_rebind_active": "true",
            "internet_extrule_active": "1",
            "internet_timerule_active": "true",
            "privacy_policy": "2",
            "dyndns_active": "reg",
            "extwan_status": "1",
            "wlan1_num": "7",
            "wlan0_num": "5",
            "wlan_guest_timeleft": "61",
            "hdvoice": "2",
            "smarthome_status": "1",
            "use_https": "1",
            "pwd_changed": "1",
            "wlanFinished": "1",
            "provis_inet": "040",
            "inet_isp": "99",
            "provis_voip": "003",
            "isp_selection": "1",
            "fail_reason": "account alice@example.net at 192.0.2.10",
            "inet_errnr": "005",
            "dsl_errnr": "006",
            "addmpriodevice": [
                {"mdevice_connected": "1"},
                {"mdevice_connected": "0"},
            ],
            "addwgdevice": [
                {"mdevice_connected": "1"},
                {"mdevice_connected": "1"},
                {"mdevice_connected": "1"},
            ],
        },
    )

    assert normalized["system"] == {
        "operating_mode": "dect_update",
        "settings_write_blocked": True,
        "device_password_changed": True,
        "initial_setup_completed": True,
    }
    assert normalized["security"] == {
        "firewall_enabled": True,
        "dns_rebind_protection": True,
        "port_blocking_enabled": True,
        "router_https_enabled": True,
    }
    assert normalized["internet"] == {
        "privacy_level": 2,
        "provisioning_code": "040",
        "bng_configured": True,
        "provider_family": "telekom",
        "error_code": "005",
    }
    assert normalized["telephony"] == {
        "hd_voice_active": True,
        "provisioning_code": "003",
        "manual_configuration_available": True,
        "provider_family": "other",
    }
    assert normalized["parental"]["enabled"] is True
    assert normalized["dsl"]["error_code"] == "006"
    assert normalized["ddns"] == {"status_code": 2, "connected": True}
    assert normalized["receiver"]["external_wan_link"] is True
    assert normalized["smarthome"]["linked"] is True
    assert "failure_reason" not in normalized["internet"]
    assert normalized["wifi"] == {
        "radio_2_4": {"client_count": 7},
        "radio_5": {"client_count": 5},
        "guest": {"client_count": 3, "remaining_minutes": 61},
        "office": {"client_count": 1},
    }


def test_telephony_provider_family_matches_all_observed_provider_codes() -> None:
    """Codes 0/99 are Telekom; any other configured provider wins."""
    telekom = normalize_feature_payload("telephony", {"isp_selection": "99"})
    mixed = normalize_feature_payload(
        "telephony",
        {"isp_selection": ["0", "99", "89"]},
    )

    assert telekom["telephony"]["provider_family"] == "telekom"
    assert mixed["telephony"]["provider_family"] == "other"


def test_public_overview_enums_reject_unknown_firmware_values() -> None:
    """Unknown firmware states stay absent instead of becoming misleading data."""
    normalized = normalize_feature_payload(
        "system",
        {
            "router_state": "FUTURE-MODE",
            "save_fails": "unknown",
            "dyndns_active": "future-status",
        },
    )

    assert "system" not in normalized
    assert "ddns" not in normalized


def test_lan_and_dhcp_exact_octets_create_bounded_read_only_state() -> None:
    """LAN and DHCP pages share one payload without losing either root."""
    raw = {
        "lan_ipv4_1": "192",
        "lan_ipv4_2": "0",
        "lan_ipv4_3": "2",
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
        "lan_ip_v6_pext": "1",
        "lan_ip_v6_arec": "0",
        "lan_dhcp_validtime": "3",
    }

    expected = {
        "lan": {
            "ipv4_address": "192.0.2.1",
            "subnet_mask": "255.255.255.0",
            "ipv6_enabled": True,
            "ula_address": "PRIVATE-IPV6",
            "usable_ipv6_range": "PRIVATE-RANGE",
            "ipv6_pext_flag": True,
            "ipv6_arec_flag": False,
        },
        "dhcp": {
            "enabled": True,
            "pool_start_ipv4": "192.0.2.20",
            "pool_end_ipv4": "192.0.2.200",
            "pool_size": 181,
            "lease_duration_code": 3,
        },
    }
    assert normalize_feature_payload("lan", raw) == expected
    assert normalize_feature_payload("dhcp", raw) == expected
    assert "PRIVATE-IPV6" in repr(expected)


@pytest.mark.parametrize("value", ["", "2", "true", -1, 0.0, 1.0, object()])
def test_lan_undocumented_ipv6_flags_reject_non_firmware_booleans(
    value: object,
) -> None:
    """Undocumented LAN flags stay absent unless firmware sends exact 0 or 1."""
    lan = normalize_feature_payload(
        "lan",
        {"lan_ip_v6_pext": value, "lan_ip_v6_arec": value},
    ).get("lan", {})

    assert "ipv6_pext_flag" not in lan
    assert "ipv6_arec_flag" not in lan


def test_lan_zero_padded_zero_rate_is_disconnected() -> None:
    """Firmware zero-padding cannot turn an unplugged LAN port into connected."""
    port = normalize_feature_payload(
        "lan",
        {"lan1_device": "0000000000"},
    )["lan"]["ports"]["port_1"]

    assert port == {"connected": False, "speed_bps": 0}


def test_lan_modem_link_stays_separate_from_general_port_four() -> None:
    """Modem-role link status cannot overwrite regular LAN port semantics."""
    normalized = normalize_feature_payload(
        "lan",
        {"lan4_device": "0", "lan4_link_status": "1"},
    )

    assert normalized["lan"]["ports"]["port_4"]["connected"] is False
    assert normalized["dsl"]["modem_lan_link"] is True


def test_lan_ports_decode_exact_firmware_link_rates() -> None:
    """The four status fields expose link state and the UI's negotiated rate."""
    normalized = normalize_feature_payload(
        "lan",
        {
            "lan1_device": "2500000000",
            "lan2_device": "1000000000",
            "lan3_device": "200000000",
            "lan4_device": "0",
        },
    )["lan"]

    assert normalized == {
        "linked_port_count": 3,
        "ports": {
            "port_1": {"connected": True, "speed_bps": 2_500_000_000},
            "port_2": {"connected": True, "speed_bps": 1_000_000_000},
            "port_3": {"connected": True, "speed_bps": 200_000_000},
            "port_4": {"connected": False, "speed_bps": 0},
        },
    }


def test_lan_port_unknown_rate_keeps_state_without_inventing_speed() -> None:
    """Unknown future encodings remain connected but omit an unsafe rate."""
    port = normalize_feature_payload("lan", {"lan1_device": "future"})["lan"]["ports"][
        "port_1"
    ]

    assert port == {"connected": True}


@pytest.mark.parametrize("raw", ["9999999999", "299999999", "12345678"])
def test_lan_port_malformed_numeric_rate_keeps_only_link_state(raw: str) -> None:
    """Unreviewed numeric encodings cannot be rounded into a link speed."""
    port = normalize_feature_payload("lan", {"lan1_device": raw})["lan"]["ports"][
        "port_1"
    ]

    assert port == {"connected": True}


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
    assert dect == {
        "dect": {
            "repeater_count": 2,
            "repeaters": [
                {"id": "1", "registered": True},
                {"id": "2", "registered": True},
            ],
        }
    }
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
    """Wi-Fi retains safe settings; shared encryption mirrors to both radios."""
    normalized = normalize_feature_payload(
        "wlan_configuration",
        {
            "use_wlan": "1",
            "wlan_band": "1",
            "wlan_visible": "0",
            "wlan_5ghz_visible": "1",
            "wlan_5ghz_speed_act": "2",
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
            "wlan_guest_display_key": "1",
            "wlan_office_wps": "1",
            "wlan_guest_key": "PRIVATE-GUEST-KEY",
            "wlan_office_ssid": "PRIVATE-OFFICE-SSID",
            "wlan_office_key": "PRIVATE-OFFICE-KEY",
            "wps_pin": "12345670",
        },
    )
    wifi = normalized["wifi"]

    assert wifi["band_mode"] == 1
    assert wifi["allow_all_devices"] is True
    assert wifi["radio_2_4"]["visible"] is False
    assert wifi["radio_2_4"]["encryption_mode"] == 6
    assert wifi["radio_5"]["encryption_mode"] == 6
    assert wifi["encryption_mode"] == 6
    assert wifi["radio_5"]["visible"] is True
    assert wifi["radio_5"]["channel_width_mode"] == "80_mhz"
    assert wifi["guest"]["ssid"] == "PRIVATE-GUEST-SSID"
    assert wifi["guest"]["display_key_enabled"] is True
    assert wifi["office"]["ssid"] == "PRIVATE-OFFICE-SSID"
    assert wifi["office"]["wps_enabled"] is True
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
        "PRIVATE-GUEST-KEY",
        "PRIVATE-OFFICE-KEY",
        "12345670",
    ):
        assert private_value not in rendered


def test_wps_enablement_does_not_claim_an_active_pairing_session() -> None:
    """WLANAccess prerequisites remain distinct from WPSStatus lifecycle."""
    wifi = normalize_feature_payload(
        "wps",
        {
            "use_wlan": "1",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_band": "1",
            "wlan_enc": "1",
            "wlan_visible": "1",
        },
    )["wifi"]

    assert wifi == {
        "wps_enabled": True,
        "wps_disabled_by_firmware": False,
        "wps_start_available": True,
    }


@pytest.mark.parametrize(
    ("firmware_state", "lifecycle"),
    [("-2", "failed"), ("-1", "failed"), ("0", "success"), ("1", "connecting")],
)
def test_wps_transaction_code_maps_to_exact_firmware_lifecycle(
    firmware_state: str,
    lifecycle: str,
) -> None:
    """WPSStatus.json state is the sole proven pairing-lifecycle source."""
    wifi = normalize_feature_payload(
        "wps_status",
        {"wlan_wps_state": firmware_state},
    )["wifi"]

    assert wifi == {
        "wps_status": lifecycle,
        "wps_state_code": int(firmware_state),
    }


@pytest.mark.parametrize("invalid_width", [True, -1, 4, 999, "4", "2 MHz", 2.5])
def test_wifi_channel_width_rejects_unreviewed_firmware_values(
    invalid_width: object,
) -> None:
    """Unknown width codes remain unavailable instead of becoming 160 MHz."""
    normalized = normalize_feature_payload(
        "wlan_configuration", {"wlan_5ghz_speed_act": invalid_width}
    )

    assert "channel_width_mode" not in normalized.get("wifi", {}).get("radio_5", {})


@pytest.mark.parametrize(
    ("raw_width", "expected"),
    [(0, "single_channel"), ("1", "40_mhz"), (2, "80_mhz"), ("3", "160_mhz")],
)
def test_wifi_channel_width_accepts_only_reviewed_codes(
    raw_width: object, expected: str
) -> None:
    """Each reviewed firmware code maps to one exact native enum value."""
    wifi = normalize_feature_payload(
        "wlan_configuration", {"wlan_5ghz_speed_act": raw_width}
    )["wifi"]

    assert wifi["radio_5"]["channel_width_mode"] == expected


@pytest.mark.parametrize(
    "hostname",
    [
        "user:secret@example.net",
        "https://private.example.net/path",
        "private..example.net",
        "private.example.net?token=secret",
    ],
)
def test_dns_rebind_rows_reject_non_hostname_text(hostname: str) -> None:
    """Only strict DNS names may enter the administrator exception list."""
    security = normalize_feature_payload(
        "dns_rebind",
        {"adddnsexcept": [{"hostname": hostname}]},
    )["security"]

    assert security == {
        "dns_rebind_exception_count": 1,
        "dns_rebind_exceptions": [],
    }


def test_guest_wifi_rows_expose_only_safe_band_and_generation_counts() -> None:
    """Ephemeral guest rows become aggregates, never child identities."""
    guest = normalize_feature_payload(
        "wifi",
        {
            "addwgdevice": [
                {"wgdevice_type": "1", "wgdevice_wifi": "4"},
                {"wgdevice_type": "2", "wgdevice_wifi": "6"},
                {"wgdevice_type": "2", "wgdevice_wifi": "6"},
            ]
        },
    )["wifi"]["guest"]

    assert guest == {
        "client_count": 3,
        "radio_2_4_client_count": 1,
        "radio_5_client_count": 2,
        "wifi_4_client_count": 1,
        "wifi_5_client_count": 0,
        "wifi_6_client_count": 2,
    }


@pytest.mark.parametrize(
    ("firmware_value", "expected_allowed"),
    [("0", True), ("1", False)],
)
def test_wlan_allow_all_uses_firmware_ui_inversion(
    firmware_value: str,
    expected_allowed: bool,  # noqa: FBT001
) -> None:
    """The UI's wlan_allow_all flag is inverse to its allow-all presentation."""
    wifi = normalize_feature_payload(
        "wlan_configuration",
        {"wlan_allow_all": firmware_value},
    )["wifi"]

    assert wifi["allow_all_devices"] is expected_allowed


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


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("0", 0),
        ("1", 1),
        ("2", 2),
        ("On", 0),
        ("Timer", 1),
        ("Off", 2),
        (0, 0),
        (1, 1),
        (2, 2),
    ],
)
def test_receiver_led_mode_normalizes_exact_firmware_values(
    raw_value: object,
    expected: int,
) -> None:
    """Both firmware read representations normalize to one stable mode code."""
    assert normalize_feature_payload("receiver_led", {"ex5g_led_mode": raw_value}) == {
        "receiver": {"led_mode": expected}
    }


@pytest.mark.parametrize(
    "raw_value",
    ["on", "timer", "off", "Always", "3", "Timer1", 1.0, True, None],
)
def test_receiver_led_mode_rejects_unproven_representations(
    raw_value: object,
) -> None:
    """Unproven aliases and coercible lookalikes remain absent."""
    assert normalize_feature_payload("receiver_led", {"ex5g_led_mode": raw_value}) == {}


def test_mobile_status_preserves_both_radio_bearers_without_eid() -> None:
    """Exact mobile status codes and both bearer readings remain independent."""
    normalized = normalize_feature_payload(
        "mobile",
        {
            "lte_status": "10",
            "ex5g_signal_5g": "-82.5",
            "ex5g_freq_5g": "NR3500",
            "ex5g_signal_lte": "-97.0",
            "ex5g_freq_lte": "LTE1800",
            "ex5g_model_name": "5G Receiver SE",
            "ex5g_eid": "PRIVATE-EID-VALUE",
        },
    )

    assert normalized["mobile"]["connected"] is True
    assert normalized["mobile"]["status_code"] == 10
    assert normalized["mobile"]["nr"] == {
        "signal_dbm": -82.5,
        "band_code": "NR3500",
    }
    assert normalized["mobile"]["lte"] == {
        "signal_dbm": -97.0,
        "band_code": "LTE1800",
    }
    assert "rsrp_dbm" not in normalized["mobile"]
    assert "band" not in normalized["mobile"]
    assert "network_type" not in normalized["mobile"]
    assert "frequency_mhz" not in normalized["mobile"]
    assert normalized["receiver"] == {
        "model": "5G Receiver SE",
        "esim_supported": True,
    }
    assert "PRIVATE-EID-VALUE" not in repr(normalized)


def test_mobile_failure_code_is_disconnected_and_unknown_code_is_absent() -> None:
    """Only the firmware's exact 10/11 states claim a mobile connection."""
    failure = normalize_feature_payload("mobile", {"lte_status": "20"})["mobile"]
    unknown = normalize_feature_payload("mobile", {"lte_status": "99"})

    assert failure == {"status_code": 20, "connected": False}
    assert "mobile" not in unknown


def test_lte_tunnel_state_does_not_claim_a_mobile_radio_connection() -> None:
    """Bonding transport state remains separate from mobile registration."""
    normalized = normalize_feature_payload("mobile", {"lte_tunnel": "1"})

    assert normalized == {"hybrid": {"lte_tunnel": True}}


def test_zero_nr_sentinel_preserves_valid_lte_bearer() -> None:
    """A firmware zero for NR cannot mask an independently observed LTE bearer."""
    mobile = normalize_feature_payload(
        "mobile",
        {
            "lte_status": "11",
            "ex5g_signal_5g": "0",
            "ex5g_freq_5g": "NR3500",
            "ex5g_signal_lte": "-91",
            "ex5g_freq_lte": "LTE1800",
        },
    )["mobile"]

    assert "nr" not in mobile
    assert mobile["lte"] == {"signal_dbm": -91.0, "band_code": "LTE1800"}
    assert "network_type" not in mobile
    assert "rsrp_dbm" not in mobile
    assert "band" not in mobile


def test_explicit_mobile_summary_fields_remain_independent_from_bearers() -> None:
    """Only dedicated summary varids populate generic mobile radio metrics."""
    mobile = normalize_feature_payload(
        "mobile",
        {
            "ex5g_rsrp": "-88.5",
            "ex5g_band": "n78",
            "mobile_network_type": "5G",
            "ex5g_signal_lte": "-95",
            "ex5g_freq_lte": "LTE1800",
        },
    )["mobile"]

    assert mobile["rsrp_dbm"] == -88.5
    assert mobile["band"] == "n78"
    assert mobile["network_type"] == "5G"
    assert mobile["lte"] == {"signal_dbm": -95.0, "band_code": "LTE1800"}


def test_zero_lte_sentinel_never_becomes_a_signal_reading() -> None:
    """A firmware zero for LTE means no LTE signal, not a perfect signal."""
    mobile = normalize_feature_payload(
        "mobile",
        {"lte_status": "11", "ex5g_signal_lte": "0", "ex5g_freq_lte": "LTE1800"},
    )["mobile"]

    assert "lte" not in mobile
    assert "rsrp_dbm" not in mobile
    assert "band" not in mobile
    assert "network_type" not in mobile


def test_receiver_esim_support_never_retains_the_identifier() -> None:
    """The unsupported sentinel becomes a boolean and no EID is retained."""
    unsupported = normalize_feature_payload("receiver", {"ex5g_eid": "not supported"})

    assert unsupported == {"receiver": {"esim_supported": False}}


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


def test_managed_client_proven_transport_fields_are_retained() -> None:
    """Managed row values retain semantics proven by the firmware UI."""
    normalized = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [
                {
                    "id": "row-1",
                    "mdevice_mac": "AA:BB:CC:DD:EE:FF",
                    "mdevice_ipv4": "192.168.2.40",
                    "mdevice_reservedip": "55",
                    "mdevice_fix_dhcp": "1",
                    "mdevice_downspeed": "1000000000",
                    "mdevice_upspeed": "500000000",
                    "mdevice_wifi": "6",
                    "mdevice_type": "2",
                    "mdevice_ula_ipv6": "fd00::40",
                    "mdevice_gua_ipv6": "2001:db8::40",
                    "mdevice_hasui": "443",
                }
            ]
        },
    )["clients"]["items"][0]

    assert normalized["configured_reserved_ipv4"] == "192.168.2.55"
    assert normalized["reserved_ipv4"] == "192.168.2.55"
    assert normalized["download_link_speed_bps"] == 1_000_000_000
    assert normalized["upload_link_speed_bps"] == 500_000_000
    assert normalized["wifi_generation"] == 6
    assert normalized["medium"] == "wifi_5"
    assert normalized["ipv6_ula"] == "fd00::40"
    assert normalized["ipv6_gua"] == "2001:db8::40"
    assert normalized["has_web_ui"] is True
    assert normalized["web_ui_port"] == 443
    assert normalized["web_ui_scheme"] == "https"
    assert "model" not in normalized
    assert "download_rate_bps" not in normalized
    assert "upload_rate_bps" not in normalized


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", (False, None, None)), ("80", (True, 80, "http"))],
)
def test_client_web_ui_port_contract(
    raw: str,
    expected: tuple[bool, int | None, str | None],
) -> None:
    """Zero disables UI; nonzero port parity selects firmware scheme."""
    client = normalize_feature_payload(
        "clients",
        {"addmdevice": [{"id": "row-1", "mdevice_hasui": raw}]},
    )["clients"]["items"][0]

    assert client.get("has_web_ui") is expected[0]
    assert client.get("web_ui_port") == expected[1]
    assert client.get("web_ui_scheme") == expected[2]


@pytest.mark.parametrize(
    "raw",
    ["443garbage", "x443y", " 443", "+443", "65536", True, 443.0],
)
def test_client_web_ui_port_rejects_malformed_values(raw: object) -> None:
    """Malformed UI-port values cannot become availability or scheme state."""
    client = normalize_feature_payload(
        "clients",
        {"addmdevice": [{"id": "row-1", "mdevice_hasui": raw}]},
    )["clients"]["items"][0]

    assert "has_web_ui" not in client
    assert "web_ui_port" not in client
    assert "web_ui_scheme" not in client


@pytest.mark.parametrize("fixed_dhcp", [None, "0"])
def test_reserved_ipv4_requires_explicit_fixed_dhcp(fixed_dhcp: str | None) -> None:
    """A reserved-address label requires affirmative fixed-DHCP readback."""
    record = {
        "id": "row-1",
        "mdevice_ipv4": "192.168.2.40",
        "mdevice_reservedip": "55",
    }
    if fixed_dhcp is not None:
        record["mdevice_fix_dhcp"] = fixed_dhcp

    normalized = normalize_feature_payload(
        "clients",
        {"addmdevice": [record]},
    )["clients"]["items"][0]

    assert normalized["configured_reserved_ipv4"] == "192.168.2.55"
    assert "reserved_ipv4" not in normalized


def test_wifi_generation_never_implies_radio_band() -> None:
    """Wi-Fi generation is proven, but only the endpoint group proves a band."""
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


def test_explicit_client_bps_fields_remain_distinct() -> None:
    """Explicitly unit-labeled rates and link speeds remain available."""
    client = normalize_feature_payload(
        "clients",
        {
            "device": [
                {
                    "id": "row-1",
                    "download_rate_bps": "80000000",
                    "upload_rate_bps": "12000000",
                    "download_link_speed_bps": "1000000000",
                    "upload_link_speed_bps": "500000000",
                }
            ]
        },
    )["clients"]["items"][0]

    assert client["download_rate_bps"] == 80_000_000
    assert client["upload_rate_bps"] == 12_000_000
    assert client["download_link_speed_bps"] == 1_000_000_000
    assert client["upload_link_speed_bps"] == 500_000_000


def test_mesh_exact_topology_fields_are_bounded() -> None:
    """Mesh topology retains status and speed semantics proven by the UI."""
    mesh = normalize_feature_payload(
        "mesh",
        {
            "addmeshdevice": [
                {
                    "id": "mesh-1",
                    "mesh_connect_to": "r",
                    "mesh_device_type": "2",
                    "mesh_type": "2",
                    "mesh_downspeed": "1200000000",
                    "mesh_upspeed": "600000000",
                    "mesh_ipv4": "192.168.2.2",
                    "mesh_mac_wlan": "AA-BB-CC-DD-EE-01",
                    "mesh_mac_wlan5": "AA-BB-CC-DD-EE-02",
                    "mesh_lan1": "1000000000",
                    "mesh_lan2": "0",
                    "mesh_use_wlan": "1",
                }
            ],
            "addmdevice": [
                {"id": "client-1", "mdevice_connected": "1", "mdevice_slave": "mesh-1"},
                {"id": "client-2", "mdevice_connected": "0", "mdevice_slave": "mesh-1"},
            ],
        },
    )["mesh"]["nodes"][0]

    assert mesh == {
        "id": "mesh-1",
        "parent": "r",
        "medium": "wifi_5",
        "device_type": 2,
        "ipv4": "192.168.2.2",
        "wifi_2_4_mac": "AA:BB:CC:DD:EE:01",
        "wifi_5_mac": "AA:BB:CC:DD:EE:02",
        "wifi_enabled": True,
        "download_link_speed_bps": 1_200_000_000,
        "upload_link_speed_bps": 600_000_000,
        "linked_lan_port_count": 1,
        "lan_port_1_speed_bps": 1_000_000_000,
        "lan_port_2_speed_bps": 0,
        "client_count": 1,
    }


@pytest.mark.parametrize(
    ("firmware_value", "expected_enabled"),
    [("0", True), ("1", True), ("2", False)],
)
def test_mesh_wifi_state_uses_firmware_ui_semantics(
    firmware_value: str,
    expected_enabled: bool,  # noqa: FBT001
) -> None:
    """The firmware UI treats only mesh_use_wlan=2 as disabled."""
    node = normalize_feature_payload(
        "mesh",
        {
            "addmeshdevice": [
                {
                    "id": "mesh-1",
                    "mesh_use_wlan": firmware_value,
                }
            ]
        },
    )["mesh"]["nodes"][0]

    assert node["wifi_enabled"] is expected_enabled


def test_usb_tethering_and_nas_keep_admin_inventory_without_credentials() -> None:
    """USB/NAS keeps bounded inventory while excluding paths and credentials."""
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
        "storage_device_count": 1,
        "storage_items": [
            {
                "serial": "PRIVATE-DISK-SERIAL",
                "name": "PRIVATE-DISK-NAME",
                "storage_type": "NAS",
                "total_bytes": 2_097_152,
                "used_bytes": 524_288,
                "free_bytes": 1_572_864,
            }
        ],
        "storage_total_bytes": 2_097_152,
        "storage_used_bytes": 524_288,
        "storage_free_bytes": 1_572_864,
    }
    rendered = repr(nas)
    for private_value in (
        "/PRIVATE/PATH",
        "PRIVATE-NAS-USER",
    ):
        assert private_value not in rendered


def test_security_and_qos_management_expose_bounded_read_only_rules() -> None:
    """Policy rows are exact while unassociated client identity stays absent."""
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
            "addextendedrule": [
                {
                    "id": "PRIVATE-RULE-1",
                    "extendedrule_active": "1",
                    "extrule_tcp": "80,443",
                    "extrule_udp": "53",
                    "extrarule_pc_7": "PRIVATE-CLIENT-SCOPE",
                },
                {
                    "id": "PRIVATE-RULE-2",
                    "extendedrule_active": "0",
                    "extrule_tcp": "PRIVATE-PORT-LIST",
                },
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

    assert dns == {
        "dns_rebind_exception_count": 2,
        "dns_rebind_exceptions": [
            {"domain": "private-a.example"},
            {"domain": "private-b.example"},
        ],
    }
    assert blocking == {
        "port_block_rule_count": 2,
        "active_port_block_rule_count": 1,
        "port_block_rules": [
            {
                "rule_group": "extended",
                "id": "PRIVATE-RULE-1",
                "active": True,
                "tcp_ports": "80,443",
                "udp_ports": "53",
            },
            {"rule_group": "extended", "id": "PRIVATE-RULE-2", "active": False},
        ],
    }
    assert qos == {
        "prioritized_client_count": 1,
        "prioritized_clients": [
            {"slot": 1, "prioritized": True},
            {"slot": 2, "prioritized": False},
        ],
    }
    rendered = repr({"dns": dns, "blocking": blocking, "qos": qos})
    for private_value in (
        "PRIVATE-CLIENT-SCOPE",
        "PRIVATE-PORT-LIST",
        "PRIVATE-QOS-HOST",
        "AA:BB:CC:DD:EE:FF",
    ):
        assert private_value not in rendered


@pytest.mark.parametrize(
    "invalid_ports",
    ["65536", "443-80", "80-", "53,alice@example.net"],
)
def test_port_block_lists_reject_malformed_or_out_of_range_values(
    invalid_ports: str,
) -> None:
    """Untrusted rule text cannot masquerade as a valid port list."""
    security = normalize_feature_payload(
        "portblocking",
        {
            "addextendedrule": [
                {
                    "id": "rule-1",
                    "extendedrule_active": "1",
                    "extrule_tcp": invalid_ports,
                    "extrule_udp": invalid_ports,
                }
            ]
        },
    )["security"]

    assert security["port_block_rules"] == [
        {"rule_group": "extended", "id": "rule-1", "active": True}
    ]


def test_port_block_rule_families_are_aggregated_consistently() -> None:
    """Extended and extra rule families contribute to one exact summary."""
    security = normalize_feature_payload(
        "portblocking",
        {
            "addextendedrule": [
                {"id": "shared", "extendedrule_active": "1", "extrule_tcp": "443"}
            ],
            "addextra": [
                {"id": "shared", "child_extrarule_active": "0", "extrule_udp": "53"}
            ],
        },
    )["security"]

    assert security == {
        "port_block_rule_count": 2,
        "active_port_block_rule_count": 1,
        "port_block_rules": [
            {
                "rule_group": "extended",
                "id": "shared",
                "active": True,
                "tcp_ports": "443",
            },
            {
                "rule_group": "extra",
                "id": "shared",
                "active": False,
                "udp_ports": "53",
            },
        ],
    }


def test_wifi_environment_stays_fail_closed_without_an_observed_row_schema() -> None:
    """Plausible WLAN scan labels never become a fabricated contract."""
    assert (
        normalize_feature_payload(
            "wifi_environment",
            {
                "ssid": "PRIVATE-NEIGHBOUR",
                "channel": 11,
                "signal": -72,
                "rows": [{"name": "PRIVATE-NEIGHBOUR", "active": True}],
            },
        )
        == {}
    )


@pytest.mark.parametrize(
    "family",
    [
        "wifi_environment",
        "mesh_firmware",
        "mesh_update",
        "mesh_reboot_status",
        "dect_settings",
        "analog",
        "logs",
        "system_services",
        "energy",
    ],
)
def test_inventory_only_families_cannot_leak_through_generic_normalization(
    family: str,
) -> None:
    """Unproven response fields remain absent until explicitly allowlisted."""
    assert (
        normalize_feature_payload(
            family,
            {
                "use_wlan": "1",
                "firmware_version": "PRIVATE-VALUE",
                "message": "PRIVATE-MESSAGE",
            },
        )
        == {}
    )


def test_dns_and_qos_administrator_rows_have_hard_size_bounds() -> None:
    """Router-controlled policy collections cannot grow the admin model forever."""
    dns = normalize_feature_payload(
        "dns_rebind",
        {
            "adddnsexcept": [
                {"hostname": f"service-{index}.example"} for index in range(300)
            ]
        },
    )["security"]
    qos = normalize_feature_payload(
        "qos",
        {"qos_pc": [str(index % 2) for index in range(300)]},
    )["qos"]

    assert dns["dns_rebind_exception_count"] == 300
    assert len(dns["dns_rebind_exceptions"]) == 256
    assert qos["prioritized_client_count"] == 150
    assert len(qos["prioritized_clients"]) == 256
    assert qos["prioritized_clients"][-1] == {
        "slot": 256,
        "prioritized": True,
    }


def test_port_forward_admin_details_use_exact_nested_mapping_fields() -> None:
    """Nested TCP/UDP fields produce bounded summaries without changing identity."""
    rule = normalize_feature_payload(
        "nat",
        {
            "addportuw": [
                {
                    "id": "rule-1",
                    "portuw_name": "Web services",
                    "portuw_active": "1",
                    "portuw_device": "PRIVATE-TARGET",
                    "addtcpportuw": {
                        "tcp_public_from": ["443", "8000"],
                        "tcp_public_to": ["443", "8005"],
                        "tcp_private_dest": ["443", "9000"],
                    },
                    "addudpportuw": {
                        "udp_public_from": "53",
                        "udp_public_to": "53",
                        "udp_private_dest": "53",
                    },
                }
            ]
        },
    )["nat"]["port_forward_rules"][0]

    assert rule["id"] == "rule-1"
    assert rule["name"] == "Web services"
    assert rule["active"] is True
    assert rule["target"] == "PRIVATE-TARGET"
    assert rule["tcp_mappings"] == "443 -> 443, 8000-8005 -> 9000"
    assert rule["udp_mappings"] == "53 -> 53"
    assert isinstance(rule["_identity_fingerprint"], str)


def test_port_forward_rule_inventory_is_bounded() -> None:
    """Router-controlled forwarding rows and identifiers have hard limits."""
    nat = normalize_feature_payload(
        "nat",
        {
            "addportuw": [
                {"id": str(index), "portuw_name": f"Rule {index}"}
                for index in range(300)
            ]
        },
    )["nat"]

    assert len(nat["port_forward_rules"]) == 256
    assert nat["port_forward_rules"][-1]["id"] == "255"
    assert (
        normalize_feature_payload(
            "nat",
            {"addportuw": [{"id": "x" * 257, "portuw_name": "oversized"}]},
        )
        == {}
    )


def test_telephony_management_keeps_admin_rows_without_numbers_or_credentials() -> None:
    """DECT, PBX, and VoIP keep bounded status rows, never contact secrets."""
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
            "addphonenumber": [
                {"status": "failed", "voip_errnr": "005"},
                {"status": "ok", "voip_errnr": "000"},
            ],
            "contact_name": "PRIVATE-CONTACT",
            "call_record": "PRIVATE-CALL-RECORD",
        },
    )["telephony"]

    assert dect["enabled"] is True
    assert dect["scan_active"] is False
    assert dect["handset_count"] == 2
    assert dect["repeater_count"] == 1
    assert dect["repeaters"] == [{"id": "PRIVATE-REPEATER-ID", "registered": True}]
    assert pbx == {
        "enabled": True,
        "configured_client_count": 3,
        "clients": [
            {
                "id": "PRIVATE-PBX-ID-1",
                "status": "registered",
                "ipv4": "192.0.2.10",
            },
            {"id": "PRIVATE-PBX-ID-2", "status": "locked"},
            {"id": "PRIVATE-PBX-ID-3", "status": "disconnected"},
        ],
        "disconnected_client_count": 1,
        "registered_client_count": 1,
        "locked_client_count": 1,
    }
    assert telephony == {
        "voip_possible": True,
        "voip_policy": 2,
        "provider_count": 1,
        "providers": [{"id": "PRIVATE-PROVIDER-ID"}],
        "numbers": [],
        "registered_number_count": 2,
        "configured_number_count": 2,
        "registered_voip_number_count": 1,
        "inactive_voip_number_count": 1,
        "failed_line_count": 1,
        "warning_voip_number_count": 0,
    }
    rendered = repr({"dect": dect, "pbx": pbx, "telephony": telephony})
    for private_value in (
        "PRIVATE-DECT-PIN",
        "PRIVATE-PBX-PASSWORD",
        "PRIVATE-PHONE-1",
        "PRIVATE-CONTACT",
        "PRIVATE-CALL-RECORD",
    ):
        assert private_value not in rendered


def test_exact_automatic_telephony_families_publish_only_safe_rows() -> None:
    """Exact automatic endpoint families reach their reviewed normalizers."""
    telephony = normalize_feature_payload(
        "voip_providers",
        {
            "addipphoneprovider": [
                {
                    "id": "provider-1",
                    "isp_selection": "42",
                    "provider_name": "PRIVATE-PROVIDER-NAME",
                    "username": "PRIVATE-VOIP-USERNAME",
                    "password": "PRIVATE-VOIP-PASSWORD",
                    "phone_number": "+49 30 123456",
                }
            ]
        },
    )["telephony"]
    pbx = normalize_feature_payload(
        "pbx_clients",
        {
            "addipclient": [
                {
                    "id": "client-1",
                    "ipclient_status": "1",
                    "ipclient_mdevice_name": "Desk phone",
                    "ipclient_mdevice_ipv4": "192.168.2.10",
                    "ipclient_mdevice_mac": "AA-BB-CC-DD-EE-FF",
                    "ipclient_username": "PRIVATE-PBX-USERNAME",
                    "ipclient_password": "PRIVATE-PBX-PASSWORD",
                }
            ]
        },
    )["pbx"]

    assert telephony == {
        "provider_count": 1,
        "providers": [{"id": "provider-1", "provider_code": 42}],
    }
    assert pbx["configured_client_count"] == 1
    assert pbx["clients"] == [
        {
            "id": "client-1",
            "status": "registered",
            "name": "Desk phone",
            "ipv4": "192.168.2.10",
            "mac": "AA:BB:CC:DD:EE:FF",
        }
    ]
    rendered = repr((telephony, pbx))
    for secret in (
        "PRIVATE-PROVIDER-NAME",
        "PRIVATE-VOIP-USERNAME",
        "PRIVATE-VOIP-PASSWORD",
        "+49 30 123456",
        "PRIVATE-PBX-USERNAME",
        "PRIVATE-PBX-PASSWORD",
    ):
        assert secret not in rendered


def test_voip_error_code_requires_opaque_stable_line_identity() -> None:
    """A status error may attach only to a non-dialable stable line row."""
    lines = normalize_feature_payload(
        "telephony",
        {
            "addphonenumber": [
                {"id": "line-1", "status": "failed", "voip_errnr": "005"},
                {"id": "+4930123456", "status": "failed", "voip_errnr": "006"},
            ]
        },
    )["telephony"]["numbers"]

    assert lines == [{"id": "line-1", "call_state": "failed", "error_code": "005"}]


def test_client_admin_fields_retain_port_but_never_construct_web_ui_url() -> None:
    """Client inventory exposes proven port metadata, never a clickable URL."""
    client = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [
                {
                    "id": "client-1",
                    "mdevice_connected": "1",
                    "mdevice_standards": "IEEE 802.11ax",
                    "mdevice_hasui": "443",
                    "mdevice_ui_url": "https://192.0.2.99:443/private",
                }
            ]
        },
    )["clients"]["items"][0]

    assert client["wifi_standard"] == "IEEE 802.11ax"
    assert client["has_web_ui"] is True
    assert client["web_ui_port"] == 443
    assert client["web_ui_scheme"] == "https"
    assert "192.0.2.99" not in repr(client)


def test_powerline_inventory_is_bounded_and_topology_private() -> None:
    """Powerline rows keep only admin topology and proven link rates."""
    rows = [
        {
            "pwline_name": f"Adapter {index}",
            "pwline_connect_to": "AA:BB:CC:DD:EE:FF",
            "pwline_downspeed": "750000",
            "pwline_upspeed": "250000",
            "pwline_password": "PRIVATE-POWERLINE-PASSWORD",
        }
        for index in range(300)
    ]
    rows[0]["pwline_name"] = "x" * 257
    rows[0]["pwline_connect_to"] = "FF:FF:FF:FF:FF:FF"
    rows[0].update(
        {
            "id": "powerline-1",
            "pwline_manufacturer": "Devolo",
            "pwline_mac": "AA:BB:CC:DD:EE:FF",
            "pwline_firmware": "1.2.3",
            "pwline_mode": "mesh",
        }
    )

    nodes = normalize_feature_payload(
        "clients",
        {"addpwlinedevice": rows},
    )["powerline"]["nodes"]

    assert len(nodes) == 256
    assert "name" not in nodes[0]
    assert "parent" not in nodes[0]
    assert nodes[0]["id"] == "powerline-1"
    assert nodes[0]["manufacturer"] == "Devolo"
    assert nodes[0]["mac"] == "AA:BB:CC:DD:EE:FF"
    assert nodes[0]["firmware"] == "1.2.3"
    assert nodes[0]["mode"] == "mesh"
    assert nodes[0]["download_link_speed_bps"] == 750_000_000
    assert nodes[0]["upload_link_speed_bps"] == 250_000_000
    assert "PRIVATE-POWERLINE-PASSWORD" not in repr(nodes)


def test_voip_lines_keep_status_not_phone_numbers() -> None:
    """VoIP rows retain opaque status metadata but never dialable numbers."""
    telephony = normalize_feature_payload(
        "telephony",
        {
            "addipphoneprovider": [
                {"id": "provider-1", "isp_selection": "99"},
            ],
            "addipnumber": [
                {
                    "id": "line-1",
                    "ip_number": "+49 30 123456",
                    "number_status": "warning",
                    "isp_selection": "99",
                    "template_id": "provider-1",
                    "connection_failure_code": "403",
                    "connection_failure_reason": "registration rejected",
                    "sip_password": "PRIVATE-SIP-PASSWORD",
                },
                {"id": "line-2", "number_status": "unexpected"},
                {"id": "+49 30 123456", "number_status": "ok"},
            ],
        },
    )["telephony"]

    assert telephony["providers"] == [{"id": "provider-1", "provider_code": 99}]
    assert telephony["numbers"] == [
        {
            "id": "line-1",
            "status": "warning",
            "provider_code": 99,
            "provider_id": "provider-1",
            "error_code": "403",
        },
        {"id": "line-2"},
    ]
    assert "+49 30 123456" not in repr(telephony)
    assert "registration rejected" not in repr(telephony)
    assert "PRIVATE-SIP-PASSWORD" not in repr(telephony)


@pytest.mark.parametrize(
    "error_code",
    [
        "alice@example.net",
        "user:secret",
        "registration rejected",
        "403\nprivate",
    ],
)
def test_voip_failure_code_rejects_identity_or_prose(error_code: str) -> None:
    """Only short opaque error tokens may enter telephony runtime data."""
    lines = normalize_feature_payload(
        "telephony",
        {"addipnumber": [{"id": "line-1", "connection_failure_code": error_code}]},
    )["telephony"]["numbers"]

    assert lines == [{"id": "line-1"}]


def test_voip_failure_code_accepts_reviewed_opaque_token_grammar() -> None:
    """Short alphanumeric dotted and dashed codes remain readable."""
    lines = normalize_feature_payload(
        "telephony",
        {"addipnumber": [{"id": "line-1", "connection_failure_code": "SIP-4.03"}]},
    )["telephony"]["numbers"]

    assert lines == [{"id": "line-1", "error_code": "SIP-4.03"}]


def test_collection_empty_and_unknown_enums_remain_explicit() -> None:
    """Observed empty lists stay empty; unknown firmware enums stay absent."""
    telephony = normalize_feature_payload(
        "telephony",
        {"addipphoneprovider": [], "addipnumber": []},
    )["telephony"]
    pbx = normalize_feature_payload(
        "pbx",
        {"addipclient": [{"id": "client-1", "ipclient_status": "9"}]},
    )["pbx"]

    assert telephony["providers"] == []
    assert telephony["numbers"] == []
    assert pbx["clients"] == [{"id": "client-1"}]


def test_nas_admin_inventory_excludes_credentials() -> None:
    """NAS inventory retains share state while withholding credentials."""
    usb = normalize_feature_payload(
        "nas",
        {
            "addnasdevice": [
                {
                    "serial": "DISK-SERIAL-1",
                    "nas_device_name": "Backup SSD",
                    "nas_device_type": "NAS",
                    "nas_device_connection": "USB",
                    "nas_device_total": "4096",
                    "nas_device_used": "1024",
                }
            ],
            "addnasmediareplay": [
                {"mediareplay_active": "1", "path": "/private/media"},
                {"mediareplay_active": "0", "path": "/private/archive"},
            ],
            "nas_active": "1",
            "sid": "share-1",
            "nas_folder_name": "/mnt/backup",
            "nas_folder_nur_lesen": "1",
            "nas_secure": "1",
            "nas_user_name": "PRIVATE-NAS-USER",
            "nas_user_pwd": "PRIVATE-NAS-PASSWORD",
        },
    )["usb"]

    assert usb["storage_items"] == [
        {
            "serial": "DISK-SERIAL-1",
            "name": "Backup SSD",
            "storage_type": "NAS",
            "connection": "USB",
            "total_bytes": 4_194_304,
            "used_bytes": 1_048_576,
            "free_bytes": 3_145_728,
        }
    ]
    assert usb["media_share_count"] == 2
    assert usb["active_media_share_count"] == 1
    assert usb["shares"] == [
        {
            "id": "share-1",
            "name": "/mnt/backup",
            "enabled": True,
            "read_only": True,
            "secure": True,
        }
    ]
    rendered = repr(usb)
    assert "/mnt/backup" in rendered
    assert "/private/media" not in rendered
    assert "PRIVATE-NAS-USER" not in rendered
    assert "PRIVATE-NAS-PASSWORD" not in rendered


def test_nas_folder_flags_stay_scoped_to_an_identified_share() -> None:
    """Folder configuration cannot impersonate global NAS/USB state."""
    normalized = normalize_feature_payload(
        "nas_folders",
        {
            "nas_active": "1",
            "sid": "share-1",
            "nas_folder_name": "/mnt/backup",
            "nas_folder_nur_lesen": "1",
            "nas_secure": "1",
        },
    )

    assert normalized == {
        "usb": {
            "shares": [
                {
                    "id": "share-1",
                    "name": "/mnt/backup",
                    "enabled": True,
                    "read_only": True,
                    "secure": True,
                }
            ]
        }
    }


def test_nas_folder_empty_sentinel_does_not_create_phantom_share() -> None:
    """The firmware's flat -1 sentinel is an explicit empty inventory."""
    assert normalize_feature_payload(
        "nas_folders",
        {
            "sid": "-1",
            "nas_active": "1",
            "nas_folder_nur_lesen": "1",
            "nas_secure": "1",
        },
    ) == {"usb": {"shares": []}}


def test_media_server_normalizer_is_scoped_to_safe_summary_counts() -> None:
    """Media detail contributes safe counts without claiming NAS-device fields."""
    normalized = normalize_feature_payload(
        "media_server",
        {
            "use_media_server": "1",
            "addnasmediareplay": [
                {"mediareplay_active": "1", "path": "/private/media"},
                {"mediareplay_active": "0", "path": "/private/archive"},
            ],
            "use_usb": "0",
            "nas_active": "1",
            "addnasdevice": [{"nas_device_name": "Must not leak"}],
            "nas_user_pwd": "PRIVATE-NAS-PASSWORD",
        },
    )

    assert normalized == {
        "usb": {
            "media_server_enabled": True,
            "media_share_count": 2,
            "active_media_share_count": 1,
        }
    }


def test_vpn_rows_derive_connection_without_retaining_address_or_secrets() -> None:
    """VPN rows expose name/state only; assigned addresses and keys stay absent."""
    vpn = normalize_feature_payload(
        "vpn_details",
        {
            "addvpn": [
                {
                    "id": "peer-1",
                    "vpn_name": "Road warrior",
                    "vpn_status": "1",
                    "vpn_userip": "192.0.2.50",
                    "vpn_password": "PRIVATE-VPN-PASSWORD",
                    "vpn_key": "PRIVATE-VPN-KEY",
                },
                {
                    "id": "peer-2",
                    "vpn_name": "Tablet",
                    "vpn_status": "0",
                    "vpn_userip": "",
                },
            ]
        },
    )["vpn"]

    assert vpn["peers"] == [
        {
            "id": "peer-1",
            "name": "Road warrior",
            "enabled": True,
            "connected": True,
        },
        {"id": "peer-2", "name": "Tablet", "enabled": False, "connected": False},
    ]
    assert vpn["connected_peer_count"] == 1
    rendered = repr(vpn)
    assert "192.0.2.50" not in rendered
    assert "PRIVATE-VPN-PASSWORD" not in rendered
    assert "PRIVATE-VPN-KEY" not in rendered


def test_admin_identifiers_fail_closed_for_unreviewed_shapes() -> None:
    """Malformed or identity-like private values never pass exact field parsers."""
    mesh = normalize_feature_payload(
        "mesh",
        {
            "addmeshdevice": [
                {
                    "id": "mesh-1",
                    "mesh_mac_wlan": "not-a-mac",
                    "mesh_mac_wlan5": {"unexpected": "shape"},
                }
            ]
        },
    )["mesh"]["nodes"][0]
    vpn = normalize_feature_payload(
        "vpn_details",
        {"addvpn": [{"id": "x" * 300, "vpn_status": "1"}]},
    )["vpn"]["peers"][0]
    telephony = normalize_feature_payload(
        "telephony",
        {
            "addipnumber": [
                {
                    "id": "line-1",
                    "template_id": "+49 30 123456",
                    "number_status": "ok",
                }
            ]
        },
    )["telephony"]["numbers"][0]
    usb = normalize_feature_payload(
        "nas",
        {
            "addnasdevice": [{"nas_device_name": "Disk", "serial": "x" * 300}],
            "addnasfolder": [{"nas_folder_name": "Share", "sid": "x" * 300}],
        },
    )["usb"]

    assert "wifi_2_4_mac" not in mesh
    assert "wifi_5_mac" not in mesh
    assert "id" not in vpn
    assert "provider_id" not in telephony
    assert "serial" not in usb["storage_items"][0]
    assert "id" not in usb["shares"][0]


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


def test_dect_paging_and_phonebook_count_are_privacy_safe() -> None:
    """Paging and the exact list count remain while contact data is withheld."""
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
    assert dect["phonebook_entry_count"] == 42
    assert "PRIVATE-CONTACT" not in repr(dect)
    assert "PRIVATE-NUMBER" not in repr(dect)


def test_dect_info_and_exact_handset_group_are_read_only_status() -> None:
    """Exact firmware status fields expose inventory, scanning, and paging."""
    inventory = normalize_feature_payload(
        "dect",
        {"adddect": [{"id": "1", "dect_name": "Office"}]},
    )["dect"]
    status = normalize_feature_payload(
        "dect_status",
        {
            "DECT_real_count": "1",
            "dect_detect_status": "0",
            "PagingStat1": "1",
            "PagingStat2": "0",
        },
    )["dect"]

    assert inventory["handsets"] == [{"id": "1", "name": "Office"}]
    assert status == {
        "scan_active": False,
        "handset_count": 1,
        "paging_handset_count": 1,
        "paging_active": True,
    }


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
