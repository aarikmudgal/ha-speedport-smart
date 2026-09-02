"""Tests for administrator-only ephemeral router queries."""

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

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
)
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import (
    AdminQueryRateLimitError,
    SpeedportHub,
)
from custom_components.speedport_smart.models import EndpointCapability
from custom_components.speedport_smart.panel_queries import (
    PANEL_PHONEBOOK_SEARCH_WS_TYPE,
    _send_private_query_result,
    websocket_phonebook_search,
)


def _enable_private_query_capability(
    mock_speedport_client: MagicMock,
    family: str,
    endpoint: str,
) -> None:
    """Add one exact authenticated query proof to the setup report."""
    report = mock_speedport_client.setup.return_value
    endpoints = dict(report.feature_endpoints)
    endpoints[family] = EndpointCapability(
        family,
        endpoint,
        authenticated=True,
    )
    mock_speedport_client.setup.return_value = replace(
        report,
        feature_endpoints=MappingProxyType(endpoints),
    )


@pytest.mark.asyncio
async def test_ip_pbx_refresh_uses_exact_query_contract_and_filters_secrets() -> None:
    """The refresh POST returns one allowlisted row and never its password."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        return_value={
            "addipclient": [
                {
                    "id": "2",
                    "ipclient_status": "1",
                    "ipclient_mdevice_name": "Office phone",
                    "ipclient_mdevice_ipv4": "192.168.2.20",
                    "ipclient_mdevice_mac": "aa:bb:cc:dd:ee:ff",
                    "ipclient_password": "PRIVATE-PBX-PASSWORD",
                }
            ]
        }
    )

    with patch.object(client, "_post_json_unlocked", post):
        result = await client.query_ip_pbx_client(client_id="2")

    post.assert_awaited_once_with(
        "data/IPClients.json",
        {"refresh": "2"},
        authenticated=True,
        referer="html/content/phone/phone_ippbx.html",
    )
    assert result == {
        "client_id": "2",
        "status": "registered",
        "status_code": 1,
        "name": "Office phone",
        "ipv4": "192.168.2.20",
        "mac": "AA:BB:CC:DD:EE:FF",
    }
    assert "PRIVATE-PBX-PASSWORD" not in repr(result)


@pytest.mark.asyncio
async def test_phonebook_search_uses_exact_contract_and_bounded_projection() -> None:
    """Search returns reviewed summary fields without passing raw values through."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        return_value={
            "addbookentry": [
                {
                    "id": "8",
                    "name": "Example",
                    "vorname": "Alice",
                    "number:1": "+49 30 1234",
                    "private_note": "PRIVATE-NOTE",
                }
            ],
            "num_entries": "1",
            "router_secret": "PRIVATE-SECRET",
        }
    )

    with patch.object(client, "_post_json_unlocked", post):
        result = await client.query_phonebook_entries(phonebook_id=0, prefix="E")

    post.assert_awaited_once_with(
        "data/PhoneBook.json",
        {"obnr": 0, "search": "E"},
        authenticated=True,
        referer="html/content/phone/phone_book.html",
    )
    assert result == {
        "phonebook_id": 0,
        "prefix": "E",
        "entries": [
            {
                "contact_id": "8",
                "last_name": "Example",
                "first_name": "Alice",
                "number": "+49 30 1234",
            }
        ],
        "truncated": False,
        "total": 1,
    }
    assert "PRIVATE" not in repr(result)


@pytest.mark.asyncio
async def test_phonebook_search_caps_router_controlled_rows() -> None:
    """A router cannot make one private WebSocket response unbounded."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        return_value={
            "addbookentry": [
                {"id": str(index), "name": f"Contact {index}"} for index in range(300)
            ],
            "num_entries": "300",
        }
    )

    with patch.object(client, "_post_json_unlocked", post):
        result = await client.query_phonebook_entries(phonebook_id=4, prefix="")

    assert len(result["entries"]) == 256
    assert result["truncated"] is True
    assert result["total"] == 300


@pytest.mark.asyncio
async def test_phonebook_contact_uses_exact_contract_and_allowlist() -> None:
    """Detail lookup is ephemeral and discards fields outside the reviewed form."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        return_value={
            "name": "Example",
            "vorname": "Alice",
            "number_p": "+49 30 1234",
            "number_a": "030/999",
            "number_m": "0170-123",
            "number_n": "0171-456",
            "strasse": "Example Street 1",
            "plz": "10115",
            "ort": "Berlin",
            "geburtstag": "01.02.1990",
            "unexpected_private_value": "PRIVATE-UNKNOWN",
        }
    )

    with patch.object(client, "_post_json_unlocked", post):
        result = await client.query_phonebook_contact(
            phonebook_id=1,
            contact_id="8",
        )

    post.assert_awaited_once_with(
        "data/PhoneBookEntry.json",
        {"obnr": 1, "chgid": "8"},
        authenticated=True,
        referer="html/content/phone/phone_book.html",
    )
    assert result == {
        "phonebook_id": 1,
        "contact_id": "8",
        "contact": {
            "last_name": "Example",
            "first_name": "Alice",
            "private_number": "+49 30 1234",
            "work_number": "030/999",
            "mobile_number": "0170-123",
            "secondary_mobile_number": "0171-456",
            "street": "Example Street 1",
            "postal_code": "10115",
            "city": "Berlin",
            "birthday": "01.02.1990",
        },
    }
    assert "PRIVATE-UNKNOWN" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("query_ip_pbx_client", {"client_id": "../bad"}),
        ("query_phonebook_entries", {"phonebook_id": True, "prefix": "A"}),
        ("query_phonebook_entries", {"phonebook_id": 0, "prefix": "AB"}),
        (
            "query_phonebook_contact",
            {"phonebook_id": 5, "contact_id": "1"},
        ),
    ],
)
async def test_private_query_inputs_fail_before_router_io(
    method: str,
    kwargs: dict[str, object],
) -> None:
    """Malformed IDs and selectors cannot reach the serialized POST boundary."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock()

    with (
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportProtocolError),
    ):
        await getattr(client, method)(**kwargs)

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_hub_private_queries_are_ephemeral_serialized_and_rate_limited(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """Queries share the operation owner and never alter coordinator data."""
    _enable_private_query_capability(
        mock_speedport_client,
        "pbx_clients",
        "data/IPClients.json",
    )
    now = [100.0]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    before = hub.data

    async def query(*, client_id: str) -> dict[str, object]:
        return {"client_id": client_id, "status": "registered"}

    mock_speedport_client.query_ip_pbx_client = AsyncMock(side_effect=query)
    async with hub._operation_lock:  # noqa: SLF001 - prove shared serialization
        task = asyncio.create_task(hub.async_query_ip_pbx_client(client_id="2"))
        await asyncio.sleep(0)
        mock_speedport_client.query_ip_pbx_client.assert_not_awaited()
    assert await task == {"client_id": "2", "status": "registered"}
    assert hub.data is before
    mock_speedport_client.logout.assert_awaited()

    current_data = hub.data
    with pytest.raises(AdminQueryRateLimitError) as failure:
        await hub.async_query_ip_pbx_client(client_id="2")
    assert failure.value.retry_after == 5.0
    assert hub.data is current_data
    assert mock_speedport_client.query_ip_pbx_client.await_count == 1


@pytest.mark.asyncio
async def test_hub_private_query_does_not_require_router_controls(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """Read-only private queries remain available when mutations are disabled."""
    _enable_private_query_capability(
        mock_speedport_client,
        "phonebook",
        "data/PhoneBook.json",
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=False,
    )
    await hub.async_setup()
    mock_speedport_client.query_phonebook_entries = AsyncMock(
        return_value={"phonebook_id": 0, "entries": []}
    )

    result = await hub.async_query_phonebook_entries(phonebook_id=0, prefix="")

    assert result == {"phonebook_id": 0, "entries": []}
    mock_speedport_client.query_phonebook_entries.assert_awaited_once_with(
        phonebook_id=0,
        prefix="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("hub_method", "client_method", "kwargs"),
    [
        (
            "async_query_ip_pbx_client",
            "query_ip_pbx_client",
            {"client_id": "2"},
        ),
        (
            "async_query_phonebook_entries",
            "query_phonebook_entries",
            {"phonebook_id": 0, "prefix": "A"},
        ),
        (
            "async_query_phonebook_contact",
            "query_phonebook_contact",
            {"phonebook_id": 0, "contact_id": "8"},
        ),
    ],
)
async def test_hub_private_queries_require_exact_discovered_endpoint(
    hass: Any,
    mock_speedport_client: MagicMock,
    hub_method: str,
    client_method: str,
    kwargs: dict[str, object],
) -> None:
    """A protected session alone never authorizes a private endpoint POST."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    query = AsyncMock()
    setattr(mock_speedport_client, client_method, query)

    with pytest.raises(HomeAssistantError, match="unsupported by this router"):
        await getattr(hub, hub_method)(**kwargs)

    query.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "authenticated"),
    [
        ("data/Other.json", True),
        ("data/PhoneBook.json", False),
    ],
    ids=["wrong-endpoint", "not-authenticated"],
)
async def test_phonebook_query_rejects_inexact_capability_proof(
    hass: Any,
    mock_speedport_client: MagicMock,
    endpoint: str,
    authenticated: bool,  # noqa: FBT001
) -> None:
    """Family name alone cannot authorize the private PhoneBook POST."""
    report = mock_speedport_client.setup.return_value
    endpoints = dict(report.feature_endpoints)
    endpoints["phonebook"] = EndpointCapability(
        "phonebook",
        endpoint,
        authenticated=authenticated,
    )
    mock_speedport_client.setup.return_value = replace(
        report,
        feature_endpoints=MappingProxyType(endpoints),
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_phonebook_entries = AsyncMock()

    with pytest.raises(HomeAssistantError, match="unsupported by this router"):
        await hub.async_query_phonebook_entries(phonebook_id=0, prefix="A")

    mock_speedport_client.query_phonebook_entries.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "state", "retry_after", "browser_logout_required"),
    [
        (
            SpeedportSessionBusyError("PRIVATE-BUSY-DETAIL"),
            "blocked",
            None,
            True,
        ),
        (
            SpeedportLoginLockedError(retry_after=27),
            "locked",
            27,
            False,
        ),
        (
            SpeedportInvalidCredentialsError("PRIVATE-CREDENTIAL-DETAIL"),
            "unavailable",
            None,
            False,
        ),
        (
            SpeedportAuthenticationError("PRIVATE-AUTH-DETAIL"),
            "unavailable",
            None,
            False,
        ),
    ],
)
async def test_private_query_failure_updates_only_safe_management_state(  # noqa: PLR0917
    hass: Any,
    mock_speedport_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    state: str,
    retry_after: int | None,
    browser_logout_required: bool,  # noqa: FBT001
) -> None:
    """Session failures update their safe gate without retaining query values."""
    _enable_private_query_capability(
        mock_speedport_client,
        "phonebook",
        "data/PhoneBook.json",
    )
    entry = MagicMock()
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
    )
    await hub.async_setup()
    hub._family_data["wifi"] = {"wifi": {"enabled": True}}  # noqa: SLF001
    hub._merge_data({"wifi": {"enabled": True}})  # noqa: SLF001
    coordinators = {group: MagicMock() for group in PollGroup}
    for group, coordinator in coordinators.items():
        hub.attach_coordinator(group, coordinator)
    mock_speedport_client.query_phonebook_contact = AsyncMock(side_effect=error)

    with (
        patch.object(hass.config_entries, "async_get_entry", return_value=entry),
        pytest.raises(HomeAssistantError) as failure,
    ):
        await hub.async_query_phonebook_contact(
            phonebook_id=0,
            contact_id="PRIVATE-CONTACT-ID",
        )

    access = hub.get("management.access")
    assert access["state"] == state
    assert access["retry_after_seconds"] == retry_after
    assert access["browser_logout_required"] is browser_logout_required
    assert hub.get("wifi.enabled") is None
    assert str(failure.value) == "The private router query could not be completed"
    assert "PRIVATE" not in repr(hub.data)
    assert "PRIVATE" not in caplog.text
    for coordinator in coordinators.values():
        coordinator.async_set_updated_data.assert_called_once()
    if isinstance(error, SpeedportInvalidCredentialsError):
        entry.async_start_reauth.assert_called_once_with(hass)
    else:
        entry.async_start_reauth.assert_not_called()
    mock_speedport_client.logout.assert_awaited_once()


@pytest.mark.asyncio
async def test_unexpected_private_query_error_is_value_free_and_releases_session(
    hass: Any,
    mock_speedport_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected failures cannot leak their text or skip owned-session cleanup."""
    _enable_private_query_capability(
        mock_speedport_client,
        "phonebook",
        "data/PhoneBook.json",
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_phonebook_entries = AsyncMock(
        side_effect=RuntimeError("PRIVATE-UNEXPECTED-DETAIL")
    )

    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_query_phonebook_entries(phonebook_id=0, prefix="")

    assert str(failure.value) == "The private router query could not be completed"
    assert hub.get("management.access.state") == "available"
    assert "PRIVATE" not in repr(hub.data)
    assert "PRIVATE" not in caplog.text
    mock_speedport_client.logout.assert_awaited_once()


def test_private_websocket_requires_admin_before_query_resolution() -> None:
    """A non-admin cannot schedule any private router query."""
    hass = MagicMock()
    connection = MagicMock()
    connection.user.is_admin = False
    msg = {
        "id": 7,
        "type": PANEL_PHONEBOOK_SEARCH_WS_TYPE,
        "entry_id": "entry-1",
        "phonebook_id": 0,
        "prefix": "A",
    }

    with pytest.raises(Unauthorized):
        websocket_phonebook_search(hass, connection, msg)

    hass.config_entries.async_get_entry.assert_not_called()


@pytest.mark.asyncio
async def test_private_websocket_returns_value_free_rate_limit_error() -> None:
    """Rate-limit errors contain only cadence and never private query fields."""
    connection = MagicMock()
    response = AsyncMock(side_effect=AdminQueryRateLimitError(1.2))()

    await _send_private_query_result(
        connection,
        {"id": 9},
        "phonebook_search",
        response,
    )

    connection.send_error.assert_called_once_with(
        9,
        "rate_limited",
        "Retry the administrator router query in 2 seconds",
    )
    connection.send_result.assert_not_called()


@pytest.mark.asyncio
async def test_private_websocket_resolves_only_loaded_speedport_entry() -> None:
    """A valid admin query stays scoped to its loaded integration entry."""
    hub = SimpleNamespace(
        async_query_phonebook_entries=AsyncMock(
            return_value={"phonebook_id": 0, "entries": []}
        )
    )
    entry = SimpleNamespace(
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = MagicMock()
    connection = MagicMock()
    msg = {
        "id": 10,
        "type": PANEL_PHONEBOOK_SEARCH_WS_TYPE,
        "entry_id": "entry-1",
        "phonebook_id": 0,
        "prefix": "A",
    }

    original_async_handler = websocket_phonebook_search.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await original_async_handler(hass, connection, msg)

    hub.async_query_phonebook_entries.assert_awaited_once_with(
        phonebook_id=0,
        prefix="A",
    )
    connection.send_result.assert_called_once_with(
        10,
        {
            "schema_version": 1,
            "query": "phonebook_search",
            "result": {"phonebook_id": 0, "entries": []},
        },
    )
    connection.send_error.assert_not_called()


@pytest.mark.asyncio
async def test_crafted_private_websocket_cannot_bypass_endpoint_proof(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """An admin WebSocket message cannot turn generic auth into capability."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_phonebook_entries = AsyncMock()
    entry = SimpleNamespace(
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    connection = MagicMock()
    msg = {
        "id": 11,
        "type": PANEL_PHONEBOOK_SEARCH_WS_TYPE,
        "entry_id": "entry-1",
        "phonebook_id": 0,
        "prefix": "A",
    }

    original_async_handler = websocket_phonebook_search.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await original_async_handler(hass, connection, msg)

    connection.send_error.assert_called_once_with(
        11,
        "query_unavailable",
        "The private router query could not be completed",
    )
    connection.send_result.assert_not_called()
    mock_speedport_client.query_phonebook_entries.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()


def test_phonebook_websocket_schema_rejects_extra_or_invalid_fields() -> None:
    """The command accepts no undeclared values and rejects Boolean book IDs."""
    schema = websocket_phonebook_search._ws_schema  # noqa: SLF001
    valid = {
        "id": 1,
        "type": PANEL_PHONEBOOK_SEARCH_WS_TYPE,
        "entry_id": "entry-1",
        "phonebook_id": 0,
        "prefix": "A",
    }
    assert schema(valid) == valid

    with pytest.raises(vol.Invalid):
        schema({**valid, "phonebook_id": True})
    with pytest.raises(vol.Invalid):
        schema({**valid, "private": "unexpected"})
