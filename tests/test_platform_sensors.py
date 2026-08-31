"""Tests for capability-gated Speedport sensors."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import UnitOfInformation

from custom_components.speedport_smart.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    SpeedportBinarySensor,
)
from custom_components.speedport_smart.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.speedport_smart.coordinator import (
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.sensor import (
    SENSOR_DESCRIPTIONS,
    SpeedportManagementAccessSensor,
    SpeedportSensor,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from custom_components.speedport_smart.sensor import (
    async_setup_entry as async_setup_sensors,
)


def _description(descriptions: tuple[Any, ...], key: str) -> Any:
    return next(description for description in descriptions if description.key == key)


def _attach_coordinators(hass: HomeAssistant, hub: SpeedportHub) -> None:
    for group, interval in (
        (PollGroup.FAST, timedelta(seconds=5)),
        (PollGroup.NORMAL, timedelta(seconds=30)),
        (PollGroup.SLOW, timedelta(minutes=5)),
    ):
        hub.attach_coordinator(
            group,
            SpeedportDataUpdateCoordinator(hass, hub, group, interval),
        )


async def test_wan_sensor_values_and_reset_semantics(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """WAN totals become decimal GB while rates become Mbit/s."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "wan": {
                "bytes_received": 12_345,
                "bytes_sent": 6_789,
                "download_rate_bps": 80_000_000,
                "upload_rate_bps": 12_345_678,
                "download_utilization": 41.6,
            }
        }
    )
    received = SpeedportSensor(
        hub, _description(SENSOR_DESCRIPTIONS, "wan_bytes_received")
    )
    rate = SpeedportSensor(hub, _description(SENSOR_DESCRIPTIONS, "wan_download_rate"))
    utilization = SpeedportSensor(
        hub, _description(SENSOR_DESCRIPTIONS, "wan_download_utilization")
    )
    assert received.native_value == 0.000012
    assert (
        received.entity_description.native_unit_of_measurement
        is UnitOfInformation.GIGABYTES
    )
    assert received.entity_description.state_class is SensorStateClass.TOTAL_INCREASING
    assert rate.native_value == 80
    assert utilization.native_value == 41.6


async def test_setup_adds_only_exposed_paths(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Capability alone never creates placeholder entities."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "wan": {"bytes_received": 100, "bytes_sent": 50},
            "internet": {"state": "online"},
            "dsl": {"state": "up"},
        }
    )
    hub._capabilities = hub.capabilities | {"internet", "dsl"}  # noqa: SLF001
    entry = MagicMock()
    entry.runtime_data = hub
    sensors: list[SpeedportSensor] = []
    binary_sensors: list[SpeedportBinarySensor] = []

    await async_setup_sensors(hass, entry, sensors.extend)
    await async_setup_binary_sensors(hass, entry, binary_sensors.extend)

    fixed_sensors = [
        entity for entity in sensors if isinstance(entity, SpeedportSensor)
    ]
    assert {entity.entity_description.key for entity in fixed_sensors} == {
        "wan_bytes_received",
        "wan_bytes_sent",
    }
    management = [
        entity
        for entity in sensors
        if isinstance(entity, SpeedportManagementAccessSensor)
    ]
    assert len(management) == 1
    assert management[0].native_value == "available"
    assert {entity.entity_description.key for entity in binary_sensors} == {
        "internet_connected",
        "dsl_connected",
    }
    assert all(entity.is_on for entity in binary_sensors)
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_description_catalog_is_complete_and_entities_default_enabled(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Catalog covers every family and fixed entities default to enabled."""
    sensor_keys = [description.key for description in SENSOR_DESCRIPTIONS]
    binary_keys = [description.key for description in BINARY_SENSOR_DESCRIPTIONS]
    assert len(sensor_keys) == len(set(sensor_keys))
    assert len(binary_keys) == len(set(binary_keys))
    capabilities = {
        description.capability
        for description in (*SENSOR_DESCRIPTIONS, *BINARY_SENSOR_DESCRIPTIONS)
    }
    assert {
        "internet",
        "wan",
        "dsl",
        "hybrid",
        "mobile",
        "wifi",
        "mesh",
        "lan",
        "dhcp",
        "clients",
        "nat",
        "ddns",
        "vpn",
        "parental",
        "telephony",
        "pbx",
        "dect",
        "security",
        "usb",
        "system",
        "diagnostics",
    } <= capabilities
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    assert all(
        SpeedportSensor(hub, description).entity_registry_enabled_default
        for description in SENSOR_DESCRIPTIONS
    )
    assert all(
        SpeedportBinarySensor(hub, description).entity_registry_enabled_default
        for description in BINARY_SENSOR_DESCRIPTIONS
    )
