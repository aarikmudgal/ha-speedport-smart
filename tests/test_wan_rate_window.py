"""Offline bounded WAN averages for router-side batched byte counters."""

# The rate boundary is exercised without router requests or coordinators.
# ruff: noqa: SLF001

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from custom_components.speedport_smart.hub import SpeedportHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import WanCounters


def _hub(
    hass: HomeAssistant, client: MagicMock, now: list[float], **kwargs: float
) -> SpeedportHub:
    return SpeedportHub(
        hass,
        client,
        fallback_identifier="synthetic-rate-window",
        monotonic_time=lambda: now[0],
        **kwargs,
    )


@pytest.mark.parametrize("jitter", [0.0, 0.015])
def test_five_second_batches_do_not_become_zero_and_fivefold_spikes(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
    jitter: float,
) -> None:
    """One-second observations average one complete five-second counter batch."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    for second in range(21):
        now[0] = second + (jitter if second % 2 else 0)
        total = second // 5 * 5_000_000
        data = hub._normalise_wan_counters(
            replace(wan_counters, bytes_received=total, bytes_sent=total // 2)
        )
        if second >= 5:
            assert data["download_rate_bps"] == pytest.approx(8_000_000, rel=0.004)
            assert data["upload_rate_bps"] == pytest.approx(4_000_000, rel=0.004)
            telemetry = hub.wan_counter_telemetry
            assert telemetry["rate_window_seconds"] == 5
            assert telemetry["rate_sample_span_seconds"] == pytest.approx(5, abs=0.02)
    mock_speedport_client.get_wan_counters.assert_not_called()


def test_real_idle_decays_to_zero_without_holding_last_nonzero(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """A burst leaves the finite window; no last nonzero value is retained."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    rates = []
    for second in range(12):
        now[0] = float(second)
        total = min(second, 5) * 1_000_000
        rates.append(
            hub._normalise_wan_counters(
                replace(wan_counters, bytes_received=total, bytes_sent=total)
            )["download_rate_bps"]
        )
    assert rates[0] is None
    assert rates[5:] == [8_000_000, 6_400_000, 4_800_000, 3_200_000, 1_600_000, 0, 0]


def test_warmup_and_sparse_reads_report_real_pair_span(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """A nominal window never invents a missing five-second counter sample."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    observations = [(0, 0, None), (2, 2_000_000, 2), (20, 20_000_000, 18)]
    for second, total, expected_span in observations:
        now[0] = float(second)
        data = hub._normalise_wan_counters(
            replace(wan_counters, bytes_received=total, bytes_sent=total)
        )
        assert hub.wan_counter_telemetry["rate_sample_span_seconds"] == expected_span
        if expected_span is not None:
            assert data["download_rate_bps"] == 8_000_000


@pytest.mark.parametrize("reset", ["rollback", "interface", "failure"])
def test_reset_discards_average_and_actual_span(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
    reset: str,
) -> None:
    """The averaging window shares existing counter reset and failure ownership."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    for second in range(6):
        now[0] = float(second)
        hub._normalise_wan_counters(
            replace(wan_counters, bytes_received=second * 1_000_000, bytes_sent=0)
        )
    current = replace(wan_counters, bytes_received=6_000_000, bytes_sent=0)
    if reset == "rollback":
        current = replace(current, bytes_received=1)
    elif reset == "interface":
        current = replace(current, interface=replace(current.interface, index=99))
    else:
        # Existing WAN failure branches clear this same sample deque.
        hub._counter_samples.clear()
        assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None
    now[0] = 6.0
    data = hub._normalise_wan_counters(current)
    assert data["download_rate_bps"] is None
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None


def test_duplicate_clock_has_no_rate_and_window_remains_bounded(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """Nonpositive elapsed time is never divided; retained samples stay finite."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now, rate_window_seconds=3)
    for _ in range(2):
        data = hub._normalise_wan_counters(wan_counters)
        assert data["download_rate_bps"] is None
    for second in range(1, 100):
        now[0] = float(second)
        hub._normalise_wan_counters(wan_counters)
    assert hub.wan_counter_telemetry["rate_window_seconds"] == 3
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] == 3
    assert len(hub._counter_samples) <= 8
    data = hub._normalise_wan_counters(wan_counters)
    assert data["download_rate_bps"] is None
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None
