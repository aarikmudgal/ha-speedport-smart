"""Offline proof for the two independently submitted telephone matrices."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phone_assignments import (
    assignment_target_contract,
    assignment_target_metadata,
)


def _raw() -> dict[str, Any]:
    return {
        "addglobalplug": [
            {
                "id": "0",
                "plug_name": "Office",
                "plug_type": "0",
                "plug_outgoing": "1",
                "plug_alternative_number": "0",
                "sid": [{"sid": "1", "outg": "1"}, {"sid": "7", "outg": "0"}],
            },
            {
                "id": "6",
                "plug_name": "Kitchen",
                "plug_type": "0",
                "plug_outgoing": "0",
                "plug_alternative_number": "0",
                "sid": [{"sid": "1", "outg": "1"}, {"sid": "7", "outg": "1"}],
            },
        ],
        "addphonenumber": [
            {"id": "1", "phone_number": "00000001", "phone_number_type": "IP"},
            {"id": "7", "phone_number": "00000002", "phone_number_type": "IP"},
        ],
    }


def test_metadata_requires_real_target() -> None:
    """The static catalog does not imply fictitious plugs or a live-tested write."""
    for row in assignment_target_metadata():
        assert row.pop("requires_target") is True
        assert row == assignment_target_contract(row["id"], "0").metadata()


def test_incoming_form_preserves_full_matrix_and_uses_router_ids() -> None:
    """Matrix field names use exact plug/number IDs, not nested template indices."""
    contract = assignment_target_contract("telephony_incoming_assignment", "0")
    raw = _raw()
    before = deepcopy(raw)
    assert contract.read(raw) == {"incoming": ["1"]}
    assert contract.build(raw, {"incoming": []}) == {
        "incoming[0][1]": 0,
        "incoming[0][7]": 0,
        "incoming[6][1]": 1,
        "incoming[6][7]": 1,
    }
    assert raw == before


def test_outgoing_form_preserves_every_backup_and_unselected_device() -> None:
    """The separate outgoing form includes all hidden backup fields."""
    contract = assignment_target_contract("telephony_outgoing_assignment", "0")
    assert contract.build(
        _raw(), {"outgoing": "7", "plug_alternative_number": "1"}
    ) == {
        "outgoing[0]": "7",
        "plug_alternative_number[0]": "1",
        "outgoing[6]": "0",
        "plug_alternative_number[6]": "0",
    }
    assert contract.choices(_raw())["plug_alternative_number"][0] == {
        "value": "0",
        "label": "No alternative",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"outgoing[0]": "7"},
        {"outgoing": "99"},
        {"outgoing": "1", "plug_alternative_number": "1"},
        {"outgoing": "0", "plug_alternative_number": "7"},
        {"outgoing": 1},
    ],
)
def test_invalid_outgoing_changes_fail(changes: dict[str, Any]) -> None:
    """Reject raw keys, unknown IDs, same-number backups and inactive backup edits."""
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_outgoing_assignment", "0").build(
            _raw(), changes
        )


@pytest.mark.parametrize("value", [["99"], ["1", "1"], "1", [1]])
def test_invalid_incoming_changes_fail(value: object) -> None:
    """Only a bounded set of currently advertised IDs is accepted."""
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_incoming_assignment", "0").build(
            _raw(), {"incoming": value}
        )


def test_missing_target_does_not_send_unchanged_full_matrix() -> None:
    """Builders must reject a stale target even outside the shared session guard."""
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_incoming_assignment", "99").build(
            _raw(), {"incoming": []}
        )


def test_wrong_compound_name_and_missing_number_rows_fail() -> None:
    """Handset compounds cannot be mistaken for global assignment compounds."""
    raw = _raw()
    raw["addglobalplug"][0]["sid"][0] = {"sid": "1", "ring_incoming": "1"}
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_incoming_assignment", "0").read(raw)
    raw = _raw()
    raw["addphonenumber"].pop()
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_incoming_assignment", "0").read(raw)


def test_verification_checks_both_matrices_and_every_sibling() -> None:
    """Requested target change cannot mask collateral outgoing or sibling changes."""
    contract = assignment_target_contract("telephony_incoming_assignment", "0")
    before = _raw()
    after = deepcopy(before)
    after["addglobalplug"][0]["sid"][0]["outg"] = "0"
    assert contract.verifier is not None
    assert contract.verifier(before, {"incoming": []}, after)
    after["addglobalplug"][1]["plug_outgoing"] = "7"
    assert not contract.verifier(before, {"incoming": []}, after)
    after = deepcopy(before)
    after["addglobalplug"][0]["sid"][0]["outg"] = "0"
    after["addglobalplug"].reverse()
    after["addphonenumber"].reverse()
    assert contract.verifier(before, {"incoming": []}, after)


def test_zero_and_canonical_identifier_rules() -> None:
    """Zero is a valid plug but reserved automatic/no-backup number."""
    for value in ("01", "-1", "../0", 0, None):
        with pytest.raises(ConfigurationError):
            assignment_target_contract("telephony_incoming_assignment", value)  # type: ignore[arg-type]
    raw = _raw()
    raw["addphonenumber"][0]["id"] = "0"
    with pytest.raises(ConfigurationError):
        assignment_target_contract("telephony_incoming_assignment", "0").read(raw)
