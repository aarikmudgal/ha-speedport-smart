"""Tests for typed Speedport protocol models."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.models import (
    WanInterface,
    normalize_status,
    select_active_wan_interface,
)


def test_normalize_public_status() -> None:
    """Known Smart 4R public fields normalize with explicit units."""
    status = normalize_status(
        {
            "device_name": "Speedport Smart 4R Typ A",
            "firmware_version": "010152.5.0.001.0",
            "online_status": "online",
            "dsl_link_status": "online",
            "dsl_downstream": "204413000",
            "dsl_upstream": 42460000,
            "inet_download": "192412000",
            "inet_upload": "39967000",
        }
    )
    assert status.info.model == "Speedport Smart 4R Typ A"
    assert status.info.firmware == "010152.5.0.001.0"
    assert status.dsl_downstream_bps == 204_413_000
    assert status.dsl_upstream_bps == 42_460_000
    assert status.wan_download_capacity_bps == 192_412_000
    assert status.wan_upload_capacity_bps == 39_967_000


def test_select_bonding_over_lte_subset() -> None:
    """Aggregate Hybrid interface wins, preventing LTE double count."""
    interfaces = [
        WanInterface(
            4,
            alias="TUNNEL_LTE",
            name="lte0",
            status="Up",
            bytes_received=900,
            bytes_sent=800,
        ),
        WanInterface(
            5,
            alias="BONDING",
            name="habond",
            status="Up",
            bytes_received=1_000,
            bytes_sent=950,
        ),
    ]
    selected = select_active_wan_interface(interfaces)
    assert selected.index == 5
    assert selected.is_aggregate


def test_select_active_wan_fallback() -> None:
    """Non-Hybrid routers choose active WAN-like counter interface."""
    interfaces = [
        WanInterface(
            1,
            alias="LAN",
            status="Up",
            bytes_received=10,
            bytes_sent=10,
        ),
        WanInterface(
            2,
            alias="WAN",
            status="Up",
            bytes_received=20,
            bytes_sent=20,
        ),
    ]
    assert select_active_wan_interface(interfaces).index == 2


def test_select_requires_complete_counters() -> None:
    """Partial counter interfaces cannot produce fabricated totals."""
    with pytest.raises(ValueError, match="both WAN byte counters"):
        select_active_wan_interface(
            [WanInterface(1, alias="WAN", status="Up", bytes_received=1)]
        )
