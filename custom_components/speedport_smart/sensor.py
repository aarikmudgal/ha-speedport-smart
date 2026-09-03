"""Capability-gated sensors for Speedport Smart."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfDataRate,
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfTime,
)
from homeassistant.core import callback

from .coordinator import PollGroup
from .diagnostics import safe_error_class_name
from .entity import SpeedportDevice, SpeedportEntity
from .platform_helpers import (
    as_datetime,
    as_float,
    as_gigabytes,
    as_int,
    as_mbit_per_second,
    as_percent,
    child_collection,
    child_item,
    coordinator,
    count_items,
    speedport_child_device,
    stable_id,
    supported,
    value,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


@dataclass(frozen=True, kw_only=True)
class SpeedportSensorEntityDescription(SensorEntityDescription):
    """Describe a normalized Speedport sensor."""

    data_path: str
    capability: str | tuple[str, ...]
    coordinator_group: PollGroup
    transform: Callable[[Any], Any] | None = None


@dataclass(frozen=True, slots=True)
class SpeedportChildSensorDescription:
    """Describe one optional field on a stable router child device."""

    key: str
    name: str
    field: str
    transform: Callable[[Any], Any] | None = None
    device_class: SensorDeviceClass | None = None
    native_unit_of_measurement: Any = None
    state_class: SensorStateClass | None = None
    suggested_display_precision: int | None = None
    attribute_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SpeedportChildSensorCollection:
    """Describe one normalized collection of router child devices."""

    kind: str
    data_paths: tuple[str, ...]
    coordinator_group: PollGroup
    fields: tuple[SpeedportChildSensorDescription, ...]


FAST = PollGroup.FAST
NORMAL = PollGroup.NORMAL
SLOW = PollGroup.SLOW
_WAN_INTERFACE_SENSOR_KEYS = frozenset({"wan_interface", "wan_interface_status"})
_WAN_TELEMETRY_KEY_BY_ENTITY = {
    "wan_fastest_proven_interval": "last_stable_interval_seconds",
    "wan_last_sample": "last_sampled_at",
    "wan_polling_interval": "effective_interval_seconds",
    "wan_polling_mode": "mode",
    "wan_polling_state": "state",
}
WAN_TELEMETRY_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="wan_polling_mode",
        translation_key="wan_polling_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["auto", "manual"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="wan_polling_interval",
        translation_key="wan_polling_interval",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="wan_polling_state",
        translation_key="wan_polling_state",
        device_class=SensorDeviceClass.ENUM,
        options=["learning", "stable", "cooldown", "retrying", "limited"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="wan_fastest_proven_interval",
        translation_key="wan_fastest_proven_interval",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="wan_last_sample",
        translation_key="wan_last_sample",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

_POLLING_HEALTH_GROUP_BY_KEY = {
    f"{group.value}_polling_health": group for group in PollGroup
}
POLLING_HEALTH_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=["healthy", "failed", "initializing"],
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for key in _POLLING_HEALTH_GROUP_BY_KEY
)
ENDPOINT_FAILURE_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="endpoint_failures",
    translation_key="endpoint_failures",
    entity_category=EntityCategory.DIAGNOSTIC,
)


def _code_enum(values: Mapping[int, str]) -> Callable[[Any], str | None]:
    """Map one bounded firmware code to a stable enum value."""

    def transform(raw: Any) -> str | None:
        return values.get(as_int(raw))

    return transform


_INTERNET_PRIVACY_LEVELS = {0: "off", 1: "level_1", 2: "level_2"}
_WIFI_BAND_MODES = {0: "both_bands", 1: "2_4_ghz_only", 2: "5_ghz_only"}
_WIFI_WPS_STATES = {
    -2: "failed",
    -1: "failed",
    0: "successful",
    1: "in_progress",
}
_WIFI_SCHEDULE_MODES = {0: "disabled", 1: "daily", 2: "weekly"}
_DDNS_STATES = {0: "not_registered", 1: "error", 2: "registered"}
_WIFI_SCHEDULE_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_RECEIVER_LED_MODES = {
    0: "use_leds",
    1: "off_after_timeout",
    2: "disabled",
}
_TELEPHONY_VOIP_POLICIES = {0: "off", 1: "level_1", 2: "level_2"}

_SIGNAL_DBM = SpeedportChildSensorDescription(
    key="signal_strength",
    name="Signal strength",
    field="signal_dbm",
    transform=as_float,
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)
_LINK_SPEED = SpeedportChildSensorDescription(
    key="link_speed",
    name="Link speed",
    field="link_speed_bps",
    transform=as_mbit_per_second,
    device_class=SensorDeviceClass.DATA_RATE,
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)
_DOWNLOAD_RATE = SpeedportChildSensorDescription(
    key="download_rate",
    name="Download throughput",
    field="download_rate_bps",
    transform=as_mbit_per_second,
    device_class=SensorDeviceClass.DATA_RATE,
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
)
_UPLOAD_RATE = SpeedportChildSensorDescription(
    key="upload_rate",
    name="Upload throughput",
    field="upload_rate_bps",
    transform=as_mbit_per_second,
    device_class=SensorDeviceClass.DATA_RATE,
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=2,
)
_DOWNLOAD_LINK_SPEED = SpeedportChildSensorDescription(
    key="download_link_speed",
    name="Download link speed",
    field="download_link_speed_bps",
    transform=as_mbit_per_second,
    device_class=SensorDeviceClass.DATA_RATE,
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)
_UPLOAD_LINK_SPEED = SpeedportChildSensorDescription(
    key="upload_link_speed",
    name="Upload link speed",
    field="upload_link_speed_bps",
    transform=as_mbit_per_second,
    device_class=SensorDeviceClass.DATA_RATE,
    native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=1,
)
_WIFI_GENERATION = SpeedportChildSensorDescription(
    key="wifi_generation",
    name="Wi-Fi generation",
    field="wifi_generation",
    transform=as_int,
)
_BYTES_RECEIVED = SpeedportChildSensorDescription(
    key="bytes_received",
    name="Data received",
    field="bytes_received",
    transform=as_int,
    device_class=SensorDeviceClass.DATA_SIZE,
    native_unit_of_measurement=UnitOfInformation.BYTES,
    state_class=SensorStateClass.TOTAL_INCREASING,
)
_BYTES_SENT = SpeedportChildSensorDescription(
    key="bytes_sent",
    name="Data sent",
    field="bytes_sent",
    transform=as_int,
    device_class=SensorDeviceClass.DATA_SIZE,
    native_unit_of_measurement=UnitOfInformation.BYTES,
    state_class=SensorStateClass.TOTAL_INCREASING,
)
_TRAFFIC_FIELDS = (
    _DOWNLOAD_RATE,
    _UPLOAD_RATE,
    _BYTES_RECEIVED,
    _BYTES_SENT,
)

CHILD_SENSOR_COLLECTIONS: tuple[SpeedportChildSensorCollection, ...] = (
    SpeedportChildSensorCollection(
        kind="client",
        data_paths=("clients.items",),
        coordinator_group=NORMAL,
        fields=(
            _SIGNAL_DBM,
            _LINK_SPEED,
            _DOWNLOAD_LINK_SPEED,
            _UPLOAD_LINK_SPEED,
            *_TRAFFIC_FIELDS,
            _WIFI_GENERATION,
            SpeedportChildSensorDescription(
                key="wifi_standard",
                name="Wi-Fi standard",
                field="wifi_standard",
            ),
            SpeedportChildSensorDescription(
                key="connection_medium",
                name="Connection medium",
                field="medium",
            ),
            SpeedportChildSensorDescription(
                key="radio_band",
                name="Radio band",
                field="band",
            ),
            SpeedportChildSensorDescription(
                key="wifi_channel",
                name="Wi-Fi channel",
                field="channel",
                transform=as_int,
            ),
            SpeedportChildSensorDescription(
                key="last_seen",
                name="Last seen",
                field="last_seen",
                transform=as_datetime,
                device_class=SensorDeviceClass.TIMESTAMP,
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="mesh_node",
        data_paths=("mesh.nodes",),
        coordinator_group=NORMAL,
        fields=(
            _SIGNAL_DBM,
            _LINK_SPEED,
            _DOWNLOAD_LINK_SPEED,
            _UPLOAD_LINK_SPEED,
            *_TRAFFIC_FIELDS,
            SpeedportChildSensorDescription(
                key="radio_band",
                name="Radio band",
                field="band",
            ),
            SpeedportChildSensorDescription(
                key="wifi_channel",
                name="Wi-Fi channel",
                field="channel",
                transform=as_int,
            ),
            SpeedportChildSensorDescription(
                key="connected_clients",
                name="Connected clients",
                field="client_count",
                transform=as_int,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="mesh_parent",
                name="Mesh parent",
                field="parent",
                attribute_fields=("ipv4",),
            ),
            SpeedportChildSensorDescription(
                key="mesh_device_type",
                name="Mesh device type",
                field="device_type",
                transform=as_int,
            ),
            SpeedportChildSensorDescription(
                key="mesh_linked_lan_ports",
                name="Linked LAN ports",
                field="linked_lan_port_count",
                transform=as_int,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="connection_medium",
                name="Connection medium",
                field="medium",
            ),
            SpeedportChildSensorDescription(
                key="lan_port_1_speed",
                name="LAN port 1 link speed",
                field="lan_port_1_speed_bps",
                transform=as_mbit_per_second,
                device_class=SensorDeviceClass.DATA_RATE,
                native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="lan_port_2_speed",
                name="LAN port 2 link speed",
                field="lan_port_2_speed_bps",
                transform=as_mbit_per_second,
                device_class=SensorDeviceClass.DATA_RATE,
                native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="role",
                name="Mesh role",
                field="role",
            ),
            SpeedportChildSensorDescription(
                key="backhaul",
                name="Backhaul",
                field="backhaul",
            ),
            SpeedportChildSensorDescription(
                key="uptime",
                name="Uptime",
                field="uptime_seconds",
                transform=as_int,
                device_class=SensorDeviceClass.DURATION,
                native_unit_of_measurement=UnitOfTime.SECONDS,
                state_class=SensorStateClass.TOTAL,
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="powerline_node",
        data_paths=("powerline.nodes",),
        coordinator_group=NORMAL,
        fields=(
            _DOWNLOAD_LINK_SPEED,
            _UPLOAD_LINK_SPEED,
            SpeedportChildSensorDescription(
                key="powerline_mode",
                name="Powerline mode",
                field="mode",
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="telephone_line",
        data_paths=("telephony.numbers",),
        coordinator_group=NORMAL,
        fields=(
            SpeedportChildSensorDescription(
                key="call_state",
                name="Call state",
                field="call_state",
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="dect_handset",
        data_paths=("dect.handsets",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildSensorDescription(
                key="battery_level",
                name="Battery level",
                field="battery_percent",
                transform=as_percent,
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            _SIGNAL_DBM,
            SpeedportChildSensorDescription(
                key="signal_quality",
                name="Signal quality",
                field="signal_percent",
                transform=as_percent,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="call_state",
                name="Call state",
                field="call_state",
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="ip_phone",
        data_paths=("pbx.ip_phones",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildSensorDescription(
                key="call_state",
                name="Call state",
                field="call_state",
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="usb_device",
        data_paths=("usb.items",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildSensorDescription(
                key="capacity",
                name="Storage capacity",
                field="total_bytes",
                transform=as_int,
                device_class=SensorDeviceClass.DATA_SIZE,
                native_unit_of_measurement=UnitOfInformation.BYTES,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="used_space",
                name="Used space",
                field="used_bytes",
                transform=as_int,
                device_class=SensorDeviceClass.DATA_SIZE,
                native_unit_of_measurement=UnitOfInformation.BYTES,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="free_space",
                name="Free space",
                field="free_bytes",
                transform=as_int,
                device_class=SensorDeviceClass.DATA_SIZE,
                native_unit_of_measurement=UnitOfInformation.BYTES,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="storage_usage",
                name="Storage usage",
                field="usage_percent",
                transform=as_percent,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="temperature",
                name="Temperature",
                field="temperature_celsius",
                transform=as_float,
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement="°C",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
            SpeedportChildSensorDescription(
                key="media_type",
                name="Media type",
                field="media_type",
            ),
        ),
    ),
    SpeedportChildSensorCollection(
        kind="receiver",
        data_paths=("receiver.items", "receiver"),
        coordinator_group=NORMAL,
        fields=(
            SpeedportChildSensorDescription(
                key="network_type",
                name="Network type",
                field="network_type",
            ),
            SpeedportChildSensorDescription(
                key="operator",
                name="Network operator",
                field="operator",
            ),
            SpeedportChildSensorDescription(
                key="rsrp",
                name="RSRP",
                field="rsrp_dbm",
                transform=as_float,
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
            SpeedportChildSensorDescription(
                key="rsrq",
                name="RSRQ",
                field="rsrq_db",
                transform=as_float,
                native_unit_of_measurement="dB",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
            SpeedportChildSensorDescription(
                key="sinr",
                name="SINR",
                field="sinr_db",
                transform=as_float,
                native_unit_of_measurement="dB",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
            SpeedportChildSensorDescription(
                key="rssi",
                name="RSSI",
                field="rssi_dbm",
                transform=as_float,
                device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
            SpeedportChildSensorDescription(
                key="band",
                name="Radio band",
                field="band",
            ),
            SpeedportChildSensorDescription(
                key="frequency",
                name="Frequency",
                field="frequency_mhz",
                transform=as_float,
                device_class=SensorDeviceClass.FREQUENCY,
                native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
                state_class=SensorStateClass.MEASUREMENT,
            ),
            SpeedportChildSensorDescription(
                key="cell_id",
                name="Cell ID",
                field="cell_id",
            ),
            _LINK_SPEED,
            *_TRAFFIC_FIELDS,
            SpeedportChildSensorDescription(
                key="temperature",
                name="Temperature",
                field="temperature_celsius",
                transform=as_float,
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement="°C",
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
            ),
        ),
    ),
)

SENSOR_DESCRIPTIONS: tuple[SpeedportSensorEntityDescription, ...] = (
    # Internet/WAN totals, rates, capacity, utilization, and diagnostics.
    SpeedportSensorEntityDescription(
        key="wan_bytes_received",
        translation_key="wan_bytes_received",
        data_path="wan.bytes_received",
        capability="wan",
        coordinator_group=FAST,
        transform=as_gigabytes,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    SpeedportSensorEntityDescription(
        key="wan_bytes_sent",
        translation_key="wan_bytes_sent",
        data_path="wan.bytes_sent",
        capability="wan",
        coordinator_group=FAST,
        transform=as_gigabytes,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    SpeedportSensorEntityDescription(
        key="wan_packets_received",
        translation_key="wan_packets_received",
        data_path="wan.packets_received",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_packets_sent",
        translation_key="wan_packets_sent",
        data_path="wan.packets_sent",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_errors_received",
        translation_key="wan_errors_received",
        data_path="wan.errors_received",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_errors_sent",
        translation_key="wan_errors_sent",
        data_path="wan.errors_sent",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_discarded_packets_received",
        translation_key="wan_discarded_packets_received",
        data_path="wan.discard_packets_received",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_discarded_packets_sent",
        translation_key="wan_discarded_packets_sent",
        data_path="wan.discard_packets_sent",
        capability="wan",
        coordinator_group=FAST,
        native_unit_of_measurement="packets",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_download_rate",
        translation_key="wan_download_rate",
        data_path="wan.download_rate_bps",
        capability="wan",
        coordinator_group=FAST,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SpeedportSensorEntityDescription(
        key="wan_upload_rate",
        translation_key="wan_upload_rate",
        data_path="wan.upload_rate_bps",
        capability="wan",
        coordinator_group=FAST,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SpeedportSensorEntityDescription(
        key="wan_download_utilization",
        translation_key="wan_download_utilization",
        data_path="wan.download_utilization",
        capability="wan",
        coordinator_group=FAST,
        transform=as_percent,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="wan_upload_utilization",
        translation_key="wan_upload_utilization",
        data_path="wan.upload_utilization",
        capability="wan",
        coordinator_group=FAST,
        transform=as_percent,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="wan_download_capacity",
        translation_key="wan_download_capacity",
        data_path="internet.download_capacity_bps",
        capability="internet",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="wan_upload_capacity",
        translation_key="wan_upload_capacity",
        data_path="internet.upload_capacity_bps",
        capability="internet",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="internet_uptime",
        translation_key="internet_uptime",
        data_path="internet.uptime_seconds",
        capability="internet",
        coordinator_group=NORMAL,
        transform=as_int,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_connected_since",
        translation_key="internet_connected_since",
        data_path="internet.connected_since",
        capability="internet",
        coordinator_group=NORMAL,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_interface",
        translation_key="wan_interface",
        data_path="wan.interface.name",
        capability="wan",
        coordinator_group=FAST,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_interface_status",
        translation_key="wan_interface_status",
        data_path="wan.interface.status",
        capability="wan",
        coordinator_group=FAST,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wan_mtu",
        translation_key="wan_mtu",
        data_path="internet.mtu",
        capability="internet",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="public_ipv4",
        translation_key="public_ipv4",
        data_path="internet.ipv4_address",
        capability="internet",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="public_ipv6_prefix",
        translation_key="public_ipv6_prefix",
        data_path="internet.ipv6_prefix",
        capability="internet",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_ip_stack",
        translation_key="internet_ip_stack",
        data_path="internet.ip_stack",
        capability="internet",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_privacy_level",
        translation_key="internet_privacy_level",
        data_path="internet.privacy_level",
        capability="internet",
        coordinator_group=SLOW,
        transform=_code_enum(_INTERNET_PRIVACY_LEVELS),
        device_class=SensorDeviceClass.ENUM,
        options=["off", "level_1", "level_2"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_provisioning_code",
        translation_key="internet_provisioning_code",
        data_path="internet.provisioning_code",
        capability="internet",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_provider_family",
        translation_key="internet_provider_family",
        data_path="internet.provider_family",
        capability="internet",
        coordinator_group=NORMAL,
        device_class=SensorDeviceClass.ENUM,
        options=["telekom", "other"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="internet_error_code",
        translation_key="internet_error_code",
        data_path="internet.error_code",
        capability="internet",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # DSL/VDSL.
    SpeedportSensorEntityDescription(
        key="dsl_downstream",
        translation_key="dsl_downstream",
        data_path="dsl.downstream_bps",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_upstream",
        translation_key="dsl_upstream",
        data_path="dsl.upstream_bps",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_attainable_downstream",
        translation_key="dsl_attainable_downstream",
        data_path="dsl.attainable_downstream_bps",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_attainable_upstream",
        translation_key="dsl_attainable_upstream",
        data_path="dsl.attainable_upstream_bps",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_mbit_per_second,
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_snr_downstream",
        translation_key="dsl_snr_downstream",
        data_path="dsl.snr_downstream_db",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_snr_upstream",
        translation_key="dsl_snr_upstream",
        data_path="dsl.snr_upstream_db",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_attenuation_downstream",
        translation_key="dsl_attenuation_downstream",
        data_path="dsl.attenuation_downstream_db",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_attenuation_upstream",
        translation_key="dsl_attenuation_upstream",
        data_path="dsl.attenuation_upstream_db",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_crc_errors",
        translation_key="dsl_crc_errors",
        data_path="dsl.crc_errors",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_fec_errors",
        translation_key="dsl_fec_errors",
        data_path="dsl.fec_errors",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_error_seconds",
        translation_key="dsl_error_seconds",
        data_path="dsl.error_seconds",
        capability="dsl",
        coordinator_group=NORMAL,
        transform=as_int,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_profile",
        translation_key="dsl_profile",
        data_path="dsl.profile",
        capability="dsl",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dsl_error_code",
        translation_key="dsl_error_code",
        data_path="dsl.error_code",
        capability="dsl",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Hybrid and mobile receiver.
    SpeedportSensorEntityDescription(
        key="mobile_network_type",
        translation_key="mobile_network_type",
        data_path="mobile.network_type",
        capability="mobile",
        coordinator_group=NORMAL,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_status_code",
        translation_key="mobile_status_code",
        data_path="mobile.status_code",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_nr_signal",
        translation_key="mobile_nr_signal",
        data_path="mobile.nr.signal_dbm",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_nr_band",
        translation_key="mobile_nr_band",
        data_path="mobile.nr.band_code",
        capability="mobile",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_lte_signal",
        translation_key="mobile_lte_signal",
        data_path="mobile.lte.signal_dbm",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_lte_band",
        translation_key="mobile_lte_band",
        data_path="mobile.lte.band_code",
        capability="mobile",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_operator",
        translation_key="mobile_operator",
        data_path="mobile.operator",
        capability="mobile",
        coordinator_group=NORMAL,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_rsrp",
        translation_key="mobile_rsrp",
        data_path="mobile.rsrp_dbm",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_rsrq",
        translation_key="mobile_rsrq",
        data_path="mobile.rsrq_db",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_sinr",
        translation_key="mobile_sinr",
        data_path="mobile.sinr_db",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        native_unit_of_measurement="dB",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_rssi",
        translation_key="mobile_rssi",
        data_path="mobile.rssi_dbm",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_band",
        translation_key="mobile_band",
        data_path="mobile.band",
        capability="mobile",
        coordinator_group=NORMAL,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_frequency",
        translation_key="mobile_frequency",
        data_path="mobile.frequency_mhz",
        capability="mobile",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="mobile_cell_id",
        translation_key="mobile_cell_id",
        data_path="mobile.cell_id",
        capability="mobile",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_mode",
        translation_key="receiver_mode",
        data_path="receiver.mode",
        capability="receiver",
        coordinator_group=NORMAL,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_model",
        translation_key="receiver_model",
        data_path="receiver.model",
        capability="receiver",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_led_mode",
        translation_key="receiver_led_mode",
        data_path="receiver.led_mode",
        capability="receiver",
        coordinator_group=NORMAL,
        transform=_code_enum(_RECEIVER_LED_MODES),
        device_class=SensorDeviceClass.ENUM,
        options=["use_leds", "off_after_timeout", "disabled"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_firmware_version",
        translation_key="receiver_firmware_version",
        data_path="receiver.firmware_version",
        capability="receiver",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_latest_firmware",
        translation_key="receiver_latest_firmware",
        data_path="receiver.latest_firmware",
        capability="receiver",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="receiver_firmware_update_time",
        translation_key="receiver_firmware_update_time",
        data_path="receiver.firmware_update_time",
        capability="receiver",
        coordinator_group=SLOW,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="lte_tunnel_bytes_received",
        translation_key="lte_tunnel_bytes_received",
        data_path="hybrid.lte_tunnel_bytes_received",
        capability="hybrid",
        coordinator_group=FAST,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="lte_tunnel_bytes_sent",
        translation_key="lte_tunnel_bytes_sent",
        data_path="hybrid.lte_tunnel_bytes_sent",
        capability="hybrid",
        coordinator_group=FAST,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Wi-Fi, Mesh, LAN and DHCP counts.
    SpeedportSensorEntityDescription(
        key="wifi_2_4_clients",
        translation_key="wifi_2_4_clients",
        data_path="wifi.radio_2_4.client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_5_clients",
        translation_key="wifi_5_clients",
        data_path="wifi.radio_5.client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_guest_clients",
        translation_key="wifi_guest_clients",
        data_path="wifi.guest.client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_guest_2_4_clients",
        translation_key="wifi_guest_2_4_clients",
        data_path="wifi.guest.radio_2_4_client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_guest_5_clients",
        translation_key="wifi_guest_5_clients",
        data_path="wifi.guest.radio_5_client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    *(
        SpeedportSensorEntityDescription(
            key=f"wifi_guest_wifi_{generation}_clients",
            translation_key=f"wifi_guest_wifi_{generation}_clients",
            data_path=f"wifi.guest.wifi_{generation}_client_count",
            capability="wifi",
            coordinator_group=NORMAL,
            transform=as_int,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        )
        for generation in (4, 5, 6)
    ),
    SpeedportSensorEntityDescription(
        key="wifi_office_clients",
        translation_key="wifi_office_clients",
        data_path="wifi.office.client_count",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_guest_remaining_time",
        translation_key="wifi_guest_remaining_time",
        data_path="wifi.guest.remaining_minutes",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_2_4_channel",
        translation_key="wifi_2_4_channel",
        data_path="wifi.radio_2_4.channel",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_5_channel",
        translation_key="wifi_5_channel",
        data_path="wifi.radio_5.channel",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=as_int,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_5_channel_width",
        translation_key="wifi_5_channel_width",
        data_path="wifi.radio_5.channel_width_mode",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=SensorDeviceClass.ENUM,
        options=["single_channel", "40_mhz", "80_mhz", "160_mhz"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_band_mode",
        translation_key="wifi_band_mode",
        data_path="wifi.band_mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=_code_enum(_WIFI_BAND_MODES),
        device_class=SensorDeviceClass.ENUM,
        options=["both_bands", "2_4_ghz_only", "5_ghz_only"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_wps_state_code",
        translation_key="wifi_wps_state_code",
        data_path="wifi.wps_state_code",
        capability="wifi",
        coordinator_group=NORMAL,
        transform=_code_enum(_WIFI_WPS_STATES),
        device_class=SensorDeviceClass.ENUM,
        options=["failed", "successful", "in_progress"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_2_4_encryption_mode",
        translation_key="wifi_2_4_encryption_mode",
        data_path="wifi.radio_2_4.encryption_mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_5_encryption_mode",
        translation_key="wifi_5_encryption_mode",
        data_path="wifi.radio_5.encryption_mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_guest_encryption_mode",
        translation_key="wifi_guest_encryption_mode",
        data_path="wifi.guest.encryption_mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_office_encryption_mode",
        translation_key="wifi_office_encryption_mode",
        data_path="wifi.office.encryption_mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_schedule_mode",
        translation_key="wifi_schedule_mode",
        data_path="wifi.schedule.mode",
        capability="wifi",
        coordinator_group=SLOW,
        transform=_code_enum(_WIFI_SCHEDULE_MODES),
        device_class=SensorDeviceClass.ENUM,
        options=["disabled", "daily", "weekly"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_schedule_daily_from",
        translation_key="wifi_schedule_daily_from",
        data_path="wifi.schedule.daily_from",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_schedule_daily_to",
        translation_key="wifi_schedule_daily_to",
        data_path="wifi.schedule.daily_to",
        capability="wifi",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="wifi_schedule_weekly",
        translation_key="wifi_schedule_weekly",
        data_path="wifi.schedule.weekly_day_count",
        capability="wifi",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="mesh_nodes",
        translation_key="mesh_nodes",
        data_path="mesh.nodes",
        capability=("mesh", "mesh_topology"),
        coordinator_group=NORMAL,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="mesh_clients",
        translation_key="mesh_clients",
        data_path="mesh.client_count",
        capability="mesh",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="connected_clients",
        translation_key="connected_clients",
        data_path="clients.connected_count",
        capability="clients",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="dhcp_leases",
        translation_key="dhcp_leases",
        data_path="dhcp.leases",
        capability="dhcp",
        coordinator_group=SLOW,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="lan_linked_ports",
        translation_key="lan_linked_ports",
        data_path="lan.linked_port_count",
        capability="lan",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    *(
        SpeedportSensorEntityDescription(
            key=f"lan_port_{port}_speed",
            translation_key=f"lan_port_{port}_speed",
            data_path=f"lan.ports.port_{port}.speed_bps",
            capability="lan",
            coordinator_group=NORMAL,
            transform=as_mbit_per_second,
            device_class=SensorDeviceClass.DATA_RATE,
            native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            suggested_display_precision=0,
        )
        for port in range(1, 5)
    ),
    SpeedportSensorEntityDescription(
        key="lan_ipv4_address",
        translation_key="lan_ipv4_address",
        data_path="lan.ipv4_address",
        capability="lan",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="lan_subnet_mask",
        translation_key="lan_subnet_mask",
        data_path="lan.subnet_mask",
        capability="lan",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="lan_ula_address",
        translation_key="lan_ula_address",
        data_path="lan.ula_address",
        capability="lan",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="lan_usable_ipv6_range",
        translation_key="lan_usable_ipv6_range",
        data_path="lan.usable_ipv6_range",
        capability="lan",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dhcp_pool_size",
        translation_key="dhcp_pool_size",
        data_path="dhcp.pool_size",
        capability="dhcp",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dhcp_lease_duration_code",
        translation_key="dhcp_lease_duration_code",
        data_path="dhcp.lease_duration_code",
        capability="dhcp",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Network services and access policy.
    SpeedportSensorEntityDescription(
        key="port_forward_rules",
        translation_key="port_forward_rules",
        data_path="nat.port_forward_rules",
        capability="nat",
        coordinator_group=SLOW,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="upnp_mappings",
        translation_key="upnp_mappings",
        data_path="nat.upnp_mappings",
        capability="nat",
        coordinator_group=SLOW,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="ddns_provider",
        translation_key="ddns_provider",
        data_path="ddns.provider",
        capability="ddns",
        coordinator_group=SLOW,
    ),
    SpeedportSensorEntityDescription(
        key="ddns_update_protocol",
        translation_key="ddns_update_protocol",
        data_path="ddns.update_protocol",
        capability="ddns",
        coordinator_group=SLOW,
        device_class=SensorDeviceClass.ENUM,
        options=["http", "https"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="ddns_update_port",
        translation_key="ddns_update_port",
        data_path="ddns.update_port",
        capability="ddns",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="ddns_status",
        translation_key="ddns_status",
        data_path="ddns.status_code",
        capability="ddns",
        coordinator_group=SLOW,
        transform=_code_enum(_DDNS_STATES),
        device_class=SensorDeviceClass.ENUM,
        options=["not_registered", "error", "registered"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="ddns_last_update",
        translation_key="ddns_last_update",
        data_path="ddns.last_update",
        capability="ddns",
        coordinator_group=SLOW,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SpeedportSensorEntityDescription(
        key="vpn_peers",
        translation_key="vpn_peers",
        data_path="vpn.peers",
        capability="vpn",
        coordinator_group=SLOW,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="vpn_connected_peers",
        translation_key="vpn_connected_peers",
        data_path="vpn.connected_peer_count",
        capability="vpn",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="vpn_type",
        translation_key="vpn_type",
        data_path="vpn.type",
        capability="vpn",
        coordinator_group=SLOW,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="parental_profiles",
        translation_key="parental_profiles",
        data_path="parental.profiles",
        capability="parental",
        coordinator_group=SLOW,
        transform=count_items,
    ),
    SpeedportSensorEntityDescription(
        key="parental_blocked_clients",
        translation_key="parental_blocked_clients",
        data_path="parental.blocked_client_count",
        capability="parental",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="dns_rebind_exceptions",
        translation_key="dns_rebind_exceptions",
        data_path="security.dns_rebind_exception_count",
        capability="security",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="port_block_rules",
        translation_key="port_block_rules",
        data_path="security.port_block_rule_count",
        capability="security",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="active_port_block_rules",
        translation_key="active_port_block_rules",
        data_path="security.active_port_block_rule_count",
        capability="security",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="qos_prioritized_clients",
        translation_key="qos_prioritized_clients",
        data_path="qos.prioritized_client_count",
        capability="qos",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # Telephony, PBX and DECT.
    SpeedportSensorEntityDescription(
        key="telephone_numbers_registered",
        translation_key="telephone_numbers_registered",
        data_path="telephony.registered_number_count",
        capability="telephony",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_voip_policy",
        translation_key="telephony_voip_policy",
        data_path="telephony.voip_policy",
        capability="telephony",
        coordinator_group=SLOW,
        transform=_code_enum(_TELEPHONY_VOIP_POLICIES),
        device_class=SensorDeviceClass.ENUM,
        options=["off", "level_1", "level_2"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_provisioning_code",
        translation_key="telephony_provisioning_code",
        data_path="telephony.provisioning_code",
        capability="telephony",
        coordinator_group=NORMAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_provider_family",
        translation_key="telephony_provider_family",
        data_path="telephony.provider_family",
        capability="telephony",
        coordinator_group=NORMAL,
        device_class=SensorDeviceClass.ENUM,
        options=["telekom", "other"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_providers",
        translation_key="telephony_providers",
        data_path="telephony.provider_count",
        capability="telephony",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_configured_numbers",
        translation_key="telephony_configured_numbers",
        data_path="telephony.configured_number_count",
        capability="telephony",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_registered_voip_numbers",
        translation_key="telephony_registered_voip_numbers",
        data_path="telephony.registered_voip_number_count",
        capability="telephony",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_inactive_voip_numbers",
        translation_key="telephony_inactive_voip_numbers",
        data_path="telephony.inactive_voip_number_count",
        capability="telephony",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_warning_voip_numbers",
        translation_key="telephony_warning_voip_numbers",
        data_path="telephony.warning_voip_number_count",
        capability="telephony",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="telephony_failed_lines",
        translation_key="telephony_failed_lines",
        data_path="telephony.failed_line_count",
        capability="telephony",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="missed_calls",
        translation_key="missed_calls",
        data_path="telephony.missed_call_count",
        capability="telephony",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.TOTAL,
    ),
    SpeedportSensorEntityDescription(
        key="last_call",
        translation_key="last_call",
        data_path="telephony.last_call.timestamp",
        capability="telephony",
        coordinator_group=NORMAL,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SpeedportSensorEntityDescription(
        key="ip_phones",
        translation_key="ip_phones",
        data_path="pbx.ip_phones",
        capability="pbx",
        coordinator_group=SLOW,
        transform=count_items,
    ),
    SpeedportSensorEntityDescription(
        key="pbx_configured_clients",
        translation_key="pbx_configured_clients",
        data_path="pbx.configured_client_count",
        capability="pbx",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="pbx_disconnected_clients",
        translation_key="pbx_disconnected_clients",
        data_path="pbx.disconnected_client_count",
        capability="pbx",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="pbx_registered_clients",
        translation_key="pbx_registered_clients",
        data_path="pbx.registered_client_count",
        capability="pbx",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="pbx_locked_clients",
        translation_key="pbx_locked_clients",
        data_path="pbx.locked_client_count",
        capability="pbx",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="dect_handsets",
        translation_key="dect_handsets",
        data_path="dect.handset_count",
        capability="dect",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="dect_repeaters",
        translation_key="dect_repeaters",
        data_path="dect.repeater_count",
        capability="dect",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="phonebooks",
        translation_key="phonebooks",
        data_path="dect.phonebooks",
        capability="dect",
        coordinator_group=SLOW,
        transform=count_items,
    ),
    SpeedportSensorEntityDescription(
        key="phonebook_entries",
        translation_key="phonebook_entries",
        data_path="dect.phonebook_entry_count",
        capability="dect",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # USB, system, firmware and diagnostics.
    SpeedportSensorEntityDescription(
        key="usb_devices",
        translation_key="usb_devices",
        data_path="usb.items",
        capability="usb",
        coordinator_group=SLOW,
        transform=count_items,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SpeedportSensorEntityDescription(
        key="dect_paging_handsets",
        translation_key="dect_paging_handsets",
        data_path="dect.paging_handset_count",
        capability="dect",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="usb_tethering_status",
        translation_key="usb_tethering_status",
        data_path="usb.tethering_status_code",
        capability="usb",
        coordinator_group=SLOW,
        transform=as_int,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="usb_storage_devices",
        translation_key="usb_storage_devices",
        data_path="usb.storage_device_count",
        capability="usb",
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="media_server_folders",
        translation_key="media_server_folders",
        data_path="usb.media_share_count",
        capability=("usb", "media_server"),
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="media_server_active_folders",
        translation_key="media_server_active_folders",
        data_path="usb.active_media_share_count",
        capability=("usb", "media_server"),
        coordinator_group=SLOW,
        transform=as_int,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="usb_storage_total",
        translation_key="usb_storage_total",
        data_path="usb.storage_total_bytes",
        capability="usb",
        coordinator_group=SLOW,
        transform=as_int,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="usb_storage_used",
        translation_key="usb_storage_used",
        data_path="usb.storage_used_bytes",
        capability="usb",
        coordinator_group=SLOW,
        transform=as_int,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="usb_storage_free",
        translation_key="usb_storage_free",
        data_path="usb.storage_free_bytes",
        capability="usb",
        coordinator_group=SLOW,
        transform=as_int,
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="system_uptime",
        translation_key="system_uptime",
        data_path="system.uptime_seconds",
        capability="system",
        coordinator_group=NORMAL,
        transform=as_int,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL,
    ),
    SpeedportSensorEntityDescription(
        key="system_operating_mode",
        translation_key="system_operating_mode",
        data_path="system.operating_mode",
        capability="system",
        coordinator_group=NORMAL,
        device_class=SensorDeviceClass.ENUM,
        options=[
            "normal",
            "thrown",
            "modem",
            "tr64",
            "tr69",
            "emergency_call",
            "dect_update",
            "botnet_protection",
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="system_temperature",
        translation_key="system_temperature",
        data_path="system.temperature_celsius",
        capability="system",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement="°C",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
    ),
    SpeedportSensorEntityDescription(
        key="system_cpu",
        translation_key="system_cpu",
        data_path="system.cpu_percent",
        capability="system",
        coordinator_group=NORMAL,
        transform=as_percent,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="system_memory",
        translation_key="system_memory",
        data_path="system.memory_percent",
        capability="system",
        coordinator_group=NORMAL,
        transform=as_percent,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="firmware_update_time",
        translation_key="firmware_update_time",
        data_path="system.update_time",
        capability="system",
        coordinator_group=SLOW,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="request_latency",
        translation_key="request_latency",
        data_path="diagnostics.request_latency_ms",
        capability="diagnostics",
        coordinator_group=NORMAL,
        transform=as_float,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
    ),
    SpeedportSensorEntityDescription(
        key="update_failures",
        translation_key="update_failures",
        data_path="diagnostics.update_failures",
        capability="diagnostics",
        coordinator_group=NORMAL,
        transform=as_int,
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportSensorEntityDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        data_path="diagnostics.last_successful_update",
        capability="diagnostics",
        coordinator_group=NORMAL,
        transform=as_datetime,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _discoverable_fixed_sensor_descriptions(
    hub: SpeedportHub,
    group: PollGroup,
    known: set[str],
) -> tuple[SpeedportSensorEntityDescription, ...]:
    """Return newly supported fixed sensors for one polling group."""
    return tuple(
        description
        for description in SENSOR_DESCRIPTIONS
        if description.coordinator_group is group
        and description.key not in known
        and supported(hub, description.capability, description.data_path)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors exposed by this router."""
    del hass
    hub = entry.runtime_data
    known_fixed: set[str] = set()

    @callback
    def discover_fixed_sensors(group: PollGroup) -> None:
        descriptions = _discoverable_fixed_sensor_descriptions(hub, group, known_fixed)
        if not descriptions:
            return
        known_fixed.update(description.key for description in descriptions)
        async_add_entities(
            SpeedportSensor(hub, description) for description in descriptions
        )

    for group in {description.coordinator_group for description in SENSOR_DESCRIPTIONS}:
        discover_fixed_sensors(group)

        @callback
        def rediscover_fixed(group: PollGroup = group) -> None:
            discover_fixed_sensors(group)

        entry.async_on_unload(
            coordinator(hub, group).async_add_listener(rediscover_fixed)
        )

    wan_telemetry_added = False

    @callback
    def discover_wan_telemetry_sensors() -> None:
        nonlocal wan_telemetry_added
        if wan_telemetry_added or not hub.has_capability("wan_counters"):
            return
        wan_telemetry_added = True
        async_add_entities(
            SpeedportWanTelemetrySensor(hub, description)
            for description in WAN_TELEMETRY_SENSOR_DESCRIPTIONS
        )

    discover_wan_telemetry_sensors()
    entry.async_on_unload(
        coordinator(hub, PollGroup.FAST).async_add_listener(
            discover_wan_telemetry_sensors
        )
    )

    if hub.has_capability("diagnostics"):
        async_add_entities(
            [
                SpeedportManagementAccessSensor(hub),
                SpeedportEndpointFailureSensor(hub),
                *(
                    SpeedportPollingHealthSensor(hub, description)
                    for description in POLLING_HEALTH_SENSOR_DESCRIPTIONS
                ),
            ]
        )

    known: set[tuple[str, str, str]] = set()

    @callback
    def discover_child_sensors(group: PollGroup) -> None:
        new_entities: list[SpeedportChildSensor] = []
        for child_spec in CHILD_SENSOR_COLLECTIONS:
            if child_spec.coordinator_group is not group:
                continue
            for item in child_collection(hub, child_spec.data_paths):
                identifier = stable_id(item)
                if identifier is None:
                    continue
                for field in child_spec.fields:
                    marker = (child_spec.kind, identifier, field.key)
                    if (
                        marker in known
                        or field.field not in item
                        or item[field.field] is None
                    ):
                        continue
                    device = speedport_child_device(child_spec.kind, item)
                    if device is None:
                        continue
                    known.add(marker)
                    new_entities.append(
                        SpeedportChildSensor(
                            hub,
                            child_spec,
                            field,
                            identifier,
                            device,
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    for group in {spec.coordinator_group for spec in CHILD_SENSOR_COLLECTIONS}:
        discover_child_sensors(group)

        @callback
        def rediscover(group: PollGroup = group) -> None:
            discover_child_sensors(group)

        entry.async_on_unload(coordinator(hub, group).async_add_listener(rediscover))


class SpeedportSensor(SpeedportEntity, SensorEntity):
    """Sensor backed by normalized hub data."""

    _attr_entity_registry_enabled_default = True
    _unrecorded_attributes = frozenset({"rate_sample_span_seconds"})
    entity_description: SpeedportSensorEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return current normalized value."""
        description = self.entity_description
        return value(
            hub=self.hub,
            data_path=description.data_path,
            transform=description.transform,
        )

    @property
    def available(self) -> bool:
        """Fail closed when a firmware enum code is outside its contract."""
        if self.entity_description.key == "update_failures":
            return self.native_value is not None
        if not super().available:
            return False
        description = self.entity_description
        if (
            description.key in _WAN_INTERFACE_SENSOR_KEYS
            and self.hub.has_endpoint_error("wan_counters")
        ):
            return False
        if description.device_class is not SensorDeviceClass.ENUM:
            return True
        return self.native_value in (description.options or ())

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return bounded metadata for compound read-only sensors."""
        if self.entity_description.key in {"wan_download_rate", "wan_upload_rate"}:
            telemetry = self.hub.wan_counter_telemetry
            return {
                "rate_method": telemetry.get("rate_method"),
                "rate_sample_span_seconds": telemetry.get("rate_sample_span_seconds"),
            }
        if self.entity_description.key == "wan_interface":
            interface_attributes = {
                key: self.hub.get(("wan", "interface", key))
                for key in ("index", "alias")
            }
            return {
                key: item
                for key, item in interface_attributes.items()
                if item is not None
            }
        if self.entity_description.key == "wifi_schedule_weekly":
            weekly = self.hub.get("wifi.schedule.weekly")
            if not isinstance(weekly, Mapping):
                return None
            schedule_attributes: dict[str, str] = {}
            for day in _WIFI_SCHEDULE_DAYS:
                window = weekly.get(day)
                if not isinstance(window, Mapping):
                    continue
                for boundary in ("from", "to"):
                    clock_time = window.get(boundary)
                    if isinstance(clock_time, str):
                        schedule_attributes[f"{day}_{boundary}"] = clock_time
            return schedule_attributes
        if self.entity_description.key == "dhcp_pool_size":
            pool_attributes = {
                "start_ipv4": self.hub.get("dhcp.pool_start_ipv4"),
                "end_ipv4": self.hub.get("dhcp.pool_end_ipv4"),
            }
            return {
                key: item for key, item in pool_attributes.items() if item is not None
            }
        if self.entity_description.key == "update_failures":
            failure_attributes: dict[str, Any] = {}
            if failed_group := self.hub.get("diagnostics.failed_group"):
                failure_attributes["last_failed_group"] = failed_group
            if last_error := self.hub.get("diagnostics.last_error"):
                failure_attributes["last_error_class"] = safe_error_class_name(
                    last_error
                )
            return {
                key: item
                for key, item in failure_attributes.items()
                if item is not None
            }
        return None

    async def async_added_to_hass(self) -> None:
        """Refresh the cross-group failure aggregate after every poll group."""
        await super().async_added_to_hass()
        if self.entity_description.key != "update_failures":
            return
        for group in (PollGroup.FAST, PollGroup.SLOW):
            self.async_on_remove(
                coordinator(self.hub, group).async_add_listener(
                    self.async_write_ha_state
                )
            )


class SpeedportWanTelemetrySensor(SpeedportEntity, SensorEntity):
    """Expose the adaptive WAN scheduler as read-only diagnostic state."""

    _attr_entity_registry_enabled_default = True
    _unrecorded_attributes = frozenset(
        {
            "retry_in_seconds",
            "success_streak",
            "observed_interval_seconds",
            "rate_sample_span_seconds",
            "polling_focus",
            "background_refresh_deferred",
        }
    )
    entity_description: SensorEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize WAN telemetry diagnostic sensor."""
        super().__init__(
            hub,
            coordinator(hub, PollGroup.FAST),
            description.key,
        )
        self.entity_description = description

    @property
    def _telemetry(self) -> Mapping[str, Any]:
        return self.hub.wan_counter_telemetry

    @property
    def native_value(self) -> Any:
        """Return one UI-safe scheduler value from hub diagnostics."""
        key = self.entity_description.key
        value_key = _WAN_TELEMETRY_KEY_BY_ENTITY[key]
        raw = self._telemetry.get(value_key)
        if key == "wan_last_sample":
            sampled_at = as_datetime(raw) if raw is not None else None
            return (
                sampled_at.replace(second=0, microsecond=0)
                if sampled_at is not None
                else None
            )
        if key in {"wan_polling_interval", "wan_fastest_proven_interval"}:
            return as_float(raw) if raw is not None else None
        return str(raw) if raw is not None else None

    @property
    def available(self) -> bool:
        """Require a retained WAN capability and a valid diagnostic value."""
        if not self.hub.has_capability("wan_counters"):
            return False
        value_now = self.native_value
        if value_now is None:
            return False
        if (
            self.entity_description.key == "wan_fastest_proven_interval"
            and self._telemetry.get("last_sampled_at") is None
        ):
            return False
        if self.entity_description.device_class is not SensorDeviceClass.ENUM:
            return True
        return value_now in (self.entity_description.options or ())

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Expose scheduler learning evidence on its state entity."""
        if self.entity_description.key != "wan_polling_state":
            return None
        telemetry = self._telemetry
        attributes = {
            key: telemetry[key]
            for key in (
                "mode",
                "target_interval_seconds",
                "runtime_floor_seconds",
                "last_stable_interval_seconds",
                "retry_in_seconds",
                "success_streak",
                "success_samples_required",
                "cooldown_seconds",
                "rate_method",
                "polling_focus",
                "background_refresh_deferred",
            )
            if telemetry.get(key) is not None
        }
        attributes["source_available"] = not self.hub.has_endpoint_error("wan_counters")
        attributes["observed_interval_seconds"] = telemetry.get(
            "observed_interval_seconds"
        )
        attributes["rate_sample_span_seconds"] = telemetry.get(
            "rate_sample_span_seconds"
        )
        return attributes


class SpeedportPollingHealthSensor(SpeedportEntity, SensorEntity):
    """Expose one coordinator's health without hiding its failure state."""

    _attr_entity_registry_enabled_default = True
    entity_description: SensorEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize polling-group health."""
        group = _POLLING_HEALTH_GROUP_BY_KEY[description.key]
        super().__init__(hub, coordinator(hub, group), description.key)
        self._group = group
        self.entity_description = description

    @property
    def native_value(self) -> str:
        """Return a bounded health state."""
        return str(self.hub.poll_group_health(self._group)["state"])

    @property
    def available(self) -> bool:
        """Remain visible specifically so a failed coordinator can be explained."""
        return True

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return bounded scheduling and failure metadata."""
        attributes: dict[str, Any] = {}
        if self.coordinator.update_interval is not None:
            attributes["update_interval_seconds"] = (
                self.coordinator.update_interval.total_seconds()
            )
        health = self.hub.poll_group_health(self._group)
        if health["state"] == "failed":
            if last_success := health["last_successful_update"]:
                attributes["last_successful_update"] = last_success
            if last_error := health["last_error_class"]:
                attributes["last_error_class"] = safe_error_class_name(last_error)
        return attributes


class SpeedportEndpointFailureSensor(SpeedportEntity, SensorEntity):
    """Expose bounded endpoint failure metadata without raw exception text."""

    _attr_entity_registry_enabled_default = True
    entity_description = ENDPOINT_FAILURE_SENSOR_DESCRIPTION

    def __init__(self, hub: SpeedportHub) -> None:
        """Initialize the endpoint failure count."""
        super().__init__(
            hub,
            coordinator(hub, PollGroup.FAST),
            self.entity_description.key,
        )

    @property
    def native_value(self) -> int:
        """Return the number of currently failed semantic endpoint families."""
        return len(self.hub.endpoint_errors)

    @property
    def available(self) -> bool:
        """Remain visible while any polling group is unavailable."""
        return True

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return sorted semantic family names and exception classes only."""
        failures = {
            family: safe_error_class_name(error_name)
            for family, error_name in sorted(self.hub.endpoint_errors.items())
        }
        return {"failures": failures}

    async def async_added_to_hass(self) -> None:
        """Refresh this aggregate when any polling group changes."""
        await super().async_added_to_hass()
        for group in (PollGroup.NORMAL, PollGroup.SLOW):
            self.async_on_remove(
                coordinator(self.hub, group).async_add_listener(
                    self.async_write_ha_state
                )
            )


class SpeedportManagementAccessSensor(SpeedportEntity, SensorEntity):
    """Explain whether protected router data can currently be read."""

    _attr_translation_key = "management_access"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: SpeedportHub) -> None:
        """Initialize the always-visible management access sensor."""
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            "management_access",
            data_path="management.access.state",
        )
        self._attr_options = [
            "available",
            "blocked",
            "locked",
            "other_session",
            "recovering",
            "unavailable",
            "unknown",
        ]

    @property
    def native_value(self) -> str | None:
        """Return the normalized management access state."""
        state = self.hub.get("management.access.state")
        return str(state) if state is not None else None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Expose local ownership and safe recovery guidance."""
        access: Any = self.hub.get("management.access", {})
        if not isinstance(access, Mapping):
            return {}
        return {
            "owner_ip_address": access.get("owner_ip_address"),
            "retry_after_seconds": access.get("retry_after_seconds"),
            "browser_logout_required": access.get("browser_logout_required"),
            "controls_available": self.hub.management_controls_available,
            "last_changed": access.get("last_changed"),
            "last_successful_update": access.get("last_successful_update"),
        }


class SpeedportChildSensor(SpeedportEntity, SensorEntity):
    """Enabled sensor for one stable router child."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        hub: SpeedportHub,
        collection_spec: SpeedportChildSensorCollection,
        description: SpeedportChildSensorDescription,
        identifier: str,
        device: SpeedportDevice,
    ) -> None:
        """Initialize a field-backed child sensor."""
        super().__init__(
            hub,
            coordinator(hub, collection_spec.coordinator_group),
            description.key,
            device=device,
        )
        self._collection_spec = collection_spec
        self._field_description = description
        self._child_identifier = identifier
        self._attr_translation_key = description.key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_suggested_display_precision = description.suggested_display_precision

    @property
    def _item(self) -> Mapping[str, Any] | None:
        """Return the current normalized child payload."""
        return child_item(
            self.hub,
            self._collection_spec.data_paths,
            self._child_identifier,
        )

    @property
    def available(self) -> bool:
        """Return whether this field remains available on the child."""
        if not super().available:
            return False
        item = self._item
        return (
            item is not None
            and self._field_description.field in item
            and item[self._field_description.field] is not None
        )

    @property
    def native_value(self) -> Any:
        """Return and safely transform the current child field."""
        item = self._item
        if item is None:
            return None
        raw = item.get(self._field_description.field)
        transform = self._field_description.transform
        if raw is None or transform is None:
            return raw
        try:
            return transform(raw)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Expose explicitly allowlisted child metadata."""
        item = self._item
        if item is None or not self._field_description.attribute_fields:
            return None
        return {
            key: item[key]
            for key in self._field_description.attribute_fields
            if item.get(key) is not None
        }
