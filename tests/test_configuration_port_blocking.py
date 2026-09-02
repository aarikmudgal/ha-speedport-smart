"""Synthetic port-blocking contracts; no network calls or live write tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_port_blocking import (
    PORT_BLOCKING_SETTINGS,
    port_blocking_target_contract,
    port_blocking_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_CREATE = PORT_BLOCKING_SETTINGS[0]
_EDIT = port_blocking_target_contract("port_blocking_edit", "7")
_DELETE = port_blocking_target_contract("port_blocking_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")


def _row(identifier: str = "7", selected: str = "device-a") -> dict[str, Any]:
    return {
        "id": identifier,
        "extendedrule_active": "1",
        "extrule_name": "Blocked services",
        "extrule_tcp": "80,443",
        "extrule_udp": "",
        "sid": [
            {"sid": sid, "mdevice_name": "1" if selected == sid else "0"}
            for sid in ("device-b", "device-a", "device-c")
        ],
    }


def _raw(*, empty: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "extrarule_addmdevice": [
            {
                "sid": sid,
                "mdevice_name": label,
                "mdevice_mac": mac,
                "mdevice_rssi": "-50",
            }
            for sid, label, mac in (
                ("device-a", "Same name", "02:00:00:00:00:01"),
                ("device-b", "Same name", "02:00:00:00:00:02"),
                ("device-c", "Third device", "02:00:00:00:00:03"),
            )
        ],
        "unrelated_counter": "10",
    }
    if not empty:
        raw["addextra"] = [_row("2", "device-b"), _row()]
    return raw


def _changes() -> dict[str, Any]:
    return {
        "extrule_name": "New rule",
        "extendedrule_active": True,
        "extrule_tcp": "0-65535",
        "selected_devices": ["device-b", "device-c"],
    }


def _after(action: str) -> dict[str, Any]:
    raw = _raw()
    if action == "create":
        row = {**_row("15"), "extrule_name": "New rule", "extrule_tcp": "0-65535"}
        for item in row["sid"]:
            item["mdevice_name"] = "0" if item["sid"] == "device-a" else "1"
        raw["addextra"].append(row)
    elif action == "edit":
        raw["addextra"][1]["extrule_tcp"] = "443"
    else:
        raw["addextra"].pop()
    return raw


def test_native_empty_shape_and_compound_checked_state() -> None:
    """Read current bindings, not every available SID or hostname labels."""
    assert _CREATE.read(_raw(empty=True))["selected_devices"] == []
    assert _EDIT.read(_raw())["selected_devices"] == ["device-a"]
    assert _EDIT.choices(_raw())["selected_devices"][:2] == [
        {"value": "device-a", "label": "Same name (device-a)"},
        {"value": "device-b", "label": "Same name (device-b)"},
    ]
    assert "02:00:00" not in str(_EDIT.read(_raw())) + str(_EDIT.choices(_raw()))
    assert port_blocking_target_rows("port_blocking_edit", _raw()) == (
        {"id": "2", "extrule_name": "Blocked services"},
        {"id": "7", "extrule_name": "Blocked services"},
    )


def test_exact_create_wire_fields_use_inventory_first_parent_second_indexes() -> None:
    """Serialize every current SID/flag while omitting the dontsubmit select-all."""
    raw = _raw()
    before = deepcopy(raw)
    assert _CREATE.build(raw, _changes()) == {
        "id": "-1",
        "extendedrule_active": "1",
        "extrule_name": "New rule",
        "portsp_template": "0",
        "extrule_tcp": "0-65535",
        "extrule_udp": "",
        "sid[13]": "device-a",
        "mdevice_name[13]": "0",
        "sid[23]": "device-b",
        "mdevice_name[23]": "1",
        "sid[33]": "device-c",
        "mdevice_name[33]": "1",
    }
    assert raw == before
    assert _CREATE.endpoint == "data/ExtendedRules.json"
    assert _CREATE.referer == "html/content/internet/portblocking.html"
    assert _CREATE.acknowledgement == "status_ok"


def test_existing_edit_preserves_template_and_selection_and_exact_target() -> None:
    """Preserve every untouched native field, including the hidden preset select."""
    raw = _raw()
    raw["addextra"][1]["portsp_template"] = "4"
    payload = _EDIT.build(raw, {"extrule_tcp": "443"})
    assert payload["id"] == "7"
    assert payload["portsp_template"] == "4"
    assert payload["mdevice_name[12]"] == "1"
    assert payload["mdevice_name[22]"] == "0"
    assert payload["sid[32]"] == "device-c"
    assert "selectall" not in payload
    assert "unrelated_counter" not in payload


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "80;443",
        "http",
        "-1",
        "65536",
        "2-1",
        "1-1",
        "1-2-3",
        "80,80",
        "70-90,80",
        "80,",
        "80,,443",
        True,
        80,
    ],
)
def test_invalid_empty_or_overlapping_port_lists_rejected(value: object) -> None:
    """Require a populated protocol and strict bounded comma/range grammar."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), {"extrule_tcp": value})


@pytest.mark.parametrize(
    "changes",
    [
        {"selected_devices": []},
        {"selected_devices": ["unknown"]},
        {"selected_devices": ["device-a", "device-a"]},
        {"selected_devices": "device-a"},
        {"extrule_name": ""},
        {"extrule_name": "<bad>"},
        {"extrule_name": "x" * 21},
        {"extrule_name": "😀"},
        {"extendedrule_active": 1},
        {"id": "2"},
        {"sid[12]": "device-b"},
        {"portsp_template": "13"},
        {"endpoint": "data/Other.json"},
    ],
)
def test_invalid_selections_names_flags_and_wire_injection_rejected(
    changes: dict[str, object],
) -> None:
    """Keep identity, naming and raw transport boundaries closed."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_inventory",
        "duplicate_inventory",
        "missing_mac",
        "missing_sid",
        "legacy_bindings",
        "duplicate_bindings",
        "missing_flag",
        "invalid_flag",
        "missing_rule_name",
        "duplicate_rule",
        "unknown_preset",
    ],
)
def test_incomplete_current_state_fails_closed(mutation: str) -> None:
    """Reject lost checked-state compounds and ambiguous physical identities."""
    raw = _raw()
    row = raw["addextra"][1]
    if mutation == "missing_inventory":
        raw.pop("extrarule_addmdevice")
    elif mutation == "duplicate_inventory":
        raw["extrarule_addmdevice"][1] = raw["extrarule_addmdevice"][0]
    elif mutation == "missing_mac":
        raw["extrarule_addmdevice"][0].pop("mdevice_mac")
    elif mutation == "missing_sid":
        raw["extrarule_addmdevice"][0].pop("sid")
    elif mutation == "legacy_bindings":
        row["sid"] = ["device-a", "device-b", "device-c"]
    elif mutation == "duplicate_bindings":
        row["sid"][0] = row["sid"][1]
    elif mutation == "missing_flag":
        row["sid"][0].pop("mdevice_name")
    elif mutation == "invalid_flag":
        row["sid"][0]["mdevice_name"] = "2"
    elif mutation == "missing_rule_name":
        row.pop("extrule_name")
    elif mutation == "duplicate_rule":
        row["id"] = "2"
    else:
        row["portsp_template"] = "14"
    with pytest.raises(ConfigurationError):
        _EDIT.read(raw)


def test_delete_exact_id_and_explicit_true_and_absence_verification() -> None:
    """Never infer deletion from missing targets or truthy untyped values."""
    assert _DELETE.build(_raw(), {"delete_entry": True}) == {
        "id": "7",
        "deleteEntry": "delete",
    }
    assert _DELETE.read(_after("delete")) == {"delete_entry": True}
    for value in (False, "true", 1, None):
        with pytest.raises(ConfigurationError):
            _DELETE.build(_raw(), {"delete_entry": value})
    with pytest.raises(ConfigurationError):
        _DELETE.build(_after("delete"), {"delete_entry": True})


def test_rule_limit_and_stable_revision_projection() -> None:
    """Bound rule creation while ignoring telemetry but retaining identity."""
    raw = _raw()
    raw["addextra"] = [_row(str(index)) for index in range(64)]
    with pytest.raises(ConfigurationError, match="port_blocking_rule_limit"):
        _CREATE.build(raw, _changes())
    raw = _raw()
    changed = deepcopy(raw)
    changed["extrarule_addmdevice"][0]["mdevice_rssi"] = "-70"
    changed["unrelated_counter"] = "11"
    assert _EDIT.revision(raw) == _EDIT.revision(changed)
    changed["extrarule_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert _EDIT.revision(raw) != _EDIT.revision(changed)


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
async def test_real_session_one_write_then_exact_full_collection_readback(
    action: str,
) -> None:
    """Exercise actual grants, positive transport completion and fresh state proof."""
    contract, changes = (
        (_CREATE, _changes())
        if action == "create"
        else (_EDIT, {"extrule_tcp": "443"})
        if action == "edit"
        else (_DELETE, {"delete_entry": True})
    )
    before, after = _raw(), _after(action)
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    assert not contract.verifier(before, changes, before)
    changed = deepcopy(after)
    changed["addextra"][0]["extrule_name"] = "Collateral change"
    assert not contract.verifier(before, changes, changed)
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()


async def test_ack_echo_without_persistence_never_retries_write() -> None:
    """Do not equate a write echo with independently observed selected membership."""
    read, write = (
        AsyncMock(return_value=_raw()),
        AsyncMock(return_value={"status": "ok"}),
    )
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            _changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
