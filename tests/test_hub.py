"""Tests for Speedport runtime hub."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.speedport_smart.api import (
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
    RouterInfo,
    RouterStatus,
    WanCounters,
    WanInterface,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_setup_and_grouped_data(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Hub discovers semantic capabilities and merges polling groups."""
    mock_speedport_client.get_json.side_effect = lambda endpoint, **_kwargs: (
        {"use_wlan": True} if endpoint == "data/WLANBasic.json" else {"use_mesh": True}
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
    )

    await hub.async_setup()
    fast = await hub.async_update_group(PollGroup.FAST)
    normal = await hub.async_update_group(PollGroup.NORMAL)
    slow = await hub.async_update_group(PollGroup.SLOW)

    assert hub.router_identifier == "SP4R-TEST-001"
    assert hub.has_capability("internet")
    assert hub.has_capability("wan")
    assert hub.has_capability("wifi")
    assert hub.get("internet.state") is True
    assert hub.get(("wan", "interface", "alias")) == "BONDING"
    assert hub.get("wifi.enabled") is True
    assert hub.get("mesh.enabled") is True
    assert fast.generation == 1
    assert normal.generation == 2
    assert slow.generation == 3
    assert hub.get("missing.path", "fallback") == "fallback"


async def test_rate_delta_and_counter_reset(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_interface: WanInterface,
) -> None:
    """Rates use monotonic deltas and counter reset emits no spike."""
    times = iter((100.0, 105.0, 110.0))
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
        rate_window_seconds=10,
        monotonic_time=lambda: next(times),
    )

    first = WanCounters(wan_interface, 1_000, 500, datetime.now(UTC))
    second = WanCounters(wan_interface, 6_001_000, 1_500_500, datetime.now(UTC))
    reset = WanCounters(wan_interface, 10, 5, datetime.now(UTC))

    first_data = hub._normalise_wan_counters(  # noqa: SLF001
        first, download_capacity=10_000_000, upload_capacity=4_000_000
    )
    second_data = hub._normalise_wan_counters(  # noqa: SLF001
        second, download_capacity=10_000_000, upload_capacity=4_000_000
    )
    reset_data = hub._normalise_wan_counters(  # noqa: SLF001
        reset, download_capacity=10_000_000, upload_capacity=4_000_000
    )

    assert first_data["download_rate_bps"] is None
    assert second_data["download_rate_bps"] == 9_600_000
    assert second_data["upload_rate_bps"] == 2_400_000
    assert second_data["download_utilization"] == 96
    assert second_data["upload_utilization"] == 60
    assert reset_data["download_rate_bps"] is None
    assert reset_data["upload_rate_bps"] is None


async def test_transitions_and_fallback_identity(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """Hub emits only changes after initial state and has stable fallback ID."""
    no_serial = RouterInfo(model="Speedport", serial_number=None)
    mock_speedport_client.router_info = no_serial
    mock_speedport_client.setup.return_value = CapabilityReport(status_json=True)
    mock_speedport_client.get_status.side_effect = (
        RouterStatus(info=no_serial, internet_state="online"),
        RouterStatus(info=no_serial, internet_state="offline"),
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
    )
    await hub.async_setup()

    first = await hub.async_update_group(PollGroup.FAST)
    second = await hub.async_update_group(PollGroup.FAST)

    assert hub.router_identifier == "entry-id"
    assert first.transitions == ()
    assert len(second.transitions) == 1
    assert second.transitions[0].path == "internet.state"
    assert second.transitions[0].previous is True
    assert second.transitions[0].current is False
    assert router_info.serial_number != hub.router_identity.serial_number


async def test_feature_failure_isolation_and_authentication(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Optional family failure does not erase another family or mask auth loss."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability("wifi", "wifi"),
                "clients": EndpointCapability("clients", "clients"),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "wifi":
            raise SpeedportConnectionError("temporary")
        return {"mdevice_mac": ["AA:BB:CC:DD:EE:FF"]}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    assert len(hub.get("clients.items")) == 1
    assert hub.get("wifi") is None
    assert hub.diagnostics()["endpoint_errors"] == {"wifi": "SpeedportConnectionError"}

    mock_speedport_client.get_json.side_effect = SpeedportInvalidCredentialsError(
        "invalid"
    )
    with pytest.raises(SpeedportInvalidCredentialsError):
        await hub.async_update_group(PollGroup.NORMAL)


async def test_unsupported_counter_removed_and_close_idempotent(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A transient counter failure preserves the confirmed capability for retry."""
    mock_speedport_client.get_wan_counters.side_effect = SpeedportUnsupportedError
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    assert hub.has_capability("wan_counters")
    assert hub.get("wan.bytes_received") is None
    assert hub.diagnostics()["endpoint_errors"] == {
        "wan_counters": "SpeedportUnsupportedError"
    }
    await hub.async_close()
    await hub.async_close()
    mock_speedport_client.close.assert_awaited_once()
    with pytest.raises(SpeedportConnectionError):
        await hub.async_update_group(PollGroup.FAST)


async def test_command_gate_and_verification(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Commands require opt-in, allowlist, implementation, and verification poll."""
    disabled = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
    )
    assert not disabled.supports_command("wifi_set_enabled")
    with pytest.raises(HomeAssistantError, match="disabled"):
        await disabled.async_execute("wifi_set_enabled", enabled=True)

    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    with pytest.raises(HomeAssistantError, match="Unsupported"):
        await hub.async_execute("factory_reset")
    with pytest.raises(HomeAssistantError, match="Unsupported"):
        await hub.async_execute("set_wifi_2_4", enabled=True)

    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(return_value="ok")
    assert hub.supports_command("wifi_set_enabled")
    assert (
        await hub.async_execute(
            "wifi_set_enabled", verify_group=PollGroup.NORMAL, enabled=True
        )
        == "ok"
    )
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=True
    )


async def test_closed_hub_cannot_be_reopened(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Closed session owner cannot silently reopen."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_close()
    with pytest.raises(SpeedportError, match="closed"):
        await hub.async_setup()
