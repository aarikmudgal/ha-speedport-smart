"""Reversible controls for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import (
    as_bool,
    collection,
    coordinator,
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
class SpeedportSwitchEntityDescription(SwitchEntityDescription):
    """Describe a reversible Speedport command."""

    data_path: str
    capability: str
    coordinator_group: PollGroup
    command: str


SWITCH_DESCRIPTIONS: tuple[SpeedportSwitchEntityDescription, ...] = (
    SpeedportSwitchEntityDescription(
        key="wifi",
        translation_key="wifi",
        data_path="wifi.enabled",
        capability="wifi",
        coordinator_group=PollGroup.NORMAL,
        command="wifi_set_enabled",
    ),
    SpeedportSwitchEntityDescription(
        key="guest_wifi",
        translation_key="guest_wifi",
        data_path="wifi.guest.enabled",
        capability="wifi",
        coordinator_group=PollGroup.NORMAL,
        command="set_guest_wifi",
    ),
    SpeedportSwitchEntityDescription(
        key="office_wifi",
        translation_key="office_wifi",
        data_path="wifi.office.enabled",
        capability="wifi",
        coordinator_group=PollGroup.NORMAL,
        command="set_office_wifi",
    ),
    SpeedportSwitchEntityDescription(
        key="upnp",
        translation_key="upnp",
        data_path="nat.upnp_enabled",
        capability="nat",
        coordinator_group=PollGroup.SLOW,
        command="set_upnp",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="ddns",
        translation_key="ddns",
        data_path="ddns.enabled",
        capability="ddns",
        coordinator_group=PollGroup.SLOW,
        command="set_ddns",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="vpn",
        translation_key="vpn",
        data_path="vpn.enabled",
        capability="vpn",
        coordinator_group=PollGroup.SLOW,
        command="set_vpn",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="parental_controls",
        translation_key="parental_controls",
        data_path="parental.enabled",
        capability="parental",
        coordinator_group=PollGroup.SLOW,
        command="set_parental_controls",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="media_server",
        translation_key="media_server",
        data_path="usb.media_server_enabled",
        capability="usb",
        coordinator_group=PollGroup.SLOW,
        command="set_media_server",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[SpeedportHub],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up controls when enabled for this config entry."""
    del hass
    hub = entry.runtime_data
    if not getattr(hub, "controls_enabled", False):
        return

    async_add_entities(
        SpeedportCommandSwitch(hub, description)
        for description in SWITCH_DESCRIPTIONS
        if hub.supports_command(description.command)
        and supported(hub, description.capability, description.data_path)
    )

    _setup_dynamic_switches(entry, hub, async_add_entities)


def _setup_dynamic_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover stable port rules and pausable clients."""
    _setup_port_forward_switches(entry, hub, async_add_entities)
    _setup_client_switches(entry, hub, async_add_entities)


def _setup_port_forward_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover stable PortuwMain forwarding rules."""
    if not hub.has_capability("nat") or not hub.supports_command(
        "set_port_forward_rule"
    ):
        return
    known_rules: set[str] = set()

    @callback
    def discover_rules() -> None:
        entities: list[SwitchEntity] = []
        for item in collection(hub, "nat.port_forward_rules"):
            identifier = stable_id(item)
            if identifier is None or identifier in known_rules:
                continue
            if "active" not in item and "enabled" not in item:
                continue
            known_rules.add(identifier)
            entities.append(SpeedportPortForwardSwitch(hub, identifier))
        if entities:
            async_add_entities(entities)

    discover_rules()
    entry.async_on_unload(
        coordinator(hub, PollGroup.SLOW).async_add_listener(discover_rules)
    )


def _setup_client_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover clients with a real internet-pause state."""
    if not hub.has_capability("clients") or not hub.supports_command(
        "set_client_internet_paused"
    ):
        return
    known_clients: set[str] = set()

    @callback
    def discover_clients() -> None:
        entities: list[SwitchEntity] = []
        for item in collection(hub, "clients.items"):
            identifier = stable_id(item)
            if identifier is None or identifier in known_clients:
                continue
            if "internet_paused" not in item:
                continue
            known_clients.add(identifier)
            entities.append(SpeedportClientInternetSwitch(hub, identifier))
        if entities:
            async_add_entities(entities)

    discover_clients()
    entry.async_on_unload(
        coordinator(hub, PollGroup.NORMAL).async_add_listener(discover_clients)
    )


class SpeedportCommandSwitch(SpeedportEntity, SwitchEntity):
    """Fixed switch using the shared router command arbiter."""

    _attr_entity_registry_enabled_default = True

    entity_description: SpeedportSwitchEntityDescription

    def __init__(
        self,
        hub: SpeedportHub,
        description: SpeedportSwitchEntityDescription,
    ) -> None:
        """Initialize command switch."""
        super().__init__(
            hub,
            coordinator(hub, description.coordinator_group),
            description.key,
            data_path=description.data_path,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return current control state."""
        return value(self.hub, self.entity_description.data_path, as_bool)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable feature."""
        del kwargs
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable feature."""
        del kwargs
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        """Execute and refresh a reversible command."""
        await self.hub.async_execute(
            self.entity_description.command,
            verify_group=self.entity_description.coordinator_group,
            enabled=enabled,
        )
        await self.coordinator.async_request_refresh()


class _SpeedportCollectionSwitch(SpeedportEntity, SwitchEntity):
    """Base for stable items within a router collection."""

    _collection_path: str
    _identifier: str

    @property
    def _item(self) -> Mapping[str, Any] | None:
        return next(
            (
                item
                for item in collection(self.hub, self._collection_path)
                if stable_id(item) == self._identifier
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """Return whether this stable collection item still exists."""
        return super().available and self._item is not None


class SpeedportPortForwardSwitch(_SpeedportCollectionSwitch):
    """Toggle one existing PortuwMain forwarding rule."""

    _collection_path = "nat.port_forward_rules"
    _attr_translation_key = "port_forward_rule"
    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize forwarding-rule switch."""
        self._identifier = identifier
        super().__init__(
            hub,
            coordinator(hub, PollGroup.SLOW),
            f"port_forward_rule_{identifier}",
            data_path=self._collection_path,
        )
        item = self._item
        self._attr_name = str(item.get("name")) if item and item.get("name") else None

    @property
    def is_on(self) -> bool:
        """Return current rule state."""
        item = self._item
        if item is None:
            return False
        try:
            return as_bool(item.get("active", item.get("enabled", False)))
        except ValueError:
            return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable existing rule."""
        del kwargs
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable existing rule."""
        del kwargs
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        await self.hub.async_execute(
            "set_port_forward_rule",
            verify_group=PollGroup.SLOW,
            rule_id=self._identifier,
            enabled=enabled,
        )
        await self.coordinator.async_request_refresh()


class SpeedportClientInternetSwitch(_SpeedportCollectionSwitch):
    """Pause or resume one client's internet access."""

    _collection_path = "clients.items"
    _attr_translation_key = "client_internet_access"
    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize client internet switch."""
        self._identifier = identifier
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            f"client_internet_access_{identifier}",
            data_path=self._collection_path,
        )
        item = self._item
        self._attr_name = (
            str(item.get("hostname") or item.get("name")) if item else None
        )

    @property
    def is_on(self) -> bool:
        """Return true when internet access is not paused."""
        item = self._item
        if item is None:
            return False
        try:
            return not as_bool(item.get("internet_paused", False))
        except ValueError:
            return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume client internet."""
        del kwargs
        await self._async_set(paused=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause client internet."""
        del kwargs
        await self._async_set(paused=True)

    async def _async_set(self, *, paused: bool) -> None:
        await self.hub.async_execute(
            "set_client_internet_paused",
            verify_group=PollGroup.NORMAL,
            client_id=self._identifier,
            paused=paused,
        )
        await self.coordinator.async_request_refresh()
