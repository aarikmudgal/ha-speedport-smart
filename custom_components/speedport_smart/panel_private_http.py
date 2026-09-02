"""
Bounded private panel POST transport, outside Home Assistant WebSocket logs.

The reviewed command schemas and dispatch functions are reused, but no real
WebSocket connection, background response task or outgoing frame queue is used.
Existing settings approvals retain their user/session/entry binding and one-use
semantics. Mixed-version clients receive an inert upgrade error on WebSocket.
"""

# Validation deliberately raises inside the same non-logging private boundary.
# ruff: noqa: TRY301

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import TYPE_CHECKING, Any, Final

from aiohttp import web
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID, KEY_HASS_USER
from homeassistant.components.http.decorators import require_admin
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.http import HomeAssistantView

from .const import DOMAIN
from .panel_queries import private_panel_command_handlers
from .private_authorization import private_authorization

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_RUNTIME: Final = f"{DOMAIN}_private_panel_view"
_REQUEST_LIMIT: Final = 256 * 1024
_RESPONSE_LIMIT: Final = 32 * 1024 * 1024
_READ_TIMEOUT: Final = 30
_OPERATION_TIMEOUT: Final = 120
_MAX_DEPTH: Final = 32
_IDENTITY_LIMIT: Final = 128
_ENTRY: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PRIVATE_HEADERS: Final = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_ERROR_CODES: Final = frozenset(
    {
        "action_busy",
        "action_failed",
        "action_outcome_unknown",
        "action_rate_limited",
        "action_rejected",
        "action_unavailable",
        "action_verification_failed",
        "administrator_required",
        "confirmation_required",
        "entry_not_found",
        "entry_not_loaded",
        "invalid_input",
        "invalid_settings",
        "invalid_settings_target",
        "management_unavailable",
        "private_operation_failed",
        "private_transport_required",
        "query_unavailable",
        "rate_limited",
        "setting_unavailable",
        "settings_failed",
        "settings_busy",
        "settings_capacity_reached",
        "settings_inventory_unavailable",
        "settings_prerequisites_unavailable",
        "settings_target_required",
        "settings_target_unavailable",
        "settings_unavailable",
        "stale_settings",
        "too_many_editors",
        "invalid_password_change",
        "password_repeat_mismatch",
        "password_unchanged",
        "password_change_preflight_failed",
        "stale_password_change",
        "password_change_rejected",
        "password_change_outcome_unknown",
        "password_verification_failed",
        "phonebook_empty",
        "phonebook_full",
        "phonebook_linked",
    }
)
_ERROR_MESSAGE: Final = (
    "Private router operation could not be completed. Inspect the router before "
    "retrying a change; nothing will be repeated automatically."
)


class _PrivateRequestError(ValueError):
    """Carry no request content, response content, path or private identifiers."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _PrivateRequestError
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise _PrivateRequestError


def _validate_depth(value: Any, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise _PrivateRequestError
    if isinstance(value, dict):
        for child in value.values():
            _validate_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_depth(child, depth + 1)


def _clear(value: Any) -> None:
    """Release owned request/response containers without claiming string zeroization."""
    if isinstance(value, dict):
        for child in value.values():
            _clear(child)
        value.clear()
    elif isinstance(value, list):
        for child in value:
            _clear(child)
        value.clear()


async def _body(request: web.Request) -> dict[str, Any]:
    if (
        request.content_type != "application/json"
        or request.headers.get("Content-Encoding")
        or request.query_string
        or (
            request.content_length is not None
            and request.content_length > _REQUEST_LIMIT
        )
    ):
        raise _PrivateRequestError
    data = bytearray()
    try:
        async with asyncio.timeout(_READ_TIMEOUT):
            while chunk := await request.content.read(_REQUEST_LIMIT + 1):
                if len(data) + len(chunk) > _REQUEST_LIMIT:
                    raise _PrivateRequestError
                data.extend(chunk)
        value = json.loads(data, object_pairs_hook=_object, parse_constant=_constant)
        if type(value) is not dict or "id" in value:
            raise _PrivateRequestError
        _validate_depth(value)
    except (ValueError, UnicodeError, RecursionError, TimeoutError):
        raise _PrivateRequestError from None
    else:
        return value
    finally:
        data.clear()


class _PrivateResult:
    """Minimal in-memory dispatcher sink; never a HA WebSocket connection."""

    def __init__(self, user: Any, refresh_token_id: str) -> None:
        self.user = user
        self.refresh_token_id = refresh_token_id
        self.envelope: dict[str, Any] | None = None

    def send_result(self, _message_id: int, result: Any) -> None:
        if self.envelope is not None:
            raise _PrivateRequestError
        self.envelope = {"result": result}

    def send_error(self, _message_id: int, code: str, _message: str) -> None:
        if self.envelope is not None:
            raise _PrivateRequestError
        self.envelope = {
            "error": {
                "code": code if code in _ERROR_CODES else "private_operation_failed",
                "message": _ERROR_MESSAGE,
            }
        }


def _handlers() -> dict[str, Any]:
    # panel imports registration from this module, so resolve its cached read
    # dispatcher only after module initialization is complete.
    from .panel import websocket_panel_admin_read  # noqa: PLC0415

    cached_read: Any = websocket_panel_admin_read
    return {
        **private_panel_command_handlers(),
        cached_read._ws_command: cached_read,  # noqa: SLF001
    }


class PrivatePanelView(HomeAssistantView):
    """Authenticate one bounded command and return its result without shared caches."""

    url = f"/api/{DOMAIN}/private/{{entry_id}}"
    name = f"api:{DOMAIN}:private"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Register no session state; existing hub approvals remain authoritative."""
        self.hass = hass

    def _identity(self, request: web.Request, entry_id: str) -> tuple[Any, str, Any]:
        if type(entry_id) is not str or _ENTRY.fullmatch(entry_id) is None:
            raise _PrivateRequestError
        user = request.get(KEY_HASS_USER)
        refresh_id = request.get(KEY_HASS_REFRESH_TOKEN_ID)
        user_id = getattr(user, "id", None)
        if (
            type(user_id) is not str
            or not 0 < len(user_id) <= _IDENTITY_LIMIT
            or type(refresh_id) is not str
            or not 0 < len(refresh_id) <= _IDENTITY_LIMIT
            or getattr(user, "is_admin", False) is not True
            or getattr(user, "is_active", False) is not True
        ):
            raise _PrivateRequestError
        token = self.hass.auth.async_get_refresh_token(refresh_id)
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if (
            token is None
            or token.user.id != user_id
            or not token.user.is_active
            or not token.user.is_admin
            or entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
            or getattr(entry, "runtime_data", None) is None
            or getattr(entry.runtime_data, "_closed", False) is True
        ):
            raise _PrivateRequestError
        return user, refresh_id, entry.runtime_data

    def _response(self, envelope: dict[str, Any], *, status: int = 200) -> web.Response:
        data = json.dumps(
            envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(data) > _RESPONSE_LIMIT:
            raise _PrivateRequestError
        return web.Response(
            body=data,
            status=status,
            content_type="application/json",
            headers=_PRIVATE_HEADERS,
        )

    @require_admin
    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        """Dispatch once; validation/errors never echo bodies or exception values."""
        body: dict[str, Any] = {}
        validated: dict[str, Any] = {}
        sink: _PrivateResult | None = None
        try:
            user, refresh_id, hub = self._identity(request, entry_id)
            requester = (user.id, refresh_id)

            def authorize() -> None:
                current_user, current_refresh, current_hub = self._identity(
                    request, entry_id
                )
                if (
                    current_user.id,
                    current_refresh,
                ) != requester or current_hub is not hub:
                    raise _PrivateRequestError

            body = await _body(request)
            if body.get("entry_id") != entry_id or type(body.get("type")) is not str:
                raise _PrivateRequestError
            handler = _handlers().get(body["type"])
            if handler is None:
                raise _PrivateRequestError
            # The integer exists only for the shared in-memory result sink. It
            # is forbidden on HTTP input and never becomes a WebSocket frame.
            validated = handler._ws_schema({**body, "id": 1})  # noqa: SLF001
            current_user, current_refresh, current_hub = self._identity(
                request, entry_id
            )
            if (
                current_user.id != user.id
                or current_refresh != refresh_id
                or current_hub is not hub
            ):
                raise _PrivateRequestError
            sink = _PrivateResult(user, refresh_id)
            # Unwrap HA scheduling/admin decorators only here: HTTP has already
            # enforced a live administrator and exact loaded-entry binding.
            dispatch = inspect.unwrap(handler)
            with private_authorization(authorize):
                async with asyncio.timeout(_OPERATION_TIMEOUT):
                    outcome = dispatch(self.hass, sink, validated)
                    if inspect.isawaitable(outcome):
                        await outcome
            current_user, current_refresh, current_hub = self._identity(
                request, entry_id
            )
            if (
                current_user.id != user.id
                or current_refresh != refresh_id
                or current_hub is not hub
            ):
                raise _PrivateRequestError
            if sink.envelope is None:
                raise _PrivateRequestError
            return self._response(
                sink.envelope, status=400 if "error" in sink.envelope else 200
            )
        except Exception:  # noqa: BLE001 -- never log private values.
            return self._response(
                {
                    "error": {
                        "code": "private_operation_failed",
                        "message": _ERROR_MESSAGE,
                    }
                },
                status=400,
            )
        finally:
            _clear(body)
            _clear(validated)
            if sink is not None and sink.envelope is not None:
                # Results can contain borrowed cached projections. Release our
                # reference without changing the hub's underlying read state.
                sink.envelope.clear()


def async_register_private_panel_view(hass: HomeAssistant) -> None:
    """Register the process-owned route once; no private payload is retained."""
    if hass.data.get(_RUNTIME):
        return
    hass.http.register_view(PrivatePanelView(hass))
    hass.data[_RUNTIME] = True
