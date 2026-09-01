"""Safe, firmware-proven names for managed Speedport devices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    DEVICE_NAME_MAX_LENGTH,
    DEVICE_NAME_PATTERN,
    DOMAIN,
)
from .coordinator import PollGroup
from .entity import SpeedportEntity
from .identity import valid_device_name
from .platform_helpers import (
    child_item,
    collection,
    coordinator,
    manageable_client_row,
    same_managed_client_row,
    speedport_child_device,
    stable_id,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover rename controls only for proven managed-device rows."""
    del hass
    hub = entry.runtime_data
    if not hub.controls_enabled:
        return

    known: set[str] = set()

    @callback
    def discover_clients() -> None:
        if not hub.supports_command("rename_client"):
            return
        entities: list[SpeedportClientNameText] = []
        for item in collection(hub, "clients.items"):
            identifier = stable_id(item)
            if (
                identifier is None
                or identifier in known
                or not manageable_client_row(item, require_fixed_dhcp=False)
                or not valid_device_name(item.get("name"))
            ):
                continue
            device = speedport_child_device("client", item)
            if device is None:
                continue
            known.add(identifier)
            entities.append(SpeedportClientNameText(hub, identifier))
        if entities:
            async_add_entities(entities)

    discover_clients()
    entry.async_on_unload(
        coordinator(hub, PollGroup.NORMAL).async_add_listener(discover_clients)
    )


class SpeedportClientNameText(SpeedportEntity, TextEntity):
    """Rename one existing managed-device row."""

    _attr_translation_key = "client_name"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 1
    _attr_native_max = DEVICE_NAME_MAX_LENGTH
    _attr_pattern = DEVICE_NAME_PATTERN

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize the rename control with stable client identity."""
        self._client_identifier = identifier
        item = self._item_from(hub)
        device = speedport_child_device("client", item) if item is not None else None
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            "client_name",
            data_path="clients.items",
            device=device,
        )

    def _item_from(self, hub: SpeedportHub) -> Mapping[str, Any] | None:
        return child_item(hub, ("clients.items",), self._client_identifier)

    @property
    def _item(self) -> Mapping[str, Any] | None:
        return self._item_from(self.hub)

    @property
    def available(self) -> bool:
        """Remain available only while the exact manageable row exists."""
        item = self._item
        return (
            super().available
            and self.hub.management_controls_available
            and item is not None
            and manageable_client_row(item, require_fixed_dhcp=False)
            and valid_device_name(item.get("name"))
        )

    @property
    def native_value(self) -> str | None:
        """Return the router's current managed-device name."""
        item = self._item
        if item is None or not valid_device_name(item.get("name")):
            return None
        return str(item["name"])

    async def async_set_value(self, value: str) -> None:
        """Rename through a fresh full-row save and one hub-owned readback."""
        item = self._item
        if item is None or not manageable_client_row(item, require_fixed_dhcp=False):
            raise _verification_error()
        if item.get("name") == value:
            return
        await self.hub.async_execute(
            "rename_client",
            verify_group=PollGroup.NORMAL,
            source_kind=str(item["source_kind"]),
            row_id=str(item["source_row_id"]),
            stable_mac=(str(item["mac"]) if item.get("mac") is not None else None),
            name=value,
        )
        current = self._item
        if (
            current is None
            or not same_managed_client_row(current, item, require_fixed_dhcp=False)
            or not valid_device_name(current.get("name"))
            or current.get("name") != value
        ):
            raise _verification_error()
        self._update_device_registry_name(value)

    def _update_device_registry_name(self, name: str) -> None:
        """Refresh the integration-provided child name without touching user naming."""
        child = self.speedport_device
        if child is None:
            return
        identifier = f"{self.hub.router_identifier}:{child.kind}:{child.identifier}"
        registry = dr.async_get(self.hub.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, identifier)})
        if device is not None:
            registry.async_update_device(device.id, name=name)


def _verification_error() -> HomeAssistantError:
    """Return the shared translated readback failure."""
    return HomeAssistantError(
        "The router action was sent, but its resulting state could not be verified.",
        translation_domain=DOMAIN,
        translation_key="command_verification_failed",
    )
