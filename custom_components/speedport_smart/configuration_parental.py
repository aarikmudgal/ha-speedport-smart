"""Exact parental profile, time-window and budget forms; no network I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
)
from .configuration_rule_devices import (
    MAX_RULE_DEVICES,
    rule_devices,
    rule_id,
    rule_rows,
    rule_selection,
    rule_selection_payload,
)

if TYPE_CHECKING:
    from .configuration import SettingValues
    from .configuration_rule_devices import RuleDevices

_ENDPOINT: Final = "data/TimeRules.json"
_REFERER: Final = "html/content/internet/chd_timerules.html"
_COLLECTION: Final = "addtime"
_INVENTORY: Final = "timerule_addmdevice"
_MAX_RULES: Final = 32
_MAX_BUDGET: Final = 1440
_MAX_CHARACTER: Final = 255
_TIME: Final = re.compile(r"(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)")
_DAYS: Final = ("d", "mo", "di", "mi", "do", "fr", "sa", "so")
_DAY_LABELS: Final = (
    "Every day",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_NAME: Final = SettingsField("timerule_name", "Profile name", "text", maximum=20)
_ACTIVE: Final = boolean("timerule_active", "Enable this time rule")
_SHARED: Final = boolean(
    "trule_allusebudget", "Share one time budget across assigned devices"
)
_MODE: Final = choice(
    "schedule_mode",
    "Schedule mode",
    (("daily", "Same every day"), ("weekly", "Individual weekdays")),
    description="Changing mode clears the other mode's time windows and budgets.",
)
_DEVICES: Final = SettingsField(
    "selected_devices",
    "Assigned devices",
    "identifiers",
    maximum=MAX_RULE_DEVICES,
    dynamic_choices=True,
    description=(
        "A device can belong to only one parental profile, including disabled profiles."
    ),
)
_DELETE: Final = boolean("delete_entry", "Delete this exact parental profile")
_WARNING: Final = (
    "Time rules restrict Internet access for the assigned devices. Disabling a rule "
    "removes its schedule restriction; it does not pause Internet access. Deleting "
    "a profile removes its restrictions and assignments."
)


def _time_key(day: str, direction: str, interval: int) -> str:
    prefix = "trule_d" if day == "d" else f"trule_{day}_"
    return f"{prefix}{direction}{interval if interval > 1 else ''}"


def _budget_key(day: str) -> str:
    return "tr_dmaxtime" if day == "d" else f"tr_{day}_maxtime"


_SCHEDULE_FIELDS: Final = tuple(
    field
    for day, label in zip(_DAYS, _DAY_LABELS, strict=True)
    for field in (
        *(
            SettingsField(
                _time_key(day, direction, interval),
                f"{label}: window {interval} {direction}",
                "text",
                maximum=5,
                description=(
                    "Blank to leave this window unused, otherwise HH:MM. End may be "
                    "24:00; overnight windows must be split."
                ),
            )
            for interval in (1, 2, 3)
            for direction in ("from", "to")
        ),
        SettingsField(
            _budget_key(day),
            f"{label}: time budget (minutes)",
            "integer",
            maximum=_MAX_BUDGET,
            description=(
                "0 means no additional budget; otherwise 1-1440 minutes. A new "
                "budget without windows creates 00:00-24:00."
            ),
        ),
    )
)
_FIELDS: Final = (_NAME, _ACTIVE, _SHARED, _MODE, _DEVICES, *_SCHEDULE_FIELDS)
_FIELD_MAP: Final = {field.name: field for field in _FIELDS}


@dataclass(frozen=True, slots=True)
class ParentalTargetSpec:
    """Static metadata for one exact existing parental profile."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


PARENTAL_TARGET_SPECS: Final = MappingProxyType(
    {
        "parental_profile_edit": ParentalTargetSpec(
            "parental_profile_edit",
            "Edit parental profile",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "timerule_name",
            _FIELDS,
        ),
        "parental_profile_delete": ParentalTargetSpec(
            "parental_profile_delete",
            "Delete parental profile",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "timerule_name",
            (_DELETE,),
        ),
    }
)


def _name(value: object) -> str:
    result = _NAME.validate(value)
    if (
        type(result) is not str
        or not result
        or any(ord(char) > _MAX_CHARACTER or char in "<>" for char in result)
    ):
        raise ConfigurationError("invalid_parental_profile_name")
    return result


def _time(value: object) -> str:
    if type(value) is not str or (value and not _TIME.fullmatch(value)):
        raise ConfigurationError("invalid_parental_time")
    return value


def _budget(value: object) -> int:
    if value == "":
        return 0
    if (
        type(value) is not str
        or not re.fullmatch(r"[0-9]{1,4}", value)
        or not 1 <= int(value) <= _MAX_BUDGET
    ):
        raise ConfigurationError("invalid_parental_budget")
    return int(value)


def _day_populated(row: SettingValues, day: str) -> bool:
    return bool(row[_budget_key(day)]) or any(
        row[_time_key(day, direction, interval)]
        for interval in (1, 2, 3)
        for direction in ("from", "to")
    )


def _validate_day(row: SettingValues, day: str) -> None:
    windows: list[tuple[str, str]] = []
    for interval in (1, 2, 3):
        start = _time(row[_time_key(day, "from", interval)])
        end = _time(row[_time_key(day, "to", interval)])
        if bool(start) != bool(end) or (start and start >= end):
            raise ConfigurationError("invalid_parental_time_pair")
        if start:
            if any(
                start <= other_end and end >= other_start
                for other_start, other_end in windows
            ):
                raise ConfigurationError("overlapping_parental_times")
            windows.append((start, end))
    _FIELD_MAP[_budget_key(day)].validate(row[_budget_key(day)])


def _devices(raw: SettingValues) -> RuleDevices:
    return rule_devices(raw, _INVENTORY)


def _rules(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    devices = _devices(raw)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    assigned: set[str] = set()
    for row in rule_rows(raw.get(_COLLECTION, []), _MAX_RULES):
        identifier = rule_id(row.get("id"))
        selected = rule_selection(row, devices)
        if identifier in seen or not selected or selected & assigned:
            raise ConfigurationError("ambiguous_parental_profile")
        value: dict[str, Any] = {
            "id": identifier,
            "timerule_name": _name(row.get("timerule_name")),
            "timerule_active": _ACTIVE.read(row),
            "trule_allusebudget": _SHARED.read(row),
            "selected_devices": sorted(selected),
        }
        for field in _SCHEDULE_FIELDS:
            value[field.name] = (
                _budget(row.get(field.name))
                if field.kind == "integer"
                else _time(row.get(field.name))
            )
        for day in _DAYS:
            _validate_day(value, day)
        if not any(_day_populated(value, day) for day in _DAYS):
            raise ConfigurationError("empty_parental_schedule")
        value["schedule_mode"] = "daily" if _day_populated(value, "d") else "weekly"
        seen.add(identifier)
        assigned.update(selected)
        result.append(value)
    return tuple(result)


def _map(raw: SettingValues) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _rules(raw)}


def _choices(
    raw: SettingValues, target_id: str | None = None
) -> dict[str, tuple[tuple[str, str], ...]]:
    unavailable = {
        sid
        for row in _rules(raw)
        if row["id"] != target_id
        for sid in row["selected_devices"]
    }
    return {
        "selected_devices": tuple(
            (sid, label)
            for sid, label in _devices(raw).choices
            if sid not in unavailable
        )
    }


def _revision(raw: SettingValues) -> dict[str, object]:
    return {"devices": _devices(raw).identities}


def _blank() -> dict[str, Any]:
    return {
        "id": "-1",
        "timerule_name": "",
        "timerule_active": False,
        "trule_allusebudget": False,
        "schedule_mode": "daily",
        "selected_devices": [],
        **{
            field.name: 0 if field.kind == "integer" else ""
            for field in _SCHEDULE_FIELDS
        },
    }


def _public(row: SettingValues) -> dict[str, Any]:
    return {field.name: row[field.name] for field in _FIELDS}


def _proposed(
    raw: SettingValues, changes: SettingValues, current: SettingValues | None = None
) -> dict[str, Any]:
    previous = current or _blank()
    value = {**previous, **changes}
    value["timerule_name"] = _name(value["timerule_name"])
    mode = _MODE.validate(value["schedule_mode"])
    active_days = ("d",) if mode == "daily" else _DAYS[1:]
    inactive_days = _DAYS[1:] if mode == "daily" else ("d",)
    for day in inactive_days:
        names = [
            _time_key(day, direction, interval)
            for interval in (1, 2, 3)
            for direction in ("from", "to")
        ]
        names.append(_budget_key(day))
        if any(name in changes for name in names) and (
            mode == previous["schedule_mode"]
            or any(changes.get(name) not in (None, "", 0) for name in names)
        ):
            raise ConfigurationError("inactive_settings_field")
        if mode != previous["schedule_mode"]:
            for name in names:
                value[name] = 0 if name == _budget_key(day) else ""
    for day in active_days:
        budget = _budget_key(day)
        if (
            budget in changes
            and value[budget]
            and not any(
                value[_time_key(day, direction, interval)]
                for interval in (1, 2, 3)
                for direction in ("from", "to")
            )
        ):
            value[_time_key(day, "from", 1)] = "00:00"
            value[_time_key(day, "to", 1)] = "24:00"
    for day in _DAYS:
        _validate_day(value, day)
    if not any(_day_populated(value, day) for day in active_days):
        raise ConfigurationError("empty_parental_schedule")
    selected = _DEVICES.validate(value["selected_devices"])
    available = {
        sid for sid, _ in _choices(raw, str(previous["id"]))["selected_devices"]
    }
    if not isinstance(selected, list) or not selected or not set(selected) <= available:
        raise ConfigurationError("invalid_parental_device_assignment")
    value["selected_devices"] = sorted(selected)
    return value


def _wire(
    raw: SettingValues, row: SettingValues, ordinal: int
) -> dict[str, str | int | bool]:
    visible_day = (
        "0"
        if row["schedule_mode"] == "daily"
        else next(day for day in reversed(_DAYS[1:]) if _day_populated(row, day))
    )
    return {
        "id": row["id"],
        "timerule_name": row["timerule_name"],
        "timerule_active": "1" if row["timerule_active"] else "0",
        "trule_allusebudget": "1" if row["trule_allusebudget"] else "0",
        "show_day": visible_day,
        **{
            field.name: (str(row[field.name]) if row[field.name] else "")
            if field.kind == "integer"
            else row[field.name]
            for field in _SCHEDULE_FIELDS
        },
        **rule_selection_payload(
            _devices(raw), frozenset(row["selected_devices"]), ordinal
        ),
    }


def _payload_changes(
    raw: SettingValues, payload: SettingValues, ordinal: int
) -> dict[str, Any]:
    values = {
        "timerule_name": payload["timerule_name"],
        "timerule_active": _ACTIVE.read(payload),
        "trule_allusebudget": _SHARED.read(payload),
    }
    for field in _SCHEDULE_FIELDS:
        values[field.name] = (
            _budget(payload[field.name])
            if field.kind == "integer"
            else _time(payload[field.name])
        )
    values["schedule_mode"] = "daily" if _day_populated(values, "d") else "weekly"
    values["selected_devices"] = []
    for index, (sid, _, _) in enumerate(_devices(raw).identities, 1):
        suffix = f"[{index}{ordinal}]"
        if payload.get("sid" + suffix) != sid or payload.get(
            "mdevice_name" + suffix
        ) not in {"0", "1"}:
            raise ConfigurationError("invalid_rule_device_payload")
        if payload["mdevice_name" + suffix] == "1":
            values["selected_devices"].append(sid)
    return values


def _create_read(raw: SettingValues) -> dict[str, Any]:
    _rules(raw)
    return _public(_blank())


def _create_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    rows = _rules(raw)
    if len(rows) >= _MAX_RULES:
        raise ConfigurationError("parental_profile_limit")
    return _wire(raw, _proposed(raw, changes), len(rows) + 1)


def _for_payload(
    values: SettingValues, current: SettingValues | None = None
) -> dict[str, Any]:
    """Recover only effective edits, avoiding invented changes to dormant fields."""
    previous = current or _blank()
    inactive_days = _DAYS[1:] if values["schedule_mode"] == "daily" else ("d",)
    inactive_names = {
        name
        for day in inactive_days
        for name in (
            *(
                _time_key(day, direction, interval)
                for interval in (1, 2, 3)
                for direction in ("from", "to")
            ),
            _budget_key(day),
        )
    }
    return {
        name: value
        for name, value in values.items()
        if previous.get(name) != value and name not in inactive_names
    }


def _create_valid(raw: SettingValues, payload: SettingValues) -> bool:
    try:
        values = _payload_changes(raw, payload, len(_rules(raw)) + 1)
        return _create_build(raw, _for_payload(values)) == dict(payload)
    except (ConfigurationError, KeyError, TypeError):
        return False


def _stable(before: SettingValues, after: SettingValues) -> bool:
    return set(_devices(before).identities) == set(_devices(after).identities)


def _create_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _create_build(before, changes)
        previous, current = _map(before), _map(after)
        created = current.keys() - previous.keys()
        if (
            not _stable(before, after)
            or len(created) != 1
            or len(current) != len(previous) + 1
            or any(current.get(key) != row for key, row in previous.items())
        ):
            return False
        identifier = next(iter(created))
        return current[identifier] == {**_proposed(before, changes), "id": identifier}
    except ConfigurationError:
        return False


def parental_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, str], ...]:
    """List exact existing profile IDs and human-readable labels."""
    if setting_id not in PARENTAL_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        {"id": row["id"], "timerule_name": row["timerule_name"]} for row in _rules(raw)
    )


def parental_target_metadata() -> list[dict[str, Any]]:
    """Describe profile editors without supplying a fabricated target row."""
    return [
        {**parental_target_contract(spec.id, "0").metadata(), "requires_target": True}
        for spec in PARENTAL_TARGET_SPECS.values()
    ]


def parental_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind a complete profile form or deletion to an exact existing stable ID."""
    spec = PARENTAL_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    target_id = rule_id(target_id)
    deleting = setting_id == "parental_profile_delete"

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _map(raw).get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return row

    def read(raw: SettingValues) -> dict[str, Any]:
        return (
            {"delete_entry": target_id not in _map(raw)}
            if deleting
            else _public(selected(raw))
        )

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        current = selected(raw)
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        ordinal = next(
            index for index, row in enumerate(_rules(raw), 1) if row["id"] == target_id
        )
        return _wire(raw, _proposed(raw, changes, current), ordinal)

    def valid(raw: SettingValues, payload: SettingValues) -> bool:
        try:
            if deleting:
                changes = {"delete_entry": True}
            else:
                ordinal = next(
                    index
                    for index, row in enumerate(_rules(raw), 1)
                    if row["id"] == target_id
                )
                changes = _for_payload(
                    _payload_changes(raw, payload, ordinal), selected(raw)
                )
            return build(raw, changes) == dict(payload)
        except (ConfigurationError, KeyError, TypeError, StopIteration):
            return False

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            expected = _map(before)
            if deleting:
                expected.pop(target_id)
            else:
                expected[target_id] = _proposed(before, changes, selected(before))
            return _stable(before, after) and _map(after) == expected
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Network",
        _ENDPOINT,
        _REFERER,
        spec.fields,
        reader=read,
        builder=build,
        payload_validator=valid,
        verifier=verify,
        field_choices=None if deleting else lambda raw: _choices(raw, target_id),
        revision_values=_revision,
        revision_fields=(_COLLECTION,),
        expected_values=None
        if deleting
        else lambda raw, changes: _public(_proposed(raw, changes, selected(raw))),
        warning=_WARNING,
        confirmation="DELETE PARENTAL PROFILE" if deleting else "SAVE PARENTAL PROFILE",
    )


PARENTAL_SETTINGS: Final = (
    SettingsContract(
        "parental_profile_create",
        "Add parental profile",
        "Network",
        _ENDPOINT,
        _REFERER,
        _FIELDS,
        reader=_create_read,
        builder=_create_build,
        payload_validator=_create_valid,
        verifier=_create_verify,
        verifier_owns_fields=True,
        field_choices=_choices,
        revision_values=_revision,
        revision_fields=(_COLLECTION,),
        expected_values=lambda raw, changes: _public(_proposed(raw, changes)),
        warning=_WARNING,
        confirmation="ADD PARENTAL PROFILE",
    ),
)
