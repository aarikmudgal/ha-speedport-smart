"""Reversible enumerated controls for Speedport Smart."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import MISSING, command_unavailable_reason, coordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


@dataclass(frozen=True, kw_only=True)
class SpeedportSelectEntityDescription(SelectEntityDescription):
    """Describe one reviewed enumerated Speedport command."""

    data_path: str
    capability: str
    coordinator_group: PollGroup
    command: str
    command_parameter: str
    option_codes: Mapping[str, int]


SELECT_DESCRIPTIONS: tuple[SpeedportSelectEntityDescription, ...] = (
    SpeedportSelectEntityDescription(
        key="internet_privacy_level_control",
        translation_key="internet_privacy_level_control",
        data_path="internet.privacy_level",
        capability="connection_privacy",
        coordinator_group=PollGroup.SLOW,
        command="set_internet_privacy_level",
        command_parameter="level",
        options=["off", "level_1", "level_2"],
        option_codes=MappingProxyType({"off": 0, "level_1": 1, "level_2": 2}),
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSelectEntityDescription(
        key="receiver_led_mode_control",
        translation_key="receiver_led_mode_control",
        data_path="receiver.led_mode",
        capability="receiver_led",
        coordinator_group=PollGroup.NORMAL,
        command="set_receiver_led_mode",
        command_parameter="mode",
        options=["use_leds", "off_after_timeout", "disabled"],
        option_codes=MappingProxyType(
            {"use_leds": 0, "off_after_timeout": 1, "disabled": 2}
        ),
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up reviewed enumerated controls when controls are enabled."""
    del hass
    hub = entry.runtime_data
    if not getattr(hub, "controls_enabled", False):
        return

    known: set[str] = set()

    @callback
    def discover_selects() -> None:
        entities: list[SelectEntity] = []
        for description in SELECT_DESCRIPTIONS:
            if description.key in known:
                continue
            if not hub.supports_command(description.command):
                continue
            known.add(description.key)
            entities.append(SpeedportCommandSelect(hub, description))
        if entities:
            async_add_entities(entities)

    discover_selects()
    for group in dict.fromkeys(
        description.coordinator_group for description in SELECT_DESCRIPTIONS
    ):
        entry.async_on_unload(
            coordinator(hub, group).async_add_listener(discover_selects)
        )


class SpeedportCommandSelect(SpeedportEntity, SelectEntity):
    """Fixed select using the shared router command arbiter."""

    _attr_entity_registry_enabled_default = True

    entity_description: SpeedportSelectEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportSelectEntityDescription,
    ) -> None:
        """Initialize a reviewed enumerated control."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """Return the semantic option for an explicitly known router code."""
        raw = self.hub.get(self.entity_description.data_path)
        if not isinstance(raw, int) or isinstance(raw, bool):
            return None
        return next(
            (
                option
                for option, code in self.entity_description.option_codes.items()
                if raw == code
            ),
            None,
        )

    def _control_unavailable_reason(self) -> str | None:
        """Explain the first failed control-safety or readback gate."""
        raw = self.hub.get(self.entity_description.data_path, MISSING)
        return command_unavailable_reason(
            self.hub,
            self.entity_description.command,
            coordinator_available=self.coordinator.last_update_success,
            state_available=raw is not MISSING and raw is not None,
            readback_supported=self.current_option is not None,
        )

    @property
    def available(self) -> bool:
        """Remain available only with explicit current-state readback."""
        return self._control_unavailable_reason() is None

    @property
    def extra_state_attributes(self) -> Mapping[str, str]:
        """Expose a safe reason code when the control is unavailable."""
        reason = self._control_unavailable_reason()
        return {} if reason is None else {"control_unavailable_reason": reason}

    async def async_select_option(self, option: str) -> None:
        """Set one allowlisted semantic option and verify fresh readback."""
        if option not in self.entity_description.option_codes:
            raise _verification_error()
        current = self.current_option
        if current is None:
            raise _verification_error()
        if current == option:
            return

        await self.hub.async_execute(
            self.entity_description.command,
            verify_group=self.entity_description.coordinator_group,
            **{
                self.entity_description.command_parameter: (
                    self.entity_description.option_codes[option]
                )
            },
        )
        if self.current_option != option:
            raise _verification_error()


def _verification_error() -> HomeAssistantError:
    """Return the shared translated readback failure."""
    return HomeAssistantError(
        "The router action was sent, but its resulting state could not be verified.",
        translation_domain=DOMAIN,
        translation_key="command_verification_failed",
    )
