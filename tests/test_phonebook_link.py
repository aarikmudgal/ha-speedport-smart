"""Offline two-stage online phonebook payload safety; no network operations."""

# ruff: noqa: S106 - synthetic fixture credentials only

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.phonebook_link import (
    online_phonebook_finish_payload,
    online_phonebook_link_payload,
    online_phonebook_link_stage,
)


def _state() -> dict[str, Any]:
    return {
        "addonlbuchentry": [
            {
                "id": "x",
                "onlbuch_nr": "2",
                "onlbuch_name": "Work",
                "onlbuch_bname": "",
                "onlbuch_sync": "0",
            }
        ]
    }


def test_explicit_two_stages_keep_credentials_out_of_pending_state() -> None:
    """No first-stage response silently triggers merge or destructive replacement."""
    payload = online_phonebook_link_payload(
        _state(), "x", username="user", domain="1", password="Secret"
    )
    assert set(payload) == {
        "id",
        "onlbuch_name",
        "onlbuch_bname",
        "onlbuch_domain",
        "onlbuch_pwd",
    }
    stage = online_phonebook_link_stage(
        _state(),
        "x",
        username="user",
        domain="1",
        response={"status": "ok", "assignedID": "x", "sum_onlineContacts": "5"},
    )
    assert "Secret" not in repr(stage)
    fresh = _state()
    fresh["addonlbuchentry"][0].update(onlbuch_bname="user", onlbuch_domain="1")
    for merge in (False, True):
        assert online_phonebook_finish_payload(fresh, stage, merge_existing=merge) == {
            "id": "x",
            "join_availEntries": merge,
            "sum_onlineContacts": "5",
        }
    fresh["addonlbuchentry"][0]["onlbuch_nr"] = "3"
    with pytest.raises(ConfigurationError, match="stale_settings"):
        online_phonebook_finish_payload(fresh, stage, merge_existing=True)


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "fail"},
        {"status": "ok", "sum_onlineContacts": "1001"},
        {"status": "ok", "sum_onlineContacts": "1", "assignedID": "other"},
        {"status": "ok", "sum_onlineContacts": 1},
    ],
)
def test_failed_or_ambiguous_first_step_cannot_create_followup_payload(
    response: dict[str, Any],
) -> None:
    """Require one exact bound ID and a native bounded contact count."""
    with pytest.raises(ConfigurationError):
        online_phonebook_link_stage(
            _state(), "x", username="user", domain="0", response=response
        )


def test_invalid_secrets_domains_and_existing_links_fail_closed() -> None:
    """Do not resend masks or overwrite a current account link implicitly."""
    for password in ("", "********", "a\nprivate"):
        with pytest.raises(ConfigurationError):
            online_phonebook_link_payload(
                _state(), "x", username="user", domain="0", password=password
            )
    state = _state()
    state["addonlbuchentry"][0]["onlbuch_sync"] = "1"
    with pytest.raises(ConfigurationError):
        online_phonebook_link_payload(
            state, "x", username="user", domain="0", password="Secret"
        )
