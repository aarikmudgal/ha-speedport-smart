"""Private history projection and guarded clear verification, without router calls."""

from __future__ import annotations

import csv
import io
from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.call_history import (
    CALL_HISTORY_MAX_ROWS,
    CALL_HISTORY_READ_ENDPOINT,
    CALL_HISTORY_SPECS,
    call_history_clear_payload,
    call_history_metadata,
    call_history_spec,
    export_call_history_csv,
    read_call_history,
    verify_call_history_clear,
)
from custom_components.speedport_smart.configuration import ConfigurationError


def _row(category: str, *, remote: str = "+0000000000") -> dict[str, str]:
    spec = call_history_spec(category)
    result = {
        f"{spec.prefix}_date": "02.09.2026",
        f"{spec.prefix}_time": "10:20",
        f"{spec.prefix}_who": remote,
        f"{spec.prefix}_{spec.local_suffix}": "<Office><Kitchen>",
    }
    if spec.has_duration:
        result[f"{spec.prefix}_duration"] = "125"
    return result


def _raw() -> dict[str, Any]:
    return {
        spec.collection: [_row(category)]
        for category, spec in CALL_HISTORY_SPECS.items()
    }


@pytest.mark.parametrize("category", ["dialed", "missed", "taken"])
def test_exact_static_contracts_and_private_projection(category: str) -> None:
    """Call data is projected through a closed family with literal plain text."""
    spec = call_history_spec(category)
    result = read_call_history(_raw(), category)
    assert CALL_HISTORY_READ_ENDPOINT == "data/PhoneCalls.json"
    assert spec.clear_endpoint == f"data/Phone{category.title()}Calls.json"
    assert spec.referer == f"html/content/phone/phone_call_{category}.html"
    assert result["category"] == category
    assert result["total"] == 1
    entry = result["entries"][0]
    assert entry["remote_party"] == "+0000000000"
    assert entry["local_party"] == "<Office><Kitchen>"
    assert ("duration_seconds" in entry) is (category != "missed")
    if category != "missed":
        assert entry["duration_seconds"] == 125
    assert call_history_clear_payload(_raw(), category) == {"action_clearlist": "true"}


@pytest.mark.parametrize("category", ["../PhoneCalls.json", "Taken", "", 0, None, []])
def test_unknown_category_cannot_select_endpoint(category: Any) -> None:
    """No endpoint, case-folded alias or malformed type is a valid selector."""
    with pytest.raises(ConfigurationError, match="invalid_call_history_category"):
        call_history_spec(category)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"router_state": "OK", "loginstate": "1", "use_dect": "0"},
        {"addtakencalls": None},
        {"addtakencalls": ""},
        {"addtakencalls": [None]},
        {"addtakencalls": [], "AddTakenCalls": []},
        {"addtakencalls": [{}]},
    ],
)
def test_absent_ambiguous_or_invalid_collection_is_not_empty(
    raw: dict[str, Any],
) -> None:
    """Global fallback documents cannot become fabricated empty histories."""
    with pytest.raises(ConfigurationError, match="call_history_unavailable"):
        read_call_history(raw, "taken")


def test_singleton_and_explicit_empty_collection() -> None:
    """Only explicit singleton/list containers are known histories."""
    assert read_call_history({"addtakencalls": _row("taken")}, "taken")["total"] == 1
    assert read_call_history({"addtakencalls": []}, "taken")["total"] == 0
    with pytest.raises(ConfigurationError, match="call_history_already_empty"):
        call_history_clear_payload({"addtakencalls": []}, "taken")


def test_no_silent_truncation_or_partial_fields() -> None:
    """Every call field is required and the bounded inventory never truncates."""
    with pytest.raises(ConfigurationError):
        read_call_history(
            {"addtakencalls": [_row("taken")] * (CALL_HISTORY_MAX_ROWS + 1)}, "taken"
        )
    raw = _raw()
    raw["addtakencalls"][0].pop("takencalls_who")
    with pytest.raises(ConfigurationError):
        read_call_history(raw, "taken")


@pytest.mark.parametrize("duration", ["-1", "1.5", True, 125, "2147483648", "", None])
def test_duration_requires_exact_bounded_wire_seconds(duration: Any) -> None:
    """Malformed duration data cannot produce a believable display or export."""
    raw = _raw()
    raw["addtakencalls"][0]["takencalls_duration"] = duration
    with pytest.raises(ConfigurationError):
        read_call_history(raw, "taken")


def test_csv_is_local_and_formula_safe_without_mutating_private_values() -> None:
    """Phone numbers and arbitrary caller labels cannot execute spreadsheet formulas."""
    raw = _raw()
    raw["addtakencalls"] = [
        _row("taken", remote=value)
        for value in ["=1+1", "+0000000000", "-2", "@SUM(A1)", " =1", 'A, "B"']
    ]
    before = deepcopy(raw)
    rows = list(csv.reader(io.StringIO(export_call_history_csv(raw, "taken"))))
    assert rows[0] == [
        "date",
        "time",
        "remote_party",
        "local_party",
        "duration_seconds",
    ]
    assert [row[2] for row in rows[1:]] == [
        "'=1+1",
        "'+0000000000",
        "'-2",
        "'@SUM(A1)",
        "' =1",
        'A, "B"',
    ]
    assert raw == before


def test_clear_verification_needs_independent_explicit_empty_collection() -> None:
    """A write ACK, fallback response or missing collection never proves deletion."""
    before = _raw()
    after = deepcopy(before)
    after["addtakencalls"] = []
    assert verify_call_history_clear(before, after, "taken")
    assert not verify_call_history_clear(before, before, "taken")
    with pytest.raises(ConfigurationError):
        verify_call_history_clear(before, {"status": "ok"}, "taken")
    after.pop("addtakencalls")
    with pytest.raises(ConfigurationError):
        verify_call_history_clear(before, after, "taken")


def test_clear_verification_preserves_siblings_with_duplicate_counts() -> None:
    """Unrelated categories retain old calls; new unrelated calls are permitted."""
    before = _raw()
    before["adddialedcalls"].append(_row("dialed"))
    after = deepcopy(before)
    after["addtakencalls"] = []
    after["addmissedcalls"].append(_row("missed", remote="New caller"))
    assert verify_call_history_clear(before, after, "taken")
    after["adddialedcalls"].pop()
    assert not verify_call_history_clear(before, after, "taken")


def test_metadata_marks_destruction_private_and_not_live_verified() -> None:
    """Static contract evidence does not assert real-router mutation testing."""
    for item in call_history_metadata():
        assert item["private"] is True
        assert item["live_write_verified"] is False
        assert item["confirmation"] == f"CLEAR {item['id'].upper()} CALLS"
        assert "permanently deletes" in item["warning"]
