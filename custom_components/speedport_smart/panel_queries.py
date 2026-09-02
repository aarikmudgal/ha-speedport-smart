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

from .admin_actions import get_admin_action_contract
from .const import DOMAIN
from .hub import (
    AdminActionBusyError,
    AdminActionConfirmationError,
    AdminActionOutcomeUnknownError,
    AdminActionRateLimitError,
    AdminActionRejectedError,
    AdminActionUnavailableError,
    AdminActionVerificationError,
    AdminQueryRateLimitError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub

PRIVATE_QUERY_SCHEMA_VERSION: Final = 1
_PANEL_WS_TYPE: Final = f"{DOMAIN}/panel"
PANEL_IP_PBX_REFRESH_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/ip_pbx_refresh"
PANEL_PHONEBOOK_SEARCH_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/phonebook_search"
PANEL_PHONEBOOK_CONTACT_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/phonebook_contact"
PANEL_DECT_HANDSET_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_handset_targets"
)
PANEL_VOIP_LINE_TARGETS_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/action/voip_line_targets"
PANEL_DECT_HANDSET_ENROLL_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_handset_enroll"
)
PANEL_DECT_REPEATER_ENROLL_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_repeater_enroll"
)
PANEL_DECT_HANDSET_SET_PAGING_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_handset_set_paging"
)
PANEL_VOIP_LINE_SET_ACTIVE_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/voip_line_set_active"
)
PANEL_DECT_HANDSET_DISCONNECT_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_handset_disconnect_targets"
)
PANEL_DECT_REPEATER_DISCONNECT_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_repeater_disconnect_targets"
)
PANEL_VOIP_PROVIDER_DELETE_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/voip_provider_delete_targets"
)
PANEL_VOIP_LINE_DELETE_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/voip_line_delete_targets"
)
PANEL_IP_PBX_CLIENT_DELETE_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/ip_pbx_client_delete_targets"
)
PANEL_PHONEBOOK_ENTRY_DELETE_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/phonebook_entry_delete_targets"
)
PANEL_NAS_SHARE_DELETE_TARGETS_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/nas_share_delete_targets"
)
PANEL_DECT_HANDSET_DISCONNECT_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_handset_disconnect"
)
PANEL_DECT_REPEATER_DISCONNECT_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/dect_repeater_disconnect"
)
PANEL_VOIP_PROVIDER_DELETE_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/voip_provider_delete"
)
PANEL_VOIP_LINE_DELETE_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/action/voip_line_delete"
PANEL_IP_PBX_CLIENT_DELETE_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/ip_pbx_client_delete"
)
PANEL_PHONEBOOK_ENTRY_DELETE_WS_TYPE: Final = (
    f"{_PANEL_WS_TYPE}/action/phonebook_entry_delete"
)
PANEL_NAS_SHARE_DELETE_WS_TYPE: Final = f"{_PANEL_WS_TYPE}/action/nas_share_delete"
_QUERY_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ACTION_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_PHONEBOOK_PREFIX = re.compile(r"^[A-Za-z]?$")
_MAX_PHONEBOOK_ID: Final = 4


def _phonebook_id(value: object) -> int:
    """Validate the firmware's fixed set of five local phonebook indexes."""
    if type(value) is not int or not 0 <= value <= _MAX_PHONEBOOK_ID:
        raise vol.Invalid("phonebook_id must be an integer from 0 through 4")
    return value


_ENTRY_ID_SCHEMA: Final = vol.All(str, vol.Length(min=1, max=64))
_QUERY_IDENTIFIER_SCHEMA: Final = vol.All(str, vol.Match(_QUERY_IDENTIFIER))
_ACTION_TOKEN_SCHEMA: Final = vol.All(str, vol.Match(_ACTION_TOKEN))
_PHONEBOOK_PREFIX_SCHEMA: Final = vol.All(str, vol.Match(_PHONEBOOK_PREFIX))


def _strict_boolean(value: object) -> bool:
    """Accept Boolean JSON values without integer truthiness widening."""
    if type(value) is not bool:
        raise vol.Invalid("value must be a boolean")
    return value


def _affirmed(value: object) -> bool:
    """Require an explicit true assertion."""
    if type(value) is not bool or not value:
        raise vol.Invalid("explicit confirmation is required")
    return True


_STRICT_BOOLEAN_SCHEMA: Final = _strict_boolean
_AFFIRMED_SCHEMA: Final = _affirmed


def _admin_action_requester(connection: ActiveConnection) -> tuple[str, str]:
    """Return the server-owned HA user and login-session identity."""
    user_id = getattr(connection.user, "id", None)
    session_id = getattr(connection, "refresh_token_id", None)
    if not isinstance(user_id, str) or not isinstance(session_id, str):
        return ("", "")
    return (user_id, session_id)


def _typed_confirmation(action: str) -> vol.All:
    """Return an exact schema bound to one immutable action phrase."""
    contract = get_admin_action_contract(action)
    phrase = contract.typed_confirmation if contract is not None else None
    if phrase is None:
        raise ValueError("Typed administrator action contract is missing")
    return vol.All(str, vol.In({phrase}))


def async_register_admin_query_commands(hass: HomeAssistant) -> None:
    """Register process-scoped private query commands exactly once."""
    websocket_api.async_register_command(hass, websocket_ip_pbx_refresh)
    websocket_api.async_register_command(hass, websocket_phonebook_search)
    websocket_api.async_register_command(hass, websocket_phonebook_contact)
    websocket_api.async_register_command(hass, websocket_dect_handset_targets)
    websocket_api.async_register_command(hass, websocket_voip_line_targets)
    websocket_api.async_register_command(hass, websocket_dect_handset_enroll)
    websocket_api.async_register_command(hass, websocket_dect_repeater_enroll)
    websocket_api.async_register_command(hass, websocket_dect_handset_set_paging)
    websocket_api.async_register_command(hass, websocket_voip_line_set_active)
    websocket_api.async_register_command(
        hass, websocket_dect_handset_disconnect_targets
    )
    websocket_api.async_register_command(
        hass, websocket_dect_repeater_disconnect_targets
    )
    websocket_api.async_register_command(hass, websocket_voip_provider_delete_targets)
    websocket_api.async_register_command(hass, websocket_voip_line_delete_targets)
    websocket_api.async_register_command(hass, websocket_ip_pbx_client_delete_targets)
    websocket_api.async_register_command(hass, websocket_phonebook_entry_delete_targets)
    websocket_api.async_register_command(hass, websocket_nas_share_delete_targets)
    websocket_api.async_register_command(hass, websocket_dect_handset_disconnect)
    websocket_api.async_register_command(hass, websocket_dect_repeater_disconnect)
    websocket_api.async_register_command(hass, websocket_voip_provider_delete)
    websocket_api.async_register_command(hass, websocket_voip_line_delete)
    websocket_api.async_register_command(hass, websocket_ip_pbx_client_delete)
    websocket_api.async_register_command(hass, websocket_phonebook_entry_delete)
    websocket_api.async_register_command(hass, websocket_nas_share_delete)


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


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_HANDSET_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_handset_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh exact handset action identities to an administrator."""
    hub = _loaded_hub(
        hass,
        connection,
        msg,
        required_method="async_query_dect_handset_targets",
    )
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        "dect_handset_targets",
        hub.async_query_dect_handset_targets(
            requester=_admin_action_requester(connection)
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_LINE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_line_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh exact VoIP line action identities to an administrator."""
    hub = _loaded_hub(
        hass,
        connection,
        msg,
        required_method="async_query_voip_line_targets",
    )
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        "voip_line_targets",
        hub.async_query_voip_line_targets(
            requester=_admin_action_requester(connection)
        ),
    )


async def _send_action_target_query(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    *,
    query: str,
    required_method: str,
    response: Callable[[SpeedportHub, tuple[str, str]], Awaitable[dict[str, Any]]],
) -> None:
    """Resolve one loaded hub and send a private action-target response."""
    hub = _loaded_hub(
        hass,
        connection,
        msg,
        required_method=required_method,
    )
    if hub is None:
        return
    await _send_private_query_result(
        connection,
        msg,
        query,
        response(hub, _admin_action_requester(connection)),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_HANDSET_DISCONNECT_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_handset_disconnect_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh DECT handset deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="dect_handset_disconnect_targets",
        required_method="async_query_dect_handset_disconnect_targets",
        response=lambda hub, requester: hub.async_query_dect_handset_disconnect_targets(
            requester=requester
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_REPEATER_DISCONNECT_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_repeater_disconnect_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh DECT repeater deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="dect_repeater_disconnect_targets",
        required_method="async_query_dect_repeater_disconnect_targets",
        response=lambda hub, requester: (
            hub.async_query_dect_repeater_disconnect_targets(requester=requester)
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_PROVIDER_DELETE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_provider_delete_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh VoIP provider deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="voip_provider_delete_targets",
        required_method="async_query_voip_provider_delete_targets",
        response=lambda hub, requester: hub.async_query_voip_provider_delete_targets(
            requester=requester
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_LINE_DELETE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_line_delete_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh VoIP number deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="voip_line_delete_targets",
        required_method="async_query_voip_line_delete_targets",
        response=lambda hub, requester: hub.async_query_voip_line_delete_targets(
            requester=requester
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_IP_PBX_CLIENT_DELETE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_ip_pbx_client_delete_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh IP-PBX client deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="ip_pbx_client_delete_targets",
        required_method="async_query_ip_pbx_client_delete_targets",
        response=lambda hub, requester: hub.async_query_ip_pbx_client_delete_targets(
            requester=requester
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_PHONEBOOK_ENTRY_DELETE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("phonebook_id"): _phonebook_id,
    }
)
@require_admin
@async_response
async def websocket_phonebook_entry_delete_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh contact deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="phonebook_entry_delete_targets",
        required_method="async_query_phonebook_entry_delete_targets",
        response=lambda hub, requester: hub.async_query_phonebook_entry_delete_targets(
            phonebook_id=msg["phonebook_id"],
            requester=requester,
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_NAS_SHARE_DELETE_TARGETS_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_nas_share_delete_targets(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return fresh NAS-share deletion targets to an administrator."""
    await _send_action_target_query(
        hass,
        connection,
        msg,
        query="nas_share_delete_targets",
        required_method="async_query_nas_share_delete_targets",
        response=lambda hub, requester: hub.async_query_nas_share_delete_targets(
            requester=requester
        ),
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_HANDSET_ENROLL_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_handset_enroll(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Start one confirmed DECT handset enrollment lifecycle."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="dect_handset_enroll",
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_REPEATER_ENROLL_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("pin_is_default"): _AFFIRMED_SCHEMA,
        vol.Required("full_power_enabled"): _AFFIRMED_SCHEMA,
        vol.Required("full_eco_disabled"): _AFFIRMED_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_repeater_enroll(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Start one confirmed DECT repeater enrollment lifecycle."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="dect_repeater_enroll",
        pin_is_default=msg["pin_is_default"],
        full_power_enabled=msg["full_power_enabled"],
        full_eco_disabled=msg["full_eco_disabled"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_HANDSET_SET_PAGING_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
        vol.Required("enabled"): _STRICT_BOOLEAN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_handset_set_paging(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set paging for one exact DECT handset action target."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="dect_handset_set_paging",
        target_token=msg["target_token"],
        enabled=msg["enabled"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_LINE_SET_ACTIVE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
        vol.Required("active"): _STRICT_BOOLEAN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_line_set_active(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set one exact VoIP line active state."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="voip_line_set_active",
        target_token=msg["target_token"],
        active=msg["active"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_HANDSET_DISCONNECT_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation(
            "dect_handset_disconnect"
        ),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_handset_disconnect(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Disconnect one exact DECT handset after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="dect_handset_disconnect",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_DECT_REPEATER_DISCONNECT_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation(
            "dect_repeater_disconnect"
        ),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_dect_repeater_disconnect(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Disconnect one exact DECT repeater after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="dect_repeater_disconnect",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_PROVIDER_DELETE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation("voip_provider_delete"),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_provider_delete(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one exact VoIP provider after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="voip_provider_delete",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_VOIP_LINE_DELETE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation("voip_line_delete"),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_voip_line_delete(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one exact VoIP number after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="voip_line_delete",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_IP_PBX_CLIENT_DELETE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation("ip_pbx_client_delete"),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_ip_pbx_client_delete(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one exact IP-PBX client after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="ip_pbx_client_delete",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_PHONEBOOK_ENTRY_DELETE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation(
            "phonebook_entry_delete"
        ),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_phonebook_entry_delete(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one exact phonebook contact after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="phonebook_entry_delete",
        target_token=msg["target_token"],
    )


@websocket_command(
    {
        vol.Required("type"): PANEL_NAS_SHARE_DELETE_WS_TYPE,
        vol.Required("entry_id"): _ENTRY_ID_SCHEMA,
        vol.Required("confirmed"): _AFFIRMED_SCHEMA,
        vol.Required("confirmation_text"): _typed_confirmation("nas_share_delete"),
        vol.Required("target_token"): _ACTION_TOKEN_SCHEMA,
    }
)
@require_admin
@async_response
async def websocket_nas_share_delete(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one exact NAS share after typed confirmation."""
    await _dispatch_admin_action(
        hass,
        connection,
        msg,
        action="nas_share_delete",
        target_token=msg["target_token"],
    )


def _loaded_hub(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    *,
    required_method: str = "async_query_phonebook_entries",
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
    if runtime_data is None or not callable(
        getattr(runtime_data, required_method, None)
    ):
        connection.send_error(
            msg["id"],
            "entry_not_loaded",
            "Telekom Speedport Smart config entry is not loaded",
        )
        return None
    return cast("SpeedportHub", runtime_data)


async def _dispatch_admin_action(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
    *,
    action: str,
    **parameters: Any,
) -> None:
    """Resolve and execute one exact administrator action."""
    hub = _loaded_hub(
        hass,
        connection,
        msg,
        required_method="async_execute_admin_action",
    )
    if hub is None:
        return
    await _send_admin_action_result(
        connection,
        msg,
        action,
        hub.async_execute_admin_action(
            action,
            confirmed=msg["confirmed"],
            confirmation_text=msg.get("confirmation_text"),
            requester=_admin_action_requester(connection),
            **parameters,
        ),
    )


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


async def _send_admin_action_result(
    connection: ActiveConnection,
    msg: dict[str, Any],
    action: str,
    response: Awaitable[dict[str, Any]],
) -> None:
    """Send one value-free action result or one fixed typed error."""
    try:
        result = await response
    except AdminActionRateLimitError as err:
        connection.send_error(
            msg["id"],
            "action_rate_limited",
            "Retry the administrator router action in "
            f"{math.ceil(err.retry_after)} seconds",
        )
        return
    except AdminActionConfirmationError:
        connection.send_error(
            msg["id"],
            "confirmation_required",
            "Administrator confirmation is required for this router action",
        )
        return
    except AdminActionBusyError:
        connection.send_error(
            msg["id"],
            "action_busy",
            "A DECT enrollment lifecycle is already active",
        )
        return
    except AdminActionRejectedError:
        connection.send_error(
            msg["id"],
            "action_rejected",
            "The router explicitly rejected the administrator action",
        )
        return
    except AdminActionUnavailableError:
        connection.send_error(
            msg["id"],
            "action_unavailable",
            "The administrator router action is not currently available",
        )
        return
    except AdminActionOutcomeUnknownError:
        connection.send_error(
            msg["id"],
            "action_outcome_unknown",
            "The router response did not prove the action outcome; "
            "check its state before retrying",
        )
        return
    except AdminActionVerificationError:
        connection.send_error(
            msg["id"],
            "action_verification_failed",
            "The router action result could not be independently verified",
        )
        return
    except HomeAssistantError:
        connection.send_error(
            msg["id"],
            "action_failed",
            "The administrator router action could not be completed",
        )
        return
    connection.send_result(
        msg["id"],
        {
            "schema_version": PRIVATE_QUERY_SCHEMA_VERSION,
            "action": action,
            "result": result,
        },
    )
