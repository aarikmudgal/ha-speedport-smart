"""Fail-closed identity proofs for mutable router records."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Final

from .const import DEVICE_NAME_MAX_LENGTH, DEVICE_NAME_PATTERN

_PORT_FORWARD_IDENTITY_KEYS: Final = frozenset(
    {
        "id",
        "name",
        "portuw_id",
        "portuw_name",
        "rule_id",
        "rule_name",
    }
)
_PORT_FORWARD_ACTIVE_KEYS: Final = frozenset({"active", "enabled", "portuw_active"})
_SECRET_TOKENS: Final = (
    "credential",
    "imei",
    "imsi",
    "password",
    "passwd",
    "private_key",
    "psk",
    "puk",
    "secret",
    "sip_auth",
    "sip_password",
    "token",
    "wireguard_key",
    "wlan_key",
    "wpa_key",
)
_INVALID: Final = object()
_MISSING: Final = object()
_DEVICE_NAME_PATTERN: Final = re.compile(DEVICE_NAME_PATTERN)


def valid_device_name(value: Any) -> bool:
    """Return whether a router name satisfies the writable text contract."""
    return (
        isinstance(value, str)
        and 1 <= len(value) <= DEVICE_NAME_MAX_LENGTH
        and _DEVICE_NAME_PATTERN.fullmatch(value) is not None
    )


def port_forward_rule_fingerprint(record: Mapping[str, Any]) -> str | None:
    """Hash stable non-state rule fields, requiring a second discriminator."""
    canonical: dict[str, Any] = {}
    excluded = _PORT_FORWARD_IDENTITY_KEYS | _PORT_FORWARD_ACTIVE_KEYS
    for raw_key, value in record.items():
        key = str(raw_key).strip().casefold()
        if not key or key in excluded or _secret_key(key):
            continue
        if key in canonical:
            return None
        normalized = _canonical_value(value)
        if normalized is _INVALID:
            return None
        if normalized is not _MISSING:
            canonical[key] = normalized
    if not canonical:
        return None
    serialized = json.dumps(
        canonical,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode()).hexdigest()


def _canonical_value(value: Any) -> Any:
    """Return deterministic JSON data without inventing unsupported values."""
    if value is None:
        return _MISSING
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or _MISSING
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _INVALID
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, nested_value in value.items():
            key = str(raw_key).strip().casefold()
            if not key or key in normalized or _secret_key(key):
                return _INVALID
            item = _canonical_value(nested_value)
            if item is _INVALID:
                return _INVALID
            if item is not _MISSING:
                normalized[key] = item
        return normalized or _MISSING
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        normalized_items: list[Any] = []
        for nested_value in value:
            item = _canonical_value(nested_value)
            if item is _INVALID:
                return _INVALID
            if item is not _MISSING:
                normalized_items.append(item)
        return normalized_items or _MISSING
    return _INVALID


def _secret_key(key: str) -> bool:
    """Return whether a field must not contribute to an identity proof."""
    normalized = key.strip().casefold()
    return any(token in normalized for token in _SECRET_TOKENS)
