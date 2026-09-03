"""Connection-owned panel focus hints without router I/O."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.decorators import websocket_command
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryState,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .polling_priority import FOCUS_LEASE_SECONDS, PollingPriorityGateClosed

if TYPE_CHECKING:
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.config_entries import ConfigEntry, ConfigEntryChange
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub
    from .polling_priority import PanelFocus

_FOCUS_TYPE: Final = f"{DOMAIN}/panel/focus"
_RENEW_TYPE: Final = f"{_FOCUS_TYPE}/renew"
_MAX_FOCUS_SUBSCRIPTIONS: Final = 4


@callback
def async_register_focus_commands(hass: HomeAssistant) -> None:
    """Register the process-scoped, strictly local focus transport."""
    websocket_api.async_register_command(hass, websocket_panel_focus)
    websocket_api.async_register_command(hass, websocket_panel_focus_renew)


class _FocusSubscription:
    """Release one opaque lease using Home Assistant's subscription lifecycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        connection: ActiveConnection,
        entry: ConfigEntry[Any],
        hub: SpeedportHub,
        *,
        subscription_id: int,
        view: PanelFocus,
    ) -> None:
        self.hass = hass
        self.connection = connection
        self.entry = entry
        self.hub = hub
        self.subscription_id = subscription_id
        self.view = view
        self.owner = object()
        self.active = True
        self._cancel_timeout: Callable[[], None] | None = None
        hub.polling_priority.set_focus(self.owner, view)
        self._cancel_entry_listener = async_dispatcher_connect(
            hass, SIGNAL_CONFIG_ENTRY_CHANGED, self._entry_changed
        )
        self._schedule_expiry()

    @callback
    def __call__(self) -> None:
        """Cancel without mutating the subscription dictionary during disconnect."""
        if not self.active:
            return
        self.active = False
        if self._cancel_timeout is not None:
            self._cancel_timeout()
            self._cancel_timeout = None
        self._cancel_entry_listener()
        self.hub.polling_priority.clear_focus(self.owner)

    @callback
    def remove(self) -> None:
        """Remove an expired or invalid lease outside disconnect iteration."""
        connection = self.connection
        subscription_id = self.subscription_id
        if connection.subscriptions.get(subscription_id) is self:
            connection.subscriptions.pop(subscription_id)
        self()

    @callback
    def renew(self) -> bool:
        """Extend only an existing gate lease, preserving focus ordering."""
        if not self.active or not self.hub.polling_priority.renew_focus(self.owner):
            self.remove()
            return False
        self._schedule_expiry()
        return True

    @callback
    def _schedule_expiry(self) -> None:
        if self._cancel_timeout is not None:
            self._cancel_timeout()
        self._cancel_timeout = async_call_later(
            self.hass, FOCUS_LEASE_SECONDS, self._expired
        )

    @callback
    def _expired(self, _now: datetime) -> None:
        self.remove()

    @callback
    def _entry_changed(
        self, _change: ConfigEntryChange, entry: ConfigEntry[Any]
    ) -> None:
        if entry.entry_id == self.entry.entry_id and (
            entry is not self.entry
            or entry.state is not ConfigEntryState.LOADED
            or getattr(entry, "runtime_data", None) is not self.hub
        ):
            self.remove()


def _focus_entry(
    hass: HomeAssistant,
    connection: ActiveConnection,
    message_id: int,
    entry_id: str,
    view: PanelFocus,
) -> tuple[ConfigEntry[Any], SpeedportHub] | None:
    """Apply the panel's existing entity-read boundary to a loaded entry."""
    from .panel import _can_read_entity, _loaded_hub  # noqa: PLC0415

    user = connection.user
    if user is None or (view == "administration" and not user.is_admin):
        connection.send_error(message_id, "unauthorized", "Insufficient permissions")
        return None
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.entry_id != entry_id or entry.domain != DOMAIN:
        connection.send_error(message_id, "entry_not_found", "Config entry not found")
        return None
    hub = _loaded_hub(entry)
    if entry.state is not ConfigEntryState.LOADED or hub is None:
        connection.send_error(message_id, "entry_not_loaded", "Config entry not loaded")
        return None
    if not user.is_admin and not any(
        entity.disabled_by is None and _can_read_entity(connection, entity.entity_id)
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    ):
        connection.send_error(message_id, "unauthorized", "Insufficient permissions")
        return None
    return entry, hub


def _positive_subscription_id(value: Any) -> int:
    """Reject bools and coercible strings as well as nonpositive identifiers."""
    if type(value) is not int or value < 1:
        raise vol.Invalid("Expected a positive integer")
    return value


@websocket_command(
    {
        vol.Required("type"): _FOCUS_TYPE,
        vol.Required("entry_id"): vol.All(str, vol.Length(min=1, max=64)),
        vol.Required("view"): vol.In(("dashboard", "administration")),
    }
)
@callback
def websocket_panel_focus(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to one short-lived panel focus lease."""
    resolved = _focus_entry(hass, connection, msg["id"], msg["entry_id"], msg["view"])
    if resolved is None:
        return
    if (
        msg["id"] in connection.subscriptions
        or sum(
            isinstance(subscription, _FocusSubscription)
            for subscription in connection.subscriptions.values()
        )
        >= _MAX_FOCUS_SUBSCRIPTIONS
    ):
        connection.send_error(
            msg["id"], "focus_limit_reached", "Panel focus subscription limit reached"
        )
        return
    entry, hub = resolved
    try:
        subscription = _FocusSubscription(
            hass,
            connection,
            entry,
            hub,
            subscription_id=msg["id"],
            view=msg["view"],
        )
    except PollingPriorityGateClosed:
        connection.send_error(msg["id"], "entry_not_loaded", "Config entry not loaded")
        return
    connection.subscriptions[msg["id"]] = subscription
    connection.send_result(msg["id"])
    connection.send_event(
        msg["id"],
        {"subscription_id": msg["id"], "expires_in_seconds": FOCUS_LEASE_SECONDS},
    )


@websocket_command(
    {
        vol.Required("type"): _RENEW_TYPE,
        vol.Required("subscription_id"): _positive_subscription_id,
    }
)
@callback
def websocket_panel_focus_renew(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Renew only a focus subscription on this exact websocket connection."""
    subscription = connection.subscriptions.get(msg["subscription_id"])
    if not isinstance(subscription, _FocusSubscription):
        connection.send_error(
            msg["id"], "focus_not_found", "Panel focus lease not found"
        )
        return
    resolved = _focus_entry(
        hass, connection, msg["id"], subscription.entry.entry_id, subscription.view
    )
    if resolved is None:
        subscription.remove()
        return
    entry, hub = resolved
    if (
        entry is not subscription.entry
        or hub is not subscription.hub
        or not subscription.renew()
    ):
        subscription.remove()
        connection.send_error(
            msg["id"], "focus_not_found", "Panel focus lease not found"
        )
        return
    connection.send_result(msg["id"], {"expires_in_seconds": FOCUS_LEASE_SECONDS})
