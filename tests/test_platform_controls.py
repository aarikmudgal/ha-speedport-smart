"""Tests for trackers and opt-in controls."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory

from custom_components.speedport_smart.button import (
    BUTTON_DESCRIPTIONS,
    SpeedportCommandButton,
    SpeedportRetryProtectedDataButton,
)
from custom_components.speedport_smart.button import (
    async_setup_entry as async_setup_buttons,
)
from custom_components.speedport_smart.coordinator import (
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.device_tracker import (
    SpeedportClientTracker,
)
from custom_components.speedport_smart.device_tracker import (
    async_setup_entry as async_setup_trackers,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.switch import (
    SWITCH_DESCRIPTIONS,
    SpeedportClientInternetSwitch,
    SpeedportCommandSwitch,
    SpeedportPortForwardSwitch,
)
from custom_components.speedport_smart.switch import (
    async_setup_entry as async_setup_switches,
)
from custom_components.speedport_smart.update import (
    SpeedportFirmwareUpdate,
)
from custom_components.speedport_smart.update import (
    async_setup_entry as async_setup_updates,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _description(descriptions: tuple[Any, ...], key: str) -> Any:
    return next(description for description in descriptions if description.key == key)


def _attach_coordinators(hass: HomeAssistant, hub: SpeedportHub) -> None:
    for group, interval in (
        (PollGroup.FAST, timedelta(seconds=5)),
        (PollGroup.NORMAL, timedelta(seconds=30)),
        (PollGroup.SLOW, timedelta(minutes=5)),
    ):
        coordinator = SpeedportDataUpdateCoordinator(hass, hub, group, interval)
        coordinator.async_request_refresh = AsyncMock()
        hub.attach_coordinator(group, coordinator)


async def test_switch_and_button_use_serialized_commands(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Controls send semantic commands and verify owning poll groups."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "wifi": {"enabled": True, "wps_status": "idle"},
        }
    )
    hub.async_execute = AsyncMock()

    wifi = SpeedportCommandSwitch(hub, _description(SWITCH_DESCRIPTIONS, "wifi"))
    assert wifi.is_on
    await wifi.async_turn_off()
    hub.async_execute.assert_awaited_once_with(
        "wifi_set_enabled", verify_group=PollGroup.NORMAL, enabled=False
    )
    await wifi.async_turn_on()
    assert hub.async_execute.await_count == 2

    hub.async_execute.reset_mock()
    wps = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    await wps.async_press()
    hub.async_execute.assert_awaited_once_with("wps", verify_group=PollGroup.NORMAL)


async def test_platform_setup_gates_controls_and_discovers_dynamic_entities(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Only confirmed, implemented controls appear after explicit opt-in."""
    disabled_hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="disabled"
    )
    await disabled_hub.async_setup()
    _attach_coordinators(hass, disabled_hub)
    disabled_entry = MagicMock(runtime_data=disabled_hub)
    disabled: list[Any] = []
    await async_setup_switches(hass, disabled_entry, disabled.extend)
    await async_setup_buttons(hass, disabled_entry, disabled.extend)
    assert len(disabled) == 1
    assert isinstance(disabled[0], SpeedportRetryProtectedDataButton)

    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = hub.capabilities | {  # noqa: SLF001
        "wifi",
        "nat",
        "clients",
        "internet",
    }
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "internet": {"state": "online"},
            "wifi": {
                "enabled": True,
                "guest": {"enabled": False},
                "office": {"enabled": True},
                "wps_status": "idle",
            },
            "nat": {
                "port_forward_rules": [
                    {"id": "rule-1", "name": "HTTPS", "active": True},
                    {"id": "no-state", "name": "No state"},
                    {"name": "No ID", "active": True},
                ]
            },
            "clients": {
                "items": [
                    {"id": "phone", "internet_paused": False},
                    {"id": "no-pause"},
                ]
            },
        }
    )
    hub.supports_command = MagicMock(return_value=True)
    entry = MagicMock(runtime_data=hub)
    switches: list[Any] = []
    buttons: list[Any] = []
    await async_setup_switches(hass, entry, switches.extend)
    await async_setup_buttons(hass, entry, buttons.extend)
    assert any(isinstance(entity, SpeedportPortForwardSwitch) for entity in switches)
    assert any(isinstance(entity, SpeedportClientInternetSwitch) for entity in switches)
    fixed_switch_keys = {
        entity.entity_description.key
        for entity in switches
        if hasattr(entity, "entity_description")
    }
    assert fixed_switch_keys >= {
        "wifi",
        "guest_wifi",
        "office_wifi",
    }
    assert {
        entity.entity_description.key
        for entity in buttons
        if hasattr(entity, "entity_description")
    } >= {
        "wps",
        "reconnect_internet",
        "reboot_router",
    }
    assert any(
        isinstance(entity, SpeedportRetryProtectedDataButton) for entity in buttons
    )
    assert entry.async_on_unload.call_count == 2
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_dynamic_rule_and_client_tracker_use_stable_ids(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Dynamic entities never use IP address or list index as identity."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "clients": {
                "items": [
                    {
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "hostname": "Phone",
                        "ipv4": "192.0.2.20",
                        "connected": True,
                        "medium": "wifi",
                    }
                ]
            },
            "nat": {
                "port_forward_rules": [
                    {"id": "rule-1", "name": "HTTPS", "active": True}
                ]
            },
        }
    )
    hub.async_execute = AsyncMock()

    tracker = SpeedportClientTracker(hub, "aa:bb:cc:dd:ee:ff")
    assert tracker.is_connected
    assert tracker.hostname == "Phone"
    assert tracker.ip_address == "192.0.2.20"
    assert tracker.source_type.value == "router"
    assert "192.0.2.20" not in tracker.unique_id
    assert tracker.device_info["via_device"] == (
        "speedport_smart",
        "SP4R-TEST-001",
    )
    assert tracker.mac_address == "AA:BB:CC:DD:EE:FF"
    assert tracker.extra_state_attributes == {"medium": "wifi"}

    rule = SpeedportPortForwardSwitch(hub, "rule-1")
    assert rule.is_on
    assert rule.entity_category is EntityCategory.CONFIG
    await rule.async_turn_off()
    hub.async_execute.assert_awaited_once_with(
        "set_port_forward_rule",
        verify_group=PollGroup.SLOW,
        rule_id="rule-1",
        enabled=False,
    )
    hub.async_execute.reset_mock()
    await rule.async_turn_on()
    hub.async_execute.assert_awaited_once()

    client_switch = SpeedportClientInternetSwitch(hub, "aa:bb:cc:dd:ee:ff")
    assert client_switch.is_on
    await client_switch.async_turn_off()
    await client_switch.async_turn_on()
    assert hub.async_execute.await_count == 3

    hub._merge_data(  # noqa: SLF001 - invalid/missing branch fixture
        {
            "clients": {"items": []},
            "nat": {"port_forward_rules": []},
        }
    )
    assert not tracker.is_connected
    assert tracker.hostname is None
    assert tracker.ip_address is None
    assert tracker.mac_address is None
    assert tracker.extra_state_attributes == {}
    assert not rule.is_on
    assert not client_switch.is_on


async def test_tracker_setup_requires_capability_and_stable_id(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Tracker discovery skips IP-only clients and subscribes for later clients."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    entry = MagicMock(runtime_data=hub)
    added: list[SpeedportClientTracker] = []
    await async_setup_trackers(hass, entry, added.extend)
    assert added == []

    hub._capabilities = hub.capabilities | {"clients"}  # noqa: SLF001
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "clients": {
                "items": [
                    {"uuid": "stable", "name": "Tablet", "active": "maybe"},
                    {"ip": "192.0.2.4", "name": "IP only"},
                ]
            }
        }
    )
    await async_setup_trackers(hass, entry, added.extend)
    assert len(added) == 1
    assert not added[0].is_connected
    assert added[0].hostname == "Tablet"
    assert entry.async_on_unload.called
    entry.async_on_unload.call_args.args[0]()


async def test_firmware_update_metadata_is_read_only_without_command(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Firmware metadata remains useful without exposing dead install action."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - platform contract fixture
        {
            "system": {
                "latest_firmware": "010152.6.0.001.0",
                "firmware_release_url": "https://example.invalid/release",
                "firmware_update_progress": 25,
            }
        }
    )
    entity = SpeedportFirmwareUpdate(hub)
    assert entity.installed_version == "010152.5.0.001.0"
    assert entity.latest_version == "010152.6.0.001.0"
    assert entity.release_url == "https://example.invalid/release"
    assert entity.in_progress == 25
    assert entity.supported_features == 0
    entry = MagicMock(runtime_data=hub)
    added: list[SpeedportFirmwareUpdate] = []
    await async_setup_updates(hass, entry, added.extend)
    assert len(added) == 1

    hub.supports_command = MagicMock(return_value=True)
    hub.async_execute = AsyncMock()
    writable = SpeedportFirmwareUpdate(hub)
    assert writable.supported_features
    await writable.async_install("010152.6.0.001.0", backup=False)
    hub.async_execute.assert_awaited_once_with(
        "firmware_update",
        verify_group=PollGroup.SLOW,
        version="010152.6.0.001.0",
    )

    hub._merge_data(  # noqa: SLF001 - invalid progress fixture
        {"system": {"firmware_update_progress": "unknown"}}
    )
    assert writable.in_progress is None
