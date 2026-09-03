"""Synthetic powerline full-form rename evidence; no network calls or live writes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_powerline import (
    powerline_target_contract,
    powerline_target_metadata,
    powerline_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_TARGET = "02:00:00:00:00:07"
_EDIT = powerline_target_contract("powerline_rename", _TARGET)
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw() -> dict[str, Any]:
    return {
        "addpwlinedevice": [
            {
                "id": "0",
                "pwline_mac": f"02-00-00-00-00-0{index}",
                "pwline_name": f"Adapter-{index}",
                "pwline_downspeed": "1000",
                "pwline_upspeed": "800",
                "pwline_manufacturer": "Synthetic manufacturer",
                "pwline_firmware": "synthetic-version",
            }
            for index in (2, 7)
        ],
        "unrelated_counter": "100",
    }


def test_complete_native_rename_form_preserves_exact_id_mac_and_fresh_rates() -> None:
    """MAC identity disambiguates multiple native hidden ID-zero device rows."""
    raw = _raw()
    previous = deepcopy(raw)
    assert _EDIT.build(raw, {"pwline_name": "Office-Adapter"}) == {
        "id": "0",
        "pwline_mac": "02-00-00-00-00-07",
        "pwline_name": "Office-Adapter",
        "pwline_downspeed": "1000",
        "pwline_upspeed": "800",
    }
    assert raw == previous
    assert _EDIT.endpoint == "data/PWLineDevice.json"
    assert _EDIT.read_endpoint == "data/DeviceList.json"
    assert _EDIT.referer == "html/content/network/devices.html"
    assert _EDIT.acknowledgement == "status_ok"
    assert powerline_target_rows("powerline_rename", raw)[1] == {
        "id": _TARGET,
        "pwline_name": f"Adapter-7 ({_TARGET})",
    }
    assert powerline_target_metadata()[0]["requires_target"] is True


def test_missing_json_id_uses_only_proven_native_static_zero_default() -> None:
    """An actual nonzero current ID is preserved; no arbitrary ID is accepted."""
    raw = _raw()
    raw["addpwlinedevice"][1].pop("id")
    assert _EDIT.build(raw, {"pwline_name": "Renamed"})["id"] == "0"
    raw["addpwlinedevice"][1]["id"] = "19"
    assert _EDIT.build(raw, {"pwline_name": "Renamed"})["id"] == "19"
    raw["addpwlinedevice"] = raw["addpwlinedevice"][1]
    assert _EDIT.read(raw) == {"pwline_name": "Adapter-7"}
    assert powerline_target_rows("powerline_rename", {}) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"pwline_name": ""},
        {"pwline_name": "a" * 29},
        {"pwline_name": "has space"},
        {"pwline_name": "underscore_name"},
        {"pwline_name": "<html>"},
        {"pwline_name": "München"},
        {"pwline_name": 1},
        {"id": "2"},
        {"pwline_mac": "02:00:00:00:00:02"},
        {"pwline_downspeed": "100"},
        {"deleteEntry": "delete"},
        {"identify": True},
        {"endpoint": "data/Other.json"},
    ],
)
def test_invalid_name_and_unreviewed_wire_fields_rejected(
    changes: dict[str, object],
) -> None:
    """Only the native name grammar can change through this editor."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing_mac", "mixed_mac", "missing_speed", "bad_id"]
)
def test_incomplete_or_ambiguous_current_identity_fails_closed(mutation: str) -> None:
    """Never select by display name, collection position or ambiguous default ID."""
    raw = _raw()
    row = raw["addpwlinedevice"][1]
    if mutation == "duplicate":
        row["pwline_mac"] = raw["addpwlinedevice"][0]["pwline_mac"]
    elif mutation == "missing_mac":
        row.pop("pwline_mac")
    elif mutation == "mixed_mac":
        row["pwline_mac"] = "02:00-00-00-00-07"
    elif mutation == "missing_speed":
        row.pop("pwline_downspeed")
    else:
        row["id"] = "-1"
    with pytest.raises(ConfigurationError):
        _EDIT.read(raw)


def test_revision_ignores_speed_updates_but_payload_always_uses_fresh_values() -> None:
    """Live link rates belong in this form, not in authorization staleness identity."""
    before, current = _raw(), _raw()
    current["addpwlinedevice"][1]["pwline_downspeed"] = "1200"
    current["addpwlinedevice"][1]["pwline_upspeed"] = "900"
    assert _EDIT.revision(before) == _EDIT.revision(current)
    assert (
        _EDIT.build(current, {"pwline_name": "Renamed"})["pwline_downspeed"] == "1200"
    )
    current["addpwlinedevice"][1]["pwline_mac"] = "02:00:00:00:00:07"
    assert _EDIT.revision(before) == _EDIT.revision(current)
    current["addpwlinedevice"][1]["pwline_name"] = "OtherName"
    assert _EDIT.revision(before) != _EDIT.revision(current)


async def test_one_shot_session_fresh_wire_rates_and_exact_sibling_readback() -> None:
    """Independent name readback proves success; changing link rates are allowed."""
    before, current, after = _raw(), _raw(), _raw()
    current["addpwlinedevice"][1]["pwline_downspeed"] = "1200"
    after["addpwlinedevice"][1]["pwline_name"] = "Office-Adapter"
    after["addpwlinedevice"][1]["pwline_downspeed"] = "1100"
    changes = {"pwline_name": "Office-Adapter"}
    assert _EDIT.verifier is not None
    assert _EDIT.verifier(before, changes, after)
    collateral = deepcopy(after)
    collateral["addpwlinedevice"][0]["pwline_name"] = "Collateral"
    assert not _EDIT.verifier(before, changes, collateral)
    replaced = deepcopy(after)
    replaced["addpwlinedevice"][1]["pwline_mac"] = "02:00:00:00:00:09"
    assert not _EDIT.verifier(before, changes, replaced)
    read, write = AsyncMock(side_effect=[before, current, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_EDIT, _OWNER, read)
    assert await session.save(
        _EDIT,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=_EDIT.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once_with(current, changes)


def test_exact_payload_guard_rejects_hidden_identity_and_telemetry_injection() -> None:
    """Every non-name field must exactly match the current router form context."""
    raw = _raw()
    payload = _EDIT.build(raw, {"pwline_name": "Renamed"})
    assert _EDIT.payload_validator is not None
    for key, value in (
        ("id", "7"),
        ("pwline_mac", "02:00:00:00:00:02"),
        ("pwline_downspeed", "999"),
        ("extra", "value"),
    ):
        assert not _EDIT.payload_validator(raw, {**payload, key: value})
    with pytest.raises(ConfigurationError):
        _EDIT.build({}, {"pwline_name": "Renamed"})
