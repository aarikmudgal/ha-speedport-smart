"""Protocol clients for Speedport Smart routers."""

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
from .client import DEFAULT_FEATURE_CANDIDATES, SpeedportClient
from .codec import (
    DEFAULT_KEY,
    DEFAULT_KEY_HEX,
    decode_payload,
    encode_payload,
    is_encrypted_payload,
    normalize_document,
)
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
from .totr64 import (
    SOAP_ACTION,
    build_get_parameter_values,
    parse_get_parameter_values,
)

__all__ = [
    "DEFAULT_FEATURE_CANDIDATES",
    "DEFAULT_KEY",
    "DEFAULT_KEY_HEX",
    "SOAP_ACTION",
    "CapabilityReport",
    "DslMetrics",
    "EndpointCapability",
    "ParameterValue",
    "RouterInfo",
    "RouterStatus",
    "SpeedportAuthenticationError",
    "SpeedportClient",
    "SpeedportConnectionError",
    "SpeedportDecodeError",
    "SpeedportError",
    "SpeedportInvalidCredentialsError",
    "SpeedportLoginLockedError",
    "SpeedportProtocolError",
    "SpeedportSessionBusyError",
    "SpeedportUnsupportedError",
    "WanCounters",
    "WanInterface",
    "build_get_parameter_values",
    "decode_payload",
    "encode_payload",
    "is_encrypted_payload",
    "normalize_document",
    "normalize_status",
    "parse_get_parameter_values",
    "select_active_wan_interface",
]
