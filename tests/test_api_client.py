"""Focused tests for serialized Speedport protocol client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Self

import pytest

from custom_components.speedport_smart.api import (
    EndpointCapability,
    SpeedportAuthenticationError,
    SpeedportClient,
    encode_payload,
)


@dataclass(slots=True)
class _FakeResponse:
    owner: _FakeSession
    body: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0

    async def __aenter__(self) -> Self:
        self.owner.active += 1
        self.owner.max_active = max(self.owner.max_active, self.owner.active)
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.owner.active -= 1

    async def text(self, *, errors: str) -> str:
        assert errors == "replace"
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.body


class _FakeSession:
    def __init__(self) -> None:
        self.responses: list[_FakeResponse] = []
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.active = 0
        self.max_active = 0

    def add(
        self,
        body: str,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0,
    ) -> None:
        self.responses.append(_FakeResponse(self, body, status, headers or {}, delay))

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def _soap_response(*parameters: tuple[str, str, str]) -> str:
    values = "".join(
        "<cwmp:ParameterValueStruct>"
        f"<cwmp:Name>{name}</cwmp:Name>"
        f'<cwmp:Value xsi:type="xsd:{data_type}">{value}</cwmp:Value>'
        "</cwmp:ParameterValueStruct>"
        for name, value, data_type in parameters
    )
    return (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        "<soap-env:Body><cwmp:GetParameterValuesResponse>"
        f"<cwmp:ParameterList>{values}</cwmp:ParameterList>"
        "</cwmp:GetParameterValuesResponse></soap-env:Body></soap-env:Envelope>"
    )


def _busy_fault() -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0"><s:Body><s:Fault>'
        "<faultcode>Client</faultcode><faultstring>CWMP fault</faultstring>"
        "<detail><cwmp:Fault><FaultCode>9801</FaultCode>"
        "<FaultString>Session busy</FaultString></cwmp:Fault></detail>"
        "</s:Fault></s:Body></s:Envelope>"
    )


def _unsupported_parameter_fault() -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0"><s:Body><s:Fault>'
        "<faultcode>Client</faultcode><faultstring>CWMP fault</faultstring>"
        "<detail><cwmp:Fault><FaultCode>9005</FaultCode>"
        "<FaultString>Invalid Parameter Name</FaultString>"
        "</cwmp:Fault></detail></s:Fault></s:Body></s:Envelope>"
    )


@pytest.mark.asyncio
async def test_all_router_requests_are_serialized() -> None:
    """Concurrent poll groups never overlap router requests."""
    session = _FakeSession()
    body = encode_payload('{"online_status":"online"}')
    session.add(body, delay=0.01)
    session.add(body, delay=0.01)
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    first, second = await asyncio.gather(client.get_status(), client.get_status())

    assert first.internet_state == "online"
    assert second.internet_state == "online"
    assert session.max_active == 1


@pytest.mark.asyncio
async def test_busy_fault_retries_with_same_serial_owner() -> None:
    """9801 SOAP fault retries without escaping request lock."""
    session = _FakeSession()
    session.add(_busy_fault(), status=500)
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "5", "unsignedInt"))
    )
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=1,
    )

    values = await client.get_parameter_values(("Device.IP.InterfaceNumberOfEntries",))

    assert values["Device.IP.InterfaceNumberOfEntries"].value == 5
    assert len(session.requests) == 2
    assert all(
        request[1] == "http://speedport.ip:5438/" for request in session.requests
    )


@pytest.mark.asyncio
async def test_dynamic_interface_discovery_selects_bonding() -> None:
    """Interface count drives enumeration and Hybrid aggregate selection."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "5", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.4.Alias", "TUNNEL_LTE", "string"),
            ("Device.IP.Interface.4.Name", "lte0", "string"),
            ("Device.IP.Interface.4.Status", "Up", "string"),
            ("Device.IP.Interface.4.Stats.BytesReceived", "400", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.BytesSent", "300", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.PacketsReceived", "40", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.PacketsSent", "30", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.4.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.4.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.4.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
            ("Device.IP.Interface.5.Alias", "BONDING", "string"),
            ("Device.IP.Interface.5.Name", "habond", "string"),
            ("Device.IP.Interface.5.Status", "Up", "string"),
            ("Device.IP.Interface.5.Stats.BytesReceived", "1000", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "900", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "90", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "2", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "3", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "4",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "5",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.5.Stats.BytesReceived", "1100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "950", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "110", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "95", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "3", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "4", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "5",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "6",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.5.Stats.BytesReceived", "1200", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "1000", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "120", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "4", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "5", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "6",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "7",
                "unsignedInt",
            ),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    counters = await client.get_wan_counters()

    assert counters.interface.alias == "BONDING"
    assert counters.bytes_received == 1_100
    assert counters.bytes_sent == 950
    assert counters.packets_received == 110
    assert counters.packets_sent == 95
    assert counters.errors_received == 3
    assert counters.errors_sent == 4
    assert counters.discard_packets_received == 5
    assert counters.discard_packets_sent == 6
    second_request_body = session.requests[1][2]["data"]
    assert "Device.IP.Interface.5.Stats.BytesReceived" in second_request_body
    assert "Device.IP.Interface.5.Stats.PacketsReceived" not in second_request_body
    counter_request_body = session.requests[2][2]["data"]
    assert "Device.IP.Interface.5.Stats.PacketsReceived" in counter_request_body
    assert "Device.IP.Interface.5.Stats.DiscardPacketsSent" in counter_request_body

    next_counters = await client.get_wan_counters()

    assert next_counters.bytes_received == 1_200
    assert next_counters.packets_received == 120
    assert next_counters.errors_sent == 5
    assert next_counters.discard_packets_sent == 7
    assert len(session.requests) == 4
    assert "InterfaceNumberOfEntries" not in session.requests[3][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[3][2]["data"]
    assert "Stats.DiscardPacketsSent" in session.requests[3][2]["data"]


@pytest.mark.asyncio
async def test_discovery_falls_back_when_optional_counters_fault() -> None:
    """Unsupported optional counters cannot hide usable WAN byte counters."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
        )
    )
    session.add(_unsupported_parameter_fault(), status=500)
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    counters = await client.get_wan_counters()

    assert counters.bytes_received == 100
    assert counters.bytes_sent == 50
    assert counters.packets_received is None
    assert len(session.requests) == 4
    assert "Stats.PacketsReceived" not in session.requests[1][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[2][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[3][2]["data"]
    assert "Stats.BytesReceived" in session.requests[3][2]["data"]


@pytest.mark.asyncio
async def test_cached_counter_poll_remembers_optional_counter_fault() -> None:
    """Fast poll retries bytes together, then skips unsupported optional names."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsSent", "5", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.1.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "110", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "55", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsReceived", "11", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsSent", "6", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.1.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
        )
    )
    session.add(_unsupported_parameter_fault(), status=500)
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "120", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "60", "unsignedLong"),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "140", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "70", "unsignedLong"),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    first = await client.get_wan_counters()
    second = await client.get_wan_counters()
    third = await client.get_wan_counters()

    assert first.packets_received == 11
    assert second.bytes_received == 120
    assert second.packets_received is None
    assert third.bytes_received == 140
    assert len(session.requests) == 6
    assert "Stats.PacketsReceived" in session.requests[2][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[3][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[4][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[5][2]["data"]
    assert session.requests[5][2]["data"].count("<xsd:string>") == 2


@pytest.mark.asyncio
async def test_modern_login_and_authenticated_decode() -> None:
    """Challenge hash opens session; challenge key decrypts secure data."""
    session = _FakeSession()
    challenge = "00" * 32
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"success"}'))
    session.add(encode_payload('{"secure":"value"}', challenge))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    result = await client.get_json("data/SecureStatus.json", authenticated=True)

    assert result == {"secure": "value"}
    assert client.is_authenticated
    assert session.requests[1][0] == "POST"
    assert session.requests[2][0] == "POST"


@pytest.mark.asyncio
async def test_rejected_login_raises_typed_error() -> None:
    """Wrong password cannot degrade into empty feature data."""
    session = _FakeSession()
    challenge = "11" * 32
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"failed"}'))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="wrong",  # noqa: S106
    )

    with pytest.raises(SpeedportAuthenticationError):
        await client.get_json("data/SecureStatus.json", authenticated=True)

    assert not client.is_authenticated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_body", "expected_families"),
    [
        ("{}", ("status",)),
        ('{"internet_state":"online"}', ("status", "internet")),
    ],
)
async def test_capability_requires_matching_nonempty_data(
    endpoint_body: str, expected_families: tuple[str, ...]
) -> None:
    """Reachable empty or unrelated endpoints never create entities."""
    session = _FakeSession()
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "5", "unsignedLong"),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "5", "unsignedLong"),
        )
    )
    session.add(endpoint_body)
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        endpoint_candidates={
            "internet": (
                EndpointCapability(
                    "internet",
                    "data/Test.json",
                    evidence_keys=("internet",),
                ),
            )
        },
    )
    await client.get_status()

    report = await client.probe_capabilities()

    assert tuple(report.feature_endpoints) == expected_families
