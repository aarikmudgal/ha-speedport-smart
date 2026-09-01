"""Tests for the GET-only UPnP/TR-064 descriptor discovery utility."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

import pytest

from scripts.discover_service_descriptors import (
    AiohttpDocumentFetcher,
    DiscoveryError,
    FetchResult,
    _DocumentError,
    _parse_xml,
    discover_service_descriptors,
)

ROOT_URL = "http://router.test:49000/tr64desc.xml"

ROOT_XML = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <friendlyName>Private router name</friendlyName>
    <serialNumber>PRIVATE-SERIAL</serialNumber>
    <serviceList>
      <service>
        <serviceType>urn:dslforum-org:service:DeviceInfo:1</serviceType>
        <serviceId>urn:dslforum-org:serviceId:DeviceInfo1</serviceId>
        <SCPDURL>/deviceinfoSCPD.xml</SCPDURL>
        <controlURL>/upnp/control/deviceinfo</controlURL>
        <eventSubURL>/upnp/event/deviceinfo</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>
"""

SCPD_XML = b"""<?xml version="1.0"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <actionList>
    <action>
      <name>GetInfo</name>
      <argumentList>
        <argument>
          <name>NewStatus</name>
          <direction>out</direction>
          <relatedStateVariable>Status</relatedStateVariable>
        </argument>
      </argumentList>
    </action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="yes">
      <name>Status</name>
      <dataType>string</dataType>
      <allowedValueList>
        <allowedValue>Down</allowedValue>
        <allowedValue>Up</allowedValue>
      </allowedValueList>
      <allowedValueRange>
        <minimum>0</minimum>
        <maximum>1</maximum>
        <step>1</step>
      </allowedValueRange>
    </stateVariable>
  </serviceStateTable>
</scpd>
"""


@dataclass
class _FakeFetcher:
    responses: dict[str, FetchResult | _DocumentError]
    gets: list[str] = field(default_factory=list)

    async def get(self, url: str) -> FetchResult:
        self.gets.append(url)
        response = self.responses[url]
        if isinstance(response, _DocumentError):
            raise response
        return response


class _RedirectResponse:
    """Small async response double that must fail before body access."""

    status = 302

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


@dataclass
class _GetOnlySession:
    """Session double exposing only the method the utility may use."""

    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def get(self, url: str, **kwargs: object) -> _RedirectResponse:
        self.calls.append((url, kwargs))
        return _RedirectResponse()


async def test_discovers_only_sanitized_advertised_contracts() -> None:
    """Only advertised schema survives; router identity and origin do not."""
    fetcher = _FakeFetcher(
        {
            ROOT_URL: FetchResult(ROOT_XML, 200),
            "http://router.test:49000/deviceinfoSCPD.xml": FetchResult(
                SCPD_XML,
                200,
            ),
        }
    )

    result = await discover_service_descriptors(
        "router.test",
        fetcher=fetcher,
        root_urls=[ROOT_URL],
    )

    assert fetcher.gets == [
        ROOT_URL,
        "http://router.test:49000/deviceinfoSCPD.xml",
    ]
    assert result["format_version"] == 1
    assert result["advertised_only"] is True
    assert result["errors"] == []
    assert result["roots"] == [
        {
            "path": "/tr64desc.xml",
            "port": 49000,
            "scheme": "http",
            "response_sha256": (
                "e9b350baf10f4ff98eae29f8d9d0ad2c7e2921935c041e23f624584de1d6d14f"
            ),
            "response_status": 200,
            "service_count": 1,
        }
    ]
    service = result["services"][0]
    assert service["advertised_only"] is True
    assert service["service_type"] == "urn:dslforum-org:service:DeviceInfo:1"
    assert service["service_id"] == "urn:dslforum-org:serviceId:DeviceInfo1"
    assert service["scpd_path"] == "/deviceinfoSCPD.xml"
    assert service["control_path"] == "/upnp/control/deviceinfo"
    assert service["event_path"] == "/upnp/event/deviceinfo"
    assert service["actions"] == [
        {
            "arguments": [
                {
                    "direction": "out",
                    "name": "NewStatus",
                    "related_state_variable": "Status",
                }
            ],
            "name": "GetInfo",
        }
    ]
    assert service["state_variables"] == [
        {
            "allowed_values": ["Down", "Up"],
            "data_type": "string",
            "evented": True,
            "name": "Status",
            "range": {"maximum": "1", "minimum": "0", "step": "1"},
        }
    ]
    serialized = str(result)
    assert "router.test" not in serialized
    assert "Private router name" not in serialized
    assert "PRIVATE-SERIAL" not in serialized


async def test_rejects_off_host_root_before_any_request() -> None:
    """An off-host root is rejected without reaching the transport."""
    fetcher = _FakeFetcher({})

    with pytest.raises(DiscoveryError, match="same-host"):
        await discover_service_descriptors(
            "router.test",
            fetcher=fetcher,
            root_urls=["http://elsewhere.test:49000/tr64desc.xml"],
        )

    assert fetcher.gets == []


async def test_aiohttp_transport_uses_get_and_never_follows_redirects() -> None:
    """The concrete transport exposes GET and rejects redirects in place."""
    session = _GetOnlySession()
    fetcher = AiohttpDocumentFetcher(session, verify_ssl=True)  # type: ignore[arg-type]

    with pytest.raises(_DocumentError, match="redirect_rejected"):
        await fetcher.get(ROOT_URL)

    assert session.calls == [
        (ROOT_URL, {"allow_redirects": False, "ssl": True}),
    ]


async def test_off_origin_scpd_is_reported_without_fetching_it() -> None:
    """An advertised off-origin SCPD is omitted and never requested."""
    root = ROOT_XML.replace(
        b"/deviceinfoSCPD.xml",
        b"http://elsewhere.test:49000/deviceinfoSCPD.xml",
    )
    fetcher = _FakeFetcher({ROOT_URL: FetchResult(root, 200)})

    result = await discover_service_descriptors(
        "router.test",
        fetcher=fetcher,
        root_urls=[ROOT_URL],
    )

    assert fetcher.gets == [ROOT_URL]
    assert result["services"] == []
    assert result["errors"] == [
        {
            "path": "/deviceinfoSCPD.xml",
            "reason": "unsafe_url",
            "stage": "advertisement",
        }
    ]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            b'<!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root>&xxe;</root>',
            "xml_entity_or_doctype_rejected",
        ),
        (
            (b"<a>" * 33) + (b"</a>" * 33),
            "xml_depth_exceeded",
        ),
        (b"\xff\xfe<\x00r\x00o\x00o\x00t\x00/\x00>", "unsupported_xml_encoding"),
        (b"x" * (512 * 1024 + 1), "response_too_large"),
    ],
)
async def test_unsafe_or_unbounded_root_fails_closed(body: bytes, reason: str) -> None:
    """Entities, deep trees, and oversized bodies cannot become evidence."""
    fetcher = _FakeFetcher({ROOT_URL: FetchResult(body, 200)})

    with pytest.raises(DiscoveryError, match="No safe root"):
        await discover_service_descriptors(
            "router.test",
            fetcher=fetcher,
            root_urls=[ROOT_URL],
        )

    assert fetcher.gets == [ROOT_URL]
    if reason != "response_too_large":
        with pytest.raises(_DocumentError, match=reason):
            _parse_xml(body)


async def test_partial_scpd_failure_is_sanitized_and_root_still_succeeds() -> None:
    """A failed SCPD keeps root evidence and emits only a sanitized error."""
    fetcher = _FakeFetcher(
        {
            ROOT_URL: FetchResult(ROOT_XML, 200),
            "http://router.test:49000/deviceinfoSCPD.xml": _DocumentError(
                "redirect_rejected",
                status=302,
            ),
        }
    )

    result = await discover_service_descriptors(
        "router.test",
        fetcher=fetcher,
        root_urls=[ROOT_URL],
    )

    assert result["errors"] == [
        {
            "path": "/deviceinfoSCPD.xml",
            "reason": "redirect_rejected",
            "response_status": 302,
            "stage": "scpd",
        }
    ]
    assert result["services"][0]["actions"] == []
    assert result["services"][0]["response_sha256"] is None
    assert result["services"][0]["response_status"] == 302
    assert result["services"][0]["state_variables"] == []


async def test_non_successful_status_from_fetcher_fails_closed() -> None:
    """A transport implementation cannot smuggle a non-success response."""
    fetcher = _FakeFetcher({ROOT_URL: FetchResult(b"not found", 404)})

    with pytest.raises(DiscoveryError, match="No safe root"):
        await discover_service_descriptors(
            "router.test",
            fetcher=fetcher,
            root_urls=[ROOT_URL],
        )


async def test_output_is_deterministic_when_root_input_order_changes() -> None:
    """Input order cannot alter the sanitized report."""
    second_url = "https://router.test:8443/tr64desc.xml"
    second_root = ROOT_XML.replace(
        b"/deviceinfoSCPD.xml",
        b"/secondSCPD.xml",
    )
    responses = {
        ROOT_URL: FetchResult(ROOT_XML, 200),
        "http://router.test:49000/deviceinfoSCPD.xml": FetchResult(SCPD_XML, 200),
        second_url: FetchResult(second_root, 200),
        "https://router.test:8443/secondSCPD.xml": FetchResult(SCPD_XML, 200),
    }

    first = await discover_service_descriptors(
        "router.test",
        fetcher=_FakeFetcher(responses),
        root_urls=[second_url, ROOT_URL],
    )
    second = await discover_service_descriptors(
        "router.test",
        fetcher=_FakeFetcher(responses),
        root_urls=[ROOT_URL, second_url],
    )

    assert first == second
