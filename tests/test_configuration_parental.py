"""Synthetic parental form contracts and sessions; no network or live writes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_parental import (
    PARENTAL_SETTINGS,
    parental_target_contract,
    parental_target_metadata,
    parental_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_CREATE = PARENTAL_SETTINGS[0]
_EDIT = parental_target_contract("parental_profile_edit", "7")
_DELETE = parental_target_contract("parental_profile_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")
_DAYS = ("d", "mo", "di", "mi", "do", "fr", "sa", "so")
_TIME_NAMES = tuple(
    f"trule_{day}{'_' if day != 'd' else ''}{direction}{suffix}"
    for day in _DAYS
    for suffix in ("", "2", "3")
    for direction in ("from", "to")
)
_BUDGET_NAMES = ("tr_dmaxtime", *(f"tr_{day}_maxtime" for day in _DAYS[1:]))
_SCHEDULE_NAMES = (*_TIME_NAMES, *_BUDGET_NAMES)
_SIDS = ("device-a", "device-b", "device-c")


def _row(identifier: str = "7", selected: str = "device-a") -> dict[str, Any]:
    return {
        "id": identifier,
        "timerule_name": "Children",
        "timerule_active": "1",
        "trule_allusebudget": "0",
        **dict.fromkeys(_SCHEDULE_NAMES, ""),
        "trule_dfrom": "08:00",
        "trule_dto": "20:00",
        "sid": [
            {"sid": sid, "mdevice_name": "1" if selected == sid else "0"}
            for sid in reversed(_SIDS)
        ],
    }


def _raw(*, empty: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "timerule_addmdevice": [
            {
                "sid": sid,
                "mdevice_name": "Same label",
                "mdevice_mac": f"02:00:00:00:00:0{index}",
                "mdevice_rssi": "-50",
            }
            for index, sid in enumerate(_SIDS, 1)
        ],
        "unrelated_counter": "10",
    }
    if not empty:
        raw["addtime"] = [_row("2", "device-b"), _row()]
    return raw


def _create_changes() -> dict[str, Any]:
    return {
        "timerule_name": "New profile",
        "timerule_active": True,
        "selected_devices": ["device-c"],
        "trule_dfrom": "08:00",
        "trule_dto": "20:00",
    }


def _after(action: str) -> dict[str, Any]:
    raw = _raw()
    if action == "create":
        row = _row("15", "device-c")
        row["timerule_name"] = "New profile"
        raw["addtime"].append(row)
    elif action == "edit":
        raw["addtime"][1]["timerule_name"] = "Updated profile"
    elif action == "budget":
        raw["addtime"][1]["tr_dmaxtime"] = "60"
        raw["addtime"][1]["trule_dfrom"] = "00:00"
        raw["addtime"][1]["trule_dto"] = "24:00"
    elif action == "weekly":
        raw["addtime"][1]["trule_dfrom"] = ""
        raw["addtime"][1]["trule_dto"] = ""
        raw["addtime"][1]["trule_mo_from"] = "10:00"
        raw["addtime"][1]["trule_mo_to"] = "18:00"
    else:
        raw["addtime"].pop()
    return raw


def test_native_singleton_shape_full_schedule_and_exclusive_choices() -> None:
    """Expose public typed state, not physical identity or available-as-selected."""
    raw = _raw()
    raw["addtime"][0]["timerule_active"] = "0"
    values = _EDIT.read(raw)
    assert len(values) == 61
    assert values["selected_devices"] == ["device-a"]
    assert values["schedule_mode"] == "daily"
    assert values["tr_dmaxtime"] == 0
    assert _EDIT.choices(raw)["selected_devices"] == [
        {"value": "device-a", "label": "Same label (device-a)"},
        {"value": "device-c", "label": "Same label (device-c)"},
    ]
    assert "02:00:00" not in str(values) + str(_EDIT.choices(raw))
    raw["addtime"] = raw["addtime"][1]
    assert _EDIT.read(raw) == values
    assert _CREATE.read(_raw(empty=True))["timerule_name"] == ""
    assert parental_target_rows("parental_profile_edit", raw) == (
        {"id": "7", "timerule_name": "Children"},
    )
    assert all(item["requires_target"] for item in parental_target_metadata())


def test_full_wire_map_preserves_untouched_fields_and_device_first_ordinals() -> None:
    """All 56 schedule inputs always submit, including dormant weekday values."""
    raw = _raw()
    raw["addtime"][1]["trule_mo_from"] = "11:00"
    raw["addtime"][1]["trule_mo_to"] = "12:00"
    before = deepcopy(raw)
    payload = _EDIT.build(raw, {"trule_allusebudget": True})
    assert payload == {
        "id": "7",
        "timerule_name": "Children",
        "timerule_active": "1",
        "trule_allusebudget": "1",
        "show_day": "0",
        **{key: raw["addtime"][1][key] for key in _SCHEDULE_NAMES},
        "sid[12]": "device-a",
        "mdevice_name[12]": "1",
        "sid[22]": "device-b",
        "mdevice_name[22]": "0",
        "sid[32]": "device-c",
        "mdevice_name[32]": "0",
    }
    assert len(payload) == 67
    assert raw == before
    assert _EDIT.endpoint == "data/TimeRules.json"
    assert _EDIT.referer == "html/content/internet/chd_timerules.html"
    assert _EDIT.acknowledgement == "status_ok"


@pytest.mark.parametrize("mode", ["daily", "weekly"])
def test_create_exact_sentinel_and_explicit_schedule(mode: str) -> None:
    """Create only from explicit name, assignment and allowed schedule fields."""
    changes = _create_changes()
    if mode == "weekly":
        changes.pop("trule_dfrom")
        changes.pop("trule_dto")
        changes.update(
            schedule_mode="weekly",
            trule_mo_from="08:00",
            trule_mo_to="12:00",
            trule_fr_from="10:00",
            trule_fr_to="20:00",
        )
    payload = _CREATE.build(_raw(), changes)
    assert payload["id"] == "-1"
    assert payload["show_day"] == ("0" if mode == "daily" else "fr")
    assert payload["mdevice_name[33]"] == "1"
    assert payload["tr_dmaxtime"] == ""
    assert _CREATE.payload_validator is not None
    assert _CREATE.payload_validator(_raw(), payload)


@pytest.mark.parametrize("mode", ["daily", "weekly"])
def test_mode_switch_clears_opposite_schedule_and_expected_values(mode: str) -> None:
    """Derived clears are accepted by the strict payload validator and readback."""
    raw = _raw() if mode == "weekly" else _after("weekly")
    changes = (
        {"schedule_mode": "weekly", "trule_mo_from": "10:00", "trule_mo_to": "18:00"}
        if mode == "weekly"
        else {"schedule_mode": "daily", "trule_dfrom": "09:00", "trule_dto": "17:00"}
    )
    payload = _EDIT.build(raw, changes)
    assert _EDIT.expected_values is not None
    expected = _EDIT.expected_values(raw, changes)
    inactive = "trule_dfrom" if mode == "weekly" else "trule_mo_from"
    assert payload[inactive] == expected[inactive] == ""
    assert expected["schedule_mode"] == mode
    assert payload["show_day"] == ("mo" if mode == "weekly" else "0")


def test_budget_without_windows_gets_explicit_full_day_and_expected_readback() -> None:
    """Mirror native budget blur behavior without treating zero as a wire budget."""
    changes = {"tr_dmaxtime": 60, "trule_dfrom": "", "trule_dto": ""}
    payload = _EDIT.build(_raw(), changes)
    assert payload["trule_dfrom"] == "00:00"
    assert payload["trule_dto"] == "24:00"
    assert payload["tr_dmaxtime"] == "60"
    assert _EDIT.expected_values is not None
    assert _EDIT.expected_values(_raw(), changes)["trule_dto"] == "24:00"
    assert _EDIT.verifier is not None
    assert _EDIT.verifier(_raw(), changes, _after("budget"))
    for budget in (0, 1, 1440):
        assert _EDIT.build(_raw(), {"tr_dmaxtime": budget})["tr_dmaxtime"] == (
            str(budget) if budget else ""
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"trule_dfrom": "24:00"},
        {"trule_dto": "24:01"},
        {"trule_dfrom": "8:00"},
        {"trule_dfrom": "22:00", "trule_dto": "04:00"},
        {"trule_dto": ""},
        {"trule_dfrom": "", "trule_dto": ""},
        {"trule_dfrom2": "20:00", "trule_dto2": "21:00"},
        {"trule_dfrom2": "10:00", "trule_dto2": "11:00"},
        {"trule_dfrom2": "07:00", "trule_dto2": "21:00"},
        {"trule_mo_from": "10:00", "trule_mo_to": "11:00"},
        {"tr_dmaxtime": -1},
        {"tr_dmaxtime": 1441},
        {"tr_dmaxtime": True},
        {"tr_dmaxtime": "60"},
        {"selected_devices": []},
        {"selected_devices": ["device-b"]},
        {"selected_devices": ["unknown"]},
        {"selected_devices": ["device-a", "device-a"]},
        {"timerule_name": ""},
        {"timerule_name": "<bad>"},
        {"timerule_name": "x" * 21},
        {"timerule_name": "😀"},
        {"timerule_active": 1},
        {"trule_allusebudget": 1},
        {"schedule_mode": "monthly"},
        {"id": "2"},
        {"sid[12]": "device-b"},
        {"show_day": "mo"},
        {"endpoint": "data/Other.json"},
    ],
)
def test_invalid_schedule_assignment_and_raw_injection_rejected(
    changes: dict[str, object],
) -> None:
    """Fail closed for malformed times, budgets, assignments and transport keys."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_time",
        "missing_budget",
        "zero_wire_budget",
        "invalid_time",
        "duplicate_assignment",
        "duplicate_rule",
        "missing_flag",
        "partial_bindings",
        "legacy_bindings",
        "missing_mac",
        "unknown_id",
        "missing_inventory",
    ],
)
def test_incomplete_or_ambiguous_current_state_rejected(mutation: str) -> None:
    """Never preserve malformed current fields or conflate membership with inventory."""
    raw = _raw()
    row = raw["addtime"][1]
    if mutation == "missing_time":
        row.pop("trule_so_to3")
    elif mutation == "missing_budget":
        row.pop("tr_dmaxtime")
    elif mutation == "zero_wire_budget":
        row["tr_dmaxtime"] = "0"
    elif mutation == "invalid_time":
        row["trule_dfrom"] = "26:00"
    elif mutation == "duplicate_assignment":
        row["sid"] = deepcopy(raw["addtime"][0]["sid"])
        raw["addtime"][0]["timerule_active"] = "0"
    elif mutation == "duplicate_rule":
        row["id"] = "2"
    elif mutation == "missing_flag":
        row["sid"][0].pop("mdevice_name")
    elif mutation == "partial_bindings":
        row["sid"].pop()
    elif mutation == "legacy_bindings":
        row["sid"] = list(_SIDS)
    elif mutation == "missing_mac":
        raw["timerule_addmdevice"][0].pop("mdevice_mac")
    elif mutation == "unknown_id":
        row["id"] = "-1"
    else:
        raw.pop("timerule_addmdevice")
    with pytest.raises(ConfigurationError):
        _EDIT.read(raw)


def test_exact_payload_validator_rejects_tampering_and_dormant_changes() -> None:
    """The key set, parent ID, indexes, selector and preserved fields are fixed."""
    raw = _raw()
    payload = _EDIT.build(raw, {"timerule_name": "Renamed"})
    assert _EDIT.payload_validator is not None
    for key, value in (
        ("id", "2"),
        ("extra", "1"),
        ("sid[12]", "device-b"),
        ("show_day", "mo"),
        ("trule_mo_from", "10:00"),
        ("tr_mo_maxtime", "60"),
    ):
        assert not _EDIT.payload_validator(raw, {**payload, key: value})
    incomplete = dict(payload)
    incomplete.pop("trule_so_to3")
    assert not _EDIT.payload_validator(raw, incomplete)


def test_delete_exact_target_requires_true_and_stale_target_never_writes() -> None:
    """Deletion removes only the selected profile through the native delete form."""
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


def test_stable_revision_excludes_counters_but_retains_device_identity() -> None:
    """Telemetry does not stale a draft; physical identity and membership do."""
    raw, changed = _raw(), _raw()
    changed["unrelated_counter"] = "11"
    changed["timerule_addmdevice"][0]["mdevice_rssi"] = "-70"
    assert _EDIT.revision(raw) == _EDIT.revision(changed)
    changed["timerule_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert _EDIT.revision(raw) != _EDIT.revision(changed)


def test_native_hyphen_mac_inventory_normalizes_but_mixed_separators_fail() -> None:
    """V17 inventory uses hyphens; delimiter style is not physical identity."""
    raw, native = _raw(), _raw()
    for row in native["timerule_addmdevice"]:
        row["mdevice_mac"] = row["mdevice_mac"].replace(":", "-").upper()
    assert _EDIT.read(native) == _EDIT.read(raw)
    assert _EDIT.revision(native) == _EDIT.revision(raw)
    assert _EDIT.build(native, {"timerule_active": False}) == _EDIT.build(
        raw, {"timerule_active": False}
    )
    native["timerule_addmdevice"][0]["mdevice_mac"] = "02-00:00-00-00-01"
    with pytest.raises(ConfigurationError):
        _EDIT.read(native)


def test_profile_and_device_limits_match_reviewed_global_constants() -> None:
    """At most 32 profiles and 253 devices, with assignment exclusivity retained."""
    raw = _raw(empty=True)
    raw["timerule_addmdevice"] = [
        {
            "sid": f"device-{index}",
            "mdevice_name": f"Device {index}",
            "mdevice_mac": f"02:00:00:00:00:{index:02x}",
        }
        for index in range(253)
    ]
    raw["addtime"] = []
    for index in range(32):
        row = _row(str(index))
        row["sid"] = [
            {
                "sid": device["sid"],
                "mdevice_name": "1" if ordinal == index else "0",
            }
            for ordinal, device in enumerate(raw["timerule_addmdevice"])
        ]
        raw["addtime"].append(row)
    assert len(parental_target_rows("parental_profile_edit", raw)) == 32
    with pytest.raises(ConfigurationError, match="parental_profile_limit"):
        _CREATE.build(raw, {**_create_changes(), "selected_devices": ["device-32"]})
    raw.pop("addtime")
    _CREATE.read(raw)
    raw["timerule_addmdevice"].append(
        {
            "sid": "device-253",
            "mdevice_name": "Over limit",
            "mdevice_mac": "02:00:00:00:00:fd",
        }
    )
    with pytest.raises(ConfigurationError):
        _CREATE.read(raw)


def test_nonoverlapping_three_windows_and_shared_budget_toggle() -> None:
    """Support complete daily windows, including midnight end and shared budget."""
    changes = {
        "trule_dfrom": "01:00",
        "trule_dto": "08:00",
        "trule_dfrom2": "09:00",
        "trule_dto2": "12:00",
        "trule_dfrom3": "13:00",
        "trule_dto3": "24:00",
        "trule_allusebudget": True,
        "tr_dmaxtime": 1440,
    }
    payload = _EDIT.build(_raw(), changes)
    assert payload["trule_dto3"] == "24:00"
    assert payload["trule_allusebudget"] == "1"
    assert payload["tr_dmaxtime"] == "1440"


@pytest.mark.parametrize("action", ["create", "edit", "delete", "budget", "weekly"])
async def test_real_session_single_write_and_independent_full_readback(
    action: str,
) -> None:
    """Exercise requester grants and derived-field expectations through real session."""
    contract = (
        _CREATE if action == "create" else _DELETE if action == "delete" else _EDIT
    )
    changes = {
        "create": _create_changes(),
        "edit": {"timerule_name": "Updated profile"},
        "delete": {"delete_entry": True},
        "budget": {"tr_dmaxtime": 60, "trule_dfrom": "", "trule_dto": ""},
        "weekly": {
            "schedule_mode": "weekly",
            "trule_mo_from": "10:00",
            "trule_mo_to": "18:00",
        },
    }[action]
    before, after = _raw(), _after(action)
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    assert not contract.verifier(before, changes, before)
    collateral = deepcopy(after)
    collateral["addtime"][0]["timerule_name"] = "Collateral change"
    assert not contract.verifier(before, changes, collateral)
    replaced = deepcopy(after)
    replaced["timerule_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert not contract.verifier(before, changes, replaced)
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


async def test_write_echo_without_persistence_does_not_replay_mutation() -> None:
    """Readback retries never repeat a POST when the new rule cannot be proven."""
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
            _create_changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


async def test_new_assignment_before_save_stales_grant_without_write() -> None:
    """Another profile taking the chosen device invalidates the one-shot grant."""
    before, after = _raw(), _raw()
    after["addtime"][0]["sid"][0]["mdevice_name"] = "1"
    read, write = AsyncMock(side_effect=[before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            _create_changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()
