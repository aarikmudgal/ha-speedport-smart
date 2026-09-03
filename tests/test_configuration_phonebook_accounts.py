"""Offline exact phonebook account operations; no router interaction."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook_accounts import (
    PHONEBOOK_ACCOUNT_CREATE_SETTINGS,
    PHONEBOOK_ACCOUNT_TARGET_SPECS,
    phonebook_account_contract,
    phonebook_account_metadata,
    phonebook_account_rows,
    phonebook_account_targets,
)


def _state() -> dict[str, Any]:
    return {
        "addonlbuchentry": [
            {
                "id": "a",
                "onlbuch_nr": "1",
                "onlbuch_name": "Family",
                "onlbuch_bname": "",
                "onlbuch_sync": "0",
            },
            {
                "id": "b",
                "onlbuch_nr": "2",
                "onlbuch_name": "Online",
                "onlbuch_bname": "fixture",
                "onlbuch_sync": "1",
                "onlbuch_pwd": "PRIVATE",
                "onlbuch_domain": "0",
            },
        ]
    }


def test_static_catalog_and_no_implicit_online_disconnection() -> None:
    """Require exact existing targets and hide irrelevant disconnected operations."""
    assert {item["id"] for item in phonebook_account_metadata()} == set(
        PHONEBOOK_ACCOUNT_TARGET_SPECS
    )
    assert [
        row["id"]
        for row in phonebook_account_targets("telephony_phonebook_disconnect", _state())
    ] == ["b"]
    with pytest.raises(ConfigurationError):
        phonebook_account_contract("telephony_phonebook_disconnect", "a").read(_state())


def test_rename_preserves_hidden_identity_username_and_sibling() -> None:
    """Submit the full name form without clearing hidden account bindings."""
    contract = phonebook_account_contract("telephony_phonebook_rename", "b")
    assert contract.build(_state(), {"onlbuch_name": "New name"}) == {
        "id": "b",
        "onlbuch_nr": "2",
        "onlbuch_bname": "fixture",
        "onlbuch_name": "New name",
    }
    after = _state()
    after["addonlbuchentry"][1]["onlbuch_name"] = "New name"
    assert contract.verifier is not None
    assert contract.verifier(_state(), {"onlbuch_name": "New name"}, after)
    after["addonlbuchentry"][0]["onlbuch_nr"] = "3"
    assert not contract.verifier(_state(), {"onlbuch_name": "New name"}, after)


def test_delete_and_disconnect_exact_commands_and_independent_verifiers() -> None:
    """Deleting an entire book differs from removing its online link."""
    delete = phonebook_account_contract("telephony_phonebook_delete", "b")
    assert delete.build(_state(), {"execute": True}) == {
        "id": "b",
        "onlbuch_nr": "2",
        "deleteEntry": "delete",
    }
    after = _state()
    after["addonlbuchentry"].pop()
    assert delete.verifier is not None
    assert delete.verifier(_state(), {"execute": True}, after)
    disconnect = phonebook_account_contract("telephony_phonebook_disconnect", "b")
    assert disconnect.build(_state(), {"execute": True}) == {
        "id": "b",
        "disconnectEntry": "disconnect",
    }
    after = _state()
    after["addonlbuchentry"][1].update(
        onlbuch_sync="0", onlbuch_pwd="", onlbuch_bname=""
    )
    before = deepcopy(after)
    assert disconnect.verifier is not None
    assert disconnect.verifier(_state(), {"execute": True}, after)
    assert after == before
    after["addonlbuchentry"][1]["onlbuch_name"] = "Unexpected"
    assert not disconnect.verifier(_state(), {"execute": True}, after)


@pytest.mark.parametrize("source", [None, {}, [], "rows"])
def test_missing_and_empty_lists_never_create_fake_targets(source: object) -> None:
    """An explicit empty inventory is valid but has no editable targets."""
    if source == []:
        assert phonebook_account_rows({"addonlbuchentry": source}) == ()
    else:
        with pytest.raises(ConfigurationError):
            phonebook_account_rows({"addonlbuchentry": source})


@pytest.mark.parametrize(
    "change",
    [
        {"onlbuch_nr": "1"},
        {"id": "a"},
        {"onlbuch_bname": None},
        {"onlbuch_name": "<bad>"},
        {"onlbuch_sync": "unknown"},
    ],
)
def test_incomplete_duplicate_or_invalid_books_fail_closed(
    change: dict[str, Any],
) -> None:
    """Never infer identity or silently discard malformed inventory rows."""
    state = _state()
    state["addonlbuchentry"][1].update(change)
    with pytest.raises(ConfigurationError):
        phonebook_account_rows(state)


@pytest.mark.parametrize(
    "changes",
    [{"execute": False}, {"execute": 1}, {"id": "a"}, {"deleteEntry": "delete"}],
)
def test_destructive_actions_require_exact_typed_changes(
    changes: dict[str, Any],
) -> None:
    """No arbitrary wire keys or truthy coercion can form a destructive command."""
    with pytest.raises(ConfigurationError):
        phonebook_account_contract("telephony_phonebook_delete", "b").build(
            _state(), changes
        )


def test_new_local_book_uses_next_free_native_slot_and_full_new_row() -> None:
    """Creation differs from editing or implicitly linking an online account."""
    contract = PHONEBOOK_ACCOUNT_CREATE_SETTINGS[0]
    assert contract.read(_state()) == {"onlbuch_name": ""}
    payload = contract.build(_state(), {"onlbuch_name": "New book"})
    assert payload == {
        "id": "-1",
        "onlbuch_nr": "3",
        "onlbuch_name": "New book",
        "onlbuch_bname": "",
    }
    after = _state()
    after["addonlbuchentry"].append({**payload, "id": "new-id", "onlbuch_sync": "0"})
    assert contract.verifier is not None
    assert contract.verifier(_state(), {"onlbuch_name": "New book"}, after)
    after["addonlbuchentry"][0]["onlbuch_name"] = "Collateral"
    assert not contract.verifier(_state(), {"onlbuch_name": "New book"}, after)
    with pytest.raises(ConfigurationError):
        contract.build(_state(), {"onlbuch_name": ""})
