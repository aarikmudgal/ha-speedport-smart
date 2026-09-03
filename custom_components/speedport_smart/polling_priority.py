"""Serialize router work with expiring, panel-aware polling priorities."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self

if TYPE_CHECKING:
    from types import TracebackType

OperationKind = Literal["wan", "administration", "telemetry"]
PanelFocus = Literal["dashboard", "administration"]
PollingFocus = Literal["dashboard", "administration", "background"]

FOCUS_LEASE_SECONDS = 45.0


class PollingPriorityGateClosed(RuntimeError):  # noqa: N818
    """The integration closed before a queued operation could start."""


@dataclass(slots=True)
class _FocusLease:
    owner: object
    view: PanelFocus
    claimed: int
    expires_at: float


@dataclass(slots=True)
class _Waiter:
    kind: OperationKind
    future: asyncio.Future[None]
    granted: bool = False


class PollingPriorityGate:
    """
    Grant one operation at a time, without preempting its router session.

    Explicit focus claims order tabs; heartbeats renew only their expiry. While
    any focus lease remains, automatic telemetry waits. Active work is never
    cancelled by the gate, including when focus changes or the gate closes.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Create a gate using the owning loop and a monotonic clock."""
        self._loop = loop
        self._clock = clock or loop.time
        self._locked = False
        self._closed = False
        self._waiters: list[_Waiter] = []
        self._leases: dict[int, _FocusLease] = {}
        self._claim_sequence = 0
        self._expiry_handle: asyncio.TimerHandle | None = None
        self._expiry_at: float | None = None

    @property
    def focus(self) -> PollingFocus:
        """Return the latest unexpired explicit panel claim."""
        self._wake_next()
        return self._active_focus()

    @property
    def background_deferred(self) -> bool:
        """Whether automatic telemetry is waiting for panel focus to end."""
        return self.focus != "background"

    def set_focus(self, owner: object, view: PanelFocus) -> None:
        """Make a new explicit claim; unlike renewal, this changes recency."""
        self._ensure_open()
        if view not in ("dashboard", "administration"):
            raise ValueError(f"Unknown panel focus: {view}")
        self._claim_sequence += 1
        self._leases[id(owner)] = _FocusLease(
            owner, view, self._claim_sequence, self._clock() + FOCUS_LEASE_SECONDS
        )
        self._wake_next()

    def renew_focus(self, owner: object) -> bool:
        """Extend a live claim without moving it ahead of other tabs."""
        self._refresh_leases()
        lease = self._leases.get(id(owner))
        if self._closed or lease is None or lease.owner is not owner:
            self._wake_next()
            return False
        lease.expires_at = self._clock() + FOCUS_LEASE_SECONDS
        self._wake_next()
        return True

    def clear_focus(self, owner: object) -> None:
        """Release this owner's claim without affecting another tab."""
        lease = self._leases.get(id(owner))
        if lease is not None and lease.owner is owner:
            del self._leases[id(owner)]
        self._wake_next()

    def locked(self) -> bool:
        """Return whether one operation currently owns the gate."""
        return self._locked

    async def acquire(self, kind: OperationKind = "administration") -> bool:
        """Wait for ownership using FIFO order within the current priority."""
        self._ensure_open()
        if kind not in ("wan", "administration", "telemetry"):
            raise ValueError(f"Unknown operation kind: {kind}")
        waiter = _Waiter(kind, self._loop.create_future())
        self._waiters.append(waiter)
        self._wake_next()
        try:
            await waiter.future
        except BaseException:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            if waiter.granted:
                self._locked = False
            self._wake_next()
            raise
        if self._closed:
            self.release()
            raise PollingPriorityGateClosed("Polling priority gate is closed")
        return True

    def release(self) -> None:
        """End the active operation and grant at most one eligible waiter."""
        if not self._locked:
            raise RuntimeError("Polling priority gate is not acquired")
        self._locked = False
        self._wake_next()

    async def __aenter__(self) -> Self:
        """Keep existing atomic command contexts at administration priority."""
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release ownership after completion, failure, or cancellation."""
        self.release()

    @asynccontextmanager
    async def hold(self, kind: OperationKind) -> AsyncIterator[None]:
        """Run one complete operation under its polling priority."""
        await self.acquire(kind)
        try:
            yield
        finally:
            self.release()

    def close(self) -> None:
        """Reject queued work and expire focus, leaving the owner untouched."""
        self._closed = True
        self._leases.clear()
        if self._expiry_handle is not None:
            self._expiry_handle.cancel()
            self._expiry_handle = None
        self._expiry_at = None
        for waiter in self._waiters:
            if not waiter.future.done():
                waiter.future.set_exception(
                    PollingPriorityGateClosed("Polling priority gate is closed")
                )
        self._waiters.clear()

    def _ensure_open(self) -> None:
        if self._closed:
            raise PollingPriorityGateClosed("Polling priority gate is closed")

    def _active_focus(self) -> PollingFocus:
        if not self._leases:
            return "background"
        return max(self._leases.values(), key=lambda lease: lease.claimed).view

    def _refresh_leases(self) -> None:
        now = self._clock() if self._leases else 0.0
        for owner_id, lease in tuple(self._leases.items()):
            if lease.expires_at <= now:
                del self._leases[owner_id]
        expires_at = min(
            (lease.expires_at for lease in self._leases.values()), default=None
        )
        if expires_at == self._expiry_at:
            return
        if self._expiry_handle is not None:
            self._expiry_handle.cancel()
            self._expiry_handle = None
        self._expiry_at = expires_at
        if expires_at is not None:
            self._expiry_handle = self._loop.call_later(
                max(0.0, expires_at - now), self._on_expiry
            )

    def _on_expiry(self) -> None:
        self._expiry_handle = None
        self._expiry_at = None
        self._wake_next()

    def _wake_next(self) -> None:
        self._refresh_leases()
        if self._locked or self._closed:
            return
        focus = self._active_focus()
        priorities: tuple[OperationKind, ...] = (
            ("administration", "wan")
            if focus == "administration"
            else ("wan", "administration")
        )
        if focus == "background":
            priorities += ("telemetry",)
        self._waiters = [waiter for waiter in self._waiters if not waiter.future.done()]
        for kind in priorities:
            for index, waiter in enumerate(self._waiters):
                if waiter.kind == kind:
                    del self._waiters[index]
                    self._locked = True
                    waiter.granted = True
                    waiter.future.set_result(None)
                    return
