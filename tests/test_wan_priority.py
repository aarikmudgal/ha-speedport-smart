"""WAN priority at completed, session-free NORMAL polling boundaries."""

# Inspect ownership and deadlines only to prove that no router operations overlap.
# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

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


async def test_due_wan_waits_for_normal_sequence_and_runs_once_after_dsl(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """NORMAL never inserts a post-logout WAN request ahead of queued FAST."""
    now = [100.0]
    hub, coordinator = await _hub(hass, mock_speedport_client, now)
    json_entered, json_release = asyncio.Event(), asyncio.Event()
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

    async def read_wan(**_kwargs: object) -> object:
        assert hub._operation_lock.locked()
        assert order[-1] == "dsl_done"
        order.append("wan")
        return counters

    async def read_dsl(**kwargs: object) -> object:
        assert kwargs == {}
        assert hub._operation_lock.locked()
        order.append("dsl")
        dsl_entered.set()
        await dsl_release.wait()
        order.append("dsl_done")
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
            fast = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
            await dsl_entered.wait()
            mock_speedport_client.get_wan_counters.assert_not_awaited()
            now[0] = 102.0
            assert not normal.done()
            assert not fast.done()
            dsl_release.set()
            normal_snapshot, fast_snapshot = await asyncio.gather(normal, fast)
    finally:
        json_release.set()
        dsl_release.set()
        await normal
        if fast is not None:
            await fast
    assert order == ["protected", "logout", "dsl", "dsl_done", "wan"]
    mock_speedport_client.get_wan_counters.assert_awaited_once_with(busy_retries=0)
    mock_speedport_client.logout.assert_awaited_once()
    mock_speedport_client.get_json.assert_awaited_once()
    mock_speedport_client.get_status.assert_not_awaited()
    coordinator.async_set_updated_data.assert_not_called()
    assert normal_snapshot.data["wifi"]["enabled"] is True
    assert fast_snapshot.data["wifi"]["enabled"] is True
    assert fast_snapshot.data["wan"]["bytes_received"] == counters.bytes_received
    assert "dsl_read_ms" in hub._poll_timing_ms[PollGroup.NORMAL]


async def test_exhausted_busy_dsl_defers_without_wan_checkpoint(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """An exhausted DSL retry sequence cannot mutate WAN polling state."""
    hub, coordinator = await _hub(hass, mock_speedport_client, [100.0])
    mock_speedport_client.get_dsl_metrics.side_effect = SpeedportSessionBusyError(
        "synthetic busy response"
    )
    await hub.async_update_group(PollGroup.NORMAL)
    mock_speedport_client.get_dsl_metrics.assert_awaited_once_with()
    assert hub._dsl_metrics_retry_at == 105.0
    assert not hub._operation_lock.locked()
    coordinator.async_set_updated_data.assert_not_called()
    mock_speedport_client.get_wan_counters.assert_not_awaited()


async def test_private_verification_keeps_its_atomic_flow_without_checkpoint(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Private verification keeps the same serialized NORMAL read sequence."""
    hub, coordinator = await _hub(hass, mock_speedport_client, [100.0])
    async with hub._operation_lock:
        await hub._async_update_group_locked(PollGroup.NORMAL)
    mock_speedport_client.get_wan_counters.assert_not_awaited()
    mock_speedport_client.get_dsl_metrics.assert_awaited_once_with()
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
