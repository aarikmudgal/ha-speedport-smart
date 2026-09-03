"""Exact nested range CRUD using only synthetic complete parent snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from test_configuration_port_rules import _range, _raw

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_port_rules import (
    port_rule_target_contract,
    port_rule_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_CREATE = port_rule_target_contract("port_forward_range_create", "7")
_EDIT = port_rule_target_contract("port_forward_range_edit", "7:tcp:9")
_DELETE = port_rule_target_contract("port_forward_range_delete", "7:tcp:9")
_OWNER = ("synthetic-admin", "synthetic-session")
_NEW = {"public_start": 6000, "public_end": 6002, "destination_start": 7000}


def test_dynamic_targets_bind_parent_protocol_and_stable_range_id() -> None:
    """List exact composite identities; positions remain private wire context."""
    rows = port_rule_target_rows("port_forward_range_edit", _raw())
    assert [row["id"] for row in rows] == ["2:tcp:11", "7:tcp:4", "7:tcp:9", "7:udp:6"]
    assert rows[2]["portuw_name"] == "Current: TCP 8443 (ID 9)"
    assert _EDIT.read(_raw()) == {
        "public_start": 8443,
        "public_end": 0,
        "destination_start": 443,
    }
    assert _CREATE.read(_raw()) == {
        "protocol": "tcp",
        "public_start": 0,
        "public_end": 0,
        "destination_start": 0,
    }


def test_append_range_preserves_parent_and_every_existing_protocol_row() -> None:
    """Append one fresh -1 range at the next native child ordinal."""
    raw = _raw()
    before = deepcopy(raw)
    payload = _CREATE.build(raw, _NEW)
    assert payload["id"] == "7"
    assert payload["portuwtcp_id[21]"] == "4"
    assert payload["portuwtcp_id[22]"] == "9"
    assert payload["portuwtcp_id[23]"] == "-1"
    assert payload["tcp_public_from[23]"] == "6000"
    assert payload["tcp_private_dest[23]"] == "7000"
    assert "tcp_private_to[23]" not in payload
    assert payload["portuwudp_id[21]"] == "6"
    assert raw == before
    udp = _CREATE.build(raw, {**_NEW, "protocol": "udp"})
    assert udp["portuwudp_id[22]"] == "-1"
    assert "portuwtcp_id[23]" not in udp


def test_range_edit_keeps_selected_id_and_all_sibling_fields() -> None:
    """Edit one exact range using the full preserved parent form."""
    payload = _EDIT.build(_raw(), {"destination_start": 9443})
    assert payload["portuwtcp_id[22]"] == "9"
    assert payload["tcp_private_dest[22]"] == "9443"
    assert payload["tcp_public_from[22]"] == "8443"
    assert payload["tcp_public_to[22]"] == ""
    assert payload["portuwtcp_id[21]"] == "4"
    assert payload["tcp_private_dest[21]"] == "80"
    assert payload["portuwudp_id[21]"] == "6"


def test_native_range_removal_retains_exact_id_and_blanks_only_its_three_inputs() -> (
    None
):
    """Mirror validated blank-row submission; invent no nested delete endpoint."""
    payload = _DELETE.build(_raw(), {"delete_entry": True})
    assert payload["id"] == "7"
    assert payload["portuwtcp_id[22]"] == "9"
    assert payload["tcp_public_from[22]"] == ""
    assert payload["tcp_public_to[22]"] == ""
    assert payload["tcp_private_dest[22]"] == ""
    assert payload["tcp_public_from[21]"] == "8080"
    assert not any("deleteEntry" in name or "private_to" in name for name in payload)


def test_last_range_requires_explicit_whole_parent_deletion() -> None:
    """Native validation requires at least one populated range per saved rule."""
    contract = port_rule_target_contract("port_forward_range_delete", "2:tcp:11")
    with pytest.raises(ConfigurationError, match="delete_empty_parent_rule_instead"):
        contract.build(_raw(), {"delete_entry": True})


@pytest.mark.parametrize(
    "target",
    [
        "7",
        "7:tcp",
        "07:tcp:9",
        "7:udp:09",
        "7:icmp:9",
        "7:tcp:-1",
        "7:tcp:9:2",
        "../7:tcp:9",
        7,
        None,
    ],
)
def test_nested_target_requires_canonical_parent_protocol_and_range(
    target: object,
) -> None:
    """Reject coercion, traversal, protocol ambiguity and malformed composite IDs."""
    with pytest.raises(ConfigurationError):
        port_rule_target_contract("port_forward_range_edit", target)  # type: ignore[arg-type]


@pytest.mark.parametrize("target", ["7:tcp:11", "2:tcp:9", "7:udp:9", "99:tcp:9"])
def test_matching_range_number_in_another_parent_or_protocol_is_not_authority(
    target: str,
) -> None:
    """Never resolve a range by its ID alone when its parent/protocol differ."""
    contract = port_rule_target_contract("port_forward_range_edit", target)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        contract.build(_raw(), {"destination_start": 9443})


@pytest.mark.parametrize(
    "changes",
    [
        {"public_start": 8081, "destination_start": 9001},
        {"public_start": 80, "destination_start": 80},
        {"public_start": 0},
        {"destination_start": 65536},
        {"public_end": 8442},
        {"public_end": 8443},
        {"id": "4"},
        {"portuwtcp_id[22]": "4"},
        {"protocol": "udp"},
        {"destination_start": True},
    ],
)
def test_range_edit_rejects_collisions_invalid_values_and_target_substitution(
    changes: dict[str, object],
) -> None:
    """Changing one range cannot expand into another range, protocol or key."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


def test_per_protocol_range_limit_and_derived_overflow() -> None:
    """Bound append count and the derived destination end."""
    raw = _raw()
    raw["addportuw"][1]["addtcpportuw"] = [
        _range("tcp", str(index), str(10000 + index), "", str(10000 + index))
        for index in range(32)
    ]
    with pytest.raises(ConfigurationError, match="port_range_limit"):
        _CREATE.build(raw, _NEW)
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw(), {**_NEW, "destination_start": 65535})


def _changed(action: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    after = _raw()
    if action == "create":
        after["addportuw"][1]["addtcpportuw"].append(
            _range("tcp", "40", "6000", "6002", "7000")
        )
        return _CREATE, _NEW, after
    if action == "edit":
        after["addportuw"][1]["addtcpportuw"][1]["tcp_private_dest"] = "9443"
        return _EDIT, {"destination_start": 9443}, after
    after["addportuw"][1]["addtcpportuw"].pop()
    return _DELETE, {"delete_entry": True}, after


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
def test_verifier_requires_exact_nested_change_and_every_unchanged_sibling(
    action: str,
) -> None:
    """No assigned-ID echo, wrong range or collateral rule mutation proves success."""
    contract, changes, after = _changed(action)
    before = _raw()
    assert contract.verifier(before, changes, after)
    assert not contract.verifier(before, changes, before)
    changed = deepcopy(after)
    changed["addportuw"][0]["portuw_name"] = "Collateral sibling"
    assert not contract.verifier(before, changes, changed)
    changed = deepcopy(after)
    changed["addportuw"][1]["addtcpportuw"][0]["portuwtcp_id"] = "400"
    assert not contract.verifier(before, changes, changed)
    changed = deepcopy(after)
    changed["portuw_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert not contract.verifier(before, changes, changed)


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
async def test_real_session_one_write_and_independent_nested_readback(
    action: str,
) -> None:
    """Exercise the actual requester-bound session using synthetic transport only."""
    contract, changes, after = _changed(action)
    read, write = AsyncMock(side_effect=[_raw(), _raw(), after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    result = await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once()


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
def test_payload_validator_requires_entire_preserved_parent_form(action: str) -> None:
    """Reject missing siblings, wrong selected IDs and extra caller fields."""
    contract, changes, _ = _changed(action)
    raw = _raw()
    payload = contract.build(raw, changes)
    assert contract.payload_validator(raw, payload)
    for key, value in (
        ("id", "2"),
        ("portuwtcp_id[21]", "99"),
        ("arbitrary", "data/Other.json"),
    ):
        assert not contract.payload_validator(raw, {**payload, key: value})
    payload.pop("portuwudp_id[21]")
    assert not contract.payload_validator(raw, payload)
