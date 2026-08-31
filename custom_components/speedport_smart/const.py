"""Constants for Speedport Smart."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "speedport_smart"
MANUFACTURER: Final = "Deutsche Telekom"

CONF_HOST: Final = "host"
CONF_PASSWORD: Final = "password"  # noqa: S105 - Home Assistant config key
CONF_USE_HTTPS: Final = "use_https"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_ENABLE_CONTROLS: Final = "enable_controls"
CONF_FAST_INTERVAL: Final = "fast_interval"
CONF_NORMAL_INTERVAL: Final = "normal_interval"
CONF_SLOW_INTERVAL: Final = "slow_interval"

DEFAULT_HOST: Final = "speedport.ip"
DEFAULT_HTTP_PORT: Final = 80
DEFAULT_HTTPS_PORT: Final = 443
DEFAULT_TR064_HTTP_PORT: Final = 5438
DEFAULT_TR064_HTTPS_PORT: Final = 8443

DEFAULT_FAST_INTERVAL: Final = timedelta(seconds=5)
DEFAULT_NORMAL_INTERVAL: Final = timedelta(seconds=30)
DEFAULT_SLOW_INTERVAL: Final = timedelta(minutes=5)
RATE_WINDOW_SECONDS: Final = 10.0

PLATFORMS: Final[tuple[str, ...]] = (
    "binary_sensor",
    "button",
    "device_tracker",
    "sensor",
    "switch",
    "update",
)

TR064_SOAP_ACTION: Final = (
    "urn:telekom-de:device:TO_InternetGatewayDevice:2#GetParameterValues"
)

REDACTED: Final = "**REDACTED**"
