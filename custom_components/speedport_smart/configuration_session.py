"""One-shot, administrator-bound optimistic configuration transactions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .api.exceptions import SpeedportCommandRejectedError, SpeedportError
from .configuration import ConfigurationError, SettingsContract

_TTL = 120.0
_MAX_GRANTS = 32
_REQUESTER_PARTS = 2
_REQUESTER_MAX_LENGTH = 128


@dataclass(frozen=True, slots=True)
class _Grant:
    setting_id: str
    target_scope: str | None
    requester: tuple[str, str]
    fingerprint: str
    expires_at: float


class ConfigurationSession:
    """Store only bounded, short-lived revisions; never router settings/secrets."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Initialize an in-memory signing key and bounded revision map."""
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._grants: dict[str, _Grant] = {}
        self._next_read_at = 0.0
        self._generation = 0

    def clear(self) -> None:
        """Invalidate every outstanding editor on unload."""
        self._grants.clear()
        self._key = secrets.token_bytes(32)
        self._generation += 1
        self._next_read_at = 0.0

    def _fingerprint(self, values: Mapping[str, Any]) -> str:
        encoded = json.dumps(values, sort_keys=True, ensure_ascii=True).encode()
        return hmac.new(self._key, encoded, hashlib.sha256).hexdigest()

    def _prune(self) -> None:
        now = self._clock()
        self._grants = {
            key: grant for key, grant in self._grants.items() if grant.expires_at > now
        }

    async def read(
        self,
        contract: SettingsContract,
        requester: tuple[str, str],
        read: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Issue a value-free revision after a successful complete typed read."""
        if len(requester) != _REQUESTER_PARTS or not all(
            isinstance(part, str) and 0 < len(part) <= _REQUESTER_MAX_LENGTH
            for part in requester
        ):
            raise ConfigurationError("administrator_required")
        self._prune()
        if self._clock() < self._next_read_at:
            raise ConfigurationError("rate_limited")
        self._next_read_at = self._clock() + 1.0
        generation = self._generation
        raw = await read()
        if generation != self._generation:
            raise ConfigurationError("stale_settings")
        values = contract.read(raw)
        self._grants = {
            key: grant
            for key, grant in self._grants.items()
            if (grant.setting_id, grant.requester) != (contract.id, requester)
        }
        if len(self._grants) >= _MAX_GRANTS:
            raise ConfigurationError("too_many_editors")
        revision = secrets.token_hex(24)
        self._grants[revision] = _Grant(
            contract.id,
            contract.target_scope,
            requester,
            self._fingerprint(contract.revision(raw)),
            self._clock() + _TTL,
        )
        return {
            "setting_id": contract.id,
            "revision": revision,
            "values": values,
            "expires_in": int(_TTL),
            **({"choices": contract.choices(raw)} if contract.field_choices else {}),
        }

    async def consume(
        self,
        contract: SettingsContract,
        requester: tuple[str, str],
        revision: str,
        changes: Mapping[str, Any],
        *,
        confirmed: bool,
        confirmation_text: str,
        read: Callable[[], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Consume one exact approval and privately return its freshly checked state."""
        if confirmed is not True or confirmation_text != contract.confirmation:
            raise ConfigurationError("confirmation_required")
        self._prune()
        grant = self._grants.get(revision)
        if (
            grant is None
            or grant.setting_id != contract.id
            or grant.target_scope != contract.target_scope
            or grant.requester != requester
        ):
            raise ConfigurationError("stale_settings")
        # Consume before any I/O. An uncertain response must not be replayed.
        del self._grants[revision]
        generation = self._generation
        # Own the approved primitive draft before awaiting the fresh read.
        owned_changes = deepcopy(dict(changes))
        raw = await read()
        if generation != self._generation or self._clock() >= grant.expires_at:
            raise ConfigurationError("stale_settings")
        before = contract.read(raw)
        if not hmac.compare_digest(
            grant.fingerprint, self._fingerprint(contract.revision(raw))
        ):
            raise ConfigurationError("stale_settings")
        return raw, before, owned_changes

    async def save(
        self,
        contract: SettingsContract,
        requester: tuple[str, str],
        revision: str,
        changes: Mapping[str, Any],
        *,
        confirmed: bool,
        confirmation_text: str,
        read: Callable[[], Awaitable[dict[str, Any]]],
        write: Callable[[Mapping[str, Any], Mapping[str, Any]], Awaitable[Any]],
        readback: Callable[[Mapping[str, Any], Any], Awaitable[dict[str, Any]]]
        | None = None,
        on_verified: Callable[
            [Mapping[str, Any], Mapping[str, Any], Any, Mapping[str, Any]],
            dict[str, Any],
        ]
        | None = None,
    ) -> dict[str, Any]:
        """Compare current state, send once, then verify without replaying writes."""
        generation = self._generation
        raw, before, changes = await self.consume(
            contract,
            requester,
            revision,
            changes,
            confirmed=confirmed,
            confirmation_text=confirmation_text,
            read=read,
        )
        payload = contract.build(raw, changes)
        fields = {item.name: item for item in contract.fields}
        expected = {
            **before,
            **{
                key: fields[key].validate(value)
                for key, value in changes.items()
                if fields[key].kind != "secret"
            },
        }
        # Reviewed forms can derive secondary values such as channel direction
        # or password-display state. Verify the actual payload, not merely the
        # explicitly edited fields. Omitted inactive fields remain unchanged.
        if contract.expected_values is None:
            for item in contract.fields:
                if item.kind != "secret" and item.name in payload:
                    expected[item.name] = item.read(
                        {item.read_key or item.name: payload[item.name]}
                    )
        if contract.expected_values is not None:
            expected = contract.expected_values(raw, changes)
            if set(expected) != set(before):
                raise ConfigurationError("invalid_contract_payload")
            for name, value in expected.items():
                expected[name] = fields[name].validate(value)
        payload.clear()
        secret_changed = any(fields[key].kind == "secret" for key in changes)
        if expected == before and not secret_changed:
            return {"status": "unchanged"}
        try:
            response = await write(raw, changes)
        except SpeedportCommandRejectedError:
            raise ConfigurationError("command_rejected") from None
        except SpeedportError:
            raise ConfigurationError("action_outcome_unknown") from None
        if generation != self._generation:
            raise ConfigurationError("action_outcome_unknown")
        if contract.readback_policy == "manual_required":
            return {"status": "outcome_unknown", "verification": "manual_required"}
        if contract.readback_policy == "reconnect_required":
            # Acknowledgement is not proof that the new address/protocol works.
            if contract.acknowledgement == "readback":
                return {
                    "status": "outcome_unknown",
                    "verification": "reconnect_required",
                }
            return {"status": "reconnect_required"}
        for delay in (0.0, 0.5, 1.0, 2.0):
            if delay:
                await asyncio.sleep(delay)
            if generation != self._generation:
                raise ConfigurationError("action_outcome_unknown")
            try:
                after_raw = await readback(raw, response) if readback else await read()
                after = (
                    {} if contract.verifier_owns_fields else contract.read(after_raw)
                )
                verified = (contract.verifier_owns_fields or after == expected) and (
                    contract.verifier is None
                    or contract.verifier(raw, changes, after_raw)
                )
            except ConfigurationError as error:
                if error.code == "action_outcome_unknown":
                    raise
                continue
            except SpeedportError:
                continue
            if generation != self._generation:
                raise ConfigurationError("action_outcome_unknown")
            if verified:
                if on_verified is not None:
                    # A reviewed private result (for example a new VPN key) is
                    # returned only to this requester after full readback. It
                    # never enters the grants, entity state or diagnostics.
                    return on_verified(raw, changes, response, after_raw)
                return {"status": "secret_unverified" if secret_changed else "verified"}
        raise ConfigurationError("action_verification_failed")
