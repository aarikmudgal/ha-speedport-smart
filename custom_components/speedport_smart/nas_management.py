"""
Pure, fail-closed contracts for editing an existing NAS share.

This module performs no I/O and retains no credentials globally. Callers must
obtain a fresh exact row, authenticate/confirm the action, and send at most once.
Firmware bounds must be supplied for editable fields. A missing folder bound
allows preserving an existing path, but never editing that path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

NAS_SHARE_ENDPOINT: Final = "data/NASFolder.json"
NAS_SHARE_REFERER: Final = "html/content/network/nas_share.html"
# The saved NAS callback does not inspect a success status. Never infer success
# from HTTP 200 or an unreviewed generic ACK; independent readback is mandatory.
NAS_SHARE_SUCCESS_ACK_PROVEN: Final = False
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_USER: Final = re.compile(r"[0-9a-zA-Z\-.]+")
_PASSWORD: Final = re.compile(r'[0-9a-zA-Z!"§$%&/()=*+#,;.:\-_]+')
_MASKS: Final = frozenset({"redacted", "**redacted**", "<redacted>", "[redacted]"})
_FLAGS: Final = ("nas_active", "nas_folder_nur_lesen", "nas_secure")
_FIRST_PRINTABLE: Final = 32
_DELETE_CHARACTER: Final = 127


class NasShareContractError(ValueError):
    """A share edit cannot preserve the exact reviewed router state safely."""


class NasShareReadback(StrEnum):
    """Non-optimistic result of an independent post-write read."""

    VERIFIED = "verified"
    SECRET_UNVERIFIED = "secret_unverified"  # noqa: S105 - result label, not a secret
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class NasShareLimits:
    """Exact bounds captured from this firmware's NAS form, without defaults."""

    folder_maximum: int | None
    username_minimum: int
    username_maximum: int
    password_minimum: int
    password_maximum: int

    def __post_init__(self) -> None:
        """Reject missing, Boolean, inverted, or unbounded field limits."""
        bounds = (
            self.username_minimum,
            self.username_maximum,
            self.password_minimum,
            self.password_maximum,
        )
        if (
            any(type(value) is not int or value <= 0 for value in bounds)
            or (
                self.folder_maximum is not None
                and (type(self.folder_maximum) is not int or self.folder_maximum <= 0)
            )
            or self.username_minimum > self.username_maximum
            or self.password_minimum > self.password_maximum
        ):
            raise NasShareContractError("NAS form bounds are not proven")


@dataclass(frozen=True, slots=True)
class NasShareEdit:
    """Explicit user changes; credentials must never enter entity attributes."""

    enabled: bool | None = None
    read_only: bool | None = None
    secure: bool | None = None
    folder_name: str | None = field(default=None, repr=False)
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)


@dataclass(slots=True)
class NasShareWrite:
    """
    Single-use wire payload and credential-free readback expectation.

    Consume immediately before sending, then discard the returned dictionary.
    This cannot wipe immutable Python strings or stop a caller logging them.
    """

    expected: Mapping[str, str | int] = field(repr=False)
    secret_submitted: bool
    _payload: dict[str, str | int] | None = field(repr=False)

    def consume_payload(self) -> dict[str, str | int]:
        """Transfer the payload once; never replay an uncertain write."""
        if self._payload is None:
            raise NasShareContractError("NAS write payload was already consumed")
        payload, self._payload = self._payload, None
        return payload

    def discard(self) -> None:
        """Drop this object's payload reference without sending anything."""
        self._payload = None


def _identifier(value: object) -> str:
    if type(value) is int and value >= 0:
        value = str(value)
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise NasShareContractError("NAS share identity is missing or invalid")
    return value


def _flag(value: object) -> int:
    if type(value) is bool:
        return int(value)
    if type(value) is int and value in (0, 1):
        return value
    if isinstance(value, str) and value in ("0", "1"):
        return int(value)
    raise NasShareContractError("NAS share state is incomplete")


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(
            ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER
            for char in value
        )
        or value.casefold() in _MASKS
        or set(value) <= {"*", "•", "●"}
    ):
        raise NasShareContractError("NAS field is missing, masked, or invalid")
    return value


def _snapshot(row: Mapping[str, object]) -> dict[str, str | int]:
    """Read exact wire fields only, excluding any returned password."""
    sid = _identifier(row.get("sid"))
    if "id" in row and _identifier(row["id"]) != sid:
        raise NasShareContractError("NAS share identities disagree")
    result: dict[str, str | int] = {"sid": sid}
    result.update({key: _flag(row.get(key)) for key in _FLAGS})
    result["nas_folder_name"] = _text(row.get("nas_folder_name"))
    if row.get("nas_user_name") not in (None, ""):
        result["nas_user_name"] = _text(row["nas_user_name"])
    return result


def nas_share_fingerprint(row: Mapping[str, object]) -> str:
    """Bind all preserved non-secret fields to a fresh, exact existing share."""
    return hashlib.sha256(
        json.dumps(_snapshot(row), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_nas_share_write(
    row: Mapping[str, object],
    *,
    expected_share_id: str,
    expected_fingerprint: str,
    edit: NasShareEdit,
    limits: NasShareLimits | None = None,
) -> NasShareWrite:
    """
    Preserve untouched fields, rejecting incomplete secure-share writes.

    This only edits an existing share. A secure active write must include an
    explicitly re-entered password: a returned router mask is never reused.
    Disabling sends only identity and the enable flag, as the firmware does.
    """
    current = _snapshot(row)
    if (
        _identifier(expected_share_id) != current["sid"]
        or not isinstance(expected_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) is None
        or not hmac.compare_digest(expected_fingerprint, nas_share_fingerprint(row))
    ):
        raise NasShareContractError("NAS target changed; refresh before editing")
    for value in (edit.enabled, edit.read_only, edit.secure):
        if value is not None and type(value) is not bool:
            raise NasShareContractError("NAS switches require Boolean input")
    if all(
        value is None
        for value in (
            edit.enabled,
            edit.read_only,
            edit.secure,
            edit.folder_name,
            edit.username,
            edit.password,
        )
    ):
        raise NasShareContractError("No NAS share change was requested")
    enabled = current["nas_active"] if edit.enabled is None else int(edit.enabled)
    payload: dict[str, str | int] = {"sid": current["sid"], "nas_active": enabled}
    if not enabled:
        if any(
            value is not None
            for value in (
                edit.read_only,
                edit.secure,
                edit.folder_name,
                edit.username,
                edit.password,
            )
        ):
            raise NasShareContractError("Disabled NAS shares cannot apply other edits")
    else:
        _populate_active_payload(payload, current, edit, limits)
    expected = MappingProxyType(
        {key: value for key, value in payload.items() if key != "nas_user_pwd"}
    )
    return NasShareWrite(expected, "nas_user_pwd" in payload, payload)


def _populate_active_payload(
    payload: dict[str, str | int],
    current: Mapping[str, str | int],
    edit: NasShareEdit,
    limits: NasShareLimits | None,
) -> None:
    if limits is None:
        raise NasShareContractError("NAS form bounds are not proven")
    folder = _text(
        current["nas_folder_name"] if edit.folder_name is None else edit.folder_name
    )
    if limits.folder_maximum is None and edit.folder_name is not None:
        raise NasShareContractError("NAS folder editing bounds are not proven")
    if limits.folder_maximum is not None and len(folder) > limits.folder_maximum:
        raise NasShareContractError("NAS folder exceeds the proven field limit")
    payload.update(
        nas_folder_name=folder,
        nas_folder_nur_lesen=(
            current["nas_folder_nur_lesen"]
            if edit.read_only is None
            else int(edit.read_only)
        ),
        nas_secure=current["nas_secure"] if edit.secure is None else int(edit.secure),
    )
    if not payload["nas_secure"]:
        if edit.username is not None or edit.password is not None:
            raise NasShareContractError("Unsecured NAS shares cannot apply credentials")
        return
    username = _text(
        current.get("nas_user_name") if edit.username is None else edit.username
    )
    password = _text(edit.password)
    if (
        not limits.username_minimum <= len(username) <= limits.username_maximum
        or _USER.fullmatch(username) is None
        or not limits.password_minimum <= len(password) <= limits.password_maximum
        or _PASSWORD.fullmatch(password) is None
    ):
        raise NasShareContractError("NAS credentials do not meet proven field rules")
    payload.update(nas_user_name=username, nas_user_pwd=password)


def build_nas_share_create_write(
    *, edit: NasShareEdit, limits: NasShareLimits
) -> NasShareWrite:
    """Build the explicit new-share sentinel form without inventing an existing row."""
    if (
        edit.enabled is not True
        or type(edit.read_only) is not bool
        or type(edit.secure) is not bool
        or edit.folder_name is None
    ):
        raise NasShareContractError("New NAS share settings must be explicit")
    payload: dict[str, str | int] = {"sid": "-1", "nas_active": 1}
    _populate_active_payload(payload, {}, edit, limits)
    expected = MappingProxyType(
        {key: value for key, value in payload.items() if key != "nas_user_pwd"}
    )
    return NasShareWrite(expected, "nas_user_pwd" in payload, payload)


def compare_nas_share_readback(
    write: NasShareWrite, row: Mapping[str, object] | None
) -> NasShareReadback:
    """Compare fresh data; never claim a credential is verified from a mask."""
    if row is None:
        return NasShareReadback.UNAVAILABLE
    try:
        sid = _identifier(row.get("sid"))
        if "id" in row and _identifier(row["id"]) != sid:
            return NasShareReadback.UNAVAILABLE
        if sid != write.expected["sid"]:
            return NasShareReadback.MISMATCH
        for key, expected in write.expected.items():
            actual = _flag(row.get(key)) if key in _FLAGS else row.get(key)
            if key == "sid":
                actual = sid
            if actual != expected:
                return NasShareReadback.MISMATCH
    except NasShareContractError:
        return NasShareReadback.UNAVAILABLE
    return (
        NasShareReadback.SECRET_UNVERIFIED
        if write.secret_submitted
        else NasShareReadback.VERIFIED
    )
