"""Administrator-only ephemeral router query WebSocket API."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any, Final, cast

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .hub import AdminQueryRateLimitError

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub

PRIVATE_QUERY_SCHEMA_VERSION: Final = 1
_PANEL_WS_TYPE: Final = f"{DOMAIN}/panel"
PANEL_IP_PBX_REFRESH_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/ip_pbx_refresh"
PANEL_PHONEBOOK_SEARCH_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/phonebook_search"
PANEL_PHONEBOOK_CONTACT_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/phonebook_contact"
_QUERY_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PHONEBOOK_PREFIX = re.compile(r"^[A-Za-z]?$")
_MAX_PHONEBOOK_ID: Final = 4


def _phonebook_id(value: object) -> int:
    """Validate the firmware's fixed set of five local phonebook indexes."""
    if type(value) is not int or not 0 <= value <= _MAX_PHONEBOOK_ID:
        raise vol.Invalid("phonebook_id must be an integer from 0 through 4")
    return value


_ENTRY_ID_SCHEMA: Final = vol.All(str, vol.Length(min=1, max=64))
_QUERY_IDENTIFIER_SCHEMA: Final = vol.All(str, vol.Match(_QUERY_IDENTIFIER))
_PHONEBOOK_PREFIX_SCHEMA: Final = vol.All(str, vol.Match(_PHONEBOOK_PREFIX))


def async_register_admin_query_commands(hass: HomeAssistant) -> None:
    """Register process-scoped private query commands exactly once."""
    websocket_api.async_register_command(hass, websocket_ip_pbx_refresh)
    websocket_api.async_register_command(hass, websocket_phonebook_search)
    websocket_api.async_register_command(hass, websocket_phonebook_contact)


@websocket_command(
    {
        vol.Required("type"): PANEL_IP_PBX_REFRESH_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("client_id"): _QUERY_IDENTIFIER_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_ip_pbx_refresh(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one IP-PBX status refresh only to a Home Assistant admin."""
    hub = _loaded_hub(hass, connection, msg)
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        "ip_pbx_refresh",
        hub.async_query_ip_pbx_client(client_id=msg["client_id"]),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_PHONEBOOK_SEARCH_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("phonebook_id"): _phonebook_id,
        vol.Required("prefix"): _PHONEBOOK_PREFIX_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_phonebook_search(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one bounded private phonebook search to an administrator."""
    hub = _loaded_hub(hass, connection, msg)
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        "phonebook_search",
        hub.async_query_phonebook_entries(
            phonebook_id=msg["phonebook_id"],
            prefix=msg["prefix"],
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_PHONEBOOK_CONTACT_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("phonebook_id"): _phonebook_id,
        vol.Required("contact_id"): _QUERY_IDENTIFIER_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_phonebook_contact(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one allowlisted private contact detail to an administrator."""
    hub = _loaded_hub(hass, connection, msg)
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        "phonebook_contact",
        hub.async_query_phonebook_contact(
            phonebook_id=msg["phonebook_id"],
            contact_id=msg["contact_id"],
        ),
    )


def _loaded_hub(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> SpeedportHub | None:
    """Resolve one loaded Speedport entry without accepting cross-domain IDs."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"],
            "entry_not_found",
            "Telekom Speedport Smart config entry not found",
        )
        return None
    if entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"],
            "entry_not_loaded",
            "Telekom Speedport Smart config entry is not loaded",
        )
        return None
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not hasattr(
        runtime_data,
        "async_query_phonebook_entries",
    ):
        connection.send_error(
            msg["id"],
            "entry_not_loaded",
            "Telekom Speedport Smart config entry is not loaded",
        )
        return None
    return cast("SpeedportHub", runtime_data)


async def _send_private_query_result(
    connection: ActiveConnection,
    msg: dict[str, Any],
    query: str,
    response: Awaitable[dict[str, Any]],
) -> None:
    """Send a private result or a value-free typed error without logging it."""
    try:
        result = await response
    except AdminQueryRateLimitError as err:
        connection.send_error(
            msg["id"],
            "rate_limited",
            "Retry the administrator router query in "
            f"{math.ceil(err.retry_after)} seconds",
        )
        return
    except HomeAssistantError:
        connection.send_error(
            msg["id"],
            "query_unavailable",
            "The private router query could not be completed",
        )
        return
    connection.send_result(
        msg["id"],
        {
            "schema_version": PRIVATE_QUERY_SCHEMA_VERSION,
            "query": query,
            "result": result,
        },
    )
