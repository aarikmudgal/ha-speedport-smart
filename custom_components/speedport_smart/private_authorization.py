"""Request-scoped live authorization at private router mutation boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class PrivateAuthorizationError(PermissionError):
    """Report revoked authorization without retaining private callback errors."""

    def __init__(self) -> None:
        """Expose only a fixed, value-free message."""
        super().__init__("Administrator authorization is no longer current")


class _Scope:
    """Share scope expiration with child tasks without retaining completed requests."""

    def __init__(self, checker: Callable[[], None], parent: _Scope | None) -> None:
        self.checker: Callable[[], None] | None = checker
        self.parent = parent
        self.active = True

    def check(self) -> None:
        if not self.active or self.checker is None:
            raise PrivateAuthorizationError
        if self.parent is not None:
            self.parent.check()
        try:
            result = self.checker()
        except Exception:  # noqa: BLE001 - callback details may contain private values
            raise PrivateAuthorizationError from None
        if result is not None:
            raise PrivateAuthorizationError

    def close(self) -> None:
        self.active = False
        self.checker = None
        self.parent = None


_CURRENT: ContextVar[_Scope | None] = ContextVar(
    "speedport_private_authorization", default=None
)


@contextmanager
def private_authorization(checker: Callable[[], None]) -> Iterator[None]:
    """Bind one request; nested scopes cannot weaken an outer authorization gate."""
    scope = _Scope(checker, _CURRENT.get())
    token = _CURRENT.set(scope)
    try:
        yield
    finally:
        # A task that inherited this scope must not write after its request ends.
        scope.close()
        _CURRENT.reset(token)


def check_private_authorization() -> None:
    """Recheck before private sends; leave ordinary unscoped work unchanged."""
    scope = _CURRENT.get()
    if scope is not None:
        scope.check()


@contextmanager
def autonomous_ha_context() -> Iterator[None]:
    """
    Detach only our scope for trusted HA publication and autonomous scheduling.

    This is not a write-authorization bypass for private requests. It is used
    only for coordinator publication/poll scheduling and proven credential
    persistence that schedules an independent integration reload, never around
    a private router transaction or router I/O.
    Other Home Assistant context variables and the caller's scope are preserved.
    """
    token = _CURRENT.set(None)
    try:
        yield
    finally:
        _CURRENT.reset(token)
