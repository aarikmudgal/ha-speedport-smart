"""Offline WAN rates from consecutive counter observations, without smoothing."""

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


def _hub(hass: HomeAssistant, client: MagicMock, now: list[float]) -> SpeedportHub:
    return SpeedportHub(
        hass,
        client,
        fallback_identifier="synthetic-rate-window",
        monotonic_time=lambda: now[0],
    )


@pytest.mark.parametrize("jitter", [0.0, 0.015])
def test_each_rate_uses_only_the_latest_two_observations(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
    jitter: float,
) -> None:
    """A counter jump is reported immediately, not distributed across five seconds."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    for second in range(21):
        now[0] = second + (jitter if second % 2 else 0)
        total = second // 5 * 5_000_000
        data = hub._normalise_wan_counters(
            replace(wan_counters, bytes_received=total, bytes_sent=total // 2)
        )
        if second > 0:
            previous_second = second - 1
            previous_at = previous_second + (jitter if previous_second % 2 else 0)
            elapsed = now[0] - previous_at
            delta = total - previous_second // 5 * 5_000_000
            assert data["download_rate_bps"] == pytest.approx(delta * 8 / elapsed)
            assert data["upload_rate_bps"] == pytest.approx(delta * 4 / elapsed)
            telemetry = hub.wan_counter_telemetry
            assert telemetry["rate_method"] == "consecutive_samples"
            assert "rate_window_seconds" not in telemetry
            assert telemetry["rate_sample_span_seconds"] == pytest.approx(elapsed)
    mock_speedport_client.get_wan_counters.assert_not_called()


def test_unchanged_counters_return_zero_without_a_smoothed_tail(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """The first unchanged pair is zero; no previous traffic is held or averaged."""
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
    assert rates[5:] == [8_000_000, 0, 0, 0, 0, 0, 0]


def test_warmup_and_sparse_reads_report_real_pair_span(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """A delayed pair uses its real span instead of the configured poll interval."""
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
def test_reset_discards_pair_and_actual_span(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
    reset: str,
) -> None:
    """Rates keep existing counter reset and failure ownership."""
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


def test_duplicate_clock_has_no_rate_and_only_two_samples_are_retained(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_counters: WanCounters,
) -> None:
    """Nonpositive elapsed time is never divided; retained samples stay finite."""
    now = [0.0]
    hub = _hub(hass, mock_speedport_client, now)
    for _ in range(2):
        data = hub._normalise_wan_counters(wan_counters)
        assert data["download_rate_bps"] is None
    for second in range(1, 100):
        now[0] = float(second)
        hub._normalise_wan_counters(wan_counters)
    assert hub.wan_counter_telemetry["rate_method"] == "consecutive_samples"
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] == 1
    assert len(hub._counter_samples) == 2
    data = hub._normalise_wan_counters(wan_counters)
    assert data["download_rate_bps"] is None
    assert hub.wan_counter_telemetry["rate_sample_span_seconds"] is None
