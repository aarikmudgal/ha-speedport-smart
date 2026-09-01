"""Config and options flows for Speedport Smart."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportSessionBusyError,
)
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_NORMAL_INTERVAL,
    CONF_SLOW_INTERVAL,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    CONF_WAN_INTERVAL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_NORMAL_INTERVAL,
    DEFAULT_SLOW_INTERVAL,
    DEFAULT_TR064_HTTP_PORT,
    DEFAULT_TR064_HTTPS_PORT,
    DEFAULT_WAN_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from .models import RouterInfo

_LOGGER = logging.getLogger(__name__)
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class CannotConnectError(Exception):
    """Raised when router cannot be reached or identified."""


class InvalidAuthError(Exception):
    """Raised when router rejects credentials."""


class RouterBusyError(Exception):
    """Raised when router has another active management session."""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Validated router connection metadata."""

    title: str
    unique_id: str
    router_info: RouterInfo | None


async def async_validate_input(
    hass: HomeAssistant,
    data: Mapping[str, Any],
    *,
    session: aiohttp.ClientSession | None = None,
) -> ValidationResult:
    """Validate input by discovering capabilities from router."""
    normalized = _normalize_connection_data(data)
    if not _nonempty(normalized.get(CONF_PASSWORD)):
        raise InvalidAuthError
    verify_ssl = bool(normalized[CONF_VERIFY_SSL])
    owns_session = session is None
    client_session = session or _create_isolated_session(hass, verify_ssl=verify_ssl)
    try:
        client = SpeedportClient(
            client_session,
            str(normalized[CONF_HOST]),
            password=normalized.get(CONF_PASSWORD),
            use_https=bool(normalized[CONF_USE_HTTPS]),
            verify_ssl=verify_ssl,
            tr064_http_port=DEFAULT_TR064_HTTP_PORT,
            tr064_https_port=DEFAULT_TR064_HTTPS_PORT,
            owns_session=owns_session,
        )
    except Exception:
        if owns_session:
            client_session.detach()
        raise
    try:
        await client.setup()
        info = client.router_info
    except SpeedportInvalidCredentialsError as err:
        raise InvalidAuthError from err
    except SpeedportSessionBusyError as err:
        raise RouterBusyError from err
    except (
        SpeedportAuthenticationError,
        SpeedportConnectionError,
        SpeedportError,
    ) as err:
        raise CannotConnectError from err
    finally:
        await client.close()

    serial = _nonempty(getattr(info, "serial_number", None))
    model = _nonempty(getattr(info, "model", None))
    host = str(normalized[CONF_HOST])
    return ValidationResult(
        title=model or f"Telekom Speedport Smart ({host})",
        unique_id=(serial or host).casefold(),
        router_info=info,
    )


def _create_isolated_session(
    hass: HomeAssistant, *, verify_ssl: bool
) -> aiohttp.ClientSession:
    """Create a private cookie jar over Home Assistant's shared connector."""
    return async_create_clientsession(
        hass,
        verify_ssl=verify_ssl,
        auto_cleanup=False,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
        connector_owner=False,
    )


class SpeedportSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Speedport Smart configuration."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return options flow."""
        del config_entry
        return SpeedportSmartOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a router from UI."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=_connection_schema({})
            )

        errors, result = await self._async_try_validate(user_input)
        if result is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_connection_schema(user_input),
                errors=errors,
            )

        await self.async_set_unique_id(result.unique_id)
        self._abort_if_unique_id_configured(
            updates=_normalize_connection_data(user_input)
        )
        return self.async_create_entry(
            title=result.title,
            data=_normalize_connection_data(user_input),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Begin credential refresh."""
        del entry_data
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate replacement credentials and reload entry."""
        entry = self._get_reauth_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR}
                ),
            )

        updated = dict(entry.data)
        updated[CONF_PASSWORD] = user_input[CONF_PASSWORD]
        errors, result = await self._async_try_validate(updated)
        if result is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_PASSWORD,
                            description={"suggested_value": user_input[CONF_PASSWORD]},
                        ): _PASSWORD_SELECTOR
                    }
                ),
                errors=errors,
            )

        await self.async_set_unique_id(result.unique_id)
        self._abort_if_unique_id_mismatch()
        return self.async_update_reload_and_abort(entry, data_updates=updated)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change router connection settings."""
        entry = self._get_reconfigure_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_connection_schema(entry.data),
            )

        errors, result = await self._async_try_validate(user_input)
        if result is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_connection_schema(user_input),
                errors=errors,
            )

        await self.async_set_unique_id(result.unique_id)
        self._abort_if_unique_id_mismatch()
        return self.async_update_reload_and_abort(
            entry,
            title=result.title,
            data_updates=_normalize_connection_data(user_input),
        )

    async def _async_try_validate(
        self, user_input: Mapping[str, Any]
    ) -> tuple[dict[str, str], ValidationResult | None]:
        """Map validation exceptions to config-flow errors."""
        try:
            return {}, await async_validate_input(self.hass, user_input)
        except InvalidAuthError:
            return {"base": "invalid_auth"}, None
        except RouterBusyError:
            return {"base": "router_busy"}, None
        except CannotConnectError:
            return {"base": "cannot_connect"}, None
        except Exception:
            _LOGGER.exception("Unexpected exception validating Speedport router")
            return {"base": "unknown"}, None


class SpeedportSmartOptionsFlow(OptionsFlow):
    """Configure polling and router control exposure."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_CONTROLS,
                        default=bool(current.get(CONF_ENABLE_CONTROLS, True)),
                    ): cv.boolean,
                    vol.Required(
                        CONF_FAST_INTERVAL,
                        default=int(
                            current.get(
                                CONF_FAST_INTERVAL,
                                DEFAULT_FAST_INTERVAL.total_seconds(),
                            )
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                    vol.Required(
                        CONF_WAN_INTERVAL,
                        default=int(
                            current.get(CONF_WAN_INTERVAL, DEFAULT_WAN_INTERVAL)
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                    vol.Required(
                        CONF_NORMAL_INTERVAL,
                        default=int(
                            current.get(
                                CONF_NORMAL_INTERVAL,
                                DEFAULT_NORMAL_INTERVAL.total_seconds(),
                            )
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
                    vol.Required(
                        CONF_SLOW_INTERVAL,
                        default=int(
                            current.get(
                                CONF_SLOW_INTERVAL,
                                DEFAULT_SLOW_INTERVAL.total_seconds(),
                            )
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                }
            ),
        )


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Build connection schema with suggested values for secrets."""
    password = defaults.get(CONF_PASSWORD)
    password_marker: vol.Marker
    if password:
        password_marker = vol.Optional(
            CONF_PASSWORD, description={"suggested_value": password}
        )
    else:
        password_marker = vol.Required(CONF_PASSWORD)
    return vol.Schema(
        {
            vol.Required(
                CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)
            ): cv.string,
            password_marker: _PASSWORD_SELECTOR,
            vol.Required(
                CONF_USE_HTTPS, default=bool(defaults.get(CONF_USE_HTTPS, False))
            ): cv.boolean,
            vol.Required(
                CONF_VERIFY_SSL,
                default=bool(defaults.get(CONF_VERIFY_SSL, False)),
            ): cv.boolean,
        }
    )


def _normalize_connection_data(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize persisted connection data."""
    host = str(data.get(CONF_HOST, DEFAULT_HOST)).strip()
    normalized: dict[str, Any] = {
        CONF_HOST: host.rstrip("."),
        CONF_USE_HTTPS: bool(data.get(CONF_USE_HTTPS, False)),
        CONF_VERIFY_SSL: bool(data.get(CONF_VERIFY_SSL, False)),
    }
    password = _nonempty(data.get(CONF_PASSWORD))
    if password is not None:
        normalized[CONF_PASSWORD] = password
    return normalized


def _nonempty(value: Any) -> str | None:
    """Return stripped non-empty string."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
