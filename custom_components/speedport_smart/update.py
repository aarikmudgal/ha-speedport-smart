"""Firmware update entity for Speedport Smart."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory

from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import coordinator, supported

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import SpeedportHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up firmware entity when router exposes update metadata."""
    del hass
    hub = entry.runtime_data
    if supported(hub, "system", "system.latest_firmware"):
        async_add_entities([SpeedportFirmwareUpdate(hub)])


class SpeedportFirmwareUpdate(SpeedportEntity, UpdateEntity):
    """Represent locally reported Speedport firmware availability."""

    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: SpeedportHub) -> None:
        """Initialize firmware entity."""
        super().__init__(
            hub,
            coordinator(hub, PollGroup.SLOW),
            "firmware",
            data_path="system.latest_firmware",
        )
        if supported(hub, "system", "system.firmware_update_progress"):
            self._attr_supported_features |= UpdateEntityFeature.PROGRESS
        if hub.supports_command("firmware_update"):
            self._attr_supported_features |= UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str | None:
        """Return installed router firmware."""
        raw = self.hub.get("router.firmware")
        return str(raw) if raw is not None else None

    @property
    def latest_version(self) -> str | None:
        """Return latest firmware reported by router."""
        raw = self.hub.get("system.latest_firmware")
        return str(raw) if raw is not None else None

    @property
    def release_url(self) -> str | None:
        """Return firmware release information URL when exposed."""
        raw = self.hub.get("system.firmware_release_url")
        return str(raw) if raw is not None else None

    @property
    def in_progress(self) -> bool | None:
        """Return firmware installation progress."""
        raw = self.hub.get("system.firmware_update_progress")
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int | float):
            return raw > 0
        return None

    @property
    def update_percentage(self) -> int | float | None:
        """Return firmware installation percentage."""
        raw = self.hub.get("system.firmware_update_progress")
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return raw
        return None

    async def async_install(
        self,
        version: str | None,
        backup: bool,  # noqa: FBT001
        **kwargs: Any,
    ) -> None:
        """Install router-approved firmware through command arbiter."""
        del backup, kwargs
        await self.hub.async_execute(
            "firmware_update",
            verify_group=PollGroup.SLOW,
            version=version,
        )
        await self.coordinator.async_request_refresh()
