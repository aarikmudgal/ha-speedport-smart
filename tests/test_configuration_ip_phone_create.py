"""Offline IP phone creation proof; no router requests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_ip_phone_create import (
    ip_phone_create_contract,
    ip_phone_create_metadata,
    ip_phone_created_id,
)


def _row(identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "ipclient_name": "IP phone",
        "ipclient_password": "Abcd1234",
        "ipclient_status": "0",
        "plug_outgoing": "0",
        "sid": [{"sid": "1", "ring_incoming": "1"}],
    }


def test_metadata_static_and_native_allocation_payload_exact() -> None:
    """Allocate with the command, not a guessed new-row form."""
    contract = ip_phone_create_contract()
    assert ip_phone_create_metadata() == [contract.metadata()]
    assert contract.endpoint == "data/IPClients.json"
    assert contract.read_endpoint == "data/IPPBX.json"
    assert contract.build({"addipclient": []}, {"create": True}) == {
        "add_ipcl": "add ip phone"
    }
    assert "Abcd1234" not in repr(contract)


@pytest.mark.parametrize("changes", [{}, {"create": False}, {"create": 1}, {"id": "1"}])
def test_only_typed_explicit_create_forms_command(changes: dict[str, Any]) -> None:
    """Require an explicit boolean change and reject arbitrary wire fields."""
    with pytest.raises(ConfigurationError):
        ip_phone_create_contract().build({"addipclient": []}, changes)


def test_capacity_and_ambiguous_inventory_fail_closed() -> None:
    """Enforce the three-client hardware limit without guessing missing lists."""
    contract = ip_phone_create_contract()
    with pytest.raises(ConfigurationError, match="settings_capacity_reached"):
        contract.read({"addipclient": [_row("1"), _row("2"), _row("3")]})
    for rows in (None, {}, [_row("1"), _row("1")], [_row(str(i)) for i in range(4)]):
        with pytest.raises(ConfigurationError):
            contract.read({"addipclient": rows})


@pytest.mark.parametrize("value", [None, 1, "", "../1", "x" * 65])
def test_native_response_requires_bounded_newest_id(value: object) -> None:
    """Missing or unsafe returned IDs do not prove allocation."""
    validator = ip_phone_create_contract().response_validator
    assert validator is not None
    with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
        validator({"newestID": value})


def test_one_added_row_and_unchanged_siblings_required() -> None:
    """Bind independent added-row proof to the native newestID."""
    contract = ip_phone_create_contract()
    before = {"addipclient": [_row("1")]}
    after = {"addipclient": [_row("1"), _row("2")], "_created_ip_phone_id": "2"}
    assert ip_phone_created_id(before, {"newestID": "2"}) == "2"
    with pytest.raises(ConfigurationError):
        ip_phone_created_id(before, {"newestID": "1"})
    assert contract.verifier is not None
    assert contract.verifier(before, {"create": True}, after)
    collateral = deepcopy(after)
    collateral["addipclient"][0]["ipclient_name"] = "Changed"
    assert not contract.verifier(before, {"create": True}, collateral)
    assert not contract.verifier(before, {"create": True}, before)
    assert not contract.verifier(
        before, {"create": True}, {"addipclient": [*after["addipclient"], _row("3")]}
    )
