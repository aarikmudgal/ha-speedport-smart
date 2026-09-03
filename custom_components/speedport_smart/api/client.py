"""Serialized async client for Speedport JSON and Telekom ToTR64 protocols."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Final, Protocol, cast
from urllib.parse import urlencode, urlsplit

import aiohttp

from ..admin_actions import get_admin_action_contract
from ..configuration import ConfigurationError, settings_contracts
from ..configuration_targets import (
    resolve_settings_contract,
    target_settings_read_pairs,
)
from ..const import (
    MANAGED_DEVICE_FORM_FIELDS,
    RECEIVER_LED_MODE_CODES,
)
from ..identity import port_forward_rule_fingerprint, valid_device_name
from ..maintenance import MaintenanceError, maintenance_payload
from ..models import (
    CandidateInventoryResult,
    CapabilityReport,
    DslMetrics,
    EndpointCapability,
    ParameterValue,
    RouterInfo,
    RouterStatus,
    WanCounters,
    WanInterface,
    normalize_status,
    select_active_wan_interface,
)
from ..private_authorization import check_private_authorization
from .codec import DEFAULT_KEY, decode_payload, encode_payload, is_encrypted_payload
from .exceptions import (
    SpeedportAuthenticationError,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportMutationOutcomeUnknownError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from .totr64 import SOAP_ACTION, build_get_parameter_values, parse_get_parameter_values

_HTTP_TOKEN_PATTERNS: Final = (
    re.compile(r"var\s+_httoken\s*=\s*[\"']?(\d+)[\"']?\s*;"),
    re.compile(r"name=[\"']httoken[\"'][^>]*value=[\"']([^\"']+)[\"']"),
)
_INTERFACE_PARAMETER = re.compile(r"^Device\.IP\.Interface\.(\d+)\.(.+)$")
_LOGIN_MARKERS: Final = (
    "login/index.html",
    "login_index_html",
    "document moved",
)
_MAX_INTERFACE_COUNT: Final = 64
_MAX_INTERFACE_SCAN: Final = 16
_HTTP_BAD_REQUEST: Final = 400
_HTTP_NOT_FOUND: Final = 404
_LOGOUT_REFERER: Final = "html/content/overview/index.html"
_LOGOUT_SETTLE_SECONDS: Final = 0.5
_LOGOUT_REJECTED_STATES: Final = frozenset(
    {"denied", "error", "failed", "failure", "false", "invalid", "0"}
)
_LOGOUT_ACCEPTED_STATES: Final = frozenset({"1", "ok", "success", "true"})
_WAN_BYTE_COUNTER_SUFFIXES: Final = (
    "BytesReceived",
    "BytesSent",
)
_WAN_OPTIONAL_COUNTER_SUFFIXES: Final = (
    "PacketsReceived",
    "PacketsSent",
    "ErrorsReceived",
    "ErrorsSent",
    "DiscardPacketsReceived",
    "DiscardPacketsSent",
)
_WAN_COUNTER_SUFFIXES: Final = (
    *_WAN_BYTE_COUNTER_SUFFIXES,
    *_WAN_OPTIONAL_COUNTER_SUFFIXES,
)
_INTERFACE_METADATA_SUFFIXES: Final = (
    "Alias",
    "Name",
    "Status",
    "Enable",
)
_DSL_LINE_INDEX: Final = 1
_DSL_CHANNEL_INDEX: Final = 1
_DSL_DOWNSTREAM_CURRENT_RATE: Final = (
    f"Device.DSL.Channel.{_DSL_CHANNEL_INDEX}.DownstreamCurrRate"
)
_DSL_UPSTREAM_CURRENT_RATE: Final = (
    f"Device.DSL.Channel.{_DSL_CHANNEL_INDEX}.UpstreamCurrRate"
)
_DSL_PARAMETER_NAMES: Final = (
    f"Device.DSL.Channel.{_DSL_CHANNEL_INDEX}.Status",
    _DSL_DOWNSTREAM_CURRENT_RATE,
    _DSL_UPSTREAM_CURRENT_RATE,
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.DownstreamMaxBitRate",
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.UpstreamMaxBitRate",
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.DownstreamNoiseMargin",
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.UpstreamNoiseMargin",
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.DownstreamAttenuation",
    f"Device.DSL.Line.{_DSL_LINE_INDEX}.UpstreamAttenuation",
)
_DEVICE_LIST_ENDPOINT: Final = "data/DeviceList.json"
_DEVICE_LIST_REFERER: Final = "html/content/network/devices.html"
_PORT_FORWARD_ENDPOINT: Final = "data/PortuwMain.json"
_PORT_FORWARD_REFERER: Final = "html/content/internet/portforwarding.html"
_PORT_FORWARD_GROUPS: Final = frozenset({"addportuw", "port_forward_rules", "portuw"})
_INTERNET_PRIVACY_ENDPOINT: Final = "data/IPPrivacy.json"
_INTERNET_PRIVACY_REFERER: Final = "html/content/internet/con_privacy.html"
_LTE_MODE_ENDPOINT: Final = "data/LTE.json"
_LTE_MODE_REFERER: Final = "html/content/internet/lte_mode.html"
_LTE_FIRMWARE_REFERER: Final = "html/content/internet/lte_firmware.html"
_IP_INFORMATION_MAX_RESPONSE_BYTES: Final = 128 * 1024
_WPS_ENDPOINT: Final = "data/WLANAccess.json"
_WPS_STATUS_ENDPOINT: Final = "data/WPSStatus.json"
_WPS_REFERER: Final = "html/content/network/wlan_wps.html"
_WIFI_ACCESS_REFERER: Final = "html/content/network/wlan_access.html"
_QUERY_TOKEN_VALUE = re.compile(r"^[0-9]{1,32}$")
_QUERY_TOKEN_READS: Final = frozenset(
    {
        (_INTERNET_PRIVACY_ENDPOINT, _INTERNET_PRIVACY_REFERER),
        (_LTE_MODE_ENDPOINT, _LTE_MODE_REFERER),
        (_LTE_MODE_ENDPOINT, _LTE_FIRMWARE_REFERER),
        ("data/IPData.json", "html/content/internet/con_ipdata.html"),
        (_WPS_ENDPOINT, _WPS_REFERER),
        (_WPS_ENDPOINT, _WIFI_ACCESS_REFERER),
        ("data/NASFolder.json", "html/content/network/nas_share.html"),
        ("data/NASFileCount.json", "html/content/network/nas_mediareplay.html"),
        ("data/PhoneOnlbuch.json", "html/content/phone/phone_book_basic.html"),
        ("data/FwCheckForUpdate.json", "html/content/config/check_for_updates.html"),
        (
            "data/FwCheckForUpdateMesh.json",
            "html/content/config/check_for_updates_mesh.html",
        ),
    }
)
_IP_PBX_CLIENTS_ENDPOINT: Final = "data/IPClients.json"
_IP_PBX_CLIENTS_REFERER: Final = "html/content/phone/phone_ippbx.html"
_PHONEBOOK_ENDPOINT: Final = "data/PhoneBook.json"
_PHONEBOOK_ENTRY_ENDPOINT: Final = "data/PhoneBookEntry.json"
_PHONEBOOK_REFERER: Final = "html/content/phone/phone_book_entries.html"
_DECT_ACTION_ENDPOINT: Final = "data/DECT.json"
_DECT_STATION_ENDPOINT: Final = "data/DECTStation.json"
_DECT_STATUS_ENDPOINT: Final = "data/DECTInfo.json"
_DECT_REPEATER_ENDPOINT: Final = "data/DECTRepeater.json"
_DECT_MOBILES_REFERER: Final = "html/content/phone/phone_dect_mobiles.html"
_DECT_REPEATER_REFERER: Final = "html/content/phone/phone_dect_repeater.html"
_VOIP_PROVIDERS_ENDPOINT: Final = "data/IPPhone.json"
_VOIP_LINES_ENDPOINT: Final = "data/IPPhoneNumbers.json"
_VOIP_LINES_REFERER: Final = "html/content/phone/phone_internet.html"
_NAS_FOLDERS_ENDPOINT: Final = "data/NASFolder.json"
_NAS_FOLDERS_REFERER: Final = "html/content/network/nas_share.html"
_THREE_STATE_VALUES: Final = frozenset({"0", "1", "2"})
_BINARY_STATE_VALUES: Final = frozenset({"0", "1"})
_WPS_STATE_VALUES: Final = frozenset({"-2", "-1", "0", "1"})
_IP_PBX_STATUS_VALUES: Final = {0: "disconnected", 1: "registered", 2: "locked"}
_PHONEBOOK_IDS: Final = frozenset(range(6))
_PRIVATE_QUERY_MAX_ROWS: Final = 256
_PRIVATE_PHONEBOOK_MAX_ROWS: Final = 1000
_SETTINGS_TARGET_MAX_ROWS: Final = 64
_PHONEBOOK_SETTINGS_MAX_TARGETS: Final = 5000
_PRIVATE_QUERY_MAX_TEXT_LENGTH: Final = 256
_PRIVATE_QUERY_MAX_PHONE_LENGTH: Final = 64
_PRIVATE_QUERY_MAX_DECT_TARGETS: Final = 16
_PRIVATE_QUERY_MAX_VOIP_TARGETS: Final = 32
_PRIVATE_QUERY_MAX_DISPLAY_NAME_LENGTH: Final = 64
_MASKED_PHONE_SUFFIX_DIGITS: Final = 4
_MAX_VOIP_PROVIDER_CODE: Final = 9_999
_PRIVATE_QUERY_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PHONEBOOK_SEARCH_PREFIX = re.compile(r"^[A-Za-z]?$")
_PHONEBOOK_NUMBER = re.compile(r"^\+?[0-9/\-*# ]*$")
_PHONEBOOK_BIRTHDAY = re.compile(r"^(?:|\d{2}\.\d{2}\.\d{4})$")
_OBSERVED_SCHEMA_MAX_DEPTH: Final = 6
_OBSERVED_SCHEMA_MAX_FIELDS: Final = 128
_OBSERVED_SCHEMA_MAX_FAMILIES: Final = 96
_OBSERVED_SCHEMA_MAX_CANDIDATES: Final = 128
_OBSERVED_SCHEMA_MAX_CANDIDATES_PER_FAMILY: Final = 8
_OBSERVED_SCHEMA_MAX_ARRAY_ITEMS: Final = 8
_OBSERVED_SCHEMA_MAX_MAPPING_ITEMS: Final = 256
_OBSERVED_SCHEMA_MAX_NAME_LENGTH: Final = 64
_OBSERVED_SCHEMA_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_]*(?:\[\])?$")
_OBSERVED_SCHEMA_ENDPOINT = re.compile(
    r"^data/(?P<name>[A-Za-z][A-Za-z0-9_-]{0,63})\.json$"
)
_OBSERVED_SCHEMA_REFERER = re.compile(
    r"^html/content/(?P<path>[a-z0-9_-]+(?:/[a-z0-9_-]+){0,4})\.html$"
)
_OBSERVED_SCHEMA_ARRAY_INDEX = re.compile(r"\[\d+\]")
_OBSERVED_SCHEMA_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
_OBSERVED_SCHEMA_MAC = re.compile(r"(?i)^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$")
_OBSERVED_SCHEMA_SEPARATED_MAC = re.compile(
    r"(?i)(?:^|_)(?:[0-9a-f]{2}_){5}[0-9a-f]{2}(?:_|$)"
)
_OBSERVED_SCHEMA_COMPACT_IDENTIFIER = re.compile(r"(?i)^[0-9a-f]{12,}$")
_OBSERVED_SCHEMA_IP_TOKENS = re.compile(r"(?:^|_)(?:\d{1,3}_){3}\d{1,3}(?:_|$)")
_OBSERVED_SCHEMA_LONG_NUMBER = re.compile(r"\d{6,}")
_OBSERVED_SCHEMA_DYNAMIC_KEY = re.compile(
    r"^(?:client|device|entry|host|peer|row|rule|user)_"
    r"(?:\d+|[0-9a-f]{8,}|[a-z0-9]{16,})$"
)
_OBSERVED_SCHEMA_BLOCKED_TOKENS: Final = frozenset(
    {
        "authorization",
        "auth",
        "authentication",
        "challenge",
        "cookie",
        "credential",
        "csrf",
        "endpoint",
        "fingerprint",
        "host",
        "hostname",
        "httoken",
        "id",
        "key",
        "login",
        "nonce",
        "origin",
        "passphrase",
        "password",
        "payload",
        "pin",
        "puk",
        "raw",
        "referer",
        "referrer",
        "secret",
        "session",
        "token",
        "uid",
        "url",
        "username",
        "uuid",
    }
)


class _PrivateQueryParser(Protocol):
    """One bounded scalar parser for private query projections."""

    def __call__(self, value: Any, *, max_length: int) -> str | None:
        """Return one safe scalar or reject it."""


_OBSERVED_SCHEMA_SAFE_SINGLE_FIELDS: Final = frozenset(
    {
        "active",
        "available",
        "bond",
        "call",
        "calls",
        "channel",
        "client",
        "clients",
        "connected",
        "count",
        "deep",
        "device",
        "devices",
        "dsl",
        "empty",
        "enabled",
        "energy",
        "errors",
        "firewall",
        "firmware",
        "frequency",
        "guest",
        "hybrid",
        "internet",
        "ip",
        "item",
        "items",
        "lan",
        "lte",
        "matrix",
        "mesh",
        "mobile",
        "mode",
        "nas",
        "node",
        "nodes",
        "office",
        "online",
        "packets",
        "pbx",
        "phone",
        "phonebook",
        "port",
        "ports",
        "qos",
        "receiver",
        "result",
        "router",
        "rows",
        "safe",
        "service",
        "services",
        "speedport",
        "state",
        "status",
        "system",
        "telephony",
        "type",
        "upnp",
        "usb",
        "values",
        "version",
        "vpn",
        "wan",
        "wide",
        "wifi",
        "wireguard",
        "wlan",
        "wps",
    }
)
_OBSERVED_SCHEMA_SAFE_FIELDS: Final = _OBSERVED_SCHEMA_SAFE_SINGLE_FIELDS | frozenset(
    {
        "addipclient",
        "addipnumber",
        "addipphoneprovider",
        "addrepeater",
        "adddnsexcept",
        "addmdevice",
        "addmpriodevice",
        "addmwlan5device",
        "addmwlandevice",
        "addnasdevice",
        "addnasmediareplay",
        "addpwlinedevice",
        "addvpn",
        "addwgdevice",
        "auto_external_modem",
        "auto_update",
        "br_active",
        "dns_rebind_active",
        "dect_detect_status",
        "dect_real_count",
        "dsl_errnr",
        "dsl_link_status",
        "dyndns_active",
        "dyndns_domain",
        "dyndns_updport",
        "dyndns_updprot",
        "dyndns_updsrv",
        "easy_support_deactive",
        "ex5g_eid",
        "ex5g_freq_5g",
        "ex5g_freq_lte",
        "ex5g_fw_version",
        "ex5g_fwupd_avail",
        "ex5g_fwupd_planned",
        "ex5g_fwupd_time",
        "ex5g_fwupd_version",
        "ex5g_led_mode",
        "ex5g_model_name",
        "ex5g_signal_5g",
        "ex5g_signal_lte",
        "extwan_status",
        "extwan_typ",
        "fail_reason",
        "hdvoice",
        "inet_errnr",
        "inet_isp",
        "internet_extrule_active",
        "internet_timerule_active",
        "ipclient_status",
        "isp_selection",
        "lan1_device",
        "lan2_device",
        "lan3_device",
        "lan4_device",
        "lan4_link_status",
        "lan_dhcp_validtime",
        "lan_ip_v6",
        "lan_ip_v6_arec",
        "lan_ip_v6_pext",
        "lan_ip_v6_range",
        "lan_ip_v6_used",
        "lte_status",
        "mdevice_connected",
        "mdevice_gua_ipv6",
        "mdevice_hasui",
        "mdevice_standards",
        "mdevice_type",
        "mdevice_ula_ipv6",
        "mesh_lan1",
        "mesh_lan2",
        "mesh_type",
        "nas_active",
        "nas_device_connection",
        "nas_device_total",
        "nas_device_type",
        "nas_device_used",
        "nas_folder_nur_lesen",
        "nas_folder_name",
        "nas_secure",
        "number_status",
        "num_entries",
        "onlinestatus",
        "privacy_policy",
        "provis_inet",
        "provis_voip",
        "pwline_connect_to",
        "pwline_downspeed",
        "pwline_firmware",
        "pwline_mac",
        "pwline_manufacturer",
        "pwline_mode",
        "pwline_upspeed",
        "qos_pc",
        "router_firewall_active",
        "router_state",
        "save_fails",
        "smarthome_status",
        "source_kind",
        "use_bonding",
        "use_https",
        "use_lte",
        "use_wlan",
        "varid",
        "varvalue",
        "vpn_status",
        "wlan0_num",
        "wlan1_num",
        "wlan_5ghz_speed_act",
        "wlan_active",
        "wlan_band",
        "wlan_finished",
        "wlan_guest_active",
        "wlan_guest_display_key",
        "wlan_guest_ssid",
        "wlan_guest_timeleft",
        "wlan_office_active",
        "wlan_office_ssid",
        "wlan_office_wps",
        "wlan_ssid",
        "wlan_5ghz_ssid",
        "wlan_visible",
        "wlanfinished",
    }
)


@dataclass(frozen=True, slots=True)
class _ManagedDeviceForm:
    """One firmware-proven managed-device row form."""

    endpoint: str
    fields: frozenset[str]


_MANAGED_DEVICE_FORMS: Final[Mapping[str, _ManagedDeviceForm]] = MappingProxyType(
    {
        "addmdevice": _ManagedDeviceForm(
            "data/ManagedDevice.json", MANAGED_DEVICE_FORM_FIELDS["addmdevice"]
        ),
        "addmlandevice": _ManagedDeviceForm(
            "data/ManagedLANDevice.json",
            MANAGED_DEVICE_FORM_FIELDS["addmlandevice"],
        ),
        "addmwlandevice": _ManagedDeviceForm(
            "data/ManagedWLAN2Device.json",
            MANAGED_DEVICE_FORM_FIELDS["addmwlandevice"],
        ),
        "addmwlan5device": _ManagedDeviceForm(
            "data/ManagedWLAN5Device.json",
            MANAGED_DEVICE_FORM_FIELDS["addmwlan5device"],
        ),
    }
)


def _endpoint(
    family: str,
    path: str,
    *,
    authenticated: bool = False,
    referer: str | None = None,
    evidence_keys: tuple[str, ...] = (),
    automatic_probe: bool = True,
    inventory_safe: bool = True,
) -> EndpointCapability:
    """Build one statically reviewed built-in read endpoint contract."""
    return EndpointCapability(
        family=family,
        endpoint=path,
        authenticated=authenticated,
        referer=referer,
        evidence_keys=evidence_keys,
        automatic_probe=automatic_probe,
        inventory_safe=inventory_safe,
    )


DEFAULT_FEATURE_CANDIDATES: Final[Mapping[str, tuple[EndpointCapability, ...]]] = (
    MappingProxyType(
        {
            "internet": (
                _endpoint(
                    "internet",
                    "data/Overview.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("online", "internet", "inet_"),
                ),
            ),
            "dsl": (
                _endpoint(
                    "dsl",
                    "data/Overview.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("dsl",),
                ),
            ),
            "hybrid": (
                _endpoint(
                    "hybrid",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("hybrid", "bond"),
                ),
            ),
            "wifi": (
                _endpoint(
                    "wifi",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=(
                        "wlan_active",
                        "wlan_guest_active",
                        "wlan_office_active",
                        "wlan_time_active",
                    ),
                ),
                _endpoint(
                    "wifi",
                    "data/WLANBasic.json",
                    authenticated=True,
                    referer="html/content/network/wlan_basic.html",
                    evidence_keys=("wlan", "wifi"),
                ),
            ),
            "wifi_configuration": (
                _endpoint(
                    "wifi_configuration",
                    "data/WLANBasicAss.json",
                    authenticated=True,
                    referer="html/content/network/wlan_name_enc.html",
                    evidence_keys=("wlan", "ssid", "enc", "visible"),
                ),
                _endpoint(
                    "wifi_configuration",
                    "data/WLANSettings.json",
                    authenticated=True,
                    referer="html/content/network/wlan_settings.html",
                    evidence_keys=("wlan", "wifi"),
                ),
            ),
            "wifi_schedule": (
                _endpoint(
                    "wifi_schedule",
                    "data/WLANBasic.json",
                    authenticated=True,
                    referer="html/content/network/wlan_basic.html",
                    evidence_keys=(
                        "wlan_timerule",
                        "wlan_dfrom",
                        "wlan_dto",
                        "wlan_time_mo_",
                        "wlan_time_di_",
                        "wlan_time_mi_",
                        "wlan_time_do_",
                        "wlan_time_fr_",
                        "wlan_time_sa_",
                        "wlan_time_so_",
                    ),
                ),
            ),
            "lan": (
                _endpoint(
                    "lan",
                    "data/LAN.json",
                    authenticated=True,
                    referer="html/content/network/lan.html",
                    evidence_keys=("lan", "dhcp", "subnet"),
                ),
                _endpoint(
                    "lan",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=("device", "client", "host", "lan"),
                ),
            ),
            "clients": (
                _endpoint(
                    "clients",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=("device", "client", "host"),
                ),
                _endpoint(
                    "clients",
                    "data/HomeNetwork.json",
                    authenticated=True,
                    referer="html/content/network/home_network.html",
                    evidence_keys=("device", "client", "host"),
                ),
                _endpoint(
                    "clients",
                    "data/Modules.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("device", "client", "host"),
                ),
            ),
            "ip": (
                _endpoint(
                    "ip",
                    "data/IPData.json",
                    authenticated=True,
                    referer="html/content/internet/con_ipdata.html",
                    evidence_keys=("public_ip", "gateway", "dns", "ipv"),
                ),
            ),
            "internet_configuration": (
                _endpoint(
                    "internet_configuration",
                    "data/InternetConnection.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                    evidence_keys=(
                        "onlinestatus",
                        "auto_external_modem",
                        "extwan_status",
                        "lte_status",
                    ),
                    automatic_probe=False,
                ),
                _endpoint(
                    "internet_configuration",
                    "data/INetIP.json",
                    authenticated=True,
                    referer="html/content/internet/connection.html",
                    evidence_keys=("inet_isp", "isp_selection", "internet"),
                    automatic_probe=False,
                ),
            ),
            "connection_privacy": (
                _endpoint(
                    "connection_privacy",
                    "data/IPPrivacy.json",
                    authenticated=True,
                    referer="html/content/internet/con_privacy.html",
                    evidence_keys=("lan_privacy_policy",),
                ),
            ),
            "telephony": (
                _endpoint(
                    "telephony",
                    "data/PhoneCalls.json",
                    authenticated=True,
                    referer="html/content/phone/phone_call_taken.html",
                    evidence_keys=("call",),
                ),
            ),
            "system": (
                _endpoint(
                    "system",
                    "data/Router.json",
                    authenticated=True,
                    referer="html/content/index.html",
                    evidence_keys=("router", "firmware", "serial", "uptime"),
                ),
            ),
            "ip_phones": (
                _endpoint(
                    "ip_phones",
                    "data/IPPhoneHandler.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                    evidence_keys=("ip_phone", "ipphone", "sip"),
                ),
            ),
            "telephony_configuration": (
                _endpoint(
                    "telephony_configuration",
                    "data/IPPhone.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                    evidence_keys=("addipphoneprovider", "isp_selection", "phone"),
                    automatic_probe=False,
                ),
                _endpoint(
                    "telephony_configuration",
                    "data/IPPhoneNumbers.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                    evidence_keys=("addipnumber", "number_status", "phone"),
                    automatic_probe=False,
                ),
                _endpoint(
                    "telephony_configuration",
                    "data/PhoneNumberAssignment.json",
                    authenticated=True,
                    referer="html/content/phone/phone_number.html",
                    evidence_keys=("phone", "number", "assignment"),
                    automatic_probe=False,
                ),
            ),
            "voip_lines": (
                _endpoint(
                    "voip_lines",
                    _VOIP_LINES_ENDPOINT,
                    authenticated=True,
                    referer=_VOIP_LINES_REFERER,
                    evidence_keys=("addipnumber", "number_status"),
                ),
            ),
            "voip_providers": (
                _endpoint(
                    "voip_providers",
                    _VOIP_PROVIDERS_ENDPOINT,
                    authenticated=True,
                    referer=_VOIP_LINES_REFERER,
                    evidence_keys=("addipphoneprovider", "isp_selection"),
                ),
            ),
            "wps": (
                _endpoint(
                    "wps",
                    _WPS_ENDPOINT,
                    authenticated=True,
                    referer=_WPS_REFERER,
                    evidence_keys=("use_wps",),
                ),
            ),
            "wps_status": (
                _endpoint(
                    "wps_status",
                    _WPS_STATUS_ENDPOINT,
                    authenticated=True,
                    referer=_WPS_REFERER,
                    evidence_keys=("wlan_wps_state",),
                ),
            ),
            "wifi_access": (
                _endpoint(
                    "wifi_access",
                    _WPS_ENDPOINT,
                    authenticated=True,
                    referer=_WIFI_ACCESS_REFERER,
                    evidence_keys=("wlan", "wps", "access"),
                ),
            ),
            "wifi_environment": (
                _endpoint(
                    "wifi_environment",
                    "data/WLANEnviron.json",
                    authenticated=True,
                    referer="html/content/network/wlan_environ.html",
                    evidence_keys=("wlan", "ssid", "channel", "environment"),
                    automatic_probe=False,
                    inventory_safe=False,
                ),
            ),
            "port_forwarding": (
                _endpoint(
                    "port_forwarding",
                    "data/PortuwMain.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("portuw", "forward", "mapping"),
                ),
                _endpoint(
                    "port_forwarding",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("internet_ports_active",),
                ),
            ),
            "mobile": (
                _endpoint(
                    "mobile",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=("mobile", "lte", "5g", "ex5g"),
                ),
                _endpoint(
                    "mobile",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("mobile", "lte", "5g", "webnwalk"),
                ),
                _endpoint(
                    "mobile",
                    "data/WebnWalk.json",
                    authenticated=True,
                    referer="html/content/internet/webnwalk.html",
                    evidence_keys=("mobile", "lte", "5g", "webnwalk"),
                ),
            ),
            "lte": (
                _endpoint(
                    "lte",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=("lte", "ex5g_signal_lte", "webnwalk"),
                ),
                _endpoint(
                    "lte",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("lte", "webnwalk"),
                ),
                _endpoint(
                    "lte",
                    "data/WebnWalk.json",
                    authenticated=True,
                    referer="html/content/internet/webnwalk.html",
                    evidence_keys=("lte", "webnwalk"),
                ),
            ),
            "lte_log": (
                _endpoint(
                    "lte_log",
                    "data/LTElog.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=("addmessage", "message", "log"),
                    automatic_probe=False,
                ),
            ),
            "5g": (
                _endpoint(
                    "5g",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=("5g", "ex5g"),
                ),
                _endpoint(
                    "5g",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("5g", "ex5g"),
                ),
                _endpoint(
                    "5g",
                    "data/WebnWalk.json",
                    authenticated=True,
                    referer="html/content/internet/webnwalk.html",
                    evidence_keys=("5g", "ex5g"),
                ),
            ),
            "receiver": (
                _endpoint(
                    "receiver",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=(
                        "receiver",
                        "ex5g",
                        "external_5g",
                        "auto_external_modem",
                        "extwan_typ",
                        "use_lte",
                    ),
                ),
                _endpoint(
                    "receiver",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=(
                        "receiver",
                        "ex5g",
                        "external_5g",
                        "auto_external_modem",
                        "extwan_typ",
                        "use_lte",
                    ),
                ),
            ),
            "receiver_led": (
                _endpoint(
                    "receiver_led",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                    evidence_keys=("ex5g_led_mode",),
                ),
            ),
            "mesh": (
                _endpoint(
                    "mesh",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("mesh",),
                ),
                _endpoint(
                    "mesh",
                    "data/Mesh.json",
                    authenticated=True,
                    referer="html/content/network/mesh.html",
                    evidence_keys=("mesh",),
                ),
            ),
            "mesh_topology": (
                _endpoint(
                    "mesh_topology",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=(
                        "addmeshdevice",
                        "mesh_connect_to",
                        "mesh_downspeed",
                        "mesh_ipv4",
                    ),
                ),
            ),
            "mesh_firmware": (
                _endpoint(
                    "mesh_firmware",
                    "data/FirmwareUpdateMesh.json",
                    authenticated=True,
                    referer="html/content/config/check_for_updates_mesh.html",
                    evidence_keys=("mesh", "firmware", "fwupd", "update"),
                    automatic_probe=False,
                ),
            ),
            "mesh_update": (
                _endpoint(
                    "mesh_update",
                    "data/FwCheckForUpdateMesh.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("mesh", "firmware", "fwupd", "update"),
                    automatic_probe=False,
                    inventory_safe=False,
                ),
            ),
            "mesh_reboot_status": (
                _endpoint(
                    "mesh_reboot_status",
                    "data/RebootMesh.json",
                    authenticated=True,
                    referer="html/content/config/problem_handling_mesh.html",
                    evidence_keys=("mesh", "reboot", "reset", "device"),
                    automatic_probe=False,
                ),
            ),
            "dhcp": (
                _endpoint(
                    "dhcp",
                    "data/LAN.json",
                    authenticated=True,
                    referer="html/content/network/dhcp.html",
                    evidence_keys=("dhcp", "lease", "reserved"),
                ),
                _endpoint(
                    "dhcp",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=("dhcp", "lease", "reserved", "device"),
                ),
            ),
            "nat": (
                _endpoint(
                    "nat",
                    "data/PortuwMain.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("portuw", "forward", "mapping", "nat"),
                ),
                _endpoint(
                    "nat",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("internet_ports_active",),
                ),
                _endpoint(
                    "nat",
                    "data/Portforwarding.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("forward", "mapping", "nat"),
                ),
            ),
            "upnp": (
                _endpoint(
                    "upnp",
                    "data/PortuwMain.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("upnp", "upnp_igd"),
                ),
            ),
            "port_blocking": (
                _endpoint(
                    "port_blocking",
                    "data/ExtendedRules.json",
                    authenticated=True,
                    referer="html/content/internet/portblocking.html",
                    evidence_keys=("extended", "portblock", "blocked", "rule"),
                ),
            ),
            "ddns": (
                _endpoint(
                    "ddns",
                    "data/DynDNS.json",
                    authenticated=True,
                    referer="html/content/internet/dyn_dns.html",
                    evidence_keys=("ddns", "dyndns", "dynamic_dns"),
                ),
                _endpoint(
                    "ddns",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("dyndns_active",),
                ),
                _endpoint(
                    "ddns",
                    "data/DDNS.json",
                    authenticated=True,
                    referer="html/content/internet/dynamic_dns.html",
                    evidence_keys=("ddns", "dyndns", "dynamic_dns"),
                ),
            ),
            "vpn": (
                _endpoint(
                    "vpn",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=(
                        "vpn_active",
                        "vpn_act_users",
                        "vpn_act_selection",
                        "vpn_typ",
                    ),
                ),
                _endpoint(
                    "vpn",
                    "data/VPN.json",
                    authenticated=True,
                    referer="html/content/internet/vpn.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
                _endpoint(
                    "vpn",
                    "data/WireGuard.json",
                    authenticated=True,
                    referer="html/content/internet/wireguard.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
                _endpoint(
                    "vpn",
                    "data/Wireguard.json",
                    authenticated=True,
                    referer="html/content/internet/wireguard.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
            ),
            "vpn_details": (
                _endpoint(
                    "vpn_details",
                    "data/VPN.json",
                    authenticated=True,
                    referer="html/content/internet/vpn.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
                _endpoint(
                    "vpn_details",
                    "data/WireGuard.json",
                    authenticated=True,
                    referer="html/content/internet/wireguard.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
                _endpoint(
                    "vpn_details",
                    "data/Wireguard.json",
                    authenticated=True,
                    referer="html/content/internet/wireguard.html",
                    evidence_keys=("wireguard", "vpn", "peer"),
                ),
            ),
            "parental": (
                _endpoint(
                    "parental",
                    "data/TimeRules.json",
                    authenticated=True,
                    referer="html/content/network/parental_control.html",
                    evidence_keys=("timerule", "time_rule", "parental", "profile"),
                ),
            ),
            "calls": (
                _endpoint(
                    "calls",
                    "data/PhoneCalls.json",
                    authenticated=True,
                    referer="html/content/phone/phone_call_taken.html",
                    evidence_keys=("call",),
                ),
            ),
            "active_calls": (
                _endpoint(
                    "active_calls",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("active_call", "call_state", "call_in_progress"),
                ),
                _endpoint(
                    "active_calls",
                    "data/PhoneCalls.json",
                    authenticated=True,
                    referer="html/content/phone/phone_call_taken.html",
                    evidence_keys=("active_call", "call_state", "call_in_progress"),
                ),
            ),
            "pbx": (
                _endpoint(
                    "pbx",
                    "data/IPPBX.json",
                    authenticated=True,
                    referer="html/content/phone/phone_ippbx.html",
                    evidence_keys=("pbx", "ippbx", "ip_phone", "ipphone", "sip"),
                ),
                _endpoint(
                    "pbx",
                    "data/IPPhoneHandler.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                    evidence_keys=("pbx", "ip_phone", "ipphone", "sip"),
                ),
                _endpoint(
                    "pbx",
                    "data/PhoneSettings.json",
                    authenticated=True,
                    referer="html/content/phone/settings.html",
                    evidence_keys=("pbx", "sip", "ip_phone", "ipphone"),
                ),
            ),
            "pbx_clients": (
                _endpoint(
                    "pbx_clients",
                    "data/IPClients.json",
                    authenticated=True,
                    referer="html/content/phone/phone_ippbx.html",
                    evidence_keys=("addipclient", "ipclient_status"),
                ),
            ),
            "dect": (
                _endpoint(
                    "dect",
                    "data/DECTStation.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_mobiles.html",
                    evidence_keys=("dect", "handset"),
                ),
                _endpoint(
                    "dect",
                    "data/DECTRepeater.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_repeater.html",
                    evidence_keys=("dect", "repeater"),
                ),
                _endpoint(
                    "dect",
                    "data/Phone.json",
                    authenticated=True,
                    referer="html/content/phone/phone_devices.html",
                    evidence_keys=("dect", "handset"),
                ),
                _endpoint(
                    "dect",
                    "data/PhoneSettings.json",
                    authenticated=True,
                    referer="html/content/phone/settings.html",
                    evidence_keys=("dect", "handset"),
                ),
            ),
            "dect_status": (
                _endpoint(
                    "dect_status",
                    "data/DECTInfo.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_mobiles.html",
                    evidence_keys=(
                        "dect_real_count",
                        "dect_detect_status",
                        "pagingstat",
                    ),
                ),
            ),
            "dect_settings": (
                _endpoint(
                    "dect_settings",
                    "data/DECTSettings.json",
                    authenticated=True,
                    referer="html/content/config/problem_handling_dect.html",
                    evidence_keys=("dect", "handset", "base"),
                    automatic_probe=False,
                ),
            ),
            "dect_repeater": (
                _endpoint(
                    "dect_repeater",
                    "data/DECTRepeater.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_repeater.html",
                    evidence_keys=("addrepeater", "dect_repeaters"),
                ),
            ),
            "analog": (
                _endpoint(
                    "analog",
                    "data/PhonePlugs.json",
                    authenticated=True,
                    referer="html/content/phone/phone_devices.html",
                    evidence_keys=("analog", "tae", "phone_plug", "phoneplug"),
                    automatic_probe=False,
                ),
                _endpoint(
                    "analog",
                    "data/PhonePlugs.json",
                    authenticated=True,
                    referer="html/content/phone/phone_analog.html",
                    evidence_keys=("analog", "tae", "phone_plug", "phoneplug"),
                    automatic_probe=False,
                ),
            ),
            "phonebook": (
                _endpoint(
                    "phonebook",
                    "data/PhoneBook.json",
                    authenticated=True,
                    referer="html/content/phone/phone_book.html",
                    evidence_keys=(
                        "addbookentry",
                        "num_entries",
                        "phonebook",
                        "contact",
                        "directory",
                    ),
                ),
            ),
            "security": (
                _endpoint(
                    "security",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=(
                        "security",
                        "firewall",
                        "rebind",
                        "remote_management",
                    ),
                ),
                _endpoint(
                    "security",
                    "data/SystemMessages.json",
                    authenticated=True,
                    referer="html/content/config/system_messages.html",
                    evidence_keys=("security", "firewall", "blocked"),
                ),
            ),
            "firewall": (
                _endpoint(
                    "firewall",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("firewall", "blocked_connection", "rebind"),
                ),
            ),
            "dns_rebind": (
                _endpoint(
                    "dns_rebind",
                    "data/DNSExcept.json",
                    authenticated=True,
                    referer="html/content/network/dns_rebind.html",
                    evidence_keys=("dns", "rebind", "except"),
                ),
            ),
            "qos": (
                _endpoint(
                    "qos",
                    "data/QOS.json",
                    authenticated=True,
                    referer="html/content/network/qos.html",
                    evidence_keys=("qos", "priority", "prio"),
                ),
            ),
            "usb": (
                _endpoint(
                    "usb",
                    "data/NASDevice.json",
                    authenticated=True,
                    referer="html/content/network/nas_overview.html",
                    evidence_keys=("usb", "nas", "storage", "printer"),
                ),
                _endpoint(
                    "usb",
                    "data/NASMediacenter.json",
                    authenticated=True,
                    referer="html/content/network/nas_mediacenter.html",
                    evidence_keys=("media", "nas", "usb", "storage"),
                ),
            ),
            "media_server": (
                _endpoint(
                    "media_server",
                    "data/NASMediacenter.json",
                    authenticated=True,
                    referer="html/content/network/nas_mediacenter.html",
                    evidence_keys=(
                        "addnasmediareplay",
                        "nas_media_shares",
                        "media_server_enabled",
                        "use_media_server",
                    ),
                ),
            ),
            "usb_tethering": (
                _endpoint(
                    "usb_tethering",
                    "data/INetTeth.json",
                    authenticated=True,
                    referer="html/content/internet/usb_tethering.html",
                    evidence_keys=("tether", "inet_teth"),
                ),
            ),
            "nas": (
                _endpoint(
                    "nas",
                    "data/NASDevice.json",
                    authenticated=True,
                    referer="html/content/network/nas_overview.html",
                    evidence_keys=("nas", "usb", "storage", "folder", "share"),
                ),
            ),
            "nas_folders": (
                _endpoint(
                    "nas_folders",
                    _NAS_FOLDERS_ENDPOINT,
                    authenticated=True,
                    referer=_NAS_FOLDERS_REFERER,
                    evidence_keys=(
                        "nas_active",
                        "nas_folder_name",
                        "nas_secure",
                    ),
                    inventory_safe=False,
                ),
            ),
            "logs": (
                _endpoint(
                    "logs",
                    "data/SystemMessages.json",
                    authenticated=True,
                    referer="html/content/config/system_messages.html",
                    evidence_keys=("message", "log", "error", "warning"),
                    automatic_probe=False,
                ),
            ),
            "diagnostics": (
                _endpoint(
                    "diagnostics",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("status", "uptime", "firmware", "version"),
                ),
            ),
            "system_services": (
                _endpoint(
                    "system_services",
                    "data/ActiveServices.json",
                    authenticated=True,
                    referer="html/content/config/system_services.html",
                    evidence_keys=("service", "active_service"),
                    automatic_probe=False,
                ),
            ),
            "energy": (
                _endpoint(
                    "energy",
                    "data/Energy.json",
                    authenticated=True,
                    referer="html/content/config/energy.html",
                    evidence_keys=("energy", "power", "eco", "led"),
                    automatic_probe=False,
                ),
            ),
            "backup_restore": (
                _endpoint(
                    "backup_restore",
                    "data/BackupRestore.json",
                    authenticated=True,
                    referer="html/content/config/save_settings.html",
                    evidence_keys=("br_active", "backup", "restore"),
                    automatic_probe=False,
                ),
            ),
            "easy_support": (
                _endpoint(
                    "easy_support",
                    "data/EasySupport.json",
                    authenticated=True,
                    referer="html/content/config/easy_support.html",
                    evidence_keys=("easy_support", "easysupport", "acs"),
                ),
            ),
            "firmware": (
                _endpoint(
                    "firmware",
                    "data/FirmwareUpdate.json",
                    authenticated=True,
                    referer="html/content/config/check_for_updates.html",
                    evidence_keys=("firmware", "fwupd", "update", "version"),
                ),
                _endpoint(
                    "firmware",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("firmware", "update", "version"),
                ),
                _endpoint(
                    "firmware",
                    "data/Update.json",
                    authenticated=True,
                    referer="html/content/config/check_for_updates.html",
                    evidence_keys=("firmware", "update", "version"),
                ),
            ),
        }
    )
)


class SpeedportClient:
    """Own all router I/O and serialize it through one request lock."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        password: str | None = None,
        *,
        use_https: bool = False,
        verify_ssl: bool = True,
        request_timeout: float = 10.0,
        json_port: int | None = None,
        tr064_http_port: int = 5438,
        tr064_https_port: int = 8443,
        max_busy_retries: int = 4,
        busy_backoff: float = 0.5,
        owns_session: bool = False,
        endpoint_candidates: Mapping[
            str, Sequence[EndpointCapability]
        ] = DEFAULT_FEATURE_CANDIDATES,
    ) -> None:
        """Initialize client without performing network I/O."""
        if request_timeout <= 0:
            msg = "request_timeout must be positive"
            raise ValueError(msg)
        if max_busy_retries < 0:
            msg = "max_busy_retries cannot be negative"
            raise ValueError(msg)
        if busy_backoff < 0:
            msg = "busy_backoff cannot be negative"
            raise ValueError(msg)

        normalized_host, detected_https, detected_port = _normalize_host(host)
        self._host = normalized_host
        self._use_https = use_https or detected_https
        self._verify_ssl = verify_ssl
        self._password = password or None
        self._session = session
        self._owns_session = owns_session
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._max_busy_retries = max_busy_retries
        self._busy_backoff = busy_backoff
        self._lock = asyncio.Lock()
        self._authenticated = False
        self._login_key: bytes | None = None
        self._session_cleanup_key: bytes | None = None
        self._encrypted_mode: bool | None = None
        self._closed = False
        self._router_info: RouterInfo | None = None
        self._last_status: RouterStatus | None = None
        self._capabilities = CapabilityReport()
        self._endpoint_candidates = {
            family: tuple(candidates)
            for family, candidates in endpoint_candidates.items()
        }
        self._selected_endpoints: dict[str, EndpointCapability] = {}
        self._observed_feature_schema: dict[str, tuple[tuple[str, str], ...]] = {}
        self._observed_candidate_schema: dict[
            str,
            dict[tuple[str, bool, str | None], tuple[tuple[str, str], ...]],
        ] = {}
        self._wan_interface: WanInterface | None = None
        self._wan_optional_counter_faults: set[int] = set()
        self._dsl_parameter_names: tuple[str, ...] | None = None
        self._last_management_error: SpeedportError | None = None

        scheme = "https" if self._use_https else "http"
        default_json_port = 443 if self._use_https else 80
        selected_json_port = json_port or detected_port or default_json_port
        self._base_url = _base_url(scheme, self._host, selected_json_port)
        tr064_port = tr064_https_port if self._use_https else tr064_http_port
        self._tr064_url = _base_url(scheme, self._host, tr064_port) + "/"

    @property
    def configuration_url(self) -> str:
        """Return the normalized local router web-interface URL."""
        return self._base_url

    @property
    def capabilities(self) -> CapabilityReport:
        """Return latest immutable capability report."""
        return self._capabilities

    @property
    def router_info(self) -> RouterInfo | None:
        """Return latest router identity."""
        return self._router_info

    @property
    def is_authenticated(self) -> bool:
        """Return whether client owns authenticated web session."""
        return self._authenticated

    @property
    def last_management_error(
        self,
    ) -> SpeedportError | None:
        """Return the latest typed management gate without logging owner details."""
        return self._last_management_error

    @property
    def observed_feature_schema(
        self,
    ) -> Mapping[str, tuple[Mapping[str, str], ...]]:
        """Return an immutable value-free snapshot for runtime diagnostics."""
        return MappingProxyType(
            {
                family: tuple(
                    MappingProxyType({"path": path, "shape": shape})
                    for path, shape in fields
                )
                for family, fields in self._observed_feature_schema.items()
            }
        )

    @property
    def observed_candidate_schema(
        self,
    ) -> Mapping[str, tuple[Mapping[str, object], ...]]:
        """Return immutable value-free schemas for successful probe candidates."""
        return MappingProxyType(
            {
                family: tuple(
                    MappingProxyType(
                        {
                            "endpoint": endpoint,
                            "authenticated": authenticated,
                            "referer": referer,
                            "schema": tuple(
                                MappingProxyType({"path": path, "shape": shape})
                                for path, shape in fields
                            ),
                        }
                    )
                    for (endpoint, authenticated, referer), fields in candidates.items()
                )
                for family, candidates in self._observed_candidate_schema.items()
            }
        )

    async def setup(
        self, *, allow_protected_degraded: bool = False
    ) -> CapabilityReport:
        """Verify public status and discover non-mutating capabilities."""
        await self.get_status()
        return await self.probe_capabilities(
            allow_protected_degraded=allow_protected_degraded
        )

    async def capture_candidate_inventory(self) -> CandidateInventoryResult:
        """Capture every safe candidate schema without changing capabilities."""
        observed_candidate_schema: dict[
            str,
            dict[tuple[str, bool, str | None], tuple[tuple[str, str], ...]],
        ] = {}
        endpoint_results: dict[
            tuple[str, bool, str | None],
            tuple[dict[str, Any] | None, SpeedportError | None],
        ] = {}
        attempted = 0
        succeeded = 0
        unsupported = 0
        failed = 0
        all_contracts = {
            (candidate.endpoint, candidate.authenticated, candidate.referer)
            for candidates in self._endpoint_candidates.values()
            for candidate in candidates
        }

        def inventory_candidate_is_safe(
            family: str, candidate: EndpointCapability
        ) -> bool:
            return candidate.inventory_safe and (
                _safe_observed_candidate_metadata(family, candidate) is not None
            )

        safe_contracts = {
            (candidate.endpoint, candidate.authenticated, candidate.referer)
            for family, candidates in self._endpoint_candidates.items()
            for candidate in candidates
            if inventory_candidate_is_safe(family, candidate)
        }
        excluded_contracts = all_contracts - safe_contracts

        async def capture_phase(*, authenticated: bool) -> None:
            nonlocal attempted, failed, succeeded, unsupported
            for family, candidates in self._endpoint_candidates.items():
                for candidate in candidates:
                    if candidate.authenticated is not authenticated:
                        continue
                    if not inventory_candidate_is_safe(family, candidate):
                        continue
                    cache_key = (
                        candidate.endpoint,
                        candidate.authenticated,
                        candidate.referer,
                    )
                    if cache_key not in endpoint_results:
                        attempted += 1
                        try:
                            fetched_data = await self.get_json(
                                candidate.endpoint,
                                authenticated=candidate.authenticated,
                                referer=candidate.referer,
                            )
                        except SpeedportUnsupportedError as exc:
                            unsupported += 1
                            endpoint_results[cache_key] = (None, exc)
                        except SpeedportError as exc:
                            if isinstance(
                                exc,
                                (
                                    SpeedportAuthenticationError,
                                    SpeedportConnectionError,
                                    SpeedportDecodeError,
                                    SpeedportSessionBusyError,
                                ),
                            ):
                                raise
                            failed += 1
                            endpoint_results[cache_key] = (None, exc)
                        else:
                            succeeded += 1
                            endpoint_results[cache_key] = (fetched_data, None)

                    endpoint_data, error = endpoint_results[cache_key]
                    if error is not None or endpoint_data is None:
                        continue
                    self._observe_candidate_data(
                        family,
                        candidate,
                        endpoint_data,
                        inventory=observed_candidate_schema,
                    )

        try:
            await self.logout()
            await capture_phase(authenticated=False)
            protected_candidates = any(
                candidate.authenticated
                and inventory_candidate_is_safe(family, candidate)
                for family, candidates in self._endpoint_candidates.items()
                for candidate in candidates
            )
            if protected_candidates:
                if not self._password:
                    raise SpeedportAuthenticationError(
                        "Protected Speedport access requires a configured password"
                    )
                await self.login()
                self._last_management_error = None
                await capture_phase(authenticated=True)
        finally:
            await self.logout()

        self._observed_candidate_schema = observed_candidate_schema
        return CandidateInventoryResult(
            attempted=attempted,
            succeeded=succeeded,
            unsupported=unsupported,
            failed=failed,
            observed=sum(
                len(candidates) for candidates in observed_candidate_schema.values()
            ),
            excluded=len(excluded_contracts),
        )

    async def close(self) -> None:
        """Release the router session and any owned HTTP client session."""
        if self._closed:
            return
        async with self._lock:
            try:
                await self._logout_unlocked()
            finally:
                self._password = None
                self._closed = True
                if self._owns_session and not self._session.closed:
                    self._session.detach()

    async def login(self) -> None:
        """Open modern SHA-256 challenge-response session."""
        self._ensure_open()
        async with self._lock:
            await self._login_unlocked()

    async def logout(self) -> None:
        """Release this client's authenticated web session."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()

    async def logout_ephemeral(self) -> None:
        """Release an action session and report unconfirmed cleanup safely."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked(require_confirmation=True)

    async def get_status(self) -> RouterStatus:
        """Fetch and normalize public encrypted Status.json."""
        data = await self.get_json("data/Status.json")
        status = normalize_status(data)
        self._last_status = status
        self._router_info = status.info
        return status

    async def get_json(
        self,
        endpoint: str,
        *,
        authenticated: bool = False,
        referer: str | None = None,
        preserve_compounds: bool = False,
    ) -> dict[str, Any]:
        """Fetch one JSON endpoint through serialized session owner."""
        self._ensure_open()
        async with self._lock:
            return await self._get_json_with_recovery_unlocked(
                endpoint,
                authenticated=authenticated,
                referer=referer,
                **({"preserve_compounds": True} if preserve_compounds else {}),
            )

    async def read_configuration(
        self, setting_id: str, target_id: str | None = None
    ) -> dict[str, Any]:
        """Read one statically reviewed form, without probing action endpoints."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_phone_numbers import NUMBER_TARGET_SPECS  # noqa: PLC0415
        from ..configuration_phone_providers import (  # noqa: PLC0415
            PROVIDER_TARGET_SPECS,
        )
        from ..configuration_provider_create import (  # noqa: PLC0415
            PROVIDER_CREATE_SETTINGS,
        )
        from ..configuration_telephony import (  # noqa: PLC0415
            normalize_dect_station_payload,
        )
        from ..system_actions import (  # noqa: PLC0415
            merge_system_action_offer,
            system_action_extra_read,
        )

        contract = resolve_settings_contract(setting_id, target_id)
        if setting_id == "system_router_password_change":
            from ..configuration_password import (  # noqa: PLC0415
                password_configuration_context,
            )

            return password_configuration_context(
                await self.get_json("data/Status.json", authenticated=False)
            )
        if setting_id in {"telephony_phonebook_contact", "telephony_phonebook_create"}:
            return await self._read_phonebook_configuration(setting_id, target_id)
        raw = await self.get_json(
            contract.read_endpoint or contract.endpoint,
            authenticated=True,
            referer=contract.read_referer or contract.referer,
            **(
                {"preserve_compounds": True}
                if contract.field_choices is not None
                or contract.payload_validator is not None
                else {}
            ),
        )
        normalized = normalize_configuration_payload(raw)
        if setting_id in {"receiver_bonding", "receiver_led_mode"}:
            from ..configuration_network_controls import (  # noqa: PLC0415
                merge_receiver_identity,
                receiver_identity_requires_read,
            )

            if receiver_identity_requires_read(normalized):
                firmware = normalize_configuration_payload(
                    await self.get_json(
                        _LTE_MODE_ENDPOINT,
                        authenticated=True,
                        referer=_LTE_FIRMWARE_REFERER,
                    )
                )
                normalized = merge_receiver_identity(normalized, firmware)
        if setting_id == "telephony_phonebook_link":
            from ..configuration_phonebook_accounts import (  # noqa: PLC0415
                phonebook_account_rows,
            )

            selected_books = [
                row
                for row in phonebook_account_rows(normalized)
                if row["id"] == target_id and row["onlbuch_sync"] == "0"
            ]
            if len(selected_books) != 1:
                raise ConfigurationError("settings_target_unavailable")
            normalized[
                "local_inventory"
            ] = await self._phonebook_configuration_inventory(
                int(selected_books[0]["onlbuch_nr"])
            )
        extra_read = system_action_extra_read(setting_id, normalized)
        if extra_read is not None:
            offer = await self.get_json(
                extra_read[0],
                authenticated=True,
                referer=extra_read[1],
                preserve_compounds=True,
            )
            normalized = merge_system_action_offer(setting_id, normalized, offer)
        if setting_id == "storage_media_reindex":
            normalized["index"] = await self.get_json(
                "data/NASFileCount.json",
                authenticated=True,
                referer="html/content/network/nas_mediareplay.html",
                preserve_compounds=True,
            )
        if setting_id == "telephony_handset_phonebook":
            normalized["phonebooks"] = await self.get_json(
                "data/PhoneOnlbuch.json",
                authenticated=True,
                referer="html/content/phone/phone_book_assign.html",
                preserve_compounds=True,
            )
        if (
            setting_id == "receiver_bonding"
            and "easy_support_deactive" not in normalized
        ):
            support = normalize_configuration_payload(
                await self.get_json(
                    "data/EasySupport.json",
                    authenticated=True,
                    referer="html/content/config/easy_support.html",
                )
            )
            normalized["network_prerequisites"] = {
                key: support[key]
                for key in ("easy_support_deactive",)
                if key in support
            }
        if (
            setting_id in PROVIDER_TARGET_SPECS
            or setting_id in NUMBER_TARGET_SPECS
            or setting_id in {item.id for item in PROVIDER_CREATE_SETTINGS}
            or setting_id == "vpn_peer_create"
        ):
            connection = normalize_configuration_payload(
                await self.get_json(
                    "data/InternetConnection.json",
                    authenticated=True,
                    referer="html/content/phone/phone_internet.html",
                )
            )
            normalized[
                "vpn_connectivity"
                if setting_id == "vpn_peer_create"
                else "internet_connection"
            ] = {
                key: connection[key]
                for key in (
                    "onlinestatus",
                    "auto_external_modem",
                    "extwan_typ",
                    "extwan_status",
                    "lte_status",
                )
                if key in connection
            }
        if setting_id == "telephony_dect_settings":
            normalized = normalize_dect_station_payload(normalized, authenticated=True)
        if setting_id == "storage_nas_share" and target_id is not None:
            rows = _strict_nas_share_rows(normalized)
            matches = [row for row in rows if row["id"] == target_id]
            if len(matches) != 1:
                raise ConfigurationError("stale_settings")
            row = normalize_configuration_payload(matches[0])
            row["sid"] = target_id
            for name in ("use_usb", "printer_connected"):
                if name in normalized:
                    row[name] = normalized[name]
            return row
        return normalized

    async def query_configuration_targets(self, setting_id: str) -> dict[str, Any]:
        """List bounded existing targets on an explicit administrator read."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_targets import (  # noqa: PLC0415
            target_settings_limit,
            target_settings_rows,
            target_settings_source,
        )

        if setting_id in {"telephony_phonebook_contact", "telephony_phonebook_create"}:
            return await self._query_phonebook_configuration_targets(setting_id)
        source = target_settings_source(setting_id)
        if setting_id != "storage_nas_share" and source is None:
            raise ConfigurationError("setting_unavailable")
        raw = await self.get_json(
            source[0] if source else _NAS_FOLDERS_ENDPOINT,
            authenticated=True,
            referer=source[1] if source else _NAS_FOLDERS_REFERER,
            **({"preserve_compounds": True} if source else {}),
        )
        normalized = normalize_configuration_payload(raw)
        if setting_id == "telephony_handset_phonebook":
            normalized["phonebooks"] = await self.get_json(
                "data/PhoneOnlbuch.json",
                authenticated=True,
                referer="html/content/phone/phone_book_assign.html",
                preserve_compounds=True,
            )
        rows = (
            target_settings_rows(setting_id, normalized)
            if source
            else _strict_nas_share_rows(normalized)
        )
        if len(rows) > target_settings_limit(setting_id):
            raise ConfigurationError("too_many_settings_targets")
        targets = []
        for row in rows:
            target_id = row["id"]
            resolve_settings_contract(setting_id, target_id)
            label = row.get(source[2] if source else "nas_folder_name")
            if source and source[2] == "phone_number":
                digits = "".join(
                    char for char in str(label) if char.isascii() and char.isdigit()
                )
                label = (
                    f"Telephone number ••••{digits[-4:]}"
                    if digits
                    else "Telephone number"
                )
            if (
                not isinstance(label, str)
                or not label
                or len(label) > _PRIVATE_QUERY_MAX_TEXT_LENGTH
            ):
                label = f"{source[3] if source else 'Share'} {target_id}"
            targets.append({"id": target_id, "label": label})
        return {"setting_id": setting_id, "targets": targets}

    async def _phonebook_configuration_inventory(self, book_id: int) -> dict[str, Any]:
        """Bind the complete contact list to a freshly identified local book."""
        from ..configuration_phonebook_accounts import (  # noqa: PLC0415
            phonebook_account_rows,
        )

        safe_book_id = _require_phonebook_id(book_id)
        inventory = await self._phonebook_transfer_inventory(safe_book_id)
        row = next(
            row
            for row in phonebook_account_rows(inventory["books"])
            if row["onlbuch_nr"] == str(safe_book_id)
        )
        if row["onlbuch_sync"] != "0":
            raise ConfigurationError("phonebook_linked")
        result: dict[str, Any] = dict(inventory["content"])
        result["book_identity"] = {
            key: row[key] for key in ("id", "onlbuch_nr", "onlbuch_sync")
        }
        return result

    async def _phonebook_transfer_inventory(self, book_id: int) -> dict[str, Any]:
        """Prove book membership and content privately under one client lock."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_phonebook_accounts import (  # noqa: PLC0415
            phonebook_account_rows,
        )
        from ..configuration_phonebook_lifecycle import (  # noqa: PLC0415
            phonebook_inventory,
        )

        self._ensure_open()
        safe_book_id = _require_phonebook_id(book_id)
        async with self._lock:
            books = normalize_configuration_payload(
                await self._get_json_unlocked(
                    "data/PhoneOnlbuch.json",
                    authenticated=True,
                    referer="html/content/phone/phone_book_basic.html",
                    preserve_compounds=True,
                )
            )
            if not any(
                row["onlbuch_nr"] == str(safe_book_id)
                for row in phonebook_account_rows(books)
            ):
                raise ConfigurationError("settings_target_unavailable")
            response = normalize_configuration_payload(
                await self._post_json_unlocked(
                    _PHONEBOOK_ENDPOINT,
                    {"obnr": safe_book_id, "search": ""},
                    authenticated=True,
                    referer=_PHONEBOOK_REFERER,
                )
            )
        if response.get("status") != "ok":
            raise ConfigurationError("settings_inventory_unavailable")
        content = _project_phonebook_entries(
            response, phonebook_id=safe_book_id, prefix=""
        )
        phonebook_inventory(content, phonebook_id=safe_book_id)
        return {"books": books, "content": content}

    async def _phonebook_configuration_contact(
        self, book_id: int, contact_id: str
    ) -> dict[str, Any]:
        """Keep current fields private; absent values are never blank defaults."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_phonebook import normalize_contact_fields  # noqa: PLC0415

        self._ensure_open()
        safe_book_id = _require_phonebook_id(book_id)
        safe_contact_id = _require_private_query_identifier(
            contact_id, description="Phonebook contact ID"
        )
        async with self._lock:
            response = normalize_configuration_payload(
                await self._post_json_unlocked(
                    _PHONEBOOK_ENTRY_ENDPOINT,
                    {"obnr": safe_book_id, "chgid": safe_contact_id},
                    authenticated=True,
                    referer=_PHONEBOOK_REFERER,
                )
            )
        return {
            "phonebook_id": safe_book_id,
            "contact_id": safe_contact_id,
            "contact": normalize_contact_fields(response),
        }

    async def _read_phonebook_configuration(
        self, setting_id: str, target_id: str | None
    ) -> dict[str, Any]:
        """Resolve an exact local book or existing contact before detail reads."""
        from ..configuration_phonebook import parse_phonebook_target  # noqa: PLC0415
        from ..configuration_phonebook_lifecycle import (  # noqa: PLC0415
            phonebook_create_book_id,
            phonebook_inventory,
        )

        if target_id is None:
            raise ConfigurationError("settings_target_required")
        if setting_id == "telephony_phonebook_create":
            return await self._phonebook_configuration_inventory(
                phonebook_create_book_id(target_id)
            )
        book_id, contact_id = parse_phonebook_target(target_id)
        inventory = await self._phonebook_configuration_inventory(book_id)
        if contact_id not in phonebook_inventory(inventory, phonebook_id=book_id):
            raise ConfigurationError("settings_target_unavailable")
        contact = await self._phonebook_configuration_contact(book_id, contact_id)
        contact["book_identity"] = inventory["book_identity"]
        return contact

    async def _query_phonebook_configuration_targets(
        self, setting_id: str
    ) -> dict[str, Any]:
        """List proven local books or contacts, never invent an absent row."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_phonebook_accounts import (  # noqa: PLC0415
            phonebook_account_rows,
        )

        books = phonebook_account_rows(
            normalize_configuration_payload(
                await self.get_json(
                    "data/PhoneOnlbuch.json",
                    authenticated=True,
                    referer="html/content/phone/phone_book_basic.html",
                    preserve_compounds=True,
                )
            )
        )
        targets = []
        for book in books:
            if book["onlbuch_sync"] != "0":
                continue
            book_id = _require_phonebook_id(int(book["onlbuch_nr"]))
            raw = await self._phonebook_configuration_inventory(book_id)
            if setting_id == "telephony_phonebook_create":
                if raw["free_entries"] > 0:
                    targets.append({"id": str(book_id), "label": book["onlbuch_name"]})
                continue
            for row in raw["entries"]:
                label = " ".join(
                    row.get(name, "") for name in ("first_name", "last_name")
                ).strip()
                targets.append(
                    {
                        "id": f"{book_id}:{row['contact_id']}",
                        "label": f"{book['onlbuch_name']}: {label or 'Contact'}",
                    }
                )
            if len(targets) > _PHONEBOOK_SETTINGS_MAX_TARGETS:
                raise ConfigurationError("too_many_settings_targets")
        return {"setting_id": setting_id, "targets": targets}

    async def read_created_phonebook_configuration(
        self, target_id: str, before: Mapping[str, Any], response: Any
    ) -> dict[str, Any]:
        """Verify a returned new ID through independent list and detail read queries."""
        from ..configuration_phonebook_lifecycle import (  # noqa: PLC0415
            phonebook_create_book_id,
            phonebook_created_id,
            phonebook_inventory,
        )

        book_id = phonebook_create_book_id(target_id)
        if not isinstance(response, Mapping):
            raise ConfigurationError("action_outcome_unknown")
        assigned_id = phonebook_created_id(
            response,
            existing_ids=set(phonebook_inventory(before, phonebook_id=book_id)),
        )
        current = await self._phonebook_configuration_inventory(book_id)
        if assigned_id not in phonebook_inventory(current, phonebook_id=book_id):
            raise ConfigurationError("action_verification_failed")
        current["assigned_id"] = assigned_id
        current["created_contact"] = await self._phonebook_configuration_contact(
            book_id, assigned_id
        )
        return current

    async def query_ip_information(self) -> dict[str, Any]:
        """Read native IP information only for a private administrator view."""
        from ..ip_information import (  # noqa: PLC0415
            IP_INFORMATION_ENDPOINT,
            IP_INFORMATION_REFERER,
            read_ip_information,
        )

        return read_ip_information(
            await self.get_json(
                IP_INFORMATION_ENDPOINT,
                authenticated=True,
                referer=IP_INFORMATION_REFERER,
            )
        )

    async def query_call_history(
        self, *, category: str, export: bool = False
    ) -> dict[str, Any]:
        """Read one closed private category or produce its local CSV, without writes."""
        from ..configuration import normalize_configuration_payload  # noqa: PLC0415
        from ..configuration_call_history import (  # noqa: PLC0415
            call_history_private_export,
            call_history_private_read,
            call_history_read_source,
        )

        endpoint, referer = call_history_read_source(category)
        if type(export) is not bool:
            raise ConfigurationError("invalid_call_history_export")
        raw = normalize_configuration_payload(
            await self.get_json(endpoint, authenticated=True, referer=referer)
        )
        return (
            call_history_private_export(raw, category)
            if export
            else call_history_private_read(raw, category)
        )

    async def read_created_ip_phone_configuration(
        self, before: Mapping[str, Any], response: Any
    ) -> dict[str, Any]:
        """Bind independent row readback to the native allocation response ID."""
        from ..configuration_ip_phone_create import ip_phone_created_id  # noqa: PLC0415

        if not isinstance(response, Mapping):
            raise ConfigurationError("action_outcome_unknown")
        assigned_id = ip_phone_created_id(before, response)
        current = await self.read_configuration("telephony_ip_phone_create")
        current["_created_ip_phone_id"] = assigned_id
        return current

    async def save_configuration(
        self,
        setting_id: str,
        current: Mapping[str, Any],
        changes: Mapping[str, Any],
        target_id: str | None = None,
    ) -> dict[str, Any]:
        """Build an exact reviewed form and send it once; never retry a write."""
        if setting_id == "system_router_password_change":
            raise ConfigurationError("password_change_isolated_flow_required")
        contract = resolve_settings_contract(setting_id, target_id)
        payload = contract.build(current, changes)
        response = await self._post_ephemeral_action(
            contract.endpoint,
            payload,
            referer=contract.referer,
            require_status_ok=contract.acknowledgement == "status_ok",
        )
        if contract.acknowledgement == "result_ok":
            _require_exact_result_ok(response)
        if contract.response_validator is not None:
            contract.response_validator(response)
        return response

    async def _post_reviewed_command(
        self,
        endpoint: str,
        data: Mapping[str, str | int | bool],
        *,
        authenticated: bool = True,
        referer: str | None = None,
    ) -> dict[str, Any]:
        """Post one exact reviewed command through the serialized owner."""
        self._ensure_open()
        async with self._lock:
            result = await self._post_json_unlocked(
                endpoint,
                data,
                authenticated=authenticated,
                referer=referer,
            )
            _require_command_acknowledgement(result)
            return result

    async def _post_ephemeral_action(
        self,
        endpoint: str,
        data: Mapping[str, str | int | bool],
        *,
        referer: str,
        require_status_ok: bool = False,
    ) -> dict[str, Any]:
        """Send one exact action once and apply its reviewed ACK policy."""
        self._ensure_open()
        async with self._lock:
            await self._ensure_authenticated_unlocked()
            fields = dict(data)
            if "httoken" not in fields:
                token = await self._get_http_token_unlocked(referer)
                if token:
                    fields["httoken"] = token
            try:
                result = await self._post_json_unlocked(
                    endpoint,
                    fields,
                    authenticated=True,
                    referer=referer,
                    ensure_auth=False,
                    resolve_http_token=False,
                )
            except SpeedportError as err:
                raise SpeedportMutationOutcomeUnknownError(
                    "Router mutation result is indeterminate"
                ) from err
            if require_status_ok:
                _require_exact_status_ok(result)
            else:
                _reject_explicit_action_failure(result)
            return result

    async def query_ip_pbx_client(self, *, client_id: str) -> dict[str, Any]:
        """Refresh and return one IP-PBX registration row without changing it."""
        safe_client_id = _require_private_query_identifier(
            client_id,
            description="IP-PBX client ID",
        )
        self._ensure_open()
        async with self._lock:
            response = await self._post_json_unlocked(
                _IP_PBX_CLIENTS_ENDPOINT,
                {"refresh": safe_client_id},
                authenticated=True,
                referer=_IP_PBX_CLIENTS_REFERER,
            )
        return _project_ip_pbx_client(response, client_id=safe_client_id)

    async def query_phonebook_entries(
        self,
        *,
        phonebook_id: int,
        prefix: str,
    ) -> dict[str, Any]:
        """Return one bounded phonebook prefix search as ephemeral private data."""
        safe_phonebook_id = _require_phonebook_id(phonebook_id)
        safe_prefix = _require_phonebook_search_prefix(prefix)
        self._ensure_open()
        async with self._lock:
            response = await self._post_json_unlocked(
                _PHONEBOOK_ENDPOINT,
                {"obnr": safe_phonebook_id, "search": safe_prefix},
                authenticated=True,
                referer=_PHONEBOOK_REFERER,
            )
        return _project_phonebook_entries(
            response,
            phonebook_id=safe_phonebook_id,
            prefix=safe_prefix,
        )

    async def query_phonebook_contact(
        self,
        *,
        phonebook_id: int,
        contact_id: str,
    ) -> dict[str, Any]:
        """Return one bounded phonebook contact as ephemeral private data."""
        safe_phonebook_id = _require_phonebook_id(phonebook_id)
        safe_contact_id = _require_private_query_identifier(
            contact_id,
            description="Phonebook contact ID",
        )
        self._ensure_open()
        async with self._lock:
            response = await self._post_json_unlocked(
                _PHONEBOOK_ENTRY_ENDPOINT,
                {"obnr": safe_phonebook_id, "chgid": safe_contact_id},
                authenticated=True,
                referer=_PHONEBOOK_REFERER,
            )
        return _project_phonebook_contact(
            response,
            phonebook_id=safe_phonebook_id,
            contact_id=safe_contact_id,
        )

    async def query_dect_handset_targets(self) -> dict[str, Any]:
        """Return bounded handset targets only through the ephemeral admin API."""
        self._ensure_open()
        async with self._lock:
            station = await self._get_json_with_recovery_unlocked(
                _DECT_STATION_ENDPOINT,
                authenticated=True,
                referer=_DECT_MOBILES_REFERER,
            )
            status = await self._get_json_with_recovery_unlocked(
                _DECT_STATUS_ENDPOINT,
                authenticated=True,
                referer=_DECT_MOBILES_REFERER,
            )
        return _project_dect_handset_targets(station, status)

    async def query_voip_line_targets(self) -> dict[str, Any]:
        """Return bounded VoIP line targets only through the ephemeral admin API."""
        data = await self.get_json(
            _VOIP_LINES_ENDPOINT,
            authenticated=True,
            referer=_VOIP_LINES_REFERER,
        )
        return _project_voip_line_targets(data)

    async def query_dect_handset_disconnect_targets(self) -> dict[str, Any]:
        """Return exact registered-handset deletion targets ephemerally."""
        data = await self.get_json(
            _DECT_STATION_ENDPOINT,
            authenticated=True,
            referer=_DECT_MOBILES_REFERER,
        )
        return _project_dect_handset_disconnect_targets(data)

    async def query_dect_repeater_disconnect_targets(self) -> dict[str, Any]:
        """Return exact registered-repeater deletion targets ephemerally."""
        data = await self.get_json(
            _DECT_REPEATER_ENDPOINT,
            authenticated=True,
            referer=_DECT_REPEATER_REFERER,
        )
        return _project_dect_repeater_disconnect_targets(data)

    async def query_voip_provider_delete_targets(self) -> dict[str, Any]:
        """Return exact VoIP provider deletion targets ephemerally."""
        data = await self.get_json(
            _VOIP_PROVIDERS_ENDPOINT,
            authenticated=True,
            referer=_VOIP_LINES_REFERER,
        )
        return _project_voip_provider_delete_targets(data)

    async def query_voip_line_delete_targets(self) -> dict[str, Any]:
        """Return exact VoIP number deletion targets ephemerally."""
        data = await self.get_json(
            _VOIP_LINES_ENDPOINT,
            authenticated=True,
            referer=_VOIP_LINES_REFERER,
        )
        return _project_voip_line_delete_targets(data)

    async def query_ip_pbx_client_delete_targets(self) -> dict[str, Any]:
        """Return exact IP-PBX client deletion targets ephemerally."""
        data = await self.get_json(
            _IP_PBX_CLIENTS_ENDPOINT,
            authenticated=True,
            referer=_IP_PBX_CLIENTS_REFERER,
        )
        return _project_ip_pbx_client_delete_targets(data)

    async def query_phonebook_entry_delete_targets(
        self,
        *,
        phonebook_id: int,
    ) -> dict[str, Any]:
        """Return one complete phonebook's exact deletion targets ephemerally."""
        safe_phonebook_id = _require_phonebook_id(phonebook_id)
        self._ensure_open()
        async with self._lock:
            data = await self._post_json_unlocked(
                _PHONEBOOK_ENDPOINT,
                {"obnr": safe_phonebook_id, "search": ""},
                authenticated=True,
                referer=_PHONEBOOK_REFERER,
            )
        return _project_phonebook_entry_delete_targets(
            data,
            phonebook_id=safe_phonebook_id,
        )

    async def query_nas_share_delete_targets(self) -> dict[str, Any]:
        """Return exact NAS-share deletion targets ephemerally."""
        data = await self.get_json(
            _NAS_FOLDERS_ENDPOINT,
            authenticated=True,
            referer=_NAS_FOLDERS_REFERER,
        )
        return _project_nas_share_delete_targets(data)

    async def get_dect_scan_active(self) -> bool:
        """Read the exact DECT enrollment lifecycle flag."""
        data = await self.get_json(
            _DECT_STATUS_ENDPOINT,
            authenticated=True,
            referer=_DECT_MOBILES_REFERER,
        )
        return _require_dect_scan_active(data)

    async def get_dect_repeater_scan_active(self) -> bool:
        """Read repeater enrollment lifecycle without reading the DECT PIN."""
        return await self.get_dect_scan_active()

    async def get_dect_handset_paging(
        self,
        *,
        handset_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read handset membership and its exact paging state."""
        safe_id = _require_admin_action_identifier(
            handset_id,
            description="DECT handset ID",
        )
        safe_fingerprint = _require_admin_target_fingerprint(target_fingerprint)
        self._ensure_open()
        async with self._lock:
            station = await self._get_json_with_recovery_unlocked(
                _DECT_STATION_ENDPOINT,
                authenticated=True,
                referer=_DECT_MOBILES_REFERER,
            )
            handset = _require_dect_handset(station, handset_id=safe_id)
            if (
                _dect_handset_fingerprint(handset, handset_id=safe_id)
                != safe_fingerprint
            ):
                raise SpeedportUnsupportedError("DECT handset target identity changed")
            status = await self._get_json_with_recovery_unlocked(
                _DECT_STATUS_ENDPOINT,
                authenticated=True,
                referer=_DECT_MOBILES_REFERER,
            )
        return _require_dect_paging_state(status, handset_id=safe_id)

    async def get_voip_line_active(
        self,
        *,
        line_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read one exact VoIP line state without returning its number."""
        safe_id = _require_admin_action_identifier(
            line_id,
            description="VoIP line ID",
        )
        safe_fingerprint = _require_admin_target_fingerprint(target_fingerprint)
        data = await self.get_json(
            _VOIP_LINES_ENDPOINT,
            authenticated=True,
            referer=_VOIP_LINES_REFERER,
        )
        line = _require_voip_line(data, line_id=safe_id)
        if _voip_line_fingerprint(line, line_id=safe_id) != safe_fingerprint:
            raise SpeedportUnsupportedError("VoIP line target identity changed")
        return _require_voip_line_active(line)

    async def get_dect_handset_present(
        self,
        *,
        handset_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read exact handset membership for destructive verification."""
        return await self._get_target_membership(
            endpoint=_DECT_STATION_ENDPOINT,
            referer=_DECT_MOBILES_REFERER,
            target_id=handset_id,
            target_fingerprint=target_fingerprint,
            rows=_strict_dect_handset_rows,
            fingerprint=lambda row, row_id: _dect_handset_fingerprint(
                row,
                handset_id=row_id,
            ),
        )

    async def get_dect_repeater_present(
        self,
        *,
        repeater_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read exact repeater membership for destructive verification."""
        return await self._get_target_membership(
            endpoint=_DECT_REPEATER_ENDPOINT,
            referer=_DECT_REPEATER_REFERER,
            target_id=repeater_id,
            target_fingerprint=target_fingerprint,
            rows=_strict_dect_repeater_rows,
            fingerprint=_dect_repeater_fingerprint,
        )

    async def get_voip_provider_present(
        self,
        *,
        provider_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read exact VoIP provider membership."""
        return await self._get_target_membership(
            endpoint=_VOIP_PROVIDERS_ENDPOINT,
            referer=_VOIP_LINES_REFERER,
            target_id=provider_id,
            target_fingerprint=target_fingerprint,
            rows=_strict_voip_provider_rows,
            fingerprint=_voip_provider_fingerprint,
        )

    async def get_voip_line_present(
        self,
        *,
        line_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read exact VoIP number membership."""
        return await self._get_target_membership(
            endpoint=_VOIP_LINES_ENDPOINT,
            referer=_VOIP_LINES_REFERER,
            target_id=line_id,
            target_fingerprint=target_fingerprint,
            rows=_strict_voip_line_rows,
            fingerprint=lambda row, row_id: _voip_line_fingerprint(
                row,
                line_id=row_id,
            ),
        )

    async def get_ip_pbx_client_present(
        self,
        *,
        client_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Fresh-read exact IP-PBX client membership."""
        return await self._get_target_membership(
            endpoint=_IP_PBX_CLIENTS_ENDPOINT,
            referer=_IP_PBX_CLIENTS_REFERER,
            target_id=client_id,
            target_fingerprint=target_fingerprint,
            rows=_strict_ip_pbx_client_rows,
            fingerprint=_ip_pbx_client_fingerprint,
        )

    async def get_phonebook_entry_present(
        self,
        *,
        contact_id: str,
        target_fingerprint: str,
        phonebook_id: int,
    ) -> bool:
        """Fresh-read exact contact membership from a complete phonebook list."""
        safe_id = _require_admin_action_identifier(
            contact_id,
            description="Phonebook contact ID",
        )
        safe_fingerprint = _require_admin_target_fingerprint(target_fingerprint)
        safe_phonebook_id = _require_phonebook_id(phonebook_id)
        self._ensure_open()
        async with self._lock:
            data = await self._post_json_unlocked(
                _PHONEBOOK_ENDPOINT,
                {"obnr": safe_phonebook_id, "search": ""},
                authenticated=True,
                referer=_PHONEBOOK_REFERER,
            )
        rows = _strict_phonebook_rows(data)
        _require_complete_phonebook_result(data, rows)
        return _target_membership(
            rows,
            target_id=safe_id,
            target_fingerprint=safe_fingerprint,
            fingerprint=lambda row, row_id: _phonebook_entry_fingerprint(
                row,
                contact_id=row_id,
                phonebook_id=safe_phonebook_id,
            ),
        )

    async def get_nas_share_present(
        self,
        *,
        share_id: str,
        target_fingerprint: str,
    ) -> bool:
        """Read NAS membership without using another flat row as absence proof."""
        safe_id = _require_admin_action_identifier(
            share_id,
            description="NAS share ID",
        )
        safe_fingerprint = _require_admin_target_fingerprint(target_fingerprint)
        data = await self.get_json(
            _NAS_FOLDERS_ENDPOINT,
            authenticated=True,
            referer=_NAS_FOLDERS_REFERER,
        )
        rows = _strict_nas_share_rows(data)
        has_complete_collection = any(
            _mapping_value(data, collection) is not None
            for collection in ("addnasfolder", "nas_folders", "nasfolder")
        )
        if not has_complete_collection and rows and rows[0]["id"] != safe_id:
            raise SpeedportUnsupportedError(
                "Flat NAS share response cannot prove target absence"
            )
        return _target_membership(
            rows,
            target_id=safe_id,
            target_fingerprint=safe_fingerprint,
            fingerprint=_nas_share_fingerprint,
        )

    async def _get_target_membership(
        self,
        *,
        endpoint: str,
        referer: str,
        target_id: str,
        target_fingerprint: str,
        rows: Callable[[Mapping[str, Any]], tuple[dict[str, Any], ...]],
        fingerprint: Callable[[Mapping[str, Any], str], str],
    ) -> bool:
        """Fresh-read one complete collection and prove exact membership."""
        safe_id = _require_admin_action_identifier(
            target_id,
            description="Administrator action target ID",
        )
        safe_fingerprint = _require_admin_target_fingerprint(target_fingerprint)
        data = await self.get_json(
            endpoint,
            authenticated=True,
            referer=referer,
        )
        return _target_membership(
            rows(data),
            target_id=safe_id,
            target_fingerprint=safe_fingerprint,
            fingerprint=fingerprint,
        )

    async def start_dect_handset_enrollment(self) -> dict[str, Any]:
        """Start one DECT handset enrollment scan through its exact contract."""
        return await self._post_ephemeral_action(
            _DECT_ACTION_ENDPOINT,
            {"scan_dect": "scan dect phones"},
            referer=_DECT_MOBILES_REFERER,
        )

    async def start_dect_repeater_enrollment(self) -> dict[str, Any]:
        """Start one DECT repeater enrollment scan through its exact contract."""
        return await self._post_ephemeral_action(
            _DECT_REPEATER_ENDPOINT,
            {"scan_repeater": "scan dect repeater"},
            referer=_DECT_REPEATER_REFERER,
        )

    async def toggle_dect_handset_paging(
        self,
        *,
        handset_id: str,
    ) -> dict[str, Any]:
        """Toggle paging for one freshly proven handset row."""
        safe_id = _require_admin_action_identifier(
            handset_id,
            description="DECT handset ID",
        )
        return await self._post_ephemeral_action(
            _DECT_ACTION_ENDPOINT,
            {"ring": "start paging", "id": safe_id},
            referer=_DECT_MOBILES_REFERER,
        )

    async def set_voip_line_active(
        self,
        *,
        line_id: str,
        active: bool,
    ) -> dict[str, Any]:
        """Set one freshly proven VoIP line to the requested active state."""
        safe_id = _require_admin_action_identifier(
            line_id,
            description="VoIP line ID",
        )
        _require_boolean(active, description="VoIP line state")
        return await self._post_ephemeral_action(
            _VOIP_LINES_ENDPOINT,
            {
                "id": safe_id,
                "no_delete": "keep",
                "number_status": "ok" if active else "inactive",
            },
            referer=_VOIP_LINES_REFERER,
        )

    async def disconnect_dect_handset(self, *, handset_id: str) -> dict[str, Any]:
        """Disconnect one freshly proven DECT handset."""
        safe_id = _require_admin_action_identifier(
            handset_id,
            description="DECT handset ID",
        )
        return await self._post_ephemeral_action(
            _DECT_ACTION_ENDPOINT,
            {"disconnect": "disconnect", "id": safe_id},
            referer=_DECT_MOBILES_REFERER,
        )

    async def disconnect_dect_repeater(self, *, repeater_id: str) -> dict[str, Any]:
        """Disconnect one freshly proven DECT repeater."""
        safe_id = _require_admin_action_identifier(
            repeater_id,
            description="DECT repeater ID",
        )
        return await self._post_ephemeral_action(
            _DECT_REPEATER_ENDPOINT,
            {"disconnect": "disconnect", "id": safe_id},
            referer=_DECT_REPEATER_REFERER,
        )

    async def delete_voip_provider(self, *, provider_id: str) -> dict[str, Any]:
        """Delete one freshly proven VoIP provider."""
        safe_id = _require_admin_action_identifier(
            provider_id,
            description="VoIP provider ID",
        )
        return await self._post_ephemeral_action(
            _VOIP_PROVIDERS_ENDPOINT,
            {"id": safe_id, "deleteEntry": "delete"},
            referer=_VOIP_LINES_REFERER,
        )

    async def delete_voip_line(self, *, line_id: str) -> dict[str, Any]:
        """Delete one freshly proven VoIP number with an exact positive ACK."""
        safe_id = _require_admin_action_identifier(
            line_id,
            description="VoIP line ID",
        )
        return await self._post_ephemeral_action(
            _VOIP_LINES_ENDPOINT,
            {"id": safe_id, "deleteEntry": "delete"},
            referer=_VOIP_LINES_REFERER,
            require_status_ok=True,
        )

    async def delete_ip_pbx_client(self, *, client_id: str) -> dict[str, Any]:
        """Delete one freshly proven IP-PBX client."""
        safe_id = _require_admin_action_identifier(
            client_id,
            description="IP-PBX client ID",
        )
        return await self._post_ephemeral_action(
            _IP_PBX_CLIENTS_ENDPOINT,
            {"delete": "delete", "id": safe_id},
            referer=_IP_PBX_CLIENTS_REFERER,
        )

    async def delete_phonebook_entry(
        self,
        *,
        contact_id: str,
        phonebook_id: int,
    ) -> dict[str, Any]:
        """Delete one freshly proven contact from one exact phonebook."""
        safe_id = _require_admin_action_identifier(
            contact_id,
            description="Phonebook contact ID",
        )
        safe_phonebook_id = _require_phonebook_id(phonebook_id)
        return await self._post_ephemeral_action(
            _PHONEBOOK_ENDPOINT,
            {
                "id": safe_id,
                "obnr": safe_phonebook_id,
                "deleteEntry": "delete",
            },
            referer=_PHONEBOOK_REFERER,
        )

    async def delete_nas_share(self, *, share_id: str) -> dict[str, Any]:
        """Delete one freshly proven NAS share."""
        safe_id = _require_admin_action_identifier(
            share_id,
            description="NAS share ID",
        )
        return await self._post_ephemeral_action(
            _NAS_FOLDERS_ENDPOINT,
            {"sid": safe_id, "deleteEntry": "delete"},
            referer=_NAS_FOLDERS_REFERER,
        )

    async def post_maintenance_action(
        self, action: str, parameters: Mapping[str, object]
    ) -> dict[str, Any]:
        """Send one fixed maintenance payload once, after the hub's preflight."""
        contract = get_admin_action_contract(action)
        if contract is None or contract.execution_policy != "maintenance":
            raise MaintenanceError
        payload = maintenance_payload(action, parameters)
        return await self._post_ephemeral_action(
            contract.endpoint,
            payload,
            referer=contract.referer,
        )

    async def reconnect(self) -> dict[str, Any]:
        """Request Internet reconnection through confirmed endpoint."""
        return await self._post_reviewed_command(
            "data/Connect.json",
            {"req_connect": "reconnect"},
            referer="html/content/internet/con_ipdata.html",
        )

    async def execute_internet_reconnect(self) -> dict[str, Any]:
        """Compatibility name for Internet reconnection command."""
        return await self.reconnect()

    async def reboot(self) -> dict[str, Any]:
        """Request router reboot through confirmed endpoint."""
        return await self._post_reviewed_command(
            "data/Reboot.json",
            {"reboot_device": "true"},
            referer="html/content/config/restart.html",
        )

    async def execute_router_reboot(self) -> dict[str, Any]:
        """Compatibility name for router reboot command."""
        return await self.reboot()

    async def wps(self) -> dict[str, Any]:
        """Start WPS through confirmed WLANAccess endpoint."""
        return await self._post_reviewed_command(
            _WPS_ENDPOINT,
            {"wlan_add": "on", "wps_key": "connect"},
            referer=_WPS_REFERER,
        )

    async def execute_wps_start(self) -> dict[str, Any]:
        """Compatibility name for WPS command."""
        return await self.wps()

    async def execute_wifi_set_enabled(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed global Wi-Fi state field."""
        _require_boolean(enabled, description="Global Wi-Fi state")
        return await self._set_guarded_scalar(
            endpoint="data/Modules.json",
            referer="html/content/overview/index.html",
            field="use_wlan",
            desired_value="1" if enabled else "0",
            allowed_values=_BINARY_STATE_VALUES,
        )

    async def set_guest_wifi(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed guest Wi-Fi state field."""
        _require_boolean(enabled, description="Guest Wi-Fi state")
        return await self._set_guarded_scalar(
            endpoint="data/Modules.json",
            referer="html/content/overview/index.html",
            field="wlan_guest_active",
            desired_value="1" if enabled else "0",
            allowed_values=_BINARY_STATE_VALUES,
        )

    async def execute_guest_wifi_set_enabled(self, *, enabled: bool) -> dict[str, Any]:
        """Compatibility name for guest Wi-Fi command."""
        return await self.set_guest_wifi(enabled=enabled)

    async def set_office_wifi(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed office Wi-Fi state field."""
        _require_boolean(enabled, description="Office Wi-Fi state")
        return await self._set_guarded_scalar(
            endpoint="data/Modules.json",
            referer="html/content/overview/index.html",
            field="wlan_office_active",
            desired_value="1" if enabled else "0",
            allowed_values=_BINARY_STATE_VALUES,
        )

    async def set_internet_privacy_level(self, level: int) -> dict[str, Any]:
        """Set the firmware-proven Internet privacy level."""
        if not isinstance(level, int) or isinstance(level, bool):
            raise SpeedportProtocolError("Internet privacy level must be an integer")
        return await self._set_guarded_scalar(
            endpoint=_INTERNET_PRIVACY_ENDPOINT,
            referer=_INTERNET_PRIVACY_REFERER,
            field="lan_privacy_policy",
            desired_value=str(level),
            allowed_values=_THREE_STATE_VALUES,
        )

    async def set_receiver_led_mode(self, mode: int) -> dict[str, Any]:
        """Set the firmware-proven external receiver LED mode."""
        if not isinstance(mode, int) or isinstance(mode, bool):
            raise SpeedportProtocolError("Receiver LED mode must be an integer")
        return await self._set_guarded_scalar(
            endpoint=_LTE_MODE_ENDPOINT,
            referer=_LTE_MODE_REFERER,
            field="ex5g_led_mode",
            desired_value=str(mode),
            allowed_values=_THREE_STATE_VALUES,
            current_value_reader=_require_receiver_led_mode_value,
        )

    async def set_hybrid_bonding(self, *, enabled: bool) -> dict[str, Any]:
        """Set the firmware-proven hybrid bonding state."""
        _require_boolean(enabled, description="Hybrid bonding state")
        return await self._set_guarded_scalar(
            endpoint=_LTE_MODE_ENDPOINT,
            referer=_LTE_MODE_REFERER,
            field="use_bonding",
            desired_value="1" if enabled else "0",
            allowed_values=_BINARY_STATE_VALUES,
        )

    async def _set_guarded_scalar(
        self,
        *,
        endpoint: str,
        referer: str,
        field: str,
        desired_value: str,
        allowed_values: frozenset[str],
        current_value_reader: Callable[[Mapping[str, Any]], str] | None = None,
    ) -> dict[str, Any]:
        """Fresh-read and submit one exact allowlisted scalar field."""
        if desired_value not in allowed_values:
            raise SpeedportProtocolError("Requested scalar state is not allowlisted")
        self._ensure_open()
        async with self._lock:
            readback = await self._get_json_with_recovery_unlocked(
                endpoint,
                authenticated=True,
                referer=referer,
            )
            current_value = (
                current_value_reader(readback)
                if current_value_reader is not None
                else _require_guarded_scalar_value(
                    readback,
                    field=field,
                    allowed_values=allowed_values,
                )
            )
            if current_value == desired_value:
                return {"status": "unchanged"}
            result = await self._post_json_unlocked(
                endpoint,
                {field: desired_value},
                authenticated=True,
                referer=referer,
            )
            _require_command_acknowledgement(result)
            return result

    async def _get_json_with_recovery_unlocked(
        self,
        endpoint: str,
        *,
        authenticated: bool,
        referer: str | None,
        preserve_compounds: bool = False,
    ) -> dict[str, Any]:
        """Retry one protected GET after bounded, ownership-safe recovery."""
        try:
            return await self._get_json_unlocked(
                endpoint,
                authenticated=authenticated,
                referer=referer,
                **({"preserve_compounds": True} if preserve_compounds else {}),
            )
        except (SpeedportAuthenticationError, SpeedportDecodeError) as err:
            if (
                not authenticated
                or self._password is None
                or isinstance(
                    err,
                    (
                        SpeedportInvalidCredentialsError,
                        SpeedportLoginLockedError,
                    ),
                )
            ):
                raise

            if self._session_cleanup_key is not None:
                await self._logout_unlocked()
            else:
                # Status/challenge failures happen before the router supplies a
                # proof-bound key. Forget only local preflight state: a logout
                # without that key could terminate somebody else's session.
                self._clear_session_state()
                self._encrypted_mode = None

            # Deliberately issue one direct retry instead of recursing through
            # this helper. This bounds a pre-proof failure to one additional
            # challenge and never wraps or replays a state-changing request.
            return await self._get_json_unlocked(
                endpoint,
                authenticated=True,
                referer=referer,
                **({"preserve_compounds": True} if preserve_compounds else {}),
            )

    async def rename_client(
        self,
        *,
        source_kind: str,
        row_id: str,
        stable_mac: str | None,
        name: str,
    ) -> dict[str, Any]:
        """Rename one proven managed-device row without altering other fields."""
        if not valid_device_name(name):
            raise SpeedportProtocolError(
                "Device name must contain 1-28 letters, numbers, or hyphens"
            )
        return await self._update_managed_device_row(
            source_kind=source_kind,
            row_id=row_id,
            stable_mac=stable_mac,
            update={"mdevice_name": name},
        )

    async def set_client_fixed_dhcp(
        self,
        *,
        source_kind: str,
        row_id: str,
        stable_mac: str | None,
        enabled: bool,
    ) -> dict[str, Any]:
        """Toggle only the firmware-proven fixed-DHCP flag on one fresh row."""
        _require_boolean(enabled, description="Fixed DHCP state")
        return await self._update_managed_device_row(
            source_kind=source_kind,
            row_id=row_id,
            stable_mac=stable_mac,
            update={"mdevice_fix_dhcp": "1" if enabled else "0"},
            require_fixed_dhcp=True,
        )

    async def _update_managed_device_row(
        self,
        *,
        source_kind: str,
        row_id: str,
        stable_mac: str | None,
        update: Mapping[str, str],
        require_fixed_dhcp: bool = False,
    ) -> dict[str, Any]:
        """Fresh-read, preserve and submit exactly one allowlisted firmware row."""
        self._ensure_open()
        normalized_kind = source_kind.strip().casefold()
        form = _MANAGED_DEVICE_FORMS.get(normalized_kind)
        if form is None:
            raise SpeedportUnsupportedError(
                "Managed-device row kind is not safely writable"
            )
        if not update or not set(update) <= {"mdevice_name", "mdevice_fix_dhcp"}:
            raise SpeedportUnsupportedError("Managed-device update is not allowlisted")

        async with self._lock:
            readback = await self._get_json_unlocked(
                _DEVICE_LIST_ENDPOINT,
                authenticated=True,
                referer=_DEVICE_LIST_REFERER,
            )
            row = _select_managed_device_row(
                readback,
                normalized_kind,
                form,
                row_id=row_id,
                stable_mac=stable_mac,
            )
            if require_fixed_dhcp:
                _validate_fixed_dhcp_row(row)
            payload = {field: row[field] for field in form.fields}
            payload.update(update)
            result = await self._post_json_unlocked(
                form.endpoint,
                payload,
                authenticated=True,
                referer=_DEVICE_LIST_REFERER,
            )
            _require_command_acknowledgement(result)
            return result

    async def set_port_forward_rule(
        self,
        *,
        rule_id: str,
        enabled: bool,
        expected_name: str | None,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        """Fresh-read and toggle exactly one existing PortuwMain rule."""
        _require_boolean(enabled, description="Port-forward rule state")
        self._ensure_open()
        async with self._lock:
            readback = await self._get_json_unlocked(
                _PORT_FORWARD_ENDPOINT,
                authenticated=True,
                referer=_PORT_FORWARD_REFERER,
            )
            current = _select_port_forward_rule(
                readback,
                rule_id=rule_id,
                expected_name=expected_name,
                expected_fingerprint=expected_fingerprint,
            )
            if current is enabled:
                return {"status": "unchanged"}
            result = await self._post_json_unlocked(
                _PORT_FORWARD_ENDPOINT,
                {"id": rule_id, "portuw_active": "1" if enabled else "0"},
                authenticated=True,
                referer=_PORT_FORWARD_REFERER,
            )
            _require_command_acknowledgement(result)
            return result

    async def execute_port_mapping_set_enabled(
        self,
        *,
        rule_id: str,
        enabled: bool,
        expected_name: str | None,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        """Compatibility name for existing port-rule toggle."""
        return await self.set_port_forward_rule(
            rule_id=rule_id,
            enabled=enabled,
            expected_name=expected_name,
            expected_fingerprint=expected_fingerprint,
        )

    async def get_feature_data(self, family: str) -> dict[str, Any]:
        """Fetch previously confirmed semantic feature endpoint."""
        capability = self._selected_endpoints.get(family)
        if capability is None:
            msg = f"Router capability not confirmed: {family}"
            raise SpeedportUnsupportedError(msg)
        data = await self.get_json(
            capability.endpoint,
            authenticated=capability.authenticated,
            referer=capability.referer,
        )
        self.observe_feature_data(family, data)
        return data

    def observe_feature_data(self, family: str, data: Mapping[str, Any]) -> None:
        """Record bounded response structure without values or additional I/O."""
        if family not in self._selected_endpoints:
            return
        safe_family = _safe_observed_schema_name(family)
        if safe_family != family:
            return
        if (
            safe_family not in self._observed_feature_schema
            and len(self._observed_feature_schema) >= _OBSERVED_SCHEMA_MAX_FAMILIES
        ):
            return

        observed = _describe_observed_schema(data)
        current = self._observed_feature_schema.get(safe_family, ())
        merged = list(current)
        known = set(current)
        for descriptor in observed:
            if descriptor in known:
                continue
            if len(merged) >= _OBSERVED_SCHEMA_MAX_FIELDS:
                break
            merged.append(descriptor)
            known.add(descriptor)
        self._observed_feature_schema[safe_family] = tuple(merged)

    def _observe_candidate_data(
        self,
        family: str,
        candidate: EndpointCapability,
        data: Mapping[str, Any],
        *,
        inventory: dict[
            str,
            dict[tuple[str, bool, str | None], tuple[tuple[str, str], ...]],
        ]
        | None = None,
    ) -> None:
        """Record one successful capability-probe response without its values."""
        metadata = _safe_observed_candidate_metadata(family, candidate)
        if metadata is None:
            return
        observed_candidates = (
            self._observed_candidate_schema if inventory is None else inventory
        )
        safe_family, endpoint, authenticated, referer = metadata
        family_candidates = observed_candidates.get(safe_family)
        if family_candidates is None:
            if len(observed_candidates) >= _OBSERVED_SCHEMA_MAX_FAMILIES:
                return
            family_candidates = {}
            observed_candidates[safe_family] = family_candidates

        candidate_key = (endpoint, authenticated, referer)
        if candidate_key not in family_candidates:
            if len(family_candidates) >= _OBSERVED_SCHEMA_MAX_CANDIDATES_PER_FAMILY:
                return
            total_candidates = sum(
                len(observed) for observed in observed_candidates.values()
            )
            if total_candidates >= _OBSERVED_SCHEMA_MAX_CANDIDATES:
                return

        current = family_candidates.get(candidate_key, ())
        merged = list(current)
        known = set(current)
        for descriptor in _describe_observed_schema(data):
            if descriptor in known:
                continue
            if len(merged) >= _OBSERVED_SCHEMA_MAX_FIELDS:
                break
            merged.append(descriptor)
            known.add(descriptor)
        family_candidates[candidate_key] = tuple(merged)

    async def get_parameter_values(
        self, names: Sequence[str]
    ) -> dict[str, ParameterValue]:
        """Read ToTR64 parameters with 9801 retry/backoff."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()
            return await self._get_parameter_values_unlocked(names)

    async def get_dsl_metrics(self) -> DslMetrics:
        """Read normalized DSL telemetry from exact TR-181 leaf parameters."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()
            names = self._dsl_parameter_names or _DSL_PARAMETER_NAMES
            values, supported_names = await self._read_dsl_parameters_unlocked(names)
            self._dsl_parameter_names = supported_names
            return _make_dsl_metrics(values)

    async def discover_wan_interfaces(self) -> tuple[WanInterface, ...]:
        """Enumerate TR-181 IP interfaces without hardcoded index."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()
            interfaces = await self._discover_wan_interfaces_unlocked()
            with suppress(ValueError):
                self._wan_interface = select_active_wan_interface(interfaces)
            return interfaces

    async def get_wan_counters(self, *, busy_retries: int | None = None) -> WanCounters:
        """Read WAN counters with an optional per-call busy retry policy."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()
            if self._wan_interface is not None:
                try:
                    return await self._read_wan_counters_unlocked(
                        self._wan_interface,
                        busy_retries=busy_retries,
                    )
                except SpeedportSessionBusyError:
                    raise
                except SpeedportProtocolError:
                    self._wan_interface = None
            interfaces = await self._discover_wan_interfaces_unlocked(
                busy_retries=busy_retries
            )
            try:
                interface = select_active_wan_interface(interfaces)
            except ValueError as exc:
                raise SpeedportUnsupportedError(str(exc)) from exc
            self._wan_interface = interface
            return await self._read_wan_counters_unlocked(
                interface,
                busy_retries=busy_retries,
            )

    async def _read_wan_counters_unlocked(
        self,
        interface: WanInterface,
        *,
        busy_retries: int | None = None,
    ) -> WanCounters:
        prefix = f"Device.IP.Interface.{interface.index}.Stats"
        suffixes = (
            _WAN_BYTE_COUNTER_SUFFIXES
            if interface.index in self._wan_optional_counter_faults
            else _WAN_COUNTER_SUFFIXES
        )
        names = tuple(f"{prefix}.{suffix}" for suffix in suffixes)
        try:
            values = await self._get_parameter_values_unlocked(
                names, busy_retries=busy_retries
            )
        except SpeedportSessionBusyError:
            raise
        except SpeedportUnsupportedError:
            if interface.index in self._wan_optional_counter_faults:
                raise
            byte_names = tuple(
                f"{prefix}.{suffix}" for suffix in _WAN_BYTE_COUNTER_SUFFIXES
            )
            values = await self._get_parameter_values_unlocked(
                byte_names, busy_retries=busy_retries
            )
            self._wan_optional_counter_faults.add(interface.index)
        received = _parameter_int(values, f"{prefix}.BytesReceived")
        sent = _parameter_int(values, f"{prefix}.BytesSent")
        if received is None or sent is None:
            raise SpeedportUnsupportedError(
                "Active WAN interface no longer exposes both counters"
            )
        updated_interface = replace(
            interface,
            bytes_received=received,
            bytes_sent=sent,
            packets_received=_parameter_int(values, f"{prefix}.PacketsReceived"),
            packets_sent=_parameter_int(values, f"{prefix}.PacketsSent"),
            errors_received=_parameter_int(values, f"{prefix}.ErrorsReceived"),
            errors_sent=_parameter_int(values, f"{prefix}.ErrorsSent"),
            discard_packets_received=_parameter_int(
                values, f"{prefix}.DiscardPacketsReceived"
            ),
            discard_packets_sent=_parameter_int(values, f"{prefix}.DiscardPacketsSent"),
        )
        self._wan_interface = updated_interface
        return _make_wan_counters(updated_interface)

    async def _read_dsl_parameters_unlocked(
        self, names: Sequence[str]
    ) -> tuple[dict[str, ParameterValue], tuple[str, ...]]:
        """Read DSL leaves, isolating unsupported optional parameters."""
        try:
            values = await self._get_parameter_values_unlocked(names)
        except SpeedportSessionBusyError:
            raise
        except SpeedportUnsupportedError:
            values = {}
            supported_names: list[str] = []
            for name in names:
                try:
                    parameter = await self._get_parameter_values_unlocked((name,))
                except SpeedportSessionBusyError:
                    raise
                except SpeedportUnsupportedError:
                    continue
                values.update(parameter)
                if name in parameter:
                    supported_names.append(name)
        else:
            supported_names = [name for name in names if name in values]

        if not any(
            name in values
            for name in (
                _DSL_DOWNSTREAM_CURRENT_RATE,
                _DSL_UPSTREAM_CURRENT_RATE,
            )
        ):
            raise SpeedportUnsupportedError(
                "Router exposes no DSL channel current-rate telemetry"
            )
        return values, tuple(supported_names)

    async def probe_capabilities(
        self,
        *,
        allow_protected_degraded: bool = False,
    ) -> CapabilityReport:
        """Probe only read endpoints and record independent failures."""
        observed_candidate_schema: dict[
            str,
            dict[tuple[str, bool, str | None], tuple[tuple[str, str], ...]],
        ] = {}
        failures: dict[str, str] = {}
        selected: dict[str, EndpointCapability] = {}
        status_ok = False
        tr064_ok = False
        counters_ok = False
        authenticated_ok = False

        endpoint_results: dict[
            tuple[str, bool, str | None],
            tuple[dict[str, Any] | None, SpeedportError | None],
        ] = {}
        confirmed_endpoint_families: set[str] = set()

        async def probe_endpoint_phase(*, authenticated: bool) -> None:
            nonlocal authenticated_ok
            for family, candidates in self._endpoint_candidates.items():
                if family in confirmed_endpoint_families:
                    continue
                phase_candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.authenticated is authenticated
                    and candidate.automatic_probe
                ]
                for candidate in phase_candidates:
                    cache_key = (
                        candidate.endpoint,
                        candidate.authenticated,
                        candidate.referer,
                    )
                    if cache_key not in endpoint_results:
                        try:
                            fetched_data = await self.get_json(
                                candidate.endpoint,
                                authenticated=candidate.authenticated,
                                referer=candidate.referer,
                            )
                            if (
                                authenticated
                                and not fetched_data
                                and (
                                    candidate.endpoint,
                                    candidate.referer,
                                )
                                in _QUERY_TOKEN_READS
                            ):
                                # A freshly tokenized page read should be stable,
                                # but one bounded retry prevents a transient empty
                                # response from suppressing the control until reload.
                                fetched_data = await self.get_json(
                                    candidate.endpoint,
                                    authenticated=True,
                                    referer=candidate.referer,
                                )
                        except SpeedportUnsupportedError as exc:
                            endpoint_results[cache_key] = (None, exc)
                        except SpeedportError as exc:
                            if not (authenticated and allow_protected_degraded):
                                raise
                            authenticated_ok = False
                            endpoint_results[cache_key] = (None, exc)
                            failures["authentication"] = _failure_text(exc)
                            self._last_management_error = exc
                            return
                        else:
                            endpoint_results[cache_key] = (fetched_data, None)
                            if authenticated:
                                authenticated_ok = True
                    endpoint_data, error = endpoint_results[cache_key]
                    if error is None and endpoint_data is not None:
                        self._observe_candidate_data(
                            family,
                            candidate,
                            endpoint_data,
                            inventory=observed_candidate_schema,
                        )
                    if (
                        error is None
                        and endpoint_data is not None
                        and _has_capability_evidence(endpoint_data, candidate)
                    ):
                        selected[family] = candidate
                        confirmed_endpoint_families.add(family)
                        failures.pop(family, None)
                        break
                    if error is None:
                        error = SpeedportUnsupportedError(
                            "Endpoint returned no matching capability data"
                        )
                    if family not in selected:
                        failures.setdefault(family, _failure_text(error))

        try:
            await self.logout()
            try:
                if self._last_status is None:
                    await self.get_status()
                status_ok = True
                selected["status"] = _endpoint("status", "data/Status.json")
                self._add_status_capabilities(selected)
            except SpeedportUnsupportedError as exc:
                failures["status"] = _failure_text(exc)

            try:
                await self.get_wan_counters()
                tr064_ok = True
                counters_ok = True
            except SpeedportSessionBusyError as exc:
                # A valid 9801 SOAP fault proves that ToTR64 accepted the
                # GetParameterValues request. It does not prove that this
                # router exposes the requested WAN counter parameters, so keep
                # only ToTR64 confirmed and let the hub retry the counters.
                tr064_ok = True
                failures["tr064"] = _failure_text(exc)
                failures["wan_counters"] = _failure_text(exc)
                self._last_management_error = exc
                if not allow_protected_degraded:
                    raise
            except SpeedportUnsupportedError as exc:
                failures["tr064"] = _failure_text(exc)
                failures["wan_counters"] = _failure_text(exc)

            await probe_endpoint_phase(authenticated=False)

            if self._password:
                try:
                    await self.login()
                except (
                    SpeedportSessionBusyError,
                    SpeedportLoginLockedError,
                ) as exc:
                    failures["authentication"] = _failure_text(exc)
                    self._last_management_error = exc
                    if not allow_protected_degraded:
                        raise
                except SpeedportInvalidCredentialsError:
                    raise
                except SpeedportError as exc:
                    if not allow_protected_degraded:
                        raise
                    failures["authentication"] = _failure_text(exc)
                    self._last_management_error = exc
                else:
                    self._last_management_error = None
                    await probe_endpoint_phase(authenticated=True)
                    if not authenticated_ok:
                        failures.setdefault(
                            "authentication",
                            "No authenticated endpoint read succeeded",
                        )

            report = CapabilityReport(
                status_json=status_ok,
                tr064=tr064_ok,
                wan_counters=counters_ok,
                authenticated_json=authenticated_ok,
                feature_endpoints=MappingProxyType(dict(selected)),
                failures=MappingProxyType(failures),
            )
        finally:
            await self.logout()

        self._selected_endpoints = selected
        self._capabilities = report
        self._observed_candidate_schema = observed_candidate_schema
        return report

    def _add_status_capabilities(self, selected: dict[str, EndpointCapability]) -> None:
        """Expose core families proven directly by public Status.json."""
        status = self._last_status
        if status is None:
            return
        if (
            status.internet_state is not None
            or status.wan_download_capacity_bps is not None
            or status.wan_upload_capacity_bps is not None
        ):
            selected["internet"] = _endpoint("internet", "data/Status.json")
        if (
            status.dsl_state is not None
            or status.dsl_downstream_bps is not None
            or status.dsl_upstream_bps is not None
        ):
            selected["dsl"] = _endpoint("dsl", "data/Status.json")
        for family, evidence in {
            "hybrid": ("hybrid", "bond"),
            "mobile": ("mobile", "lte", "5g", "ex5g"),
            "lte": ("lte", "ex5g_signal_lte"),
            "5g": ("5g", "ex5g"),
        }.items():
            capability = _endpoint(
                family,
                "data/Status.json",
                evidence_keys=evidence,
            )
            if _has_capability_evidence(status.raw, capability):
                selected[family] = capability

    async def _login_unlocked(self) -> None:
        if self._authenticated:
            return
        if self._session_cleanup_key is not None:
            await self._logout_unlocked()
        if not self._password:
            raise SpeedportAuthenticationError("Router password is required")
        if self._encrypted_mode is None:
            await self._get_json_unlocked(
                "data/Status.json", authenticated=False, referer=None
            )
        challenge_result = await self._post_json_unlocked(
            "data/Login.json",
            {"getChallenge": "1"},
            authenticated=False,
            referer=None,
            ensure_auth=False,
        )
        try:
            _raise_login_gate(challenge_result)
        except (SpeedportSessionBusyError, SpeedportLoginLockedError) as err:
            self._last_management_error = err
            raise
        challenge = str(challenge_result.get("challenge", "")).strip()
        try:
            challenge_key = bytes.fromhex(challenge)
        except ValueError as exc:
            raise SpeedportAuthenticationError(
                "Router returned invalid login challenge"
            ) from exc
        if len(challenge_key) not in {16, 24, 32}:
            raise SpeedportAuthenticationError(
                "Router returned invalid login challenge"
            )
        password_hash = sha256(f"{challenge}:{self._password}".encode()).hexdigest()
        # A proof request may be accepted even when its response cannot be
        # decoded or the connection drops. Retain only this router-issued key
        # so logout/close can release the tentative session without ever
        # sending a blind logout.
        self._session_cleanup_key = challenge_key
        result = await self._post_json_unlocked(
            "data/Login.json",
            {"showpw": "0", "password": password_hash},
            authenticated=False,
            referer=None,
            ensure_auth=False,
            request_key=challenge_key,
            response_key=challenge_key,
        )
        try:
            _raise_login_gate(result)
        except (SpeedportSessionBusyError, SpeedportLoginLockedError) as err:
            self._clear_session_state()
            self._last_management_error = err
            raise
        login_state = str(result.get("login", result.get("status", ""))).casefold()
        if login_state not in {"success", "ok", "true", "1"}:
            self._clear_session_state()
            raise SpeedportInvalidCredentialsError("Router rejected login credentials")
        self._login_key = challenge_key
        self._authenticated = True
        self._last_management_error = None

    async def _get_json_unlocked(
        self,
        endpoint: str,
        *,
        authenticated: bool,
        referer: str | None,
        preserve_compounds: bool = False,
    ) -> dict[str, Any]:
        if authenticated:
            await self._ensure_authenticated_unlocked()
        path = _validate_endpoint(endpoint)
        query: dict[str, str | int] = {}
        settings_token_read = any(
            (path, referer)
            == (item.read_endpoint or item.endpoint, item.read_referer or item.referer)
            for item in settings_contracts().values()
        )
        if (
            authenticated
            and referer
            and (
                (path.partition("?")[0], referer) in _QUERY_TOKEN_READS
                or settings_token_read
                or (path, referer) in target_settings_read_pairs()
            )
        ):
            # Smart 4 page-scoped JSON endpoints return an empty document unless
            # the page's current HTTP token is supplied as the `_tn` query value.
            # Fetching the referer and then issuing this GET mirrors the router UI
            # without changing router state.
            token = await self._get_http_token_unlocked(referer)
            if token is None or _QUERY_TOKEN_VALUE.fullmatch(token) is None:
                raise SpeedportUnsupportedError(
                    "Router page token is unavailable for protected read"
                )
            query["_tn"] = token
        nonce = time.time_ns()
        query["_time"] = nonce // 1_000_000
        query["_rand"] = nonce % 1001
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}{urlencode(query)}"
        headers = self._json_headers(referer)
        text = await self._request_text_unlocked("GET", url, headers=headers)
        if _looks_like_login_page(text):
            self._invalidate_authentication()
            raise SpeedportAuthenticationError("Router session expired")
        if self._encrypted_mode is None:
            self._encrypted_mode = is_encrypted_payload(text)
        if authenticated and self._login_key is None:
            raise SpeedportAuthenticationError("Authenticated session has no key")
        try:
            return _decode_response(
                text,
                self._login_key,
                **({"preserve_compounds": True} if preserve_compounds else {}),
            )
        except SpeedportDecodeError as exc:
            if authenticated:
                self._invalidate_authentication()
                raise SpeedportAuthenticationError(
                    "Authenticated router response could not be decoded"
                ) from exc
            raise

    async def _post_json_unlocked(
        self,
        endpoint: str,
        data: Mapping[str, str | int | bool],
        *,
        authenticated: bool,
        referer: str | None,
        ensure_auth: bool = True,
        resolve_http_token: bool = True,
        request_key: bytes | None = None,
        response_key: bytes | None = None,
    ) -> dict[str, Any]:
        if authenticated and ensure_auth:
            await self._ensure_authenticated_unlocked()
        path = _validate_endpoint(endpoint)
        fields = dict(data)
        if referer and resolve_http_token and "httoken" not in fields:
            token = await self._get_http_token_unlocked(referer)
            if token:
                fields["httoken"] = token
        plain_body = urlencode(fields)
        key: bytes | None
        if request_key is not None:
            key = request_key
        elif authenticated:
            key = self._login_key
        else:
            key = DEFAULT_KEY
        if authenticated and key is None:
            raise SpeedportAuthenticationError("Authenticated session has no key")
        body = (
            encode_payload(plain_body, key or DEFAULT_KEY)
            if self._encrypted_mode is not False
            else plain_body
        )
        headers = self._json_headers(referer)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        # The request may have waited on a client lock, authentication, or page
        # token. Revalidate the live HA session only after those awaits. Exact
        # ownership-key logout remains possible after revocation/cancellation.
        owned_logout = (
            path == "data/Login.json"
            and dict(data) == {"logout": "byby"}
            and not authenticated
            and not ensure_auth
            and self._session_cleanup_key is not None
            and request_key is self._session_cleanup_key
        )
        if not owned_logout:
            check_private_authorization()
        text = await self._request_text_unlocked(
            "POST", f"{self._base_url}/{path}", headers=headers, data=body
        )
        if _looks_like_login_page(text):
            self._invalidate_authentication()
            raise SpeedportAuthenticationError("Router session expired")
        try:
            decode_key = response_key if response_key is not None else self._login_key
            return _decode_response(text, decode_key)
        except SpeedportDecodeError as exc:
            if authenticated:
                self._invalidate_authentication()
                raise SpeedportAuthenticationError(
                    "Authenticated router response could not be decoded"
                ) from exc
            raise

    async def _get_http_token_unlocked(self, referer: str) -> str | None:
        path = _validate_endpoint(referer)
        text = await self._request_text_unlocked(
            "GET",
            f"{self._base_url}/{path}",
            headers=self._json_headers(None),
        )
        if _looks_like_login_page(text):
            self._invalidate_authentication()
            raise SpeedportAuthenticationError("Router session expired")
        for pattern in _HTTP_TOKEN_PATTERNS:
            if match := pattern.search(text):
                return match.group(1)
        return None

    async def _ensure_authenticated_unlocked(self) -> None:
        if not self._authenticated:
            await self._login_unlocked()

    async def _logout_unlocked(self, *, require_confirmation: bool = False) -> None:
        """Release our web login while retaining credentials for later reuse."""
        cleanup_key = self._session_cleanup_key
        if cleanup_key is None:
            return
        try:
            primary_rejected = False
            primary_confirmed = False
            try:
                result = await self._post_json_unlocked(
                    "data/Login.json",
                    {"logout": "byby"},
                    authenticated=False,
                    referer=_LOGOUT_REFERER,
                    ensure_auth=False,
                    request_key=cleanup_key,
                    response_key=cleanup_key,
                )
                primary_rejected = _logout_response_rejected(result)
                primary_confirmed = _logout_response_confirmed(result)
            except SpeedportError:
                primary_rejected = True
            cleanup_unconfirmed = not primary_confirmed
            if primary_rejected or (require_confirmation and not primary_confirmed):
                try:
                    fallback = await self._post_json_unlocked(
                        "data/Login.json",
                        {"logout": "byby"},
                        authenticated=False,
                        referer=None,
                        ensure_auth=False,
                        request_key=cleanup_key,
                        response_key=cleanup_key,
                    )
                    cleanup_unconfirmed = not _logout_response_confirmed(fallback)
                except SpeedportError:
                    cleanup_unconfirmed = True
            if require_confirmation and cleanup_unconfirmed:
                raise SpeedportProtocolError(
                    "Router session cleanup could not be confirmed"
                )
        finally:
            self._clear_session_state()
            await asyncio.sleep(_LOGOUT_SETTLE_SECONDS)

    async def _get_parameter_values_unlocked(
        self,
        names: Sequence[str],
        *,
        busy_retries: int | None = None,
    ) -> dict[str, ParameterValue]:
        max_busy_retries = (
            self._max_busy_retries if busy_retries is None else busy_retries
        )
        if max_busy_retries < 0:
            msg = "busy_retries cannot be negative"
            raise ValueError(msg)
        body = build_get_parameter_values(names)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
            "User-Agent": "Home Assistant Telekom Speedport Smart",
        }
        for attempt in range(max_busy_retries + 1):
            text = await self._request_text_unlocked(
                "POST",
                self._tr064_url,
                headers=headers,
                data=body,
                allow_error_body=True,
            )
            try:
                return parse_get_parameter_values(text)
            except SpeedportSessionBusyError:
                if attempt >= max_busy_retries:
                    raise
                await asyncio.sleep(self._busy_backoff * (2**attempt))
        raise SpeedportSessionBusyError("ToTR64 session remained busy")

    async def _discover_wan_interfaces_unlocked(
        self, *, busy_retries: int | None = None
    ) -> tuple[WanInterface, ...]:
        parameters: dict[str, ParameterValue]
        interface_count: int | None = None
        try:
            count_values = await self._get_parameter_values_unlocked(
                ("Device.IP.InterfaceNumberOfEntries",),
                busy_retries=busy_retries,
            )
            count_value = count_values.get("Device.IP.InterfaceNumberOfEntries")
            if count_value is not None:
                interface_count = _as_int(count_value.value)
        except SpeedportSessionBusyError:
            raise
        except SpeedportProtocolError:
            interface_count = None

        if interface_count is not None and 0 < interface_count <= _MAX_INTERFACE_COUNT:
            interface_suffixes = (
                *_INTERFACE_METADATA_SUFFIXES,
                *(f"Stats.{suffix}" for suffix in _WAN_BYTE_COUNTER_SUFFIXES),
            )
            names = tuple(
                f"Device.IP.Interface.{index}.{suffix}"
                for index in range(1, interface_count + 1)
                for suffix in interface_suffixes
            )
            try:
                parameters = await self._get_parameter_values_unlocked(
                    names, busy_retries=busy_retries
                )
            except SpeedportSessionBusyError:
                raise
            except SpeedportProtocolError:
                parameters = await self._discover_interface_parameters_unlocked(
                    busy_retries=busy_retries
                )
        else:
            parameters = await self._discover_interface_parameters_unlocked(
                busy_retries=busy_retries
            )

        grouped: dict[int, dict[str, ParameterValue]] = {}
        for name, parameter in parameters.items():
            match = _INTERFACE_PARAMETER.fullmatch(name)
            if match is None:
                continue
            index = int(match.group(1))
            grouped.setdefault(index, {})[match.group(2)] = parameter
        interfaces = tuple(
            _make_interface(index, values) for index, values in sorted(grouped.items())
        )
        if not interfaces:
            raise SpeedportUnsupportedError(
                "Router exposed no Device.IP.Interface entries"
            )
        return interfaces

    async def _discover_interface_parameters_unlocked(
        self,
        *,
        busy_retries: int | None = None,
    ) -> dict[str, ParameterValue]:
        """Scan standard interface aliases when secured count is unavailable."""
        try:
            return await self._get_parameter_values_unlocked(
                ("Device.IP.Interface.",), busy_retries=busy_retries
            )
        except SpeedportSessionBusyError:
            raise
        except SpeedportProtocolError:
            pass

        parameters: dict[str, ParameterValue] = {}
        for index in range(1, _MAX_INTERFACE_SCAN + 1):
            prefix = f"Device.IP.Interface.{index}"
            alias_name = f"{prefix}.Alias"
            try:
                alias = await self._get_parameter_values_unlocked(
                    (alias_name,), busy_retries=busy_retries
                )
            except SpeedportSessionBusyError:
                raise
            except SpeedportProtocolError:
                continue
            parameters.update(alias)
            detail_suffixes = (
                "Name",
                "Status",
                "Enable",
                *(f"Stats.{suffix}" for suffix in _WAN_BYTE_COUNTER_SUFFIXES),
            )
            names = tuple(f"{prefix}.{suffix}" for suffix in detail_suffixes)
            try:
                parameters.update(
                    await self._get_parameter_values_unlocked(
                        names, busy_retries=busy_retries
                    )
                )
            except SpeedportSessionBusyError:
                raise
            except SpeedportProtocolError:
                fallback_names = tuple(
                    f"{prefix}.{suffix}" for suffix in detail_suffixes
                )
                try:
                    parameters.update(
                        await self._get_parameter_values_unlocked(
                            fallback_names, busy_retries=busy_retries
                        )
                    )
                    continue
                except SpeedportSessionBusyError:
                    raise
                except SpeedportProtocolError:
                    pass
                for name in fallback_names:
                    try:
                        parameters.update(
                            await self._get_parameter_values_unlocked(
                                (name,), busy_retries=busy_retries
                            )
                        )
                    except SpeedportSessionBusyError:
                        raise
                    except SpeedportProtocolError:
                        continue
        return parameters

    async def _request_text_unlocked(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: str | None = None,
        allow_error_body: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "headers": dict(headers),
            "timeout": self._timeout,
            "allow_redirects": False,
        }
        if data is not None:
            kwargs["data"] = data
        if url.startswith("https://") and not self._verify_ssl:
            kwargs["ssl"] = False
        try:
            async with self._session.request(method, url, **kwargs) as response:
                if method != "GET" or urlsplit(url).path != "/data/IPData.json":
                    text = await response.text(errors="replace")
                else:
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(16 * 1024):
                        if len(body) + len(chunk) > _IP_INFORMATION_MAX_RESPONSE_BYTES:
                            raise SpeedportProtocolError(
                                "Router response exceeded the private read limit"
                            )
                        body.extend(chunk)
                    text = body.decode("utf-8", errors="replace")
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location", "")
                    if "login" in location.casefold():
                        self._invalidate_authentication()
                        raise SpeedportAuthenticationError("Router session expired")
                    raise SpeedportProtocolError(
                        f"Unexpected router redirect: HTTP {response.status}"
                    )
                if response.status in {401, 403}:
                    self._invalidate_authentication()
                    raise SpeedportAuthenticationError(
                        f"Router rejected request: HTTP {response.status}"
                    )
                if response.status == _HTTP_NOT_FOUND:
                    raise SpeedportUnsupportedError("Router endpoint not found")
                if response.status >= _HTTP_BAD_REQUEST and not allow_error_body:
                    raise SpeedportProtocolError(
                        f"Router returned HTTP {response.status}"
                    )
                return text
        except SpeedportError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise SpeedportConnectionError("Router request failed") from exc

    def _json_headers(self, referer: str | None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Home Assistant Telekom Speedport Smart",
        }
        if referer:
            path = _validate_endpoint(referer)
            headers["Referer"] = f"{self._base_url}/{path}"
        return headers

    def _invalidate_authentication(self) -> None:
        """Invalidate reads while preserving proof-bound cleanup ownership."""
        self._authenticated = False
        self._login_key = None

    def _clear_session_state(self) -> None:
        """Forget both active authentication and any tentative owned session."""
        self._invalidate_authentication()
        self._session_cleanup_key = None

    def _ensure_open(self) -> None:
        if self._closed:
            raise SpeedportProtocolError("Speedport client is closed")


def _require_boolean(value: object, *, description: str) -> None:
    """Reject truthy substitutes before any Boolean router mutation."""
    if not isinstance(value, bool):
        raise SpeedportProtocolError(f"{description} must be a boolean")


def _require_guarded_scalar_value(
    payload: Mapping[str, Any],
    *,
    field: str,
    allowed_values: frozenset[str],
) -> str:
    """Return one exact allowlisted scalar or fail closed before mutation."""
    matches = [
        (raw_key, value)
        for raw_key, value in payload.items()
        if isinstance(raw_key, str) and raw_key.strip().casefold() == field.casefold()
    ]
    if len(matches) != 1 or matches[0][0] != field:
        raise SpeedportUnsupportedError("Guarded scalar state is missing or ambiguous")
    value = matches[0][1]
    if not isinstance(value, str) or value not in allowed_values:
        raise SpeedportUnsupportedError(
            "Guarded scalar state has an unsupported representation"
        )
    return value


def _require_receiver_led_mode_value(payload: Mapping[str, Any]) -> str:
    """Return the exact receiver LED readback as its write-side decimal code."""
    raw_value = _require_guarded_scalar_value(
        payload,
        field="ex5g_led_mode",
        allowed_values=frozenset(RECEIVER_LED_MODE_CODES),
    )
    return str(RECEIVER_LED_MODE_CODES[raw_value])


def _select_managed_device_row(
    payload: Mapping[str, Any],
    source_kind: str,
    form: _ManagedDeviceForm,
    *,
    row_id: str,
    stable_mac: str | None,
) -> dict[str, str | int | bool]:
    """Select one unambiguous full form row from a fresh DeviceList payload."""
    matching_groups = [
        value
        for key, value in payload.items()
        if str(key).strip().casefold() == source_kind
    ]
    if len(matching_groups) != 1:
        raise SpeedportUnsupportedError(
            "Managed-device source row is missing or ambiguous"
        )

    expected_id = row_id.strip().casefold()
    if not expected_id:
        raise SpeedportUnsupportedError("Managed-device row has no stable ID")
    expected_mac = _mac_token(value=stable_mac) if stable_mac is not None else ""
    if not expected_mac:
        raise SpeedportUnsupportedError("Managed-device row has no stable MAC address")
    matches: list[dict[str, str | int | bool]] = []
    for candidate in _managed_form_rows(matching_groups[0]):
        row = _canonical_form_row(candidate)
        if row is None or str(row.get("id", "")).strip().casefold() != expected_id:
            continue
        if not form.fields <= row.keys():
            raise SpeedportUnsupportedError(
                "Managed-device row does not expose the complete firmware form"
            )
        unknown_form_fields = set(row) - form.fields
        if unknown_form_fields:
            raise SpeedportUnsupportedError(
                "Managed-device row contains unproven firmware fields"
            )
        row_mac = row.get("mdevice_mac")
        if (
            row_mac is None
            or row_mac == ""
            or _mac_token(value=row_mac) != expected_mac
        ):
            continue
        matches.append({field: row[field] for field in form.fields})

    if len(matches) != 1:
        raise SpeedportUnsupportedError(
            "Managed-device source row is missing, duplicated, or changed identity"
        )
    return matches[0]


def _select_port_forward_rule(
    payload: Mapping[str, Any],
    *,
    rule_id: str,
    expected_name: str | None,
    expected_fingerprint: str,
) -> bool:
    """Select one unchanged rule identity with an explicit fresh active state."""
    expected_id = rule_id.strip().casefold()
    if not expected_id:
        raise SpeedportUnsupportedError("Port-forward rule has no stable ID")
    if not isinstance(expected_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_fingerprint
    ):
        raise SpeedportUnsupportedError(
            "Port-forward rule has no stable identity fingerprint"
        )
    matches: list[bool] = []
    for raw_key, value in payload.items():
        if str(raw_key).strip().casefold() not in _PORT_FORWARD_GROUPS:
            continue
        for candidate in _managed_form_rows(value):
            row = {str(key).strip().casefold(): item for key, item in candidate.items()}
            identifier = next(
                (row[key] for key in ("id", "rule_id", "portuw_id") if key in row),
                None,
            )
            if str(identifier).strip().casefold() != expected_id:
                continue
            name = next(
                (
                    row[key]
                    for key in ("name", "rule_name", "portuw_name")
                    if key in row
                ),
                None,
            )
            if expected_name is not None and (
                name is None or str(name).strip() != expected_name
            ):
                continue
            if port_forward_rule_fingerprint(row) != expected_fingerprint:
                continue
            active = next(
                (
                    _as_bool(row[key])
                    for key in ("active", "enabled", "portuw_active")
                    if key in row
                ),
                None,
            )
            if active is None:
                raise SpeedportUnsupportedError(
                    "Port-forward rule has no explicit current state"
                )
            matches.append(active)
    if len(matches) != 1:
        raise SpeedportUnsupportedError(
            "Port-forward rule is missing, duplicated, or changed identity"
        )
    return matches[0]


def _managed_form_rows(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Expand one template collection without inventing row identities."""
    if isinstance(value, Mapping):
        sequence_columns = {
            str(key): tuple(items)
            for key, items in value.items()
            if isinstance(items, Sequence)
            and not isinstance(items, (str, bytes, bytearray))
        }
        if not sequence_columns:
            return (value,)
        lengths = {len(items) for items in sequence_columns.values()}
        if len(lengths) != 1:
            return ()
        scalar_columns = {
            str(key): item for key, item in value.items() if key not in sequence_columns
        }
        length = lengths.pop()
        return tuple(
            {
                **scalar_columns,
                **{key: items[index] for key, items in sequence_columns.items()},
            }
            for index in range(length)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _canonical_form_row(
    row: Mapping[str, Any],
) -> dict[str, str | int | bool] | None:
    """Case-normalize safe scalar form values and reject duplicate keys."""
    canonical: dict[str, str | int | bool] = {}
    for raw_key, value in row.items():
        key = str(raw_key).strip().casefold()
        if (
            key in canonical
            or isinstance(value, bool)
            or not isinstance(value, (str, int))
        ):
            return None
        canonical[key] = value
    return canonical


def _validate_fixed_dhcp_row(row: Mapping[str, str | int | bool]) -> None:
    """Enforce firmware UI prerequisites without changing address metadata."""
    use_rule = _form_boolean(value=row["mdevice_use_rule"])
    uses_dhcp = _form_boolean(value=row["mdevice_use_dhcp"])
    fixed_dhcp = _form_boolean(value=row["mdevice_fix_dhcp"])
    if use_rule is None or uses_dhcp is None or fixed_dhcp is None:
        raise SpeedportUnsupportedError(
            "Managed-device row contains an unknown checkbox value"
        )
    if use_rule is not False:
        raise SpeedportUnsupportedError(
            "Fixed DHCP cannot change while an access rule owns this row"
        )
    if not (uses_dhcp or fixed_dhcp):
        raise SpeedportUnsupportedError(
            "Managed-device row does not expose fixed-DHCP control"
        )
    try:
        ipaddress.IPv4Address(str(row["mdevice_ipv4"]).strip())
    except ipaddress.AddressValueError as err:
        raise SpeedportUnsupportedError(
            "Managed-device row has no valid current IPv4 address"
        ) from err


def _form_boolean(*, value: str | int | bool) -> bool | None:
    """Interpret only explicit firmware checkbox values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        return None
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "on", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    return None


def _require_command_acknowledgement(response: Mapping[str, Any]) -> None:
    """Fail closed unless firmware explicitly accepts a state-changing POST."""
    status = response.get("status")
    accepted = status is True or status == 1
    if isinstance(status, str):
        accepted = status.strip().casefold() in {"1", "ok", "success", "true"}
    if not accepted:
        raise SpeedportCommandRejectedError(
            "Router command response did not contain a successful acknowledgement"
        )


def _reject_explicit_action_failure(response: Mapping[str, Any]) -> None:
    """Allow absent ACK only when no exact response field reports failure."""
    for key in ("status", "result"):
        if key not in response:
            continue
        value = response[key]
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"1", "ok", "success", "true"}:
                continue
            if normalized in {
                "0",
                "denied",
                "error",
                "failed",
                "failure",
                "false",
                "no",
                "nok",
                "rejected",
            }:
                raise SpeedportCommandRejectedError(
                    "Router explicitly rejected the administrator action"
                )
        else:
            if (type(value) is bool and value) or (type(value) is int and value == 1):
                continue
            if (type(value) is bool and not value) or (
                type(value) is int and value == 0
            ):
                raise SpeedportCommandRejectedError(
                    "Router explicitly rejected the administrator action"
                )
        raise SpeedportMutationOutcomeUnknownError(
            "Router mutation acknowledgement is indeterminate"
        )
    for key in ("error", "errors"):
        if key in response and response[key] not in (None, "", False, 0, (), [], {}):
            raise SpeedportCommandRejectedError(
                "Router explicitly rejected the administrator action"
            )


def _require_exact_status_ok(response: Mapping[str, Any]) -> None:
    """Require the VoIP-number deletion callback's exact positive status."""
    for key in ("error", "errors"):
        if key in response and response[key] not in (None, "", False, 0, (), [], {}):
            raise SpeedportCommandRejectedError(
                "Router explicitly rejected the administrator action"
            )
    status = _mapping_value(response, "status")
    if isinstance(status, str) and status.strip().casefold() == "ok":
        return
    explicit_negative = (type(status) is bool and not status) or (
        type(status) is int and status == 0
    )
    if isinstance(status, str):
        explicit_negative = status.strip().casefold() in {
            "0",
            "denied",
            "error",
            "failed",
            "failure",
            "false",
            "no",
            "nok",
            "rejected",
        }
    if explicit_negative:
        raise SpeedportCommandRejectedError(
            "Router explicitly rejected the administrator action"
        )
    raise SpeedportMutationOutcomeUnknownError(
        "Router mutation acknowledgement is indeterminate"
    )


def _require_exact_result_ok(response: Mapping[str, Any]) -> None:
    """Require the firmware-update callback's explicit result, never infer success."""
    _reject_explicit_action_failure(response)
    keys = [key for key in response if str(key).casefold() == "result"]
    if keys == ["result"] and response["result"] == "ok":
        return
    raise SpeedportMutationOutcomeUnknownError(
        "Router mutation acknowledgement is indeterminate"
    )


def _require_private_query_identifier(value: object, *, description: str) -> str:
    """Accept one short opaque firmware row identifier without echoing it on error."""
    if not isinstance(value, str) or _PRIVATE_QUERY_ID.fullmatch(value) is None:
        raise SpeedportProtocolError(f"{description} is invalid")
    return value


def _require_admin_action_identifier(value: object, *, description: str) -> str:
    """Accept one short opaque action target without echoing it on failure."""
    if not isinstance(value, str) or _PRIVATE_QUERY_ID.fullmatch(value) is None:
        raise SpeedportProtocolError(f"{description} is invalid")
    return value


def _require_admin_target_fingerprint(value: object) -> str:
    """Accept one internal row fingerprint without echoing it on failure."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SpeedportProtocolError("Administrator action target proof is invalid")
    return value


def _strict_router_boolean(value: object) -> bool | None:
    """Parse only exact Boolean wire representations used by this firmware."""
    if type(value) is bool:
        return value
    if type(value) is int and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value in {"0", "1"}:
        return value == "1"
    return None


def _require_unique_scalar(payload: Mapping[str, Any], field: str) -> object:
    """Return one exact case-insensitive scalar field or fail closed."""
    matches = [
        value
        for raw_key, value in payload.items()
        if isinstance(raw_key, str) and raw_key.strip().casefold() == field.casefold()
    ]
    if len(matches) != 1:
        raise SpeedportUnsupportedError("Router action state is missing or ambiguous")
    return matches[0]


def _require_dect_scan_active(payload: Mapping[str, Any]) -> bool:
    """Return the exact DECT scan lifecycle value."""
    value = _strict_router_boolean(
        _require_unique_scalar(payload, "dect_detect_status")
    )
    if value is None:
        raise SpeedportUnsupportedError("DECT scan state is unsupported")
    return value


def _dect_handset_rows(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one complete, uniquely identified firmware handset collection."""
    return _strict_dect_handset_rows(payload)


def _require_dect_handset(
    payload: Mapping[str, Any],
    *,
    handset_id: str,
) -> dict[str, Any]:
    """Return one exact handset row by stable opaque ID."""
    matches = [
        row
        for row in _dect_handset_rows(payload)
        if _private_query_identifier(row.get("id")) == handset_id
    ]
    if len(matches) != 1:
        raise SpeedportUnsupportedError("DECT handset target is missing or ambiguous")
    return matches[0]


def _dect_handset_fingerprint(
    row: Mapping[str, Any],
    *,
    handset_id: str,
) -> str:
    """Bind one handset token to stable, non-secret row identity fields."""
    name = _first_private_query_value(
        row,
        ("dect_name", "name"),
        _private_query_text,
        max_length=64,
    )
    return sha256(f"dect\x1f{handset_id}\x1f{name or ''}".encode()).hexdigest()


def _require_dect_paging_state(
    payload: Mapping[str, Any],
    *,
    handset_id: str,
) -> bool:
    """Return one exact per-handset paging state."""
    value = _strict_router_boolean(
        _require_unique_scalar(payload, f"pagingstat{handset_id}")
    )
    if value is None:
        raise SpeedportUnsupportedError("DECT paging state is unsupported")
    return value


def _project_dect_handset_targets(
    station: Mapping[str, Any],
    status: Mapping[str, Any],
) -> dict[str, Any]:
    """Project bounded action targets without exposing handset assignments."""
    rows = _dect_handset_rows(station)
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        target_id = _private_query_identifier(row.get("id"))
        if target_id is None or target_id in seen:
            continue
        seen.add(target_id)
        try:
            paging = _require_dect_paging_state(status, handset_id=target_id)
        except SpeedportUnsupportedError:
            continue
        target: dict[str, Any] = {
            "target_id": target_id,
            "reference": target_id,
            "paging": paging,
        }
        target["target_fingerprint"] = _dect_handset_fingerprint(
            row,
            handset_id=target_id,
        )
        name = _first_private_query_value(
            row,
            ("dect_name", "name"),
            _private_query_text,
            max_length=64,
        )
        if name is not None:
            target["name"] = name
        eligible.append(target)
    return {
        "targets": eligible[:_PRIVATE_QUERY_MAX_DECT_TARGETS],
        "truncated": len(eligible) > _PRIVATE_QUERY_MAX_DECT_TARGETS,
    }


def _voip_line_rows(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return one complete, uniquely identified firmware VoIP line collection."""
    return _strict_voip_line_rows(payload)


def _project_voip_line_targets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project bounded line action identities without exposing phone numbers."""
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _voip_line_rows(payload):
        target_id = _private_query_identifier(
            row.get("id", row.get("ipphonenumber_id"))
        )
        if target_id is None or target_id in seen:
            continue
        seen.add(target_id)
        status = row.get("number_status")
        if status not in {"ok", "inactive"}:
            continue
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _voip_line_fingerprint(
                row,
                line_id=target_id,
            ),
            "reference": target_id,
            "active": status == "ok",
        }
        number = _first_private_query_value(
            row,
            ("ip_number", "phone_number", "number"),
            _private_query_phone_number,
            max_length=_PRIVATE_QUERY_MAX_PHONE_LENGTH,
        )
        digits = "".join(character for character in number or "" if character.isdigit())
        if len(digits) > _MASKED_PHONE_SUFFIX_DIGITS:
            target["number_suffix"] = digits[-_MASKED_PHONE_SUFFIX_DIGITS:]
        targets.append(target)
    return {
        "targets": targets[:_PRIVATE_QUERY_MAX_VOIP_TARGETS],
        "truncated": len(targets) > _PRIVATE_QUERY_MAX_VOIP_TARGETS,
    }


def _voip_line_fingerprint(
    row: Mapping[str, Any],
    *,
    line_id: str,
) -> str:
    """Bind one line token to stable identity fields without exposing them."""
    number = _first_private_query_value(
        row,
        ("ip_number", "phone_number", "number"),
        _private_query_phone_number,
        max_length=_PRIVATE_QUERY_MAX_PHONE_LENGTH,
    )
    provider = _as_int(row.get("isp_selection"))
    provider_value = (
        provider
        if provider is not None and 0 <= provider <= _MAX_VOIP_PROVIDER_CODE
        else ""
    )
    return sha256(
        f"voip\x1f{line_id}\x1f{number or ''}\x1f{provider_value}".encode()
    ).hexdigest()


def _require_voip_line(
    payload: Mapping[str, Any],
    *,
    line_id: str,
) -> dict[str, Any]:
    """Return one exact VoIP line row by stable opaque ID."""
    rows = _voip_line_rows(payload)
    matches = [
        row
        for row in rows
        if _private_query_identifier(row.get("id", row.get("ipphonenumber_id")))
        == line_id
    ]
    if len(matches) != 1:
        raise SpeedportUnsupportedError("VoIP line target is missing or ambiguous")
    return matches[0]


def _require_voip_line_active(row: Mapping[str, Any]) -> bool:
    """Return one exact VoIP line state without retaining its number."""
    status = row.get("number_status")
    if status == "ok":
        return True
    if status == "inactive":
        return False
    raise SpeedportUnsupportedError("VoIP line state is unsupported")


def _project_dect_handset_disconnect_targets(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project exact handset identities with an opaque reference."""
    targets: list[dict[str, Any]] = []
    rows = _strict_dect_handset_rows(payload)
    for row in rows[:_PRIVATE_QUERY_MAX_DECT_TARGETS]:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _dect_handset_fingerprint(
                row,
                handset_id=target_id,
            ),
            "reference": target_id,
        }
        name = _first_private_query_value(
            row,
            ("dect_name", "name"),
            _private_query_text,
            max_length=64,
        )
        if name is not None:
            target["name"] = name
        targets.append(target)
    return {
        "targets": targets,
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_DECT_TARGETS,
    }


def _dect_repeater_fingerprint(_row: Mapping[str, Any], repeater_id: str) -> str:
    """Bind a repeater action token to exact stable row identity."""
    return sha256(f"dect-repeater\x1f{repeater_id}".encode()).hexdigest()


def _project_dect_repeater_disconnect_targets(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project exact repeater identities with an admin-visible opaque reference."""
    rows = _strict_dect_repeater_rows(payload)
    return {
        "targets": [
            {
                "target_id": (target_id := cast("str", row["id"])),
                "target_fingerprint": _dect_repeater_fingerprint(row, target_id),
                "reference": target_id,
            }
            for row in rows[:_PRIVATE_QUERY_MAX_DECT_TARGETS]
        ],
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_DECT_TARGETS,
    }


def _voip_provider_fingerprint(row: Mapping[str, Any], provider_id: str) -> str:
    """Bind a provider token without retaining credentials or telephone data."""
    provider_code = _bounded_integer(
        row.get("isp_selection"),
        minimum=0,
        maximum=_MAX_VOIP_PROVIDER_CODE,
    )
    code = provider_code if provider_code is not None else ""
    return sha256(f"voip-provider\x1f{provider_id}\x1f{code}".encode()).hexdigest()


def _project_voip_provider_delete_targets(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project exact provider targets without exposing credentials."""
    rows = _strict_voip_provider_rows(payload)
    targets: list[dict[str, Any]] = []
    for row in rows[:_PRIVATE_QUERY_MAX_VOIP_TARGETS]:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _voip_provider_fingerprint(row, target_id),
            "reference": target_id,
        }
        provider_code = _bounded_integer(
            row.get("isp_selection"),
            minimum=0,
            maximum=_MAX_VOIP_PROVIDER_CODE,
        )
        if provider_code is not None:
            target["provider_code"] = provider_code
        targets.append(target)
    return {
        "targets": targets,
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_VOIP_TARGETS,
    }


def _project_voip_line_delete_targets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project all exact VoIP number targets with only a masked suffix."""
    rows = _strict_voip_line_rows(payload)
    targets: list[dict[str, Any]] = []
    for row in rows[:_PRIVATE_QUERY_MAX_VOIP_TARGETS]:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _voip_line_fingerprint(
                row,
                line_id=target_id,
            ),
            "reference": target_id,
        }
        status = row.get("number_status")
        if status in {"ok", "inactive"}:
            target["active"] = status == "ok"
        number = _first_private_query_value(
            row,
            ("ip_number", "phone_number", "number"),
            _private_query_phone_number,
            max_length=_PRIVATE_QUERY_MAX_PHONE_LENGTH,
        )
        digits = "".join(character for character in number or "" if character.isdigit())
        if len(digits) > _MASKED_PHONE_SUFFIX_DIGITS:
            target["number_suffix"] = digits[-_MASKED_PHONE_SUFFIX_DIGITS:]
        targets.append(target)
    return {
        "targets": targets,
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_VOIP_TARGETS,
    }


def _ip_pbx_client_fingerprint(row: Mapping[str, Any], client_id: str) -> str:
    """Bind a PBX-client token to stable non-secret identity fields."""
    name = _first_private_query_value(
        row,
        ("ipclient_mdevice_name",),
        _private_query_text,
        max_length=64,
    )
    mac = _private_query_mac(row.get("ipclient_mdevice_mac"))
    return sha256(
        f"ip-pbx-client\x1f{client_id}\x1f{name or ''}\x1f{mac or ''}".encode()
    ).hexdigest()


def _project_ip_pbx_client_delete_targets(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Project exact PBX-client targets without credentials."""
    rows = _strict_ip_pbx_client_rows(payload)
    targets: list[dict[str, Any]] = []
    for row in rows[:_PRIVATE_QUERY_MAX_VOIP_TARGETS]:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _ip_pbx_client_fingerprint(row, target_id),
            "reference": target_id,
        }
        name = _first_private_query_value(
            row,
            ("ipclient_mdevice_name",),
            _private_query_text,
            max_length=64,
        )
        if name is not None:
            target["name"] = name
        status_code = _bounded_integer(
            row.get("ipclient_status"),
            minimum=0,
            maximum=2,
        )
        if status_code is not None:
            target["status"] = _IP_PBX_STATUS_VALUES[status_code]
        targets.append(target)
    return {
        "targets": targets,
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_VOIP_TARGETS,
    }


def _phonebook_entry_fingerprint(
    row: Mapping[str, Any],
    *,
    contact_id: str,
    phonebook_id: int,
) -> str:
    """Bind one contact token without returning its private fields."""
    values = [
        _first_private_query_value(
            row,
            (field,),
            (
                _private_query_phone_number
                if field.startswith("number")
                else _private_query_text
            ),
            max_length=_PRIVATE_QUERY_MAX_DISPLAY_NAME_LENGTH,
        )
        or ""
        for field in ("name", "vorname", "number_p", "number_a", "number_m", "number_n")
    ]
    fingerprint_value = "\x1f".join(
        ("phonebook-entry", str(phonebook_id), contact_id, *values)
    )
    return sha256(fingerprint_value.encode()).hexdigest()


def _project_phonebook_entry_delete_targets(
    payload: Mapping[str, Any],
    *,
    phonebook_id: int,
) -> dict[str, Any]:
    """Project exact contact targets from one complete phonebook response."""
    rows = _strict_phonebook_rows(payload)
    _require_complete_phonebook_result(payload, rows)
    targets: list[dict[str, Any]] = []
    # The strict phonebook reader already proves a bounded complete inventory.
    # A VoIP-device display cap must not hide otherwise valid contact targets.
    for row in rows:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _phonebook_entry_fingerprint(
                row,
                contact_id=target_id,
                phonebook_id=phonebook_id,
            ),
            "phonebook_id": phonebook_id,
            "reference": target_id,
        }
        name_parts = [
            value
            for value in (
                _first_private_query_value(
                    row,
                    ("vorname",),
                    _private_query_text,
                    max_length=32,
                ),
                _first_private_query_value(
                    row,
                    ("name",),
                    _private_query_text,
                    max_length=32,
                ),
            )
            if value is not None
        ]
        display_name = " ".join(name_parts)
        if 0 < len(display_name) <= _PRIVATE_QUERY_MAX_DISPLAY_NAME_LENGTH:
            target["display_name"] = display_name
        targets.append(target)
    return {
        "targets": targets,
        "truncated": False,
    }


def _nas_share_fingerprint(row: Mapping[str, Any], share_id: str) -> str:
    """Bind one NAS-share token without credentials."""
    name = _first_private_query_value(
        row,
        ("nas_folder_name", "nas_share_name", "share_name"),
        _private_query_text,
        max_length=64,
    )
    flags = tuple(
        _strict_router_boolean(row[field]) if field in row else None
        for field in ("nas_active", "nas_folder_nur_lesen", "nas_secure")
    )
    return sha256(
        f"nas-share\x1f{share_id}\x1f{name or ''}\x1f{flags!r}".encode()
    ).hexdigest()


def _project_nas_share_delete_targets(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project exact NAS-share targets without credentials."""
    rows = _strict_nas_share_rows(payload)
    targets: list[dict[str, Any]] = []
    for row in rows[:_PRIVATE_QUERY_MAX_VOIP_TARGETS]:
        target_id = cast("str", row["id"])
        target: dict[str, Any] = {
            "target_id": target_id,
            "target_fingerprint": _nas_share_fingerprint(row, target_id),
            "reference": target_id,
        }
        name = _first_private_query_value(
            row,
            ("nas_folder_name", "nas_share_name", "share_name"),
            _private_query_text,
            max_length=64,
        )
        if name is not None:
            target["name"] = name
        targets.append(target)
    return {
        "targets": targets,
        "truncated": len(rows) > _PRIVATE_QUERY_MAX_VOIP_TARGETS,
    }


def _require_phonebook_id(value: object) -> int:
    """Accept only the five firmware-supported local phonebook indexes."""
    if type(value) is not int or value not in _PHONEBOOK_IDS:
        raise SpeedportProtocolError("Phonebook ID is invalid")
    return value


def _require_phonebook_search_prefix(value: object) -> str:
    """Accept the exact all-contacts or single-letter firmware search form."""
    if not isinstance(value, str) or _PHONEBOOK_SEARCH_PREFIX.fullmatch(value) is None:
        raise SpeedportProtocolError("Phonebook search prefix is invalid")
    return value


def _project_ip_pbx_client(
    response: Mapping[str, Any],
    *,
    client_id: str,
) -> dict[str, Any]:
    """Project one PBX status row while discarding credentials and unknown fields."""
    rows = _private_query_rows(_mapping_value(response, "addipclient"))
    matches = [
        row for row in rows if _private_query_identifier(row.get("id")) == client_id
    ]
    if len(matches) != 1:
        raise SpeedportProtocolError("IP-PBX refresh returned no unique client row")

    row = matches[0]
    status_code = _bounded_integer(row.get("ipclient_status"), minimum=0, maximum=2)
    if status_code is None:
        raise SpeedportProtocolError("IP-PBX refresh returned an invalid status")
    result: dict[str, Any] = {
        "client_id": client_id,
        "status": _IP_PBX_STATUS_VALUES[status_code],
        "status_code": status_code,
    }
    name = _private_query_text(row.get("ipclient_mdevice_name"))
    if name is not None:
        result["name"] = name
    ipv4 = _private_query_ipv4(row.get("ipclient_mdevice_ipv4"))
    if ipv4 is not None:
        result["ipv4"] = ipv4
    mac = _private_query_mac(row.get("ipclient_mdevice_mac"))
    if mac is not None:
        result["mac"] = mac
    return result


def _project_phonebook_entries(
    response: Mapping[str, Any],
    *,
    phonebook_id: int,
    prefix: str,
) -> dict[str, Any]:
    """Project an allowlisted, bounded contact search result."""
    rows = _private_query_rows(
        _mapping_value(response, "addbookentry"),
        maximum_rows=_PRIVATE_PHONEBOOK_MAX_ROWS,
    )
    entries: list[dict[str, str]] = []
    for row in rows[:_PRIVATE_PHONEBOOK_MAX_ROWS]:
        contact_id = _private_query_identifier(row.get("id"))
        if contact_id is None:
            continue
        entry = {"contact_id": contact_id}
        for output, candidates, parser in (
            ("last_name", ("name",), _private_query_text),
            ("first_name", ("vorname",), _private_query_text),
            (
                "number",
                ("number:1", "number", "number_p"),
                _private_query_phone_number,
            ),
        ):
            value = _first_private_query_value(row, candidates, parser)
            if value is not None:
                entry[output] = value
        entries.append(entry)

    result: dict[str, Any] = {
        "phonebook_id": phonebook_id,
        "prefix": prefix,
        "entries": entries,
        "truncated": len(rows) > _PRIVATE_PHONEBOOK_MAX_ROWS,
    }
    total = _bounded_integer(
        _mapping_value(response, "num_entries"),
        minimum=0,
        maximum=1000,
    )
    if total is not None:
        result["total"] = total
    free_entries = _bounded_integer(
        _mapping_value(response, "free_entry_num"),
        minimum=0,
        maximum=1000,
    )
    if free_entries is not None:
        result["free_entries"] = free_entries
    return result


def _project_phonebook_contact(
    response: Mapping[str, Any],
    *,
    phonebook_id: int,
    contact_id: str,
) -> dict[str, Any]:
    """Project only reviewed contact fields and discard every unknown value."""
    row = _casefold_private_query_mapping(response)
    contact: dict[str, str] = {}
    for output, candidates, parser, max_length in (
        ("last_name", ("name",), _private_query_text, 256),
        ("first_name", ("vorname",), _private_query_text, 256),
        ("private_number", ("number_p",), _private_query_phone_number, 64),
        ("work_number", ("number_a",), _private_query_phone_number, 64),
        ("mobile_number", ("number_m",), _private_query_phone_number, 64),
        (
            "secondary_mobile_number",
            ("number_n",),
            _private_query_phone_number,
            64,
        ),
        ("street", ("strasse",), _private_query_text, 256),
        ("postal_code", ("plz",), _private_query_text, 32),
        ("city", ("ort",), _private_query_text, 256),
        ("birthday", ("geburtstag",), _private_query_birthday, 10),
    ):
        value = _first_private_query_value(
            row,
            candidates,
            parser,
            max_length=max_length,
        )
        if value is not None:
            contact[output] = value
    if not contact:
        raise SpeedportProtocolError("Phonebook contact response had no safe fields")
    return {
        "phonebook_id": phonebook_id,
        "contact_id": contact_id,
        "contact": contact,
    }


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Any:
    """Return one case-insensitive field only when its spelling is unambiguous."""
    matches = [
        value for raw_key, value in mapping.items() if str(raw_key).casefold() == key
    ]
    return matches[0] if len(matches) == 1 else None


def _private_query_rows(
    value: Any, *, maximum_rows: int = _PRIVATE_QUERY_MAX_ROWS
) -> tuple[dict[str, Any], ...]:
    """Expand only bounded mapping rows from a decoded template collection."""
    if isinstance(value, Mapping):
        sequence_columns = {
            str(key): tuple(items)
            for key, items in value.items()
            if isinstance(items, Sequence)
            and not isinstance(items, (str, bytes, bytearray))
        }
        if not sequence_columns:
            row = _casefold_private_query_mapping(value)
            return (row,) if row else ()
        lengths = {len(items) for items in sequence_columns.values()}
        if len(lengths) != 1:
            return ()
        scalar_columns = {
            str(key): item for key, item in value.items() if key not in sequence_columns
        }
        length = min(lengths.pop(), maximum_rows + 1)
        candidates: tuple[Mapping[Any, Any], ...] = tuple(
            {
                **scalar_columns,
                **{key: items[index] for key, items in sequence_columns.items()},
            }
            for index in range(length)
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = tuple(
            item for item in value[: maximum_rows + 1] if isinstance(item, Mapping)
        )
    else:
        return ()
    rows = tuple(_casefold_private_query_mapping(candidate) for candidate in candidates)
    return tuple(row for row in rows if row)


def _strict_private_query_rows(
    payload: Mapping[str, Any],
    collection: str,
    *,
    maximum_rows: int = _PRIVATE_QUERY_MAX_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Return one complete collection without dropping malformed rows."""
    value = _mapping_value(payload, collection)
    if value is None:
        raise SpeedportUnsupportedError(
            "Router target inventory is missing or ambiguous"
        )
    if isinstance(value, Mapping):
        sequence_columns = {
            str(key): tuple(items)
            for key, items in value.items()
            if isinstance(items, Sequence)
            and not isinstance(items, (str, bytes, bytearray))
        }
        if sequence_columns:
            lengths = {len(items) for items in sequence_columns.values()}
            if len(lengths) != 1:
                raise SpeedportUnsupportedError("Router target inventory is malformed")
            length = lengths.pop()
            if length > maximum_rows:
                raise SpeedportUnsupportedError("Router target inventory is truncated")
            scalar_columns = {
                str(key): item
                for key, item in value.items()
                if str(key) not in sequence_columns
            }
            candidates: tuple[Mapping[Any, Any], ...] = tuple(
                {
                    **scalar_columns,
                    **{key: items[index] for key, items in sequence_columns.items()},
                }
                for index in range(length)
            )
        else:
            candidates = (value,) if value else ()
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        if len(value) > maximum_rows or any(
            not isinstance(item, Mapping) for item in value
        ):
            raise SpeedportUnsupportedError("Router target inventory is truncated")
        candidates = tuple(cast("Mapping[Any, Any]", item) for item in value)
    else:
        raise SpeedportUnsupportedError("Router target inventory is malformed")

    rows = tuple(_casefold_private_query_mapping(candidate) for candidate in candidates)
    if any(not row for row in rows):
        raise SpeedportUnsupportedError("Router target inventory is malformed")
    return rows


def _strict_identified_rows(
    payload: Mapping[str, Any],
    collection: str,
    *,
    identifier_fields: tuple[str, ...] = ("id",),
    maximum_rows: int = _PRIVATE_QUERY_MAX_ROWS,
) -> tuple[dict[str, Any], ...]:
    """Return complete rows with unique canonical opaque IDs."""
    rows = _strict_private_query_rows(payload, collection, maximum_rows=maximum_rows)
    identified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        identifiers = {
            identifier
            for field in identifier_fields
            if (identifier := _private_query_identifier(row.get(field))) is not None
        }
        if len(identifiers) != 1:
            raise SpeedportUnsupportedError("Router target identity is ambiguous")
        identifier = identifiers.pop()
        if identifier in seen:
            raise SpeedportUnsupportedError("Router target identity is ambiguous")
        seen.add(identifier)
        identified.append({**row, "id": identifier})
    return tuple(identified)


def _strict_dect_handset_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    collections = [
        key
        for key in ("adddectdevice", "adddect")
        if _mapping_value(payload, key) is not None
    ]
    if len(collections) != 1:
        raise SpeedportUnsupportedError(
            "DECT handset inventory is missing or ambiguous"
        )
    return _strict_identified_rows(payload, collections[0])


def _strict_dect_repeater_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    return _strict_identified_rows(payload, "addrepeater")


def _strict_voip_provider_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    return _strict_identified_rows(payload, "addipphoneprovider")


def _strict_voip_line_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    return _strict_identified_rows(
        payload,
        "addipnumber",
        identifier_fields=("id", "ipphonenumber_id"),
    )


def _strict_ip_pbx_client_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    return _strict_identified_rows(payload, "addipclient")


def _strict_phonebook_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    # The real firmware omits addbookentry for an empty local book. Only its
    # complete successful zero-count response proves absence after deletion.
    collection_keys = [
        key for key in payload if str(key).strip().casefold() == "addbookentry"
    ]
    if (
        not collection_keys
        and _mapping_value(payload, "status") == "ok"
        and _bounded_integer(
            _mapping_value(payload, "num_entries"), minimum=0, maximum=0
        )
        == 0
        and _bounded_integer(
            _mapping_value(payload, "free_entry_num"), minimum=0, maximum=1000
        )
        is not None
    ):
        return ()
    return _strict_identified_rows(
        payload, "addbookentry", maximum_rows=_PRIVATE_PHONEBOOK_MAX_ROWS
    )


def _strict_nas_share_rows(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return complete NAS-share rows, including the firmware's flat form."""
    for collection in ("addnasfolder", "nas_folders", "nasfolder"):
        if _mapping_value(payload, collection) is not None:
            return _strict_identified_rows(
                payload,
                collection,
                identifier_fields=("sid", "id"),
            )
    row = _casefold_private_query_mapping(payload)
    raw_identifier = row.get("sid", row.get("id"))
    if (
        isinstance(raw_identifier, (str, int))
        and not isinstance(raw_identifier, bool)
        and str(raw_identifier).strip() == "-1"
    ):
        return ()
    identifier = _private_query_identifier(raw_identifier)
    if identifier is None:
        raise SpeedportUnsupportedError("NAS share inventory is missing or ambiguous")
    return ({**row, "id": identifier},)


def _target_membership(
    rows: tuple[dict[str, Any], ...],
    *,
    target_id: str,
    target_fingerprint: str,
    fingerprint: Callable[[Mapping[str, Any], str], str],
) -> bool:
    """Prove exact target presence or complete absence."""
    matches = [row for row in rows if row["id"] == target_id]
    if not matches:
        return False
    if len(matches) != 1 or fingerprint(matches[0], target_id) != target_fingerprint:
        raise SpeedportUnsupportedError("Administrator action target identity changed")
    return True


def _require_complete_phonebook_result(
    payload: Mapping[str, Any],
    rows: tuple[dict[str, Any], ...],
) -> None:
    """Require explicit proof that a phonebook response is untruncated."""
    total = _bounded_integer(
        _mapping_value(payload, "num_entries"),
        minimum=0,
        maximum=_PRIVATE_PHONEBOOK_MAX_ROWS,
    )
    if total is None or total != len(rows):
        raise SpeedportUnsupportedError("Phonebook target inventory is incomplete")


def _casefold_private_query_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    """Normalize field names while rejecting ambiguous duplicate spellings."""
    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        key = str(raw_key).strip().casefold()
        if not key or key in result:
            return {}
        result[key] = item
    return result


def _first_private_query_value(
    row: Mapping[str, Any],
    keys: Sequence[str],
    parser: _PrivateQueryParser,
    *,
    max_length: int = _PRIVATE_QUERY_MAX_TEXT_LENGTH,
) -> str | None:
    """Parse the first reviewed private field without exposing rejected values."""
    for key in keys:
        if key not in row:
            continue
        value = parser(row[key], max_length=max_length)
        if value is not None:
            return value
    return None


def _private_query_identifier(value: Any, *, max_length: int = 32) -> str | None:
    del max_length
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text if _PRIVATE_QUERY_ID.fullmatch(text) is not None else None


def _private_query_text(
    value: Any,
    *,
    max_length: int = _PRIVATE_QUERY_MAX_TEXT_LENGTH,
) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_length or not text.isprintable():
        return None
    return text


def _private_query_phone_number(value: Any, *, max_length: int = 64) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if (
        not text
        or len(text) > min(max_length, _PRIVATE_QUERY_MAX_PHONE_LENGTH)
        or _PHONEBOOK_NUMBER.fullmatch(text) is None
    ):
        return None
    return text


def _private_query_birthday(value: Any, *, max_length: int = 10) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) > max_length or _PHONEBOOK_BIRTHDAY.fullmatch(text) is None:
        return None
    return text or None


def _private_query_ipv4(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        address = ipaddress.IPv4Address(value.strip())
    except ipaddress.AddressValueError:
        return None
    return str(address)


def _private_query_mac(value: Any) -> str | None:
    if (
        not isinstance(value, str)
        or _OBSERVED_SCHEMA_MAC.fullmatch(value.strip()) is None
    ):
        return None
    return value.strip().upper().replace("-", ":")


def _bounded_integer(value: Any, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return None
    return parsed if minimum <= parsed <= maximum else None


def _mac_token(*, value: str | int | bool) -> str:
    """Compare MAC spellings without changing the preserved row value."""
    return "".join(
        character for character in str(value).casefold() if character.isalnum()
    )


def _normalize_host(host: str) -> tuple[str, bool, int | None]:
    value = host.strip().rstrip("/")
    if not value:
        msg = "Router host cannot be empty"
        raise ValueError(msg)
    if "://" not in value:
        return value.strip("[]"), False, None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        msg = "Router host must use http or https"
        raise ValueError(msg)
    return parsed.hostname, parsed.scheme == "https", parsed.port


def _base_url(scheme: str, host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    suffix = "" if port == default_port else f":{port}"
    return f"{scheme}://{rendered_host}{suffix}"


def _validate_endpoint(endpoint: str) -> str:
    path = endpoint.strip().lstrip("/")
    if not path or "://" in path or path.startswith("../") or "/../" in path:
        msg = "Invalid router-relative endpoint"
        raise ValueError(msg)
    return path


def _looks_like_login_page(text: str) -> bool:
    folded = text.casefold()
    return any(marker in folded for marker in _LOGIN_MARKERS)


def _decode_response(
    payload: str, challenge_key: bytes | None, *, preserve_compounds: bool = False
) -> dict[str, Any]:
    """Decode with the active challenge key, then the fixed public key."""
    if challenge_key is not None and is_encrypted_payload(payload):
        try:
            return decode_payload(
                payload,
                challenge_key,
                **({"preserve_compounds": True} if preserve_compounds else {}),
            )
        except SpeedportDecodeError:
            pass
    return decode_payload(
        payload,
        DEFAULT_KEY,
        **({"preserve_compounds": True} if preserve_compounds else {}),
    )


def _logout_response_rejected(data: Mapping[str, Any]) -> bool:
    """Return whether a decoded logout response explicitly reports failure."""
    for key in ("logout", "status", "result"):
        value = data.get(key)
        if (
            value is not None
            and str(value).strip().casefold() in _LOGOUT_REJECTED_STATES
        ):
            return True
    return any(
        key in data and data[key] not in (None, "", False, 0, (), [], {})
        for key in ("error", "errors")
    )


def _logout_response_confirmed(data: Mapping[str, Any]) -> bool:
    """Return whether a decoded logout response explicitly confirms release."""
    if _logout_response_rejected(data):
        return False
    for key in ("logout", "status", "result"):
        value = data.get(key)
        if type(value) is bool:
            if value:
                return True
            continue
        if type(value) is int:
            if value == 1:
                return True
            continue
        if (
            isinstance(value, str)
            and value.strip().casefold() in _LOGOUT_ACCEPTED_STATES
        ):
            return True
    return False


def _raise_login_gate(data: Mapping[str, Any]) -> None:
    """Classify router GUI ownership and login cooldown before credentials."""
    owner_value = str(data.get("login_other", "")).strip()
    other = owner_value.casefold()
    if other not in {"", "0", "false", "none", "null"}:
        owner = owner_value if other not in {"1", "true", "yes"} else None
        raise SpeedportSessionBusyError(
            "Another GUI session owns router access", owner=owner
        )

    locked = data.get("login_locked")
    locked_seconds = _as_int(locked)
    if (locked_seconds is not None and locked_seconds > 0) or _as_bool(locked) is True:
        raise SpeedportLoginLockedError(
            retry_after=(
                locked_seconds if locked_seconds and locked_seconds > 0 else None
            )
        )


def _failure_text(error: SpeedportError) -> str:
    return f"{type(error).__name__}: {error}"


def _has_capability_evidence(
    data: Mapping[str, Any], capability: EndpointCapability
) -> bool:
    if capability.family == "wps_status" and not data:
        # WPSStatus.json is an ephemeral transaction endpoint. An empty,
        # successfully decoded response is its firmware-defined idle shape.
        return True
    if not data:
        return False
    if capability.family == "receiver_led":
        try:
            _require_receiver_led_mode_value(data)
        except SpeedportUnsupportedError:
            return False
        return True
    exact_scalar = {
        "connection_privacy": ("lan_privacy_policy", _THREE_STATE_VALUES),
        "wps": ("use_wps", _BINARY_STATE_VALUES),
        "wps_status": ("wlan_wps_state", _WPS_STATE_VALUES),
    }.get(capability.family)
    if exact_scalar is not None:
        field, allowed_values = exact_scalar
        try:
            _require_guarded_scalar_value(
                data,
                field=field,
                allowed_values=allowed_values,
            )
        except SpeedportUnsupportedError:
            return False
        return True
    if capability.family == "dect_status":
        try:
            _require_dect_scan_active(data)
        except SpeedportUnsupportedError:
            return False
        return True
    strict_collections = {
        "dect": _strict_dect_handset_rows,
        "dect_repeater": _strict_dect_repeater_rows,
        "voip_lines": _strict_voip_line_rows,
        "voip_providers": _strict_voip_provider_rows,
        "pbx_clients": _strict_ip_pbx_client_rows,
        "phonebook": _strict_phonebook_rows,
        "nas_folders": _strict_nas_share_rows,
    }
    strict_collection = strict_collections.get(capability.family)
    if strict_collection is not None:
        try:
            rows = strict_collection(data)
            if capability.family == "phonebook":
                _require_complete_phonebook_result(data, rows)
        except SpeedportUnsupportedError:
            return False
        return True
    if not capability.evidence_keys:
        return True
    keys = tuple(_iter_mapping_keys(data))
    return any(
        evidence.casefold() in key
        for evidence in capability.evidence_keys
        for key in keys
    )


def _iter_mapping_keys(value: object) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key).casefold())
            keys.extend(_iter_mapping_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            keys.extend(_iter_mapping_keys(item))
    return tuple(keys)


def _describe_observed_schema(
    data: Mapping[Any, Any],
) -> tuple[tuple[str, str], ...]:
    """Describe bounded JSON structure while retaining no response values."""
    descriptors: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(path: str, value: object) -> bool:
        shape = _observed_schema_shape(value)
        if shape is None:
            return False
        descriptor = (path, shape)
        if descriptor not in seen:
            if len(descriptors) >= _OBSERVED_SCHEMA_MAX_FIELDS:
                return False
            descriptors.append(descriptor)
            seen.add(descriptor)
        return True

    def visit(value: object, path: str, depth: int) -> None:
        if len(descriptors) >= _OBSERVED_SCHEMA_MAX_FIELDS or not add(path, value):
            return
        if depth >= _OBSERVED_SCHEMA_MAX_DEPTH:
            return
        if isinstance(value, Mapping):
            for index, (raw_name, item) in enumerate(value.items()):
                if index >= _OBSERVED_SCHEMA_MAX_MAPPING_ITEMS:
                    return
                if not isinstance(raw_name, str):
                    continue
                safe_name = _safe_observed_schema_field_name(raw_name)
                if safe_name is None:
                    continue
                child_path = f"{path}.{safe_name}" if path else safe_name
                visit(item, child_path, depth + 1)
                if len(descriptors) >= _OBSERVED_SCHEMA_MAX_FIELDS:
                    return
            return
        if isinstance(value, list | tuple):
            item_path = f"{path}[]"
            for item in value[:_OBSERVED_SCHEMA_MAX_ARRAY_ITEMS]:
                visit(item, item_path, depth + 1)
                if len(descriptors) >= _OBSERVED_SCHEMA_MAX_FIELDS:
                    return

    for index, (raw_name, value) in enumerate(data.items()):
        if index >= _OBSERVED_SCHEMA_MAX_MAPPING_ITEMS:
            break
        if not isinstance(raw_name, str):
            continue
        safe_name = _safe_observed_schema_field_name(raw_name)
        if safe_name is None:
            continue
        visit(value, safe_name, 1)
        if len(descriptors) >= _OBSERVED_SCHEMA_MAX_FIELDS:
            break
    return tuple(descriptors)


def _safe_observed_candidate_metadata(
    family: str,
    candidate: EndpointCapability,
) -> tuple[str, str, bool, str | None] | None:
    """Accept only fixed local firmware paths that cannot contain identifiers."""
    safe_family = _safe_observed_schema_name(family)
    if safe_family != family:
        return None

    endpoint_match = _OBSERVED_SCHEMA_ENDPOINT.fullmatch(candidate.endpoint)
    if (
        endpoint_match is None
        or _safe_observed_schema_name(endpoint_match.group("name").casefold()) is None
    ):
        return None

    referer = candidate.referer
    if referer is not None:
        referer_match = _OBSERVED_SCHEMA_REFERER.fullmatch(referer)
        if referer_match is None or any(
            _safe_observed_schema_name(component) is None
            for component in referer_match.group("path").split("/")
        ):
            return None

    return safe_family, candidate.endpoint, candidate.authenticated, referer


def _safe_observed_schema_name(raw_name: str) -> str | None:
    """Keep only exact schema-like names; normalize array indexes and reject PII."""
    if (
        not raw_name
        or raw_name != raw_name.strip()
        or len(raw_name) > _OBSERVED_SCHEMA_MAX_NAME_LENGTH
        or raw_name != raw_name.casefold()
        or _OBSERVED_SCHEMA_EMAIL.fullmatch(raw_name)
        or _OBSERVED_SCHEMA_MAC.fullmatch(raw_name)
        or _OBSERVED_SCHEMA_SEPARATED_MAC.search(raw_name)
        or _OBSERVED_SCHEMA_COMPACT_IDENTIFIER.fullmatch(raw_name)
        or _OBSERVED_SCHEMA_IP_TOKENS.search(raw_name)
    ):
        return None
    try:
        ipaddress.ip_address(raw_name.strip("[]"))
    except ValueError:
        pass
    else:
        return None

    normalized = _OBSERVED_SCHEMA_ARRAY_INDEX.sub("[]", raw_name)
    number_check = normalized.replace("[]", "")
    tokens = frozenset(number_check.split("_"))
    if (
        _OBSERVED_SCHEMA_LONG_NUMBER.search(number_check)
        or _OBSERVED_SCHEMA_DYNAMIC_KEY.fullmatch(number_check)
        or tokens & _OBSERVED_SCHEMA_BLOCKED_TOKENS
        or not any(character.isalpha() for character in number_check)
        or not _OBSERVED_SCHEMA_SAFE_NAME.fullmatch(normalized)
    ):
        return None
    return normalized


def _safe_observed_schema_field_name(raw_name: str) -> str | None:
    """Retain only fixed, non-identifying firmware schema field names."""
    normalized = _safe_observed_schema_name(raw_name)
    if normalized is None:
        return None
    candidate = normalized.replace("[]", "")
    return normalized if candidate in _OBSERVED_SCHEMA_SAFE_FIELDS else None


def _observed_schema_shape(value: object) -> str | None:
    """Return only JSON shape metadata, never a scalar value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list | tuple):
        return "array"
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str | bytes | bytearray):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    folded = str(value).casefold()
    if folded in {"1", "true", "yes", "on", "enabled"}:
        return True
    if folded in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _parameter_text(values: Mapping[str, ParameterValue], key: str) -> str | None:
    parameter = values.get(key)
    if parameter is None:
        return None
    text = str(parameter.value).strip()
    return text or None


def _parameter_int(values: Mapping[str, ParameterValue], key: str) -> int | None:
    parameter = values.get(key)
    return None if parameter is None else _as_int(parameter.value)


def _parameter_scaled_int(
    values: Mapping[str, ParameterValue], key: str, multiplier: int
) -> int | None:
    value = _parameter_int(values, key)
    return None if value is None else value * multiplier


def _parameter_scaled_float(
    values: Mapping[str, ParameterValue], key: str, divisor: int
) -> float | None:
    value = _parameter_int(values, key)
    return None if value is None else value / divisor


def _make_dsl_metrics(
    values: Mapping[str, ParameterValue],
) -> DslMetrics:
    line = f"Device.DSL.Line.{_DSL_LINE_INDEX}"
    channel = f"Device.DSL.Channel.{_DSL_CHANNEL_INDEX}"
    return DslMetrics(
        line_index=_DSL_LINE_INDEX,
        channel_index=_DSL_CHANNEL_INDEX,
        status=_parameter_text(values, f"{channel}.Status"),
        downstream_current_bps=_parameter_scaled_int(
            values, _DSL_DOWNSTREAM_CURRENT_RATE, 1_000
        ),
        upstream_current_bps=_parameter_scaled_int(
            values, _DSL_UPSTREAM_CURRENT_RATE, 1_000
        ),
        downstream_max_bps=_parameter_scaled_int(
            values, f"{line}.DownstreamMaxBitRate", 1_000
        ),
        upstream_max_bps=_parameter_scaled_int(
            values, f"{line}.UpstreamMaxBitRate", 1_000
        ),
        downstream_noise_margin_db=_parameter_scaled_float(
            values, f"{line}.DownstreamNoiseMargin", 10
        ),
        upstream_noise_margin_db=_parameter_scaled_float(
            values, f"{line}.UpstreamNoiseMargin", 10
        ),
        downstream_attenuation_db=_parameter_scaled_float(
            values, f"{line}.DownstreamAttenuation", 10
        ),
        upstream_attenuation_db=_parameter_scaled_float(
            values, f"{line}.UpstreamAttenuation", 10
        ),
        sampled_at=datetime.now(UTC),
    )


def _make_interface(index: int, values: Mapping[str, ParameterValue]) -> WanInterface:
    enabled_parameter = values.get("Enable")
    return WanInterface(
        index=index,
        alias=_parameter_text(values, "Alias"),
        name=_parameter_text(values, "Name"),
        status=_parameter_text(values, "Status"),
        enabled=(
            _as_bool(enabled_parameter.value) if enabled_parameter is not None else None
        ),
        bytes_received=_parameter_int(values, "Stats.BytesReceived"),
        bytes_sent=_parameter_int(values, "Stats.BytesSent"),
        packets_received=_parameter_int(values, "Stats.PacketsReceived"),
        packets_sent=_parameter_int(values, "Stats.PacketsSent"),
        errors_received=_parameter_int(values, "Stats.ErrorsReceived"),
        errors_sent=_parameter_int(values, "Stats.ErrorsSent"),
        discard_packets_received=_parameter_int(values, "Stats.DiscardPacketsReceived"),
        discard_packets_sent=_parameter_int(values, "Stats.DiscardPacketsSent"),
    )


def _make_wan_counters(interface: WanInterface) -> WanCounters:
    received = interface.bytes_received
    sent = interface.bytes_sent
    if received is None or sent is None:
        raise SpeedportUnsupportedError(
            "Active WAN interface does not expose both byte counters"
        )
    return WanCounters(
        interface=interface,
        bytes_received=received,
        bytes_sent=sent,
        sampled_at=datetime.now(UTC),
        packets_received=interface.packets_received,
        packets_sent=interface.packets_sent,
        errors_received=interface.errors_received,
        errors_sent=interface.errors_sent,
        discard_packets_received=interface.discard_packets_received,
        discard_packets_sent=interface.discard_packets_sent,
    )
