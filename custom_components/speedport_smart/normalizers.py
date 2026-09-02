"""
Normalize observed Speedport varid payloads for platform consumption.

This module is deliberately transport independent. It accepts decoded mappings
from the protocol layer and emits only canonical, privacy-safe fields consumed
by Home Assistant platforms. Unknown and missing values remain absent.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from .const import MANAGED_DEVICE_FORM_FIELDS, MANAGED_DEVICE_SOURCE_KINDS
from .identity import port_forward_rule_fingerprint

if TYPE_CHECKING:
    from .models import RouterStatus

NormalizedData = dict[str, Any]
Parser = Callable[[Any], Any | None]

_EMPTY: Final = (None, "")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_MAC = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
_DNS_LABEL = re.compile(r"(?i)^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_QOS_PC_SLOT = re.compile(r"^qos_pc\[(\d+)\]$")
_MIN_PHONE_LABEL_DIGITS: Final = 5
_MIN_BNG_CODE_LENGTH: Final = 2
_INTERNET_FAILURE_REASONS: Final = frozenset({"user", "net", "dsl", "router"})
_SECONDS_PER_MINUTE: Final = 60
_NAS_VALUE_BYTES: Final = 1_024
_TETHERING_CONNECTED_STATUS: Final = 2
_MAX_CLOCK_HOUR: Final = 23
_MAX_CLOCK_MINUTE: Final = 59
_MAX_TCP_PORT: Final = 65_535
_PORT_RANGE_LENGTH: Final = 2
_MAX_FIRMWARE_VERSION_LENGTH: Final = 64
_MAX_COLLECTION_ROWS: Final = 256
_MAX_COLLECTION_TEXT_LENGTH: Final = 256
_MAX_ADDRESS_TEXT_LENGTH: Final = 128
_MAX_DNS_NAME_LENGTH: Final = 253
_LAN_LINK_SPEEDS_BPS: Final = frozenset(
    {0, 10_000_000, 100_000_000, 200_000_000, 1_000_000_000, 2_500_000_000}
)
_IPV4_MAX_OCTET: Final = 255
_IPV4_PREFIX_OCTETS: Final = 3
_DDNS_REGISTERED_STATUS: Final = 2
_MESH_WLAN_DISABLED: Final = 2
_WIFI_CHANNEL_WIDTH_40_MHZ: Final = 1
_WIFI_CHANNEL_WIDTH_80_MHZ: Final = 2
_WIFI_CHANNEL_WIDTH_160_MHZ: Final = 3
_ROUTER_OPERATING_MODES: Final = {
    "OK": "normal",
    "THROWN": "thrown",
    "MODEM": "modem",
    "TR64": "tr64",
    "TR69": "tr69",
    "EMCALL": "emergency_call",
    "DECTUPD": "dect_update",
    "BOTNET": "botnet_protection",
}
_MOBILE_STATUS_CODES: Final = frozenset(
    {10, 11, 20, 21, 22, 23, 25, 30, 31, 32, 40, 50}
)
_MOBILE_CONNECTED_STATUS_CODES: Final = frozenset({10, 11})
_CLIENT_MEDIUM_CODES: Final = {
    0: "lan",
    1: "wifi_2_4",
    2: "wifi_5",
    4: "wifi_office",
}
_NR_BAND_CODES: Final = frozenset(
    {
        "NR2100",
        "NR1800",
        "NR2600",
        "NR900",
        "NR800",
        "NR700",
        "NR1427",
        "NR1432",
        "NR3500",
    }
)
_LTE_BAND_CODES: Final = frozenset(
    {"LTE2100", "LTE1800", "LTE2600", "LTE900", "LTE800", "LTE700", "LTE1500"}
)
_WIFI_SCHEDULE_DAYS: Final = (
    ("mo", "monday"),
    ("di", "tuesday"),
    ("mi", "wednesday"),
    ("do", "thursday"),
    ("fr", "friday"),
    ("sa", "saturday"),
    ("so", "sunday"),
)

# Values with these names must never enter normalized runtime data. The list is
# intentionally broad; platforms do not need any of them.
_SECRET_TOKENS: Final = (
    "credential",
    "imei",
    "imsi",
    "password",
    "passwd",
    "private_key",
    "psk",
    "puk",
    "secret",
    "sip_auth",
    "sip_password",
    "token",
    "wireguard_key",
    "wlan_key",
    "wpa_key",
)

# Exact firmware fields that must never enter normalized runtime data even when
# their names do not contain a generic secret token. These are subscriber or
# authenticated-session metadata, not router-management state.
_FORBIDDEN_RAW_FIELDS: Final = frozenset(
    {
        "loginstate",
        "t_callident",
        "t_number",
        "t_password",
    }
)

_CLIENT_GROUPS: Final = {
    "addmdevice": None,
    "addmpriodevice": None,
    "addmwlandevice": "wifi_2_4",
    "addmwlan5device": "wifi_5",
    "addmlandevice": "lan",
    "mdevice": None,
    "device": None,
}

_CALL_GROUPS: Final = {
    "adddialedcalls": "outgoing",
    "addmissedcalls": "missed",
    "addtakencalls": "incoming",
}
_WPS_WEP_ENCRYPTION: Final = 2
_WPS_WPA3_ENCRYPTION: Final = 6

_MANAGEMENT_SCOPED_FAMILIES: Final = frozenset(
    {
        "connection_privacy",
        "analog",
        "dect_settings",
        "dect_repeater",
        "dns_rebind",
        "easy_support",
        "firmware",
        "energy",
        "logs",
        "mesh_firmware",
        "mesh_reboot_status",
        "mesh_update",
        "mesh_topology",
        "media_server",
        "nas",
        "port_blocking",
        "qos",
        "system_services",
        "usb_tethering",
        "wifi_access",
        "wifi_configuration",
        "wifi_environment",
        "wifi_schedule",
        "wps",
        "wps_status",
        "receiver_led",
        "vpn_details",
    }
)


def normalize_status_payload(
    status: RouterStatus,
) -> tuple[NormalizedData, frozenset[str]]:
    """
    Normalize typed public status plus observed flat status varids.

    Returned capabilities are inferred only from values that exist in the
    payload. WAN counters are not inferred here because they come from ToTR64.
    """
    result = _normalize_known_flat(status.raw)
    view = _view(status.raw)

    router = _without_missing(
        {
            "model": status.info.model,
            "firmware": status.info.firmware,
            "serial_number": status.info.serial_number,
            "hardware_version": status.info.hardware_version,
        }
    )
    internet = _without_missing(
        {
            "state": _state(status.internet_state),
            "download_capacity_bps": status.wan_download_capacity_bps,
            "upload_capacity_bps": status.wan_upload_capacity_bps,
            "failure_reason": _first(
                view,
                ("fail_reason",),
                _internet_failure_reason,
            ),
        }
    )
    dsl = _without_missing(
        {
            "state": _state(status.dsl_state),
            "downstream_bps": status.dsl_downstream_bps,
            "upstream_bps": status.dsl_upstream_bps,
        }
    )
    _merge_root(result, "router", router)
    _merge_root(result, "internet", internet)
    _merge_root(result, "dsl", dsl)
    domain_name = _bounded_technical_text(view.get("domain_name"))
    if domain_name is not None:
        _merge_root(result, "system", {"domain_name": domain_name})

    capabilities = frozenset(
        root
        for root, payload in result.items()
        if root != "router" and isinstance(payload, Mapping) and payload
    )
    if router:
        capabilities = capabilities | {"system"}
    return result, capabilities


def normalize_feature_payload(
    family: str,
    raw: Mapping[str, Any],
) -> NormalizedData:
    """Normalize one decoded feature payload into canonical root mappings."""
    safe_raw = _safe_mapping(raw)
    canonical = _canonical_family(family)
    normalized = (
        {}
        if canonical in _MANAGEMENT_SCOPED_FAMILIES
        else _normalize_known_flat(safe_raw)
    )

    handlers: dict[str, Callable[[Mapping[str, Any]], NormalizedData]] = {
        "internet": _normalize_internet,
        "connection_privacy": _normalize_connection_privacy,
        "dsl": _normalize_dsl,
        "hybrid": _normalize_hybrid,
        "mobile": _normalize_mobile,
        "wifi": _normalize_wifi,
        "wifi_access": _normalize_wifi,
        "wifi_configuration": _normalize_wifi,
        "wifi_schedule": _normalize_wifi_schedule,
        "wps": _normalize_wps_prerequisites,
        "wps_status": _normalize_wps_status,
        "mesh": _normalize_mesh,
        "mesh_topology": _normalize_mesh,
        "lan": _normalize_lan,
        "dhcp": _normalize_dhcp,
        "clients": _normalize_clients,
        "nat": _normalize_nat,
        "ddns": _normalize_ddns,
        "vpn": _normalize_vpn,
        "vpn_details": _normalize_vpn_details,
        "parental": _normalize_parental,
        "telephony": _normalize_telephony,
        "pbx": _normalize_pbx,
        "dect": _normalize_dect,
        "dect_status": _normalize_dect,
        "dect_repeater": _normalize_dect_repeater,
        "receiver": _normalize_receiver,
        "receiver_led": _normalize_receiver_led,
        "security": _normalize_security,
        "dns_rebind": _normalize_security,
        "port_blocking": _normalize_security,
        "qos": _normalize_qos,
        "wifi_environment": _normalize_wifi_environment,
        "usb": _normalize_usb,
        "media_server": _normalize_media_server,
        "nas": _normalize_usb,
        "nas_folders": _normalize_nas_folders,
        "usb_tethering": _normalize_usb,
        "system": _normalize_system,
        "easy_support": _normalize_system,
        "firmware": _normalize_system,
        "diagnostics": _normalize_diagnostics,
    }
    handler = handlers.get(canonical)
    if handler is not None:
        normalized = _deep_merge(normalized, handler(safe_raw))
    return normalized


def _canonical_family(family: str) -> str:
    normalized = family.strip().casefold().replace("-", "_")
    aliases = {
        "5g": "mobile",
        "active_calls": "telephony",
        "calls": "telephony",
        "internet_privacy": "connection_privacy",
        "firewall": "security",
        "ip": "internet",
        "ip_phones": "pbx",
        "lte": "mobile",
        "nas_storage": "nas",
        "phonebook": "dect",
        "portblocking": "port_blocking",
        "port_forwarding": "nat",
        "upnp": "nat",
        "wifi_access_control": "wifi_access",
        "wlan_access": "wifi_access",
        "wlan_configuration": "wifi_configuration",
        "wireguard": "vpn",
    }
    return aliases.get(normalized, normalized)


def _normalize_known_flat(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize unambiguous prefixed varids found across status endpoints."""
    view = _view(raw)
    result: NormalizedData = {}

    internet = _fields(
        view,
        {
            "state": (("onlinestatus", "online_status", "inet_status"), _text),
            "download_capacity_bps": (
                ("inet_download", "internet_download_bps"),
                _bps,
            ),
            "upload_capacity_bps": (
                ("inet_upload", "internet_upload_bps"),
                _bps,
            ),
            "ipv4_address": (
                ("public_ip_v4", "inet_ipv4", "wan_ipv4"),
                _public_address,
            ),
            "ipv6_prefix": (
                ("public_ip_v6", "inet_ipv6_prefix", "wan_ipv6_prefix"),
                _public_address,
            ),
            "mtu": (("inet_mtu", "wan_mtu"), _integer),
            "ip_stack": (("dualstack",), _text),
            "privacy_level": (("privacy_policy",), _privacy_level),
            "provisioning_code": (("provis_inet",), _provisioning_code),
            "bng_configured": (("provis_inet",), _bng_configured),
            "provider_family": (("inet_isp",), _internet_provider_family),
            "error_code": (("inet_errnr",), _bounded_error_code),
        },
    )
    uptime_seconds = _online_uptime_seconds(view)
    if uptime_seconds is not None:
        internet["uptime_seconds"] = uptime_seconds
    connected_since = _first(
        view,
        ("inet_uptime",),
        _internet_connected_since,
    )
    if connected_since is not None:
        internet["connected_since"] = connected_since
    _merge_root(result, "internet", internet)
    _merge_root(result, "dsl", _dsl_fields(view, include_generic=False))
    _merge_root(result, "hybrid", _hybrid_fields(view, include_generic=False))
    _merge_root(result, "mobile", _mobile_fields(view, include_generic=False))
    _merge_root(result, "wifi", _wifi_fields(view))
    _merge_root(result, "mesh", _mesh_fields(view))
    _merge_root(result, "lan", _lan_fields(view))
    _merge_root(result, "dhcp", _dhcp_fields(raw, view))
    _merge_root(result, "dect", _dect_fields(view))
    _merge_root(result, "pbx", _pbx_fields(view))
    _merge_root(
        result,
        "telephony",
        _fields(
            view,
            {
                "hd_voice_active": (("hdvoice",), _nonzero_boolean),
                "provisioning_code": (("provis_voip",), _provisioning_code),
                "manual_configuration_available": (
                    ("provis_voip",),
                    _manual_telephony_configuration,
                ),
            },
        ),
    )
    telephony_provider = _telephony_provider_family_from_view(view)
    if telephony_provider is not None:
        _merge_root(
            result,
            "telephony",
            {"provider_family": telephony_provider},
        )
    _merge_root(result, "vpn", _vpn_fields(view, include_generic=False))
    _merge_root(result, "system", _system_fields(view))
    _merge_root(result, "security", _security_fields(view))
    parental_enabled = _first(view, ("internet_timerule_active",), _boolean)
    if parental_enabled is not None:
        _merge_root(result, "parental", {"enabled": parental_enabled})
    ddns_status = _first(
        view,
        ("dyndns_active", "dyndns_status"),
        _ddns_status_code,
    )
    if ddns_status is not None:
        _merge_root(
            result,
            "ddns",
            {
                "status_code": ddns_status,
                "connected": ddns_status == _DDNS_REGISTERED_STATUS,
            },
        )
    _merge_root(result, "receiver", _receiver_status_fields(view))
    smarthome_linked = _first(view, ("smarthome_status",), _boolean)
    if smarthome_linked is not None:
        _merge_root(result, "smarthome", {"linked": smarthome_linked})
    return result


def _normalize_internet(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    internet = _fields(
        view,
        {
            "state": (
                ("state", "status", "online", "connected", "connection_status"),
                _state,
            ),
            "download_capacity_bps": (
                ("download_capacity_bps", "downstream_bps", "download_rate"),
                _bps,
            ),
            "upload_capacity_bps": (
                ("upload_capacity_bps", "upstream_bps", "upload_rate"),
                _bps,
            ),
            "uptime_seconds": (("uptime", "uptime_seconds", "online_time"), _seconds),
            "ipv4_address": (
                ("ipv4_address", "public_ip", "public_ip_v4"),
                _public_address,
            ),
            "ipv6_prefix": (
                ("ipv6_prefix", "public_ip_v6"),
                _public_address,
            ),
            "mtu": (("mtu",), _integer),
            "privacy_level": (
                ("lan_privacy_policy", "privacy_policy"),
                _privacy_level,
            ),
            "provisioning_code": (("provis_inet",), _provisioning_code),
            "bng_configured": (("provis_inet",), _bng_configured),
            "provider_family": (
                ("inet_isp", "isp"),
                _internet_provider_family,
            ),
            "error_code": (("inet_errnr",), _bounded_error_code),
        },
    )
    return {"internet": internet} if internet else {}


def _normalize_connection_privacy(raw: Mapping[str, Any]) -> NormalizedData:
    privacy_level = _first(
        _view(raw),
        ("lan_privacy_policy", "privacy_policy"),
        _privacy_level,
    )
    if privacy_level is None:
        return {}
    return {"internet": {"privacy_level": privacy_level}}


def _normalize_dsl(raw: Mapping[str, Any]) -> NormalizedData:
    dsl = _dsl_fields(_view(raw), include_generic=True)
    return {"dsl": dsl} if dsl else {}


def _dsl_fields(view: Mapping[str, Any], *, include_generic: bool) -> NormalizedData:
    aliases: dict[str, tuple[tuple[str, ...], Parser]] = {
        "state": (("dsl_link_status", "dsl_status", "dsl_state"), _state),
        "downstream_bps": (
            ("dsl_downstream", "dsl_downstream_bps", "dsl_ds_rate"),
            _bps,
        ),
        "upstream_bps": (
            ("dsl_upstream", "dsl_upstream_bps", "dsl_us_rate"),
            _bps,
        ),
        "attainable_downstream_bps": (
            ("dsl_attainable_downstream", "dsl_max_downstream", "dsl_ds_attainable"),
            _bps,
        ),
        "attainable_upstream_bps": (
            ("dsl_attainable_upstream", "dsl_max_upstream", "dsl_us_attainable"),
            _bps,
        ),
        "snr_downstream_db": (
            ("dsl_snr_downstream", "dsl_ds_snr", "dsl_down_snr"),
            _number_value,
        ),
        "snr_upstream_db": (
            ("dsl_snr_upstream", "dsl_us_snr", "dsl_up_snr"),
            _number_value,
        ),
        "attenuation_downstream_db": (
            ("dsl_attenuation_downstream", "dsl_ds_attenuation"),
            _number_value,
        ),
        "attenuation_upstream_db": (
            ("dsl_attenuation_upstream", "dsl_us_attenuation"),
            _number_value,
        ),
        "crc_errors": (("dsl_crc_errors", "dsl_crc"), _integer),
        "fec_errors": (("dsl_fec_errors", "dsl_fec"), _integer),
        "error_seconds": (("dsl_error_seconds", "dsl_es"), _integer),
        "profile": (("dsl_profile", "dsl_line_profile"), _text),
        "error_code": (("dsl_errnr",), _bounded_error_code),
    }
    if include_generic:
        aliases = {
            **aliases,
            "state": (aliases["state"][0] + ("state", "status"), _state),
            "downstream_bps": (
                aliases["downstream_bps"][0] + ("downstream", "downstream_bps"),
                _bps,
            ),
            "upstream_bps": (
                aliases["upstream_bps"][0] + ("upstream", "upstream_bps"),
                _bps,
            ),
        }
    return _fields(view, aliases)


def _normalize_hybrid(raw: Mapping[str, Any]) -> NormalizedData:
    hybrid = _hybrid_fields(_view(raw), include_generic=True)
    return {"hybrid": hybrid} if hybrid else {}


def _hybrid_fields(view: Mapping[str, Any], *, include_generic: bool) -> NormalizedData:
    connected: tuple[str, ...] = (
        "hybrid_connected",
        "hybrid_status",
        "hybrid_tunnel",
        "bonding_status",
    )
    enabled: tuple[str, ...] = ("use_bonding", "use_hybrid")
    if include_generic:
        connected += ("connected", "status")
        enabled += ("enabled",)
    return _fields(
        view,
        {
            "connected": (connected, _boolean_or_state),
            "enabled": (enabled, _boolean),
            "dsl_tunnel": (("dsl_tunnel", "dsl_tunnel_status"), _boolean_or_state),
            "lte_tunnel": (("lte_tunnel", "lte_tunnel_status"), _boolean_or_state),
            "lte_tunnel_bytes_received": (
                ("lte_tunnel_bytes_received", "lte_bytes_received"),
                _integer,
            ),
            "lte_tunnel_bytes_sent": (
                ("lte_tunnel_bytes_sent", "lte_bytes_sent"),
                _integer,
            ),
        },
    )


def _normalize_mobile(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    mobile = _mobile_fields(view, include_generic=True)
    receiver = _receiver_status_fields(view)
    result: NormalizedData = {}
    if mobile:
        result["mobile"] = mobile
    if receiver:
        result["receiver"] = receiver
    return result


def _mobile_fields(view: Mapping[str, Any], *, include_generic: bool) -> NormalizedData:
    aliases: dict[str, tuple[tuple[str, ...], Parser]] = {
        "connected": (
            (
                "mobile_connected",
                "lte_connected",
                "ex5g_status",
            ),
            _boolean_or_state,
        ),
        "network_type": (
            ("mobile_network_type", "network_type", "radio_access_type"),
            _text,
        ),
        "operator": (
            ("mobile_operator", "lte_operator", "ex5g_operator"),
            _text,
        ),
        "rsrp_dbm": (
            (
                "ex5g_rsrp",
                "ex5g_5g_rsrp",
                "ex5g_lte_rsrp",
                "mobile_rsrp",
            ),
            _number_value,
        ),
        "rsrq_db": (
            ("ex5g_rsrq", "ex5g_5g_rsrq", "ex5g_lte_rsrq", "mobile_rsrq"),
            _number_value,
        ),
        "sinr_db": (
            ("ex5g_sinr", "ex5g_5g_sinr", "ex5g_lte_sinr", "mobile_sinr"),
            _number_value,
        ),
        "rssi_dbm": (
            ("ex5g_rssi", "ex5g_5g_rssi", "ex5g_lte_rssi", "mobile_rssi"),
            _number_value,
        ),
        "band": (
            (
                "ex5g_band",
                "lte_band",
                "mobile_band",
            ),
            _text,
        ),
        "frequency_mhz": (
            (
                "ex5g_frequency",
                "lte_frequency",
                "mobile_frequency",
            ),
            _number_value,
        ),
        "cell_id": (("ex5g_cell_id", "lte_cell_id", "mobile_cell_id"), _text),
    }
    if include_generic:
        aliases = {
            **aliases,
            "connected": (
                aliases["connected"][0] + ("connected", "status"),
                _boolean_or_state,
            ),
            "network_type": (aliases["network_type"][0] + ("technology",), _text),
            "operator": (aliases["operator"][0] + ("operator",), _text),
            "rsrp_dbm": (aliases["rsrp_dbm"][0] + ("rsrp",), _number_value),
            "rsrq_db": (aliases["rsrq_db"][0] + ("rsrq",), _number_value),
            "sinr_db": (aliases["sinr_db"][0] + ("sinr",), _number_value),
            "rssi_dbm": (aliases["rssi_dbm"][0] + ("rssi",), _number_value),
            "band": (aliases["band"][0] + ("band",), _text),
            "frequency_mhz": (
                aliases["frequency_mhz"][0] + ("frequency",),
                _number_value,
            ),
            "cell_id": (aliases["cell_id"][0] + ("cell_id",), _text),
        }
    mobile = _fields(view, aliases)
    status_code = _first(view, ("lte_status",), _mobile_status_code)
    if status_code is not None:
        mobile["status_code"] = status_code
        mobile["connected"] = status_code in _MOBILE_CONNECTED_STATUS_CODES
    nr: NormalizedData = {}
    nr_signal = _first(view, ("ex5g_signal_5g",), _nonzero_number_value)
    if nr_signal is not None:
        nr["signal_dbm"] = nr_signal
        nr_band = _first(view, ("ex5g_freq_5g",), _nr_band_code)
        if nr_band is not None:
            nr["band_code"] = nr_band
    lte: NormalizedData = {}
    lte_signal = _first(view, ("ex5g_signal_lte",), _nonzero_number_value)
    if lte_signal is not None:
        lte["signal_dbm"] = lte_signal
        lte_band = _first(view, ("ex5g_freq_lte",), _lte_band_code)
        if lte_band is not None:
            lte["band_code"] = lte_band
    if nr:
        mobile["nr"] = nr
    if lte:
        mobile["lte"] = lte
    return mobile


def _normalize_wifi(raw: Mapping[str, Any]) -> NormalizedData:
    wifi = _wifi_fields(_view(raw))
    return {"wifi": wifi} if wifi else {}


def _normalize_wps_prerequisites(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize only stable WPS start prerequisites from WLANAccess.json."""
    view = _view(raw)
    if not view:
        return {}
    wps_enabled = _first(view, ("use_wps",), _boolean)
    disabled_by_firmware = _first(view, ("disabled_wps",), _boolean)
    wifi_enabled = _first(view, ("use_wlan",), _boolean)
    band_mode = _first(view, ("wlan_band",), _wifi_band_mode)
    visible_2_4 = _first(view, ("wlan_visible",), _boolean)
    visible_5 = _first(view, ("wlan_5ghz_visible",), _boolean)
    encryption_mode = _first(view, ("wlan_enc",), _nonnegative_integer)
    guest_enabled = _first(view, ("wlan_guest_active",), _boolean)
    guest_wps_enabled = _first(view, ("wlan_guest_wps",), _boolean)
    guest_encryption_mode = _first(view, ("wlan_guest_enc",), _nonnegative_integer)

    wifi = _without_missing(
        {
            "wps_enabled": wps_enabled,
            "wps_disabled_by_firmware": disabled_by_firmware,
        }
    )
    reason: str | None
    prerequisite = (wps_enabled, disabled_by_firmware, wifi_enabled, band_mode)
    if any(value is None for value in prerequisite):
        reason = "wps_prerequisite_unavailable"
    elif disabled_by_firmware:
        reason = "disabled_by_firmware"
    elif not wps_enabled:
        reason = "disabled_by_setting"
    elif not wifi_enabled:
        reason = "wifi_off"
    elif encryption_mode is None:
        reason = "wps_prerequisite_unavailable"
    elif encryption_mode == _WPS_WEP_ENCRYPTION:
        reason = "incompatible_encryption"
    else:
        active_visibility = tuple(
            visible
            for active, visible in (
                (band_mode in {0, 1}, visible_2_4),
                (band_mode in {0, 2}, visible_5),
            )
            if active
        )
        main_visible = (
            True
            if any(visible is True for visible in active_visibility)
            else False
            if all(visible is False for visible in active_visibility)
            else None
        )
        guest_prerequisite = (
            guest_enabled,
            guest_wps_enabled,
            guest_encryption_mode,
        )
        guest_required = (
            encryption_mode == _WPS_WPA3_ENCRYPTION or main_visible is not True
        )
        if guest_required and any(value is None for value in guest_prerequisite):
            reason = "wps_prerequisite_unavailable"
        elif (
            all(value is not None for value in guest_prerequisite)
            and guest_enabled
            and guest_wps_enabled
            and guest_encryption_mode != _WPS_WPA3_ENCRYPTION
        ):
            reason = (
                "incompatible_encryption"
                if guest_encryption_mode == _WPS_WEP_ENCRYPTION
                else None
            )
        elif encryption_mode == _WPS_WPA3_ENCRYPTION:
            reason = "incompatible_encryption"
        elif main_visible is None:
            reason = "wps_prerequisite_unavailable"
        elif not main_visible:
            reason = "ssid_hidden"
        else:
            reason = None
    wifi["wps_start_available"] = reason is None
    if reason is not None:
        wifi["wps_unavailable_reason"] = reason
    return {"wifi": wifi}


def _normalize_wps_status(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize WPSStatus.json lifecycle; its empty response is idle."""
    view = _view(raw)
    if not view:
        return {"wifi": {"wps_status": "idle"}}
    state_code = _first(view, ("wlan_wps_state",), _wps_state_code)
    if state_code is None:
        return {}
    return {
        "wifi": {
            "wps_state_code": state_code,
            "wps_status": {
                -2: "failed",
                -1: "failed",
                0: "success",
                1: "connecting",
            }[state_code],
        }
    }


def _normalize_wifi_schedule(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize only schedule fields owned by the detail endpoint."""
    schedule = _wifi_schedule_fields(_view(raw))
    if not schedule:
        return {}
    wifi: NormalizedData = {"schedule": schedule}
    mode = schedule.get("mode")
    if isinstance(mode, int):
        wifi["schedule_enabled"] = mode != 0
    return {"wifi": wifi}


def _wifi_fields(view: Mapping[str, Any]) -> NormalizedData:
    wifi = _fields(
        view,
        {
            "enabled": (
                ("use_wlan", "wlan_active", "wlan_enabled", "wifi_enabled"),
                _boolean,
            ),
            "mac_filter_enabled": (("wlan_mac_active",), _boolean),
            "schedule_enabled": (("wlan_time_active",), _boolean),
            "band_mode": (("wlan_band",), _wifi_band_mode),
        },
    )
    # wlan_access.js presents the inverse of this firmware form flag.
    wlan_allow_all = _first(view, ("wlan_allow_all",), _boolean)
    if wlan_allow_all is not None:
        wifi["allow_all_devices"] = not wlan_allow_all
    radio_2_4 = _fields(
        view,
        {
            "enabled": (
                (
                    "use_wlan_2ghz",
                    "wlan_2_4_active",
                    "wlan_24_enabled",
                ),
                _boolean,
            ),
            "channel": (
                (
                    "wlan_channel_act",
                    "wlan_channel",
                    "wlan_2_4_channel",
                    "channel_2_4",
                ),
                _integer,
            ),
            "client_count": (
                ("wlan_client_count", "wlan_2_4_client_count", "wlan1_num"),
                _integer,
            ),
            "visible": (("wlan_visible",), _boolean),
            "ssid": (("wlan_ssid",), _bounded_collection_text),
            "encryption_mode": (("wlan_enc",), _nonnegative_integer),
        },
    )
    radio_5 = _fields(
        view,
        {
            "enabled": (
                (
                    "use_wlan_5ghz",
                    "wlan_5_active",
                    "wlan_5_enabled",
                ),
                _boolean,
            ),
            "channel": (
                (
                    "wlan_5ghz_channel_act",
                    "wlan_5ghz_channel",
                    "wlan_5_channel",
                    "channel_5",
                ),
                _integer,
            ),
            "client_count": (
                ("wlan_5ghz_client_count", "wlan_5_client_count", "wlan0_num"),
                _integer,
            ),
            "visible": (("wlan_5ghz_visible",), _boolean),
            "ssid": (("wlan_5ghz_ssid",), _bounded_collection_text),
            "encryption_mode": (("wlan_enc",), _nonnegative_integer),
            "channel_width_mode": (
                ("wlan_5ghz_speed_act",),
                _wifi_channel_width_mode,
            ),
        },
    )
    global_enabled = wifi.get("enabled")
    band_mode = _first(view, ("wlan_band",), _integer)
    if isinstance(global_enabled, bool):
        band_2_4_disabled = 2
        band_5_disabled = 1
        radio_2_4.setdefault(
            "enabled", global_enabled and band_mode != band_2_4_disabled
        )
        radio_5.setdefault("enabled", global_enabled and band_mode != band_5_disabled)
    guest = _fields(
        view,
        {
            "enabled": (("wlan_guest_active", "guest_enabled"), _boolean),
            "client_count": (("wlan_guest_client_count",), _integer),
            "remaining_minutes": (("wlan_guest_timeleft",), _nonnegative_integer),
            "ssid": (("wlan_guest_ssid",), _bounded_collection_text),
            "encryption_mode": (("wlan_guest_enc",), _nonnegative_integer),
            "wps_enabled": (("wlan_guest_wps",), _boolean),
            "display_key_enabled": (("wlan_guest_display_key",), _boolean),
        },
    )
    office = _fields(
        view,
        {
            "enabled": (("wlan_office_active", "office_enabled"), _boolean),
            "client_count": (("wlan_office_client_count",), _integer),
            "ssid": (("wlan_office_ssid",), _bounded_collection_text),
            "encryption_mode": (("wlan_office_enc",), _nonnegative_integer),
            "wps_enabled": (("wlan_office_wps",), _boolean),
        },
    )
    if "client_count" not in guest:
        guest_count = _collection_count(view, ("addwgdevice",))
        if guest_count is not None:
            guest["client_count"] = guest_count
    guest_2_4_count = _collection_enum_count(
        view,
        ("addwgdevice",),
        ("wgdevice_type",),
        parser=_integer,
        expected=1,
    )
    if guest_2_4_count is not None:
        guest["radio_2_4_client_count"] = guest_2_4_count
        if isinstance(guest.get("client_count"), int):
            guest["radio_5_client_count"] = max(
                guest["client_count"] - guest_2_4_count,
                0,
            )
    for generation in (4, 5, 6):
        generation_count = _collection_enum_count(
            view,
            ("addwgdevice",),
            ("wgdevice_wifi", "wifi"),
            parser=_integer,
            expected=generation,
        )
        if generation_count is not None:
            guest[f"wifi_{generation}_client_count"] = generation_count
    if "client_count" not in office:
        office_count = _collection_enum_count(
            view,
            ("addmpriodevice",),
            ("mdevice_connected", "connected"),
            parser=_boolean,
            expected=True,
        )
        if office_count is not None:
            office["client_count"] = office_count
    schedule = _wifi_schedule_fields(view)
    if schedule:
        wifi["schedule"] = schedule
        if "schedule_enabled" not in wifi and "mode" in schedule:
            wifi["schedule_enabled"] = schedule["mode"] != 0
    # Smart 4R firmware exposes one main-WLAN encryption selector shared by
    # both radios. The per-radio values are presentation mirrors, not evidence
    # of independently configurable 2.4 GHz and 5 GHz encryption modes.
    main_encryption = _first(view, ("wlan_enc",), _nonnegative_integer)
    if main_encryption is not None:
        wifi["encryption_mode"] = main_encryption
    if radio_2_4:
        wifi["radio_2_4"] = radio_2_4
    if radio_5:
        wifi["radio_5"] = radio_5
    if guest:
        wifi["guest"] = guest
    if office:
        wifi["office"] = office
    return wifi


def _wifi_schedule_fields(view: Mapping[str, Any]) -> NormalizedData:
    """Return only constrained schedule metadata proven by wlan_basic.js."""
    schedule = _fields(
        view,
        {
            "mode": (("wlan_timerule",), _wifi_schedule_mode),
            "daily_from": (("wlan_dfrom",), _clock_time),
            "daily_to": (("wlan_dto",), _clock_time),
        },
    )
    weekly: NormalizedData = {}
    for firmware_day, canonical_day in _WIFI_SCHEDULE_DAYS:
        window = _fields(
            view,
            {
                "from": ((f"wlan_time_{firmware_day}_from",), _clock_time),
                "to": ((f"wlan_time_{firmware_day}_to",), _clock_time),
            },
        )
        if window:
            weekly[canonical_day] = window
    if weekly:
        schedule["weekly"] = weekly
        schedule["weekly_day_count"] = len(weekly)
    return schedule


def _normalize_mesh(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    mesh = _mesh_fields(view)
    nodes = _normalize_stable_devices(
        raw,
        ("addmeshdevice", "addmanageddevice", "mesh_nodes", "nodes"),
        kind="mesh",
    )
    if nodes:
        clients = _client_records(raw)
        mesh_links_observed = any("mesh_node" in client for client in clients)
        if mesh_links_observed:
            for node in nodes:
                identifier = node.get("id")
                if identifier is None:
                    continue
                node["client_count"] = sum(
                    client.get("connected") is True
                    and str(client.get("mesh_node")) == str(identifier)
                    for client in clients
                )
        mesh["nodes"] = nodes
    else:
        count = _first(view, ("mesh_node_count", "node_count"), _integer)
        if count is not None:
            mesh["nodes"] = count
    client_count = _first(view, ("mesh_client_count", "client_count"), _integer)
    if client_count is not None:
        mesh["client_count"] = client_count
    return {"mesh": mesh} if mesh else {}


def _mesh_fields(view: Mapping[str, Any]) -> NormalizedData:
    return _fields(
        view,
        {
            "enabled": (("mesh_exist", "mesh_enabled", "use_mesh"), _boolean),
        },
    )


def _normalize_lan(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    lan = _lan_fields(view)
    dhcp = _dhcp_fields(raw, view)
    result: NormalizedData = {}
    if lan:
        result["lan"] = lan
    if dhcp:
        result["dhcp"] = dhcp
    modem_lan_link = _first(view, ("lan4_link_status",), _boolean)
    if modem_lan_link is not None:
        result["dsl"] = {"modem_lan_link": modem_lan_link}
    return result


def _lan_fields(view: Mapping[str, Any]) -> NormalizedData:
    linked = 0
    observed = False
    ports: NormalizedData = {}
    for port in range(1, 5):
        raw_value = view.get(f"lan{port}_device")
        if raw_value is None:
            continue
        observed = True
        connected = _port_has_device(raw_value)
        if connected:
            linked += 1
        port_data: NormalizedData = {"connected": connected}
        speed_bps = _lan_link_speed_bps(raw_value)
        if speed_bps is not None:
            port_data["speed_bps"] = speed_bps
        ports[f"port_{port}"] = port_data
    lan: NormalizedData = {}
    if observed:
        lan["linked_port_count"] = linked
        lan["ports"] = ports
    explicit = _first(view, ("linked_port_count", "lan_linked_ports"), _integer)
    if explicit is not None:
        lan["linked_port_count"] = explicit
    ipv4_address = _dotted_octets(view, "lan_ipv4", first_default=None)
    if ipv4_address is not None:
        lan["ipv4_address"] = ipv4_address
    subnet_mask = _dotted_octets(view, "lan_mask", first_default=255)
    if subnet_mask is not None:
        lan["subnet_mask"] = subnet_mask
    ipv6_enabled = _first(view, ("lan_ip_v6_used",), _boolean)
    if ipv6_enabled is not None:
        lan["ipv6_enabled"] = ipv6_enabled
    ula_address = _first(view, ("lan_ip_v6",), _private_address)
    if ula_address is not None:
        lan["ula_address"] = ula_address
    usable_ipv6_range = _first(view, ("lan_ip_v6_range",), _private_address)
    if usable_ipv6_range is not None:
        lan["usable_ipv6_range"] = usable_ipv6_range
    ipv6_pext_flag = _first(view, ("lan_ip_v6_pext",), _binary_option)
    if ipv6_pext_flag is not None:
        lan["ipv6_pext_flag"] = ipv6_pext_flag
    ipv6_arec_flag = _first(view, ("lan_ip_v6_arec",), _binary_option)
    if ipv6_arec_flag is not None:
        lan["ipv6_arec_flag"] = ipv6_arec_flag
    return lan


def _normalize_dhcp(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    dhcp = _dhcp_fields(raw, view)
    lan = _lan_fields(view)
    result: NormalizedData = {}
    if dhcp:
        result["dhcp"] = dhcp
    if lan:
        result["lan"] = lan
    return result


def _dhcp_fields(raw: Mapping[str, Any], view: Mapping[str, Any]) -> NormalizedData:
    """Normalize DHCP state and a private pool derived from LAN octets."""
    dhcp = _fields(
        view,
        {
            "enabled": (
                ("lan_use_dhcp", "use_dhcp", "dhcp_enabled", "dhcp_active"),
                _boolean,
            ),
        },
    )
    lease_count = _collection_count(raw, ("addlease", "leases", "dhcp_leases"))
    if lease_count is None:
        lease_count = _first(view, ("lease_count", "dhcp_lease_count"), _integer)
    if lease_count is not None:
        dhcp["leases"] = lease_count
    prefix = _lan_ipv4_prefix(view)
    pool_from = _first(view, ("lan_dhcp_from",), _ipv4_octet)
    pool_to = _first(view, ("lan_dhcp_to",), _ipv4_octet)
    if prefix is not None and pool_from is not None:
        dhcp["pool_start_ipv4"] = f"{prefix}.{pool_from}"
    if prefix is not None and pool_to is not None:
        dhcp["pool_end_ipv4"] = f"{prefix}.{pool_to}"
    if pool_from is not None and pool_to is not None and pool_to >= pool_from:
        dhcp["pool_size"] = pool_to - pool_from + 1
    lease_duration_code = _first(
        view,
        ("lan_dhcp_validtime",),
        _nonnegative_integer,
    )
    if lease_duration_code is not None:
        dhcp["lease_duration_code"] = lease_duration_code
    return dhcp


def _normalize_clients(raw: Mapping[str, Any]) -> NormalizedData:
    items = _client_records(raw)
    powerline_nodes = _normalize_powerline_nodes(raw)
    if not items:
        empty_result: NormalizedData = {}
        if _collection_observed_empty(
            raw,
            _CLIENT_GROUPS,
            prefixes=("mdevice_", "device_"),
        ):
            empty_result["clients"] = {"items": [], "connected_count": 0}
        if powerline_nodes is not None:
            empty_result["powerline"] = {"nodes": powerline_nodes}
        return empty_result
    clients: NormalizedData = {"items": items}
    if any("connected" in item for item in items):
        clients["connected_count"] = sum(
            item.get("connected") is True for item in items
        )
    result: NormalizedData = {"clients": clients}
    wifi = _wifi_counts_from_clients(items)
    if wifi:
        result["wifi"] = wifi
    if any(item.get("medium") == "lan" for item in items):
        result["lan"] = {
            "linked_port_count": sum(
                item.get("connected") is True and item.get("medium") == "lan"
                for item in items
            )
        }
    if powerline_nodes is not None:
        result["powerline"] = {"nodes": powerline_nodes}
    return result


def _client_records(raw: Mapping[str, Any]) -> list[NormalizedData]:
    records: list[NormalizedData] = []
    view = _view(raw)
    for group, medium in _CLIENT_GROUPS.items():
        group_value = view.get(group)
        if group_value is None:
            continue
        for candidate in _records(group_value):
            normalized = _normalize_client_record(
                candidate,
                medium,
                source_kind=(group if group in MANAGED_DEVICE_SOURCE_KINDS else None),
            )
            if normalized:
                records.append(normalized)

    # Some firmwares expose parallel mdevice_* or device_* columns.
    for prefix in ("mdevice_", "device_"):
        columns = {
            key.removeprefix(prefix): value
            for key, value in view.items()
            if key.startswith(prefix)
        }
        for candidate in _records(columns):
            normalized = _normalize_client_record(candidate, None, source_kind=None)
            if normalized:
                records.append(normalized)
    return _deduplicate_client_records(records)


def _normalize_client_record(
    record: Mapping[str, Any],
    medium: str | None,
    *,
    source_kind: str | None,
) -> NormalizedData:
    view = _record_view(record)
    identifier = _stable_identifier(view)
    if identifier is None:
        return {}
    return _without_missing(
        {
            "id": identifier,
            "source_kind": source_kind,
            "source_row_id": _first(view, ("id",), _text),
            "managed_form_supported": (
                True if _managed_form_supported(record, source_kind) else None
            ),
            "mac": _first(view, ("mac", "mac_address", "device_mac"), _mac_address),
            "hostname": _first(view, ("hostname", "host_name"), _text),
            "name": _first(view, ("name", "device_name"), _text),
            "fixed_dhcp": _first(
                view,
                ("fix_dhcp", "fixed_dhcp"),
                _boolean,
            ),
            "uses_dhcp": _first(view, ("use_dhcp",), _boolean),
            "uses_rule": _first(view, ("use_rule",), _integer),
            "manufacturer": _first(
                view,
                ("manufacturer", "vendor", "maker"),
                _text,
            ),
            "model": _client_model(view),
            "firmware": _first(
                view,
                ("firmware", "firmware_version", "sw_version", "version"),
                _text,
            ),
            "hardware_version": _first(
                view,
                ("hardware_version", "hw_version"),
                _text,
            ),
            "ipv4": _first(view, ("ipv4", "ip", "ip_address"), _private_address),
            "configured_reserved_ipv4": _managed_configured_reserved_ipv4(view),
            "reserved_ipv4": _managed_reserved_ipv4(view),
            "ipv6": _first(view, ("ipv6",), _private_address),
            "ipv6_ula": _first(view, ("ula_ipv6",), _private_address),
            "ipv6_gua": _first(view, ("gua_ipv6",), _private_address),
            "connected": _first(
                view,
                ("connected", "online", "active", "present"),
                _boolean,
            ),
            "medium": medium or _client_medium(view),
            # devices.js maps mdevice_wifi 4/5/6 to the matching Wi-Fi icon.
            "wifi_generation": _first(view, ("wifi",), _wifi_generation),
            "wifi_standard": _first(
                view,
                ("standards", "mdevice_standards"),
                _bounded_collection_text,
            ),
            # The firmware value is a local UI port, not a URL. Retain only
            # whether a UI exists so no endpoint details enter runtime data.
            "has_web_ui": _first(
                view,
                ("hasui", "mdevice_hasui"),
                _client_has_web_ui,
            ),
            "web_ui_port": _first(
                view,
                ("hasui", "mdevice_hasui"),
                _client_web_ui_port,
            ),
            "web_ui_scheme": _first(
                view,
                ("hasui", "mdevice_hasui"),
                _client_web_ui_scheme,
            ),
            "signal_dbm": _first(view, ("rssi", "signal", "signal_dbm"), _number_value),
            "link_speed_bps": _first(
                view,
                ("link_speed_bps", "speed_bps", "speed"),
                _bps,
            ),
            "download_rate_bps": _first(
                view,
                (
                    "download_rate_bps",
                    "download_rate",
                    "down_rate",
                    "rx_rate",
                ),
                _bps,
            ),
            "upload_rate_bps": _first(
                view,
                (
                    "upload_rate_bps",
                    "upload_rate",
                    "up_rate",
                    "tx_rate",
                ),
                _bps,
            ),
            "download_link_speed_bps": _first(
                view,
                # devices.js renders mdevice_downspeed through calcSpeed(), whose
                # base unit is bit/s.
                ("download_link_speed_bps", "downlink_speed_bps", "downspeed"),
                _bps,
            ),
            "upload_link_speed_bps": _first(
                view,
                ("upload_link_speed_bps", "uplink_speed_bps", "upspeed"),
                _bps,
            ),
            "bytes_received": _first(
                view,
                ("bytes_received", "received_bytes", "rx_bytes"),
                _integer,
            ),
            "bytes_sent": _first(
                view,
                ("bytes_sent", "sent_bytes", "tx_bytes"),
                _integer,
            ),
            "access_point": _first(view, ("access_point", "ap_name"), _text),
            "mesh_node": _first(view, ("mesh_node", "slave"), _text),
            "band": _first(
                view,
                ("band", "radio_band", "frequency_band", "wlan_band"),
                _text,
            ),
            "channel": _first(
                view,
                ("channel", "wifi_channel", "wlan_channel"),
                _integer,
            ),
            "last_seen": _first(view, ("last_seen", "lastseen"), _timestamp),
            "parental_profile": _first(
                view,
                ("parental_profile", "profile", "timerule"),
                _text,
            ),
            "internet_paused": _first(
                view,
                ("internet_paused", "blocked", "paused"),
                _boolean,
            ),
            "internet_access_allowed": _first(
                view,
                ("access_possible",),
                _boolean,
            ),
        }
    )


def _normalize_powerline_nodes(raw: Mapping[str, Any]) -> list[NormalizedData] | None:
    """Normalize the exact read-only powerline inventory from DeviceList."""
    view = _view(raw)
    key = "addpwlinedevice"
    if key not in view:
        return None
    nodes: list[NormalizedData] = []
    for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
        row = _view(record)
        node = _without_missing(
            {
                "id": _first(row, ("id",), _bounded_collection_text),
                "name": _first(
                    row,
                    ("pwline_name", "name"),
                    _bounded_collection_text,
                ),
                "parent": _first(
                    row,
                    ("pwline_connect_to", "connect_to"),
                    _powerline_parent,
                ),
                "manufacturer": _first(
                    row,
                    ("pwline_manufacturer", "manufacturer"),
                    _bounded_collection_text,
                ),
                "mac": _first(
                    row,
                    ("pwline_mac", "mac"),
                    _mac_address,
                ),
                "firmware": _first(
                    row,
                    ("pwline_firmware", "firmware"),
                    _bounded_collection_text,
                ),
                "mode": _first(
                    row,
                    ("pwline_mode", "mode"),
                    _bounded_collection_text,
                ),
                "download_link_speed_bps": _first(
                    row,
                    ("pwline_downspeed", "downspeed"),
                    _powerline_kilobits_to_bps,
                ),
                "upload_link_speed_bps": _first(
                    row,
                    ("pwline_upspeed", "upspeed"),
                    _powerline_kilobits_to_bps,
                ),
            }
        )
        if node:
            nodes.append(node)
    return nodes


def _managed_reserved_ipv4(view: Mapping[str, Any]) -> str | None:
    """Return the configured address only while fixed DHCP is active."""
    fixed_dhcp = _first(view, ("fix_dhcp", "fixed_dhcp"), _boolean)
    if fixed_dhcp is not True:
        return None
    return _managed_configured_reserved_ipv4(view)


def _managed_configured_reserved_ipv4(view: Mapping[str, Any]) -> str | None:
    """Reconstruct the firmware's configured reservation from its final octet."""
    current = _first(view, ("ipv4",), _private_address)
    reserved = _first(view, ("reservedip",), _ipv4_octet)
    if current is None or reserved is None:
        return None
    prefix, separator, _last = current.rpartition(".")
    if not separator or len(prefix.split(".")) != _IPV4_PREFIX_OCTETS:
        return None
    return f"{prefix}.{reserved}"


def _managed_form_supported(record: Mapping[str, Any], source_kind: str | None) -> bool:
    """Confirm that discovery returned one exact, scalar firmware form row."""
    if source_kind is None:
        return False
    expected = MANAGED_DEVICE_FORM_FIELDS.get(source_kind)
    if expected is None:
        return False
    canonical: dict[str, str | int] = {}
    for raw_key, value in record.items():
        key = str(raw_key).strip().casefold()
        if (
            key in canonical
            or isinstance(value, bool)
            or not isinstance(value, str | int)
        ):
            return False
        canonical[key] = value
    return set(canonical) == expected


def _wifi_counts_from_clients(items: Sequence[Mapping[str, Any]]) -> NormalizedData:
    counts = {"wifi_2_4": 0, "wifi_5": 0, "guest": 0}
    for item in items:
        if item.get("connected") is not True:
            continue
        medium = str(item.get("medium", "")).casefold()
        if medium in {"wifi_2_4", "wlan", "wlan_2_4"}:
            counts["wifi_2_4"] += 1
        elif medium in {"wifi_5", "wlan5", "wlan_5"}:
            counts["wifi_5"] += 1
        elif medium in {"guest", "guest_wifi", "wlan_guest"}:
            counts["guest"] += 1
    wifi: NormalizedData = {}
    if counts["wifi_2_4"]:
        wifi["radio_2_4"] = {"client_count": counts["wifi_2_4"]}
    if counts["wifi_5"]:
        wifi["radio_5"] = {"client_count": counts["wifi_5"]}
    if counts["guest"]:
        wifi["guest"] = {"client_count": counts["guest"]}
    return wifi


def _normalize_nat(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    nat = _fields(
        view,
        {
            "upnp_enabled": (("upnp_enabled", "use_upnp", "upnp_igd"), _boolean),
            "port_forwarding_enabled": (
                ("internet_ports_active",),
                _boolean_or_state,
            ),
        },
    )
    rules: list[NormalizedData] = []
    for group in ("addportuw", "port_forward_rules", "portuw"):
        value = view.get(group)
        if value is None:
            continue
        for record in _records(value)[:_MAX_COLLECTION_ROWS]:
            record_view = _view(record)
            identifier = _first(
                record_view,
                ("id", "rule_id", "portuw_id"),
                _bounded_collection_text,
            )
            if identifier is None:
                continue
            rule = _without_missing(
                {
                    "id": identifier,
                    "name": _first(
                        record_view,
                        ("name", "rule_name", "portuw_name"),
                        _bounded_collection_text,
                    ),
                    "active": _first(
                        record_view,
                        ("active", "enabled", "portuw_active"),
                        _boolean,
                    ),
                    "target": _first(
                        record_view,
                        ("portuw_device", "portuw_target"),
                        _bounded_collection_text,
                    ),
                    "tcp_mappings": _port_forward_mapping_summary(
                        record_view,
                        group="addtcpportuw",
                        prefix="tcp",
                    ),
                    "udp_mappings": _port_forward_mapping_summary(
                        record_view,
                        group="addudpportuw",
                        prefix="udp",
                    ),
                    "_identity_fingerprint": port_forward_rule_fingerprint(record_view),
                }
            )
            rules.append(rule)
    if rules:
        nat["port_forward_rules"] = _deduplicate(rules)
    upnp_count = _collection_count(raw, ("addupnp", "upnp_mappings"))
    if upnp_count is None:
        upnp_count = _first(view, ("upnp_mapping_count",), _integer)
    if upnp_count is not None:
        nat["upnp_mappings"] = upnp_count
    return {"nat": nat} if nat else {}


def _port_forward_mapping_summary(
    view: Mapping[str, Any], *, group: str, prefix: str
) -> str | None:
    """Render exact nested port fields as one bounded administrator summary."""
    value = view.get(group)
    if value is None:
        return None

    mappings: list[str] = []
    for record in _records(value)[:_MAX_COLLECTION_ROWS]:
        record_view = _view(record)
        public_from = _first(
            record_view,
            (f"{prefix}_public_from",),
            _port_number,
        )
        private_destination = _first(
            record_view,
            (f"{prefix}_private_dest",),
            _port_number,
        )
        if public_from is None or private_destination is None:
            continue
        public_to = _first(
            record_view,
            (f"{prefix}_public_to",),
            _port_number,
        )
        if public_to is not None and public_to < public_from:
            continue

        public_range = (
            str(public_from)
            if public_to is None or public_to == public_from
            else f"{public_from}-{public_to}"
        )
        item = f"{public_range} -> {private_destination}"
        candidate = ", ".join((*mappings, item))
        if len(candidate) > _MAX_COLLECTION_TEXT_LENGTH:
            break
        mappings.append(item)
    return ", ".join(mappings) or None


def _normalize_ddns(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    ddns = _fields(
        view,
        {
            "enabled": (
                (
                    "ddns_enabled",
                    "dyndns_enabled",
                    "use_ddns",
                    "use_dyndns",
                ),
                _boolean,
            ),
            "connected": (
                ("ddns_connected", "ddns_status", "status"),
                _boolean_or_state,
            ),
            "provider": (("dyndns_provider", "ddns_provider", "provider"), _text),
            "domain": (("dyndns_domain",), _ddns_domain),
            "update_server": (("dyndns_updsrv",), _ddns_update_server),
            "update_protocol": (("dyndns_updprot",), _ddns_update_protocol),
            "update_port": (("dyndns_updport",), _port_number),
            "last_update": (("ddns_last_update", "last_update"), _timestamp),
        },
    )
    status_code = _first(
        view,
        ("dyndns_status", "dyndns_active"),
        _ddns_status_code,
    )
    if status_code is not None:
        ddns["status_code"] = status_code
        ddns["connected"] = status_code == _DDNS_REGISTERED_STATUS
    return {"ddns": ddns} if ddns else {}


def _normalize_vpn(
    raw: Mapping[str, Any], *, include_generic: bool = True
) -> NormalizedData:
    view = _view(raw)
    vpn = _vpn_fields(view, include_generic=include_generic)
    peers: list[NormalizedData] = []
    peers_observed = False
    for key in ("addpeer", "peers", "wireguard_peers"):
        if key not in view:
            continue
        peers_observed = True
        for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
            row = _view(record)
            peer = _without_missing(
                {
                    "connected": _first(
                        row,
                        ("connected", "active", "status"),
                        _boolean_or_state,
                    ),
                    "last_handshake": _first(
                        row,
                        ("last_handshake", "handshake"),
                        _timestamp,
                    ),
                }
            )
            if peer:
                peers.append(peer)

    if "addvpn" in view:
        peers_observed = True
        for record in _records(view["addvpn"])[:_MAX_COLLECTION_ROWS]:
            row = _view(record)
            peer = _without_missing(
                {
                    "name": _first(
                        row,
                        ("vpn_name", "name"),
                        _bounded_collection_text,
                    ),
                    "enabled": _first(
                        row,
                        ("vpn_status",),
                        _boolean,
                    ),
                    # UI treats a non-empty assigned user IP as connected. The
                    # address itself is intentionally never retained.
                    "connected": _first(
                        row,
                        ("vpn_userip",),
                        _nonempty_text_boolean,
                    ),
                }
            )
            if peer:
                peers.append(peer)

    if peers_observed:
        vpn["peers"] = peers
        vpn["connected_peer_count"] = sum(
            peer.get("connected") is True for peer in peers
        )
    return {"vpn": vpn} if vpn else {}


def _normalize_vpn_details(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize only exact VPN fields owned by the detail endpoint."""
    return _normalize_vpn(raw, include_generic=False)


def _vpn_fields(view: Mapping[str, Any], *, include_generic: bool) -> NormalizedData:
    enabled: tuple[str, ...] = (
        "vpn_enabled",
        "wireguard_enabled",
        "use_vpn",
        "vpn_active",
        "vpn_status",
    )
    connected: tuple[str, ...] = (
        "vpn_connected",
        "wireguard_connected",
    )
    if include_generic:
        enabled += ("enabled", "active")
        connected += ("connected", "status")
    return _fields(
        view,
        {
            "enabled": (enabled, _boolean),
            "connected": (connected, _boolean_or_state),
            "connected_peer_count": (
                (
                    "vpn_act_users",
                    "vpn_connected_peer_count",
                    "connected_peer_count",
                ),
                _integer,
            ),
            "type": (("vpn_act_selection", "vpn_typ"), _text),
        },
    )


def _normalize_parental(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    parental = _fields(
        view,
        {
            "enabled": (
                (
                    "parental_enabled",
                    "parental_control_enabled",
                    "use_parental",
                    "internet_timerule_active",
                ),
                _boolean,
            ),
            "blocked_client_count": (
                ("blocked_client_count", "parental_blocked_count"),
                _integer,
            ),
        },
    )
    profiles = _collection_count(raw, ("addprofile", "profiles", "timerules"))
    if profiles is not None:
        parental["profiles"] = profiles
    if "blocked_client_count" not in parental:
        blocked = _collection_count(raw, ("blocked_clients", "addblockeddevice"))
        if blocked is not None:
            parental["blocked_client_count"] = blocked
    return {"parental": parental} if parental else {}


def _normalize_telephony(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    telephony = _fields(
        view,
        {
            "registered": (
                ("telephony_registered", "voip_registered", "registered"),
                _boolean,
            ),
            "registered_number_count": (
                ("registered_number_count", "voip_number_count"),
                _integer,
            ),
            "active_call": (("active_call", "call_active"), _boolean),
            "voip_possible": (("vosip_possible",), _boolean),
            "voip_policy": (("phone_vosip_policy",), _nonnegative_integer),
            "hd_voice_active": (("hdvoice",), _nonzero_boolean),
            "provisioning_code": (("provis_voip",), _provisioning_code),
            "manual_configuration_available": (
                ("provis_voip",),
                _manual_telephony_configuration,
            ),
        },
    )
    provider_family = _telephony_provider_family_from_view(view)
    if provider_family is not None:
        telephony["provider_family"] = provider_family
    missed = 0
    observed_missed = False
    timestamps: list[datetime] = []
    for group, direction in _CALL_GROUPS.items():
        value = view.get(group)
        if value is None:
            continue
        records = _records(value)
        if direction == "missed":
            observed_missed = True
            missed += len(records)
        for record in records:
            timestamp = _call_timestamp(_record_view(record))
            if isinstance(timestamp, datetime):
                timestamps.append(timestamp)
    if observed_missed:
        telephony["missed_call_count"] = missed
    if timestamps:
        telephony["last_call"] = {"timestamp": max(timestamps).isoformat()}
    number_groups = (
        "addnumber",
        "addphonenumber",
        "registered_numbers",
        "telephone_numbers",
        "numbers",
    )
    numbers = _normalize_stable_devices(
        raw,
        number_groups,
        kind="telephone_line",
    )
    voip_lines = _normalize_voip_lines(raw)
    if voip_lines is not None:
        numbers.extend(voip_lines)
        numbers = _deduplicate(numbers)
    if numbers:
        telephony["numbers"] = numbers
    elif voip_lines is not None or _collection_observed_empty(
        raw, number_groups, prefixes=_device_prefixes("telephone_line")
    ):
        telephony["numbers"] = []
    if "registered_number_count" not in telephony:
        number_count = _collection_count(raw, number_groups)
        if number_count is not None:
            telephony["registered_number_count"] = number_count
    provider_count = _recursive_collection_count(
        raw,
        ("addipphoneprovider", "ip_phone_providers"),
    )
    if provider_count is not None:
        telephony["provider_count"] = provider_count
    providers = _normalize_telephony_providers(raw)
    if providers is not None:
        telephony["providers"] = providers
    voip_number_groups = ("addipnumber", "ip_phone_numbers")
    configured_number_count = _recursive_collection_count(raw, voip_number_groups)
    if configured_number_count is not None:
        telephony["configured_number_count"] = configured_number_count
    for status, canonical in (
        ("ok", "registered_voip_number_count"),
        ("inactive", "inactive_voip_number_count"),
        ("warning", "warning_voip_number_count"),
    ):
        count = _recursive_collection_enum_count(
            raw,
            voip_number_groups,
            ("number_status", "status"),
            expected=status,
        )
        if count is not None:
            telephony[canonical] = count
    failed_line_count = _recursive_collection_enum_count(
        raw,
        ("addphonenumber",),
        ("status",),
        expected="failed",
    )
    if failed_line_count is not None:
        telephony["failed_line_count"] = failed_line_count
    return {"telephony": telephony} if telephony else {}


def _normalize_telephony_providers(
    raw: Mapping[str, Any],
) -> list[NormalizedData] | None:
    """Retain only opaque provider identity and observed provider code."""
    view = _view(raw)
    key = "addipphoneprovider"
    if key not in view:
        return None
    providers: list[NormalizedData] = []
    for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
        row = _view(record)
        identifier = _first(row, ("id",), _bounded_collection_text)
        if identifier is None:
            continue
        providers.append(
            _without_missing(
                {
                    "id": identifier,
                    "provider_code": _first(
                        row,
                        ("isp_selection",),
                        _nonnegative_integer,
                    ),
                }
            )
        )
    return _deduplicate(providers)


def _normalize_voip_lines(raw: Mapping[str, Any]) -> list[NormalizedData] | None:
    """Normalize VoIP line state without retaining any telephone number."""
    view = _view(raw)
    key = "addipnumber"
    if key not in view:
        return None
    lines: list[NormalizedData] = []
    for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
        row = _view(record)
        identifier = _first(
            row,
            ("id", "ipphonenumber_id"),
            _non_phone_identifier,
        )
        if identifier is None:
            continue
        lines.append(
            _without_missing(
                {
                    "id": identifier,
                    "status": _first(
                        row,
                        ("number_status",),
                        _voip_line_status,
                    ),
                    "provider_code": _first(
                        row,
                        ("isp_selection",),
                        _nonnegative_integer,
                    ),
                    "error_code": _first(
                        row,
                        ("connection_failure_code",),
                        _bounded_error_code,
                    ),
                }
            )
        )
    return _deduplicate(lines)


def _normalize_pbx(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    pbx = _pbx_fields(view)
    phones = _normalize_stable_devices(
        raw,
        ("addipphone", "ip_phones", "phones"),
        kind="ip_phone",
    )
    if phones:
        pbx["ip_phones"] = phones
    else:
        count = _collection_count(raw, ("addipphone", "ip_phones", "phones"))
        if count is not None:
            pbx["ip_phones"] = count
    client_groups = ("addipclient", "ip_clients")
    client_count = _collection_count(raw, client_groups)
    if client_count is not None:
        pbx["configured_client_count"] = client_count
    clients = _normalize_pbx_clients(raw, client_groups)
    if clients is not None:
        pbx["clients"] = clients
    for status_code, canonical in (
        (0, "disconnected_client_count"),
        (1, "registered_client_count"),
        (2, "locked_client_count"),
    ):
        count = _collection_enum_count(
            raw,
            client_groups,
            ("ipclient_status", "status"),
            parser=_integer,
            expected=status_code,
        )
        if count is not None:
            pbx[canonical] = count
    return {"pbx": pbx} if pbx else {}


def _normalize_pbx_clients(
    raw: Mapping[str, Any],
    groups: Iterable[str],
) -> list[NormalizedData] | None:
    """Normalize bounded PBX registration rows, excluding credentials."""
    view = _view(raw)
    observed = False
    clients: list[NormalizedData] = []
    for group in groups:
        key = group.casefold()
        if key not in view:
            continue
        observed = True
        for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
            row = _view(record)
            identifier = _first(row, ("id",), _bounded_collection_text)
            if identifier is None:
                continue
            clients.append(
                _without_missing(
                    {
                        "id": identifier,
                        "status": _first(
                            row,
                            ("ipclient_status", "status"),
                            _pbx_client_status,
                        ),
                        "name": _first(
                            row,
                            ("ipclient_mdevice_name",),
                            _bounded_collection_text,
                        ),
                        "ipv4": _first(
                            row,
                            ("ipclient_mdevice_ipv4",),
                            _private_address,
                        ),
                        "mac": _first(
                            row,
                            ("ipclient_mdevice_mac",),
                            _mac_address,
                        ),
                    }
                )
            )
    return _deduplicate(clients) if observed else None


def _pbx_fields(view: Mapping[str, Any]) -> NormalizedData:
    return _fields(
        view,
        {
            "enabled": (("use_ippbx", "ippbx_enabled", "pbx_enabled"), _boolean),
        },
    )


def _normalize_dect(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    dect = _dect_fields(view)
    handsets = _normalize_stable_devices(
        raw,
        ("adddectdevice", "adddect", "handsets", "dect_devices"),
        kind="dect",
    )
    for handset in handsets:
        identifier = handset.get("id")
        if identifier is None:
            continue
        paging = _first(view, (f"pagingstat{identifier}",), _boolean)
        if paging is not None:
            handset["paging"] = paging
    if handsets:
        dect["handsets"] = handsets
    else:
        count = _collection_count(
            raw,
            ("adddectdevice", "adddect", "handsets", "dect_devices"),
        )
        if count is not None:
            dect["handsets"] = count
    handset_count = _first(view, ("dect_real_count",), _nonnegative_integer)
    if handset_count is None:
        handset_count = _collection_count(
            raw,
            ("adddectdevice", "adddect", "handsets", "dect_devices"),
        )
    if handset_count is not None:
        dect["handset_count"] = handset_count
    paging_count = _prefixed_boolean_count(view, ("pagingstat",))
    if paging_count is not None:
        dect["paging_handset_count"] = paging_count
        dect["paging_active"] = paging_count > 0
    repeater_count = _collection_count(raw, ("addrepeater", "dect_repeaters"))
    if repeater_count is not None:
        dect["repeater_count"] = repeater_count
    repeaters = _normalize_dect_repeaters(raw)
    if repeaters is not None:
        dect["repeaters"] = repeaters
    phonebooks = _collection_count(raw, ("addphonebook", "phonebooks"))
    if phonebooks is not None:
        dect["phonebooks"] = phonebooks
    phonebook_entry_count = _first(view, ("num_entries",), _nonnegative_integer)
    if phonebook_entry_count is not None:
        dect["phonebook_entry_count"] = phonebook_entry_count
    return {"dect": dect} if dect else {}


def _normalize_dect_repeater(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize exact repeater membership owned by the detail endpoint."""
    repeater_count = _collection_count(raw, ("addrepeater", "dect_repeaters"))
    if repeater_count is None:
        return {}
    dect: NormalizedData = {"repeater_count": repeater_count}
    repeaters = _normalize_dect_repeaters(raw)
    if repeaters is not None:
        dect["repeaters"] = repeaters
    return {"dect": dect}


def _normalize_dect_repeaters(raw: Mapping[str, Any]) -> list[NormalizedData] | None:
    """Retain bounded registered-repeater rows without labels or settings."""
    view = _view(raw)
    if "addrepeater" not in view:
        return None
    repeaters: list[NormalizedData] = []
    for record in _records(view["addrepeater"])[:_MAX_COLLECTION_ROWS]:
        identifier = _first(_view(record), ("id",), _bounded_collection_text)
        if identifier is None:
            continue
        repeaters.append({"id": identifier, "registered": True})
    return _deduplicate(repeaters)


def _dect_fields(view: Mapping[str, Any]) -> NormalizedData:
    return _fields(
        view,
        {
            "enabled": (("use_dect", "dect_enabled", "dect_active"), _boolean),
            "scan_active": (("dect_detect_status",), _boolean),
            "smart_home_enabled": (("use_smarthome",), _boolean),
        },
    )


def _normalize_security(raw: Mapping[str, Any]) -> NormalizedData:
    security = _security_fields(_view(raw), include_generic=True)
    dns_exceptions = _collection_count(raw, ("adddnsexcept", "dns_exceptions"))
    if dns_exceptions is not None:
        security["dns_rebind_exception_count"] = dns_exceptions
    dns_exception_rows = _dns_rebind_exception_rows(raw)
    if dns_exception_rows is not None:
        security["dns_rebind_exceptions"] = dns_exception_rows

    view = _view(raw)
    port_block_families = (
        ("extended", ("addextendedrule", "extended_rules", "port_block_rules")),
        ("extra", ("addextra",)),
    )
    rules: list[NormalizedData] = []
    port_block_rule_count = 0
    port_block_rules_observed = False
    active_port_block_rule_count = 0
    active_port_block_rules_observed = False
    active_fields = ("extendedrule_active", "child_extrarule_active", "active")
    for rule_group, aliases in port_block_families:
        selected_alias = next((alias for alias in aliases if alias in view), None)
        if selected_alias is None:
            continue
        value = view[selected_alias]
        port_block_rules_observed = True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            port_block_rule_count += max(int(value), 0)
            continue
        records = _records(value)
        port_block_rule_count += len(records)
        for record in records:
            record_view = _view(record)
            if any(field in record_view for field in active_fields):
                active_port_block_rules_observed = True
                if _first(record_view, active_fields, _boolean) is True:
                    active_port_block_rule_count += 1
            rule = _without_missing(
                {
                    "rule_group": rule_group,
                    "id": _first(
                        record_view,
                        ("id", "extendedrule_id", "extrarule_id"),
                        _bounded_collection_text,
                    ),
                    "active": _first(
                        record_view,
                        ("extendedrule_active", "child_extrarule_active", "active"),
                        _boolean,
                    ),
                    "tcp_ports": _first(
                        record_view,
                        ("extrule_tcp",),
                        _bounded_port_list,
                    ),
                    "udp_ports": _first(
                        record_view,
                        ("extrule_udp",),
                        _bounded_port_list,
                    ),
                }
            )
            if rule and len(rules) < _MAX_COLLECTION_ROWS:
                rules.append(rule)
    if port_block_rules_observed:
        security["port_block_rule_count"] = port_block_rule_count
        security["port_block_rules"] = rules
    if active_port_block_rules_observed:
        security["active_port_block_rule_count"] = active_port_block_rule_count
    return {"security": security} if security else {}


def _dns_rebind_exception_rows(
    raw: Mapping[str, Any],
) -> list[NormalizedData] | None:
    """Retain exact, bounded domain rows for the administrator-only view."""
    value = _view(raw).get("adddnsexcept")
    if value is None:
        return None
    rows: list[NormalizedData] = []
    for record in _records(value)[:_MAX_COLLECTION_ROWS]:
        domain = _first(
            _record_view(record),
            ("hostname",),
            _strict_dns_name,
        )
        if domain is not None:
            rows.append({"domain": domain})
    return rows


def _security_fields(
    view: Mapping[str, Any], *, include_generic: bool = False
) -> NormalizedData:
    firewall: tuple[str, ...] = (
        "firewall_enabled",
        "use_firewall",
        "router_firewall_active",
    )
    if include_generic:
        firewall += ("enabled", "active")
    return _fields(
        view,
        {
            "firewall_enabled": (firewall, _boolean),
            "dns_rebind_protection": (
                (
                    "dns_rebind_protection",
                    "rebind_protection",
                    "dns_rebind_active",
                ),
                _boolean,
            ),
            "port_blocking_enabled": (
                ("child_extrarule_active", "internet_extrule_active"),
                _boolean,
            ),
            "remote_management": (
                ("remote_management", "remote_access_enabled"),
                _boolean,
            ),
            "router_https_enabled": (("use_https",), _boolean),
        },
    )


def _normalize_qos(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    qos: NormalizedData = {}
    prioritized = _prefixed_boolean_count(view, ("qos_pc",))
    if prioritized is not None:
        qos["prioritized_client_count"] = prioritized
    rows = _qos_priority_rows(view)
    if rows is not None:
        qos["prioritized_clients"] = rows
    return {"qos": qos} if qos else {}


def _qos_priority_rows(view: Mapping[str, Any]) -> list[NormalizedData] | None:
    """Model only exact ``qos_pc`` checkbox slots; identity is not inferred."""
    rows: dict[int, NormalizedData] = {}
    observed = False
    for key, value in view.items():
        match = _QOS_PC_SLOT.fullmatch(key)
        if match is not None:
            observed = True
            slot = int(match.group(1))
            if slot > _MAX_COLLECTION_ROWS:
                continue
            prioritized = _first({"value": value}, ("value",), _boolean)
            if prioritized is not None:
                rows[slot] = {"slot": slot, "prioritized": prioritized}
            continue
        if key != "qos_pc":
            continue
        observed = True
        for slot, raw_value in enumerate(
            _scalar_values(value)[:_MAX_COLLECTION_ROWS],
            start=1,
        ):
            prioritized = _boolean(raw_value)
            if prioritized is not None:
                rows[slot] = {"slot": slot, "prioritized": prioritized}
    return [rows[slot] for slot in sorted(rows)] if observed else None


def _normalize_wifi_environment(raw: Mapping[str, Any]) -> NormalizedData:
    """Fail closed until exact WLANEnviron row fields are observed and reviewed."""
    del raw
    return {}


def _normalize_usb(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    usb = _fields(
        view,
        {
            "connected": (("usb_connected", "usb_present"), _boolean),
            "port_enabled": (("use_usb",), _boolean),
            "tethering_enabled": (("use_tethering",), _boolean),
            "tethering_status_code": (("tethering_status",), _nonnegative_integer),
            "printer_connected": (("printer_connected",), _boolean),
        },
    )
    devices = _normalize_stable_devices(
        raw,
        ("addusbdevice", "usb_devices", "items"),
        kind="usb",
    )
    if devices:
        usb["items"] = devices
        usb.setdefault("connected", True)
    else:
        count = _collection_count(raw, ("addusbdevice", "usb_devices", "items"))
        if count is not None:
            usb["items"] = count
            usb.setdefault("connected", count > 0)
    tethering_status = _first(view, ("tethering_status",), _nonnegative_integer)
    if tethering_status is not None:
        usb["tethering_connected"] = tethering_status == _TETHERING_CONNECTED_STATUS

    storage_groups = ("addnasdevice", "nas_devices")
    storage_count = _collection_count(raw, storage_groups)
    if storage_count is not None:
        usb["storage_device_count"] = storage_count
    storage_items = _normalize_nas_storage_items(raw, storage_groups)
    if storage_items is not None:
        usb["storage_items"] = storage_items
    total_bytes, used_bytes = _nas_capacity_totals(raw, storage_groups)
    if total_bytes is not None:
        usb["storage_total_bytes"] = total_bytes
    if used_bytes is not None:
        usb["storage_used_bytes"] = used_bytes
    if total_bytes is not None and used_bytes is not None:
        usb["storage_free_bytes"] = max(total_bytes - used_bytes, 0)

    usb = _deep_merge(usb, _media_server_fields(raw))

    shares = _normalize_nas_shares(raw)
    if shares is not None:
        usb["shares"] = shares

    return {"usb": usb} if usb else {}


def _normalize_media_server(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize only the safe media-server summary fields into USB state."""
    usb = _media_server_fields(raw)
    return {"usb": usb} if usb else {}


def _normalize_nas_folders(raw: Mapping[str, Any]) -> NormalizedData:
    """Keep NAS-folder state on identified share rows, never global USB state."""
    shares = _normalize_nas_shares(raw)
    return {"usb": {"shares": shares}} if shares is not None else {}


def _media_server_fields(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    usb = _fields(
        view,
        {
            "media_server_enabled": (
                ("media_server_enabled", "use_media_server"),
                _boolean,
            ),
        },
    )
    media_groups = ("addnasmediareplay", "nas_media_shares")
    media_share_count = _collection_count(raw, media_groups)
    if media_share_count is not None:
        usb["media_share_count"] = media_share_count
    active_media_share_count = _collection_enum_count(
        raw,
        media_groups,
        ("mediareplay_active", "active"),
        parser=_boolean,
        expected=True,
    )
    if active_media_share_count is None and media_share_count == 0:
        active_media_share_count = 0
    if active_media_share_count is not None:
        usb["active_media_share_count"] = active_media_share_count

    return usb


def _normalize_nas_storage_items(
    raw: Mapping[str, Any],
    groups: Iterable[str],
) -> list[NormalizedData] | None:
    """Normalize bounded storage rows while keeping names panel-admin-only."""
    view = _view(raw)
    observed = False
    items: list[NormalizedData] = []
    for group in groups:
        key = group.casefold()
        if key not in view:
            continue
        observed = True
        for record in _records(view[key])[:_MAX_COLLECTION_ROWS]:
            row = _view(record)
            total_bytes = _first(
                row,
                ("nas_device_total", "total_kib"),
                _nas_capacity_bytes,
            )
            used_bytes = _first(
                row,
                ("nas_device_used", "used_kib"),
                _nas_capacity_bytes,
            )
            item = _without_missing(
                {
                    "name": _first(
                        row,
                        ("nas_device_name", "name"),
                        _bounded_collection_text,
                    ),
                    "storage_type": _first(
                        row,
                        ("nas_device_type", "type"),
                        _bounded_collection_text,
                    ),
                    "connection": _first(
                        row,
                        ("nas_device_connection", "connection"),
                        _bounded_collection_text,
                    ),
                    "total_bytes": total_bytes,
                    "used_bytes": used_bytes,
                    "free_bytes": (
                        max(total_bytes - used_bytes, 0)
                        if total_bytes is not None and used_bytes is not None
                        else None
                    ),
                }
            )
            if item:
                items.append(item)
    return items if observed else None


def _normalize_nas_shares(raw: Mapping[str, Any]) -> list[NormalizedData] | None:
    """Normalize NAS share flags and path, excluding all credentials."""
    view = _view(raw)
    group_keys = ("addnasfolder", "nas_folders", "nasfolder")
    records: list[Mapping[str, Any]] = []
    observed = False
    for group in group_keys:
        if group not in view:
            continue
        observed = True
        records.extend(_records(view[group])[:_MAX_COLLECTION_ROWS])

    flat_name = _first(
        view,
        ("nas_folder_name", "nas_share_name", "share_name"),
        _bounded_collection_text,
    )
    if not observed and flat_name is not None:
        observed = True
        records = [view]

    shares: list[NormalizedData] = []
    for record in records[:_MAX_COLLECTION_ROWS]:
        row = _view(record)
        share = _without_missing(
            {
                "name": _first(
                    row,
                    ("nas_folder_name", "nas_share_name", "share_name"),
                    _bounded_collection_text,
                ),
                "enabled": _first(row, ("nas_active", "active"), _boolean),
                "read_only": _first(
                    row,
                    ("nas_folder_nur_lesen", "read_only"),
                    _boolean,
                ),
                "secure": _first(row, ("nas_secure", "secure"), _boolean),
            }
        )
        if share:
            shares.append(share)
    return shares if observed else None


def _normalize_receiver(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    receiver = _receiver_status_fields(view)
    mobile = _mobile_fields(view, include_generic=True)
    receiver_groups = (
        "addreceiver",
        "receiver_items",
        "receivers",
        "external_5g_receiver",
        "items",
    )
    receivers = _normalize_stable_devices(
        raw,
        receiver_groups,
        kind="receiver",
    )
    if not receivers:
        candidate = _normalize_stable_device_record(raw, kind="receiver")
        if candidate:
            receivers = [candidate]
    if receivers or _collection_observed_empty(
        raw,
        receiver_groups,
        prefixes=_device_prefixes("receiver"),
    ):
        receiver["items"] = receivers
    result: NormalizedData = {}
    if receiver:
        result["receiver"] = receiver
    if mobile:
        result["mobile"] = mobile
    return result


def _normalize_receiver_led(raw: Mapping[str, Any]) -> NormalizedData:
    """Normalize only LED control readback from its exact LTE capability."""
    led_mode = _first(_view(raw), ("ex5g_led_mode",), _led_mode)
    return {"receiver": {"led_mode": led_mode}} if led_mode is not None else {}


def _receiver_status_fields(view: Mapping[str, Any]) -> NormalizedData:
    """Return receiver settings under their canonical receiver root."""
    return _fields(
        view,
        {
            "external_modem_enabled": (("auto_external_modem",), _boolean),
            "external_wan_link": (("extwan_status",), _boolean),
            "mode": (("extwan_typ",), _receiver_mode),
            "lte_enabled": (("use_lte",), _boolean),
            "led_mode": (("ex5g_led_mode",), _led_mode),
            "firmware_auto_update": (("auto_update",), _boolean),
            "firmware_update_available": (("ex5g_fwupd_avail",), _boolean),
            "firmware_version": (("ex5g_fw_version",), _firmware_version),
            "latest_firmware": (("ex5g_fwupd_version",), _firmware_version),
            "firmware_update_planned": (("ex5g_fwupd_planned",), _boolean),
            "firmware_update_time": (("ex5g_fwupd_time",), _timestamp),
            "model": (("ex5g_model_name",), _bounded_label),
            "esim_supported": (("ex5g_eid",), _esim_supported),
        },
    )


def _normalize_system(raw: Mapping[str, Any]) -> NormalizedData:
    system = _system_fields(_view(raw), include_generic=True)
    return {"system": system} if system else {}


def _system_fields(
    view: Mapping[str, Any], *, include_generic: bool = False
) -> NormalizedData:
    aliases: dict[str, tuple[tuple[str, ...], Parser]] = {
        "uptime_seconds": (
            ("system_uptime", "router_uptime", "device_uptime"),
            _seconds,
        ),
        "temperature_celsius": (
            ("system_temperature", "router_temperature", "temperature_celsius"),
            _number_value,
        ),
        "cpu_percent": (("cpu_percent", "cpu_usage"), _percentage),
        "memory_percent": (("memory_percent", "memory_usage"), _percentage),
        "update_available": (("fwupd_avail", "firmware_update_available"), _boolean),
        "latest_firmware": (
            ("fwupd_version", "latest_firmware", "firmware_available_version"),
            _firmware_version,
        ),
        "update_planned": (("fwupd_planned",), _boolean),
        "update_time": (("fwupd_time",), _timestamp),
        "firmware_release_url": (("firmware_release_url",), _safe_url),
        "firmware_update_progress": (("firmware_update_progress",), _percentage),
        "remote_support_active": (("br_active",), _boolean),
        "operating_mode": (("router_state",), _router_operating_mode),
        "settings_write_blocked": (("save_fails",), _boolean),
        "device_password_changed": (("pwd_changed",), _nonzero_boolean),
        "initial_setup_completed": (("wlanfinished",), _nonzero_boolean),
    }
    if include_generic:
        aliases["uptime_seconds"] = (
            aliases["uptime_seconds"][0] + ("uptime",),
            _seconds,
        )
    system = _fields(view, aliases)
    automatic_updates_disabled = _first(view, ("autofw_deactive",), _boolean)
    if automatic_updates_disabled is not None:
        system["automatic_updates_enabled"] = not automatic_updates_disabled
    easy_support_disabled = _first(view, ("easy_support_deactive",), _boolean)
    if easy_support_disabled is not None:
        system["easy_support_enabled"] = not easy_support_disabled
    return system


def _normalize_diagnostics(raw: Mapping[str, Any]) -> NormalizedData:
    diagnostics = _fields(
        _view(raw),
        {
            "problem": (("problem", "router_problem"), _boolean),
            "request_latency_ms": (("request_latency_ms",), _number_value),
            "update_failures": (("update_failures",), _integer),
            "last_successful_update": (("last_successful_update",), _timestamp),
        },
    )
    return {"diagnostics": diagnostics} if diagnostics else {}


def _normalize_stable_devices(
    raw: Mapping[str, Any],
    groups: Iterable[str],
    *,
    kind: str,
) -> list[NormalizedData]:
    view = _view(raw)
    devices: list[NormalizedData] = []
    for group in groups:
        value = view.get(group.casefold())
        if value is None:
            continue
        for record in _records(value):
            normalized = _normalize_stable_device_record(record, kind=kind)
            if normalized:
                devices.append(normalized)

    # Several Speedport pages return one flat set of parallel prefixed columns
    # instead of a named collection. Reconstruct only prefixes belonging to
    # the requested family; unrelated page data remains ignored.
    for prefix in _device_prefixes(kind):
        columns = {
            key.removeprefix(prefix): value
            for key, value in view.items()
            if key.startswith(prefix)
        }
        for record in _records(columns):
            normalized = _normalize_stable_device_record(record, kind=kind)
            if normalized:
                devices.append(normalized)
    return _deduplicate(devices)


def _normalize_stable_device_record(
    record: Mapping[str, Any],
    *,
    kind: str,
) -> NormalizedData:
    view = _record_view(record)
    identifier = _stable_identifier(
        view,
        reject_phone_like=kind == "telephone_line",
    )
    if identifier is None:
        return {}

    name = _first(
        view,
        ("name", "device_name", "hostname", "label", "display_name"),
        _text,
    )
    if kind == "telephone_line" and name is not None and _phone_like(name):
        name = None
    model_aliases: tuple[str, ...] = ("model", "product_name", "model_name")
    if kind != "mesh":
        model_aliases = ("model", "type", "product_name", "model_name")

    device = _without_missing(
        {
            "id": identifier,
            "serial": _first(view, ("serial", "serial_number"), _text),
            "mac": _first(view, ("mac", "mac_address"), _mac_address),
            "name": name,
            "manufacturer": _first(
                view,
                ("manufacturer", "vendor", "maker"),
                _text,
            ),
            "model": _first(
                view,
                model_aliases,
                _text,
            ),
            "firmware": _first(
                view,
                ("firmware", "firmware_version", "sw_version", "version"),
                _text,
            ),
            "hardware_version": _first(
                view,
                ("hardware_version", "hw_version"),
                _text,
            ),
        }
    )
    fields = _device_fields(view, kind)
    return _deep_merge(device, fields)


def _device_fields(view: Mapping[str, Any], kind: str) -> NormalizedData:
    common_connection = {
        "connected": (
            ("connected", "online", "present", "connection_status", "active"),
            _boolean,
        ),
    }
    traffic = {
        "link_speed_bps": (
            ("link_speed_bps", "link_speed", "speed_bps", "speed"),
            _bps,
        ),
        "download_rate_bps": (
            ("download_rate_bps", "download_rate", "down_rate", "rx_rate"),
            _bps,
        ),
        "upload_rate_bps": (
            ("upload_rate_bps", "upload_rate", "up_rate", "tx_rate"),
            _bps,
        ),
        "bytes_received": (
            ("bytes_received", "received_bytes", "rx_bytes"),
            _integer,
        ),
        "bytes_sent": (("bytes_sent", "sent_bytes", "tx_bytes"), _integer),
    }
    radio = {
        "signal_dbm": (("signal_dbm", "rssi", "signal"), _number_value),
        "band": (("band", "radio_band", "frequency_band", "wlan_band"), _text),
        "channel": (("channel", "wifi_channel", "wlan_channel"), _integer),
    }

    if kind == "mesh":
        mesh = _fields(
            view,
            {
                **common_connection,
                **traffic,
                **radio,
                "parent": (("connect_to",), _text),
                "medium": (("mesh_type", "type"), _network_medium_code),
                "device_type": (("device_type",), _mesh_device_type),
                "ipv4": (("ipv4",), _private_address),
                # devices.js treats mesh_use_wlan=2 as disabled.
                "wifi_enabled": (("use_wlan",), _mesh_wifi_enabled),
                "download_link_speed_bps": (
                    ("download_link_speed_bps", "downlink_speed_bps", "downspeed"),
                    _bps,
                ),
                "upload_link_speed_bps": (
                    ("upload_link_speed_bps", "uplink_speed_bps", "upspeed"),
                    _bps,
                ),
                "client_count": (
                    ("client_count", "connected_clients", "clients"),
                    _integer,
                ),
                "role": (("role", "mesh_role", "node_role"), _text),
                "backhaul": (
                    ("backhaul", "backhaul_type", "uplink", "uplink_type"),
                    _text,
                ),
                "uptime_seconds": (
                    ("uptime_seconds", "uptime", "online_time"),
                    _seconds,
                ),
                "lan_port_1_speed_bps": (("lan1",), _lan_link_speed_bps),
                "lan_port_2_speed_bps": (("lan2",), _lan_link_speed_bps),
            },
        )
        linked_lan_ports = _linked_lan_port_count(view, ("lan1", "lan2"))
        if linked_lan_ports is not None:
            mesh["linked_lan_port_count"] = linked_lan_ports
        return mesh
    if kind == "telephone_line":
        return _fields(
            view,
            {
                "registered": (
                    ("registered", "registration", "registration_status"),
                    _boolean,
                ),
                "enabled": (("enabled", "active"), _boolean),
                "active_call": (
                    ("active_call", "call_active", "in_call", "incall"),
                    _boolean,
                ),
                "call_state": (
                    ("call_state", "call_status", "line_status", "status"),
                    _text,
                ),
                "error_code": (("voip_errnr",), _bounded_error_code),
            },
        )
    if kind == "dect":
        return _fields(
            view,
            {
                **common_connection,
                "registered": (
                    ("registered", "registration", "registration_status"),
                    _boolean,
                ),
                "active_call": (
                    ("active_call", "call_active", "in_call", "incall"),
                    _boolean,
                ),
                "charging": (("charging", "is_charging"), _boolean),
                "battery_percent": (
                    ("battery_percent", "battery_level", "battery", "charge_level"),
                    _percentage,
                ),
                "signal_dbm": (("signal_dbm", "rssi", "signal"), _number_value),
                "signal_percent": (
                    ("signal_percent", "signal_quality", "quality"),
                    _percentage,
                ),
                "call_state": (
                    ("call_state", "call_status", "status"),
                    _text,
                ),
            },
        )
    if kind == "ip_phone":
        return _fields(
            view,
            {
                **common_connection,
                "registered": (
                    ("registered", "registration", "registration_status"),
                    _boolean,
                ),
                "active_call": (
                    ("active_call", "call_active", "in_call", "incall"),
                    _boolean,
                ),
                "call_state": (
                    ("call_state", "call_status", "status"),
                    _text,
                ),
            },
        )
    if kind == "usb":
        return _fields(
            view,
            {
                **common_connection,
                "mounted": (("mounted", "is_mounted", "mount_status"), _boolean),
                "total_bytes": (
                    ("total_bytes", "capacity_bytes", "capacity", "total_space"),
                    _bytes,
                ),
                "used_bytes": (("used_bytes", "used_space"), _bytes),
                "free_bytes": (("free_bytes", "free_space"), _bytes),
                "usage_percent": (
                    ("usage_percent", "used_percent", "storage_usage"),
                    _percentage,
                ),
                "temperature_celsius": (
                    ("temperature_celsius", "temperature", "temp"),
                    _number_value,
                ),
                "media_type": (
                    ("media_type", "storage_type", "device_type", "type"),
                    _text,
                ),
            },
        )
    if kind == "receiver":
        receiver = _fields(
            view,
            {
                **common_connection,
                **traffic,
                "network_type": (
                    ("network_type", "radio_access_type", "technology"),
                    _text,
                ),
                "operator": (("operator", "network_operator"), _text),
                "rsrp_dbm": (
                    ("rsrp_dbm", "rsrp", "5g_rsrp", "lte_rsrp", "signal_5g"),
                    _number_value,
                ),
                "rsrq_db": (("rsrq_db", "rsrq", "5g_rsrq", "lte_rsrq"), _number_value),
                "sinr_db": (("sinr_db", "sinr", "5g_sinr", "lte_sinr"), _number_value),
                "rssi_dbm": (
                    ("rssi_dbm", "rssi", "5g_rssi", "lte_rssi", "signal_lte"),
                    _number_value,
                ),
                "band": (("band", "radio_band", "freq_5g", "freq_lte"), _text),
                "frequency_mhz": (
                    ("frequency_mhz", "frequency", "freq_mhz"),
                    _number_value,
                ),
                "cell_id": (("cell_id", "cellid"), _text),
                "temperature_celsius": (
                    ("temperature_celsius", "temperature", "temp"),
                    _number_value,
                ),
            },
        )
        if "network_type" not in receiver:
            if _present(view, "signal_5g") or _present(view, "5g_rsrp"):
                receiver["network_type"] = "5G"
            elif _present(view, "signal_lte") or _present(view, "lte_rsrp"):
                receiver["network_type"] = "LTE"
        return receiver
    return {}


def _device_prefixes(kind: str) -> tuple[str, ...]:
    return {
        "mesh": ("meshdevice_", "manageddevice_", "mesh_", "node_", "repeater_"),
        "telephone_line": (
            "phonenumber_",
            "phonenum_",
            "telnumber_",
            "telephone_",
            "telephony_",
            "number_",
            "line_",
            "msn_",
        ),
        "dect": ("dectdevice_", "dect_", "handset_"),
        "ip_phone": ("ipphone_", "ip_phone_"),
        "usb": ("usbdevice_", "usb_device_", "usb_"),
        "receiver": ("receiver_", "external_5g_", "ex5g_"),
    }.get(kind, ())


def _stable_identifier(
    view: Mapping[str, Any], *, reject_phone_like: bool = False
) -> str | None:
    """Use only router ID/UUID, MAC, or serial as stable child identity."""
    for aliases, parser in (
        (("id", "uuid", "uid", "device_id", "router_id"), _text),
        (("mac", "mac_address", "device_mac"), _mac_address),
        (("serial", "serial_number"), _text),
    ):
        for alias in aliases:
            value = _first(view, (alias,), parser)
            if value is None:
                continue
            normalized = str(value).strip().casefold()
            if reject_phone_like and _phone_like(normalized):
                continue
            return normalized
    return None


def _records(value: Any) -> list[Mapping[str, Any]]:
    """Expand nested, repeated, or parallel-column varid collections."""
    if isinstance(value, Mapping):
        safe = _safe_mapping(value)
        if not safe:
            return []
        sequence_values = {
            key: list(item)
            for key, item in safe.items()
            if isinstance(item, list | tuple)
        }
        if sequence_values:
            scalar_values = {
                key: item
                for key, item in safe.items()
                if not isinstance(item, list | tuple)
            }
            length = max(len(item) for item in sequence_values.values())
            return [
                {
                    **scalar_values,
                    **{
                        key: items[index]
                        for key, items in sequence_values.items()
                        if index < len(items)
                    },
                }
                for index in range(length)
            ]
        return [safe]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        records: list[Mapping[str, Any]] = []
        for item in value:
            records.extend(_records(item))
        return records
    return []


def _collection_count(raw: Mapping[str, Any], groups: Iterable[str]) -> int | None:
    view = _view(raw)
    for group in groups:
        key = group.casefold()
        if key not in view:
            continue
        value = view[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(int(value), 0)
        return len(_records(value))
    return None


def _collection_enum_count(
    raw: Mapping[str, Any],
    groups: Iterable[str],
    fields: Iterable[str],
    *,
    parser: Parser,
    expected: Any,
) -> int | None:
    """Count an explicitly observed record state without inventing zero."""
    view = _view(raw)
    count = 0
    observed = False
    for group in groups:
        value = view.get(group.casefold())
        if value is None:
            continue
        for record in _records(value):
            record_view = _record_view(record)
            if not any(field.casefold() in record_view for field in fields):
                continue
            observed = True
            if _first(record_view, fields, parser) == expected:
                count += 1
    return count if observed else None


def _recursive_collection_count(
    raw: Mapping[str, Any], groups: Iterable[str]
) -> int | None:
    values = list(
        _recursive_group_values(raw, frozenset(group.casefold() for group in groups))
    )
    if not values:
        return None
    return sum(len(_records(value)) for value in values)


def _recursive_collection_enum_count(
    raw: Mapping[str, Any],
    groups: Iterable[str],
    fields: Iterable[str],
    *,
    expected: Any,
) -> int | None:
    count = 0
    observed = False
    group_names = frozenset(group.casefold() for group in groups)
    for value in _recursive_group_values(raw, group_names):
        for record in _records(value):
            record_view = _record_view(record)
            if not any(field.casefold() in record_view for field in fields):
                continue
            observed = True
            if _first(record_view, fields, _text) == expected:
                count += 1
    return count if observed else None


def _recursive_group_values(raw: Any, groups: frozenset[str]) -> Iterable[Any]:
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if _secret_key(str(key)):
                continue
            if str(key).strip().casefold() in groups:
                yield value
            yield from _recursive_group_values(value, groups)
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            yield from _recursive_group_values(item, groups)


def _prefixed_boolean_count(
    view: Mapping[str, Any], prefixes: Iterable[str]
) -> int | None:
    parsed: list[bool] = []
    normalized_prefixes = tuple(prefix.casefold() for prefix in prefixes)
    for key, value in view.items():
        if not key.startswith(normalized_prefixes):
            continue
        for scalar in _scalar_values(value):
            boolean = _boolean(scalar)
            if boolean is not None:
                parsed.append(boolean)
    return sum(parsed) if parsed else None


def _nas_capacity_totals(
    raw: Mapping[str, Any], groups: Iterable[str]
) -> tuple[int | None, int | None]:
    """Aggregate capacity columns without retaining storage identity or paths."""
    view = _view(raw)
    records: list[Mapping[str, Any]] = []
    for group in groups:
        value = view.get(group.casefold())
        if value is not None:
            records.extend(_records(value))
    if not records:
        records = [view]

    def total(aliases: tuple[str, ...]) -> int | None:
        values: list[int] = []
        for record in records:
            record_view = _record_view(record)
            for alias in aliases:
                key = alias.casefold()
                if key not in record_view:
                    continue
                for scalar in _scalar_values(record_view[key]):
                    parsed = _nas_capacity_bytes(scalar)
                    if parsed is not None:
                        values.append(parsed)
        return sum(values) if values else None

    return (
        total(("nas_device_total", "total_kib")),
        total(("nas_device_used", "used_kib")),
    )


def _collection_observed_empty(
    raw: Mapping[str, Any],
    groups: Iterable[str],
    *,
    prefixes: Iterable[str] = (),
) -> bool:
    """Return true only when observed collection representations are all empty."""
    view = _view(raw)
    observed_counts: list[int] = []
    for group in groups:
        key = group.casefold()
        if key not in view:
            continue
        value = view[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            observed_counts.append(max(int(value), 0))
        else:
            observed_counts.append(len(_records(value)))
    if observed_counts:
        return all(count == 0 for count in observed_counts)
    for prefix in prefixes:
        columns = {
            key.removeprefix(prefix): value
            for key, value in view.items()
            if key.startswith(prefix)
        }
        if columns:
            observed_counts.append(len(_records(columns)))
    return bool(observed_counts) and all(count == 0 for count in observed_counts)


def _fields(
    view: Mapping[str, Any],
    aliases: Mapping[str, tuple[tuple[str, ...], Parser]],
) -> NormalizedData:
    result: NormalizedData = {}
    for canonical, (candidates, parser) in aliases.items():
        parsed = _first(view, candidates, parser)
        if parsed is not None:
            result[canonical] = parsed
    return result


def _first(
    view: Mapping[str, Any],
    candidates: Iterable[str],
    parser: Parser,
) -> Any | None:
    for candidate in candidates:
        key = candidate.casefold()
        if key not in view:
            continue
        values = _scalar_values(view[key])
        for raw_value in values:
            parsed = parser(raw_value)
            if parsed is not None:
                return parsed
    return None


def _scalar_values(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _view(raw: Mapping[str, Any]) -> NormalizedData:
    if _forbidden_varid_record(raw):
        return {}
    return {
        str(key).strip().casefold(): value
        for key, value in raw.items()
        if str(key).strip().casefold() not in _FORBIDDEN_RAW_FIELDS
        and not _secret_key(str(key))
    }


def _record_view(raw: Mapping[str, Any]) -> NormalizedData:
    """Expose canonical record keys while retaining safe prefixed originals."""
    view = _view(raw)
    prefixes = (
        "mdevice_",
        "device_",
        "meshdevice_",
        "manageddevice_",
        "mesh_",
        "node_",
        "repeater_",
        "phonenumber_",
        "phonenum_",
        "telnumber_",
        "telephone_",
        "telephony_",
        "number_",
        "line_",
        "msn_",
        "dialedcalls_",
        "missedcalls_",
        "takencalls_",
        "call_",
        "dectdevice_",
        "dect_",
        "handset_",
        "ipphone_",
        "ip_phone_",
        "usbdevice_",
        "usb_device_",
        "usb_",
        "receiver_",
        "external_5g_",
        "ex5g_",
        "mobile_",
        "lte_",
    )
    expanded = dict(view)
    pending = list(view.items())
    while pending:
        key, value = pending.pop()
        for prefix in prefixes:
            if not key.startswith(prefix):
                continue
            stripped = key.removeprefix(prefix)
            if not stripped or _secret_key(stripped) or stripped in expanded:
                continue
            expanded[stripped] = value
            pending.append((stripped, value))
    return expanded


def _safe_mapping(raw: Mapping[str, Any]) -> NormalizedData:
    if _forbidden_varid_record(raw):
        return {}

    safe: NormalizedData = {}
    for key, value in raw.items():
        normalized_key = str(key)
        if normalized_key.strip().casefold() in _FORBIDDEN_RAW_FIELDS or _secret_key(
            normalized_key
        ):
            continue
        if isinstance(value, Mapping):
            safe[normalized_key] = _safe_mapping(value)
        elif isinstance(value, list | tuple):
            safe[normalized_key] = [
                _safe_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            safe[normalized_key] = value
    return safe


def _forbidden_varid_record(raw: Mapping[str, Any]) -> bool:
    """Return whether one firmware varid row carries forbidden metadata."""
    return any(
        str(key).strip().casefold() == "varid"
        and isinstance(value, str)
        and value.strip().casefold() in _FORBIDDEN_RAW_FIELDS
        for key, value in raw.items()
    )


def _secret_key(key: str) -> bool:
    normalized = key.strip().casefold()
    return any(token in normalized for token in _SECRET_TOKENS)


def _without_missing(values: Mapping[str, Any]) -> NormalizedData:
    return {
        key: value
        for key, value in values.items()
        if value is not None and (not isinstance(value, str) or value.strip())
    }


def _merge_root(target: NormalizedData, root: str, value: Mapping[str, Any]) -> None:
    if not value:
        return
    existing = target.get(root)
    if isinstance(existing, Mapping):
        target[root] = _deep_merge(dict(existing), value)
    else:
        target[root] = dict(value)


def _deep_merge(base: Mapping[str, Any], update: Mapping[str, Any]) -> NormalizedData:
    merged = dict(base)
    for key, value in update.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _deduplicate_client_records(
    records: Iterable[NormalizedData],
) -> list[NormalizedData]:
    """Merge clients while withholding controls for duplicated source rows."""
    unique: dict[str, NormalizedData] = {}
    source_counts: dict[str, int] = {}
    unkeyed: list[NormalizedData] = []
    for record in records:
        identifier = record.get("id")
        if identifier is None:
            unkeyed.append(record)
            continue
        key = str(identifier).casefold()
        if record.get("source_kind") is not None:
            source_counts[key] = source_counts.get(key, 0) + 1
        unique[key] = _deep_merge(unique.get(key, {}), record)

    for key, count in source_counts.items():
        if count <= 1:
            continue
        for field in (
            "source_kind",
            "source_row_id",
            "managed_form_supported",
            "fixed_dhcp",
            "uses_dhcp",
            "uses_rule",
        ):
            unique[key].pop(field, None)
    return [*unique.values(), *unkeyed]


def _deduplicate(records: Iterable[NormalizedData]) -> list[NormalizedData]:
    unique: dict[str, NormalizedData] = {}
    unkeyed: list[NormalizedData] = []
    for record in records:
        identifier = record.get("id")
        if identifier is None:
            unkeyed.append(record)
            continue
        key = str(identifier).casefold()
        unique[key] = _deep_merge(unique.get(key, {}), record)
    return [*unique.values(), *unkeyed]


def _present(view: Mapping[str, Any], key: str) -> bool:
    return key in view and view[key] not in _EMPTY


def _online_uptime_seconds(view: Mapping[str, Any]) -> int | None:
    explicit = _first(
        view,
        ("uptime_seconds", "online_time_seconds", "inet_uptime_seconds"),
        _seconds,
    )
    if explicit is not None:
        return int(explicit)

    days = _first(view, ("days_online", "online_days"), _integer)
    clock = _first(view, ("time_online", "online_time"), _seconds)
    if days is None and clock is None:
        return None
    return max(days or 0, 0) * 86_400 + max(clock or 0, 0)


def _internet_connected_since(value: Any) -> str | None:
    """Return firmware connection timestamp only with an explicit UTC offset."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?"
        r"(?:Z|[+-](?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))",
        text,
    )
    if match is None:
        # The router UI localizes timestamps for display. Without a transmitted
        # offset, interpreting a locale-shaped or naive value would invent the
        # router timezone. Keep the field absent instead.
        return None
    offset_hour = match.group("offset_hour")
    offset_minute = match.group("offset_minute")
    if offset_hour is not None and (
        int(offset_hour) > _MAX_CLOCK_HOUR
        or int(offset_minute or "0") > _MAX_CLOCK_MINUTE
    ):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


def _call_timestamp(view: Mapping[str, Any]) -> datetime | None:
    combined = _first(
        view,
        ("timestamp", "datetime", "call_datetime", "call_time"),
        _datetime_value,
    )
    if isinstance(combined, datetime):
        return combined

    date = _first(view, ("date", "call_date"), _text)
    time = _first(view, ("time", "start_time", "call_time"), _text)
    if date is None or time is None:
        return None
    return _datetime_value(f"{date} {time}")


def _phone_like(value: str) -> bool:
    compact = "".join(character for character in value if not character.isspace())
    digits = sum(character.isdigit() for character in compact)
    return digits >= _MIN_PHONE_LABEL_DIGITS and digits * 2 >= len(compact)


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, Mapping):
        return None
    text = str(value).strip()
    return text or None


def _bounded_collection_text(value: Any) -> str | None:
    """Return bounded text suitable for an administrator-only collection."""
    text = _text(value)
    if (
        text is None
        or len(text) > _MAX_COLLECTION_TEXT_LENGTH
        or not text.isprintable()
    ):
        return None
    return text


def _bounded_technical_text(value: Any) -> str | None:
    """Return exact bounded firmware text without coercing an unknown type."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_COLLECTION_TEXT_LENGTH or not text.isprintable():
        return None
    return text


def _non_phone_identifier(value: Any) -> str | None:
    """Return a bounded row ID only when it cannot be a dialable number."""
    identifier = _bounded_collection_text(value)
    if identifier is None or _phone_like(identifier):
        return None
    return identifier


def _bounded_port_list(value: Any) -> str | None:
    """Return one exact, bounded comma-separated port/range list."""
    text = _bounded_collection_text(value)
    if text is None:
        return None
    for entry in text.split(","):
        parts = tuple(part.strip() for part in entry.split("-"))
        if len(parts) not in {1, _PORT_RANGE_LENGTH} or any(
            not part.isdigit() for part in parts
        ):
            return None
        ports = tuple(int(part) for part in parts)
        if any(not 0 <= port <= _MAX_TCP_PORT for port in ports):
            return None
        if len(ports) == _PORT_RANGE_LENGTH and ports[0] >= ports[1]:
            return None
    return text


def _state(value: Any) -> str | bool | None:
    boolean = _boolean(value)
    if boolean is not None:
        return boolean
    return _text(value)


def _internet_failure_reason(value: Any) -> str | None:
    """Return only failure-reason codes proven by the firmware status UI."""
    if not isinstance(value, str):
        return None
    return value if value in _INTERNET_FAILURE_REASONS else None


def _boolean_or_state(value: Any) -> bool | str | None:
    boolean = _boolean(value)
    return boolean if boolean is not None else _text(value)


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {
        "1",
        "active",
        "connected",
        "enabled",
        "on",
        "online",
        "registered",
        "true",
        "up",
        "yes",
    }:
        return True
    if normalized in {
        "0",
        "disabled",
        "disconnected",
        "down",
        "false",
        "inactive",
        "no",
        "off",
        "offline",
        "unregistered",
    }:
        return False
    return None


def _binary_option(value: Any) -> bool | None:
    """Decode firmware option fields whose contract is exactly 0 or 1."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in {"0", "1"}:
            return normalized == "1"
    return None


def _nonzero_boolean(value: Any) -> bool | None:
    number = _integer(value)
    return number != 0 if number is not None else None


def _nonempty_text_boolean(value: Any) -> bool | None:
    if value is None or isinstance(value, Mapping):
        return None
    return bool(str(value).strip())


def _powerline_parent(value: Any) -> str | None:
    parent = _bounded_collection_text(value)
    if parent is None or parent.casefold() == "ff:ff:ff:ff:ff:ff":
        return None
    return parent


def _powerline_kilobits_to_bps(value: Any) -> int | None:
    number = _nonnegative_integer(value)
    return number * 1_000 if number is not None else None


def _number_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER.search(value.replace(" ", ""))
    if match is None:
        return None
    try:
        return float(match.group().replace(",", "."))
    except ValueError:
        return None


def _nonzero_number_value(value: Any) -> float | None:
    number = _number_value(value)
    return number if number not in {None, 0.0} else None


def _integer(value: Any) -> int | None:
    number = _number_value(value)
    return int(number) if number is not None else None


def _nonnegative_integer(value: Any) -> int | None:
    number = _integer(value)
    return number if number is not None and number >= 0 else None


def _ipv4_octet(value: Any) -> int | None:
    number = _integer(value)
    return number if number is not None and 0 <= number <= _IPV4_MAX_OCTET else None


def _dotted_octets(
    view: Mapping[str, Any], prefix: str, *, first_default: int | None
) -> str | None:
    """Build one dotted IPv4 value only from four valid firmware octets."""
    parts: list[int] = []
    for index in range(1, 5):
        if index == 1 and first_default is not None:
            key = f"{prefix}_{index}"
            if key in view:
                part = _ipv4_octet(view[key])
                if part is None:
                    return None
                parts.append(part)
            else:
                parts.append(first_default)
            continue
        part = _first(view, (f"{prefix}_{index}",), _ipv4_octet)
        if part is None:
            return None
        parts.append(part)
    return ".".join(str(part) for part in parts)


def _lan_ipv4_prefix(view: Mapping[str, Any]) -> str | None:
    parts = [_first(view, (f"lan_ipv4_{index}",), _ipv4_octet) for index in range(1, 4)]
    if any(part is None for part in parts):
        return None
    return ".".join(str(part) for part in parts)


def _privacy_level(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _provisioning_code(value: Any) -> str | None:
    text = _text(value)
    if text is None or re.fullmatch(r"[A-Za-z0-9._-]{1,16}", text) is None:
        return None
    return text


def _bng_configured(value: Any) -> bool | None:
    code = _provisioning_code(value)
    return (
        code[1] == "4"
        if code is not None and len(code) >= _MIN_BNG_CODE_LENGTH
        else None
    )


def _manual_telephony_configuration(value: Any) -> bool | None:
    code = _provisioning_code(value)
    return code in {"003", "004"} if code is not None else None


def _internet_provider_family(value: Any) -> str | None:
    code = _nonnegative_integer(value)
    if code is None:
        return None
    return "telekom" if code in {0, 99} else "other"


def _telephony_provider_family(value: Any) -> str | None:
    code = _nonnegative_integer(value)
    if code is None:
        return None
    return "telekom" if code in {0, 99} else "other"


def _telephony_provider_family_from_view(view: Mapping[str, Any]) -> str | None:
    value = view.get("isp_selection")
    if value is None:
        return None
    families = {
        parsed
        for candidate in _scalar_values(value)
        if (parsed := _telephony_provider_family(candidate)) is not None
    }
    if "other" in families:
        return "other"
    return "telekom" if "telekom" in families else None


def _wifi_band_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _wifi_channel_width_mode(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-3]", value):
        number = int(value)
    else:
        return None
    return {
        0: "single_channel",
        _WIFI_CHANNEL_WIDTH_40_MHZ: "40_mhz",
        _WIFI_CHANNEL_WIDTH_80_MHZ: "80_mhz",
        _WIFI_CHANNEL_WIDTH_160_MHZ: "160_mhz",
    }.get(number)


def _wifi_schedule_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _wifi_generation(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {4, 5, 6} else None


def _ddns_status_code(value: Any) -> int | None:
    if isinstance(value, str):
        named = {"notreg": 0, "err": 1, "reg": 2}.get(value.strip().casefold())
        if named is not None:
            return named
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _voip_line_status(value: Any) -> str | None:
    status = _bounded_collection_text(value)
    if status is None:
        return None
    normalized = status.casefold()
    return normalized if normalized in {"ok", "inactive", "warning"} else None


def _pbx_client_status(value: Any) -> str | None:
    code = _integer(value)
    if code is None:
        return None
    return {
        0: "disconnected",
        1: "registered",
        2: "locked",
    }.get(code)


def _router_operating_mode(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _ROUTER_OPERATING_MODES.get(value.strip().upper())


def _mobile_status_code(value: Any) -> int | None:
    number = _integer(value)
    return number if number in _MOBILE_STATUS_CODES else None


def _client_medium(view: Mapping[str, Any]) -> str | None:
    exact: str | None = _first(view, ("mdevice_type",), _network_medium_code)
    if exact is not None:
        return exact
    return _first(view, ("medium", "interface", "connection_type"), _text)


def _network_medium_code(value: Any) -> str | None:
    code = _nonnegative_integer(value)
    return _CLIENT_MEDIUM_CODES.get(code) if code is not None else None


def _client_model(view: Mapping[str, Any]) -> str | None:
    candidates: tuple[str, ...] = ("model", "product_name")
    if "mdevice_type" not in view:
        candidates += ("type",)
    return _first(view, candidates, _text)


def _client_web_ui_port(value: Any) -> int | None:
    return _port_number(value)


def _port_number(value: Any) -> int | None:
    """Return one valid TCP/UDP port number without coercing a range."""
    port = _strict_port_value(value)
    if port is None or not 1 <= port <= _MAX_TCP_PORT:
        return None
    return port


def _client_has_web_ui(value: Any) -> bool | None:
    port = _strict_port_value(value)
    if port is None:
        return None
    if port == 0:
        return False
    return 1 <= port <= _MAX_TCP_PORT or None


def _strict_port_value(value: Any) -> int | None:
    """Parse only an integer or an exact ASCII-decimal port field."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}", value):
        return None
    return int(value)


def _ddns_domain(value: Any) -> str | None:
    """Return a bounded DNS hostname, never credentials or arbitrary prose."""
    hostname = _strict_dns_name(value)
    return hostname if hostname is not None and "." in hostname else None


def _ddns_update_server(value: Any) -> str | None:
    """Return a host or host-only HTTP(S) URL without embedded credentials."""
    text = _bounded_collection_text(value)
    if text is None:
        return None
    if "://" not in text:
        return _strict_dns_name(text)

    parsed = urlsplit(text)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or _strict_dns_name(parsed.hostname) is None
    ):
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is not None and _port_number(port) is None:
        return None
    return text


def _ddns_update_protocol(value: Any) -> str | None:
    """Return only the two reviewed Dynamic DNS transport schemes."""
    text = _text(value)
    if text is None:
        return None
    protocol = text.casefold()
    return protocol if protocol in {"http", "https"} else None


def _strict_dns_name(value: Any) -> str | None:
    """Return a conservative ASCII DNS name without userinfo or paths."""
    text = _bounded_collection_text(value)
    if text is None or len(text) > _MAX_DNS_NAME_LENGTH or not text.isascii():
        return None
    hostname = text.removesuffix(".")
    if not hostname or any(
        _DNS_LABEL.fullmatch(label) is None for label in hostname.split(".")
    ):
        return None
    return hostname


def _client_web_ui_scheme(value: Any) -> str | None:
    port = _client_web_ui_port(value)
    if port is None:
        return None
    return "https" if port % 2 else "http"


def _nr_band_code(value: Any) -> str | None:
    text = _text(value)
    return text if text in _NR_BAND_CODES else None


def _lte_band_code(value: Any) -> str | None:
    text = _text(value)
    return text if text in _LTE_BAND_CODES else None


def _bounded_label(value: Any) -> str | None:
    text = _text(value)
    if text is None or len(text) > _MAX_FIRMWARE_VERSION_LENGTH:
        return None
    return text if all(character.isprintable() for character in text) else None


def _bounded_error_code(value: Any) -> str | None:
    text = _text(value)
    if text is None or re.fullmatch(r"[A-Za-z0-9._-]{1,16}", text) is None:
        return None
    return text


def _esim_supported(value: Any) -> bool | None:
    text = _text(value)
    if text is None:
        return None
    return text.casefold() != "not supported"


def _wps_state_code(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {-2, -1, 0, 1} else None


def _receiver_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2, 3} else None


def _mesh_device_type(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _mesh_wifi_enabled(value: Any) -> bool | None:
    number = _integer(value)
    if number not in {0, 1, 2}:
        return None
    return number != _MESH_WLAN_DISABLED


def _led_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _clock_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > _MAX_CLOCK_HOUR or minute > _MAX_CLOCK_MINUTE:
        return None
    return f"{hour:02d}:{minute:02d}"


def _firmware_version(value: Any) -> str | None:
    text = _text(value)
    if text is None or len(text) > _MAX_FIRMWARE_VERSION_LENGTH:
        return None
    if re.fullmatch(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", text) is None:
        return None
    return text


def _nas_capacity_bytes(value: Any) -> int | None:
    number = _number_value(value)
    if number is None or number < 0:
        return None
    return int(number * _NAS_VALUE_BYTES)


def _percentage(value: Any) -> float | None:
    number = _number_value(value)
    if number is None:
        return None
    return min(max(number, 0.0), 100.0)


def _seconds(value: Any) -> int | None:
    if isinstance(value, str):
        text = value.strip()
        # The public Status endpoint uses inet_uptime as an ISO connection
        # start timestamp. It must never be interpreted as a duration.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", text) or re.fullmatch(
            r"\d{1,2}\.\d{1,2}\.\d{4}(?:\s+.*)?",
            text,
        ):
            return None
        clock = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", text)
        if clock is not None:
            hours, minutes, seconds = (
                int(clock.group(1)),
                int(clock.group(2)),
                int(clock.group(3) or 0),
            )
            if minutes >= _SECONDS_PER_MINUTE or seconds >= _SECONDS_PER_MINUTE:
                return None
            return hours * 3_600 + minutes * _SECONDS_PER_MINUTE + seconds
    number = _number_value(value)
    if number is None or number < 0:
        return None
    if isinstance(value, str):
        normalized = value.casefold()
        if "day" in normalized or "tag" in normalized:
            number *= 86_400
        elif "hour" in normalized or "stunde" in normalized:
            number *= 3_600
        elif "min" in normalized:
            number *= 60
    return int(number)


def _bytes(value: Any) -> int | None:
    number = _number_value(value)
    if number is None or number < 0:
        return None
    if isinstance(value, str):
        normalized = value.casefold().replace(" ", "")
        if "tb" in normalized:
            number *= 1_000_000_000_000
        elif "gb" in normalized:
            number *= 1_000_000_000
        elif "mb" in normalized:
            number *= 1_000_000
        elif "kb" in normalized:
            number *= 1_000
    return int(number)


def _bps(value: Any) -> int | None:
    number = _number_value(value)
    if number is None or number < 0:
        return None
    if isinstance(value, str):
        normalized = value.casefold().replace(" ", "")
        if "gbit" in normalized or "gbps" in normalized:
            number *= 1_000_000_000
        elif "mbit" in normalized or "mbps" in normalized:
            number *= 1_000_000
        elif "kbit" in normalized or "kbps" in normalized:
            number *= 1_000
    return int(number)


def _timestamp(value: Any) -> str | None:
    parsed = _datetime_value(value)
    return parsed.isoformat() if parsed is not None else None


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                parsed = datetime.strptime(text, pattern).replace(tzinfo=UTC)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _mac_address(value: Any) -> str | None:
    text = _text(value)
    if text is None or _MAC.fullmatch(text) is None:
        return None
    return text.upper().replace("-", ":")


def _private_address(value: Any) -> str | None:
    # Client addresses are useful entity attributes but are stripped from
    # diagnostics by the diagnostics layer. Never use them as identity.
    return _bounded_address_text(value)


def _public_address(value: Any) -> str | None:
    # Public addresses are legitimate entity values but are never copied into
    # device identity or child records.
    return _bounded_address_text(value)


def _bounded_address_text(value: Any) -> str | None:
    """Return bounded printable router address/range text."""
    text = _text(value)
    if text is None or len(text) > _MAX_ADDRESS_TEXT_LENGTH or not text.isprintable():
        return None
    return text


def _safe_url(value: Any) -> str | None:
    text = _text(value)
    if text is None or not text.casefold().startswith(("https://", "http://")):
        return None
    return text


def _port_has_device(value: Any) -> bool:
    link_speed = _lan_link_speed_bps(value)
    if link_speed is not None:
        return link_speed > 0
    boolean = _boolean(value)
    if boolean is not None:
        return boolean
    text = _text(value)
    return text is not None and text.casefold() not in {"none", "unknown", "-"}


def _lan_link_speed_bps(value: Any) -> int | None:
    """Map the exact link-rate representation used by calcLANSpeed()."""
    text = _text(value)
    if text is None or re.fullmatch(r"[0-9]{1,10}", text) is None:
        return None
    speed = int(text)
    return speed if speed in _LAN_LINK_SPEEDS_BPS else None


def _linked_lan_port_count(view: Mapping[str, Any], keys: Iterable[str]) -> int | None:
    observed = [view[key] for key in keys if key in view]
    if not observed:
        return None
    return sum(_port_has_device(value) for value in observed)
