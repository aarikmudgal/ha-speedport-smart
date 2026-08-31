"""Serialized async client for Speedport JSON and Telekom ToTR64 protocols."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode, urlsplit

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Sequence

from ..models import (
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
from .codec import DEFAULT_KEY, decode_payload, encode_payload, is_encrypted_payload
from .exceptions import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
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


def _endpoint(
    family: str,
    path: str,
    *,
    authenticated: bool = False,
    referer: str | None = None,
    evidence_keys: tuple[str, ...] = (),
) -> EndpointCapability:
    return EndpointCapability(family, path, authenticated, referer, evidence_keys)


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
                    "data/WLANSettings.json",
                    authenticated=True,
                    referer="html/content/network/wlan_settings.html",
                    evidence_keys=("wlan", "wifi"),
                ),
            ),
            "lan": (
                _endpoint(
                    "lan",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=("device", "client", "host", "lan"),
                ),
                _endpoint(
                    "lan",
                    "data/LAN.json",
                    authenticated=True,
                    referer="html/content/network/lan.html",
                    evidence_keys=("lan", "dhcp", "subnet"),
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
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/home_network.html",
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
                    referer="html/content/internet/connection.html",
                    evidence_keys=("public_ip", "gateway", "dns", "ipv"),
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
                    referer="html/content/overview/index.html",
                    evidence_keys=("router", "firmware", "serial", "uptime"),
                ),
            ),
            "ip_phones": (
                _endpoint(
                    "ip_phones",
                    "data/IPPhoneHandler.json",
                    authenticated=True,
                    referer="html/content/phone/ip_phone.html",
                    evidence_keys=("ip_phone", "ipphone", "sip"),
                ),
            ),
            "wps": (
                _endpoint(
                    "wps",
                    "data/WPSStatus.json",
                    authenticated=True,
                    referer="html/content/network/wlan_wps.html",
                    evidence_keys=("wps",),
                ),
            ),
            "port_forwarding": (
                _endpoint(
                    "port_forwarding",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("internet_ports_active",),
                ),
                _endpoint(
                    "port_forwarding",
                    "data/PortuwMain.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("portuw", "forward", "mapping"),
                ),
            ),
            "mobile": (
                _endpoint(
                    "mobile",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("mobile", "lte", "5g", "ex5g", "webnwalk"),
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
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("lte", "ex5g_signal_lte", "webnwalk"),
                ),
                _endpoint(
                    "lte",
                    "data/WebnWalk.json",
                    authenticated=True,
                    referer="html/content/internet/webnwalk.html",
                    evidence_keys=("lte", "webnwalk"),
                ),
            ),
            "5g": (
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
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("receiver", "ex5g", "external_5g"),
                ),
            ),
            "mesh": (
                _endpoint(
                    "mesh",
                    "data/Mesh.json",
                    authenticated=True,
                    referer="html/content/network/mesh.html",
                    evidence_keys=("mesh",),
                ),
            ),
            "dhcp": (
                _endpoint(
                    "dhcp",
                    "data/DeviceList.json",
                    authenticated=True,
                    referer="html/content/network/devices.html",
                    evidence_keys=("dhcp", "lease", "reserved", "device"),
                ),
                _endpoint(
                    "dhcp",
                    "data/LAN.json",
                    authenticated=True,
                    referer="html/content/network/lan.html",
                    evidence_keys=("dhcp", "lease", "reserved"),
                ),
            ),
            "nat": (
                _endpoint(
                    "nat",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("internet_ports_active",),
                ),
                _endpoint(
                    "nat",
                    "data/PortuwMain.json",
                    authenticated=True,
                    referer="html/content/internet/portforwarding.html",
                    evidence_keys=("portuw", "forward", "mapping", "nat"),
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
            "ddns": (
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
                _endpoint(
                    "ddns",
                    "data/DynDNS.json",
                    authenticated=True,
                    referer="html/content/internet/dynamic_dns.html",
                    evidence_keys=("ddns", "dyndns", "dynamic_dns"),
                ),
                _endpoint(
                    "ddns",
                    "data/Router.json",
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
                _endpoint(
                    "vpn",
                    "data/VPN.json",
                    authenticated=True,
                    referer="html/content/internet/vpn.html",
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
                    "data/IPPhoneHandler.json",
                    authenticated=True,
                    referer="html/content/phone/ip_phone.html",
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
            "dect": (
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
            "analog": (
                _endpoint(
                    "analog",
                    "data/PhonePlugs.json",
                    authenticated=True,
                    referer="html/content/phone/phone_devices.html",
                    evidence_keys=("analog", "tae", "phone_plug", "phoneplug"),
                ),
            ),
            "phonebook": (
                _endpoint(
                    "phonebook",
                    "data/PhoneBook.json",
                    authenticated=True,
                    referer="html/content/phone/phonebook.html",
                    evidence_keys=("phonebook", "contact", "directory"),
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
            "usb": (
                _endpoint(
                    "usb",
                    "data/NASDevice.json",
                    authenticated=True,
                    referer="html/content/network/nas_device.html",
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
            "logs": (
                _endpoint(
                    "logs",
                    "data/SystemMessages.json",
                    authenticated=True,
                    referer="html/content/config/system_messages.html",
                    evidence_keys=("message", "log", "error", "warning"),
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
            "firmware": (
                _endpoint(
                    "firmware",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                    evidence_keys=("firmware", "update", "version"),
                ),
                _endpoint(
                    "firmware",
                    "data/FirmwareUpdate.json",
                    authenticated=True,
                    referer="html/content/config/check_for_updates.html",
                    evidence_keys=("firmware", "fwupd", "update", "version"),
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
        self._wan_interface: WanInterface | None = None
        self._wan_optional_counter_faults: set[int] = set()
        self._dsl_parameter_names: tuple[str, ...] | None = None
        self._last_management_error: (
            SpeedportSessionBusyError | SpeedportLoginLockedError | None
        ) = None

        scheme = "https" if self._use_https else "http"
        default_json_port = 443 if self._use_https else 80
        selected_json_port = json_port or detected_port or default_json_port
        self._base_url = _base_url(scheme, self._host, selected_json_port)
        tr064_port = tr064_https_port if self._use_https else tr064_http_port
        self._tr064_url = _base_url(scheme, self._host, tr064_port) + "/"

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
    ) -> SpeedportSessionBusyError | SpeedportLoginLockedError | None:
        """Return the latest typed management gate without logging owner details."""
        return self._last_management_error

    async def setup(
        self, *, allow_protected_degraded: bool = False
    ) -> CapabilityReport:
        """Verify public status and discover non-mutating capabilities."""
        await self.get_status()
        return await self.probe_capabilities(
            allow_protected_degraded=allow_protected_degraded
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
    ) -> dict[str, Any]:
        """Fetch one JSON endpoint through serialized session owner."""
        self._ensure_open()
        async with self._lock:
            had_authenticated_session = authenticated and self._authenticated
            try:
                return await self._get_json_unlocked(
                    endpoint,
                    authenticated=authenticated,
                    referer=referer,
                )
            except SpeedportAuthenticationError:
                if not had_authenticated_session:
                    raise
                self._invalidate_authentication()
                await self._login_unlocked()
                return await self._get_json_unlocked(
                    endpoint,
                    authenticated=True,
                    referer=referer,
                )

    async def post_json(
        self,
        endpoint: str,
        data: Mapping[str, str | int | bool],
        *,
        authenticated: bool = True,
        referer: str | None = None,
    ) -> dict[str, Any]:
        """Post to known router endpoint through same serialized owner."""
        self._ensure_open()
        async with self._lock:
            return await self._post_json_unlocked(
                endpoint,
                data,
                authenticated=authenticated,
                referer=referer,
            )

    async def reconnect(self) -> dict[str, Any]:
        """Request Internet reconnection through confirmed endpoint."""
        return await self.post_json(
            "data/Connect.json",
            {"req_connect": "reconnect"},
            referer="html/content/internet/con_ipdata.html",
        )

    async def execute_internet_reconnect(self) -> dict[str, Any]:
        """Compatibility name for Internet reconnection command."""
        return await self.reconnect()

    async def reboot(self) -> dict[str, Any]:
        """Request router reboot through confirmed endpoint."""
        return await self.post_json(
            "data/Reboot.json",
            {"reboot_device": "true"},
            referer="html/content/config/restart.html",
        )

    async def execute_router_reboot(self) -> dict[str, Any]:
        """Compatibility name for router reboot command."""
        return await self.reboot()

    async def wps(self) -> dict[str, Any]:
        """Start WPS through confirmed WLANAccess endpoint."""
        return await self.post_json(
            "data/WLANAccess.json",
            {"wlan_add": "on", "wps_key": "connect"},
            referer="html/content/network/wlan_wps.html",
        )

    async def execute_wps_start(self) -> dict[str, Any]:
        """Compatibility name for WPS command."""
        return await self.wps()

    async def execute_wifi_set_enabled(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed global Wi-Fi state field."""
        return await self.post_json(
            "data/Modules.json",
            {"use_wlan": "1" if enabled else "0"},
            referer="html/content/overview/index.html",
        )

    async def set_guest_wifi(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed guest Wi-Fi state field."""
        return await self.post_json(
            "data/Modules.json",
            {"wlan_guest_active": "1" if enabled else "0"},
            referer="html/content/overview/index.html",
        )

    async def execute_guest_wifi_set_enabled(self, *, enabled: bool) -> dict[str, Any]:
        """Compatibility name for guest Wi-Fi command."""
        return await self.set_guest_wifi(enabled=enabled)

    async def set_office_wifi(self, *, enabled: bool) -> dict[str, Any]:
        """Set confirmed office Wi-Fi state field."""
        return await self.post_json(
            "data/Modules.json",
            {"wlan_office_active": "1" if enabled else "0"},
            referer="html/content/overview/index.html",
        )

    async def set_port_forward_rule(
        self, *, rule_id: str, enabled: bool
    ) -> dict[str, Any]:
        """Toggle one existing PortuwMain rule by stable router ID."""
        return await self.post_json(
            "data/PortuwMain.json",
            {"id": rule_id, "portuw_active": "1" if enabled else "0"},
            referer="html/content/internet/portforwarding.html",
        )

    async def execute_port_mapping_set_enabled(
        self, *, rule_id: str, enabled: bool
    ) -> dict[str, Any]:
        """Compatibility name for existing port-rule toggle."""
        return await self.set_port_forward_rule(rule_id=rule_id, enabled=enabled)

    async def get_feature_data(self, family: str) -> dict[str, Any]:
        """Fetch previously confirmed semantic feature endpoint."""
        capability = self._selected_endpoints.get(family)
        if capability is None:
            msg = f"Router capability not confirmed: {family}"
            raise SpeedportUnsupportedError(msg)
        return await self.get_json(
            capability.endpoint,
            authenticated=capability.authenticated,
            referer=capability.referer,
        )

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

    async def get_wan_counters(self) -> WanCounters:
        """Read aggregate active WAN counters."""
        self._ensure_open()
        async with self._lock:
            await self._logout_unlocked()
            if self._wan_interface is not None:
                try:
                    return await self._read_wan_counters_unlocked(self._wan_interface)
                except SpeedportSessionBusyError:
                    raise
                except SpeedportProtocolError:
                    self._wan_interface = None
            interfaces = await self._discover_wan_interfaces_unlocked()
            try:
                interface = select_active_wan_interface(interfaces)
            except ValueError as exc:
                raise SpeedportUnsupportedError(str(exc)) from exc
            self._wan_interface = interface
            return await self._read_wan_counters_unlocked(interface)

    async def _read_wan_counters_unlocked(self, interface: WanInterface) -> WanCounters:
        prefix = f"Device.IP.Interface.{interface.index}.Stats"
        suffixes = (
            _WAN_BYTE_COUNTER_SUFFIXES
            if interface.index in self._wan_optional_counter_faults
            else _WAN_COUNTER_SUFFIXES
        )
        names = tuple(f"{prefix}.{suffix}" for suffix in suffixes)
        try:
            values = await self._get_parameter_values_unlocked(names)
        except SpeedportSessionBusyError:
            raise
        except SpeedportUnsupportedError:
            if interface.index in self._wan_optional_counter_faults:
                raise
            byte_names = tuple(
                f"{prefix}.{suffix}" for suffix in _WAN_BYTE_COUNTER_SUFFIXES
            )
            values = await self._get_parameter_values_unlocked(byte_names)
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
        self, *, allow_protected_degraded: bool = False
    ) -> CapabilityReport:
        """Probe only read endpoints and record independent failures."""
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
            for family, candidates in self._endpoint_candidates.items():
                if family in confirmed_endpoint_families:
                    continue
                phase_candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.authenticated is authenticated
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
                        except SpeedportUnsupportedError as exc:
                            endpoint_results[cache_key] = (None, exc)
                        else:
                            endpoint_results[cache_key] = (fetched_data, None)
                    endpoint_data, error = endpoint_results[cache_key]
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
                    authenticated_ok = True
                except (
                    SpeedportSessionBusyError,
                    SpeedportLoginLockedError,
                ) as exc:
                    failures["authentication"] = _failure_text(exc)
                    self._last_management_error = exc
                    if not allow_protected_degraded:
                        raise
                else:
                    self._last_management_error = None
                    await probe_endpoint_phase(authenticated=True)

            self._selected_endpoints = selected
            self._capabilities = CapabilityReport(
                status_json=status_ok,
                tr064=tr064_ok,
                wan_counters=counters_ok,
                authenticated_json=authenticated_ok,
                feature_endpoints=MappingProxyType(dict(selected)),
                failures=MappingProxyType(failures),
            )
            return self._capabilities
        finally:
            await self.logout()

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
        result = await self._post_json_unlocked(
            "data/Login.json",
            {"showpw": "0", "password": password_hash},
            authenticated=False,
            referer=None,
            ensure_auth=False,
        )
        try:
            _raise_login_gate(result)
        except (SpeedportSessionBusyError, SpeedportLoginLockedError) as err:
            self._last_management_error = err
            raise
        login_state = str(result.get("login", result.get("status", ""))).casefold()
        if login_state not in {"success", "ok", "true", "1"}:
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
    ) -> dict[str, Any]:
        if authenticated:
            await self._ensure_authenticated_unlocked()
        path = _validate_endpoint(endpoint)
        separator = "&" if "?" in path else "?"
        url = f"{self._base_url}/{path}{separator}_time={time.time_ns() // 1_000_000}"
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
            return _decode_response(text, self._login_key)
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
    ) -> dict[str, Any]:
        if authenticated and ensure_auth:
            await self._ensure_authenticated_unlocked()
        path = _validate_endpoint(endpoint)
        fields = dict(data)
        if referer:
            token = await self._get_http_token_unlocked(referer)
            if token:
                fields["httoken"] = token
        plain_body = urlencode(fields)
        key = self._login_key if authenticated else DEFAULT_KEY
        if authenticated and key is None:
            raise SpeedportAuthenticationError("Authenticated session has no key")
        body = (
            encode_payload(plain_body, key or DEFAULT_KEY)
            if self._encrypted_mode is not False
            else plain_body
        )
        headers = self._json_headers(referer)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        text = await self._request_text_unlocked(
            "POST", f"{self._base_url}/{path}", headers=headers, data=body
        )
        if _looks_like_login_page(text):
            self._invalidate_authentication()
            raise SpeedportAuthenticationError("Router session expired")
        try:
            return _decode_response(text, self._login_key)
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
        for pattern in _HTTP_TOKEN_PATTERNS:
            if match := pattern.search(text):
                return match.group(1)
        return None

    async def _ensure_authenticated_unlocked(self) -> None:
        if not self._authenticated:
            await self._login_unlocked()

    async def _logout_unlocked(self) -> None:
        """Release our web login while retaining credentials for later reuse."""
        if not self._authenticated:
            return
        try:
            primary_rejected = False
            try:
                result = await self._post_json_unlocked(
                    "data/Login.json",
                    {"logout": "byby"},
                    authenticated=True,
                    referer=_LOGOUT_REFERER,
                    ensure_auth=False,
                )
                primary_rejected = _logout_response_rejected(result)
            except SpeedportError:
                primary_rejected = True
            if primary_rejected:
                with suppress(SpeedportError):
                    await self._post_json_unlocked(
                        "data/Login.json",
                        {"logout": "byby"},
                        authenticated=False,
                        referer=None,
                        ensure_auth=False,
                    )
        finally:
            self._invalidate_authentication()
            await asyncio.sleep(_LOGOUT_SETTLE_SECONDS)

    async def _get_parameter_values_unlocked(
        self, names: Sequence[str]
    ) -> dict[str, ParameterValue]:
        body = build_get_parameter_values(names)
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
            "User-Agent": "Home Assistant Telekom Speedport Smart",
        }
        for attempt in range(self._max_busy_retries + 1):
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
                if attempt >= self._max_busy_retries:
                    raise
                await asyncio.sleep(self._busy_backoff * (2**attempt))
        raise SpeedportSessionBusyError("ToTR64 session remained busy")

    async def _discover_wan_interfaces_unlocked(self) -> tuple[WanInterface, ...]:
        parameters: dict[str, ParameterValue]
        interface_count: int | None = None
        try:
            count_values = await self._get_parameter_values_unlocked(
                ("Device.IP.InterfaceNumberOfEntries",)
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
                parameters = await self._get_parameter_values_unlocked(names)
            except SpeedportSessionBusyError:
                raise
            except SpeedportProtocolError:
                parameters = await self._discover_interface_parameters_unlocked()
        else:
            parameters = await self._discover_interface_parameters_unlocked()

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
    ) -> dict[str, ParameterValue]:
        """Scan standard interface aliases when secured count is unavailable."""
        try:
            return await self._get_parameter_values_unlocked(("Device.IP.Interface.",))
        except SpeedportSessionBusyError:
            raise
        except SpeedportProtocolError:
            pass

        parameters: dict[str, ParameterValue] = {}
        for index in range(1, _MAX_INTERFACE_SCAN + 1):
            prefix = f"Device.IP.Interface.{index}"
            alias_name = f"{prefix}.Alias"
            try:
                alias = await self._get_parameter_values_unlocked((alias_name,))
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
                parameters.update(await self._get_parameter_values_unlocked(names))
            except SpeedportSessionBusyError:
                raise
            except SpeedportProtocolError:
                fallback_names = tuple(
                    f"{prefix}.{suffix}" for suffix in detail_suffixes
                )
                try:
                    parameters.update(
                        await self._get_parameter_values_unlocked(fallback_names)
                    )
                    continue
                except SpeedportSessionBusyError:
                    raise
                except SpeedportProtocolError:
                    pass
                for name in fallback_names:
                    try:
                        parameters.update(
                            await self._get_parameter_values_unlocked((name,))
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
                text = await response.text(errors="replace")
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
        self._authenticated = False
        self._login_key = None

    def _ensure_open(self) -> None:
        if self._closed:
            raise SpeedportProtocolError("Speedport client is closed")


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


def _decode_response(payload: str, challenge_key: bytes | None) -> dict[str, Any]:
    """Decode with the active challenge key, then the fixed public key."""
    if challenge_key is not None and is_encrypted_payload(payload):
        try:
            return decode_payload(payload, challenge_key)
        except SpeedportDecodeError:
            pass
    return decode_payload(payload, DEFAULT_KEY)


def _logout_response_rejected(data: Mapping[str, Any]) -> bool:
    """Return whether a decoded logout response explicitly reports failure."""
    for key in ("logout", "status", "result"):
        value = data.get(key)
        if (
            value is not None
            and str(value).strip().casefold() in _LOGOUT_REJECTED_STATES
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
    if not data:
        return False
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
