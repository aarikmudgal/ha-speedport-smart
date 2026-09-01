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

from .const import MANAGED_DEVICE_FORM_FIELDS, MANAGED_DEVICE_SOURCE_KINDS
from .identity import port_forward_rule_fingerprint

if TYPE_CHECKING:
    from .models import RouterStatus

NormalizedData = dict[str, Any]
Parser = Callable[[Any], Any | None]

_EMPTY: Final = (None, "")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_MAC = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
_MIN_PHONE_LABEL_DIGITS: Final = 5
_SECONDS_PER_MINUTE: Final = 60
_NAS_VALUE_BYTES: Final = 1_024
_TETHERING_CONNECTED_STATUS: Final = 2
_MAX_CLOCK_HOUR: Final = 23
_MAX_CLOCK_MINUTE: Final = 59
_MAX_FIRMWARE_VERSION_LENGTH: Final = 64
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

_MANAGEMENT_SCOPED_FAMILIES: Final = frozenset(
    {
        "connection_privacy",
        "dns_rebind",
        "easy_support",
        "firmware",
        "nas",
        "port_blocking",
        "qos",
        "usb_tethering",
        "wifi_access",
        "wifi_configuration",
        "wps",
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
        "wps": _normalize_wifi,
        "mesh": _normalize_mesh,
        "lan": _normalize_lan,
        "dhcp": _normalize_dhcp,
        "clients": _normalize_clients,
        "nat": _normalize_nat,
        "ddns": _normalize_ddns,
        "vpn": _normalize_vpn,
        "parental": _normalize_parental,
        "telephony": _normalize_telephony,
        "pbx": _normalize_pbx,
        "dect": _normalize_dect,
        "receiver": _normalize_receiver,
        "security": _normalize_security,
        "dns_rebind": _normalize_security,
        "port_blocking": _normalize_security,
        "qos": _normalize_qos,
        "usb": _normalize_usb,
        "nas": _normalize_usb,
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
        },
    )
    uptime_seconds = _online_uptime_seconds(view)
    if uptime_seconds is not None:
        internet["uptime_seconds"] = uptime_seconds
    _merge_root(result, "internet", internet)
    _merge_root(result, "dsl", _dsl_fields(view, include_generic=False))
    _merge_root(result, "hybrid", _hybrid_fields(view, include_generic=False))
    _merge_root(result, "mobile", _mobile_fields(view, include_generic=False))
    _merge_root(result, "wifi", _wifi_fields(view))
    _merge_root(result, "mesh", _mesh_fields(view))
    _merge_root(result, "lan", _lan_fields(view))
    _merge_root(result, "dect", _dect_fields(view))
    _merge_root(result, "pbx", _pbx_fields(view))
    _merge_root(result, "vpn", _vpn_fields(view, include_generic=False))
    _merge_root(result, "system", _system_fields(view))
    _merge_root(result, "security", _security_fields(view))
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
            "privacy_level": (("lan_privacy_policy",), _privacy_level),
        },
    )
    return {"internet": internet} if internet else {}


def _normalize_connection_privacy(raw: Mapping[str, Any]) -> NormalizedData:
    privacy_level = _first(_view(raw), ("lan_privacy_policy",), _privacy_level)
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
    mobile = _mobile_fields(_view(raw), include_generic=True)
    return {"mobile": mobile} if mobile else {}


def _mobile_fields(view: Mapping[str, Any], *, include_generic: bool) -> NormalizedData:
    aliases: dict[str, tuple[tuple[str, ...], Parser]] = {
        "connected": (
            (
                "mobile_connected",
                "lte_connected",
                "lte_tunnel",
                "ex5g_status",
                "lte_status",
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
                "ex5g_signal_5g",
                "ex5g_lte_rsrp",
                "ex5g_signal_lte",
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
                "ex5g_freq_5g",
                "ex5g_freq_lte",
                "lte_band",
                "mobile_band",
            ),
            _text,
        ),
        "frequency_mhz": (
            (
                "ex5g_frequency",
                "ex5g_freq_5g",
                "ex5g_freq_lte",
                "lte_frequency",
                "mobile_frequency",
            ),
            _number_value,
        ),
        "cell_id": (("ex5g_cell_id", "lte_cell_id", "mobile_cell_id"), _text),
        "external_modem_enabled": (("auto_external_modem",), _boolean),
        "receiver_mode": (("extwan_typ",), _receiver_mode),
        "lte_enabled": (("use_lte",), _boolean),
        "led_mode": (("ex5g_led_mode",), _led_mode),
        "firmware_auto_update": (("auto_update",), _boolean),
        "firmware_update_available": (("ex5g_fwupd_avail",), _boolean),
        "firmware_version": (("ex5g_fw_version",), _firmware_version),
        "latest_firmware": (("ex5g_fwupd_version",), _firmware_version),
        "firmware_update_planned": (("ex5g_fwupd_planned",), _boolean),
        "firmware_update_time": (("ex5g_fwupd_time",), _timestamp),
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
    if "network_type" not in mobile:
        if _present(view, "ex5g_signal_5g"):
            mobile["network_type"] = "5G"
        elif _present(view, "ex5g_signal_lte"):
            mobile["network_type"] = "LTE"
    return mobile


def _normalize_wifi(raw: Mapping[str, Any]) -> NormalizedData:
    wifi = _wifi_fields(_view(raw))
    return {"wifi": wifi} if wifi else {}


def _wifi_fields(view: Mapping[str, Any]) -> NormalizedData:
    wifi = _fields(
        view,
        {
            "enabled": (
                ("use_wlan", "wlan_active", "wlan_enabled", "wifi_enabled"),
                _boolean,
            ),
            "wps_status": (("wps_status", "use_wps", "wps_active"), _boolean_or_state),
            "wps_enabled": (("use_wps",), _boolean),
            "wps_state_code": (("wlan_wps_state",), _wps_state_code),
            "wps_disabled_by_firmware": (("disabled_wps",), _boolean),
            "mac_filter_enabled": (("wlan_mac_active",), _boolean),
            "schedule_enabled": (("wlan_time_active",), _boolean),
            "allow_all_devices": (("wlan_allow_all",), _boolean),
            "band_mode": (("wlan_band",), _wifi_band_mode),
        },
    )
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
                ("wlan_client_count", "wlan_2_4_client_count"),
                _integer,
            ),
            "visible": (("wlan_visible",), _boolean),
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
                ("wlan_5ghz_client_count", "wlan_5_client_count"),
                _integer,
            ),
            "visible": (("wlan_5ghz_visible",), _boolean),
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
            "encryption_mode": (("wlan_guest_enc",), _nonnegative_integer),
            "wps_enabled": (("wlan_guest_wps",), _boolean),
        },
    )
    office = _fields(
        view,
        {
            "enabled": (("wlan_office_active", "office_enabled"), _boolean),
            "encryption_mode": (("wlan_office_enc",), _nonnegative_integer),
        },
    )
    schedule = _wifi_schedule_fields(view)
    if schedule:
        wifi["schedule"] = schedule
        if "schedule_enabled" not in wifi and "mode" in schedule:
            wifi["schedule_enabled"] = schedule["mode"] != 0
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
    lan = _lan_fields(_view(raw))
    return {"lan": lan} if lan else {}


def _lan_fields(view: Mapping[str, Any]) -> NormalizedData:
    linked = 0
    observed = False
    for port in range(1, 5):
        raw_value = view.get(f"lan{port}_device")
        if raw_value is None:
            continue
        observed = True
        if _port_has_device(raw_value):
            linked += 1
    lan: NormalizedData = {}
    if observed:
        lan["linked_port_count"] = linked
    explicit = _first(view, ("linked_port_count", "lan_linked_ports"), _integer)
    if explicit is not None:
        lan["linked_port_count"] = explicit
    return lan


def _normalize_dhcp(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    dhcp = _fields(
        view,
        {
            "enabled": (("use_dhcp", "dhcp_enabled", "dhcp_active"), _boolean),
        },
    )
    lease_count = _collection_count(raw, ("addlease", "leases", "dhcp_leases"))
    if lease_count is None:
        lease_count = _first(view, ("lease_count", "dhcp_lease_count"), _integer)
    if lease_count is not None:
        dhcp["leases"] = lease_count
    return {"dhcp": dhcp} if dhcp else {}


def _normalize_clients(raw: Mapping[str, Any]) -> NormalizedData:
    items = _client_records(raw)
    if not items:
        if _collection_observed_empty(
            raw,
            _CLIENT_GROUPS,
            prefixes=("mdevice_", "device_"),
        ):
            return {"clients": {"items": [], "connected_count": 0}}
        return {}
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
            "model": _first(
                view,
                ("model", "type", "product_name"),
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
            "ipv4": _first(view, ("ipv4", "ip", "ip_address"), _private_address),
            "ipv6": _first(view, ("ipv6", "gua_ipv6", "ula_ipv6"), _private_address),
            "connected": _first(
                view,
                ("connected", "online", "active", "present"),
                _boolean,
            ),
            "medium": medium
            or _first(view, ("medium", "interface", "connection_type"), _text),
            "signal_dbm": _first(view, ("rssi", "signal", "signal_dbm"), _number_value),
            "link_speed_bps": _first(
                view,
                ("link_speed_bps", "speed_bps", "speed"),
                _bps,
            ),
            "download_rate_bps": _first(
                view,
                ("download_rate_bps", "download_rate", "down_rate", "rx_rate"),
                _bps,
            ),
            "upload_rate_bps": _first(
                view,
                ("upload_rate_bps", "upload_rate", "up_rate", "tx_rate"),
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
        for record in _records(value):
            record_view = _view(record)
            identifier = _first(
                record_view,
                ("id", "rule_id", "portuw_id"),
                _text,
            )
            if identifier is None:
                continue
            rule = _without_missing(
                {
                    "id": identifier,
                    "name": _first(
                        record_view,
                        ("name", "rule_name", "portuw_name"),
                        _text,
                    ),
                    "active": _first(
                        record_view,
                        ("active", "enabled", "portuw_active"),
                        _boolean,
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


def _normalize_ddns(raw: Mapping[str, Any]) -> NormalizedData:
    ddns = _fields(
        _view(raw),
        {
            "enabled": (
                (
                    "ddns_enabled",
                    "dyndns_active",
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
            "provider": (("ddns_provider", "provider"), _text),
            "last_update": (("ddns_last_update", "last_update"), _timestamp),
        },
    )
    return {"ddns": ddns} if ddns else {}


def _normalize_vpn(raw: Mapping[str, Any]) -> NormalizedData:
    view = _view(raw)
    vpn = _vpn_fields(view, include_generic=True)
    peer_values = next(
        (view[key] for key in ("addpeer", "peers", "wireguard_peers") if key in view),
        None,
    )
    if peer_values is not None:
        peers = [
            _without_missing(
                {
                    "connected": _first(
                        _view(record),
                        ("connected", "active", "status"),
                        _boolean_or_state,
                    ),
                    "last_handshake": _first(
                        _view(record),
                        ("last_handshake", "handshake"),
                        _timestamp,
                    ),
                }
            )
            for record in _records(peer_values)
        ]
        vpn["peers"] = peers
        vpn["connected_peer_count"] = sum(
            peer.get("connected") is True for peer in peers
        )
    return {"vpn": vpn} if vpn else {}


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
                ("parental_enabled", "parental_control_enabled", "use_parental"),
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
        },
    )
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
    if numbers:
        telephony["numbers"] = numbers
    elif _collection_observed_empty(
        raw,
        number_groups,
        prefixes=_device_prefixes("telephone_line"),
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
    return {"telephony": telephony} if telephony else {}


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
        ("adddectdevice", "handsets", "dect_devices"),
        kind="dect",
    )
    if handsets:
        dect["handsets"] = handsets
    else:
        count = _collection_count(raw, ("adddectdevice", "handsets", "dect_devices"))
        if count is not None:
            dect["handsets"] = count
    handset_count = _first(view, ("dect_real_count",), _nonnegative_integer)
    if handset_count is None:
        handset_count = _collection_count(raw, ("adddect", "handsets", "dect_devices"))
    if handset_count is not None:
        dect["handset_count"] = handset_count
    repeater_count = _collection_count(raw, ("addrepeater", "dect_repeaters"))
    if repeater_count is not None:
        dect["repeater_count"] = repeater_count
    phonebooks = _collection_count(raw, ("addphonebook", "phonebooks"))
    if phonebooks is not None:
        dect["phonebooks"] = phonebooks
    return {"dect": dect} if dect else {}


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

    port_block_groups = ("addextra", "extended_rules", "port_block_rules")
    port_block_rules = _collection_count(raw, port_block_groups)
    if port_block_rules is not None:
        security["port_block_rule_count"] = port_block_rules
    active_port_block_rules = _collection_enum_count(
        raw,
        port_block_groups,
        ("extendedrule_active", "child_extrarule_active", "active"),
        parser=_boolean,
        expected=True,
    )
    if active_port_block_rules is not None:
        security["active_port_block_rule_count"] = active_port_block_rules
    return {"security": security} if security else {}


def _security_fields(
    view: Mapping[str, Any], *, include_generic: bool = False
) -> NormalizedData:
    firewall: tuple[str, ...] = ("firewall_enabled", "use_firewall")
    if include_generic:
        firewall += ("enabled", "active")
    return _fields(
        view,
        {
            "firewall_enabled": (firewall, _boolean),
            "dns_rebind_protection": (
                ("dns_rebind_protection", "rebind_protection"),
                _boolean,
            ),
            "port_blocking_enabled": (("child_extrarule_active",), _boolean),
            "remote_management": (
                ("remote_management", "remote_access_enabled"),
                _boolean,
            ),
        },
    )


def _normalize_qos(raw: Mapping[str, Any]) -> NormalizedData:
    prioritized = _prefixed_boolean_count(_view(raw), ("qos_pc",))
    if prioritized is None:
        return {}
    return {"qos": {"prioritized_client_count": prioritized}}


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
            "nas_enabled": (("nas_active",), _boolean),
            "nas_secure": (("nas_secure",), _boolean),
            "nas_read_only": (("nas_folder_nur_lesen",), _boolean),
            "media_server_enabled": (
                ("media_server_enabled", "use_media_server"),
                _boolean,
            ),
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
    total_bytes, used_bytes = _nas_capacity_totals(raw, storage_groups)
    if total_bytes is not None:
        usb["storage_total_bytes"] = total_bytes
    if used_bytes is not None:
        usb["storage_used_bytes"] = used_bytes
    if total_bytes is not None and used_bytes is not None:
        usb["storage_free_bytes"] = max(total_bytes - used_bytes, 0)

    return {"usb": usb} if usb else {}


def _normalize_receiver(raw: Mapping[str, Any]) -> NormalizedData:
    receiver = _fields(
        _view(raw),
        {
            "external_modem_enabled": (("auto_external_modem",), _boolean),
            "mode": (("extwan_typ",), _receiver_mode),
            "lte_enabled": (("use_lte",), _boolean),
            "led_mode": (("ex5g_led_mode",), _led_mode),
            "firmware_auto_update": (("auto_update",), _boolean),
            "firmware_update_available": (("ex5g_fwupd_avail",), _boolean),
            "firmware_version": (("ex5g_fw_version",), _firmware_version),
            "latest_firmware": (("ex5g_fwupd_version",), _firmware_version),
            "firmware_update_planned": (("ex5g_fwupd_planned",), _boolean),
            "firmware_update_time": (("ex5g_fwupd_time",), _timestamp),
        },
    )
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
    return {"receiver": receiver} if receiver else {}


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
                ("model", "type", "product_name", "model_name"),
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
        return _fields(
            view,
            {
                **common_connection,
                **traffic,
                **radio,
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
            },
        )
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
    return {
        str(key).strip().casefold(): value
        for key, value in raw.items()
        if not _secret_key(str(key))
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
    safe: NormalizedData = {}
    for key, value in raw.items():
        normalized_key = str(key)
        if _secret_key(normalized_key):
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


def _state(value: Any) -> str | bool | None:
    boolean = _boolean(value)
    if boolean is not None:
        return boolean
    return _text(value)


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


def _integer(value: Any) -> int | None:
    number = _number_value(value)
    return int(number) if number is not None else None


def _nonnegative_integer(value: Any) -> int | None:
    number = _integer(value)
    return number if number is not None and number >= 0 else None


def _privacy_level(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _wifi_band_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _wifi_schedule_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2} else None


def _wps_state_code(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {-2, -1, 0, 1} else None


def _receiver_mode(value: Any) -> int | None:
    number = _integer(value)
    return number if number in {0, 1, 2, 3} else None


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
    return _text(value)


def _public_address(value: Any) -> str | None:
    # Public addresses are legitimate entity values but are never copied into
    # device identity or child records.
    return _text(value)


def _safe_url(value: Any) -> str | None:
    text = _text(value)
    if text is None or not text.casefold().startswith(("https://", "http://")):
        return None
    return text


def _port_has_device(value: Any) -> bool:
    boolean = _boolean(value)
    if boolean is not None:
        return boolean
    text = _text(value)
    return text is not None and text.casefold() not in {"none", "unknown", "-"}
