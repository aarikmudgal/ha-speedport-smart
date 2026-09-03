"""Offline pending online-link approval bindings and replay prevention."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.phonebook_link import OnlinePhonebookStage
from custom_components.speedport_smart.phonebook_link_session import (
    OnlinePhonebookSession,
)


def _local() -> dict[str, Any]:
    return {
        "phonebook_id": 2,
        "prefix": "",
        "entries": [{"contact_id": "1", "first_name": "Private name"}],
        "total": 1,
        "free_entries": 999,
        "truncated": False,
    }


def _book() -> dict[str, Any]:
    return {
        "addonlbuchentry": [
            {
                "id": "x",
                "onlbuch_nr": "2",
                "onlbuch_name": "Family",
                "onlbuch_bname": "private-user",
                "onlbuch_domain": "0",
                "onlbuch_sync": "1",
            }
        ]
    }


def _issue(session: OnlinePhonebookSession) -> dict[str, Any]:
    return session.issue(
        OnlinePhonebookStage("x", "2", "Family", "private-user", "0", "4"),
        requester=("admin", "login"),
        entry_id="router",
        local_inventory=_local(),
    )


def _consume(
    session: OnlinePhonebookSession, token: str, **changes: Any
) -> dict[str, str | bool]:
    return session.consume(
        token,
        **{
            "requester": ("admin", "login"),
            "entry_id": "router",
            "confirmed": True,
            "confirmation_text": "MERGE ONLINE PHONEBOOK CONTACTS",
            "merge_existing": True,
            "fresh_book": _book(),
            "fresh_local_inventory": _local(),
            **changes,
        },
    )


def test_pending_metadata_private_and_second_step_explicit_once() -> None:
    """Only counts and opaque approvals leave the owner; no automatic second write."""
    session = OnlinePhonebookSession()
    issued = _issue(session)
    assert "private" not in str(issued).lower()
    assert issued["online_contacts"] == 4
    assert _consume(session, issued["pending_link"]) == {
        "id": "x",
        "join_availEntries": True,
        "sum_onlineContacts": "4",
    }
    with pytest.raises(ConfigurationError, match="stale_settings"):
        _consume(session, issued["pending_link"])


@pytest.mark.parametrize(
    "changes",
    [
        {"requester": ("other", "login")},
        {"requester": ("admin", "other")},
        {"entry_id": "other"},
    ],
)
def test_foreign_requester_entry_or_login_cannot_consume(
    changes: dict[str, Any],
) -> None:
    """Another user cannot steal or burn a pending approval."""
    session = OnlinePhonebookSession()
    issued = _issue(session)
    with pytest.raises(ConfigurationError):
        _consume(session, issued["pending_link"], **changes)
    assert _consume(session, issued["pending_link"])["id"] == "x"


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": False},
        {"confirmed": 1},
        {"merge_existing": False},
        {"merge_existing": "true"},
        {"confirmation_text": "yes"},
    ],
)
def test_wrong_confirmation_or_merge_choice_consumes_without_payload(
    changes: dict[str, Any],
) -> None:
    """Replacement needs its own typed warning, never the merge confirmation."""
    session = OnlinePhonebookSession()
    token = _issue(session)["pending_link"]
    with pytest.raises(ConfigurationError, match="confirmation_required"):
        _consume(session, token, **changes)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        _consume(session, token)


def test_expiry_clear_and_changed_contacts_require_new_first_step() -> None:
    """Do not merge over local edits or reuse old approvals after teardown."""
    now = [0.0]
    session = OnlinePhonebookSession(clock=lambda: now[0])
    token = _issue(session)["pending_link"]
    now[0] = 121
    with pytest.raises(ConfigurationError):
        _consume(session, token)
    token = _issue(session)["pending_link"]
    local = _local()
    local["entries"][0]["first_name"] = "Changed"
    with pytest.raises(ConfigurationError, match="stale_settings"):
        _consume(session, token, fresh_local_inventory=local)
    token = _issue(session)["pending_link"]
    session.clear()
    with pytest.raises(ConfigurationError):
        _consume(session, token)


def test_replace_choice_is_explicit_not_a_default() -> None:
    """Return the native replacement boolean only after exact confirmation."""
    session = OnlinePhonebookSession()
    token = _issue(session)["pending_link"]
    result = _consume(
        session,
        token,
        merge_existing=False,
        confirmation_text="REPLACE LOCAL PHONEBOOK CONTACTS",
    )
    assert result["join_availEntries"] is False
