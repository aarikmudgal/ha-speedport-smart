"""Tests for the privacy-safe read-only router validator."""

from __future__ import annotations

import asyncio
import json
from argparse import Namespace
from collections.abc import Mapping
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.speedport_smart.api import (
    SpeedportClient as RealSpeedportClient,
)
from custom_components.speedport_smart.api import SpeedportUnsupportedError
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
    RouterInfo,
    RouterStatus,
)
from scripts import validate_router


def test_observed_schema_serialization_detaches_immutable_snapshot() -> None:
    """Mapping proxies become JSON data without weakening the source snapshot."""
    schema = MappingProxyType(
        {"wifi": (MappingProxyType({"path": "wlan_active", "shape": "boolean"}),)}
    )

    serialized = validate_router._serialize_observed_feature_schema(schema)  # noqa: SLF001

    assert json.loads(json.dumps(serialized)) == {
        "wifi": [{"path": "wlan_active", "shape": "boolean"}]
    }
    serialized["wifi"][0]["path"] = "changed"
    assert schema["wifi"][0]["path"] == "wlan_active"


@pytest.mark.asyncio
async def test_validator_observes_cached_payload_without_extra_request_or_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One cached GET feeds every family while output remains structure-only."""
    endpoint = "data/SharedFeature.json"
    referer = "html/content/shared.html"
    feature_endpoints = MappingProxyType(
        {
            family: EndpointCapability(
                family,
                endpoint,
                authenticated=True,
                referer=referer,
            )
            for family in ("wifi", "wifi_access")
        }
    )
    report = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=feature_endpoints,
    )
    status = RouterStatus(info=RouterInfo(model="Speedport", firmware="test-firmware"))
    private_payload = {
        "wlan_active": True,
        "rows": [
            {
                "status": "PRIVATE-NEIGHBOUR",
                "hostname": "PRIVATE-HOST",
                "aa:bb:cc:dd:ee:ff": "PRIVATE-MAC",
            }
        ],
        "router_password": "PRIVATE-PASSWORD",
    }
    created_clients: list[_FakeValidatorClient] = []

    class _FakeValidatorClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            observer = RealSpeedportClient(MagicMock(), "speedport.ip")
            observer._selected_endpoints = dict(feature_endpoints)  # noqa: SLF001
            self._observer = observer
            self.setup = AsyncMock(return_value=report)
            self.get_status = AsyncMock(return_value=status)
            self.get_dsl_metrics = AsyncMock(
                side_effect=SpeedportUnsupportedError("unsupported")
            )
            self.get_json = AsyncMock(return_value=private_payload)
            self.close = AsyncMock()
            self.observe_calls: list[tuple[str, object]] = []
            created_clients.append(self)

        @property
        def observed_feature_schema(
            self,
        ) -> Mapping[str, tuple[Mapping[str, str], ...]]:
            return self._observer.observed_feature_schema

        def observe_feature_data(self, family: str, payload: object) -> None:
            self.observe_calls.append((family, payload))
            self._observer.observe_feature_data(family, payload)  # type: ignore[arg-type]

    class _FakeSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _FakeHub:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.capabilities: frozenset[str] = frozenset()
            self.data: dict[str, object] = {}

        async def async_setup(self) -> None:
            return None

        async def async_update_group(self, _group: object) -> None:
            return None

        def get(self, _path: str) -> None:
            return None

    monkeypatch.setattr(
        aiohttp,
        "TCPConnector",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        aiohttp,
        "CookieJar",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        aiohttp,
        "ClientSession",
        lambda **_kwargs: _FakeSession(),
    )
    monkeypatch.setattr(validate_router, "SpeedportClient", _FakeValidatorClient)
    monkeypatch.setattr(validate_router, "SpeedportHub", _FakeHub)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    result = await validate_router.async_validate_router(
        Namespace(
            authenticated=False,
            host="speedport.ip",
            https=False,
            interval=1.0,
            samples=2,
            verify_ssl=False,
        )
    )

    client = created_clients[0]
    client.get_json.assert_awaited_once_with(
        endpoint,
        authenticated=True,
        referer=referer,
    )
    assert [family for family, _payload in client.observe_calls] == [
        "wifi",
        "wifi_access",
    ]
    assert all(payload is private_payload for _family, payload in client.observe_calls)

    rendered = json.dumps(result, sort_keys=True)
    for private_value in (
        "PRIVATE-NEIGHBOUR",
        "PRIVATE-HOST",
        "PRIVATE-MAC",
        "PRIVATE-PASSWORD",
        "aa:bb:cc:dd:ee:ff",
        "hostname",
        "router_password",
    ):
        assert private_value not in rendered
    assert result["observed_feature_schema"] == {
        family: [
            {"path": "wlan_active", "shape": "boolean"},
            {"path": "rows", "shape": "array"},
            {"path": "rows[]", "shape": "object"},
            {"path": "rows[].status", "shape": "string"},
        ]
        for family in ("wifi", "wifi_access")
    }
