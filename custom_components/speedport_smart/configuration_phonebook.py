"""Existing local phonebook contacts with a complete, independently read form."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField

if TYPE_CHECKING:
    from .configuration import SettingValues

PHONEBOOK_SETTING_ID: Final = "telephony_phonebook_contact"
PHONEBOOK_ENDPOINT: Final = "data/PhoneBookEntry.json"
PHONEBOOK_REFERER: Final = "html/content/phone/phone_book_entries.html"
_TARGET: Final = re.compile(r"([0-5]):([A-Za-z0-9_-]{1,32})")
_PHONE: Final = re.compile(r"\+?[0-9/\-*# ]*")
_BIRTHDAY: Final = re.compile(r"([0-9]{2})\.([0-9]{2})\.((?:19|20)[0-9]{2})")
_NUMBERS: Final = ("number_p", "number_a", "number_m", "number_n")
PHONEBOOK_FIELDS: Final = (
    SettingsField("name", "Last name", "text", maximum=16),
    SettingsField("vorname", "First name", "text", maximum=16),
    SettingsField("number_p", "Private telephone number", "text", maximum=40),
    SettingsField("number_a", "Work telephone number", "text", maximum=40),
    SettingsField("number_m", "Mobile telephone number", "text", maximum=40),
    SettingsField("number_n", "Second mobile telephone number", "text", maximum=40),
    SettingsField("adresse", "Street address", "text", maximum=40),
    SettingsField("plz", "Postal code", "text", maximum=6),
    SettingsField("ort", "City", "text", maximum=40),
    SettingsField(
        "geburtstag",
        "Birthday",
        "text",
        maximum=10,
        description="Optional, DD.MM.YYYY between 1900 and 2099.",
    ),
)
_WARNING: Final = (
    "This changes the selected existing contact in a local router phonebook. "
    "Every unedited field is preserved. Online phonebooks are not edited here."
)
_CONFIRMATION: Final = "SAVE PHONEBOOK CONTACT"


def parse_phonebook_target(target_id: str) -> tuple[int, str]:
    """Bind an exact local phonebook and existing contact; never accept new-row -1."""
    match = _TARGET.fullmatch(target_id) if isinstance(target_id, str) else None
    if match is None or match[2] == "-1":
        raise ConfigurationError("settings_target_unavailable")
    return int(match[1]), match[2]


def normalize_contact_fields(raw: SettingValues) -> dict[str, str]:
    """Require all current fields and apply the exact telephone-number normalization."""
    values: dict[str, str] = {}
    for item in PHONEBOOK_FIELDS:
        value = item.read(raw)
        if not isinstance(value, str):
            raise ConfigurationError("invalid_settings")
        values[item.name] = value
    if not values["name"].strip() and not values["vorname"].strip():
        raise ConfigurationError("invalid_settings")
    for name in _NUMBERS:
        if _PHONE.fullmatch(values[name]) is None:
            raise ConfigurationError("invalid_settings")
        values[name] = values[name].replace(" ", "")
    if not any(values[name] for name in _NUMBERS):
        raise ConfigurationError("invalid_settings")
    if values["plz"] and re.fullmatch(r"[0-9]{1,6}", values["plz"]) is None:
        raise ConfigurationError("invalid_settings")
    birthday = values["geburtstag"].strip()
    if birthday:
        match = _BIRTHDAY.fullmatch(birthday)
        if match is None:
            raise ConfigurationError("invalid_settings")
        try:
            date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            raise ConfigurationError("invalid_settings") from None
    values["geburtstag"] = birthday
    return values


def _contact(raw: SettingValues, phonebook_id: int, contact_id: str) -> dict[str, str]:
    if (
        type(raw.get("phonebook_id")) is not int
        or raw["phonebook_id"] != phonebook_id
        or raw.get("contact_id") != contact_id
        or not isinstance(raw.get("contact"), Mapping)
    ):
        raise ConfigurationError("stale_settings")
    return normalize_contact_fields(raw["contact"])


def phonebook_contact_settings(target_id: str) -> SettingsContract:
    """Edit one existing local contact from a fresh, complete private detail query."""
    phonebook_id, contact_id = parse_phonebook_target(target_id)

    def read(raw: SettingValues) -> dict[str, str]:
        return _contact(raw, phonebook_id, contact_id)

    def expected(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
        return normalize_contact_fields({**read(raw), **changes})

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        return {"obnr": phonebook_id, "id": contact_id, **expected(raw, changes)}

    return SettingsContract(
        PHONEBOOK_SETTING_ID,
        "Existing local phonebook contact",
        "Telephony",
        PHONEBOOK_ENDPOINT,
        PHONEBOOK_REFERER,
        PHONEBOOK_FIELDS,
        reader=read,
        builder=build,
        expected_values=expected,
        payload_keys=frozenset(
            ("obnr", "id", *(field.name for field in PHONEBOOK_FIELDS))
        ),
        revision_fields=("phonebook_id", "contact_id", "contact", "book_identity"),
        warning=_WARNING,
        confirmation=_CONFIRMATION,
    )


def phonebook_contact_metadata() -> dict[str, Any]:
    """Describe the editor without choosing a book or exposing a contact."""
    return {
        "id": PHONEBOOK_SETTING_ID,
        "title": "Existing local phonebook contact",
        "section": "Telephony",
        "fields": [item.metadata() for item in PHONEBOOK_FIELDS],
        "warning": _WARNING,
        "confirmation": _CONFIRMATION,
        "requires_target": True,
        "live_write_verified": False,
    }
