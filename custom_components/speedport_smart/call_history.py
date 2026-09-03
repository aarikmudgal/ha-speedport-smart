"""
Private call-history contracts, bounded views, and local CSV exports.

These helpers do not send requests. Callers must use an administrator-only,
explicit-load surface, never recorder entities or a public panel snapshot.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from .configuration import ConfigurationError

CALL_HISTORY_READ_ENDPOINT: Final = "data/PhoneCalls.json"
CALL_HISTORY_MAX_ROWS: Final = 1000
_TEXT_LIMIT: Final = 512
_DURATION: Final = re.compile(r"[0-9]{1,10}")


@dataclass(frozen=True, slots=True)
class CallHistorySpec:
    """One fixed firmware category; user input cannot choose an endpoint."""

    id: str
    title: str
    collection: str
    prefix: str
    local_suffix: str
    clear_endpoint: str
    referer: str
    has_duration: bool


CALL_HISTORY_SPECS: Final = MappingProxyType(
    {
        name: CallHistorySpec(
            name,
            title,
            f"add{name}calls",
            f"{name}calls",
            "for" if name == "missed" else "as",
            f"data/Phone{endpoint}Calls.json",
            f"html/content/phone/phone_call_{name}.html",
            name != "missed",
        )
        for name, title, endpoint in (
            ("dialed", "Dialed calls", "Dialed"),
            ("missed", "Missed calls", "Missed"),
            ("taken", "Answered calls", "Taken"),
        )
    }
)


def call_history_spec(category: str) -> CallHistorySpec:
    """Reject unknown categories, paths, aliases and non-string selectors."""
    if not isinstance(category, str) or category not in CALL_HISTORY_SPECS:
        raise ConfigurationError("invalid_call_history_category")
    return CALL_HISTORY_SPECS[category]


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _TEXT_LIMIT
        or (bool(value) and not value.isprintable())
    ):
        raise ConfigurationError("call_history_unavailable")
    return value


def _rows(raw: Mapping[str, Any], spec: CallHistorySpec) -> list[Mapping[str, Any]]:
    """Missing collections are unknown, including authenticated global fallbacks."""
    names = [name for name in raw if str(name).casefold() == spec.collection]
    if names != [spec.collection]:
        raise ConfigurationError("call_history_unavailable")
    value = raw[spec.collection]
    if isinstance(value, Mapping):
        value = [value]
    if (
        not isinstance(value, list)
        or len(value) > CALL_HISTORY_MAX_ROWS
        or any(not isinstance(row, Mapping) for row in value)
    ):
        raise ConfigurationError("call_history_unavailable")
    return value


def read_call_history(raw: Mapping[str, Any], category: str) -> dict[str, Any]:
    """Project one explicitly present complete category without markup or secrets."""
    spec = call_history_spec(category)
    entries: list[dict[str, Any]] = []
    for row in _rows(raw, spec):
        entry: dict[str, Any] = {
            "date": _text(row.get(f"{spec.prefix}_date")),
            "time": _text(row.get(f"{spec.prefix}_time")),
            "remote_party": _text(row.get(f"{spec.prefix}_who")),
            "local_party": _text(row.get(f"{spec.prefix}_{spec.local_suffix}")),
        }
        if not entry["date"] or not entry["time"]:
            raise ConfigurationError("call_history_unavailable")
        if spec.has_duration:
            duration = row.get(f"{spec.prefix}_duration")
            if (
                not isinstance(duration, str)
                or _DURATION.fullmatch(duration) is None
                or int(duration) > 2**31 - 1
            ):
                raise ConfigurationError("call_history_unavailable")
            entry["duration_seconds"] = int(duration)
        entries.append(entry)
    return {"category": category, "entries": entries, "total": len(entries)}


def _spreadsheet_text(value: str) -> str:
    """Prevent formula execution when a private CSV is opened in a spreadsheet."""
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_call_history_csv(raw: Mapping[str, Any], category: str) -> str:
    """Export a confirmed private snapshot locally, not through a guessed router API."""
    spec = call_history_spec(category)
    snapshot = read_call_history(raw, category)
    fields = ["date", "time", "remote_party", "local_party"]
    if spec.has_duration:
        fields.append("duration_seconds")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(fields)
    for entry in snapshot["entries"]:
        writer.writerow(
            _spreadsheet_text(value) if isinstance(value := entry[key], str) else value
            for key in fields
        )
    return stream.getvalue()


def call_history_clear_payload(raw: Mapping[str, Any], category: str) -> dict[str, str]:
    """Require a known nonempty list before building the exact destructive form."""
    if read_call_history(raw, category)["total"] == 0:
        raise ConfigurationError("call_history_already_empty")
    return {"action_clearlist": "true"}


def _entry_counts(snapshot: dict[str, Any]) -> Counter[tuple[tuple[str, Any], ...]]:
    return Counter(tuple(sorted(entry.items())) for entry in snapshot["entries"])


def verify_call_history_clear(
    before: Mapping[str, Any], after: Mapping[str, Any], category: str
) -> bool:
    """
    Require an explicit empty readback; an ACK or missing list proves nothing.

    Other categories observed before the operation must retain every prior row.
    New calls may arrive there during verification. A new selected-category call
    instead yields an uncertain outcome; no automatic second clear is safe.
    """
    call_history_clear_payload(before, category)
    if read_call_history(after, category)["total"] != 0:
        return False
    for name, spec in CALL_HISTORY_SPECS.items():
        if name != category and spec.collection in before:
            previous = _entry_counts(read_call_history(before, name))
            current = _entry_counts(read_call_history(after, name))
            if not previous <= current:
                return False
    return True


def call_history_metadata() -> list[dict[str, Any]]:
    """Advertise exact contracts without claiming live clear/readback validation."""
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "private": True,
            "confirmation": f"CLEAR {spec.id.upper()} CALLS",
            "warning": (
                f"This permanently deletes the router's {spec.title.lower()} history. "
                "Export it first if needed. A clear is sent once; an uncertain "
                "result must be checked before trying again."
            ),
            "live_write_verified": False,
        }
        for spec in CALL_HISTORY_SPECS.values()
    ]
