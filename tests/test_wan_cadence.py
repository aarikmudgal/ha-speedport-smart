"""Offline deadlines and consecutive-sample WAN rate regressions."""

# Exact internal deadlines are inspected only to prove scheduling boundaries.
# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportConnectionError
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import WanCounters


async def _hub(
    hass: HomeAssistant, client: MagicMock, now: list[float]
) -> SpeedportHub:
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="synthetic",
        wan_counter_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    hub._public_status_next_poll_at = float("inf")
    return hub


@pytest.mark.parametrize("phase", [0.0, 0.2, 0.999])
@pytest.mark.parametrize("latency", [0.001, 0.1, 0.7])
async def test_one_second_slots_do_not_skip_for_latency_or_late_jitter(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
    phase: float,
    latency: float,
) -> None:
    """A late timer consumes one slot, without moving the anchored next slot."""
    now = [100 + phase]
    hub = await _hub(hass, mock_speedport_client, now)
    starts = []

    async def read(**_kwargs: object) -> WanCounters:
        starts.append(now[0])
        now[0] += latency
        return wan_counters

    mock_speedport_client.get_wan_counters.side_effect = read
    for index, jitter in enumerate([0, 0.001, 0.02, 0.002, 0.01, 0.001]):
        now[0] = 100 + phase + index + jitter
        await hub.async_update_group(PollGroup.FAST)
        assert hub._wan_counter_next_poll_at == pytest.approx(101 + phase + index)
    assert len(starts) == 6
    assert hub.wan_counter_telemetry["state"] == "stable"


async def test_slow_valid_response_skips_elapsed_slots_without_catchup(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """A response taking multiple slots is accepted once; no overdue poll replays."""
    now = [100.2]
    hub = await _hub(hass, mock_speedport_client, now)

    async def read(**_kwargs: object) -> WanCounters:
        now[0] += 2.1
        return wan_counters

    mock_speedport_client.get_wan_counters.side_effect = read
    await hub.async_update_group(PollGroup.FAST)
    assert hub.get("wan.bytes_received") == wan_counters.bytes_received
    assert hub._wan_counter_next_poll_at == pytest.approx(103.2)
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 1


async def test_status_delay_rechecks_wan_due_after_await(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A WAN slot becoming due during Status is consumed in that same refresh."""
    now = [100.2]
    hub = await _hub(hass, mock_speedport_client, now)
    await hub.async_update_group(PollGroup.FAST)
    now[0] = 100.9
    hub._public_status_next_poll_at = 0
    status = mock_speedport_client.get_status.return_value

    async def read_status() -> object:
        now[0] = 101.3
        return status

    mock_speedport_client.get_status.side_effect = read_status
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 2
    assert hub._wan_counter_next_poll_at == pytest.approx(102.2)


async def test_live_rate_uses_latest_pair_and_resets_on_failure(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """Latest-pair rates use real elapsed time and errors clear the baseline."""
    now = [100.0]
    hub = await _hub(hass, mock_speedport_client, now)
    for seconds, received in [(100, 0), (101, 0), (102, 1_000_000)]:
        now[0] = seconds
        mock_speedport_client.get_wan_counters.return_value = replace(
            wan_counters,
            bytes_received=received,
            bytes_sent=received,
        )
        await hub.async_update_group(PollGroup.FAST)
    assert hub.get("wan.download_rate_bps") == 8_000_000
    assert hub.wan_counter_telemetry["observed_interval_seconds"] == 1
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] == 1
    mock_speedport_client.get_wan_counters.side_effect = SpeedportConnectionError(
        "synthetic"
    )
    now[0] = 103
    await hub.async_update_group(PollGroup.FAST)
    assert hub.wan_counter_telemetry["observed_interval_seconds"] is None
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None
    assert hub.get("wan.download_rate_bps") is None
    mock_speedport_client.get_wan_counters.side_effect = None
    now[0] = 163
    await hub.async_update_group(PollGroup.FAST)
    assert hub.wan_counter_telemetry["observed_interval_seconds"] is None
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None
    assert hub.get("wan.download_rate_bps") is None
    now[0] = 164.25
    await hub.async_update_group(PollGroup.FAST)
    assert hub.wan_counter_telemetry["observed_interval_seconds"] == 1.25
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] == 1.25


async def test_interface_change_cannot_mix_counter_baselines(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """Increasing counters on another interface are not a traffic spike."""
    now = [100.0]
    hub = await _hub(hass, mock_speedport_client, now)
    await hub.async_update_group(PollGroup.FAST)
    now[0] = 101
    mock_speedport_client.get_wan_counters.return_value = replace(
        wan_counters,
        interface=replace(wan_counters.interface, index=99),
        bytes_received=wan_counters.bytes_received + 1_000_000,
    )
    await hub.async_update_group(PollGroup.FAST)
    assert hub.get("wan.download_rate_bps") is None
    assert hub.wan_counter_telemetry["observed_interval_seconds"] is None


async def test_waiting_fast_refresh_never_overlaps_or_replays_a_missed_slot(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """Even an explicit concurrent refresh waits, then observes the future slot."""
    now = [100.2]
    hub = await _hub(hass, mock_speedport_client, now)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(**_kwargs: object) -> WanCounters:
        entered.set()
        await release.wait()
        now[0] = 102.3
        return wan_counters

    mock_speedport_client.get_wan_counters.side_effect = read
    first = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
    await entered.wait()
    second = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
    await asyncio.sleep(0)
    assert mock_speedport_client.get_wan_counters.await_count == 1
    release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert second_result.generation > first_result.generation
    assert mock_speedport_client.get_wan_counters.await_count == 1
    assert hub._wan_counter_next_poll_at == pytest.approx(103.2)


async def test_utc_grid_alignment_is_once_and_wall_clock_jumps_do_not_move_it(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Whole UTC seconds select the initial phase only; deadlines stay monotonic."""
    now = [100.75]
    hub = await _hub(hass, mock_speedport_client, now)
    with patch("custom_components.speedport_smart.hub.datetime") as wall_clock:
        wall_clock.now.return_value = datetime(2026, 9, 3, 12, 0, 0, 750000, tzinfo=UTC)
        hub.align_fast_poll_clock()
        assert hub._wan_counter_grid_anchor == 100.0
        now[0] = 200.5
        wall_clock.now.return_value = datetime(2025, 1, 1, tzinfo=UTC)
        hub.align_fast_poll_clock()
        assert hub._wan_counter_grid_anchor == 100.0
    await hub.async_update_group(PollGroup.FAST)
    assert hub._wan_counter_next_poll_at == 201.0


async def test_fractional_failure_keeps_fixed_cooldown_and_original_grid(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Sixty seconds is eligibility, never a replacement fractional grid phase."""
    now = [100.0]
    hub = await _hub(hass, mock_speedport_client, now)
    await hub.async_update_group(PollGroup.FAST)

    async def fail(**_kwargs: object) -> None:
        now[0] += 0.231
        raise SpeedportConnectionError("synthetic")

    now[0] = 101
    mock_speedport_client.get_wan_counters.side_effect = fail
    await hub.async_update_group(PollGroup.FAST)
    assert hub._wan_counter_retry_at == pytest.approx(161.231)
    assert hub._wan_counter_next_poll_at == 162
    mock_speedport_client.get_wan_counters.side_effect = None
    now[0] = 161.231
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 2
    assert hub.wan_counter_telemetry["state"] == "learning"
    now[0] = 162.001
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 3
    assert hub._wan_counter_next_poll_at == 163
