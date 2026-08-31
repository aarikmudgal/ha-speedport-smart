"""Tests for Telekom ToTR64 SOAP codec."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.api.exceptions import (
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.api.totr64 import (
    build_get_parameter_values,
    parse_get_parameter_values,
)


def _response(*structures: str) -> str:
    return (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        "<soap-env:Body><cwmp:GetParameterValuesResponse>"
        f"<cwmp:ParameterList>{''.join(structures)}</cwmp:ParameterList>"
        "</cwmp:GetParameterValuesResponse></soap-env:Body></soap-env:Envelope>"
    )


def _parameter(name: str, value: str, data_type: str) -> str:
    return (
        "<cwmp:ParameterValueStruct>"
        f"<cwmp:Name>{name}</cwmp:Name>"
        f'<cwmp:Value xsi:type="xsd:{data_type}">{value}</cwmp:Value>'
        "</cwmp:ParameterValueStruct>"
    )


def _fault(code: str, description: str) -> str:
    return (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0">'
        "<soap-env:Body><soap-env:Fault>"
        "<faultcode>Client</faultcode><faultstring>CWMP fault</faultstring>"
        f"<detail><cwmp:Fault><FaultCode>{code}</FaultCode>"
        f"<FaultString>{description}</FaultString></cwmp:Fault></detail>"
        "</soap-env:Fault></soap-env:Body></soap-env:Envelope>"
    )


def test_build_exact_get_parameter_values_shape() -> None:
    """Request uses tested Telekom action body and preserves list length."""
    body = build_get_parameter_values(
        (
            "Device.IP.Interface.5.Stats.BytesReceived",
            "Device.IP.Interface.5.Stats.BytesSent",
        )
    )
    assert "GetParameterValues" in body
    assert 'ParameterNames length="2"' in body
    assert "Device.IP.Interface.5.Stats.BytesReceived" in body


def test_parse_unsigned_long_and_boolean() -> None:
    """SOAP scalar types become typed values."""
    parsed = parse_get_parameter_values(
        _response(
            _parameter(
                "Device.IP.Interface.5.Stats.BytesReceived",
                "184467440737095",
                "unsignedLong",
            ),
            _parameter("Device.IP.Interface.5.Enable", "1", "boolean"),
        )
    )
    assert (
        parsed["Device.IP.Interface.5.Stats.BytesReceived"].value == 184_467_440_737_095
    )
    assert parsed["Device.IP.Interface.5.Enable"].value is True


def test_parse_busy_fault() -> None:
    """Router-specific 9801 fault becomes retryable session-busy error."""
    with pytest.raises(SpeedportSessionBusyError):
        parse_get_parameter_values(_fault("9801", "Session busy"))


def test_parse_unsupported_parameter_fault() -> None:
    """TR-069 invalid parameter fault maps to capability absence."""
    with pytest.raises(SpeedportUnsupportedError):
        parse_get_parameter_values(_fault("9005", "Invalid Parameter Name"))


def test_reject_malformed_or_empty_response() -> None:
    """Malformed and value-free XML never creates empty success."""
    with pytest.raises(SpeedportProtocolError):
        parse_get_parameter_values("<broken")
    with pytest.raises(SpeedportProtocolError):
        parse_get_parameter_values(_response())
