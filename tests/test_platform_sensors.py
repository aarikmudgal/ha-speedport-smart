"""Tests for capability-gated Speedport sensors."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, PropertyMock, patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfInformation

from custom_components.speedport_smart.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    CHILD_BINARY_SENSOR_COLLECTIONS,
    SpeedportBinarySensor,
    SpeedportChildBinarySensor,
)
from custom_components.speedport_smart.binary_sensor import (
    async_setup_entry as async_setup_binary_sensors,
)
from custom_components.speedport_smart.coordinator import (
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
)
from custom_components.speedport_smart.panel import (
    _PUBLIC_STATUS_KEYS,
    _access_source_for_entity,
)
from custom_components.speedport_smart.platform_helpers import speedport_child_device
from custom_components.speedport_smart.sensor import (
    CHILD_SENSOR_COLLECTIONS,
    ENDPOINT_FAILURE_SENSOR_DESCRIPTION,
    POLLING_HEALTH_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    WAN_TELEMETRY_SENSOR_DESCRIPTIONS,
    SpeedportChildSensor,
    SpeedportEndpointFailureSensor,
    SpeedportManagementAccessSensor,
    SpeedportPollingHealthSensor,
    SpeedportSensor,
    SpeedportWanTelemetrySensor,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from custom_components.speedport_smart.sensor import (
    async_setup_entry as async_setup_sensors,
)


def _description(descriptions: tuple[Any, ...], key: str) -> Any:
    return next(description for description in descriptions if description.key == key)


def _nested_payload(data_path: str, value: Any) -> dict[str, Any]:
    """Build a normalized nested payload for one dotted data path."""
    payload: Any = value
    for part in reversed(data_path.split(".")):
        payload = {part: payload}
    return payload


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


async def test_internet_connected_since_is_diagnostic_timestamp(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Explicit-offset connection time becomes an aware timestamp sensor."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {"internet": {"connected_since": "2026-09-02T08:15:30+02:00"}}
    )
    description = _description(SENSOR_DESCRIPTIONS, "internet_connected_since")
    sensor = SpeedportSensor(hub, description)

    assert sensor.native_value == datetime.fromisoformat("2026-09-02T08:15:30+02:00")
    assert description.device_class is SensorDeviceClass.TIMESTAMP
    assert description.entity_category is EntityCategory.DIAGNOSTIC


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


async def test_smarthome_linked_uses_public_system_status_capability(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Status.json SmartHome state needs no nonexistent detail capability."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {"system"}  # noqa: SLF001
    hub._merge_data({"smarthome": {"linked": True}})  # noqa: SLF001
    assert "smarthome" not in hub.capabilities
    entry = MagicMock(runtime_data=hub)
    binary_sensors: list[SpeedportBinarySensor] = []

    await async_setup_binary_sensors(hass, entry, binary_sensors.extend)

    linked = next(
        entity
        for entity in binary_sensors
        if entity.entity_description.key == "smarthome_linked"
    )
    assert linked.is_on
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_cross_root_normalizer_values_create_native_entities(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Successful endpoint polling discovers every returned canonical entity."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        authenticated_json=True,
        feature_endpoints={
            family: EndpointCapability(
                family,
                f"data/{family}.json",
                authenticated=True,
            )
            for family in ("clients", "lan", "mobile")
        },
    )
    mock_speedport_client.get_json.side_effect = lambda endpoint, **_kwargs: {
        "data/clients.json": {
            "addmlandevice": [{"id": "lan-1", "connected": "1"}],
            "addmwlandevice": [{"id": "wifi-1", "connected": "1"}],
            "addpwlinedevice": [
                {
                    "id": "powerline-1",
                    "pwline_name": "Powerline",
                    "pwline_mode": "mesh",
                }
            ],
        },
        "data/lan.json": {
            "lan_use_dhcp": "1",
            "lan1_device": "1000000000",
            "lan4_link_status": "1",
        },
        "data/mobile.json": {
            "ex5g_signal_5g": "-80",
            "ex5g_led_mode": "1",
        },
    }[endpoint]
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    entry = MagicMock(runtime_data=hub)
    sensors: list[Any] = []
    binary_sensors: list[Any] = []

    await async_setup_sensors(hass, entry, sensors.extend)
    await async_setup_binary_sensors(hass, entry, binary_sensors.extend)

    fixed_sensor_keys = {
        entity.entity_description.key
        for entity in sensors
        if isinstance(entity, SpeedportSensor)
    }
    assert {
        "lan_linked_ports",
        "receiver_led_mode",
        "wifi_2_4_clients",
    } <= fixed_sensor_keys
    assert any(
        isinstance(entity, SpeedportChildSensor)
        and entity._collection_spec.kind == "powerline_node"  # noqa: SLF001
        and entity._field_description.key == "powerline_mode"  # noqa: SLF001
        for entity in sensors
    )
    assert any(
        isinstance(entity, SpeedportBinarySensor)
        and entity.entity_description.key == "dhcp_enabled"
        for entity in binary_sensors
    )
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_fixed_wan_binary_sensor_is_added_after_setup_busy_recovers(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A first WAN sample adds its fixed binary entity without a reload."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {"wan", "wan_counters"}  # noqa: SLF001
    entry = MagicMock(runtime_data=hub)
    binary_sensors: list[SpeedportBinarySensor] = []

    await async_setup_binary_sensors(hass, entry, binary_sensors.extend)
    assert not any(
        entity.entity_description.key == "wan_interface_enabled"
        for entity in binary_sensors
    )

    hub._merge_data(  # noqa: SLF001 - setup-recovery fixture
        {"wan": {"interface": {"enabled": True}}}
    )
    hub.coordinator(PollGroup.FAST).async_update_listeners()
    hub.coordinator(PollGroup.FAST).async_update_listeners()

    recovered = [
        entity
        for entity in binary_sensors
        if entity.entity_description.key == "wan_interface_enabled"
    ]
    assert len(recovered) == 1
    assert recovered[0].is_on
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_wan_interface_entities_fail_closed_during_telemetry_retry(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Cached interface identity and state are not presented as current."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "wan": {
                "interface": {
                    "name": "habond",
                    "status": "Up",
                    "enabled": True,
                }
            }
        }
    )
    interface = SpeedportSensor(hub, _description(SENSOR_DESCRIPTIONS, "wan_interface"))
    interface_status = SpeedportSensor(
        hub, _description(SENSOR_DESCRIPTIONS, "wan_interface_status")
    )
    interface_enabled = SpeedportBinarySensor(
        hub, _description(BINARY_SENSOR_DESCRIPTIONS, "wan_interface_enabled")
    )

    assert interface.entity_description.coordinator_group is PollGroup.FAST
    assert interface.available
    assert interface_status.available
    assert interface_enabled.available

    hub._endpoint_errors["wan_counters"] = (  # noqa: SLF001
        "SpeedportSessionBusyError"
    )

    assert not interface.available
    assert not interface_status.available
    assert not interface_enabled.available


async def test_native_wan_scheduler_diagnostics_expose_all_visible_fields(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Auto-learning cadence is visible to dashboards and automations."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {"wan_counters"}  # noqa: SLF001
    telemetry = {
        "mode": "auto",
        "state": "learning",
        "effective_interval_seconds": 4.0,
        "runtime_floor_seconds": 1.0,
        "last_stable_interval_seconds": 5.0,
        "target_interval_seconds": 1.0,
        "retry_in_seconds": 0.0,
        "success_streak": 7,
        "last_sampled_at": "2026-09-01T10:00:00+00:00",
    }
    descriptions = {
        description.key: description
        for description in WAN_TELEMETRY_SENSOR_DESCRIPTIONS
    }

    with patch.object(
        type(hub),
        "wan_counter_telemetry",
        new_callable=PropertyMock,
        return_value=telemetry,
    ):
        entities = {
            key: SpeedportWanTelemetrySensor(hub, description)
            for key, description in descriptions.items()
        }

        assert set(entities) == {
            "wan_polling_mode",
            "wan_polling_interval",
            "wan_polling_state",
            "wan_fastest_proven_interval",
            "wan_last_sample",
        }
        assert all(
            entity.entity_registry_enabled_default for entity in entities.values()
        )
        assert entities["wan_polling_mode"].native_value == "auto"
        assert entities["wan_polling_interval"].native_value == 4.0
        assert entities["wan_polling_state"].native_value == "learning"
        assert entities["wan_fastest_proven_interval"].native_value == 5.0
        assert entities["wan_last_sample"].native_value == datetime(
            2026, 9, 1, 10, tzinfo=UTC
        )
        telemetry["last_sampled_at"] = "2026-09-01T10:00:59.999999+00:00"
        assert entities["wan_last_sample"].native_value == datetime(
            2026, 9, 1, 10, tzinfo=UTC
        )
        telemetry["last_sampled_at"] = "2026-09-01T10:01:00+00:00"
        assert entities["wan_last_sample"].native_value == datetime(
            2026, 9, 1, 10, 1, tzinfo=UTC
        )
        assert entities["wan_polling_state"].extra_state_attributes == {
            "mode": "auto",
            "target_interval_seconds": 1.0,
            "runtime_floor_seconds": 1.0,
            "last_stable_interval_seconds": 5.0,
            "retry_in_seconds": 0.0,
            "success_streak": 7,
            "source_available": True,
        }
        hub.coordinator(PollGroup.FAST).last_update_success = False
        assert all(entity.available for entity in entities.values())


async def test_polling_and_endpoint_health_diagnostics_are_bounded_and_visible(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Coordinator failures stay observable without raw exception messages."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    descriptions = {
        description.key: description
        for description in POLLING_HEALTH_SENSOR_DESCRIPTIONS
    }
    fast = SpeedportPollingHealthSensor(
        hub,
        descriptions["fast_polling_health"],
    )
    slow = SpeedportPollingHealthSensor(
        hub,
        descriptions["slow_polling_health"],
    )
    endpoint_failures = SpeedportEndpointFailureSensor(hub)

    assert fast.native_value == "initializing"
    assert fast.available
    assert fast.extra_state_attributes == {"update_interval_seconds": 5.0}
    assert endpoint_failures.native_value == 0
    assert endpoint_failures.extra_state_attributes == {
        "failures": {},
    }

    hub.record_update_failure(
        PollGroup.SLOW,
        RuntimeError("private original message"),
    )
    assert slow.native_value == "failed"
    assert slow.extra_state_attributes == {
        "update_interval_seconds": 300.0,
        "last_error_class": "RuntimeError",
    }

    await hub.async_update_group(PollGroup.FAST)
    assert fast.native_value == "healthy"
    assert fast.extra_state_attributes == {
        "update_interval_seconds": 5.0,
    }

    last_success = hub.poll_group_health(PollGroup.FAST)["last_successful_update"]
    hub.record_update_failure(
        PollGroup.FAST,
        RuntimeError("must never become an attribute"),
    )
    hub._endpoint_errors.update(  # noqa: SLF001 - bounded diagnostic fixture
        {
            "wifi": "SpeedportConnectionError",
            "wan_counters": "SpeedportSessionBusyError",
        }
    )
    assert fast.native_value == "failed"
    assert fast.available
    assert fast.extra_state_attributes == {
        "update_interval_seconds": 5.0,
        "last_successful_update": last_success,
        "last_error_class": "RuntimeError",
    }
    assert endpoint_failures.native_value == 2
    assert endpoint_failures.extra_state_attributes == {
        "failures": {
            "wan_counters": "SpeedportSessionBusyError",
            "wifi": "SpeedportConnectionError",
        },
    }
    assert "must never become" not in repr(fast.extra_state_attributes)

    await hub.async_update_group(PollGroup.FAST)
    assert fast.native_value == "healthy"
    assert fast.extra_state_attributes == {"update_interval_seconds": 5.0}


async def test_update_failure_sensor_exposes_only_bounded_failure_context(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The existing failure counter explains its last safe failure class."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub.record_update_failure(
        PollGroup.NORMAL,
        RuntimeError("private router text must not be exposed"),
    )
    entity = SpeedportSensor(
        hub,
        _description(SENSOR_DESCRIPTIONS, "update_failures"),
    )

    assert entity.native_value == 1
    assert entity.extra_state_attributes == {
        "last_failed_group": "normal",
        "last_error_class": "RuntimeError",
    }
    assert "private router text" not in repr(entity.extra_state_attributes)
    hub.coordinator(PollGroup.NORMAL).last_update_success = False
    assert entity.available


async def test_update_failure_sensor_refreshes_from_every_poll_group(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The aggregate refreshes when fast, normal, or slow polling changes."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    entity = SpeedportSensor(
        hub,
        _description(SENSOR_DESCRIPTIONS, "update_failures"),
    )
    entity.hass = hass
    listener_registrations: dict[PollGroup, MagicMock] = {}
    for group in PollGroup:
        registration = MagicMock(return_value=MagicMock())
        hub.coordinator(group).async_add_listener = registration
        listener_registrations[group] = registration

    with patch.object(entity, "async_write_ha_state") as write_state:
        await entity.async_added_to_hass()
        for registration in listener_registrations.values():
            assert registration.call_count == 1
            registration.call_args.args[0]()

        assert write_state.call_count == len(PollGroup)

    await entity.async_will_remove_from_hass()


async def test_client_safe_connection_metadata_entities_are_discovered(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Observed non-secret client metadata becomes read-only native entities."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "clients": {
                "items": [
                    {
                        "id": "AA:BB:CC:DD:EE:FF",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "connected": True,
                        "internet_access_allowed": True,
                        "uses_dhcp": True,
                        "has_web_ui": False,
                        "medium": "wifi_5",
                        "wifi_standard": "IEEE 802.11ax",
                    }
                ]
            }
        }
    )
    entry = MagicMock(runtime_data=hub)
    binary_sensors: list[SpeedportBinarySensor | SpeedportChildBinarySensor] = []
    sensors: list[SpeedportSensor | SpeedportChildSensor] = []

    await async_setup_binary_sensors(hass, entry, binary_sensors.extend)
    await async_setup_sensors(hass, entry, sensors.extend)

    allowed = next(
        entity
        for entity in binary_sensors
        if isinstance(entity, SpeedportChildBinarySensor)
        and entity.unique_id.endswith("internet_access_allowed")
    )
    assert allowed.translation_key == "internet_access_allowed"
    assert allowed.is_on
    assert allowed.device_class is BinarySensorDeviceClass.CONNECTIVITY
    uses_dhcp = next(
        entity
        for entity in binary_sensors
        if isinstance(entity, SpeedportChildBinarySensor)
        and entity.unique_id.endswith("uses_dhcp")
    )
    web_interface = next(
        entity
        for entity in binary_sensors
        if isinstance(entity, SpeedportChildBinarySensor)
        and entity.unique_id.endswith("web_interface_available")
    )
    medium = next(
        entity
        for entity in sensors
        if isinstance(entity, SpeedportChildSensor)
        and entity.unique_id.endswith("connection_medium")
    )
    standard = next(
        entity
        for entity in sensors
        if isinstance(entity, SpeedportChildSensor)
        and entity.unique_id.endswith("wifi_standard")
    )
    assert uses_dhcp.is_on
    assert uses_dhcp.device_class is None
    assert web_interface.is_on is False
    assert web_interface.device_class is None
    assert medium.native_value == "wifi_5"
    assert standard.native_value == "IEEE 802.11ax"
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_disappeared_client_connectivity_is_off_but_signal_is_unavailable(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A fresh client list treats a missing client as offline, not unknown."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {"clients"}  # noqa: SLF001
    hub._merge_data(  # noqa: SLF001 - platform lifecycle fixture
        {
            "clients": {
                "items": [
                    {
                        "id": "AA:BB:CC:DD:EE:FF",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "connected": True,
                        "signal_dbm": -55.0,
                    }
                ]
            }
        }
    )
    item = hub.get("clients.items")[0]
    device = speedport_child_device("client", item)
    assert device is not None
    binary_collection = next(
        spec for spec in CHILD_BINARY_SENSOR_COLLECTIONS if spec.kind == "client"
    )
    sensor_collection = next(
        spec for spec in CHILD_SENSOR_COLLECTIONS if spec.kind == "client"
    )
    connected = SpeedportChildBinarySensor(
        hub,
        binary_collection,
        _description(binary_collection.fields, "connected"),
        "aa:bb:cc:dd:ee:ff",
        device,
    )
    signal = SpeedportChildSensor(
        hub,
        sensor_collection,
        _description(sensor_collection.fields, "signal_strength"),
        "aa:bb:cc:dd:ee:ff",
        device,
    )
    assert connected.available
    assert connected.is_on
    assert signal.available
    assert signal.native_value == -55.0

    hub._merge_data({"clients": {"items": []}})  # noqa: SLF001

    assert connected.available
    assert connected.is_on is False
    assert not signal.available
    assert signal.native_value is None

    hub._merge_data({"clients": {"items": None}})  # noqa: SLF001
    assert not connected.available
    assert not signal.available


async def test_description_catalog_is_complete_and_entities_default_enabled(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Catalog covers every family and fixed entities default to enabled."""
    sensor_keys = [description.key for description in SENSOR_DESCRIPTIONS]
    binary_keys = [description.key for description in BINARY_SENSOR_DESCRIPTIONS]
    assert len(sensor_keys) == len(set(sensor_keys))
    assert len(binary_keys) == len(set(binary_keys))
    assert all(
        description.entity_registry_enabled_default
        for description in SENSOR_DESCRIPTIONS
    )
    assert all(
        description.entity_registry_enabled_default
        for description in WAN_TELEMETRY_SENSOR_DESCRIPTIONS
    )
    assert all(
        description.entity_registry_enabled_default
        for description in POLLING_HEALTH_SENSOR_DESCRIPTIONS
    )
    assert ENDPOINT_FAILURE_SENSOR_DESCRIPTION.entity_registry_enabled_default
    assert all(
        description.entity_registry_enabled_default
        for description in BINARY_SENSOR_DESCRIPTIONS
    )
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


def test_public_overview_read_only_descriptions_are_capability_gated() -> None:
    """Exact public overview values are exposed as read-only entities only."""
    sensor_paths = {
        **{
            f"lan_port_{port}_speed": f"lan.ports.port_{port}.speed_bps"
            for port in range(1, 5)
        },
        "wifi_office_clients": "wifi.office.client_count",
        "wifi_guest_remaining_time": "wifi.guest.remaining_minutes",
        "system_operating_mode": "system.operating_mode",
        "internet_provisioning_code": "internet.provisioning_code",
        "internet_provider_family": "internet.provider_family",
        "telephony_provisioning_code": "telephony.provisioning_code",
        "telephony_provider_family": "telephony.provider_family",
        "internet_error_code": "internet.error_code",
        "dsl_error_code": "dsl.error_code",
        "mobile_status_code": "mobile.status_code",
        "mobile_nr_signal": "mobile.nr.signal_dbm",
        "mobile_nr_band": "mobile.nr.band_code",
        "mobile_lte_signal": "mobile.lte.signal_dbm",
        "mobile_lte_band": "mobile.lte.band_code",
        "receiver_model": "receiver.model",
        "wifi_5_channel_width": "wifi.radio_5.channel_width_mode",
        "lan_ula_address": "lan.ula_address",
        "lan_usable_ipv6_range": "lan.usable_ipv6_range",
        "dhcp_lease_duration_code": "dhcp.lease_duration_code",
        "dect_paging_handsets": "dect.paging_handset_count",
        "wifi_5_encryption_mode": "wifi.radio_5.encryption_mode",
        "wifi_guest_2_4_clients": "wifi.guest.radio_2_4_client_count",
        "wifi_guest_5_clients": "wifi.guest.radio_5_client_count",
        "wifi_guest_wifi_4_clients": "wifi.guest.wifi_4_client_count",
        "wifi_guest_wifi_5_clients": "wifi.guest.wifi_5_client_count",
        "wifi_guest_wifi_6_clients": "wifi.guest.wifi_6_client_count",
        "ddns_update_protocol": "ddns.update_protocol",
        "ddns_update_port": "ddns.update_port",
        "telephony_failed_lines": "telephony.failed_line_count",
    }
    binary_paths = {
        **{
            f"lan_port_{port}_connected": f"lan.ports.port_{port}.connected"
            for port in range(1, 5)
        },
        "receiver_external_wan_link": "receiver.external_wan_link",
        "dect_paging_active": "dect.paging_active",
        "guest_wifi_display_key_enabled": "wifi.guest.display_key_enabled",
        "office_wifi_wps_enabled": "wifi.office.wps_enabled",
        "dsl_modem_lan_link": "dsl.modem_lan_link",
        "settings_write_blocked": "system.settings_write_blocked",
        "internet_bng_configured": "internet.bng_configured",
        "telephony_hd_voice_active": "telephony.hd_voice_active",
        "telephony_manual_configuration_available": (
            "telephony.manual_configuration_available"
        ),
        "smarthome_linked": "smarthome.linked",
        "router_https_enabled": "security.router_https_enabled",
        "device_password_changed": "system.device_password_changed",
        "initial_setup_completed": "system.initial_setup_completed",
        "receiver_esim_supported": "receiver.esim_supported",
        "wifi_enabled": "wifi.enabled",
    }

    for key, data_path in sensor_paths.items():
        description = _description(SENSOR_DESCRIPTIONS, key)
        assert description.data_path == data_path
        assert description.entity_registry_enabled_default
        assert not hasattr(description, "command")
    for key, data_path in binary_paths.items():
        description = _description(BINARY_SENSOR_DESCRIPTIONS, key)
        assert description.data_path == data_path
        assert description.entity_registry_enabled_default
        assert not hasattr(description, "command")

    native_keys = {description.key for description in SENSOR_DESCRIPTIONS}
    assert {
        "wifi_2_4_ssid",
        "wifi_5_ssid",
        "wifi_guest_ssid",
        "wifi_office_ssid",
        "ddns_domain",
        "ddns_update_server",
    }.isdisjoint(native_keys)

    assert (
        _description(SENSOR_DESCRIPTIONS, "system_operating_mode").device_class
        is SensorDeviceClass.ENUM
    )
    assert (
        _description(BINARY_SENSOR_DESCRIPTIONS, "settings_write_blocked").device_class
        is BinarySensorDeviceClass.PROBLEM
    )


async def test_normalized_read_only_metadata_entities(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Normalized firmware metadata is exposed without control semantics."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {  # noqa: SLF001
        "ddns",
        "hybrid",
        "internet",
        "nat",
        "pbx",
        "usb",
        "vpn",
        "wan",
        "wifi",
    }
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "internet": {"ip_stack": "Dual Stack"},
            "hybrid": {
                "enabled": True,
                "dsl_tunnel": True,
                "lte_tunnel": False,
            },
            "wifi": {
                "enabled": True,
                "wps_status": "idle",
                "mac_filter_enabled": True,
                "schedule_enabled": False,
            },
            "nat": {"port_forwarding_enabled": True},
            "ddns": {"enabled": False},
            "vpn": {"enabled": True, "type": "WireGuard"},
            "pbx": {"enabled": True},
            "usb": {"media_server_enabled": False},
            "wan": {
                "interface": {
                    "index": 5,
                    "alias": "BONDING",
                    "name": "habond",
                    "status": "Up",
                    "enabled": True,
                }
            },
        }
    )

    expected_sensors = {
        "internet_ip_stack": ("internet.ip_stack", "Dual Stack"),
        "vpn_type": ("vpn.type", "WireGuard"),
        "wan_interface_status": ("wan.interface.status", "Up"),
    }
    for key, (data_path, expected_value) in expected_sensors.items():
        description = _description(SENSOR_DESCRIPTIONS, key)
        assert description.data_path == data_path
        assert description.entity_category is EntityCategory.DIAGNOSTIC
        assert description.entity_registry_enabled_default
        assert SpeedportSensor(hub, description).native_value == expected_value

    interface = SpeedportSensor(hub, _description(SENSOR_DESCRIPTIONS, "wan_interface"))
    assert interface.extra_state_attributes == {"index": 5, "alias": "BONDING"}

    expected_binary = {
        "hybrid_enabled": ("hybrid.enabled", True),
        "hybrid_dsl_tunnel": ("hybrid.dsl_tunnel", True),
        "hybrid_lte_tunnel": ("hybrid.lte_tunnel", False),
        "wifi_enabled": ("wifi.enabled", True),
        "wifi_wps_active": ("wifi.wps_status", False),
        "wifi_mac_filter_enabled": ("wifi.mac_filter_enabled", True),
        "wifi_schedule_enabled": ("wifi.schedule_enabled", False),
        "port_forwarding_enabled": ("nat.port_forwarding_enabled", True),
        "ddns_enabled": ("ddns.enabled", False),
        "vpn_enabled": ("vpn.enabled", True),
        "pbx_enabled": ("pbx.enabled", True),
        "media_server_enabled": ("usb.media_server_enabled", False),
        "wan_interface_enabled": ("wan.interface.enabled", True),
    }
    for key, (data_path, expected_value) in expected_binary.items():
        description = _description(BINARY_SENSOR_DESCRIPTIONS, key)
        assert description.data_path == data_path
        assert description.entity_category is EntityCategory.DIAGNOSTIC
        assert description.entity_registry_enabled_default
        assert SpeedportBinarySensor(hub, description).is_on is expected_value

    wps_description = _description(BINARY_SENSOR_DESCRIPTIONS, "wifi_wps_active")
    hub._merge_data({"wifi": {"wps_status": "configured"}})  # noqa: SLF001
    assert SpeedportBinarySensor(hub, wps_description).is_on is False
    hub._merge_data({"wifi": {"wps_status": "connecting"}})  # noqa: SLF001
    assert SpeedportBinarySensor(hub, wps_description).is_on is True

    assert (
        _description(BINARY_SENSOR_DESCRIPTIONS, "hybrid_dsl_tunnel").device_class
        is BinarySensorDeviceClass.CONNECTIVITY
    )
    for key in ("firewall_enabled", "dns_rebind_protection"):
        assert (
            _description(BINARY_SENSOR_DESCRIPTIONS, key).device_class
            is BinarySensorDeviceClass.RUNNING
        )
    assert not any(
        description.data_path in {"dsl.line_index", "dsl.channel_index"}
        for description in SENSOR_DESCRIPTIONS
    )
    assert not any(
        "last_handshake" in description.data_path for description in SENSOR_DESCRIPTIONS
    )


async def test_management_telemetry_is_read_only_complete_and_fail_closed(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Expose constrained management metadata without creating controls."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)

    expected_sensors: dict[str, tuple[str, Any]] = {
        "internet_privacy_level": ("internet.privacy_level", "level_2"),
        "wifi_band_mode": ("wifi.band_mode", "2_4_ghz_only"),
        "wifi_wps_state_code": ("wifi.wps_state_code", "failed"),
        "wifi_2_4_encryption_mode": ("wifi.radio_2_4.encryption_mode", 6),
        "wifi_guest_encryption_mode": ("wifi.guest.encryption_mode", 5),
        "wifi_office_encryption_mode": ("wifi.office.encryption_mode", 4),
        "wifi_schedule_mode": ("wifi.schedule.mode", "daily"),
        "wifi_schedule_daily_from": ("wifi.schedule.daily_from", "07:30"),
        "wifi_schedule_daily_to": ("wifi.schedule.daily_to", "22:15"),
        "wifi_schedule_weekly": ("wifi.schedule.weekly_day_count", 2),
        "receiver_mode": ("receiver.mode", 3),
        "receiver_led_mode": ("receiver.led_mode", "disabled"),
        "receiver_firmware_version": (
            "receiver.firmware_version",
            "010152.5.0.001.0",
        ),
        "receiver_latest_firmware": (
            "receiver.latest_firmware",
            "010152.6.0.001.0",
        ),
        "receiver_firmware_update_time": (
            "receiver.firmware_update_time",
            datetime(2026, 9, 1, 5, 30, tzinfo=UTC),
        ),
        "usb_tethering_status": ("usb.tethering_status_code", 2),
        "usb_storage_devices": ("usb.storage_device_count", 1),
        "usb_storage_total": ("usb.storage_total_bytes", 2_097_152),
        "usb_storage_used": ("usb.storage_used_bytes", 524_288),
        "usb_storage_free": ("usb.storage_free_bytes", 1_572_864),
        "media_server_folders": ("usb.media_share_count", 2),
        "media_server_active_folders": ("usb.active_media_share_count", 1),
        "dns_rebind_exceptions": ("security.dns_rebind_exception_count", 2),
        "port_block_rules": ("security.port_block_rule_count", 2),
        "active_port_block_rules": (
            "security.active_port_block_rule_count",
            1,
        ),
        "qos_prioritized_clients": ("qos.prioritized_client_count", 1),
        "dect_repeaters": ("dect.repeater_count", 1),
        "pbx_configured_clients": ("pbx.configured_client_count", 3),
        "pbx_disconnected_clients": ("pbx.disconnected_client_count", 1),
        "pbx_registered_clients": ("pbx.registered_client_count", 1),
        "pbx_locked_clients": ("pbx.locked_client_count", 1),
        "telephony_voip_policy": ("telephony.voip_policy", "level_2"),
        "telephony_providers": ("telephony.provider_count", 1),
        "telephony_configured_numbers": ("telephony.configured_number_count", 2),
        "telephony_registered_voip_numbers": (
            "telephony.registered_voip_number_count",
            1,
        ),
        "telephony_inactive_voip_numbers": (
            "telephony.inactive_voip_number_count",
            1,
        ),
        "telephony_warning_voip_numbers": (
            "telephony.warning_voip_number_count",
            0,
        ),
        "firmware_update_time": (
            "system.update_time",
            datetime(2026, 9, 2, 2, 0, tzinfo=UTC),
        ),
    }
    expected_binary: dict[str, tuple[str, bool]] = {
        "wifi_wps_enabled": ("wifi.wps_enabled", True),
        "wifi_wps_disabled_by_firmware": (
            "wifi.wps_disabled_by_firmware",
            False,
        ),
        "wifi_allow_all_devices": ("wifi.allow_all_devices", False),
        "wifi_2_4_visible": ("wifi.radio_2_4.visible", False),
        "wifi_5_visible": ("wifi.radio_5.visible", True),
        "guest_wifi_wps_enabled": ("wifi.guest.wps_enabled", True),
        "receiver_external_modem_enabled": (
            "receiver.external_modem_enabled",
            True,
        ),
        "receiver_lte_enabled": ("receiver.lte_enabled", True),
        "receiver_firmware_automatic_updates": (
            "receiver.firmware_auto_update",
            True,
        ),
        "receiver_firmware_update_available": (
            "receiver.firmware_update_available",
            True,
        ),
        "receiver_firmware_update_planned": (
            "receiver.firmware_update_planned",
            False,
        ),
        "usb_port_enabled": ("usb.port_enabled", True),
        "usb_tethering_enabled": ("usb.tethering_enabled", True),
        "usb_tethering_connected": ("usb.tethering_connected", True),
        "usb_printer_connected": ("usb.printer_connected", False),
        "port_blocking_enabled": ("security.port_blocking_enabled", True),
        "dect_scan_active": ("dect.scan_active", False),
        "dect_smart_home_enabled": ("dect.smart_home_enabled", True),
        "telephony_voip_possible": ("telephony.voip_possible", True),
        "firmware_update_planned": ("system.update_planned", False),
        "firmware_automatic_updates": (
            "system.automatic_updates_enabled",
            True,
        ),
        "remote_support_active": ("system.cloud_backup_active", False),
        "easy_support_enabled": ("system.easy_support_enabled", False),
    }

    for key, (data_path, _expected) in expected_sensors.items():
        description = _description(SENSOR_DESCRIPTIONS, key)
        entity = SpeedportSensor(hub, description)
        assert description.data_path == data_path
        assert description.entity_category is EntityCategory.DIAGNOSTIC
        assert not hasattr(description, "command")
        assert entity.native_value is None
        assert not entity.available
        assert _access_source_for_entity(key, "sensor", None, is_control=False) == (
            "public_status" if key in _PUBLIC_STATUS_KEYS else "protected_json"
        )
    for key, (data_path, _expected) in expected_binary.items():
        description = _description(BINARY_SENSOR_DESCRIPTIONS, key)
        entity = SpeedportBinarySensor(hub, description)
        assert description.data_path == data_path
        assert description.entity_category is EntityCategory.DIAGNOSTIC
        assert not hasattr(description, "command")
        assert entity.is_on is None
        assert not entity.available
        assert _access_source_for_entity(
            key, "binary_sensor", None, is_control=False
        ) == ("public_status" if key in _PUBLIC_STATUS_KEYS else "protected_json")

    hub._capabilities = hub.capabilities | {  # noqa: SLF001
        "dect",
        "internet",
        "pbx",
        "qos",
        "receiver",
        "security",
        "system",
        "telephony",
        "usb",
        "wifi",
    }
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "internet": {"privacy_level": 2},
            "wifi": {
                "band_mode": 1,
                "wps_enabled": True,
                "wps_state_code": -1,
                "wps_disabled_by_firmware": False,
                "allow_all_devices": False,
                "radio_2_4": {"visible": False, "encryption_mode": 6},
                "radio_5": {"visible": True},
                "guest": {"encryption_mode": 5, "wps_enabled": True},
                "office": {"encryption_mode": 4},
                "schedule": {
                    "mode": 1,
                    "daily_from": "07:30",
                    "daily_to": "22:15",
                    "weekly": {
                        "monday": {"from": "08:00", "to": "21:00"},
                        "friday": {"from": "09:00", "to": "22:30"},
                    },
                    "weekly_day_count": 2,
                },
            },
            "receiver": {
                "external_modem_enabled": True,
                "mode": 3,
                "lte_enabled": True,
                "led_mode": 2,
                "firmware_auto_update": True,
                "firmware_update_available": True,
                "firmware_version": "010152.5.0.001.0",
                "latest_firmware": "010152.6.0.001.0",
                "firmware_update_planned": False,
                "firmware_update_time": "2026-09-01T05:30:00+00:00",
            },
            "usb": {
                "port_enabled": True,
                "tethering_enabled": True,
                "tethering_status_code": 2,
                "tethering_connected": True,
                "printer_connected": False,
                "storage_device_count": 1,
                "storage_total_bytes": 2_097_152,
                "storage_used_bytes": 524_288,
                "storage_free_bytes": 1_572_864,
                "media_share_count": 2,
                "active_media_share_count": 1,
            },
            "security": {
                "dns_rebind_exception_count": 2,
                "port_blocking_enabled": True,
                "port_block_rule_count": 2,
                "active_port_block_rule_count": 1,
            },
            "qos": {"prioritized_client_count": 1},
            "dect": {
                "scan_active": False,
                "smart_home_enabled": True,
                "repeater_count": 1,
            },
            "pbx": {
                "configured_client_count": 3,
                "disconnected_client_count": 1,
                "registered_client_count": 1,
                "locked_client_count": 1,
            },
            "telephony": {
                "voip_possible": True,
                "voip_policy": 2,
                "provider_count": 1,
                "configured_number_count": 2,
                "registered_voip_number_count": 1,
                "inactive_voip_number_count": 1,
                "warning_voip_number_count": 0,
            },
            "system": {
                "update_planned": False,
                "update_time": "2026-09-02T02:00:00+00:00",
                "automatic_updates_enabled": True,
                "cloud_backup_active": False,
                "easy_support_enabled": False,
            },
        }
    )

    for key, (_data_path, expected) in expected_sensors.items():
        description = _description(SENSOR_DESCRIPTIONS, key)
        assert SpeedportSensor(hub, description).native_value == expected
    for key, (_data_path, expected) in expected_binary.items():
        description = _description(BINARY_SENSOR_DESCRIPTIONS, key)
        assert SpeedportBinarySensor(hub, description).is_on is expected

    for key in ("media_server_folders", "media_server_active_folders"):
        assert _description(SENSOR_DESCRIPTIONS, key).capability == (
            "usb",
            "media_server",
        )

    enum_contracts = {
        "internet_privacy_level": (
            "internet.privacy_level",
            {0: "off", 1: "level_1", 2: "level_2"},
            ["off", "level_1", "level_2"],
        ),
        "wifi_band_mode": (
            "wifi.band_mode",
            {0: "both_bands", 1: "2_4_ghz_only", 2: "5_ghz_only"},
            ["both_bands", "2_4_ghz_only", "5_ghz_only"],
        ),
        "wifi_wps_state_code": (
            "wifi.wps_state_code",
            {-2: "failed", -1: "failed", 0: "successful", 1: "in_progress"},
            ["failed", "successful", "in_progress"],
        ),
        "wifi_schedule_mode": (
            "wifi.schedule.mode",
            {0: "disabled", 1: "daily", 2: "weekly"},
            ["disabled", "daily", "weekly"],
        ),
        "receiver_led_mode": (
            "receiver.led_mode",
            {0: "use_leds", 1: "off_after_timeout", 2: "disabled"},
            ["use_leds", "off_after_timeout", "disabled"],
        ),
        "telephony_voip_policy": (
            "telephony.voip_policy",
            {0: "off", 1: "level_1", 2: "level_2"},
            ["off", "level_1", "level_2"],
        ),
    }
    for key, (data_path, code_values, options) in enum_contracts.items():
        description = _description(SENSOR_DESCRIPTIONS, key)
        entity = SpeedportSensor(hub, description)
        assert description.device_class is SensorDeviceClass.ENUM
        assert description.options == options
        for code, expected in code_values.items():
            hub._merge_data(_nested_payload(data_path, code))  # noqa: SLF001
            assert entity.native_value == expected
            assert entity.available
        hub._merge_data(_nested_payload(data_path, 999))  # noqa: SLF001
        assert entity.native_value is None
        assert not entity.available

    storage_keys = {"usb_storage_total", "usb_storage_used", "usb_storage_free"}
    for key in storage_keys:
        description = _description(SENSOR_DESCRIPTIONS, key)
        assert description.device_class is SensorDeviceClass.DATA_SIZE
        assert description.native_unit_of_measurement is UnitOfInformation.BYTES
        assert description.state_class is SensorStateClass.MEASUREMENT
    for key in ("firmware_update_time", "receiver_firmware_update_time"):
        assert (
            _description(SENSOR_DESCRIPTIONS, key).device_class
            is SensorDeviceClass.TIMESTAMP
        )

    weekly = SpeedportSensor(
        hub,
        _description(SENSOR_DESCRIPTIONS, "wifi_schedule_weekly"),
    )
    assert weekly.native_value == 2
    assert weekly.available
    assert weekly.extra_state_attributes == {
        "monday_from": "08:00",
        "monday_to": "21:00",
        "friday_from": "09:00",
        "friday_to": "22:30",
    }
    hub._merge_data(  # noqa: SLF001 - stale nested-path regression fixture
        {
            "wifi": {
                "schedule": {
                    "weekly_day_count": None,
                    "weekly": {
                        "monday": {"from": None, "to": None},
                        "friday": {"from": None, "to": None},
                    },
                }
            }
        }
    )
    assert weekly.native_value is None
    assert not weekly.available
    assert weekly.extra_state_attributes == {}


def test_dect_count_and_receiver_link_speed_have_native_entity_coverage() -> None:
    """Aggregate DECT count and receiver link speed use existing entity seams."""
    dect = _description(SENSOR_DESCRIPTIONS, "dect_handsets")
    assert dect.data_path == "dect.handset_count"
    assert dect.transform("3") == 3

    phonebook_entries = _description(SENSOR_DESCRIPTIONS, "phonebook_entries")
    assert phonebook_entries.data_path == "dect.phonebook_entry_count"
    assert phonebook_entries.transform("42") == 42

    repeater = next(
        collection
        for collection in CHILD_BINARY_SENSOR_COLLECTIONS
        if collection.kind == "dect_repeater"
    )
    assert repeater.data_paths == ("dect.repeaters",)
    assert _description(repeater.fields, "registered").field == "registered"

    receiver = next(
        collection
        for collection in CHILD_SENSOR_COLLECTIONS
        if collection.kind == "receiver"
    )
    link_speed = _description(receiver.fields, "link_speed")
    assert link_speed.field == "link_speed_bps"
    assert link_speed.transform(1_000_000_000) == 1_000.0


async def test_p1_safe_read_fields_have_native_entity_coverage(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Exact retained LAN and DDNS fields reach Home Assistant."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {  # noqa: SLF001
        "ddns",
        "dhcp",
        "lan",
    }
    hub._merge_data(  # noqa: SLF001 - entity contract fixture
        {
            "lan": {
                "ipv4_address": "192.0.2.1",
                "subnet_mask": "255.255.255.0",
                "ipv6_enabled": True,
            },
            "dhcp": {
                "pool_start_ipv4": "192.0.2.20",
                "pool_end_ipv4": "192.0.2.200",
                "pool_size": 181,
            },
            "ddns": {"provider": "4", "status_code": 2},
        }
    )

    expected = {
        "lan_ipv4_address": "192.0.2.1",
        "lan_subnet_mask": "255.255.255.0",
        "dhcp_pool_size": 181,
        "ddns_provider": "4",
        "ddns_status": "registered",
    }
    for key, expected_value in expected.items():
        entity = SpeedportSensor(hub, _description(SENSOR_DESCRIPTIONS, key))
        assert entity.native_value == expected_value
        assert entity.available

    pool = SpeedportSensor(hub, _description(SENSOR_DESCRIPTIONS, "dhcp_pool_size"))
    assert pool.extra_state_attributes == {
        "start_ipv4": "192.0.2.20",
        "end_ipv4": "192.0.2.200",
    }
    ipv6 = SpeedportBinarySensor(
        hub,
        _description(BINARY_SENSOR_DESCRIPTIONS, "lan_ipv6_enabled"),
    )
    assert ipv6.is_on is True

    mesh = next(
        collection
        for collection in CHILD_SENSOR_COLLECTIONS
        if collection.kind == "mesh_node"
    )
    assert mesh.coordinator_group is PollGroup.NORMAL
    mesh_binary = next(
        collection
        for collection in CHILD_BINARY_SENSOR_COLLECTIONS
        if collection.kind == "mesh_node"
    )
    assert mesh_binary.coordinator_group is PollGroup.NORMAL
    assert _description(SENSOR_DESCRIPTIONS, "mesh_nodes").coordinator_group is (
        PollGroup.NORMAL
    )
    assert {field.key for field in mesh.fields} >= {
        "download_link_speed",
        "upload_link_speed",
        "mesh_parent",
        "mesh_device_type",
        "mesh_linked_lan_ports",
    }
    client = next(
        collection
        for collection in CHILD_SENSOR_COLLECTIONS
        if collection.kind == "client"
    )
    assert {field.key for field in client.fields} >= {
        "connection_medium",
        "download_link_speed",
        "upload_link_speed",
        "wifi_generation",
        "wifi_standard",
    }
    client_binary = next(
        collection
        for collection in CHILD_BINARY_SENSOR_COLLECTIONS
        if collection.kind == "client"
    )
    assert {field.key for field in client_binary.fields} >= {
        "uses_dhcp",
        "web_interface_available",
    }


def test_detail_entities_follow_their_source_poll_group() -> None:
    """Detail-only values listen to the group that actually fetches them."""
    assert _description(SENSOR_DESCRIPTIONS, "mesh_clients").coordinator_group is (
        PollGroup.SLOW
    )
    assert (
        _description(
            SENSOR_DESCRIPTIONS,
            "parental_blocked_clients",
        ).coordinator_group
        is PollGroup.SLOW
    )
    for key in (
        "wifi_schedule_mode",
        "wifi_schedule_daily_from",
        "wifi_schedule_daily_to",
        "wifi_schedule_weekly",
    ):
        assert (
            _description(SENSOR_DESCRIPTIONS, key).coordinator_group is PollGroup.SLOW
        )
    assert (
        _description(
            BINARY_SENSOR_DESCRIPTIONS,
            "wifi_schedule_enabled",
        ).coordinator_group
        is PollGroup.NORMAL
    )


async def test_wifi_schedule_enabled_updates_from_normal_wifi_source(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The base Wi-Fi response keeps schedule enabled available without detail data."""
    capability = EndpointCapability(
        "wifi",
        "data/WLANBasic.json",
        authenticated=True,
        referer="html/content/network/wlan_basic.html",
    )
    report = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints={"wifi": capability},
    )
    mock_speedport_client.setup.return_value = report
    mock_speedport_client.capabilities = report
    mock_speedport_client.get_json.return_value = {"wlan_time_active": "1"}
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    _attach_coordinators(hass, hub)

    entity = SpeedportBinarySensor(
        hub,
        _description(BINARY_SENSOR_DESCRIPTIONS, "wifi_schedule_enabled"),
    )

    assert entity.coordinator is hub.coordinator(PollGroup.NORMAL)
    assert entity.is_on is True
    mock_speedport_client.get_json.assert_awaited_once_with(
        "data/WLANBasic.json",
        authenticated=True,
        referer="html/content/network/wlan_basic.html",
    )


async def test_mesh_devicelist_endpoint_reaches_directional_link_speed_entities(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The proven topology endpoint reaches native child data-rate entities."""
    capability = EndpointCapability(
        "mesh_topology",
        "data/DeviceList.json",
        authenticated=True,
        referer="html/content/network/devices.html",
    )
    report = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints={"mesh_topology": capability},
    )
    mock_speedport_client.setup.return_value = report
    mock_speedport_client.capabilities = report
    mock_speedport_client.get_json.return_value = {
        "addmeshdevice": [
            {
                "id": "mesh-1",
                "mesh_name": "Mesh repeater",
                "mesh_downspeed": "1200000000",
                "mesh_upspeed": "600000000",
                "mesh_lan1": "1000",
                "mesh_lan2": "0",
            }
        ]
    }
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    _attach_coordinators(hass, hub)
    entry = MagicMock(runtime_data=hub)
    entities: list[Any] = []
    await async_setup_sensors(hass, entry, entities.extend)

    mesh_entities = {
        entity._field_description.key: entity  # noqa: SLF001 - entity contract proof
        for entity in entities
        if isinstance(entity, SpeedportChildSensor)
        and entity._collection_spec.kind == "mesh_node"  # noqa: SLF001
    }
    mesh_count = next(
        entity
        for entity in entities
        if isinstance(entity, SpeedportSensor)
        and entity.entity_description.key == "mesh_nodes"
    )
    assert mesh_count.native_value == 1
    assert mesh_count.coordinator is hub.coordinator(PollGroup.NORMAL)
    assert mesh_entities["download_link_speed"].native_value == 1_200.0
    assert mesh_entities["upload_link_speed"].native_value == 600.0
    assert mesh_entities["mesh_linked_lan_ports"].native_value == 1
    assert mesh_entities["download_link_speed"].coordinator is hub.coordinator(
        PollGroup.NORMAL
    )
    assert mesh_entities["mesh_linked_lan_ports"].coordinator is hub.coordinator(
        PollGroup.NORMAL
    )
    assert (
        mesh_entities["download_link_speed"].native_unit_of_measurement
        is UnitOfDataRate.MEGABITS_PER_SECOND
    )
    mock_speedport_client.get_json.assert_awaited_once_with(
        "data/DeviceList.json",
        authenticated=True,
        referer="html/content/network/devices.html",
    )
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


def test_read_only_metadata_translations_are_complete() -> None:
    """New read-only entity names exist in source, English, and German."""
    root = Path(__file__).parents[1] / "custom_components" / "speedport_smart"
    catalogs = {
        path: json.loads(path.read_text(encoding="utf-8"))
        for path in (
            root / "strings.json",
            root / "translations" / "en.json",
            root / "translations" / "de.json",
        )
    }
    sensor_keys = {
        description.translation_key
        for description in (
            *SENSOR_DESCRIPTIONS,
            *WAN_TELEMETRY_SENSOR_DESCRIPTIONS,
            *POLLING_HEALTH_SENSOR_DESCRIPTIONS,
            ENDPOINT_FAILURE_SENSOR_DESCRIPTION,
        )
        if description.translation_key is not None
    }
    binary_keys = {
        description.translation_key
        for description in BINARY_SENSOR_DESCRIPTIONS
        if description.translation_key is not None
    }
    sensor_keys.update(
        field.key
        for collection in CHILD_SENSOR_COLLECTIONS
        for field in collection.fields
    )
    binary_keys.update(
        field.key
        for collection in CHILD_BINARY_SENSOR_COLLECTIONS
        for field in collection.fields
    )
    for catalog in catalogs.values():
        assert sensor_keys <= set(catalog["entity"]["sensor"])
        assert binary_keys <= set(catalog["entity"]["binary_sensor"])
