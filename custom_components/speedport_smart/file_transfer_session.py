"""Short-lived, requester-bound file approvals; no files or passwords are stored."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from .file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
    validate_upload_descriptor,
)

_TTL: Final = 120.0
_MAX_GRANTS: Final = 8
_MAX_ID: Final = 128
_IDENTITY_PARTS: Final = 2
_GRANT: Final = re.compile(r"[0-9a-f]{48}")


@dataclass(frozen=True, slots=True, repr=False)
class FileTransferGrant:
    """An immutable consumed approval; identity/digest never appear in repr."""

    action: str
    requester: tuple[str, str]
    entry_id: str
    size: int
    sha256: str | None
    confirmation_text: str
    expires_at: float
    generation: int


class FileTransferSession:
    """Issue and consume bounded one-shot grants within one loaded router hub."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Keep only approvals, never file contents, names or backup passwords."""
        self._clock = clock
        self._generation = 0
        self._grants: dict[str, FileTransferGrant] = {}

    def clear(self) -> None:
        """Invalidate issued and in-flight approvals on unload or protected failure."""
        self._generation += 1
        self._grants.clear()

    def _prune(self) -> None:
        now = self._clock()
        self._grants = {
            token: grant
            for token, grant in self._grants.items()
            if grant.expires_at > now
        }

    @staticmethod
    def _identity(requester: object, entry_id: object) -> None:
        if (
            type(requester) is not tuple
            or len(requester) != _IDENTITY_PARTS
            or any(
                type(part) is not str or not 0 < len(part) <= _MAX_ID
                for part in requester
            )
            or type(entry_id) is not str
            or not 0 < len(entry_id) <= _MAX_ID
        ):
            raise FileTransferError

    def prepare(
        self,
        action: str,
        *,
        requester: tuple[str, str],
        entry_id: str,
        size: object,
        sha256: object,
        confirmed: object,
        confirmation_text: object,
    ) -> dict[str, Any]:
        """Bind the explicit review to one user's current HA login and exact file."""
        self._identity(requester, entry_id)
        if type(action) is not str or action not in FILE_TRANSFER_CONTRACTS:
            raise FileTransferError
        contract = FILE_TRANSFER_CONTRACTS[action]
        if type(size) is not int:
            raise FileTransferError("invalid_transfer_file")
        if confirmed is not True or confirmation_text != contract.confirmation:
            raise FileTransferError("confirmation_required")
        if contract.file_field:
            validate_upload_descriptor(action, size=size, sha256=sha256)
        elif type(size) is not int or size != 0 or sha256 is not None:
            raise FileTransferError("invalid_transfer_file")
        self._prune()
        self._grants = {
            token: grant
            for token, grant in self._grants.items()
            if grant.requester != requester
        }
        if len(self._grants) >= _MAX_GRANTS:
            raise FileTransferError
        token = secrets.token_hex(24)
        self._grants[token] = FileTransferGrant(
            action,
            requester,
            entry_id,
            size,
            str(sha256) if sha256 is not None else None,
            contract.confirmation,
            self._clock() + _TTL,
            self._generation,
        )
        return {"action": action, "grant": token, "expires_in": int(_TTL)}

    def consume(
        self,
        token: object,
        *,
        action: object,
        requester: tuple[str, str],
        entry_id: str,
    ) -> FileTransferGrant:
        """Consume before file-body processing; never permit retry after ambiguity."""
        self._identity(requester, entry_id)
        self._prune()
        if type(token) is not str or _GRANT.fullmatch(token) is None:
            raise FileTransferError
        grant = self._grants.get(token)
        if (
            grant is None
            or grant.action != action
            or grant.requester != requester
            or grant.entry_id != entry_id
        ):
            raise FileTransferError
        del self._grants[token]
        self.check_current(grant)
        return grant

    def check_current(self, grant: FileTransferGrant) -> None:
        """Recheck expiry/invalidation after every wait before the router request."""
        if grant.generation != self._generation or self._clock() >= grant.expires_at:
            raise FileTransferError
