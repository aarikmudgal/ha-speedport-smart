"""Tests for Speedport Smart config-entry lifecycle."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.speedport_smart import (
    _async_reload_entry,
    _enable_previously_integration_disabled_entities,
    _poll_interval,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportInvalidCredentialsError,
)
from custom_components.speedport_smart.const import (
    CONF_ENABLE_CONTROLS,
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_NORMAL_INTERVAL,
    CONF_SLOW_INTERVAL,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
)
from custom_components.speedport_smart.coordinator import PollGroup

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _entry() -> MockConfigEntry:
    """Create representative config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: "speedport.ip",
            CONF_USE_HTTPS: False,
            CONF_VERIFY_SSL: False,
        },
        options={
            CONF_ENABLE_CONTROLS: True,
            CONF_FAST_INTERVAL: 6,
            CONF_NORMAL_INTERVAL: 31,
            CONF_SLOW_INTERVAL: 301,
        },
    )


async def test_setup_unload_and_reload(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Lifecycle stores hub in runtime_data and closes it only after unload."""
    entry = _entry()
    entry.add_to_hass(hass)
    for dependency in ("frontend", "http", "panel_custom", "websocket_api"):
        mock_component(hass, dependency)
    with (
        patch(
            "custom_components.speedport_smart.async_register_panel",
            AsyncMock(),
        ),
        patch(
            "custom_components.speedport_smart.SpeedportClient",
            return_value=mock_speedport_client,
        ),
        patch(
            "custom_components.speedport_smart._create_isolated_session",
            return_value=MagicMock(),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(),
        ) as forward,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    hub = entry.runtime_data
    assert entry.state is ConfigEntryState.LOADED
    assert hub.controls_enabled
    assert hub.coordinator(PollGroup.FAST).update_interval == timedelta(seconds=6)
    assert hub.coordinator(PollGroup.NORMAL).update_interval == timedelta(seconds=31)
    assert hub.coordinator(PollGroup.SLOW).update_interval == timedelta(seconds=301)
    assert hub.available
    forward.assert_awaited_once_with(entry, PLATFORMS)

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ) as unload:
        assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    unload.assert_awaited_once_with(entry, PLATFORMS)
    mock_speedport_client.close.assert_awaited_once()

    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry:
        await _async_reload_entry(hass, entry)
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_setup_enables_only_integration_disabled_entities_without_commands(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Setup migrates old defaults without commands or overriding user choice."""
    entry = _entry()
    entry.add_to_hass(hass)
    for dependency in ("frontend", "http", "panel_custom", "websocket_api"):
        mock_component(hass, dependency)
    registry = er.async_get(hass)
    integration_disabled = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "old_integration_default",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    user_disabled = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "user_disabled",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )

    with (
        patch(
            "custom_components.speedport_smart.async_register_panel",
            AsyncMock(),
        ),
        patch(
            "custom_components.speedport_smart.SpeedportClient",
            return_value=mock_speedport_client,
        ),
        patch(
            "custom_components.speedport_smart._create_isolated_session",
            return_value=MagicMock(),
        ),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)

    assert registry.async_get(integration_disabled.entity_id).disabled_by is None
    assert (
        registry.async_get(user_disabled.entity_id).disabled_by
        is er.RegistryEntryDisabler.USER
    )
    for method_name in (
        "reconnect",
        "execute_internet_reconnect",
        "reboot",
        "execute_router_reboot",
        "wps",
        "execute_wps_start",
        "execute_wifi_set_enabled",
        "set_guest_wifi",
        "execute_guest_wifi_set_enabled",
        "set_office_wifi",
        "rename_client",
        "set_client_fixed_dhcp",
        "set_port_forward_rule",
        "execute_port_mapping_set_enabled",
    ):
        getattr(mock_speedport_client, method_name).assert_not_awaited()


def test_entity_migration_respects_disable_new_entities_preference(
    hass: HomeAssistant,
) -> None:
    """Do not override the config entry's explicit disable-new preference."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "speedport.ip"},
        pref_disable_new_entities=True,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    integration_disabled = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "preference_disabled",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )

    _enable_previously_integration_disabled_entities(hass, entry)

    assert (
        registry.async_get(integration_disabled.entity_id).disabled_by
        is er.RegistryEntryDisabler.INTEGRATION
    )


async def test_unload_failure_keeps_client_open(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Failed platform unload preserves active runtime client."""
    entry = _entry()
    hub = MagicMock()
    hub.async_close = AsyncMock()
    entry.runtime_data = hub
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    ):
        assert not await async_unload_entry(hass, entry)
    hub.async_close.assert_not_awaited()
    mock_speedport_client.close.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SpeedportInvalidCredentialsError("bad"), ConfigEntryAuthFailed),
        (SpeedportAuthenticationError("expired"), ConfigEntryNotReady),
        (SpeedportConnectionError("offline"), ConfigEntryNotReady),
    ],
)
async def test_setup_error_closes_client(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    error: Exception,
    expected: type[Exception],
) -> None:
    """Setup maps protocol failures and closes partially initialized client."""
    entry = _entry()
    mock_speedport_client.setup.side_effect = error
    with (
        patch(
            "custom_components.speedport_smart.SpeedportClient",
            return_value=mock_speedport_client,
        ),
        patch(
            "custom_components.speedport_smart._create_isolated_session",
            return_value=MagicMock(),
        ),
        pytest.raises(expected),
    ):
        await async_setup_entry(hass, entry)
    mock_speedport_client.close.assert_awaited_once()


def test_poll_interval_parsing() -> None:
    """Polling parser accepts persisted seconds and timedeltas."""
    default = timedelta(seconds=30)
    assert _poll_interval({}, "interval", default) == default
    assert _poll_interval({"interval": 0}, "interval", default) == timedelta(seconds=1)
    custom = timedelta(seconds=9)
    assert _poll_interval({"interval": custom}, "interval", default) is custom
