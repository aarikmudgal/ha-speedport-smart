"""Shared entity helpers for Speedport Smart platforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import GroupSnapshot, SpeedportDataUpdateCoordinator

if TYPE_CHECKING:
    from .hub import SpeedportHub

_NOT_FOUND = object()


@dataclass(frozen=True, slots=True)
class SpeedportDevice:
    """Stable child-device reference for router-backed entities."""

    identifier: str
    kind: str
    name: str
    manufacturer: str | None = None
    model: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None


class SpeedportEntity(CoordinatorEntity[SpeedportDataUpdateCoordinator]):
    """Base for entities backed by one Speedport polling group."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hub: SpeedportHub,
        coordinator: SpeedportDataUpdateCoordinator,
        entity_key: str,
        *,
        data_path: tuple[str | int, ...] | str | None = None,
        device: SpeedportDevice | None = None,
    ) -> None:
        """Initialize entity."""
        super().__init__(coordinator)
        self.hub = hub
        self.entity_key = entity_key
        self.data_path = data_path
        self.speedport_device = device
        parts = [hub.router_identifier]
        if device is not None:
            parts.extend((device.kind, device.identifier))
        parts.append(entity_key)
        self._attr_unique_id = "_".join(_identifier_part(part) for part in parts)

    @property
    def available(self) -> bool:
        """Return availability for coordinator and optional backing path."""
        if not super().available:
            return False
        if self.data_path is None:
            return True
        backing_value = self.hub.get(self.data_path, _NOT_FOUND)
        return backing_value is not _NOT_FOUND and backing_value is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return router or stable child-device metadata."""
        router = self.hub.router_identity
        device = self.speedport_device
        if device is None:
            return DeviceInfo(
                identifiers={(DOMAIN, router.identifier)},
                manufacturer=MANUFACTURER,
                model=router.model,
                name=router.model or "Telekom Speedport Smart",
                sw_version=router.firmware,
                hw_version=router.hardware_version,
                serial_number=router.serial_number,
            )

        child_identifier = f"{router.identifier}:{device.kind}:{device.identifier}"
        return DeviceInfo(
            identifiers={(DOMAIN, child_identifier)},
            manufacturer=device.manufacturer or MANUFACTURER,
            model=device.model,
            name=device.name,
            sw_version=device.sw_version,
            hw_version=device.hw_version,
            via_device=(DOMAIN, router.identifier),
        )

    @property
    def value(self) -> Any:
        """Return current value from data path for descriptor-based platforms."""
        if self.data_path is None:
            return None
        return self.hub.get(self.data_path)

    @property
    def group_snapshot(self) -> GroupSnapshot | None:
        """Return latest polling-group snapshot."""
        return self.coordinator.data


def _identifier_part(value: str) -> str:
    """Normalize one unique-ID component."""
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value
    ).strip("_")
