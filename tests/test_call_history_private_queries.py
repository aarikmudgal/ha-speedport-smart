"""Private call-history routes with mocked I/O, session ownership and admin checks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.call_history import CALL_HISTORY_SPECS
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.hub import AdminQueryRateLimitError, SpeedportHub
from custom_components.speedport_smart.models import EndpointCapability
from custom_components.speedport_smart.panel_queries import (
    PANEL_CALL_HISTORY_WS_TYPE,
    async_register_admin_query_commands,
    websocket_call_history,
)


def _raw() -> dict[str, Any]:
    return {
        "addtakencalls": [
            {
                "takencalls_date": "02.09.2026",
                "takencalls_time": "12:34",
                "takencalls_who": "PRIVATE-CALLER",
                "takencalls_as": "PRIVATE-LINE",
                "takencalls_duration": "12",
                "secret": "UNRELATED-SECRET",
            }
        ],
        "unrelated": "UNRELATED-SECRET",
    }


def _capability(
    client: MagicMock,
    *,
    endpoint: str = "data/PhoneCalls.json",
    authenticated: bool = True,
) -> None:
    report = client.setup.return_value
    endpoints = dict(report.feature_endpoints)
    endpoints["calls"] = EndpointCapability(
        "calls", endpoint, authenticated=authenticated
    )
    client.setup.return_value = replace(
        report, feature_endpoints=MappingProxyType(endpoints)
    )


@pytest.mark.parametrize("export", [False, True])
async def test_client_uses_one_exact_authenticated_get_and_no_router_export(
    export: bool,  # noqa: FBT001 -- parametrized wire boolean
) -> None:
    """Private viewing and local CSV export share only the exact authenticated GET."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get, post = AsyncMock(return_value=_raw()), AsyncMock()
    with (
        patch.object(client, "get_json", get),
        patch.object(client, "_post_json_unlocked", post),
    ):
        result = await client.query_call_history(category="taken", export=export)
    get.assert_awaited_once_with(
        "data/PhoneCalls.json",
        authenticated=True,
        referer="html/content/phone/phone_call_taken.html",
    )
    post.assert_not_awaited()
    assert "PRIVATE-CALLER" in repr(result)
    assert "UNRELATED-SECRET" not in repr(result)
    assert ("private_download" in result) is export


@pytest.mark.parametrize("category", CALL_HISTORY_SPECS)
async def test_client_exact_category_referer_with_explicit_empty_list(
    category: str,
) -> None:
    """Each fixed category uses its native page referer and accepts explicit empty."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    spec = CALL_HISTORY_SPECS[category]
    get = AsyncMock(return_value={spec.collection: []})
    with patch.object(client, "get_json", get):
        assert await client.query_call_history(category=category) == {
            "category": category,
            "entries": [],
            "total": 0,
        }
    get.assert_awaited_once_with(
        "data/PhoneCalls.json", authenticated=True, referer=spec.referer
    )


@pytest.mark.parametrize(
    "parameters",
    [
        {"category": "../Other.json"},
        {"category": "TAKEN"},
        {"category": []},
        {"category": "taken", "export": 1},
        {"category": "taken", "export": "true"},
    ],
)
async def test_client_rejects_invalid_selectors_before_io(
    parameters: dict[str, Any],
) -> None:
    """No malformed selector can reach the router transport."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get = AsyncMock()
    with patch.object(client, "get_json", get), pytest.raises(ConfigurationError):
        await client.query_call_history(**parameters)
    get.assert_not_awaited()


@pytest.mark.parametrize("export", [False, True])
async def test_client_missing_history_cannot_be_viewed_or_exported(
    export: bool,  # noqa: FBT001 -- parametrized wire boolean
) -> None:
    """A global-only fallback cannot become an empty private result."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    with (
        patch.object(
            client, "get_json", AsyncMock(return_value={"router_state": "OK"})
        ),
        pytest.raises(ConfigurationError),
    ):
        await client.query_call_history(category="taken", export=export)


async def test_hub_shares_lock_cleanup_rate_limit_without_publishing_history(
    hass: Any, mock_speedport_client: MagicMock
) -> None:
    """Private reads share operation ownership but never update coordinator state."""
    _capability(mock_speedport_client)
    now = [100.0]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=False,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    before = hub.data
    mock_speedport_client.query_call_history = AsyncMock(
        return_value={"category": "taken", "entries": ["PRIVATE-CALLER"]}
    )
    async with hub._operation_lock:  # noqa: SLF001 -- prove existing shared owner
        task = asyncio.create_task(hub.async_query_call_history(category="taken"))
        await asyncio.sleep(0)
        mock_speedport_client.query_call_history.assert_not_awaited()
    assert "PRIVATE-CALLER" in repr(await task)
    assert hub.data is before
    assert "PRIVATE-CALLER" not in repr(hub.data)
    mock_speedport_client.logout.assert_awaited_once()
    with pytest.raises(AdminQueryRateLimitError):
        await hub.async_query_call_history(category="missed", export=True)
    assert mock_speedport_client.query_call_history.await_count == 1


@pytest.mark.parametrize(
    ("endpoint", "authenticated"),
    [("data/Other.json", True), ("data/PhoneCalls.json", False)],
)
async def test_hub_requires_exact_authenticated_capability(
    hass: Any,
    mock_speedport_client: MagicMock,
    endpoint: str,
    authenticated: bool,  # noqa: FBT001 -- parametrized capability evidence
) -> None:
    """A family name or unauthenticated candidate alone cannot authorize reads."""
    _capability(mock_speedport_client, endpoint=endpoint, authenticated=authenticated)
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_call_history = AsyncMock()
    with pytest.raises(HomeAssistantError, match="unsupported by this router"):
        await hub.async_query_call_history(category="taken")
    mock_speedport_client.query_call_history.assert_not_awaited()


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_hub_failure_cleanup_never_exposes_private_values(
    hass: Any,
    mock_speedport_client: MagicMock,
    caplog: Any,
    cleanup_failure: bool,  # noqa: FBT001 -- parametrized failure phase
) -> None:
    """Read or session-cleanup failures discard results and return fixed errors."""
    _capability(mock_speedport_client)
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_call_history = AsyncMock(
        return_value={"PRIVATE-CALLER": "PRIVATE-LINE"},
        side_effect=None if cleanup_failure else RuntimeError("PRIVATE-CALLER"),
    )
    if cleanup_failure:
        mock_speedport_client.logout.side_effect = RuntimeError("PRIVATE-SESSION")
    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_query_call_history(category="taken", export=True)
    assert "PRIVATE" not in str(failure.value) + repr(hub.data) + caplog.text
    mock_speedport_client.logout.assert_awaited_once()


def test_websocket_schema_is_closed_and_requires_strict_export_boolean() -> None:
    """Only declared categories and real JSON booleans are accepted."""
    schema = websocket_call_history._ws_schema  # noqa: SLF001 -- validate registered schema
    valid = {
        "id": 1,
        "type": PANEL_CALL_HISTORY_WS_TYPE,
        "entry_id": "entry-a",
        "category": "taken",
    }
    assert schema(valid) == valid
    assert schema({**valid, "export": True})["export"] is True
    for change in (
        {"category": "all"},
        {"category": "../Other.json"},
        {"export": 1},
        {"export": "false"},
        {"endpoint": "data/Other.json"},
    ):
        with pytest.raises(vol.Invalid):
            schema({**valid, **change})


def test_non_admin_is_rejected_before_entry_lookup() -> None:
    """Administrator authorization precedes all entry resolution and scheduling."""
    hass, connection = MagicMock(), MagicMock()
    connection.user.is_admin = False
    with pytest.raises(Unauthorized):
        websocket_call_history(hass, connection, {"id": 1})
    hass.config_entries.async_get_entry.assert_not_called()


@pytest.mark.parametrize("export", [False, True])
async def test_websocket_returns_only_to_requesting_loaded_entry(
    export: bool,  # noqa: FBT001 -- parametrized wire boolean
) -> None:
    """The command resolves one loaded entry and replies to its requesting socket."""
    result = {"category": "taken", "private_download": {"content": "PRIVATE-CALLER"}}
    hub = SimpleNamespace(async_query_call_history=AsyncMock(return_value=result))
    entry = SimpleNamespace(
        domain="speedport_smart", state=ConfigEntryState.LOADED, runtime_data=hub
    )
    hass, connection = MagicMock(), MagicMock()
    msg = {
        "id": 3,
        "type": PANEL_CALL_HISTORY_WS_TYPE,
        "entry_id": "entry-a",
        "category": "taken",
        "export": export,
    }
    handler = websocket_call_history.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await handler(hass, connection, msg)
    hub.async_query_call_history.assert_awaited_once_with(
        category="taken", export=export
    )
    connection.send_result.assert_called_once_with(
        3, {"schema_version": 1, "query": "call_history", "result": result}
    )
    connection.send_error.assert_not_called()


def test_call_history_legacy_websocket_rejection_is_registered_once() -> None:
    """Private WebSocket is retired; the old name receives one inert upgrade stub."""
    with patch(
        "custom_components.speedport_smart.panel_queries.websocket_api.async_register_command"
    ) as register:
        async_register_admin_query_commands(MagicMock())
    assert (
        sum(
            call.args[1]._ws_command == PANEL_CALL_HISTORY_WS_TYPE  # noqa: SLF001
            and call.args[1] is not websocket_call_history
            for call in register.call_args_list
        )
        == 1
    )
