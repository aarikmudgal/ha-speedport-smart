"""One-shot local contact creation with returned-ID and complete detail proof."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract
from .configuration_phonebook import (
    PHONEBOOK_ENDPOINT,
    PHONEBOOK_FIELDS,
    PHONEBOOK_REFERER,
    normalize_contact_fields,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

PHONEBOOK_CREATE_SETTING_ID: Final = "telephony_phonebook_create"
_BOOK: Final = re.compile(r"[0-5]")
_CONTACT: Final = re.compile(r"[A-Za-z0-9_-]{1,32}")
_LIMIT: Final = 1000
_TEXT_LIMIT: Final = 256
_CAPACITY_LIMIT: Final = 1000
_ENTRY_KEYS: Final = frozenset({"contact_id", "first_name", "last_name", "number"})
_WARNING: Final = (
    "This adds one contact to the selected local router phonebook. A save is sent "
    "once. If its resulting ID cannot be verified, inspect the phonebook before "
    "trying again to avoid duplicates."
)
_CONFIRMATION: Final = "CREATE PHONEBOOK CONTACT"


def phonebook_create_book_id(target_id: str) -> int:
    """Accept only an exact local book index, never an online phonebook alias."""
    if not isinstance(target_id, str) or _BOOK.fullmatch(target_id) is None:
        raise ConfigurationError("settings_target_unavailable")
    return int(target_id)


def _contact_id(value: object) -> str:
    if type(value) is int and value >= 0:
        value = str(value)
    if not isinstance(value, str) or _CONTACT.fullmatch(value) is None or value == "-1":
        raise ConfigurationError("action_outcome_unknown")
    return value


def phonebook_inventory(
    raw: SettingValues, *, phonebook_id: int
) -> dict[str, dict[str, str]]:
    """Require a complete private prefix search before reasoning about ID deltas."""
    entries = raw.get("entries")
    total = raw.get("total")
    free = raw.get("free_entries")
    if (
        type(raw.get("phonebook_id")) is not int
        or raw["phonebook_id"] != phonebook_id
        or raw.get("truncated") is not False
        or raw.get("prefix") != ""
        or not isinstance(entries, list)
        or len(entries) > _LIMIT
        or type(total) is not int
        or total != len(entries)
        or type(free) is not int
        or not 0 <= free <= _CAPACITY_LIMIT
    ):
        raise ConfigurationError("settings_inventory_unavailable")
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or not set(entry) <= _ENTRY_KEYS:
            raise ConfigurationError("settings_inventory_unavailable")
        identifier = _contact_id(entry.get("contact_id"))
        if identifier in result:
            raise ConfigurationError("settings_inventory_unavailable")
        if any(
            not isinstance(value, str)
            or len(value) > _TEXT_LIMIT
            or (bool(value) and not value.isprintable())
            for value in entry.values()
        ):
            raise ConfigurationError("settings_inventory_unavailable")
        result[identifier] = dict(entry)
    return result


def phonebook_created_id(response: SettingValues, *, existing_ids: set[str]) -> str:
    """Validate optional generic assignedID proof; absence never authorizes a retry."""
    status_keys = [key for key in response if str(key).casefold() == "status"]
    assigned_keys = [key for key in response if str(key).casefold() == "assignedid"]
    if (
        status_keys != ["status"]
        or assigned_keys != ["assignedID"]
        or response.get("status") != "ok"
    ):
        raise ConfigurationError("action_outcome_unknown")
    identifier = _contact_id(response["assignedID"])
    if identifier in existing_ids:
        raise ConfigurationError("action_outcome_unknown")
    return identifier


def phonebook_create_payload(
    raw: SettingValues, changes: SettingValues, *, phonebook_id: int
) -> dict[str, str | int | bool]:
    """Build the reviewed new-row form only after capacity and full inventory proof."""
    phonebook_inventory(raw, phonebook_id=phonebook_id)
    if raw["free_entries"] < 1:
        raise ConfigurationError("settings_capacity_reached")
    names = {item.name for item in PHONEBOOK_FIELDS}
    if not changes or not set(changes) <= names:
        raise ConfigurationError("invalid_settings")
    values = normalize_contact_fields({**dict.fromkeys(names, ""), **changes})
    return {"obnr": phonebook_id, "id": "-1", **values}


def verify_phonebook_creation(
    before: SettingValues,
    changes: SettingValues,
    after: SettingValues,
    *,
    phonebook_id: int,
) -> bool:
    """Prove one new ID, unchanged listed siblings, and exact new contact details."""
    previous = phonebook_inventory(before, phonebook_id=phonebook_id)
    current = phonebook_inventory(after, phonebook_id=phonebook_id)
    assigned_id = _contact_id(after.get("assigned_id"))
    if assigned_id in previous or set(current) != set(previous) | {assigned_id}:
        return False
    if any(current[identifier] != entry for identifier, entry in previous.items()):
        return False
    detail = after.get("created_contact")
    if (
        not isinstance(detail, Mapping)
        or type(detail.get("phonebook_id")) is not int
        or detail["phonebook_id"] != phonebook_id
        or detail.get("contact_id") != assigned_id
        or not isinstance(detail.get("contact"), Mapping)
    ):
        return False
    expected = phonebook_create_payload(before, changes, phonebook_id=phonebook_id)
    values = {item.name: expected[item.name] for item in PHONEBOOK_FIELDS}
    return normalize_contact_fields(detail["contact"]) == values


def phonebook_create_settings(target_id: str) -> SettingsContract:
    """Describe a new-contact form whose success requires response-aware readback."""
    phonebook_id = phonebook_create_book_id(target_id)

    def read(raw: SettingValues) -> dict[str, str]:
        phonebook_inventory(raw, phonebook_id=phonebook_id)
        if raw["free_entries"] < 1:
            raise ConfigurationError("settings_capacity_reached")
        return {item.name: "" for item in PHONEBOOK_FIELDS}

    def expected(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
        payload = phonebook_create_payload(raw, changes, phonebook_id=phonebook_id)
        return {item.name: payload[item.name] for item in PHONEBOOK_FIELDS}

    return SettingsContract(
        PHONEBOOK_CREATE_SETTING_ID,
        "Create local phonebook contact",
        "Telephony",
        PHONEBOOK_ENDPOINT,
        PHONEBOOK_REFERER,
        PHONEBOOK_FIELDS,
        reader=read,
        builder=lambda raw, changes: phonebook_create_payload(
            raw, changes, phonebook_id=phonebook_id
        ),
        expected_values=expected,
        payload_keys=frozenset(
            ("obnr", "id", *(item.name for item in PHONEBOOK_FIELDS))
        ),
        revision_fields=(
            "phonebook_id",
            "entries",
            "total",
            "free_entries",
            "prefix",
            "truncated",
            "book_identity",
        ),
        verifier=lambda before, changes, after: verify_phonebook_creation(
            before, changes, after, phonebook_id=phonebook_id
        ),
        verifier_owns_fields=True,
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )


def phonebook_create_metadata() -> dict[str, Any]:
    """Describe the creation form without inventing a contact or selecting a book."""
    return {
        "id": PHONEBOOK_CREATE_SETTING_ID,
        "title": "Create local phonebook contact",
        "section": "Telephony",
        "fields": [item.metadata() for item in PHONEBOOK_FIELDS],
        "warning": _WARNING,
        "confirmation": _CONFIRMATION,
        "requires_target": True,
        "live_write_verified": False,
    }
