"""Tests for trackers and opt-in controls."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speedport_smart.api import SpeedportSessionBusyError
from custom_components.speedport_smart.button import (
    BUTTON_DESCRIPTIONS,
    SpeedportCaptureReadOnlyInventoryButton,
    SpeedportCommandButton,
    SpeedportRetryProtectedDataButton,
)
from custom_components.speedport_smart.button import (
    async_setup_entry as async_setup_buttons,
)
from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.coordinator import (
    GroupSnapshot,
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
from custom_components.speedport_smart.models import EndpointCapability, RouterInfo
from custom_components.speedport_smart.select import (
    SELECT_DESCRIPTIONS,
    SpeedportCommandSelect,
)
from custom_components.speedport_smart.select import (
    async_setup_entry as async_setup_selects,
)
from custom_components.speedport_smart.switch import (
    SWITCH_DESCRIPTIONS,
    SpeedportClientFixedDhcpSwitch,
    SpeedportClientInternetSwitch,
    SpeedportCommandSwitch,
    SpeedportPortForwardSwitch,
)
from custom_components.speedport_smart.switch import (
    async_setup_entry as async_setup_switches,
)
from custom_components.speedport_smart.text import SpeedportClientNameText
from custom_components.speedport_smart.text import (
    async_setup_entry as async_setup_texts,
)
from custom_components.speedport_smart.update import (
    SpeedportFirmwareUpdate,
)
from custom_components.speedport_smart.update import (
    async_setup_entry as async_setup_updates,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_PORT_FORWARD_FINGERPRINT = "a" * 64


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


def _add_exact_feature_families(hub: SpeedportHub, *families: str) -> None:
    """Add exact probed endpoint families to a focused control fixture."""
    report = hub._capability_report  # noqa: SLF001 - explicit capability fixture
    assert report is not None
    endpoints = dict(report.feature_endpoints)
    endpoints.update(
        {
            family: EndpointCapability(
                family,
                f"data/{family}.json",
                authenticated=True,
            )
            for family in families
        }
    )
    hub._apply_capability_report(  # noqa: SLF001 - explicit capability fixture
        replace(
            report,
            authenticated_json=True,
            feature_endpoints=MappingProxyType(endpoints),
        )
    )


async def test_select_setup_requires_reviewed_identity_capabilities_and_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Enumerated controls exist only on the exact reviewed router contract."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_exact_feature_families(
        hub,
        "connection_privacy",
        "receiver",
    )
    hub._merge_data(  # noqa: SLF001
        {
            "internet": {"privacy_level": 1},
            "receiver": {"led_mode": 0},
        }
    )
    entry = MagicMock(runtime_data=hub)
    entities: list[Any] = []

    await async_setup_selects(hass, entry, entities.extend)

    assert [entity.entity_description.key for entity in entities] == [
        "internet_privacy_level_control",
        "receiver_led_mode_control",
    ]
    assert [entity.options for entity in entities] == [
        ["off", "level_1", "level_2"],
        ["use_leds", "off_after_timeout", "disabled"],
    ]
    assert [entity.current_option for entity in entities] == ["level_1", "use_leds"]
    assert all(entity.available for entity in entities)
    assert all(entity.entity_registry_enabled_default for entity in entities)

    hub._router_info = RouterInfo(  # noqa: SLF001 - exact write-contract boundary
        model="Speedport Smart 4R Typ A",
        firmware="unreviewed",
        serial_number="SP4R-TEST-001",
        hardware_version="A",
    )
    unreviewed: list[Any] = []
    await async_setup_selects(hass, entry, unreviewed.extend)

    assert unreviewed == []
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


@pytest.mark.parametrize(
    ("key", "target"),
    [
        ("internet_privacy_level_control", "level_2"),
        ("receiver_led_mode_control", "off_after_timeout"),
    ],
)
async def test_selects_noop_then_execute_exact_semantic_command(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    key: str,
    target: str,
) -> None:
    """Selects skip no-ops and send only the reviewed integer parameter."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    description = _description(SELECT_DESCRIPTIONS, key)
    initial = description.options[0]
    initial_code = description.option_codes[initial]
    parameter = description.command_parameter
    root = "internet" if key == "internet_privacy_level_control" else "receiver"
    field = "privacy_level" if root == "internet" else "led_mode"
    hub._merge_data({root: {field: initial_code}})  # noqa: SLF001
    entity = SpeedportCommandSelect(hub, description)
    hub.async_execute = AsyncMock()

    await entity.async_select_option(initial)
    hub.async_execute.assert_not_awaited()

    async def execute(command: str, **parameters: Any) -> None:
        assert command == description.command
        hub._merge_data({root: {field: parameters[parameter]}})  # noqa: SLF001

    hub.async_execute.side_effect = execute
    await entity.async_select_option(target)

    assert entity.current_option == target
    hub.async_execute.assert_awaited_once_with(
        description.command,
        verify_group=description.coordinator_group,
        **{parameter: description.option_codes[target]},
    )


async def test_selects_fail_closed_for_unknown_options_and_missing_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Unknown requested or reported values cannot reach router I/O."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    description = _description(SELECT_DESCRIPTIONS, "internet_privacy_level_control")
    hub._merge_data({"internet": {"privacy_level": 1}})  # noqa: SLF001
    entity = SpeedportCommandSelect(hub, description)
    hub.async_execute = AsyncMock()

    with pytest.raises(HomeAssistantError) as unknown_request:
        await entity.async_select_option("unexpected")

    assert unknown_request.value.translation_key == "command_verification_failed"
    hub.async_execute.assert_not_awaited()

    hub._merge_data({"internet": {"privacy_level": 99}})  # noqa: SLF001
    assert entity.current_option is None
    assert not entity.available
    with pytest.raises(HomeAssistantError) as unknown_readback:
        await entity.async_select_option("off")

    assert unknown_readback.value.translation_key == "command_verification_failed"
    hub.async_execute.assert_not_awaited()


async def test_select_rejects_mismatched_post_command_readback_and_backoff(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Selects require matching refreshed state and honor management backoff."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_exact_feature_families(hub, "receiver")
    description = _description(SELECT_DESCRIPTIONS, "receiver_led_mode_control")
    hub._merge_data({"receiver": {"led_mode": 0}})  # noqa: SLF001
    entity = SpeedportCommandSelect(hub, description)
    hub.async_execute = AsyncMock(return_value={"status": "ok"})

    assert entity.available
    with pytest.raises(HomeAssistantError) as mismatch:
        await entity.async_select_option("disabled")

    assert mismatch.value.translation_key == "command_verification_failed"
    hub.async_execute.assert_awaited_once_with(
        "set_receiver_led_mode",
        verify_group=PollGroup.NORMAL,
        mode=2,
    )

    hub._mark_management_busy(SpeedportSessionBusyError("busy"))  # noqa: SLF001
    assert not entity.available


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
    wps = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    normal_coordinator = hub.coordinator(PollGroup.NORMAL)

    async def execute(command: str, **parameters: Any) -> None:
        if command == "wifi_set_enabled":
            hub._merge_data(  # noqa: SLF001 - verified readback fixture
                {
                    "wifi": {
                        "enabled": parameters["enabled"],
                        "wps_status": "idle",
                    }
                }
            )
        elif command == "wps":
            hub._merge_data(  # noqa: SLF001 - verified readback fixture
                {"wifi": {"enabled": True, "wps_status": "active"}}
            )

    hub.async_execute.side_effect = execute
    hub.async_execute.assert_not_awaited()
    normal_coordinator.async_request_refresh.assert_not_awaited()
    assert wifi.is_on
    await wifi.async_turn_on()
    hub.async_execute.assert_not_awaited()
    await wifi.async_turn_off()
    hub.async_execute.assert_awaited_once_with(
        "wifi_set_enabled", verify_group=PollGroup.NORMAL, enabled=False
    )
    await wifi.async_turn_on()
    assert hub.async_execute.await_count == 2
    normal_coordinator.async_request_refresh.assert_not_awaited()

    hub.async_execute.reset_mock()
    await wps.async_press()
    hub.async_execute.assert_awaited_once_with("wps", verify_group=PollGroup.NORMAL)
    normal_coordinator.async_request_refresh.assert_not_awaited()


async def test_management_backoff_makes_mutating_entities_unavailable(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Buttons, switches, and text fail closed while recovery remains available."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_exact_feature_families(hub, "clients", "wps")
    client = {
        "id": "aa:bb:cc:dd:ee:ff",
        "source_kind": "addmdevice",
        "source_row_id": "row-1",
        "managed_form_supported": True,
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Phone",
        "ipv4": "192.0.2.10",
        "connected": True,
        "fixed_dhcp": False,
        "uses_dhcp": True,
        "uses_rule": 0,
    }
    hub._merge_data(  # noqa: SLF001
        {
            "wifi": {"enabled": True, "wps_status": "idle"},
            "clients": {"items": [client]},
        }
    )
    switch = SpeedportCommandSwitch(hub, _description(SWITCH_DESCRIPTIONS, "wifi"))
    button = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    text = SpeedportClientNameText(hub, "aa:bb:cc:dd:ee:ff")
    retry = SpeedportRetryProtectedDataButton(hub)
    capture = SpeedportCaptureReadOnlyInventoryButton(hub)

    assert switch.available
    assert button.available
    assert text.available
    assert retry.available
    assert capture.available

    hub._mark_management_busy(SpeedportSessionBusyError("busy"))  # noqa: SLF001

    assert not switch.available
    assert not button.available
    assert not text.available
    assert retry.available
    assert capture.available

    hub._set_management_access("available")  # noqa: SLF001
    hub._protected_retry_at = 0.0  # noqa: SLF001 - isolate firmware gate
    hub._merge_data(  # noqa: SLF001 - firmware-state safety fixture
        {"system": {"settings_write_blocked": True}}
    )

    assert not switch.available
    assert not button.available
    assert not text.available
    assert retry.available
    assert capture.available

    hub._merge_data(  # noqa: SLF001 - isolate protected retry gate
        {"system": {"settings_write_blocked": False}}
    )
    hub._protected_retry_at = hub._monotonic_time() + 60  # noqa: SLF001

    assert not switch.available
    assert not button.available
    assert not text.available
    assert retry.available
    assert capture.available

    hub.async_capture_candidate_inventory = AsyncMock()
    await capture.async_press()
    hub.async_capture_candidate_inventory.assert_awaited_once_with()


async def test_wps_requires_fresh_started_state(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A command acknowledgement alone cannot claim WPS started."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data({"wifi": {"wps_status": "idle"}})  # noqa: SLF001
    hub.async_execute = AsyncMock(return_value={"status": "ok"})
    wps = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))

    with pytest.raises(HomeAssistantError):
        await wps.async_press()

    hub.async_execute.assert_awaited_once_with("wps", verify_group=PollGroup.NORMAL)


async def test_wps_terminal_state_does_not_block_a_new_pairing_window(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A prior terminal WPS result is inactive and permits a new request."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data({"wifi": {"wps_status": "configured"}})  # noqa: SLF001

    async def execute(_command: str, **_parameters: Any) -> None:
        hub._merge_data({"wifi": {"wps_status": "success"}})  # noqa: SLF001

    hub.async_execute = AsyncMock(side_effect=execute)
    wps = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))

    await wps.async_press()
    hub.async_execute.assert_awaited_once_with("wps", verify_group=PollGroup.NORMAL)

    hub.async_execute.reset_mock()
    hub._merge_data({"wifi": {"wps_status": "active"}})  # noqa: SLF001
    await wps.async_press()
    hub.async_execute.assert_not_awaited()


async def test_fixed_switch_rejects_missing_state_without_command(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Direct service calls cannot mutate a switch with unknown readback."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data({"wifi": {"enabled": None}})  # noqa: SLF001
    hub.async_execute = AsyncMock()
    entity = SpeedportCommandSwitch(hub, _description(SWITCH_DESCRIPTIONS, "wifi"))

    assert not entity.available
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_turn_on()

    assert error.value.translation_key == "command_verification_failed"
    hub.async_execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("key", "initial_state"),
    [("wifi", "on"), ("guest_wifi", "off"), ("office_wifi", "on")],
)
async def test_fixed_switches_noop_and_verify_matching_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    key: str,
    initial_state: str,
) -> None:
    """Each reachable fixed switch skips no-ops and proves changed state."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    initial = initial_state == "on"
    wifi_data: dict[str, Any] = {
        "enabled": True,
        "guest": {"enabled": False},
        "office": {"enabled": True},
    }
    hub._merge_data({"wifi": wifi_data})  # noqa: SLF001
    entity = SpeedportCommandSwitch(hub, _description(SWITCH_DESCRIPTIONS, key))
    hub.async_execute = AsyncMock()

    await entity._async_set(enabled=initial)  # noqa: SLF001
    hub.async_execute.assert_not_awaited()

    async def execute(command: str, **parameters: Any) -> None:
        assert command == entity.entity_description.command
        if key == "wifi":
            wifi_data["enabled"] = parameters["enabled"]
        else:
            section = "guest" if key == "guest_wifi" else "office"
            wifi_data[section]["enabled"] = parameters["enabled"]
        hub._merge_data({"wifi": wifi_data})  # noqa: SLF001

    hub.async_execute.side_effect = execute
    await entity._async_set(enabled=not initial)  # noqa: SLF001

    assert entity.is_on is not initial
    hub.async_execute.assert_awaited_once_with(
        entity.entity_description.command,
        verify_group=PollGroup.NORMAL,
        enabled=not initial,
    )


async def test_hybrid_bonding_switch_noops_and_verifies_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Hybrid bonding changes only after a known state and matching refresh."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data({"hybrid": {"enabled": True}})  # noqa: SLF001
    entity = SpeedportCommandSwitch(
        hub,
        _description(SWITCH_DESCRIPTIONS, "hybrid_bonding"),
    )
    hub.async_execute = AsyncMock()

    await entity.async_turn_on()
    hub.async_execute.assert_not_awaited()

    async def execute(command: str, **parameters: Any) -> None:
        assert command == "set_hybrid_bonding"
        assert parameters == {
            "verify_group": PollGroup.NORMAL,
            "enabled": False,
        }
        hub._merge_data({"hybrid": {"enabled": False}})  # noqa: SLF001

    hub.async_execute.side_effect = execute
    await entity.async_turn_off()

    assert entity.is_on is False
    hub.async_execute.assert_awaited_once_with(
        "set_hybrid_bonding",
        verify_group=PollGroup.NORMAL,
        enabled=False,
    )


@pytest.mark.parametrize(
    ("key", "initial_state"),
    [("wifi", "on"), ("guest_wifi", "off"), ("office_wifi", "on")],
)
async def test_fixed_switches_reject_mismatched_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    key: str,
    initial_state: str,
) -> None:
    """A successful command response cannot replace fixed-switch readback."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    initial = initial_state == "on"
    hub._merge_data(  # noqa: SLF001
        {
            "wifi": {
                "enabled": True,
                "guest": {"enabled": False},
                "office": {"enabled": True},
            }
        }
    )
    hub.async_execute = AsyncMock(return_value={"status": "ok"})
    entity = SpeedportCommandSwitch(hub, _description(SWITCH_DESCRIPTIONS, key))

    with pytest.raises(HomeAssistantError) as error:
        await entity._async_set(enabled=not initial)  # noqa: SLF001

    assert error.value.translation_key == "command_verification_failed"


async def test_port_forward_switch_noop_and_verifies_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Port-forward toggles skip no-ops and require matching rule state."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    rule = {
        "id": "rule-1",
        "name": "HTTPS",
        "active": True,
        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
    }
    hub._merge_data(  # noqa: SLF001
        {"nat": {"port_forward_rules": [rule]}}
    )
    entity = SpeedportPortForwardSwitch(hub, "rule-1")
    hub.async_execute = AsyncMock()

    await entity.async_turn_on()
    hub.async_execute.assert_not_awaited()

    async def execute(_command: str, **parameters: Any) -> None:
        rule["active"] = parameters["enabled"]
        hub._merge_data(  # noqa: SLF001
            {"nat": {"port_forward_rules": [rule]}}
        )

    hub.async_execute.side_effect = execute
    await entity.async_turn_off()

    assert not entity.is_on
    hub.async_execute.assert_awaited_once_with(
        "set_port_forward_rule",
        verify_group=PollGroup.SLOW,
        rule_id="rule-1",
        enabled=False,
        expected_name="HTTPS",
        expected_fingerprint=_PORT_FORWARD_FINGERPRINT,
    )


@pytest.mark.parametrize("readback", ["mismatch", "missing"])
async def test_port_forward_switch_rejects_mismatched_or_missing_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    readback: str,
) -> None:
    """Port-forward commands fail when fresh rule state is wrong or absent."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    rule = {
        "id": "rule-1",
        "name": "HTTPS",
        "active": True,
        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
    }
    hub._merge_data(  # noqa: SLF001
        {"nat": {"port_forward_rules": [rule]}}
    )
    entity = SpeedportPortForwardSwitch(hub, "rule-1")

    async def execute(_command: str, **_parameters: Any) -> None:
        if readback == "missing":
            hub._merge_data(  # noqa: SLF001
                {"nat": {"port_forward_rules": []}}
            )

    hub.async_execute = AsyncMock(side_effect=execute)

    with pytest.raises(HomeAssistantError) as error:
        await entity.async_turn_off()

    assert error.value.translation_key == "command_verification_failed"


async def test_port_forward_switch_rejects_reused_semantics_before_command(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Same ID and name cannot authorize a rule with changed target semantics."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001
        {
            "nat": {
                "port_forward_rules": [
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                    }
                ]
            }
        }
    )
    entity = SpeedportPortForwardSwitch(hub, "rule-1")
    hub.async_execute = AsyncMock()
    hub._merge_data(  # noqa: SLF001
        {
            "nat": {
                "port_forward_rules": [
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": "b" * 64,
                    }
                ]
            }
        }
    )

    assert not entity.available
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_turn_off()

    assert error.value.translation_key == "command_verification_failed"
    hub.async_execute.assert_not_awaited()


async def test_disruptive_buttons_defer_verification_and_propagate_failures(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Reboot/reconnect avoid immediate reads and entity failures are not hidden."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub.async_execute = AsyncMock()
    reconnect = SpeedportCommandButton(
        hub, _description(BUTTON_DESCRIPTIONS, "reconnect_internet")
    )
    reboot = SpeedportCommandButton(
        hub, _description(BUTTON_DESCRIPTIONS, "reboot_router")
    )

    hub.async_execute.assert_not_awaited()
    await reconnect.async_press()
    await reboot.async_press()

    assert hub.async_execute.await_args_list == [
        call("reconnect", verify_group=None),
        call("reboot", verify_group=None),
    ]
    hub.coordinator(PollGroup.NORMAL).async_request_refresh.assert_not_awaited()
    hub.coordinator(PollGroup.SLOW).async_request_refresh.assert_not_awaited()

    expected = HomeAssistantError(
        "failed",
        translation_domain=DOMAIN,
        translation_key="command_failed",
    )
    hub.async_execute = AsyncMock(side_effect=expected)
    with pytest.raises(HomeAssistantError) as raised:
        await reconnect.async_press()
    assert raised.value is expected


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
    assert [type(entity) for entity in disabled] == [
        SpeedportRetryProtectedDataButton,
        SpeedportCaptureReadOnlyInventoryButton,
    ]

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
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                    },
                    {"id": "no-fingerprint", "name": "Legacy", "active": True},
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
    hub.async_execute = AsyncMock()
    entry = MagicMock(runtime_data=hub)
    switches: list[Any] = []
    buttons: list[Any] = []
    await async_setup_switches(hass, entry, switches.extend)
    await async_setup_buttons(hass, entry, buttons.extend)
    hub.async_execute.assert_not_awaited()
    assert all(
        description.entity_registry_enabled_default
        for description in (*SWITCH_DESCRIPTIONS, *BUTTON_DESCRIPTIONS)
    )
    assert all(entity.entity_registry_enabled_default for entity in switches)
    assert all(entity.entity_registry_enabled_default for entity in buttons)
    assert (
        sum(isinstance(entity, SpeedportPortForwardSwitch) for entity in switches) == 1
    )
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
    assert any(
        isinstance(entity, SpeedportCaptureReadOnlyInventoryButton)
        for entity in buttons
    )
    assert entry.async_on_unload.call_count == 7
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_reviewed_controls_register_after_protected_capability_recovery(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A degraded platform start must not permanently omit reviewed controls."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._capabilities = frozenset({"status", "system"})  # noqa: SLF001
    hub._mark_management_unavailable()  # noqa: SLF001 - simulate GUI-owned session
    entry = MagicMock(runtime_data=hub)
    switches: list[Any] = []
    buttons: list[Any] = []
    selects: list[Any] = []
    texts: list[Any] = []

    await async_setup_switches(hass, entry, switches.extend)
    await async_setup_buttons(hass, entry, buttons.extend)
    await async_setup_selects(hass, entry, selects.extend)
    await async_setup_texts(hass, entry, texts.extend)

    assert {
        entity.entity_description.key
        for entity in switches
        if isinstance(entity, SpeedportCommandSwitch)
    } == {
        "guest_wifi",
        "hybrid_bonding",
        "office_wifi",
        "wifi",
    }
    assert {entity.entity_description.key for entity in selects} == {
        "internet_privacy_level_control",
        "receiver_led_mode_control",
    }
    assert texts == []
    assert {
        entity.entity_description.key
        for entity in buttons
        if isinstance(entity, SpeedportCommandButton)
    } == {"reboot_router", "reconnect_internet", "wps"}
    assert (
        sum(isinstance(entity, SpeedportRetryProtectedDataButton) for entity in buttons)
        == 1
    )
    assert (
        sum(
            isinstance(entity, SpeedportCaptureReadOnlyInventoryButton)
            for entity in buttons
        )
        == 1
    )
    assert all(not entity.available for entity in switches)
    assert all(not entity.available for entity in selects)
    assert all(
        not entity.available
        for entity in buttons
        if isinstance(entity, SpeedportCommandButton)
    )

    client = {
        "id": "aa:bb:cc:dd:ee:ff",
        "source_kind": "addmdevice",
        "source_row_id": "row-1",
        "managed_form_supported": True,
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Phone",
        "ipv4": "192.0.2.10",
        "connected": True,
        "fixed_dhcp": False,
        "uses_dhcp": True,
        "uses_rule": 0,
    }
    _add_exact_feature_families(
        hub,
        "clients",
        "connection_privacy",
        "hybrid",
        "internet",
        "nat",
        "port_forwarding",
        "receiver",
        "system",
        "wifi",
        "wps",
    )
    hub._merge_data(  # noqa: SLF001
        {
            "wifi": {
                "enabled": True,
                "guest": {"enabled": False},
                "office": {"enabled": True},
                "wps_status": "idle",
            },
            "internet": {"privacy_level": 1, "state": "online"},
            "hybrid": {"enabled": True},
            "receiver": {"led_mode": 0},
            "clients": {"items": [client]},
            "nat": {
                "port_forward_rules": [
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                    }
                ]
            },
        }
    )
    hub._set_management_access("available")  # noqa: SLF001 - recovered session
    snapshot = GroupSnapshot(
        group=PollGroup.NORMAL,
        data=hub.data,
        generation=1,
        updated_at=datetime.now(UTC),
    )
    hub.coordinator(PollGroup.NORMAL).async_set_updated_data(snapshot)
    hub.coordinator(PollGroup.SLOW).async_set_updated_data(
        GroupSnapshot(
            group=PollGroup.SLOW,
            data=hub.data,
            generation=1,
            updated_at=datetime.now(UTC),
        )
    )

    fixed_switch_keys = {
        entity.entity_description.key
        for entity in switches
        if isinstance(entity, SpeedportCommandSwitch)
    }
    assert fixed_switch_keys == {
        "guest_wifi",
        "hybrid_bonding",
        "office_wifi",
        "wifi",
    }
    assert sum(isinstance(item, SpeedportPortForwardSwitch) for item in switches) == 1
    assert (
        sum(isinstance(item, SpeedportClientFixedDhcpSwitch) for item in switches) == 1
    )
    assert {
        entity.entity_description.key
        for entity in buttons
        if isinstance(entity, SpeedportCommandButton)
    } == {"reboot_router", "reconnect_internet", "wps"}
    assert {entity.entity_description.key for entity in selects} == {
        "internet_privacy_level_control",
        "receiver_led_mode_control",
    }
    assert len(texts) == 1
    assert isinstance(texts[0], SpeedportClientNameText)

    counts = (len(switches), len(buttons), len(selects), len(texts))
    hub.coordinator(PollGroup.NORMAL).async_set_updated_data(snapshot)
    assert (len(switches), len(buttons), len(selects), len(texts)) == counts

    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_registered_controls_follow_firmware_drift_without_duplicates(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """Registered fixed and collection controls fail closed, then recover in place."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_exact_feature_families(
        hub,
        "clients",
        "connection_privacy",
        "hybrid",
        "internet",
        "nat",
        "port_forwarding",
        "receiver",
        "system",
        "wifi",
        "wps",
    )
    client = {
        "id": "aa:bb:cc:dd:ee:ff",
        "source_kind": "addmdevice",
        "source_row_id": "row-1",
        "managed_form_supported": True,
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Phone",
        "ipv4": "192.0.2.10",
        "connected": True,
        "fixed_dhcp": False,
        "uses_dhcp": True,
        "uses_rule": 0,
    }
    hub._merge_data(  # noqa: SLF001 - complete writable readback fixture
        {
            "hybrid": {"enabled": True},
            "internet": {"privacy_level": 1, "state": "online"},
            "receiver": {"led_mode": 0},
            "wifi": {
                "enabled": True,
                "guest": {"enabled": False},
                "office": {"enabled": True},
                "wps_status": "idle",
            },
            "clients": {"items": [client]},
            "nat": {
                "port_forward_rules": [
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                    }
                ]
            },
        }
    )
    entry = MagicMock(runtime_data=hub)
    switches: list[Any] = []
    buttons: list[Any] = []
    selects: list[Any] = []
    texts: list[Any] = []

    await async_setup_switches(hass, entry, switches.extend)
    await async_setup_buttons(hass, entry, buttons.extend)
    await async_setup_selects(hass, entry, selects.extend)
    await async_setup_texts(hass, entry, texts.extend)

    writable = [
        *switches,
        *(entity for entity in buttons if isinstance(entity, SpeedportCommandButton)),
        *selects,
        *texts,
    ]
    safe_read_only = [
        entity
        for entity in buttons
        if isinstance(
            entity,
            SpeedportRetryProtectedDataButton | SpeedportCaptureReadOnlyInventoryButton,
        )
    ]
    assert any(isinstance(entity, SpeedportPortForwardSwitch) for entity in writable)
    assert any(
        isinstance(entity, SpeedportClientFixedDhcpSwitch) for entity in writable
    )
    assert len(safe_read_only) == 2
    assert writable
    assert all(entity.available for entity in writable)
    assert all(entity.available for entity in safe_read_only)
    counts = (len(switches), len(buttons), len(selects), len(texts))

    def publish(group: PollGroup, generation: int) -> None:
        hub.coordinator(group).async_set_updated_data(
            GroupSnapshot(
                group=group,
                data=hub.data,
                generation=generation,
                updated_at=datetime.now(UTC),
            )
        )

    hub._router_info = RouterInfo(  # noqa: SLF001 - simulate reported drift
        model=router_info.model,
        firmware="unreviewed",
        serial_number=router_info.serial_number,
        hardware_version=router_info.hardware_version,
    )
    publish(PollGroup.NORMAL, 1)
    publish(PollGroup.SLOW, 1)

    assert (len(switches), len(buttons), len(selects), len(texts)) == counts
    assert all(not entity.available for entity in writable)
    assert all(entity.available for entity in safe_read_only)

    hub._router_info = router_info  # noqa: SLF001 - exact reviewed identity restored
    publish(PollGroup.NORMAL, 2)
    publish(PollGroup.SLOW, 2)
    publish(PollGroup.NORMAL, 3)

    assert (len(switches), len(buttons), len(selects), len(texts)) == counts
    assert all(entity.available for entity in writable)
    assert all(entity.available for entity in safe_read_only)

    hub._mark_management_unavailable()  # noqa: SLF001 - transient session loss
    publish(PollGroup.NORMAL, 4)

    assert (len(switches), len(buttons), len(selects), len(texts)) == counts
    assert all(not entity.available for entity in writable)
    assert all(entity.available for entity in safe_read_only)

    hub._set_management_access("available")  # noqa: SLF001 - session recovered
    publish(PollGroup.NORMAL, 5)

    assert (len(switches), len(buttons), len(selects), len(texts)) == counts
    assert all(entity.available for entity in writable)
    assert all(entity.available for entity in safe_read_only)

    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_managed_client_controls_are_gated_and_verify_readback(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Typed client controls require proven row metadata and verify new state."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_exact_feature_families(hub, "clients")
    client = {
        "id": "aa:bb:cc:dd:ee:ff",
        "source_kind": "addmdevice",
        "source_row_id": "row-1",
        "managed_form_supported": True,
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Phone",
        "ipv4": "192.0.2.10",
        "connected": True,
        "fixed_dhcp": False,
        "uses_dhcp": True,
        "uses_rule": 0,
    }
    hub._merge_data({"clients": {"items": [client]}})  # noqa: SLF001
    hub.supports_command = MagicMock(return_value=True)
    hub.async_execute = AsyncMock()
    entry = MagicMock(runtime_data=hub)
    switches: list[Any] = []
    texts: list[Any] = []

    await async_setup_switches(hass, entry, switches.extend)
    await async_setup_texts(hass, entry, texts.extend)

    fixed = next(
        entity
        for entity in switches
        if isinstance(entity, SpeedportClientFixedDhcpSwitch)
    )
    name = next(
        entity for entity in texts if isinstance(entity, SpeedportClientNameText)
    )
    registry = dr.async_get(hass)
    registry_config_entry = MockConfigEntry(domain=DOMAIN)
    registry_config_entry.add_to_hass(hass)
    registered_device = registry.async_get_or_create(
        config_entry_id=registry_config_entry.entry_id,
        identifiers=name.device_info["identifiers"],
        name="Phone",
    )
    registry.async_update_device(registered_device.id, name_by_user="My phone")
    hub.async_execute.assert_not_awaited()
    assert fixed.available
    assert not fixed.is_on
    assert name.available
    assert name.native_value == "Phone"
    assert name.native_min == 1
    assert name.native_max == 28
    assert name.device_info == fixed.device_info

    async def execute(command: str, **parameters: Any) -> None:
        updated = dict(client)
        if command == "rename_client":
            updated["name"] = parameters["name"]
        elif command == "set_client_fixed_dhcp":
            updated["fixed_dhcp"] = parameters["enabled"]
        hub._merge_data({"clients": {"items": [updated]}})  # noqa: SLF001
        client.update(updated)

    hub.async_execute.side_effect = execute
    await name.async_set_value("Living-Room")
    await fixed.async_turn_on()
    await fixed.async_turn_off()

    assert name.native_value == "Living-Room"
    renamed_device = registry.async_get(registered_device.id)
    assert renamed_device is not None
    assert renamed_device.name == "Living-Room"
    assert renamed_device.name_by_user == "My phone"
    assert not fixed.is_on
    assert hub.async_execute.await_args_list == [
        call(
            "rename_client",
            verify_group=PollGroup.NORMAL,
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            name="Living-Room",
        ),
        call(
            "set_client_fixed_dhcp",
            verify_group=PollGroup.NORMAL,
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            enabled=True,
        ),
        call(
            "set_client_fixed_dhcp",
            verify_group=PollGroup.NORMAL,
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            enabled=False,
        ),
    ]
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_invalid_current_client_name_never_creates_or_breaks_text_entity(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Legacy names outside the text contract remain safely read-only."""
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
                        "id": "aa:bb:cc:dd:ee:ff",
                        "source_kind": "addmdevice",
                        "source_row_id": "row-1",
                        "managed_form_supported": True,
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "name": "Living Room",
                    }
                ]
            }
        }
    )
    hub.supports_command = MagicMock(return_value=True)
    entry = MagicMock(runtime_data=hub)
    texts: list[Any] = []

    await async_setup_texts(hass, entry, texts.extend)

    assert texts == []
    stale = SpeedportClientNameText(hub, "aa:bb:cc:dd:ee:ff")
    assert not stale.available
    assert stale.native_value is None
    for unload_call in entry.async_on_unload.call_args_list:
        unload_call.args[0]()


async def test_managed_client_controls_reject_missing_verified_state(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A command response alone cannot claim success without matching readback."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001
        {
            "clients": {
                "items": [
                    {
                        "id": "aa:bb:cc:dd:ee:ff",
                        "source_kind": "addmdevice",
                        "source_row_id": "row-1",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "name": "Phone",
                    }
                ]
            }
        }
    )
    hub.async_execute = AsyncMock(return_value={"status": "ok"})
    entity = SpeedportClientNameText(hub, "aa:bb:cc:dd:ee:ff")

    with pytest.raises(HomeAssistantError) as error:
        await entity.async_set_value("Living-Room")

    assert error.value.translation_key == "command_verification_failed"


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
                        "internet_paused": False,
                        "internet_access_allowed": True,
                    }
                ]
            },
            "nat": {
                "port_forward_rules": [
                    {
                        "id": "rule-1",
                        "name": "HTTPS",
                        "active": True,
                        "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                    }
                ]
            },
        }
    )

    async def execute(command: str, **parameters: Any) -> None:
        if command == "set_client_internet_paused":
            hub._merge_data(  # noqa: SLF001 - verified readback fixture
                {
                    "clients": {
                        "items": [
                            {
                                "mac": "AA:BB:CC:DD:EE:FF",
                                "hostname": "Phone",
                                "ipv4": "192.0.2.20",
                                "connected": True,
                                "medium": "wifi",
                                "internet_paused": parameters["paused"],
                            }
                        ]
                    }
                }
            )
            return
        if command != "set_port_forward_rule":
            return
        hub._merge_data(  # noqa: SLF001 - verified readback fixture
            {
                "nat": {
                    "port_forward_rules": [
                        {
                            "id": "rule-1",
                            "name": "HTTPS",
                            "active": parameters["enabled"],
                            "_identity_fingerprint": _PORT_FORWARD_FINGERPRINT,
                        }
                    ]
                }
            }
        )

    hub.async_execute = AsyncMock(side_effect=execute)

    tracker = SpeedportClientTracker(hub, "aa:bb:cc:dd:ee:ff")
    assert tracker.is_connected
    assert tracker.state == STATE_HOME
    assert tracker.hostname == "Phone"
    assert tracker.ip_address == "192.0.2.20"
    assert tracker.source_type.value == "router"
    assert "192.0.2.20" not in tracker.unique_id
    assert tracker.device_info["via_device"] == (
        "speedport_smart",
        "SP4R-TEST-001",
    )
    assert tracker.mac_address == "AA:BB:CC:DD:EE:FF"
    assert tracker.extra_state_attributes == {
        "medium": "wifi",
        "internet_paused": False,
        "internet_access_allowed": True,
    }

    rule = SpeedportPortForwardSwitch(hub, "rule-1")
    assert rule.is_on
    assert rule.entity_category is EntityCategory.CONFIG
    await rule.async_turn_off()
    hub.async_execute.assert_awaited_once_with(
        "set_port_forward_rule",
        verify_group=PollGroup.SLOW,
        rule_id="rule-1",
        enabled=False,
        expected_name="HTTPS",
        expected_fingerprint=_PORT_FORWARD_FINGERPRINT,
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
    assert tracker.available
    assert not tracker.is_connected
    assert tracker.state == STATE_NOT_HOME
    assert tracker.hostname is None
    assert tracker.ip_address is None
    assert tracker.mac_address is None
    assert tracker.extra_state_attributes == {}
    assert not rule.is_on
    assert not client_switch.is_on

    hub._merge_data({"clients": {"items": None}})  # noqa: SLF001
    assert not tracker.available


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
    assert not added[0].available
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
    _add_exact_feature_families(hub, "system")
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
    assert entity.in_progress is True
    assert entity.update_percentage == 25
    assert entity.supported_features == UpdateEntityFeature.PROGRESS
    entry = MagicMock(runtime_data=hub)
    added: list[SpeedportFirmwareUpdate] = []
    await async_setup_updates(hass, entry, added.extend)
    assert len(added) == 1

    hub.supports_command = MagicMock(return_value=True)
    hub.async_execute = AsyncMock()
    writable = SpeedportFirmwareUpdate(hub)
    assert writable.supported_features == (
        UpdateEntityFeature.PROGRESS | UpdateEntityFeature.INSTALL
    )
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
    assert writable.update_percentage is None
