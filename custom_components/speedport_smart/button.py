"""Action buttons for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory

from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import coordinator, supported

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


@dataclass(frozen=True, kw_only=True)
class SpeedportButtonEntityDescription(ButtonEntityDescription):
    """Describe a Speedport action."""

    data_path: str
    capability: str
    coordinator_group: PollGroup
    command: str


BUTTON_DESCRIPTIONS: tuple[SpeedportButtonEntityDescription, ...] = (
    SpeedportButtonEntityDescription(
        key="wps",
        translation_key="wps",
        data_path="wifi.wps_status",
        capability="wifi",
        coordinator_group=PollGroup.NORMAL,
        command="wps",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="reconnect_internet",
        translation_key="reconnect_internet",
        data_path="internet.state",
        capability="internet",
        coordinator_group=PollGroup.NORMAL,
        command="reconnect",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="restart_dsl",
        translation_key="restart_dsl",
        data_path="dsl.state",
        capability="dsl",
        coordinator_group=PollGroup.NORMAL,
        command="dsl_restart",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="reboot_router",
        translation_key="reboot_router",
        data_path="router.model",
        capability="system",
        coordinator_group=PollGroup.SLOW,
        command="reboot",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="update_ddns",
        translation_key="update_ddns",
        data_path="ddns.enabled",
        capability="ddns",
        coordinator_group=PollGroup.SLOW,
        command="ddns_update",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="restart_vpn",
        translation_key="restart_vpn",
        data_path="vpn.enabled",
        capability="vpn",
        coordinator_group=PollGroup.SLOW,
        command="wireguard_restart",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="optimize_mesh",
        translation_key="optimize_mesh",
        data_path="mesh.enabled",
        capability="mesh",
        coordinator_group=PollGroup.SLOW,
        command="mesh_optimize",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up supported action buttons when router controls are enabled."""
    del hass
    hub = entry.runtime_data
    async_add_entities([SpeedportRetryProtectedDataButton(hub)])
    if not hub.controls_enabled:
        return
    async_add_entities(
        SpeedportCommandButton(hub, description)
        for description in BUTTON_DESCRIPTIONS
        if hub.supports_command(description.command)
        and supported(hub, description.capability, description.data_path)
    )


class SpeedportCommandButton(SpeedportEntity, ButtonEntity):
    """Button using serialized command owner."""

    _attr_entity_registry_enabled_default = True

    entity_description: SpeedportButtonEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportButtonEntityDescription,
    ) -> None:
        """Initialize button."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    async def async_press(self) -> None:
        """Execute action and verify through its owning poll group."""
        await self.hub.async_execute(
            self.entity_description.command,
            verify_group=self.entity_description.coordinator_group,
        )
        await self.coordinator.async_request_refresh()


class SpeedportRetryProtectedDataButton(SpeedportEntity, ButtonEntity):
    """Safely retry read-only protected access after browser logout."""

    _attr_translation_key = "retry_protected_data"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, hub: SpeedportHub) -> None:
        """Initialize outside the router control gate."""
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            "retry_protected_data",
        )

    async def async_press(self) -> None:
        """Perform read-only rediscovery and schedule a clean entry reload."""
        await self.hub.async_retry_protected_data()
