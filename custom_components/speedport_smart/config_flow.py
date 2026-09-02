"""Config and options flows for Speedport Smart."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_DHCP,
    SOURCE_SSDP,
    ConfigFlow,
    OptionsFlow,
)
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

    from homeassistant.components.dhcp import DhcpServiceInfo
    from homeassistant.components.ssdp import SsdpServiceInfo
    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant

    from .models import RouterInfo

_LOGGER = logging.getLogger(__name__)
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
_SUPPORTED_DISCOVERY_MODELS: Final = frozenset({"speedport smart 4r typ a"})


class CannotConnectError(Exception):
    """Raised when router cannot be reached or identified."""


class InvalidAuthError(Exception):
    """Raised when router rejects credentials."""


class RouterBusyError(Exception):
    """Raised when router has another active management session."""


class UnsupportedDiscoveryError(Exception):
    """Raised when public identity is not an allowlisted Speedport Smart."""


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


async def async_probe_discovered_router(
    hass: HomeAssistant,
    host: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> ValidationResult:
    """Read public router identity without credentials or capability probes."""
    owns_session = session is None
    client_session = session or _create_isolated_session(hass, verify_ssl=False)
    try:
        client = SpeedportClient(
            client_session,
            host,
            password=None,
            use_https=False,
            verify_ssl=False,
            tr064_http_port=DEFAULT_TR064_HTTP_PORT,
            tr064_https_port=DEFAULT_TR064_HTTPS_PORT,
            owns_session=owns_session,
        )
    except Exception:
        if owns_session:
            client_session.detach()
        raise
    try:
        status = await client.get_status()
        info = status.info
    except (SpeedportConnectionError, SpeedportError) as err:
        raise CannotConnectError from err
    finally:
        await client.close()

    if not _is_supported_discovered_router(info):
        raise UnsupportedDiscoveryError
    serial = _router_serial(info)
    if serial is None:
        raise UnsupportedDiscoveryError
    return ValidationResult(
        title=" ".join(info.model.split()),
        unique_id=serial.casefold(),
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
    _discovered_host: str | None = None
    _discovered_identity: ValidationResult | None = None

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

        self._async_abort_discovery_flows(result.unique_id)
        await self.async_set_unique_id(result.unique_id)
        self._abort_if_unique_id_configured(
            updates=_normalize_connection_data(user_input)
        )
        return self.async_create_entry(
            title=result.title,
            data=_normalize_connection_data(user_input),
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a broad DHCP hint without trusting its advertised identity."""
        host = _normalize_discovered_ipv4(discovery_info.ip)
        if host is None:
            return self.async_abort(reason="invalid_discovery_info")
        return await self._async_begin_discovery(host)

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a broad SSDP hint without trusting its advertised identity."""
        location = _nonempty(discovery_info.ssdp_location)
        if location is None:
            return self.async_abort(reason="invalid_discovery_info")
        try:
            parsed = urlsplit(location)
            parsed_host = parsed.hostname
        except ValueError:
            return self.async_abort(reason="invalid_discovery_info")
        host = _normalize_discovered_ipv4(parsed_host)
        if host is None or parsed.scheme.casefold() not in {"http", "https"}:
            return self.async_abort(reason="invalid_discovery_info")
        return await self._async_begin_discovery(host)

    async def _async_begin_discovery(self, host: str) -> ConfigFlowResult:
        """Start user confirmation for one normalized discovery candidate."""
        self._discovered_host = host
        if self._configured_host_matches(host):
            return self.async_abort(reason="already_configured")

        if self.hass.config_entries.flow.async_has_matching_flow(self):
            return self.async_abort(reason="already_in_progress")

        try:
            identity = await async_probe_discovered_router(self.hass, host)
        except UnsupportedDiscoveryError:
            return self.async_abort(reason="not_supported")
        except CannotConnectError:
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("Unexpected exception probing discovered router")
            return self.async_abort(reason="unknown")
        if not _is_supported_discovered_router(identity.router_info):
            return self.async_abort(reason="not_supported")

        self._discovered_identity = identity
        await self.async_set_unique_id(identity.unique_id)
        self._abort_if_unique_id_configured()

        self.context["title_placeholders"] = {"name": host}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and confirm a discovered Speedport Smart router."""
        host = self._discovered_host
        if host is None:
            return self.async_abort(reason="invalid_discovery_info")

        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=_discovery_schema({}),
                description_placeholders={CONF_HOST: host},
            )

        connection_data = {**user_input, CONF_HOST: host}
        errors, result = await self._async_try_validate(connection_data)
        if result is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=_discovery_schema(user_input),
                description_placeholders={CONF_HOST: host},
                errors=errors,
            )
        if not _same_discovered_router(self._discovered_identity, result):
            return self.async_abort(reason="not_supported")

        normalized = _normalize_connection_data(connection_data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=result.title, data=normalized)

    def is_matching(self, other_flow: SpeedportSmartConfigFlow) -> bool:
        """Match concurrent DHCP and SSDP hints only by exact normalized host."""
        return (
            self._discovered_host is not None
            and self._discovered_host == other_flow._discovered_host
        )

    def _configured_host_matches(self, host: str) -> bool:
        """Return whether an existing entry has this exact normalized IPv4 host."""
        return any(
            _normalize_discovered_ipv4(entry.data.get(CONF_HOST)) == host
            for entry in self._async_current_entries(include_ignore=False)
        )

    def _async_abort_discovery_flows(self, unique_id: str) -> None:
        """Give a validated manual flow priority over pending discoveries."""
        for progress in self._async_in_progress(
            include_uninitialized=True,
            match_context={"unique_id": unique_id},
        ):
            if progress["context"].get("source") in {SOURCE_DHCP, SOURCE_SSDP}:
                self.hass.config_entries.flow.async_abort(progress["flow_id"])

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


def _discovery_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Build confirmation schema for a discovered host."""
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
    host = _normalize_connection_host(data.get(CONF_HOST, DEFAULT_HOST))
    normalized: dict[str, Any] = {
        CONF_HOST: host,
        CONF_USE_HTTPS: bool(data.get(CONF_USE_HTTPS, False)),
        CONF_VERIFY_SSL: bool(data.get(CONF_VERIFY_SSL, False)),
    }
    password = _nonempty(data.get(CONF_PASSWORD))
    if password is not None:
        normalized[CONF_PASSWORD] = password
    return normalized


def _normalize_connection_host(value: Any) -> str:
    """Normalize an IP literal or DNS host for storage and exact comparison."""
    host = str(value).strip().rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host.casefold()


def _normalize_discovered_ipv4(value: Any) -> str | None:
    """Return canonical usable private-unicast IPv4 text or reject it."""
    if value is None:
        return None
    try:
        address = ipaddress.ip_address(str(value).strip().rstrip("."))
    except ValueError:
        return None
    if not isinstance(address, ipaddress.IPv4Address):
        return None
    if (
        not address.is_private
        or address.is_global
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return None
    return str(address)


def _is_supported_discovered_router(info: RouterInfo | None) -> bool:
    """Accept only a proven Speedport Smart model with stable router identity."""
    if info is None or not isinstance(info.model, str):
        return False
    model = _normalize_router_model(info.model)
    return _router_serial(info) is not None and model in _SUPPORTED_DISCOVERY_MODELS


def _same_discovered_router(
    discovered: ValidationResult | None, validated: ValidationResult
) -> bool:
    """Require full validation to prove the same allowlisted public identity."""
    if discovered is None:
        return False
    discovered_info = discovered.router_info
    validated_info = validated.router_info
    if not (
        _is_supported_discovered_router(discovered_info)
        and _is_supported_discovered_router(validated_info)
    ):
        return False
    if discovered_info is None or validated_info is None:
        return False
    discovered_serial = _router_serial(discovered_info)
    validated_serial = _router_serial(validated_info)
    if discovered_serial is None or validated_serial is None:
        return False
    return (
        _normalize_router_model(discovered_info.model)
        == _normalize_router_model(validated_info.model)
        and discovered_serial.casefold() == validated_serial.casefold()
        and discovered.unique_id == validated.unique_id
    )


def _normalize_router_model(value: str) -> str:
    """Normalize router model only for exact allowlist comparison."""
    return " ".join(value.split()).casefold()


def _router_serial(info: RouterInfo) -> str | None:
    """Return a non-empty typed router serial number."""
    if not isinstance(info.serial_number, str):
        return None
    return _nonempty(info.serial_number)


def _nonempty(value: Any) -> str | None:
    """Return stripped non-empty string."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
