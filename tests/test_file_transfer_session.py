"""One-use file grants never retain passwords or bytes and cannot cross HA sessions."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from custom_components.speedport_smart.file_transfer import (
    FILE_TRANSFER_CONTRACTS,
    FileTransferError,
)
from custom_components.speedport_smart.file_transfer_session import FileTransferSession

_USER = ("user-a", "session-a")
_ACTION = "system_backup_restore"


def _prepare(session: FileTransferSession, **overrides: Any) -> dict[str, Any]:
    args = {
        "requester": _USER,
        "entry_id": "entry-a",
        "size": 4,
        "sha256": hashlib.sha256(b"file").hexdigest(),
        "confirmed": True,
        "confirmation_text": FILE_TRANSFER_CONTRACTS[_ACTION].confirmation,
        **overrides,
    }
    return session.prepare(_ACTION, **args)


def test_file_grant_is_closed_value_free_and_consumed_once() -> None:
    """Only an opaque grant and expiry leave the store; every valid consume burns it."""
    session = FileTransferSession(clock=lambda: 100.0)
    issued = _prepare(session)
    assert set(issued) == {"action", "grant", "expires_in"}
    assert issued["expires_in"] == 120
    grant = session.consume(
        issued["grant"], action=_ACTION, requester=_USER, entry_id="entry-a"
    )
    assert grant.size == 4
    assert "session-a" not in repr(grant)
    assert "user-a" not in repr(grant)
    assert "file" not in repr(issued)
    with pytest.raises(FileTransferError):
        session.consume(
            issued["grant"], action=_ACTION, requester=_USER, entry_id="entry-a"
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"requester": ("user-b", "session-a")},
        {"requester": ("user-a", "session-b")},
        {"entry_id": "entry-b"},
        {"action": "system_firmware_upload"},
    ],
)
def test_grants_cannot_cross_user_login_entry_or_action(
    overrides: dict[str, Any],
) -> None:
    """A wrong caller cannot consume another administrator's approval."""
    session = FileTransferSession()
    issued = _prepare(session)
    args = {"action": _ACTION, "requester": _USER, "entry_id": "entry-a"}
    with pytest.raises(FileTransferError):
        session.consume(issued["grant"], **{**args, **overrides})
    session.consume(issued["grant"], **args)


def test_expiry_rotation_and_inflight_invalidation() -> None:
    """Expiry is exclusive and clear invalidates already consumed in-flight grants."""
    now = [100.0]
    session = FileTransferSession(clock=lambda: now[0])
    first = _prepare(session)
    second = _prepare(session)
    with pytest.raises(FileTransferError):
        session.consume(
            first["grant"], action=_ACTION, requester=_USER, entry_id="entry-a"
        )
    now[0] = 220.0
    with pytest.raises(FileTransferError):
        session.consume(
            second["grant"], action=_ACTION, requester=_USER, entry_id="entry-a"
        )
    current = _prepare(session)
    grant = session.consume(
        current["grant"], action=_ACTION, requester=_USER, entry_id="entry-a"
    )
    session.clear()
    with pytest.raises(FileTransferError):
        session.check_current(grant)


@pytest.mark.parametrize(
    "overrides",
    [
        {"size": True},
        {"size": 0},
        {"size": 6_291_457},
        {"sha256": "unknown"},
        {"confirmed": 1},
        {"confirmed": False},
        {"confirmation_text": "SAVE"},
        {"requester": ("", "session")},
        {"entry_id": ""},
    ],
)
def test_grant_invalid_inputs_never_issue_approval(overrides: dict[str, Any]) -> None:
    """All size, digest, identity and confirmation constraints are checked first."""
    with pytest.raises(FileTransferError):
        _prepare(FileTransferSession(), **overrides)


def test_store_capacity_is_bounded_and_download_has_no_file_digest() -> None:
    """Many administrators cannot create an unbounded approval cache."""
    session = FileTransferSession()
    for number in range(8):
        _prepare(session, requester=(f"user-{number}", f"session-{number}"))
    with pytest.raises(FileTransferError):
        _prepare(session, requester=("extra", "extra-session"))
    session.clear()
    action = "system_backup_download"
    grant = session.prepare(
        action,
        requester=_USER,
        entry_id="entry-a",
        size=0,
        sha256=None,
        confirmed=True,
        confirmation_text=FILE_TRANSFER_CONTRACTS[action].confirmation,
    )
    assert grant["action"] == action
