"""Prove panel focus ownership, authorization, and local-only cleanup."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.config_entries import ConfigEntryChange, ConfigEntryState

from custom_components.speedport_smart import panel as panel_module
from custom_components.speedport_smart import panel_focus as focus_module
from custom_components.speedport_smart.panel_focus import (
    async_register_focus_commands,
    websocket_panel_focus,
    websocket_panel_focus_renew,
)
from custom_components.speedport_smart.polling_priority import PollingPriorityGateClosed


@dataclass
class _FocusEnvironment:
    hass: Any
    connection: Any
    entry: Any
    hub: Any
    timer: Any
    listener: Any
    entities: Any


@pytest.fixture
def focus_env() -> Iterator[_FocusEnvironment]:
    """Provide a loaded router, permitted dashboard user, and controlled expiry."""
    hub = SimpleNamespace(
        capability_report=SimpleNamespace(),
        polling_priority=MagicMock(),
        client=MagicMock(),
    )
    hub.polling_priority.renew_focus.return_value = True
    entry = SimpleNamespace(
        entry_id="entry-1",
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    connection = MagicMock()
    connection.subscriptions = {}
    connection.user.is_admin = False
    connection.user.permissions.access_all_entities.return_value = False
    connection.user.permissions.check_entity.return_value = True
    with (
        patch.object(focus_module, "async_call_later") as timer,
        patch.object(focus_module, "async_dispatcher_connect") as listener,
        patch.object(focus_module.er, "async_get"),
        patch.object(
            focus_module.er,
            "async_entries_for_config_entry",
            return_value=[
                SimpleNamespace(entity_id="sensor.router_download", disabled_by=None)
            ],
        ) as entities,
    ):
        yield _FocusEnvironment(hass, connection, entry, hub, timer, listener, entities)
    assert hub.client.mock_calls == []


def _focus_message(*, message_id: int = 7, view: str = "dashboard") -> dict[str, Any]:
    return {
        "id": message_id,
        "type": "speedport_smart/panel/focus",
        "entry_id": "entry-1",
        "view": view,
    }


def _renew_message(subscription_id: int = 7) -> dict[str, Any]:
    return {
        "id": 20,
        "type": "speedport_smart/panel/focus/renew",
        "subscription_id": subscription_id,
    }


def _subscribe(env: _FocusEnvironment, **kwargs: Any) -> None:
    websocket_panel_focus(env.hass, env.connection, _focus_message(**kwargs))


def test_focus_ack_and_event_contain_only_local_lease_metadata(
    focus_env: _FocusEnvironment,
) -> None:
    """A readable router grants a local lease without exposing router data."""
    _subscribe(focus_env)
    connection = focus_env.connection
    assert list(connection.subscriptions) == [7]
    connection.send_result.assert_called_once_with(7)
    connection.send_event.assert_called_once_with(
        7, {"subscription_id": 7, "expires_in_seconds": 45}
    )
    focus_env.hub.polling_priority.set_focus.assert_called_once()
    owner, view = focus_env.hub.polling_priority.set_focus.call_args.args
    assert type(owner) is object
    assert view == "dashboard"
    focus_env.timer.assert_called_once()
    assert focus_env.timer.call_args.args[:2] == (focus_env.hass, 45)
    connection.user.permissions.check_entity.assert_called_once_with(
        "sensor.router_download", "read"
    )


@pytest.mark.parametrize("view", ["dashboard", "administration"])
def test_admin_can_focus_without_readable_entities(
    focus_env: _FocusEnvironment, view: str
) -> None:
    """Match panel visibility for administrators even without enabled entities."""
    focus_env.connection.user.is_admin = True
    focus_env.entities.return_value = []
    _subscribe(focus_env, view=view)
    focus_env.connection.send_error.assert_not_called()
    assert focus_env.hub.polling_priority.set_focus.call_args.args[1] == view


def test_administration_denies_non_admin_before_entry_lookup(
    focus_env: _FocusEnvironment,
) -> None:
    """Read permission cannot grant administrator polling focus."""
    _subscribe(focus_env, view="administration")
    focus_env.hass.config_entries.async_get_entry.assert_not_called()
    assert focus_env.connection.send_error.call_args.args[1] == "unauthorized"
    focus_env.hub.polling_priority.set_focus.assert_not_called()


@pytest.mark.parametrize("reason", ["denied", "disabled", "empty", "no_user"])
def test_dashboard_requires_readable_enabled_entry_entity(
    focus_env: _FocusEnvironment, reason: str
) -> None:
    """Entity read permissions use the same boundary as panel metadata."""
    if reason == "denied":
        focus_env.connection.user.permissions.check_entity.return_value = False
    elif reason == "disabled":
        focus_env.entities.return_value[0].disabled_by = "user"
    elif reason == "empty":
        focus_env.entities.return_value = []
    else:
        focus_env.connection.user = None
    _subscribe(focus_env)
    assert focus_env.connection.send_error.call_args.args[1] == "unauthorized"
    assert not focus_env.connection.subscriptions
    focus_env.hub.polling_priority.set_focus.assert_not_called()


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("missing", "entry_not_found"),
        ("mismatched_id", "entry_not_found"),
        ("other_domain", "entry_not_found"),
        ("unloaded", "entry_not_loaded"),
        ("missing_runtime", "entry_not_loaded"),
        ("closed_gate", "entry_not_loaded"),
    ],
)
def test_focus_requires_exact_loaded_domain_entry(
    focus_env: _FocusEnvironment, case: str, code: str
) -> None:
    """No transitional or unrelated config entry can acquire a lease."""
    if case == "missing":
        focus_env.hass.config_entries.async_get_entry.return_value = None
    elif case == "mismatched_id":
        focus_env.entry.entry_id = "entry-2"
    elif case == "other_domain":
        focus_env.entry.domain = "other"
    elif case == "unloaded":
        focus_env.entry.state = ConfigEntryState.NOT_LOADED
    elif case == "missing_runtime":
        focus_env.entry.runtime_data = None
    else:
        focus_env.hub.polling_priority.set_focus.side_effect = PollingPriorityGateClosed
    _subscribe(focus_env)
    assert focus_env.connection.send_error.call_args.args[1] == code
    assert not focus_env.connection.subscriptions
    focus_env.timer.assert_not_called()
    focus_env.listener.assert_not_called()


def test_renew_extends_existing_owner_without_new_focus_claim(
    focus_env: _FocusEnvironment,
) -> None:
    """A heartbeat cannot steal recency from another explicit claim."""
    _subscribe(focus_env)
    owner = focus_env.hub.polling_priority.set_focus.call_args.args[0]
    websocket_panel_focus_renew(focus_env.hass, focus_env.connection, _renew_message())
    focus_env.hub.polling_priority.renew_focus.assert_called_once_with(owner)
    focus_env.hub.polling_priority.set_focus.assert_called_once()
    focus_env.timer.return_value.assert_called_once_with()
    assert focus_env.timer.call_count == 2
    focus_env.connection.send_result.assert_called_with(20, {"expires_in_seconds": 45})


@pytest.mark.parametrize("case", ["unknown", "other_subscription", "other_connection"])
def test_renew_never_targets_foreign_subscription(
    focus_env: _FocusEnvironment, case: str
) -> None:
    """An identifier has no authority outside its owning websocket connection."""
    _subscribe(focus_env)
    connection = focus_env.connection
    if case == "other_subscription":
        connection.subscriptions[8] = MagicMock()
    elif case == "other_connection":
        connection = MagicMock()
        connection.subscriptions = {}
    websocket_panel_focus_renew(
        focus_env.hass,
        connection,
        _renew_message(7 if case == "other_connection" else 8),
    )
    assert connection.send_error.call_args.args[1] == "focus_not_found"
    focus_env.hub.polling_priority.renew_focus.assert_not_called()
    assert 7 in focus_env.connection.subscriptions


def test_expired_gate_renewal_removes_subscription(
    focus_env: _FocusEnvironment,
) -> None:
    """A late heartbeat cannot revive an expired or closed gate lease."""
    _subscribe(focus_env)
    focus_env.hub.polling_priority.renew_focus.return_value = False
    websocket_panel_focus_renew(focus_env.hass, focus_env.connection, _renew_message())
    assert not focus_env.connection.subscriptions
    assert focus_env.connection.send_error.call_args.args[1] == "focus_not_found"
    focus_env.hub.polling_priority.clear_focus.assert_called_once()
    focus_env.listener.return_value.assert_called_once_with()


@pytest.mark.parametrize("view", ["dashboard", "administration"])
def test_renew_rechecks_revoked_permissions(
    focus_env: _FocusEnvironment, view: str
) -> None:
    """Revoking read or administrator rights immediately releases focus."""
    focus_env.connection.user.is_admin = view == "administration"
    _subscribe(focus_env, view=view)
    focus_env.connection.user.is_admin = False
    focus_env.connection.user.permissions.check_entity.return_value = False
    websocket_panel_focus_renew(focus_env.hass, focus_env.connection, _renew_message())
    assert not focus_env.connection.subscriptions
    assert focus_env.connection.send_error.call_args.args[1] == "unauthorized"
    focus_env.hub.polling_priority.renew_focus.assert_not_called()
    focus_env.hub.polling_priority.clear_focus.assert_called_once()


@pytest.mark.parametrize("case", ["unload", "runtime_replaced", "entry_replaced"])
def test_renew_does_not_follow_reloaded_entry(
    focus_env: _FocusEnvironment, case: str
) -> None:
    """A lease remains bound to the original loaded entry and hub identity."""
    _subscribe(focus_env)
    if case == "unload":
        focus_env.entry.state = ConfigEntryState.NOT_LOADED
    elif case == "runtime_replaced":
        focus_env.entry.runtime_data = SimpleNamespace(
            capability_report=SimpleNamespace()
        )
    else:
        focus_env.hass.config_entries.async_get_entry.return_value = SimpleNamespace(
            **vars(focus_env.entry)
        )
    websocket_panel_focus_renew(focus_env.hass, focus_env.connection, _renew_message())
    assert not focus_env.connection.subscriptions
    focus_env.hub.polling_priority.renew_focus.assert_not_called()
    focus_env.hub.polling_priority.clear_focus.assert_called_once()


@pytest.mark.parametrize("cleanup", ["unsubscribe", "disconnect", "expiry", "unload"])
def test_lifecycle_releases_lease_and_callbacks(
    focus_env: _FocusEnvironment, cleanup: str
) -> None:
    """All lifecycle exits cancel timers, listeners, and the opaque gate owner."""
    _subscribe(focus_env)
    connection = focus_env.connection
    subscription = connection.subscriptions[7]
    if cleanup == "unsubscribe":
        connection.subscriptions.pop(7)()
    elif cleanup == "disconnect":
        connection.subscriptions[8] = MagicMock()
        ActiveConnection.async_handle_close(connection)
        connection.logger.exception.assert_not_called()
    elif cleanup == "expiry":
        focus_env.timer.call_args.args[2](datetime(2026, 9, 3, tzinfo=UTC))
    else:
        focus_env.entry.state = ConfigEntryState.NOT_LOADED
        focus_env.listener.call_args.args[2](ConfigEntryChange.UPDATED, focus_env.entry)
    assert not connection.subscriptions
    subscription()
    focus_env.hub.polling_priority.clear_focus.assert_called_once()
    focus_env.timer.return_value.assert_called_once_with()
    focus_env.listener.return_value.assert_called_once_with()


def test_unrelated_entry_update_preserves_lease(focus_env: _FocusEnvironment) -> None:
    """Other integrations and loaded-entry updates cannot cancel this lease."""
    _subscribe(focus_env)
    listener = focus_env.listener.call_args.args[2]
    listener(ConfigEntryChange.UPDATED, focus_env.entry)
    listener(
        ConfigEntryChange.UPDATED,
        SimpleNamespace(entry_id="other", state=ConfigEntryState.NOT_LOADED),
    )
    assert 7 in focus_env.connection.subscriptions
    focus_env.hub.polling_priority.clear_focus.assert_not_called()


def test_subscription_limit_is_connection_local_and_excludes_other_commands(
    focus_env: _FocusEnvironment,
) -> None:
    """A browser cannot accumulate an unbounded number of focus leases."""
    focus_env.connection.subscriptions[1] = MagicMock()
    for message_id in range(7, 11):
        _subscribe(focus_env, message_id=message_id)
    _subscribe(focus_env, message_id=11)
    assert focus_env.hub.polling_priority.set_focus.call_count == 4
    assert focus_env.connection.send_error.call_args.args[1] == "focus_limit_reached"
    focus_env.connection.subscriptions.pop(7)()
    _subscribe(focus_env, message_id=12)
    assert focus_env.hub.polling_priority.set_focus.call_count == 5


@pytest.mark.parametrize(
    "change",
    [
        {"view": "unknown"},
        {"entry_id": ""},
        {"entry_id": "x" * 65},
        {"entry_id": 3},
        {"extra": "ignored"},
    ],
)
def test_focus_schema_rejects_invalid_or_extra_fields(change: dict[str, Any]) -> None:
    """No extra scope, arbitrary view, or unbounded entry identifier is accepted."""
    schema = getattr(websocket_panel_focus, "_ws_schema")  # noqa: B009
    with pytest.raises(vol.Invalid):
        schema({**_focus_message(), **change})


@pytest.mark.parametrize("value", [True, False, 0, -1, "7", 7.0, None])
def test_renew_schema_requires_strict_positive_integer(value: Any) -> None:
    """A boolean or coercible string cannot alias another subscription number."""
    schema = getattr(websocket_panel_focus_renew, "_ws_schema")  # noqa: B009
    with pytest.raises(vol.Invalid):
        schema({**_renew_message(), "subscription_id": value})
    with pytest.raises(vol.Invalid):
        schema({**_renew_message(), "entry_id": "entry-2"})


def test_registration_exposes_only_two_local_commands() -> None:
    """Focus does not register router operations or generic command dispatch."""
    hass = MagicMock()
    with patch.object(focus_module.websocket_api, "async_register_command") as register:
        async_register_focus_commands(hass)
    assert [call.args[1] for call in register.call_args_list] == [
        websocket_panel_focus,
        websocket_panel_focus_renew,
    ]


async def test_panel_setup_registers_focus_once() -> None:
    """Config-entry reloads cannot duplicate the global websocket commands."""
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    with (
        patch.object(panel_module.websocket_api, "async_register_command"),
        patch.object(panel_module.panel_custom, "async_register_panel", AsyncMock()),
        patch.object(panel_module, "async_register_focus_commands") as register,
    ):
        await panel_module.async_register_panel(hass)
        await panel_module.async_register_panel(hass)
    register.assert_called_once_with(hass)
