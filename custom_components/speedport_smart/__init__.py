"""Speedport Smart Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
)
from .const import (
    CONF_ENABLE_CONTROLS,
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_NORMAL_INTERVAL,
    CONF_SLOW_INTERVAL,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DEFAULT_FAST_INTERVAL,
    DEFAULT_NORMAL_INTERVAL,
    DEFAULT_SLOW_INTERVAL,
    DEFAULT_TR064_HTTP_PORT,
    DEFAULT_TR064_HTTPS_PORT,
    PLATFORMS,
)
from .coordinator import PollGroup, SpeedportDataUpdateCoordinator
from .hub import SpeedportHub
from .migration import (
    async_migrate_wan_totals_to_gigabytes,
    async_remove_retired_router_event_entities,
)
from .panel import async_register_panel

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

type SpeedportConfigEntry = ConfigEntry[SpeedportHub]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the process-scoped Speedport Smart dashboard."""
    del config
    await async_register_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SpeedportConfigEntry) -> bool:
    """Set up Speedport Smart from a config entry."""
    settings = {**entry.data, **entry.options}
    verify_ssl = bool(settings.get(CONF_VERIFY_SSL, False))
    session = _create_isolated_session(hass, verify_ssl=verify_ssl)
    try:
        client = SpeedportClient(
            session,
            str(settings[CONF_HOST]),
            password=settings.get("password"),
            use_https=bool(settings.get(CONF_USE_HTTPS, False)),
            verify_ssl=verify_ssl,
            tr064_http_port=DEFAULT_TR064_HTTP_PORT,
            tr064_https_port=DEFAULT_TR064_HTTPS_PORT,
            owns_session=True,
        )
    except Exception:
        session.detach()
        raise
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier=entry.entry_id,
        entry_id=entry.entry_id,
        controls_enabled=bool(settings.get(CONF_ENABLE_CONTROLS, True)),
    )

    try:
        await hub.async_setup()
    except SpeedportInvalidCredentialsError as err:
        await hub.async_close()
        raise ConfigEntryAuthFailed from err
    except (
        SpeedportAuthenticationError,
        SpeedportConnectionError,
        SpeedportError,
    ) as err:
        await hub.async_close()
        message = f"Unable to set up Speedport router: {err}"
        raise ConfigEntryNotReady(message) from err

    coordinators = {
        PollGroup.FAST: SpeedportDataUpdateCoordinator(
            hass,
            hub,
            PollGroup.FAST,
            _poll_interval(settings, CONF_FAST_INTERVAL, DEFAULT_FAST_INTERVAL),
            config_entry=entry,
        ),
        PollGroup.NORMAL: SpeedportDataUpdateCoordinator(
            hass,
            hub,
            PollGroup.NORMAL,
            _poll_interval(settings, CONF_NORMAL_INTERVAL, DEFAULT_NORMAL_INTERVAL),
            config_entry=entry,
        ),
        PollGroup.SLOW: SpeedportDataUpdateCoordinator(
            hass,
            hub,
            PollGroup.SLOW,
            _poll_interval(settings, CONF_SLOW_INTERVAL, DEFAULT_SLOW_INTERVAL),
            config_entry=entry,
        ),
    }
    for group, coordinator in coordinators.items():
        hub.attach_coordinator(group, coordinator)

    entry.runtime_data = hub
    try:
        for coordinator in coordinators.values():
            await coordinator.async_config_entry_first_refresh()
        async_remove_retired_router_event_entities(hass, entry.entry_id)
        async_migrate_wan_totals_to_gigabytes(hass, entry.entry_id)
        _enable_previously_integration_disabled_entities(hass, entry)
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hub.async_close()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpeedportConfigEntry) -> bool:
    """Unload Speedport Smart config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_close()
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: SpeedportConfigEntry) -> None:
    """Reload after options or connection settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _enable_previously_integration_disabled_entities(
    hass: HomeAssistant,
    entry: SpeedportConfigEntry,
) -> None:
    """Enable entities disabled by older integration defaults, not by users."""
    if entry.pref_disable_new_entities:
        return
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entity_entry.entity_id, disabled_by=None)


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


def _poll_interval(settings: dict[str, Any], key: str, default: timedelta) -> timedelta:
    """Read persisted seconds as polling interval."""
    value = settings.get(key)
    if value is None:
        return default
    if isinstance(value, timedelta):
        return value
    return timedelta(seconds=max(float(value), 1.0))
