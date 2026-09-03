"""Offline proof of five-sample WAN learning and fixed cooldown retries."""

# Private due times are inspected only to prove exact no-I/O boundaries.
# ruff: noqa: SLF001

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportInvalidCredentialsError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import CapabilityReport

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def _hub(
    hass: HomeAssistant, client: MagicMock, *, target: float = 0
) -> tuple[SpeedportHub, list[float]]:
    now = [100.0]
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="entry",
        wan_counter_interval_seconds=target,
        public_status_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    return hub, now


async def _sample(hub: SpeedportHub, now: list[float]) -> None:
    now[0] = max(now[0], hub._wan_counter_next_poll_at)
    await hub.async_update_group(PollGroup.FAST)


async def test_auto_needs_five_successful_reads_at_every_level_including_one(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Each cadence is tested five times; reaching one second is not yet proof."""
    hub, now = await _hub(hass, mock_speedport_client)
    for interval in (5, 4, 3, 2, 1):
        for count in range(1, 5):
            await _sample(hub, now)
            telemetry = hub.wan_counter_telemetry
            assert telemetry["effective_interval_seconds"] == interval
            assert telemetry["success_streak"] == count
            assert telemetry["state"] == "learning"
        await _sample(hub, now)
        telemetry = hub.wan_counter_telemetry
        assert telemetry["effective_interval_seconds"] == max(1, interval - 1)
        assert telemetry["success_streak"] == 0
        assert telemetry["success_samples_required"] == 5
        assert telemetry["cooldown_seconds"] == 60
        assert telemetry["runtime_floor_seconds"] == 1
    assert telemetry["state"] == "stable"
    assert telemetry["last_stable_interval_seconds"] == 1
    for _ in range(20):
        await _sample(hub, now)
    assert hub.wan_counter_telemetry["success_streak"] == 0
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == 1


@pytest.mark.parametrize(
    "error_type",
    [
        SpeedportSessionBusyError,
        SpeedportConnectionError,
        SpeedportProtocolError,
        SpeedportUnsupportedError,
        SpeedportAuthenticationError,
        SpeedportInvalidCredentialsError,
        SpeedportDecodeError,
    ],
)
async def test_every_supported_wan_error_cools_down_from_failure_completion(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    error_type: type[Exception],
) -> None:
    """All supported-WAN failures wait 60 seconds without changing failed cadence."""
    hub, now = await _hub(hass, mock_speedport_client)
    for _ in range(5):
        await _sample(hub, now)
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == 4

    async def fail(**_kwargs: object) -> None:
        now[0] += 10
        raise error_type("synthetic failure")

    mock_speedport_client.get_wan_counters.side_effect = fail
    await _sample(hub, now)
    failed_at = now[0]
    telemetry = hub.wan_counter_telemetry
    assert telemetry["state"] == "cooldown"
    assert telemetry["retrying"] is True
    assert telemetry["retry_in_seconds"] == 60
    assert telemetry["effective_interval_seconds"] == 4
    assert telemetry["runtime_floor_seconds"] == 1
    assert telemetry["success_streak"] == 0
    calls = mock_speedport_client.get_wan_counters.await_count
    mock_speedport_client.get_wan_counters.side_effect = None
    for seconds in (1, 30, 59.999):
        now[0] = failed_at + seconds
        await hub.async_update_group(PollGroup.FAST)
        assert mock_speedport_client.get_wan_counters.await_count == calls
        assert hub.wan_counter_telemetry["state"] == "cooldown"
        assert hub.wan_counter_telemetry["success_streak"] == 0
    now[0] = failed_at + 60
    assert hub.wan_counter_telemetry["state"] == "learning"
    assert hub.wan_counter_telemetry["retrying"] is False
    assert mock_speedport_client.get_wan_counters.await_count == calls
    # Cooldown expiry makes the next original-grid slot eligible; it does not
    # shift the polling phase to a fractional failure-completion timestamp.
    now[0] = hub._wan_counter_next_poll_at
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == calls + 1
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == 4
    assert hub.wan_counter_telemetry["success_streak"] == 1
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == calls + 1


async def test_repeated_failures_keep_sixty_seconds_without_rollback(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Repeated lease failures neither raise cadence nor multiply the cooldown."""
    hub, now = await _hub(hass, mock_speedport_client)
    for _ in range(10):
        await _sample(hub, now)
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == 3
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "synthetic busy"
    )
    for _ in range(6):
        await _sample(hub, now)
        telemetry = hub.wan_counter_telemetry
        assert telemetry["retry_in_seconds"] == 60
        assert telemetry["effective_interval_seconds"] == 3
        assert telemetry["runtime_floor_seconds"] == 1
    mock_speedport_client.get_wan_counters.side_effect = None
    for _ in range(5):
        await _sample(hub, now)
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == 2


@pytest.mark.parametrize("target", [1, 2, 5, 60])
async def test_manual_target_is_preserved_and_reproved_after_cooldown(
    hass: HomeAssistant, mock_speedport_client: MagicMock, target: int
) -> None:
    """Manual cadence remains exact; a failed read requires fresh success proof."""
    hub, now = await _hub(hass, mock_speedport_client, target=target)
    for _ in range(5):
        await _sample(hub, now)
    assert hub.wan_counter_telemetry["state"] == "stable"
    mock_speedport_client.get_wan_counters.side_effect = SpeedportConnectionError(
        "synthetic failure"
    )
    await _sample(hub, now)
    assert hub.wan_counter_telemetry["retry_in_seconds"] == 60
    assert hub.wan_counter_telemetry["effective_interval_seconds"] == target
    mock_speedport_client.get_wan_counters.side_effect = None
    for count in range(1, 6):
        await _sample(hub, now)
        telemetry = hub.wan_counter_telemetry
        assert telemetry["effective_interval_seconds"] == target
        assert telemetry["state"] == ("learning" if count < 5 else "stable")


async def test_unproven_unsupported_wan_retires_probe_without_cooldown_loop(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Explicit unsupported evidence still disables an unproven setup candidate."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        tr064=True,
        wan_counters=False,
        failures=MappingProxyType({"wan_counters": "SpeedportSessionBusyError: busy"}),
    )
    hub, now = await _hub(hass, mock_speedport_client)
    mock_speedport_client.get_wan_counters.side_effect = SpeedportUnsupportedError(
        "synthetic unsupported"
    )
    await _sample(hub, now)
    assert not hub.has_capability("wan_counters")
    assert hub.wan_counter_telemetry["retry_in_seconds"] == 0
    now[0] += 3600
    await hub.async_update_group(PollGroup.FAST)
    mock_speedport_client.get_wan_counters.assert_awaited_once()


async def test_idle_cooldown_expiry_does_not_schedule_or_burst_reads(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Only a normal scheduled poll retries; idle time earns no success credit."""
    hub, now = await _hub(hass, mock_speedport_client)
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "synthetic busy"
    )
    await _sample(hub, now)
    mock_speedport_client.get_wan_counters.side_effect = None
    calls = mock_speedport_client.get_wan_counters.await_count
    now[0] += 3600
    assert hub.wan_counter_telemetry["state"] == "learning"
    assert hub.wan_counter_telemetry["success_streak"] == 0
    assert mock_speedport_client.get_wan_counters.await_count == calls
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == calls + 1
    assert hub.wan_counter_telemetry["success_streak"] == 1
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == calls + 1
