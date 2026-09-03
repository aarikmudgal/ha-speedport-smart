"""Constants for Speedport Smart."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Final

DOMAIN: Final = "speedport_smart"
MANUFACTURER: Final = "Deutsche Telekom"

CONF_HOST: Final = "host"
CONF_PASSWORD: Final = "password"  # noqa: S105 - Home Assistant config key
CONF_USE_HTTPS: Final = "use_https"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_ENABLE_CONTROLS: Final = "enable_controls"
CONF_FAST_INTERVAL: Final = "fast_interval"
CONF_WAN_INTERVAL: Final = "wan_interval"
CONF_NORMAL_INTERVAL: Final = "normal_interval"
CONF_SLOW_INTERVAL: Final = "slow_interval"

DEFAULT_HOST: Final = "speedport.ip"
DEFAULT_HTTP_PORT: Final = 80
DEFAULT_HTTPS_PORT: Final = 443
DEFAULT_TR064_HTTP_PORT: Final = 5438
DEFAULT_TR064_HTTPS_PORT: Final = 8443

DEFAULT_FAST_INTERVAL: Final = timedelta(seconds=5)
DEFAULT_WAN_INTERVAL: Final = 0
DEFAULT_NORMAL_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_SLOW_INTERVAL: Final = timedelta(minutes=5)
RATE_WINDOW_SECONDS: Final = 5.0
DEVICE_NAME_MAX_LENGTH: Final = 28
DEVICE_NAME_PATTERN: Final = r"^[A-Za-z0-9-]{1,28}$"

PLATFORMS: Final[tuple[str, ...]] = (
    "binary_sensor",
    "button",
    "device_tracker",
    "select",
    "sensor",
    "switch",
    "text",
    "update",
)

MANAGED_DEVICE_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "addmdevice",
        "addmlandevice",
        "addmpriodevice",
        "addmwlandevice",
        "addmwlan5device",
    }
)

_MANAGED_DEVICE_FIELDS: Final = frozenset(
    {
        "mdevice_mac",
        "mdevice_use_dhcp",
        "mdevice_use_rule",
        "mdevice_originalip",
        "mdevice_ipv4",
        "mdevice_reservedip",
        "mdevice_type",
        "mdevice_wifi",
        "mdevice_connected",
        "mdevice_slave",
        "mdevice_downspeed",
        "mdevice_upspeed",
        "mdevice_rssi",
        "mdevice_hasui",
        "id",
        "mdevice_name",
        "mdevice_fix_dhcp",
    }
)
MANAGED_DEVICE_FORM_FIELDS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "addmdevice": _MANAGED_DEVICE_FIELDS,
        "addmlandevice": _MANAGED_DEVICE_FIELDS
        - frozenset({"mdevice_wifi", "mdevice_upspeed", "mdevice_rssi"}),
        "addmwlandevice": _MANAGED_DEVICE_FIELDS,
        "addmwlan5device": _MANAGED_DEVICE_FIELDS,
    }
)

# LTE.json returns these exact symbolic values on Smart 4R firmware, while the
# matching page submits the equivalent decimal strings when the mode changes.
RECEIVER_LED_MODE_CODES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "0": 0,
        "1": 1,
        "2": 2,
        "On": 0,
        "Timer": 1,
        "Off": 2,
    }
)

TR064_SOAP_ACTION: Final = (
    "urn:telekom-de:device:TO_InternetGatewayDevice:2#GetParameterValues"
)

REDACTED: Final = "**REDACTED**"
