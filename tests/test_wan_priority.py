"""WAN priority at completed, session-free NORMAL polling boundaries."""

# Inspect ownership and deadlines only to prove that no router operations overlap.
# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportSessionBusyError
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def _hub(
    hass: HomeAssistant, client: MagicMock, now: list[float]
) -> tuple[SpeedportHub, MagicMock]:
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="synthetic",
        wan_counter_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    hub._public_status_next_poll_at = float("inf")
    hub._capabilities |= {"dsl", "tr064"}
    coordinator = MagicMock()
    coordinator.update_interval = timedelta(seconds=1)
    hub.attach_coordinator(PollGroup.FAST, coordinator)
    return hub, coordinator


async def test_due_wan_publishes_after_logout_before_dsl_without_queued_duplicate(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """A completed protected cycle yields a WAN sample before the DSL tail."""
    now = [100.0]
    hub, coordinator = await _hub(hass, mock_speedport_client, now)
    json_entered, json_release = asyncio.Event(), asyncio.Event()
    logout_entered, logout_release = asyncio.Event(), asyncio.Event()
    dsl_entered, dsl_release = asyncio.Event(), asyncio.Event()
    order: list[str] = []
    dsl_metrics = mock_speedport_client.get_dsl_metrics.return_value
    counters = mock_speedport_client.get_wan_counters.return_value

    async def read_json(*_args: object, **_kwargs: object) -> dict[str, bool]:
        order.append("protected")
        json_entered.set()
        await json_release.wait()
        return {"use_wlan": True}

    async def logout() -> None:
        order.append("logout")
        logout_entered.set()
        await logout_release.wait()
        order.append("settled")

    async def read_wan(**_kwargs: object) -> object:
        assert hub._operation_lock.locked()
        assert order[-1] == "settled"
        order.append("wan")
        return counters

    async def read_dsl(**kwargs: object) -> object:
        assert kwargs == {"busy_retries": 0}
        assert hub._operation_lock.locked()
        assert coordinator.async_set_updated_data.call_count == 1
        order.append("dsl")
        dsl_entered.set()
        await dsl_release.wait()
        return dsl_metrics

    mock_speedport_client.get_json.side_effect = read_json
    mock_speedport_client.logout.side_effect = logout
    mock_speedport_client.get_wan_counters.side_effect = read_wan
    mock_speedport_client.get_dsl_metrics.side_effect = read_dsl
    normal = asyncio.create_task(hub.async_update_group(PollGroup.NORMAL))
    fast = None
    try:
        async with asyncio.timeout(3):
            await json_entered.wait()
            mock_speedport_client.get_wan_counters.assert_not_awaited()
            json_release.set()
            await logout_entered.wait()
            fast = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
            await asyncio.sleep(0)
            mock_speedport_client.get_wan_counters.assert_not_awaited()
            now[0] = 102.0
            logout_release.set()
            await dsl_entered.wait()
            snapshot = coordinator.async_set_updated_data.call_args.args[0]
            assert snapshot.group is PollGroup.FAST
            assert snapshot.data["wan"]["bytes_received"] == counters.bytes_received
            assert not normal.done()
            assert not fast.done()
            assert hub._wan_counter_next_poll_at == 103.0
            dsl_release.set()
            normal_snapshot, fast_snapshot = await asyncio.gather(normal, fast)
    finally:
        json_release.set()
        logout_release.set()
        dsl_release.set()
        await normal
        if fast is not None:
            await fast
    assert order == ["protected", "logout", "settled", "wan", "dsl"]
    mock_speedport_client.get_wan_counters.assert_awaited_once_with(busy_retries=0)
    mock_speedport_client.logout.assert_awaited_once()
    mock_speedport_client.get_json.assert_awaited_once()
    mock_speedport_client.get_status.assert_not_awaited()
    assert normal_snapshot.data["wifi"]["enabled"] is True
    assert fast_snapshot.data["wifi"]["enabled"] is True
    assert fast_snapshot.data["wan"]["bytes_received"] == counters.bytes_received
    assert "dsl_read_ms" in hub._poll_timing_ms[PollGroup.NORMAL]


@pytest.mark.parametrize("reason", ["not_due", "cooldown", "no_listener"])
async def test_checkpoint_never_forces_an_extra_wan_read(
    hass: HomeAssistant, mock_speedport_client: MagicMock, reason: str
) -> None:
    """The normal checkpoint obeys the existing source schedule and cooldown."""
    hub, coordinator = await _hub(hass, mock_speedport_client, [100.0])
    if reason == "not_due":
        hub._wan_counter_next_poll_at = 101.0
    elif reason == "cooldown":
        hub._wan_counter_retry_at = 160.0
    else:
        hub._coordinators.clear()
    await hub.async_update_group(PollGroup.NORMAL)
    mock_speedport_client.get_wan_counters.assert_not_awaited()
    coordinator.async_set_updated_data.assert_not_called()


async def test_busy_dsl_defers_without_holding_the_wan_lock_for_retries(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Scheduled DSL uses one attempt; the hub retains its delayed-retry policy."""
    hub, coordinator = await _hub(hass, mock_speedport_client, [100.0])
    mock_speedport_client.get_dsl_metrics.side_effect = SpeedportSessionBusyError(
        "synthetic busy response"
    )
    await hub.async_update_group(PollGroup.NORMAL)
    mock_speedport_client.get_dsl_metrics.assert_awaited_once_with(busy_retries=0)
    assert hub._dsl_metrics_retry_at == 105.0
    assert not hub._operation_lock.locked()
    assert coordinator.async_set_updated_data.call_count == 1
    assert hub.get("wan.bytes_received") is not None


async def test_private_verification_keeps_its_atomic_flow_without_checkpoint(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Only ordinary polling opts in to the intermediate WAN publication."""
    hub, coordinator = await _hub(hass, mock_speedport_client, [100.0])
    async with hub._operation_lock:
        await hub._async_update_group_locked(PollGroup.NORMAL)
    mock_speedport_client.get_wan_counters.assert_not_awaited()
    mock_speedport_client.get_dsl_metrics.assert_awaited_once_with(busy_retries=None)
    coordinator.async_set_updated_data.assert_not_called()


async def test_poll_diagnostics_include_time_waiting_for_another_operation(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """The queue delay is separate from router work, not silently omitted."""
    now = [100.0]
    hub, _coordinator = await _hub(hass, mock_speedport_client, now)
    await hub._operation_lock.acquire()
    with patch(
        "custom_components.speedport_smart.hub.time.perf_counter", lambda: now[0]
    ):
        task = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
        await asyncio.sleep(0)
        now[0] += 2
        hub._operation_lock.release()
        await task
    timing = hub.diagnostics()["polling"]["fast"]
    assert timing["lock_wait_ms"] == 2000.0
    assert timing["router_work_ms"] == 0.0
    assert timing["total_update_ms"] == 2000.0
