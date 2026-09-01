"""Client device trackers for Speedport Smart."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import callback

from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import (
    as_bool,
    child_item,
    collection,
    coordinator,
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
    """Set up trackers and discover new stable clients after setup."""
    del hass
    hub = entry.runtime_data
    if not hub.has_capability("clients"):
        return

    known: set[str] = set()

    @callback
    def discover_clients() -> None:
        new_entities: list[SpeedportClientTracker] = []
        for item in collection(hub, "clients.items"):
            identifier = stable_id(item)
            if identifier is None or identifier in known:
                continue
            known.add(identifier)
            new_entities.append(SpeedportClientTracker(hub, identifier))
        if new_entities:
            async_add_entities(new_entities)

    discover_clients()
    entry.async_on_unload(
        coordinator(hub, PollGroup.NORMAL).async_add_listener(discover_clients)
    )


class SpeedportClientTracker(SpeedportEntity, TrackerEntity):
    """One network client reported by router."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize client tracker."""
        self._client_identifier = identifier
        item = next(
            (
                candidate
                for candidate in collection(hub, "clients.items")
                if stable_id(candidate) == identifier
            ),
            None,
        )
        device = speedport_child_device("client", item) if item is not None else None
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            f"client_{identifier}",
            data_path="clients.items",
            device=device,
        )

    @property
    def _item(self) -> Mapping[str, Any] | None:
        """Return current client by stable identity."""
        return child_item(
            self.hub,
            ("clients.items",),
            self._client_identifier,
        )

    @property
    def _connected(self) -> bool | None:
        """Return only an explicit, recognized router connectivity state."""
        item = self._item
        if item is None:
            return None
        if "connected" in item:
            raw = item["connected"]
        elif "active" in item:
            raw = item["active"]
        else:
            return None
        try:
            return as_bool(raw)
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        """Remain available only with explicit router presence readback."""
        return super().available and self._connected is not None

    @property
    def is_connected(self) -> bool:
        """Return whether client is currently connected."""
        return self._connected is True

    @property
    def state(self) -> str:
        """Return the network-derived Home Assistant presence state."""
        return STATE_HOME if self.is_connected else STATE_NOT_HOME

    @property
    def source_type(self) -> SourceType:
        """Return router as location source."""
        return SourceType.ROUTER

    @property
    def hostname(self) -> str | None:
        """Return client hostname."""
        item = self._item
        if item is None:
            return None
        raw = item.get("hostname") or item.get("name")
        return str(raw) if raw else None

    @property
    def ip_address(self) -> str | None:
        """Return current IPv4 or IPv6 address."""
        item = self._item
        if item is None:
            return None
        raw = item.get("ipv4") or item.get("ip") or item.get("ipv6")
        return str(raw) if raw else None

    @property
    def mac_address(self) -> str | None:
        """Return client MAC when available."""
        item = self._item
        if item is None or not item.get("mac"):
            return None
        return str(item["mac"])

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return useful, bounded connection attributes."""
        item = self._item
        if item is None:
            return {}
        allowed = (
            "reserved_ipv4",
            "ipv6",
            "medium",
            "signal_dbm",
            "link_speed_bps",
            "access_point",
            "mesh_node",
            "last_seen",
            "parental_profile",
            "internet_paused",
            "internet_access_allowed",
        )
        return {key: item[key] for key in allowed if item.get(key) is not None}
