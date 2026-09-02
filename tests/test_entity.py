"""Tests for shared Speedport entity helpers."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.coordinator import (
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.entity import SpeedportDevice, SpeedportEntity
from custom_components.speedport_smart.hub import SpeedportHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_router_and_child_device_metadata(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Entity IDs and device links use stable router and child identifiers."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.SLOW, timedelta(minutes=5)
    )

    router_entity = SpeedportEntity(
        hub,
        coordinator,
        "firmware",
        data_path="router.firmware",
    )
    assert router_entity.available
    assert router_entity.unique_id == "SP4R-TEST-001_firmware"
    assert router_entity.value == "010152.5.0.001.0"
    assert router_entity.device_info["identifiers"] == {(DOMAIN, "SP4R-TEST-001")}
    assert router_entity.device_info["configuration_url"] == "http://speedport.ip"
    assert router_entity.group_snapshot is None

    child = SpeedportDevice(
        identifier="node-serial",
        kind="mesh",
        name="Speed Home WLAN",
        model="Speed Home WLAN",
    )
    child_entity = SpeedportEntity(
        hub,
        coordinator,
        "status",
        device=child,
    )
    assert child_entity.available
    assert child_entity.unique_id == "SP4R-TEST-001_mesh_node-serial_status"
    assert child_entity.device_info["via_device"] == (
        DOMAIN,
        "SP4R-TEST-001",
    )
    assert "configuration_url" not in child_entity.device_info
    assert not SpeedportEntity(
        hub,
        coordinator,
        "missing",
        data_path="does.not.exist",
    ).available
