"""Short-lived, single-use approval for the second online phonebook linking step."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from .configuration import ConfigurationError
from .configuration_phonebook_lifecycle import phonebook_inventory
from .phonebook_link import OnlinePhonebookStage, online_phonebook_finish_payload

_TTL: Final = 120.0
_LIMIT: Final = 8
_IDENTITY_PARTS: Final = 2
_MAX_ID: Final = 128
_CONFIRM: Final = {
    True: "MERGE ONLINE PHONEBOOK CONTACTS",
    False: "REPLACE LOCAL PHONEBOOK CONTACTS",
}


@dataclass(frozen=True, slots=True, repr=False)
class _PendingLink:
    stage: OnlinePhonebookStage
    requester: tuple[str, str]
    entry_id: str
    local_fingerprint: str = field(repr=False)
    expires_at: float


class OnlinePhonebookSession:
    """Keep only pending second-step bindings; never passwords or contact rows."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Create ephemeral grants; the hub owner provides locks and admin checks."""
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._grants: dict[str, _PendingLink] = {}

    def clear(self) -> None:
        """Forget every pending approval on unload, session loss or navigation."""
        self._grants.clear()
        self._key = secrets.token_bytes(32)

    def _identity(self, requester: tuple[str, str], entry_id: str) -> None:
        if (
            type(requester) is not tuple
            or len(requester) != _IDENTITY_PARTS
            or any(
                type(value) is not str or not 0 < len(value) <= _MAX_ID
                for value in requester
            )
            or type(entry_id) is not str
            or not 0 < len(entry_id) <= _MAX_ID
        ):
            raise ConfigurationError("administrator_required")

    def _fingerprint(self, local: Mapping[str, Any], book_number: str) -> str:
        entries = phonebook_inventory(local, phonebook_id=int(book_number))
        # The online-link flag intentionally changes in stage one. The stage
        # separately binds exact row ID/number; contact contents must not change.
        data = json.dumps(
            {"entries": entries, "book_number": book_number}, sort_keys=True
        ).encode()
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def issue(
        self,
        stage: OnlinePhonebookStage,
        *,
        requester: tuple[str, str],
        entry_id: str,
        local_inventory: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Issue only after the first credential request has independently returned."""
        self._identity(requester, entry_id)
        if not isinstance(stage, OnlinePhonebookStage):
            raise ConfigurationError("invalid_settings")
        fingerprint = self._fingerprint(local_inventory, stage.book_number)
        self._grants = {
            token: grant
            for token, grant in self._grants.items()
            if grant.expires_at > self._clock() and grant.requester != requester
        }
        if len(self._grants) >= _LIMIT:
            raise ConfigurationError("settings_busy")
        token = secrets.token_hex(24)
        self._grants[token] = _PendingLink(
            stage, requester, entry_id, fingerprint, self._clock() + _TTL
        )
        return {
            "pending_link": token,
            "expires_in": int(_TTL),
            "online_contacts": int(stage.online_count),
            "local_contacts": local_inventory["total"],
            "merge_confirmation": _CONFIRM[True],
            "replace_confirmation": _CONFIRM[False],
            "warning": (
                "Choose explicitly. Replacing removes local contacts. First-step "
                "account authentication does not complete contact synchronization."
            ),
        }

    def context(
        self,
        token: str,
        *,
        requester: tuple[str, str],
        entry_id: str,
    ) -> tuple[str, int]:
        """Validate a pending grant before issuing its bounded fresh read."""
        self._identity(requester, entry_id)
        grant = self._grants.get(token) if type(token) is str else None
        if (
            grant is None
            or grant.requester != requester
            or grant.entry_id != entry_id
            or grant.expires_at <= self._clock()
        ):
            raise ConfigurationError("stale_settings")
        return grant.stage.target_id, int(grant.stage.book_number)

    def consume(
        self,
        token: str,
        *,
        requester: tuple[str, str],
        entry_id: str,
        confirmed: bool,
        confirmation_text: str,
        merge_existing: bool,
        fresh_book: Mapping[str, Any],
        fresh_local_inventory: Mapping[str, Any],
    ) -> dict[str, str | bool]:
        """Consume before returning one fixed payload; the owner may send it once."""
        self._identity(requester, entry_id)
        if type(token) is not str:
            raise ConfigurationError("stale_settings")
        grant = self._grants.get(token)
        if grant is None or grant.requester != requester or grant.entry_id != entry_id:
            raise ConfigurationError("stale_settings")
        del self._grants[token]
        if grant.expires_at <= self._clock():
            raise ConfigurationError("stale_settings")
        if (
            type(merge_existing) is not bool
            or confirmed is not True
            or confirmation_text != _CONFIRM[merge_existing]
        ):
            raise ConfigurationError("confirmation_required")
        if not hmac.compare_digest(
            grant.local_fingerprint,
            self._fingerprint(fresh_local_inventory, grant.stage.book_number),
        ):
            raise ConfigurationError("stale_settings")
        return online_phonebook_finish_payload(
            fresh_book, grant.stage, merge_existing=merge_existing
        )
