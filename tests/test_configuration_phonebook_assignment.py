"""DECT phonebook matrix proof without any router activity."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook_assignment import (
    PHONEBOOK_ASSIGN_SETTING_ID,
    phonebook_assignment_contract,
    phonebook_assignment_metadata,
    phonebook_assignment_rows,
)


def _raw() -> dict[str, Any]:
    return {
        "adddectmobiles": [
            {"id": "1", "dect_mobile_name": "Handset", "dect_onlbuch": "0"},
            {"id": "3", "dect_mobile_name": "Office", "dect_onlbuch": "2"},
        ],
        "phonebooks": {
            "addonlbuchentry": [
                {"onlbuch_nr": "0", "onlbuch_name": "Shared"},
                {"onlbuch_nr": "2", "onlbuch_name": "Office"},
            ]
        },
    }


def test_exact_complete_matrix_and_dynamic_book_choices() -> None:
    """Real handset IDs appear in firmware field names, never DOM ordinal guesses."""
    contract = phonebook_assignment_contract(PHONEBOOK_ASSIGN_SETTING_ID, "1")
    assert contract.build(_raw(), {"phonebook": "2"}) == {
        "dect_onlbuch_1": "2",
        "dect_onlbuch_3": "2",
    }
    assert contract.read(_raw()) == {"phonebook": "0"}
    assert contract.choices(_raw()) == {
        "phonebook": [
            {"value": "0", "label": "Shared"},
            {"value": "2", "label": "Office"},
        ]
    }
    assert contract.endpoint == "data/DECTSettings.json"
    assert contract.read_endpoint == "data/DECTMobiles.json"
    metadata = phonebook_assignment_metadata()[0]
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()


def test_unselected_handset_and_phonebook_identity_preserved() -> None:
    """Verification checks the full matrix and book identity, not one enum alone."""
    contract = phonebook_assignment_contract(PHONEBOOK_ASSIGN_SETTING_ID, "1")
    before = _raw()
    after = deepcopy(before)
    after["adddectmobiles"][0]["dect_onlbuch"] = "2"
    assert contract.verifier is not None
    assert contract.verifier(before, {"phonebook": "2"}, after)
    after["adddectmobiles"][1]["dect_mobile_name"] = "Replaced handset"
    assert not contract.verifier(before, {"phonebook": "2"}, after)


@pytest.mark.parametrize(
    "changed",
    [
        {"phonebooks": {}},
        {"adddectmobiles": None},
        {"adddectmobiles": [{"id": "1", "dect_onlbuch": "9"}]},
        {
            "adddectmobiles": [
                {"id": "1", "dect_onlbuch": "0"},
                {"id": "1", "dect_onlbuch": "2"},
            ]
        },
    ],
)
def test_missing_or_unknown_assignment_inventory_rejected(
    changed: dict[str, Any],
) -> None:
    """Unknown books, duplicate handsets and absent collections never become choices."""
    with pytest.raises(ConfigurationError):
        phonebook_assignment_rows(PHONEBOOK_ASSIGN_SETTING_ID, {**_raw(), **changed})


def test_unknown_target_or_book_never_creates_wire_fields() -> None:
    """A target selector cannot inject a field or invent a phonebook."""
    with pytest.raises(ConfigurationError):
        phonebook_assignment_contract(PHONEBOOK_ASSIGN_SETTING_ID, "1[x]")
    with pytest.raises(ConfigurationError):
        phonebook_assignment_contract(PHONEBOOK_ASSIGN_SETTING_ID, "4").read(_raw())
    with pytest.raises(ConfigurationError):
        phonebook_assignment_contract(PHONEBOOK_ASSIGN_SETTING_ID, "1").build(
            _raw(), {"phonebook": "9"}
        )
