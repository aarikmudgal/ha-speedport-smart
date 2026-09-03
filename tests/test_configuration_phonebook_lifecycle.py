"""One-shot contact creation helpers; no network or router writes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook import PHONEBOOK_FIELDS
from custom_components.speedport_smart.configuration_phonebook_lifecycle import (
    phonebook_create_metadata,
    phonebook_create_payload,
    phonebook_create_settings,
    phonebook_created_id,
    phonebook_inventory,
    verify_phonebook_creation,
)


def _before() -> dict[str, Any]:
    return {
        "phonebook_id": 0,
        "entries": [
            {
                "contact_id": "1",
                "last_name": "Existing",
                "first_name": "",
                "number": "00000001",
            }
        ],
        "prefix": "",
        "total": 1,
        "free_entries": 99,
        "truncated": False,
    }


def _draft() -> dict[str, str]:
    return {"vorname": "New contact", "number_p": "000 00002"}


def _after() -> dict[str, Any]:
    value = deepcopy(_before())
    value.update(total=2, free_entries=98, assigned_id="7")
    value["entries"].append(
        {"contact_id": "7", "first_name": "New contact", "number": "00000002"}
    )
    payload = phonebook_create_payload(_before(), _draft(), phonebook_id=0)
    value["created_contact"] = {
        "phonebook_id": 0,
        "contact_id": "7",
        "contact": {item.name: payload[item.name] for item in PHONEBOOK_FIELDS},
    }
    return value


def test_creation_metadata_and_form_use_only_explicit_new_row_sentinel() -> None:
    """Blank values belong to a new-entry form, never an invented router contact."""
    contract = phonebook_create_settings("0")
    metadata = phonebook_create_metadata()
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()
    assert contract.verifier_owns_fields is True
    assert set(contract.read(_before()).values()) == {""}
    payload = contract.build(_before(), _draft())
    assert payload["id"] == "-1"
    assert payload["obnr"] == 0
    assert payload["number_p"] == "00000002"
    assert set(payload) == {"id", "obnr", *(field.name for field in PHONEBOOK_FIELDS)}


def test_returned_id_requires_exact_success_and_nonexisting_identity() -> None:
    """An ACK ID is validated before it can select an independent detail query."""
    assert (
        phonebook_created_id({"status": "ok", "assignedID": "7"}, existing_ids={"1"})
        == "7"
    )
    assert (
        phonebook_created_id({"status": "ok", "assignedID": 7}, existing_ids={"1"})
        == "7"
    )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "ok"},
        {"status": "error", "assignedID": "7"},
        {"status": "ok", "assignedID": "1"},
        {"status": "ok", "assignedID": "-1"},
        {"status": "ok", "assignedID": "../7"},
        {"status": "ok", "assignedID": True},
        {"status": "ok", "assignedID": ["7"]},
        {"status": "ok", "assignedID": "7", "assignedid": "8"},
        {"status": "ok", "Status": "error", "assignedID": "7"},
    ],
)
def test_missing_ambiguous_or_reused_id_is_unknown_not_retryable(
    response: dict[str, Any],
) -> None:
    """Never derive a target from a title, position, fallback key or old contact."""
    with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
        phonebook_created_id(response, existing_ids={"1"})


@pytest.mark.parametrize(
    "changed",
    [
        {"phonebook_id": 1},
        {"phonebook_id": "0"},
        {"truncated": True},
        {"truncated": None},
        {"prefix": "A"},
        {"total": 2},
        {"total": "1"},
        {"free_entries": None},
        {"free_entries": -1},
        {"entries": None},
        {"entries": [{"contact_id": "1"}, {"contact_id": "1"}], "total": 2},
    ],
)
def test_incomplete_or_wrong_book_inventory_blocks_creation(
    changed: dict[str, Any],
) -> None:
    """Capacity, identity and completeness are required before building a write."""
    with pytest.raises(ConfigurationError):
        phonebook_create_payload({**_before(), **changed}, _draft(), phonebook_id=0)


def test_empty_complete_book_is_valid_but_full_book_is_not() -> None:
    """Explicit zero counts prove an empty book; missing rows alone do not."""
    empty = {**_before(), "entries": [], "total": 0}
    assert phonebook_inventory(empty, phonebook_id=0) == {}
    assert phonebook_create_payload(empty, _draft(), phonebook_id=0)["id"] == "-1"
    with pytest.raises(ConfigurationError, match="settings_capacity_reached"):
        phonebook_create_payload({**empty, "free_entries": 0}, _draft(), phonebook_id=0)


def test_inventory_accepts_full_firmware_capacity_without_truncation() -> None:
    """The firmware supports 1,000 contacts per local phonebook, not 256."""
    raw = {
        **_before(),
        "entries": [{"contact_id": str(index)} for index in range(1000)],
        "total": 1000,
        "free_entries": 0,
    }
    assert len(phonebook_inventory(raw, phonebook_id=0)) == 1000
    raw["entries"].append({"contact_id": "1000"})
    raw["total"] = 1001
    with pytest.raises(ConfigurationError):
        phonebook_inventory(raw, phonebook_id=0)


def test_verifier_requires_single_added_id_and_all_private_detail_fields() -> None:
    """List membership alone cannot prove address, birthday or other phone numbers."""
    assert verify_phonebook_creation(_before(), _draft(), _after(), phonebook_id=0)
    after = _after()
    after["created_contact"]["contact"]["adresse"] = "Unexpected street"
    assert not verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)
    after = _after()
    after["created_contact"]["contact"].pop("adresse")
    with pytest.raises(ConfigurationError):
        verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)


def test_verifier_rejects_cross_book_reused_id_and_changed_sibling() -> None:
    """Do not verify another book's contact or a collateral change."""
    after = _after()
    after["created_contact"]["phonebook_id"] = 1
    assert not verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)
    after = _after()
    after["assigned_id"] = "1"
    assert not verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)
    after = _after()
    after["entries"][0]["last_name"] = "Changed existing"
    assert not verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)


def test_verifier_rejects_multiple_concurrent_new_contacts() -> None:
    """A racing additional insertion makes the single-contact result ambiguous."""
    after = _after()
    after["entries"].append({"contact_id": "8", "first_name": "Other"})
    after["total"] = 3
    assert not verify_phonebook_creation(_before(), _draft(), after, phonebook_id=0)
