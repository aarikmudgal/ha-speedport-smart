"""Capability-gated binary sensors for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .coordinator import PollGroup
from .entity import SpeedportDevice, SpeedportEntity
from .platform_helpers import (
    as_bool,
    child_collection,
    child_item,
    coordinator,
    speedport_child_device,
    stable_id,
    supported,
    value,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


@dataclass(frozen=True, kw_only=True)
class SpeedportBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a normalized Speedport binary sensor."""

    data_path: str
    capability: str
    coordinator_group: PollGroup


@dataclass(frozen=True, slots=True)
class SpeedportChildBinarySensorDescription:
    """Describe one optional boolean field on a router child device."""

    key: str
    name: str
    field: str
    device_class: BinarySensorDeviceClass | None = None


@dataclass(frozen=True, slots=True)
class SpeedportChildBinarySensorCollection:
    """Describe one normalized collection of router child devices."""

    kind: str
    data_paths: tuple[str, ...]
    coordinator_group: PollGroup
    fields: tuple[SpeedportChildBinarySensorDescription, ...]


FAST = PollGroup.FAST
NORMAL = PollGroup.NORMAL
SLOW = PollGroup.SLOW

_CONNECTED = SpeedportChildBinarySensorDescription(
    key="connected",
    name="Connected",
    field="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)
_ACTIVE_CALL = SpeedportChildBinarySensorDescription(
    key="active_call",
    name="Active call",
    field="active_call",
    device_class=BinarySensorDeviceClass.RUNNING,
)

CHILD_BINARY_SENSOR_COLLECTIONS: tuple[SpeedportChildBinarySensorCollection, ...] = (
    SpeedportChildBinarySensorCollection(
        kind="client",
        data_paths=("clients.items",),
        coordinator_group=NORMAL,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="internet_paused",
                name="Internet paused",
                field="internet_paused",
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="mesh_node",
        data_paths=("mesh.nodes",),
        coordinator_group=SLOW,
        fields=(_CONNECTED,),
    ),
    SpeedportChildBinarySensorCollection(
        kind="telephone_line",
        data_paths=("telephony.numbers",),
        coordinator_group=NORMAL,
        fields=(
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            SpeedportChildBinarySensorDescription(
                key="enabled",
                name="Enabled",
                field="enabled",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
            _ACTIVE_CALL,
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="dect_handset",
        data_paths=("dect.handsets",),
        coordinator_group=SLOW,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            _ACTIVE_CALL,
            SpeedportChildBinarySensorDescription(
                key="charging",
                name="Charging",
                field="charging",
                device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="ip_phone",
        data_paths=("pbx.ip_phones",),
        coordinator_group=SLOW,
        fields=(
            _CONNECTED,
            SpeedportChildBinarySensorDescription(
                key="registered",
                name="Registered",
                field="registered",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            ),
            _ACTIVE_CALL,
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="usb_device",
        data_paths=("usb.items",),
        coordinator_group=SLOW,
        fields=(
            SpeedportChildBinarySensorDescription(
                key="connected",
                name="Connected",
                field="connected",
                device_class=BinarySensorDeviceClass.PLUG,
            ),
            SpeedportChildBinarySensorDescription(
                key="mounted",
                name="Mounted",
                field="mounted",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        ),
    ),
    SpeedportChildBinarySensorCollection(
        kind="receiver",
        data_paths=("receiver.items", "receiver"),
        coordinator_group=NORMAL,
        fields=(_CONNECTED,),
    ),
)

BINARY_SENSOR_DESCRIPTIONS: tuple[SpeedportBinarySensorEntityDescription, ...] = (
    SpeedportBinarySensorEntityDescription(
        key="internet_connected",
        translation_key="internet_connected",
        data_path="internet.state",
        capability="internet",
        coordinator_group=FAST,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dsl_connected",
        translation_key="dsl_connected",
        data_path="dsl.state",
        capability="dsl",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="hybrid_connected",
        translation_key="hybrid_connected",
        data_path="hybrid.connected",
        capability="hybrid",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="mobile_connected",
        translation_key="mobile_connected",
        data_path="mobile.connected",
        capability="mobile",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_2_4_enabled",
        translation_key="wifi_2_4_enabled",
        data_path="wifi.radio_2_4.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="wifi_5_enabled",
        translation_key="wifi_5_enabled",
        data_path="wifi.radio_5.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="guest_wifi_enabled",
        translation_key="guest_wifi_enabled",
        data_path="wifi.guest.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="office_wifi_enabled",
        translation_key="office_wifi_enabled",
        data_path="wifi.office.enabled",
        capability="wifi",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="mesh_enabled",
        translation_key="mesh_enabled",
        data_path="mesh.enabled",
        capability="mesh",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dhcp_enabled",
        translation_key="dhcp_enabled",
        data_path="dhcp.enabled",
        capability="dhcp",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="upnp_enabled",
        translation_key="upnp_enabled",
        data_path="nat.upnp_enabled",
        capability="nat",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="ddns_connected",
        translation_key="ddns_connected",
        data_path="ddns.connected",
        capability="ddns",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=False,
    ),
    SpeedportBinarySensorEntityDescription(
        key="vpn_connected",
        translation_key="vpn_connected",
        data_path="vpn.connected",
        capability="vpn",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="parental_controls_enabled",
        translation_key="parental_controls_enabled",
        data_path="parental.enabled",
        capability="parental",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="telephony_registered",
        translation_key="telephony_registered",
        data_path="telephony.registered",
        capability="telephony",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    SpeedportBinarySensorEntityDescription(
        key="active_call",
        translation_key="active_call",
        data_path="telephony.active_call",
        capability="telephony",
        coordinator_group=FAST,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dect_enabled",
        translation_key="dect_enabled",
        data_path="dect.enabled",
        capability="dect",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firewall_enabled",
        translation_key="firewall_enabled",
        data_path="security.firewall_enabled",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.SAFETY,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="dns_rebind_protection",
        translation_key="dns_rebind_protection",
        data_path="security.dns_rebind_protection",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.SAFETY,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="remote_management",
        translation_key="remote_management",
        data_path="security.remote_management",
        capability="security",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="usb_connected",
        translation_key="usb_connected",
        data_path="usb.connected",
        capability="usb",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.PLUG,
        entity_registry_enabled_default=False,
    ),
    SpeedportBinarySensorEntityDescription(
        key="firmware_update_available",
        translation_key="firmware_update_available",
        data_path="system.update_available",
        capability="system",
        coordinator_group=SLOW,
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SpeedportBinarySensorEntityDescription(
        key="router_problem",
        translation_key="router_problem",
        data_path="diagnostics.problem",
        capability="diagnostics",
        coordinator_group=NORMAL,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up supported binary sensors."""
    del hass
    hub = entry.runtime_data
    async_add_entities(
        SpeedportBinarySensor(hub, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
        if supported(hub, description.capability, description.data_path)
    )

    known: set[tuple[str, str, str]] = set()

    @callback
    def discover_child_binary_sensors(group: PollGroup) -> None:
        new_entities: list[SpeedportChildBinarySensor] = []
        for child_spec in CHILD_BINARY_SENSOR_COLLECTIONS:
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
                        SpeedportChildBinarySensor(
                            hub,
                            child_spec,
                            field,
                            identifier,
                            device,
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    for group in {spec.coordinator_group for spec in CHILD_BINARY_SENSOR_COLLECTIONS}:
        discover_child_binary_sensors(group)

        @callback
        def rediscover(group: PollGroup = group) -> None:
            discover_child_binary_sensors(group)

        entry.async_on_unload(coordinator(hub, group).async_add_listener(rediscover))


class SpeedportBinarySensor(SpeedportEntity, BinarySensorEntity):
    """Binary sensor backed by normalized hub data."""

    _attr_entity_registry_enabled_default = True
    entity_description: SpeedportBinarySensorEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportBinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return normalized boolean state."""
        return value(self.hub, self.entity_description.data_path, as_bool)


class SpeedportChildBinarySensor(SpeedportEntity, BinarySensorEntity):
    """Enabled state sensor for one stable router child."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        hub: SpeedportHub,
        collection_spec: SpeedportChildBinarySensorCollection,
        description: SpeedportChildBinarySensorDescription,
        identifier: str,
        device: SpeedportDevice,
    ) -> None:
        """Initialize a boolean field-backed child sensor."""
        super().__init__(
            hub,
            coordinator(hub, collection_spec.coordinator_group),
            description.key,
            device=device,
        )
        self._collection_spec = collection_spec
        self._field_description = description
        self._child_identifier = identifier
        self._attr_name = description.name
        self._attr_device_class = description.device_class

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
    def is_on(self) -> bool | None:
        """Return the normalized current boolean field."""
        item = self._item
        if item is None:
            return None
        raw = item.get(self._field_description.field)
        if raw is None:
            return None
        try:
            return as_bool(raw)
        except (TypeError, ValueError):
            return None
