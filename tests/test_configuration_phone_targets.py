"""Offline exact telephone row forms; no router interaction or live writes."""

# ruff: noqa: S105, S106 - synthetic credentials only

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phone_targets import (
    PHONE_TARGET_SPECS,
    phone_target_contract,
    phone_target_metadata,
    phone_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession


def _lines() -> dict[str, Any]:
    return {
        "addphonenumber": [
            {
                "id": "8",
                "sid": "4",
                "phone_number": "00000001",
                "phone_number_type": "1",
                "line": "0",
                "clir": "0",
                "reject_on_busy": "0",
            },
            {
                "id": "3",
                "sid": "6",
                "phone_number": "00000002",
                "phone_number_type": "1",
                "line": "1",
                "clir": "1",
                "reject_on_busy": "1",
            },
        ]
    }


def _devices(setting_id: str = "telephony_analog_socket") -> dict[str, Any]:
    spec = PHONE_TARGET_SPECS[setting_id]
    row = {
        "id": "0",
        spec.label_key: "Office",
        "plug_outgoing": "0",
        "sid": [
            {"sid": "4", "ring_incoming": "1"},
            {"sid": "6", "ring_incoming": "0"},
        ],
    }
    if setting_id == "telephony_analog_socket":
        row.update(plug_type="0", plug_use_out_of_order_signaling="1")
    elif setting_id == "telephony_dect_handset":
        row.update(dect_cws="1")
    else:
        row.update(ipclient_password="Safe-Pass1", ipclient_status="0")
    return {
        spec.collection: row,
        "addphonenumber"
        if setting_id == "telephony_analog_socket"
        else "outgoing_addphonenumber": [
            {"sid": "4", "phone_number": "00000001", "phone_number_type": "1"},
            {"sid": "6", "phone_number": "00000002", "phone_number_type": "1"},
        ],
    }


def test_metadata_is_static_target_required_and_has_no_private_values() -> None:
    """Catalog entries describe real typed forms, not invented target rows."""
    for item in phone_target_metadata():
        assert item.pop("requires_target") is True
        contract = phone_target_contract(item["id"], "0")
        assert item == contract.metadata()
        assert item["live_write_verified"] is False
        assert item["confirmation"] == "SAVE PHONE SETTINGS"
        assert "Office" not in str(item)
        assert "Safe-Pass1" not in str(item)


def test_line_form_preserves_every_sibling_and_uses_dom_order_not_row_id() -> None:
    """A single outer form sends all telephone-number rows with ordinal brackets."""
    raw = _lines()
    before = deepcopy(raw)
    contract = phone_target_contract("telephony_line_options", "8")
    assert contract.build(raw, {"clir": True}) == {
        "id[1]": "8",
        "line[1]": "0",
        "clir[1]": 1,
        "reject_on_busy[1]": 0,
        "id[2]": "3",
        "line[2]": "1",
        "clir[2]": 1,
        "reject_on_busy[2]": 1,
    }
    assert raw == before
    assert contract.field_choices is None


def test_busy_toggle_derives_single_line_and_conflicting_changes_fail() -> None:
    """Mirror firmware busy click handling and include derived state verification."""
    contract = phone_target_contract("telephony_line_options", "8")
    assert contract.build(_lines(), {"reject_on_busy": True})["line[1]"] == "1"
    assert contract.expected_values is not None
    assert contract.expected_values(_lines(), {"reject_on_busy": True}) == {
        "clir": False,
        "reject_on_busy": True,
        "line": "1",
    }
    with pytest.raises(ConfigurationError):
        contract.build(_lines(), {"reject_on_busy": True, "line": "0"})
    with pytest.raises(ConfigurationError):
        phone_target_contract("telephony_line_options", "3").build(
            _lines(), {"line": "0"}
        )


def test_analog_payload_preserves_compound_assignment_and_identity() -> None:
    """Compound SIDs must retain their incoming flags; never flatten the selection."""
    contract = phone_target_contract("telephony_analog_socket", "0")
    raw = _devices()
    before = deepcopy(raw)
    assert contract.build(raw, {"plug_name": "Bedroom"}) == {
        "id": "0",
        "plug_name": "Bedroom",
        "plug_type": "0",
        "plug_use_out_of_order_signaling": 1,
        "plug_outgoing": "0",
        "selectall_deselectnone": 0,
        "sid[11]": "4",
        "ring_incoming[11]": 1,
        "sid[12]": "6",
        "ring_incoming[12]": 0,
    }
    assert raw == before
    assert contract.read(raw)["ring_incoming"] == ["4"]
    assert contract.choices(raw)["plug_outgoing"] == [
        {"value": "0", "label": "Automatic"},
        {"value": "4", "label": "00000001"},
        {"value": "6", "label": "00000002"},
    ]


def test_nested_template_indexes_use_selected_outer_row_ordinal() -> None:
    """The second target's child names concatenate outer and inner ordinals."""
    raw = _devices("telephony_dect_handset")
    first = raw["adddect"]
    raw["adddect"] = [first, {**deepcopy(first), "id": "9"}]
    payload = phone_target_contract("telephony_dect_handset", "9").build(
        raw, {"ring_incoming": ["6", "4"], "plug_outgoing": "6"}
    )
    assert payload == {
        "id": "9",
        "dect_mobile_name": "Office",
        "dect_cws": 1,
        "plug_outgoing": "6",
        "selectall_deselectnone": 1,
        "sid[21]": "4",
        "ring_incoming[21]": 1,
        "sid[22]": "6",
        "ring_incoming[22]": 1,
    }


def test_analog_hidden_call_waiting_and_type_change_rules() -> None:
    """Non-telephone equipment hides CW; selecting telephone defaults CW enabled."""
    contract = phone_target_contract("telephony_analog_socket", "0")
    raw = _devices()
    payload = contract.build(raw, {"plug_type": "2"})
    assert "plug_use_out_of_order_signaling" not in payload
    with pytest.raises(ConfigurationError):
        contract.build(
            raw, {"plug_type": "2", "plug_use_out_of_order_signaling": False}
        )
    raw["phone_plugs"].update(plug_type="2", plug_use_out_of_order_signaling="0")
    assert (
        contract.build(raw, {"plug_type": "0"})["plug_use_out_of_order_signaling"] == 1
    )
    assert (
        contract.build(
            raw, {"plug_type": "0", "plug_use_out_of_order_signaling": False}
        )["plug_use_out_of_order_signaling"]
        == 0
    )


@pytest.mark.parametrize("target", [None, "", "../4", "4\n", "-1", 0, True])
def test_invalid_target_fails_closed(target: object) -> None:
    """External target arguments cannot coerce into a different row or URL."""
    with pytest.raises(ConfigurationError):
        phone_target_contract("telephony_analog_socket", target)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "collection", [None, {}, "", ["4"], [{"id": "0"}, {"id": "0"}]]
)
def test_missing_malformed_or_duplicate_rows_are_not_empty(collection: object) -> None:
    """An ambiguous response must never authorize a partial-row write."""
    with pytest.raises(ConfigurationError):
        phone_target_rows("telephony_analog_socket", {"phone_plugs": collection})
    assert phone_target_rows("telephony_analog_socket", {"phone_plugs": []}) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "9"},
        {"ring_incoming[11]": "0"},
        {"plug_name": "<bad>"},
        {"plug_name": "bad\x7f"},
        {"plug_type": "4"},
        {"plug_outgoing": "7"},
        {"ring_incoming": ["7"]},
        {"ring_incoming": ["4", "4"]},
        {"ring_incoming": "4"},
        {"ring_incoming": [4]},
        {"plug_use_out_of_order_signaling": "0"},
    ],
)
def test_unreviewed_changes_never_form_payload(changes: dict[str, Any]) -> None:
    """No raw form keys, coercion, unknown SID or HTML name enters a builder."""
    with pytest.raises(ConfigurationError):
        phone_target_contract("telephony_analog_socket", "0").build(_devices(), changes)


@pytest.mark.parametrize(
    "assignments",
    [
        ["4", "6"],
        [{"sid": "4"}],
        [{"sid": "4", "ring_incoming": "yes"}],
        [{"sid": "0", "ring_incoming": "1"}],
        [{"sid": "4", "ring_incoming": "1"}, {"sid": "4", "ring_incoming": "0"}],
    ],
)
def test_lost_compounds_or_incomplete_assignment_inventory_fails(
    assignments: object,
) -> None:
    """Old flattened decoding and guessed all-selected assignments are forbidden."""
    raw = _devices()
    raw["phone_plugs"]["sid"] = assignments
    with pytest.raises(ConfigurationError):
        phone_target_contract("telephony_analog_socket", "0").read(raw)


def test_selected_row_and_siblings_must_match_independent_readback() -> None:
    """A correct target value alone cannot hide collateral sibling changes."""
    contract = phone_target_contract("telephony_line_options", "8")
    before = _lines()
    after = deepcopy(before)
    after["addphonenumber"][0]["clir"] = "1"
    assert contract.verifier is not None
    assert contract.verifier(before, {"clir": True}, after)
    after["addphonenumber"][1]["clir"] = "0"
    assert not contract.verifier(before, {"clir": True}, after)
    after = deepcopy(before)
    after["addphonenumber"][0].update(clir="1", phone_number="00000099")
    assert not contract.verifier(before, {"clir": True}, after)


def test_ip_phone_secret_is_not_exposed_and_masked_password_requires_reentry() -> None:
    """Full IP phone forms preserve valid credentials but never send mask literals."""
    contract = phone_target_contract("telephony_ip_phone", "0")
    raw = _devices("telephony_ip_phone")
    assert "ipclient_password" not in contract.read(raw)
    assert "Safe-Pass1" not in repr(contract)
    assert (
        contract.build(raw, {"ipclient_name": "Living room"})["ipclient_password"]
        == "Safe-Pass1"
    )
    raw["addipclient"]["ipclient_password"] = "********"
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"ipclient_name": "Living room"})
    assert (
        contract.build(raw, {"ipclient_password": "New-Pass1"})["ipclient_password"]
        == "New-Pass1"
    )
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"ipclient_password": "bad[pass]"})
    for password in ("abcdefgh", "ABCDEFGH", "12345678", "!!!!!!!!"):
        with pytest.raises(ConfigurationError):
            contract.build(raw, {"ipclient_password": password})


@pytest.mark.asyncio
async def test_session_derives_busy_radio_verifies_once_and_consumes_revision() -> None:
    """Independent GET readback verifies a full indexed form; writes never retry."""
    contract = phone_target_contract("telephony_line_options", "8")
    state = _lines()
    session = ConfigurationSession()
    writes = []

    async def read() -> dict[str, Any]:
        return deepcopy(state)

    async def write(raw: dict[str, Any], changes: dict[str, Any]) -> None:
        payload = contract.build(raw, changes)
        writes.append(payload)
        state["addphonenumber"][0].update(reject_on_busy="1", line="1")

    loaded = await session.read(contract, ("admin", "connection"), read)
    arguments = {
        "confirmed": True,
        "confirmation_text": "SAVE PHONE SETTINGS",
        "read": read,
        "write": write,
    }
    assert await session.save(
        contract,
        ("admin", "connection"),
        loaded["revision"],
        {"reject_on_busy": True},
        **arguments,
    ) == {"status": "verified"}
    assert len(writes) == 1
    with pytest.raises(ConfigurationError):
        await session.save(
            contract,
            ("admin", "connection"),
            loaded["revision"],
            {"reject_on_busy": True},
            **arguments,
        )
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_revision_binds_private_assignment_choice_inventory() -> None:
    """Changing a number label/SID after manual load invalidates the edit grant."""
    contract = phone_target_contract("telephony_analog_socket", "0")
    state = _devices()
    session = ConfigurationSession()
    writes = []

    async def read() -> dict[str, Any]:
        return deepcopy(state)

    async def write(raw: dict[str, Any], changes: dict[str, Any]) -> None:
        writes.append(contract.build(raw, changes))

    loaded = await session.read(contract, ("admin", "connection"), read)
    state["addphonenumber"][0]["phone_number"] = "00000099"
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            ("admin", "connection"),
            loaded["revision"],
            {"plug_name": "Bedroom"},
            confirmed=True,
            confirmation_text="SAVE PHONE SETTINGS",
            read=read,
            write=write,
        )
    assert writes == []
