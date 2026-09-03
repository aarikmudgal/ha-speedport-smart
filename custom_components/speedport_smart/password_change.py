"""
Private, one-use password-change policy. This module performs no I/O.

The owner must bind a short-lived approval to the administrator, refresh token
and loaded entry; serialize the operation; independently authenticate with the
entered current password; verify the fixed router identity; and fetch a fresh
change-password page token. Only ``take_payload`` supplies the password-changing
POST. That request must use the current session's encrypted JSON transport, with
no redirects or retries. Normal login challenge hashing is not this form's wire
format. A separate, isolated login with the new password proves the credential
before the owner updates its config entry. Never pass this private object to a
dashboard, diagnostic serializer, logger, exception formatter or Recorder.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from .admin_actions import SPEEDPORT_SMART_4R_TYP_A_010152
from .configuration import SettingsField

PASSWORD_CHANGE_ID: Final = "system_router_password_change"  # noqa: S105
PASSWORD_CHANGE_ENDPOINT: Final = "data/Login.json"  # noqa: S105
PASSWORD_CHANGE_REFERER: Final = "html/content/config/change_password.html"  # noqa: S105
PASSWORD_CHANGE_CONFIRMATION: Final = "CHANGE ROUTER PASSWORD"  # noqa: S105
_TOKEN: Final = re.compile(r"[0-9]{1,32}")
_PASSWORD: Final = re.compile(r'[0-9a-zA-Z!"§$%&/()=*+#,;.:_-]+')
_CHALLENGE: Final = re.compile(r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{48}|[0-9a-fA-F]{64})")
_MAX_IDENTITY: Final = 256
_MAX_PASSWORD: Final = 32
_NEW_MINIMUM: Final = 8
_NEGATIVE: Final = frozenset(
    {"0", "denied", "error", "failed", "failure", "false", "no", "nok", "rejected"}
)
PasswordAcknowledgement = Literal["accepted", "rejected", "outcome_unknown"]


class PasswordChangeError(ValueError):
    """Closed errors containing no password, token, router response or identity."""

    def __init__(self, code: str = "invalid_password_change") -> None:
        """Retain only an allowlisted public error code."""
        if code not in {
            "invalid_password_change",
            "confirmation_required",
            "unsupported_router",
            "password_change_preflight_failed",
            "password_repeat_mismatch",
            "password_unchanged",
            "stale_password_change",
            "password_change_rejected",
            "password_change_outcome_unknown",
            "password_verification_failed",
        }:
            raise ValueError("Unknown password-change error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PasswordChangeIdentity:
    """Private fingerprint of the server-owned router identity, never a password."""

    fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        """Reject malformed private binding objects without retaining the input."""
        if (
            type(self.fingerprint) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.fingerprint) is None
        ):
            raise PasswordChangeError("password_change_preflight_failed")


def password_change_identity(
    *,
    model: object,
    firmware: object,
    router_identifier: object,
) -> PasswordChangeIdentity:
    """Bind the exact reviewed firmware and a stable server-resolved router ID."""
    target = SPEEDPORT_SMART_4R_TYP_A_010152
    if model != target.model or firmware != target.firmware:
        raise PasswordChangeError("unsupported_router")
    if (
        type(router_identifier) is not str
        or not 0 < len(router_identifier) <= _MAX_IDENTITY
        or not router_identifier.isprintable()
    ):
        raise PasswordChangeError("password_change_preflight_failed")
    digest = hashlib.sha256(
        json.dumps((model, firmware, router_identifier), ensure_ascii=True).encode()
    ).hexdigest()
    return PasswordChangeIdentity(digest)


def password_change_metadata() -> dict[str, Any]:
    """Describe three empty secret inputs without exposing any current credential."""
    fields = (
        SettingsField(
            "password", "Current router password", "secret", minimum=1, maximum=32
        ),
        SettingsField(
            "new_password", "New router password", "secret", minimum=8, maximum=32
        ),
        SettingsField(
            "new_pw_repeat",
            "Repeat new router password",
            "secret",
            minimum=8,
            maximum=32,
        ),
    )
    return {
        "id": PASSWORD_CHANGE_ID,
        "title": "Change router password",
        "execution_policy": "password_change",
        "confirmation": PASSWORD_CHANGE_CONFIRMATION,
        "fields": [item.metadata() for item in fields],
        "requires_recovery_confirmation": True,
        "live_write_verified": False,
        "warning": (
            "Save the new password in a safe place before continuing. This changes "
            "the router's management password and may interrupt management sessions. "
            "The request is sent once. Home Assistant stores the new password only "
            "after a separate login proves it works on the same router. If the "
            "outcome is uncertain, inspect the router and reauthenticate manually; "
            "the integration will not cycle old and new passwords or retry the change. "
            'Allowed characters are ASCII letters, digits and !"§$%&/()=*+#,;.:_-. '
            "Passwords are never prefilled, returned or included in diagnostics."
        ),
    }


def _password(value: object, *, minimum: int) -> str:
    if (
        type(value) is not str
        or not minimum <= len(value) <= _MAX_PASSWORD
        or _PASSWORD.fullmatch(value) is None
        or re.fullmatch(r"\*+", value) is not None
    ):
        raise PasswordChangeError
    return value


def _canonical_scalar(response: Mapping[str, Any], name: str) -> object:
    matching = [key for key in response if str(key).casefold() == name.casefold()]
    if matching not in ([], [name]):
        raise PasswordChangeError("password_change_outcome_unknown")
    value = response.get(name)
    if value is not None and type(value) not in {str, int, bool}:
        raise PasswordChangeError("password_change_outcome_unknown")
    return value


def _negative(value: object) -> bool:
    return (
        (type(value) is str and value in _NEGATIVE)
        or (type(value) is int and value == 0)
        or value is False
    )


def validate_password_login_response(response: object) -> None:
    """Require the exact native login proof, with no competing owner or errors."""
    if not isinstance(response, Mapping):
        raise PasswordChangeError("password_verification_failed")
    try:
        login = _canonical_scalar(response, "login")
        status = _canonical_scalar(response, "status")
        reason = _canonical_scalar(response, "reason")
        owner = _canonical_scalar(response, "login_other")
        locked = _canonical_scalar(response, "login_locked")
        errors = [_canonical_scalar(response, key) for key in ("error", "errors")]
    except PasswordChangeError:
        raise PasswordChangeError("password_verification_failed") from None
    if (
        login != "success"
        or status not in (None, "ok")
        or reason in (-1, -2, "-1", "-2")
        or owner not in (None, "", False, 0, "0", "false", "none", "null")
        or locked not in (None, "", False, 0, "0")
        or any(value not in (None, "", False, 0) for value in errors)
    ):
        raise PasswordChangeError("password_verification_failed")


def classify_password_change_ack(response: object) -> PasswordAcknowledgement:
    """Require both generic form success and the exact password callback success."""
    if not isinstance(response, Mapping):
        return "outcome_unknown"
    try:
        status = _canonical_scalar(response, "status")
        login = _canonical_scalar(response, "login")
        reason = _canonical_scalar(response, "reason")
        errors = [_canonical_scalar(response, key) for key in ("error", "errors")]
    except PasswordChangeError:
        return "outcome_unknown"
    has_error = any(value not in (None, "", False, 0) for value in errors)
    accepted = status == "ok" and login == "success"
    if accepted:
        # A success combined with a rejection reason or error is contradictory,
        # not permission to try a new credential or replace stored credentials.
        return (
            "outcome_unknown"
            if has_error or reason in (-1, -2, "-1", "-2")
            else "accepted"
        )
    if login == "success":
        return "outcome_unknown"
    if _negative(status) or _negative(login) or has_error:
        return "rejected"
    if status == "ok" and reason in (-1, -2, "-1", "-2"):
        return "rejected"
    return "outcome_unknown"


class PasswordChangeRequest:
    """One private draft with a single payload and explicit new-login proof gate."""

    __slots__ = (
        "_ack",
        "_ack_recorded",
        "_cleared",
        "_consumed",
        "_identity",
        "_new",
        "_new_verified",
        "_old",
        "_verification_started",
    )

    def __init__(
        self,
        changes: Mapping[str, object],
        *,
        identity: PasswordChangeIdentity,
        confirmed: object,
        confirmation_text: object,
        recovery_ready: object,
    ) -> None:
        """Own only freshly entered credentials after exact typed confirmation."""
        if (
            confirmed is not True
            or recovery_ready is not True
            or confirmation_text != PASSWORD_CHANGE_CONFIRMATION
        ):
            raise PasswordChangeError("confirmation_required")
        if not isinstance(identity, PasswordChangeIdentity) or set(changes) != {
            "password",
            "new_password",
            "new_pw_repeat",
        }:
            raise PasswordChangeError
        old = _password(changes["password"], minimum=1)
        new = _password(changes["new_password"], minimum=_NEW_MINIMUM)
        repeat = _password(changes["new_pw_repeat"], minimum=_NEW_MINIMUM)
        if not hmac.compare_digest(new.encode(), repeat.encode()):
            raise PasswordChangeError("password_repeat_mismatch")
        if hmac.compare_digest(old.encode(), new.encode()):
            raise PasswordChangeError("password_unchanged")
        self._identity = identity
        self._old: str | None = old
        self._new: str | None = new
        self._consumed = False
        self._ack: PasswordAcknowledgement = "outcome_unknown"
        self._ack_recorded = False
        self._verification_started = False
        self._new_verified = False
        self._cleared = False

    def __repr__(self) -> str:
        """Never format secret values, identifiers or request payloads."""
        return "<PasswordChangeRequest private>"

    def _active(self) -> None:
        if self._cleared:
            raise PasswordChangeError("stale_password_change")

    def current_password(self) -> str:
        """Supply the current credential only to the isolated preflight login."""
        self._active()
        if self._consumed or self._old is None:
            raise PasswordChangeError("stale_password_change")
        return self._old

    def validate_identity(self, current_identity: PasswordChangeIdentity) -> None:
        """Check fresh serial-bound identity before even the old-password login."""
        self._active()
        if not isinstance(
            current_identity, PasswordChangeIdentity
        ) or not hmac.compare_digest(
            self._identity.fingerprint, current_identity.fingerprint
        ):
            raise PasswordChangeError("password_change_preflight_failed")

    def take_payload(
        self,
        *,
        page_token: object,
        current_identity: PasswordChangeIdentity,
        router_state: object,
        current_password_authenticated: object,
    ) -> dict[str, str]:
        """Consume before transport; return exact plaintext form fields and token."""
        self._active()
        if self._consumed or self._old is None or self._new is None:
            raise PasswordChangeError("stale_password_change")
        if (
            not isinstance(current_identity, PasswordChangeIdentity)
            or not hmac.compare_digest(
                self._identity.fingerprint, current_identity.fingerprint
            )
            or current_password_authenticated is not True
            or router_state != "OK"
            or type(page_token) is not str
            or _TOKEN.fullmatch(page_token) is None
        ):
            raise PasswordChangeError("password_change_preflight_failed")
        self._consumed = True
        payload = {
            "password": self._old,
            "new_password": self._new,
            "new_pw_repeat": self._new,
            "httoken": page_token,
        }
        self._old = None
        return payload

    def record_acknowledgement(self, response: object) -> PasswordAcknowledgement:
        """Retain only a closed ACK classification, never the private response."""
        self._active()
        if not self._consumed or self._ack_recorded:
            raise PasswordChangeError("stale_password_change")
        self._ack_recorded = True
        self._ack = classify_password_change_ack(response)
        return self._ack

    def verification_password(self) -> str:
        """Allow one new-login proof path only after unambiguous acceptance."""
        self._active()
        if (
            not self._consumed
            or self._ack != "accepted"
            or self._new is None
            or self._verification_started
        ):
            raise PasswordChangeError("password_change_outcome_unknown")
        self._verification_started = True
        return self._new

    def verify_new_login(
        self,
        *,
        response: object,
        current_identity: PasswordChangeIdentity,
        router_state: object,
        old_session_released: object,
        isolated_new_session: object,
        fresh_challenge_requested: object,
        new_challenge: object,
    ) -> None:
        """Reject old-session reuse, ambiguous login replies and changed routers."""
        self._active()
        if (
            not self._verification_started
            or self._ack != "accepted"
            or old_session_released is not True
            or isolated_new_session is not True
            or fresh_challenge_requested is not True
            or not isinstance(response, Mapping)
            or not isinstance(current_identity, PasswordChangeIdentity)
            or not hmac.compare_digest(
                self._identity.fingerprint, current_identity.fingerprint
            )
            or router_state != "OK"
            or type(new_challenge) is not str
            or _CHALLENGE.fullmatch(new_challenge) is None
        ):
            raise PasswordChangeError("password_verification_failed")
        validate_password_login_response(response)
        self._new_verified = True

    def credential_for_storage(self) -> str:
        """Supply the proven credential only for the client's/config entry's update."""
        self._active()
        if not self._new_verified or self._new is None:
            raise PasswordChangeError("password_verification_failed")
        return self._new

    def result(
        self, *, credential_persisted: bool, cleanup_confirmed: bool
    ) -> dict[str, Any]:
        """Report no success until credential storage and cleanup both complete."""
        self._active()
        if (
            type(credential_persisted) is not bool
            or type(cleanup_confirmed) is not bool
            or (credential_persisted and not self._new_verified)
        ):
            raise PasswordChangeError
        if not self._consumed:
            return {"status": "not_started", "retry_safe": False}
        if self._ack == "rejected":
            return {"status": "rejected", "retry_safe": False}
        if not self._new_verified:
            return {
                "status": "outcome_unknown",
                "verification": "reauthentication_required",
                "acknowledged": self._ack == "accepted",
                "retry_safe": False,
            }
        if not credential_persisted:
            return {
                "status": "outcome_unknown",
                "verification": "credential_update_required",
                "credential_verified": True,
                "retry_safe": False,
            }
        return {
            "status": "verified" if cleanup_confirmed else "outcome_unknown",
            "verification": "new_credential"
            if cleanup_confirmed
            else "session_cleanup_failed",
            "credential_updated": True,
            "retry_safe": False,
        }

    def clear(self) -> None:
        """Release references; Python immutable strings cannot be zeroized."""
        self._old = self._new = None
        self._new_verified = False
        self._cleared = True
