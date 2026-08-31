"""Protocol exceptions for Speedport Smart routers."""

from __future__ import annotations


class SpeedportError(Exception):
    """Base Speedport protocol error."""


class SpeedportConnectionError(SpeedportError):
    """Router could not be reached or returned transport failure."""


class SpeedportAuthenticationError(SpeedportError):
    """Authenticated router session could not be established or continued."""


class SpeedportInvalidCredentialsError(SpeedportAuthenticationError):
    """Router explicitly rejected the configured device password."""


class SpeedportLoginLockedError(SpeedportAuthenticationError):
    """Router temporarily blocks new management logins."""

    def __init__(self, *, retry_after: int | None = None) -> None:
        """Initialize without exposing router response details."""
        super().__init__("Router login is temporarily locked")
        self.retry_after = retry_after


class SpeedportProtocolError(SpeedportError):
    """Router returned invalid or failed protocol response."""


class SpeedportDecodeError(SpeedportProtocolError):
    """Encrypted or JSON response could not be decoded safely."""


class SpeedportSessionBusyError(SpeedportProtocolError):
    """Router rejected request because another session owns access."""

    def __init__(self, message: str, *, owner: str | None = None) -> None:
        """Initialize with an optional local owner address kept out of the message."""
        super().__init__(message)
        self.owner = owner


class SpeedportUnsupportedError(SpeedportProtocolError):
    """Router does not expose requested endpoint or capability."""
