"""Maintenance lifecycle checks through the client, hub and administrator route."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized

from custom_components.speedport_smart.admin_actions import ADMIN_ACTION_CONTRACTS
from custom_components.speedport_smart.api import (
    SpeedportClient,
    SpeedportConnectionError,
    SpeedportMutationOutcomeUnknownError,
    SpeedportProtocolError,
)
from custom_components.speedport_smart.hub import (
    AdminActionConfirmationError,
    AdminActionRateLimitError,
    AdminActionUnavailableError,
    SpeedportHub,
)
from custom_components.speedport_smart.maintenance import maintenance_payload
from custom_components.speedport_smart.panel_queries import websocket_maintenance

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_FACTORY_PARAMETERS = {"backup_saved": True, "physical_access": True}
_EMPTY_LOG = {"router_state": "OK", "filter_log": "0", "addmessage": []}


async def _hub(hass: HomeAssistant, client: MagicMock) -> SpeedportHub:
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="entry",
        controls_enabled=True,
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()
    client.get_json.reset_mock()
    client.logout_ephemeral.reset_mock()
    return hub


@pytest.mark.parametrize(
    ("action", "parameters"),
    [
        ("system_factory_reset", _FACTORY_PARAMETERS),
        ("system_dect_reset", {"retain_registrations": False}),
        (
            "system_dsl_modem_mode",
            {
                **_FACTORY_PARAMETERS,
                "link_lan1_ready": True,
                "firewall_warning_accepted": True,
            },
        ),
        ("system_log_clear", {}),
    ],
)
async def test_client_fixed_maintenance_sender_posts_once_with_token(
    action: str, parameters: dict[str, bool]
) -> None:
    """Only the contract's fixed fields, route, referer and token reach transport."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    contract = ADMIN_ACTION_CONTRACTS[action]
    post = AsyncMock(return_value={})
    with (
        patch.object(client, "_ensure_authenticated_unlocked", AsyncMock()),
        patch.object(
            client, "_get_http_token_unlocked", AsyncMock(return_value="test-token")
        ),
        patch.object(client, "_post_json_unlocked", post),
    ):
        await client.post_maintenance_action(action, parameters)
    post.assert_awaited_once_with(
        contract.endpoint,
        {**maintenance_payload(action, parameters), "httoken": "test-token"},
        authenticated=True,
        referer=contract.referer,
        ensure_auth=False,
        resolve_http_token=False,
    )


async def test_client_never_retries_failed_maintenance_post() -> None:
    """The generic recovery loop cannot replay an irreversible mutation."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(side_effect=SpeedportConnectionError("PRIVATE"))
    with (
        patch.object(client, "_ensure_authenticated_unlocked", AsyncMock()),
        patch.object(client, "_get_http_token_unlocked", AsyncMock(return_value=None)),
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportMutationOutcomeUnknownError),
    ):
        await client.post_maintenance_action(
            "system_factory_reset", _FACTORY_PARAMETERS
        )
    post.assert_awaited_once()


async def test_hub_reconnect_result_invalidates_and_cleans_without_eager_refresh(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Factory reset cannot follow the generic Boolean success/refresh path."""
    hub = await _hub(hass, mock_speedport_client)
    mock_speedport_client.get_json.return_value = {"router_state": "OK"}
    with patch.object(hub, "_async_fetch_families", AsyncMock()) as refresh:
        result = await hub.async_execute_admin_action(
            "system_factory_reset",
            confirmed=True,
            confirmation_text="FACTORY RESET ROUTER",
            **_FACTORY_PARAMETERS,
        )
    assert result == {
        "status": "outcome_unknown",
        "verification": "reconnect_required",
        "retry_safe": False,
    }
    assert hub.get("management.access.state") == "unavailable"
    refresh.assert_not_awaited()
    mock_speedport_client.get_json.assert_awaited_once_with(
        "data/Reboot.json", authenticated=True, referer="html/content/config/reset.html"
    )
    mock_speedport_client.post_maintenance_action.assert_awaited_once()
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


async def test_hub_failed_cleanup_never_reports_log_success(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Even an empty read cannot report success when the session remains unconfirmed."""
    hub = await _hub(hass, mock_speedport_client)
    mock_speedport_client.get_json.return_value = _EMPTY_LOG
    mock_speedport_client.logout_ephemeral.side_effect = SpeedportProtocolError(
        "PRIVATE"
    )
    result = await hub.async_execute_admin_action(
        "system_log_clear",
        confirmed=True,
        confirmation_text="CLEAR SYSTEM MESSAGES",
    )
    assert result == {
        "status": "outcome_unknown",
        "verification": "session_cleanup_failed",
        "retry_safe": False,
    }
    mock_speedport_client.post_maintenance_action.assert_not_awaited()
    assert "PRIVATE" not in repr(result)


async def test_hub_preflight_failure_cleans_and_never_mutates(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Missing exact runtime state is an error, not a ready-state assumption."""
    hub = await _hub(hass, mock_speedport_client)
    mock_speedport_client.get_json.return_value = {}
    with pytest.raises(AdminActionUnavailableError):
        await hub.async_execute_admin_action(
            "system_factory_reset",
            confirmed=True,
            confirmation_text="FACTORY RESET ROUTER",
            **_FACTORY_PARAMETERS,
        )
    mock_speedport_client.post_maintenance_action.assert_not_awaited()
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


async def test_hub_confirmation_before_io_and_rate_limit_after_first_action(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Incorrect operation phrases and duplicate requests cannot trigger a POST."""
    hub = await _hub(hass, mock_speedport_client)
    with pytest.raises(AdminActionConfirmationError):
        await hub.async_execute_admin_action(
            "system_factory_reset",
            confirmed=True,
            confirmation_text="RESET DECT SETTINGS",
            **_FACTORY_PARAMETERS,
        )
    mock_speedport_client.get_json.assert_not_awaited()
    mock_speedport_client.get_json.return_value = _EMPTY_LOG
    await hub.async_execute_admin_action(
        "system_log_clear",
        confirmed=True,
        confirmation_text="CLEAR SYSTEM MESSAGES",
    )
    with pytest.raises(AdminActionRateLimitError):
        await hub.async_execute_admin_action(
            "system_log_clear",
            confirmed=True,
            confirmation_text="CLEAR SYSTEM MESSAGES",
        )
    assert mock_speedport_client.get_json.await_count == 1


def test_maintenance_route_is_closed_and_admin_only() -> None:
    """Only the four action IDs and real Boolean input vocabulary are accepted."""
    valid = {
        "id": 1,
        "type": "speedport_smart/panel/maintenance",
        "entry_id": "entry",
        "action": "system_factory_reset",
        "parameters": _FACTORY_PARAMETERS,
        "confirmed": True,
        "confirmation_text": "FACTORY RESET ROUTER",
    }
    schema = websocket_maintenance._ws_schema  # noqa: SLF001
    assert schema(valid) == valid
    for changes in (
        {"confirmed": 1},
        {"action": "reboot"},
        {"parameters": {"backup_saved": "true"}},
        {"parameters": {"endpoint": "PRIVATE"}},
        {"unexpected": "PRIVATE"},
    ):
        with pytest.raises(vol.Invalid):
            schema({**valid, **changes})
    connection = MagicMock()
    connection.user.is_admin = False
    hass = MagicMock()
    with pytest.raises(Unauthorized):
        websocket_maintenance(hass, connection, valid)
    hass.config_entries.async_get_entry.assert_not_called()


async def test_maintenance_route_preserves_entry_and_requester_binding() -> None:
    """Use the existing administrator authorization and result envelope."""
    outcome = {
        "status": "outcome_unknown",
        "verification": "reconnect_required",
        "retry_safe": False,
    }
    hub = SimpleNamespace(async_execute_admin_action=AsyncMock(return_value=outcome))
    entry = SimpleNamespace(
        domain="speedport_smart", state=ConfigEntryState.LOADED, runtime_data=hub
    )
    hass = MagicMock()
    connection = MagicMock()
    connection.user.id = "user-1"
    connection.refresh_token_id = "session-1"  # noqa: S105 - synthetic session identity
    msg: dict[str, Any] = {
        "id": 1,
        "entry_id": "entry",
        "action": "system_dect_reset",
        "parameters": {"retain_registrations": False},
        "confirmed": True,
        "confirmation_text": "RESET DECT SETTINGS",
    }
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await websocket_maintenance.__wrapped__.__wrapped__(hass, connection, msg)
    hub.async_execute_admin_action.assert_awaited_once_with(
        "system_dect_reset",
        confirmed=True,
        confirmation_text="RESET DECT SETTINGS",
        requester=("user-1", "session-1"),
        retain_registrations=False,
    )
    connection.send_result.assert_called_once_with(
        1,
        {
            "schema_version": 1,
            "action": "system_dect_reset",
            "result": outcome,
        },
    )
