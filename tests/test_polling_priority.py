"""Prove serialized priorities and expiring panel focus without router I/O."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from custom_components.speedport_smart.polling_priority import (
    FOCUS_LEASE_SECONDS,
    OperationKind,
    PanelFocus,
    PollingPriorityGate,
    PollingPriorityGateClosed,
)


@dataclass
class _Timer:
    when: float
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class _ClockLoop:
    """Advance only gate timers, keeping task execution on the real loop."""

    def __init__(self) -> None:
        self.now = 100.0
        self.timers: list[_Timer] = []
        self.loop = MagicMock(spec=asyncio.AbstractEventLoop)
        self.loop.time.side_effect = lambda: self.now
        self.loop.create_future.side_effect = lambda: (
            asyncio.get_running_loop().create_future()
        )
        self.loop.call_later.side_effect = self.call_later

    def call_later(self, delay: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(self.now + delay, callback)
        self.timers.append(timer)
        return timer

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for timer in tuple(self.timers):
            if not timer.cancelled and timer.when <= self.now:
                timer.cancelled = True
                timer.callback()


async def _record(
    gate: PollingPriorityGate,
    kind: OperationKind,
    label: str,
    order: list[str],
) -> None:
    async with gate.hold(kind):
        order.append(label)
        await asyncio.sleep(0)


@pytest.mark.parametrize(
    ("focus", "expected"),
    [
        (None, ["wan1", "wan2", "admin1", "admin2", "telemetry"]),
        ("dashboard", ["wan1", "wan2", "admin1", "admin2", "telemetry"]),
        ("administration", ["admin1", "admin2", "wan1", "wan2", "telemetry"]),
    ],
)
async def test_priorities_and_fifo_under_an_active_owner(
    focus: PanelFocus | None, expected: list[str]
) -> None:
    """Only the next grant changes priority; ties retain enqueue order."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    owner = object()
    if focus is not None:
        gate.set_focus(owner, focus)
    await gate.acquire()
    order: list[str] = []
    work: list[tuple[OperationKind, str]] = [
        ("telemetry", "telemetry"),
        ("administration", "admin1"),
        ("wan", "wan1"),
        ("administration", "admin2"),
        ("wan", "wan2"),
    ]
    tasks = [
        asyncio.create_task(_record(gate, kind, label, order)) for kind, label in work
    ]
    await asyncio.sleep(0)
    assert order == []
    gate.release()
    await asyncio.wait_for(asyncio.gather(*tasks[1:]), timeout=1)
    if focus is not None:
        assert not tasks[0].done()
        assert order == expected[:-1]
        assert gate.background_deferred
        gate.clear_focus(owner)
    await asyncio.wait_for(tasks[0], timeout=1)
    assert order == expected
    assert not gate.locked()
    gate.close()


async def test_focus_switch_reorders_waiters_without_preempting_owner() -> None:
    """An Administration claim changes only future ownership decisions."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    owner = object()
    gate.set_focus(owner, "dashboard")
    await gate.acquire("wan")
    order: list[str] = []
    tasks = [
        asyncio.create_task(_record(gate, "wan", "wan", order)),
        asyncio.create_task(_record(gate, "administration", "admin", order)),
    ]
    await asyncio.sleep(0)
    gate.set_focus(owner, "administration")
    await asyncio.sleep(0)
    assert order == []
    assert gate.locked()
    gate.release()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    assert order == ["admin", "wan"]
    gate.close()


async def test_expiry_wakes_deferred_work_without_another_poll() -> None:
    """The lease timer itself releases deferred telemetry at exactly 45s."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    gate.set_focus(object(), "dashboard")
    order: list[str] = []
    task = asyncio.create_task(_record(gate, "telemetry", "telemetry", order))
    await asyncio.sleep(0)
    clock.advance(FOCUS_LEASE_SECONDS - 0.001)
    await asyncio.sleep(0)
    assert not task.done()
    assert not gate.locked()
    clock.advance(0.001)
    await asyncio.wait_for(task, timeout=1)
    assert gate.focus == "background"
    assert not gate.background_deferred
    assert order == ["telemetry"]
    gate.close()


async def test_renewal_extends_ttl_without_stealing_latest_tab_focus() -> None:
    """An older tab can remain leased without becoming the selected panel."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    dashboard, administration = object(), object()
    gate.set_focus(dashboard, "dashboard")
    clock.advance(10)
    gate.set_focus(administration, "administration")
    clock.advance(10)
    assert gate.renew_focus(dashboard)
    assert gate.focus == "administration"
    clock.advance(35)
    assert gate.focus == "dashboard"
    assert not gate.renew_focus(administration)
    clock.advance(10)
    assert gate.focus == "background"
    assert not gate.renew_focus(dashboard)
    gate.close()


async def test_stale_heartbeat_cannot_revive_a_lease_before_timer_runs() -> None:
    """A late heartbeat also expires stale focus when loop timers are delayed."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    owner = object()
    gate.set_focus(owner, "dashboard")
    task = asyncio.create_task(gate.acquire("telemetry"))
    await asyncio.sleep(0)
    clock.now += FOCUS_LEASE_SECONDS
    assert not gate.renew_focus(owner)
    assert await asyncio.wait_for(task, timeout=1)
    assert gate.focus == "background"
    gate.release()
    gate.close()


async def test_owner_identity_and_clear_preserve_other_tab_claim() -> None:
    """Equal unhashable owners remain independent connection identities."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    first: list[object] = []
    second: list[object] = []
    gate.set_focus(first, "dashboard")
    gate.set_focus(second, "administration")
    gate.clear_focus(first)
    assert gate.focus == "administration"
    assert not gate.renew_focus(first)
    gate.clear_focus(second)
    gate.clear_focus(second)
    assert gate.focus == "background"
    gate.close()


async def test_new_claim_changes_recency_but_unknown_renewal_cannot_claim() -> None:
    """Only explicit claims select another tab, never a heartbeat."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    first, second = object(), object()
    assert not gate.renew_focus(first)
    gate.set_focus(first, "dashboard")
    gate.set_focus(second, "administration")
    gate.set_focus(first, "dashboard")
    assert gate.focus == "dashboard"
    assert gate.renew_focus(second)
    assert gate.focus == "dashboard"
    gate.clear_focus(first)
    assert gate.focus == "administration"
    gate.close()


async def test_cancelled_waiter_does_not_strand_other_priorities() -> None:
    """A cancelled high-priority waiter cannot block the next live waiter."""
    gate = PollingPriorityGate(asyncio.get_running_loop())
    await gate.acquire()
    cancelled = asyncio.create_task(gate.acquire("wan"))
    successor = asyncio.create_task(gate.acquire("telemetry"))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert gate.locked()
    gate.release()
    assert await asyncio.wait_for(successor, timeout=1)
    gate.release()
    assert not gate.locked()
    gate.close()


async def test_cancellation_after_grant_transfers_reserved_ownership() -> None:
    """Cancellation between grant and coroutine resumption releases the gate."""
    gate = PollingPriorityGate(asyncio.get_running_loop())
    await gate.acquire()
    cancelled = asyncio.create_task(gate.acquire("wan"))
    successor = asyncio.create_task(gate.acquire("administration"))
    await asyncio.sleep(0)
    gate.release()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert await asyncio.wait_for(successor, timeout=1)
    gate.release()
    assert not gate.locked()
    gate.close()


async def test_cancelling_focus_deferred_work_does_not_claim_ownership() -> None:
    """Cancellation while idle and focused leaves no phantom active owner."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    owner = object()
    gate.set_focus(owner, "dashboard")
    task = asyncio.create_task(gate.acquire("telemetry"))
    await asyncio.sleep(0)
    assert not gate.locked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.clear_focus(owner)
    assert not gate.locked()
    async with gate.hold("wan"):
        assert gate.locked()
    gate.close()


async def test_active_context_cancellation_releases_next_waiter() -> None:
    """Cancellation by the caller still runs context cleanup exactly once."""
    gate = PollingPriorityGate(asyncio.get_running_loop())
    entered = asyncio.Event()

    async def active() -> None:
        async with gate:
            entered.set()
            await asyncio.Event().wait()

    active_task = asyncio.create_task(active())
    await entered.wait()
    successor = asyncio.create_task(gate.acquire("wan"))
    await asyncio.sleep(0)
    active_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active_task
    assert await asyncio.wait_for(successor, timeout=1)
    gate.release()
    gate.close()


async def test_close_rejects_queue_but_does_not_cancel_active_operation() -> None:
    """Shutdown cancels timers and queued work, never the active transaction."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    owner = object()
    gate.set_focus(owner, "dashboard")
    entered, finish = asyncio.Event(), asyncio.Event()

    async def active() -> None:
        async with gate:
            entered.set()
            await finish.wait()

    active_task = asyncio.create_task(active())
    await entered.wait()
    tasks = [
        asyncio.create_task(gate.acquire("wan")),
        asyncio.create_task(gate.acquire("telemetry")),
    ]
    await asyncio.sleep(0)
    gate.close()
    gate.close()
    for task in tasks:
        with pytest.raises(PollingPriorityGateClosed):
            await task
    assert gate.locked()
    assert not active_task.done()
    assert all(timer.cancelled for timer in clock.timers)
    assert gate.focus == "background"
    assert not gate.renew_focus(owner)
    gate.clear_focus(owner)
    with pytest.raises(PollingPriorityGateClosed):
        await gate.acquire()
    with pytest.raises(PollingPriorityGateClosed):
        gate.set_focus(owner, "dashboard")
    finish.set()
    await asyncio.wait_for(active_task, timeout=1)
    assert not gate.locked()


async def test_close_after_grant_prevents_unstarted_operation() -> None:
    """A reservation granted just before shutdown cannot start router work."""
    gate = PollingPriorityGate(asyncio.get_running_loop())
    await gate.acquire()
    task = asyncio.create_task(gate.acquire("wan"))
    await asyncio.sleep(0)
    gate.release()
    gate.close()
    with pytest.raises(PollingPriorityGateClosed):
        await task
    assert not gate.locked()


async def test_expiry_does_not_preempt_an_active_operation() -> None:
    """Expired focus unblocks telemetry only after the current owner exits."""
    clock = _ClockLoop()
    gate = PollingPriorityGate(clock.loop)
    gate.set_focus(object(), "administration")
    await gate.acquire()
    task = asyncio.create_task(gate.acquire("telemetry"))
    await asyncio.sleep(0)
    clock.advance(FOCUS_LEASE_SECONDS)
    await asyncio.sleep(0)
    assert gate.locked()
    assert not task.done()
    gate.release()
    assert await asyncio.wait_for(task, timeout=1)
    gate.release()
    gate.close()


async def test_many_waiters_never_overlap_or_start_as_a_burst() -> None:
    """Each grant remains exclusive even when every queue priority is ready."""
    gate = PollingPriorityGate(asyncio.get_running_loop())
    active = maximum_active = completed = 0

    async def operation(kind: OperationKind) -> None:
        nonlocal active, maximum_active, completed
        async with gate.hold(kind):
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0)
            assert active == 1
            active -= 1
            completed += 1

    kinds: tuple[OperationKind, ...] = ("wan", "administration", "telemetry")
    await asyncio.wait_for(
        asyncio.gather(*(operation(kind) for _ in range(8) for kind in kinds)),
        timeout=1,
    )
    assert maximum_active == 1
    assert completed == 24
    assert not gate.locked()
    gate.close()


async def test_default_context_and_exception_release_are_lock_compatible() -> None:
    """Atomic commands retain ordinary lock context and release semantics."""
    gate = PollingPriorityGate(asyncio.get_running_loop())

    async def failing_operation() -> None:
        async with gate as acquired:
            assert acquired is gate
            assert gate.locked()
            raise ValueError("synthetic")

    with pytest.raises(ValueError, match="synthetic"):
        await failing_operation()
    assert not gate.locked()
    with pytest.raises(RuntimeError, match="not acquired"):
        gate.release()
    gate.close()


async def test_background_gate_does_not_consume_injected_sample_clock() -> None:
    """Unfocused serialization must not perturb existing WAN sample clocks."""
    clock = MagicMock(side_effect=AssertionError("Unexpected sample clock read"))
    gate = PollingPriorityGate(asyncio.get_running_loop(), clock=clock)
    async with gate:
        assert gate.focus == "background"
    async with gate.hold("wan"):
        assert not gate.background_deferred
    gate.close()
    clock.assert_not_called()
