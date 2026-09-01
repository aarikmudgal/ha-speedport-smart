"""Reversible controls for Speedport Smart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .coordinator import PollGroup
from .entity import SpeedportEntity
from .platform_helpers import (
    as_bool,
    collection,
    coordinator,
    manageable_client_row,
    same_managed_client_row,
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

_SHA256_HEX_LENGTH = 64


@dataclass(frozen=True, kw_only=True)
class SpeedportSwitchEntityDescription(SwitchEntityDescription):
    """Describe a reversible Speedport command."""

    data_path: str
    capability: str
    coordinator_group: PollGroup
    command: str


SWITCH_DESCRIPTIONS: tuple[SpeedportSwitchEntityDescription, ...] = (
    SpeedportSwitchEntityDescription(
        key="hybrid_bonding",
        translation_key="hybrid_bonding",
        data_path="hybrid.enabled",
        capability="hybrid",
        coordinator_group=PollGroup.NORMAL,
        command="set_hybrid_bonding",
        entity_category=EntityCategory.CONFIG,
    ),
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
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="ddns",
        translation_key="ddns",
        data_path="ddns.enabled",
        capability="ddns",
        coordinator_group=PollGroup.SLOW,
        command="set_ddns",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="vpn",
        translation_key="vpn",
        data_path="vpn.enabled",
        capability="vpn",
        coordinator_group=PollGroup.SLOW,
        command="set_vpn",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="parental_controls",
        translation_key="parental_controls",
        data_path="parental.enabled",
        capability="parental",
        coordinator_group=PollGroup.SLOW,
        command="set_parental_controls",
        entity_category=EntityCategory.CONFIG,
    ),
    SpeedportSwitchEntityDescription(
        key="media_server",
        translation_key="media_server",
        data_path="usb.media_server_enabled",
        capability="usb",
        coordinator_group=PollGroup.SLOW,
        command="set_media_server",
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

    _setup_fixed_switches(entry, hub, async_add_entities)

    _setup_dynamic_switches(entry, hub, async_add_entities)


def _setup_fixed_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register reviewed switches whenever their protected readback appears."""
    known: set[str] = set()

    @callback
    def discover_switches() -> None:
        entities: list[SwitchEntity] = []
        for description in SWITCH_DESCRIPTIONS:
            if description.key in known:
                continue
            if not hub.supports_command(description.command) or not supported(
                hub, description.capability, description.data_path
            ):
                continue
            known.add(description.key)
            entities.append(SpeedportCommandSwitch(hub, description))
        if entities:
            async_add_entities(entities)

    discover_switches()
    for group in dict.fromkeys(
        description.coordinator_group for description in SWITCH_DESCRIPTIONS
    ):
        entry.async_on_unload(
            coordinator(hub, group).async_add_listener(discover_switches)
        )


def _setup_dynamic_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover stable port rules and pausable clients."""
    _setup_port_forward_switches(entry, hub, async_add_entities)
    _setup_client_switches(entry, hub, async_add_entities)
    _setup_client_fixed_dhcp_switches(entry, hub, async_add_entities)


def _setup_port_forward_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover stable PortuwMain forwarding rules."""
    known_rules: set[str] = set()

    @callback
    def discover_rules() -> None:
        if not hub.has_capability("nat") or not hub.supports_command(
            "set_port_forward_rule"
        ):
            return
        entities: list[SwitchEntity] = []
        for item in collection(hub, "nat.port_forward_rules"):
            identifier = stable_id(item)
            if identifier is None or identifier in known_rules:
                continue
            if "active" not in item and "enabled" not in item:
                continue
            if _port_forward_fingerprint(item) is None:
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
    known_clients: set[str] = set()

    @callback
    def discover_clients() -> None:
        if not hub.has_capability("clients") or not hub.supports_command(
            "set_client_internet_paused"
        ):
            return
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


def _setup_client_fixed_dhcp_switches(
    entry: ConfigEntry[SpeedportHub],
    hub: SpeedportHub,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover clients whose exact row proves fixed-DHCP support."""
    known_clients: set[str] = set()

    @callback
    def discover_clients() -> None:
        if not hub.has_capability("clients") or not hub.supports_command(
            "set_client_fixed_dhcp"
        ):
            return
        entities: list[SwitchEntity] = []
        for item in collection(hub, "clients.items"):
            identifier = stable_id(item)
            if (
                identifier is None
                or identifier in known_clients
                or not manageable_client_row(item, require_fixed_dhcp=True)
            ):
                continue
            known_clients.add(identifier)
            entities.append(SpeedportClientFixedDhcpSwitch(hub, identifier))
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

    @property
    def available(self) -> bool:
        """Remain available only with explicit current-state readback."""
        return (
            super().available
            and self.hub.management_controls_available
            and self.is_on is not None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable feature."""
        del kwargs
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable feature."""
        del kwargs
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        """Execute a reversible command with one hub-owned readback."""
        current = self.is_on
        if current is None:
            raise _verification_error()
        if current is enabled:
            return
        await self.hub.async_execute(
            self.entity_description.command,
            verify_group=self.entity_description.coordinator_group,
            enabled=enabled,
        )
        if self.is_on is not enabled:
            raise _verification_error()


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
        return (
            super().available
            and self.hub.management_controls_available
            and self._item is not None
        )


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
        self._expected_name = (
            str(item.get("name")) if item and item.get("name") else None
        )
        self._expected_fingerprint = _port_forward_fingerprint(item)
        self._attr_name = self._expected_name

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

    @property
    def available(self) -> bool:
        """Remain available only with explicit forwarding-state readback."""
        item = self._item
        return (
            super().available
            and _same_port_forward_rule(
                item,
                expected_name=self._expected_name,
                expected_fingerprint=self._expected_fingerprint,
            )
            and _port_forward_enabled(item) is not None
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable existing rule."""
        del kwargs
        await self._async_set(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable existing rule."""
        del kwargs
        await self._async_set(enabled=False)

    async def _async_set(self, *, enabled: bool) -> None:
        item = self._item
        if not _same_port_forward_rule(
            item,
            expected_name=self._expected_name,
            expected_fingerprint=self._expected_fingerprint,
        ):
            raise _verification_error()
        current = _port_forward_enabled(item)
        if current is None:
            raise _verification_error()
        if current is enabled:
            return
        await self.hub.async_execute(
            "set_port_forward_rule",
            verify_group=PollGroup.SLOW,
            rule_id=self._identifier,
            enabled=enabled,
            expected_name=self._expected_name,
            expected_fingerprint=self._expected_fingerprint,
        )
        current_item = self._item
        if (
            not _same_port_forward_rule(
                current_item,
                expected_name=self._expected_name,
                expected_fingerprint=self._expected_fingerprint,
            )
            or _port_forward_enabled(current_item) is not enabled
        ):
            raise _verification_error()


class SpeedportClientInternetSwitch(_SpeedportCollectionSwitch):
    """Pause or resume one client's internet access."""

    _collection_path = "clients.items"
    _attr_translation_key = "client_internet_access"
    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize client internet switch."""
        self._identifier = identifier
        item = next(
            (
                candidate
                for candidate in collection(hub, self._collection_path)
                if stable_id(candidate) == identifier
            ),
            None,
        )
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            f"client_internet_access_{identifier}",
            data_path=self._collection_path,
            device=(
                speedport_child_device("client", item) if item is not None else None
            ),
        )
        self._attr_name = (
            str(item.get("hostname") or item.get("name")) if item else None
        )

    @property
    def is_on(self) -> bool:
        """Return true when internet access is not paused."""
        paused = _client_internet_paused(self._item)
        return paused is False

    @property
    def available(self) -> bool:
        """Remain available only with explicit client access readback."""
        return super().available and _client_internet_paused(self._item) is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume client internet."""
        del kwargs
        await self._async_set(paused=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause client internet."""
        del kwargs
        await self._async_set(paused=True)

    async def _async_set(self, *, paused: bool) -> None:
        current = _client_internet_paused(self._item)
        if current is None:
            raise _verification_error()
        if current is paused:
            return
        await self.hub.async_execute(
            "set_client_internet_paused",
            verify_group=PollGroup.NORMAL,
            client_id=self._identifier,
            paused=paused,
        )
        if _client_internet_paused(self._item) is not paused:
            raise _verification_error()


class SpeedportClientFixedDhcpSwitch(_SpeedportCollectionSwitch):
    """Toggle only one managed row's proven fixed-DHCP flag."""

    _collection_path = "clients.items"
    _attr_translation_key = "client_fixed_dhcp"
    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: SpeedportHub, identifier: str) -> None:
        """Initialize on the existing client child device."""
        self._identifier = identifier
        item = next(
            (
                candidate
                for candidate in collection(hub, self._collection_path)
                if stable_id(candidate) == identifier
            ),
            None,
        )
        super().__init__(
            hub,
            coordinator(hub, PollGroup.NORMAL),
            f"client_fixed_dhcp_{identifier}",
            data_path=self._collection_path,
            device=(
                speedport_child_device("client", item) if item is not None else None
            ),
        )

    @property
    def available(self) -> bool:
        """Return whether the current row still proves safe toggle support."""
        item = self._item
        return (
            super().available
            and item is not None
            and manageable_client_row(item, require_fixed_dhcp=True)
        )

    @property
    def is_on(self) -> bool:
        """Return the fresh normalized fixed-DHCP flag."""
        item = self._item
        return bool(item.get("fixed_dhcp")) if item is not None else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable fixed DHCP without changing reservation or IP metadata."""
        del kwargs
        await self._async_set_fixed_dhcp(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable fixed DHCP without changing reservation or IP metadata."""
        del kwargs
        await self._async_set_fixed_dhcp(enabled=False)

    async def _async_set_fixed_dhcp(self, *, enabled: bool) -> None:
        item = self._item
        if item is None or not manageable_client_row(item, require_fixed_dhcp=True):
            raise _verification_error()
        if bool(item["fixed_dhcp"]) is enabled:
            return
        await self.hub.async_execute(
            "set_client_fixed_dhcp",
            verify_group=PollGroup.NORMAL,
            source_kind=str(item["source_kind"]),
            row_id=str(item["source_row_id"]),
            stable_mac=(str(item["mac"]) if item.get("mac") is not None else None),
            enabled=enabled,
        )
        current = self._item
        if (
            current is None
            or not same_managed_client_row(current, item, require_fixed_dhcp=False)
            or current.get("fixed_dhcp") is not enabled
        ):
            raise _verification_error()


def _port_forward_enabled(item: Mapping[str, Any] | None) -> bool | None:
    """Return a forwarding rule's explicit state, rejecting missing readback."""
    if item is None or ("active" not in item and "enabled" not in item):
        return None
    try:
        return as_bool(item.get("active", item.get("enabled")))
    except ValueError:
        return None


def _same_port_forward_rule(
    item: Mapping[str, Any] | None,
    *,
    expected_name: str | None,
    expected_fingerprint: str | None,
) -> bool:
    """Reject a deleted rule ID reused for different rule semantics."""
    if (
        item is None
        or expected_fingerprint is None
        or _port_forward_fingerprint(item) != expected_fingerprint
    ):
        return False
    if expected_name is None:
        return True
    return item.get("name") == expected_name


def _port_forward_fingerprint(item: Mapping[str, Any] | None) -> str | None:
    """Return one canonical internal fingerprint or reject malformed data."""
    if item is None:
        return None
    candidate = item.get("_identity_fingerprint")
    if not isinstance(candidate, str) or len(candidate) != _SHA256_HEX_LENGTH:
        return None
    return (
        candidate
        if all(character in "0123456789abcdef" for character in candidate)
        else None
    )


def _client_internet_paused(item: Mapping[str, Any] | None) -> bool | None:
    """Return the client's explicit access state, rejecting missing readback."""
    if item is None or "internet_paused" not in item:
        return None
    try:
        return as_bool(item["internet_paused"])
    except ValueError:
        return None


def _verification_error() -> HomeAssistantError:
    """Return the shared translated readback failure."""
    return HomeAssistantError(
        "The router action was sent, but its resulting state could not be verified.",
        translation_domain=DOMAIN,
        translation_key="command_verification_failed",
    )
