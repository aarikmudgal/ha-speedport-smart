"""Shared fixtures for Speedport Smart tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.models import (
    CapabilityReport,
    DslMetrics,
    EndpointCapability,
    RouterInfo,
    RouterStatus,
    WanCounters,
    WanInterface,
)

pytest_plugins = ("pytest_homeassistant_custom_component",)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Generator[None],
) -> None:
    """Enable loading custom integrations in every test."""


@pytest.fixture
def router_info() -> RouterInfo:
    """Return stable test router information."""
    return RouterInfo(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
        serial_number="SP4R-TEST-001",
        hardware_version="A",
    )


@pytest.fixture
def capability_report() -> CapabilityReport:
    """Return representative capability report."""
    return CapabilityReport(
        status_json=True,
        tr064=True,
        wan_counters=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "mesh": EndpointCapability(
                    "mesh", "data/Mesh.json", authenticated=True
                ),
            }
        ),
    )


@pytest.fixture
def router_status(router_info: RouterInfo) -> RouterStatus:
    """Return representative normalized router status."""
    return RouterStatus(
        info=router_info,
        internet_state="online",
        dsl_state="up",
        dsl_downstream_bps=204_413_000,
        dsl_upstream_bps=42_460_000,
        wan_download_capacity_bps=192_412_000,
        wan_upload_capacity_bps=39_967_000,
    )


@pytest.fixture
def wan_interface() -> WanInterface:
    """Return aggregate Hybrid WAN interface."""
    return WanInterface(
        index=5,
        alias="BONDING",
        name="habond",
        status="Up",
        enabled=True,
    )


@pytest.fixture
def wan_counters(wan_interface: WanInterface) -> WanCounters:
    """Return representative WAN counter sample."""
    return WanCounters(
        interface=wan_interface,
        bytes_received=10_000,
        bytes_sent=5_000,
        sampled_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_speedport_client(
    router_info: RouterInfo,
    capability_report: CapabilityReport,
    router_status: RouterStatus,
    wan_counters: WanCounters,
) -> MagicMock:
    """Return async protocol-client double."""
    client = MagicMock(spec=SpeedportClient)
    client.router_info = router_info
    client.capabilities = capability_report
    client.last_management_error = None
    client.setup = AsyncMock(return_value=capability_report)
    client.close = AsyncMock()
    client.logout = AsyncMock()
    client.get_json = AsyncMock(return_value={})
    client.get_status = AsyncMock(return_value=router_status)
    client.get_wan_counters = AsyncMock(return_value=wan_counters)
    client.get_dsl_metrics = AsyncMock(
        return_value=DslMetrics(
            line_index=1,
            channel_index=1,
            status="Up",
            downstream_current_bps=router_status.dsl_downstream_bps,
            upstream_current_bps=router_status.dsl_upstream_bps,
            downstream_max_bps=None,
            upstream_max_bps=None,
            downstream_noise_margin_db=None,
            upstream_noise_margin_db=None,
            downstream_attenuation_db=None,
            upstream_attenuation_db=None,
            sampled_at=datetime.now(UTC),
        )
    )
    client.get_feature_data = AsyncMock(return_value={})
    return client
