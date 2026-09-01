"""Action buttons for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import (
    coordinator,
    supported,
    wps_in_progress,
    wps_started_or_completed,
)

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
    verify_after_command: bool = True


BUTTON_DESCRIPTIONS: tuple[SpeedportButtonEntityDescription, ...] = (
    SpeedportButtonEntityDescription(
        key="wps",
        translation_key="wps",
        data_path="wifi.wps_status",
        capability="wifi",
        coordinator_group=PollGroup.NORMAL,
        command="wps",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="reconnect_internet",
        translation_key="reconnect_internet",
        data_path="internet.state",
        capability="internet",
        coordinator_group=PollGroup.NORMAL,
        command="reconnect",
        verify_after_command=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="restart_dsl",
        translation_key="restart_dsl",
        data_path="dsl.state",
        capability="dsl",
        coordinator_group=PollGroup.NORMAL,
        command="dsl_restart",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="reboot_router",
        translation_key="reboot_router",
        data_path="router.model",
        capability="system",
        coordinator_group=PollGroup.SLOW,
        command="reboot",
        verify_after_command=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="update_ddns",
        translation_key="update_ddns",
        data_path="ddns.enabled",
        capability="ddns",
        coordinator_group=PollGroup.SLOW,
        command="ddns_update",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="restart_vpn",
        translation_key="restart_vpn",
        data_path="vpn.enabled",
        capability="vpn",
        coordinator_group=PollGroup.SLOW,
        command="wireguard_restart",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportButtonEntityDescription(
        key="optimize_mesh",
        translation_key="optimize_mesh",
        data_path="mesh.enabled",
        capability="mesh",
        coordinator_group=PollGroup.SLOW,
        command="mesh_optimize",
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
    known: set[str] = set()

    @callback
    def discover_buttons() -> None:
        entities: list[ButtonEntity] = []
        for description in BUTTON_DESCRIPTIONS:
            if description.key in known:
                continue
            if not hub.supports_command(description.command) or not supported(
                hub, description.capability, description.data_path
            ):
                continue
            known.add(description.key)
            entities.append(SpeedportCommandButton(hub, description))
        if entities:
            async_add_entities(entities)

    discover_buttons()
    for group in dict.fromkeys(
        description.coordinator_group for description in BUTTON_DESCRIPTIONS
    ):
        entry.async_on_unload(
            coordinator(hub, group).async_add_listener(discover_buttons)
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

    @property
    def available(self) -> bool:
        """Remain unavailable while protected management access is backed off."""
        return super().available and self.hub.management_controls_available

    async def async_press(self) -> None:
        """Execute action through its declared hub verification policy."""
        if self.entity_description.key == "wps" and wps_in_progress(
            self.hub.get(self.entity_description.data_path)
        ):
            return
        await self.hub.async_execute(
            self.entity_description.command,
            verify_group=(
                self.entity_description.coordinator_group
                if self.entity_description.verify_after_command
                else None
            ),
        )
        if self.entity_description.key == "wps" and not wps_started_or_completed(
            self.hub.get(self.entity_description.data_path)
        ):
            raise _verification_error()


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


def _verification_error() -> HomeAssistantError:
    """Return the shared translated readback failure."""
    return HomeAssistantError(
        "The router action was sent, but its resulting state could not be verified.",
        translation_domain=DOMAIN,
        translation_key="command_verification_failed",
    )
