"""Exact existing phonebook names, deletion and online-account disconnection."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

PHONEBOOK_ACCOUNTS_ENDPOINT: Final = "data/PhoneOnlbuch.json"
PHONEBOOK_ACCOUNTS_REFERER: Final = "html/content/phone/phone_book_basic.html"
_COLLECTION: Final = "addonlbuchentry"
_MAX_BOOKS: Final = 5
_MAX_USER: Final = 255
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_BOOK_NUMBER: Final = re.compile(r"[0-5]")
_NAME_PATTERN: Final = re.compile(r"[\x20-\x3B\x3D\x3F-\x7E\x80-\xFF]{1,16}")
_NAME: Final = SettingsField(
    "onlbuch_name", "Phonebook name", "text", minimum=1, maximum=16
)
_EXECUTE: Final = boolean("execute", "Execute this phonebook action")
_SYNC: Final = boolean("onlbuch_sync", "Online phonebook linked")


@dataclass(frozen=True, slots=True)
class PhonebookAccountSpec(PhoneTargetSpec):
    """Keep each target operation separate, with its own typed confirmation."""

    confirmation: str
    warning: str


PHONEBOOK_ACCOUNT_TARGET_SPECS: Final = MappingProxyType(
    {
        identifier: PhonebookAccountSpec(
            identifier,
            title,
            PHONEBOOK_ACCOUNTS_ENDPOINT,
            PHONEBOOK_ACCOUNTS_REFERER,
            _COLLECTION,
            "onlbuch_name",
            fields,
            confirmation,
            warning,
        )
        for identifier, title, fields, confirmation, warning in (
            (
                "telephony_phonebook_rename",
                "Rename phonebook",
                (_NAME,),
                "RENAME PHONEBOOK",
                (
                    "This changes only the selected phonebook name. Its account "
                    "binding and book identity are preserved."
                ),
            ),
            (
                "telephony_phonebook_delete",
                "Delete phonebook",
                (_EXECUTE,),
                "DELETE PHONEBOOK",
                (
                    "This permanently deletes the selected phonebook and may remove "
                    "its contacts. Export first. This is not deletion of one contact."
                ),
            ),
            (
                "telephony_phonebook_disconnect",
                "Disconnect online phonebook",
                (_EXECUTE,),
                "DISCONNECT ONLINE PHONEBOOK",
                (
                    "This removes the selected online phonebook link. Verify which "
                    "contacts remain locally before reconnecting or deleting anything."
                ),
            ),
        )
    }
)


def phonebook_account_rows(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Require explicit, complete, unique book identities and online-link state."""
    source = raw.get(_COLLECTION)
    if isinstance(source, Mapping):
        source = [source]
    if not isinstance(source, list) or len(source) > _MAX_BOOKS:
        raise ConfigurationError("settings_inventory_unavailable")
    rows = []
    ids: set[str] = set()
    numbers: set[str] = set()
    for row in source:
        if not isinstance(row, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        identifier, number = row.get("id"), row.get("onlbuch_nr")
        name, username = row.get("onlbuch_name"), row.get("onlbuch_bname")
        if (
            not isinstance(identifier, str)
            or _ID.fullmatch(identifier) is None
            or not isinstance(number, str)
            or _BOOK_NUMBER.fullmatch(number) is None
            or identifier in ids
            or number in numbers
            or not isinstance(name, str)
            or _NAME_PATTERN.fullmatch(name) is None
            or not isinstance(username, str)
            or len(username) > _MAX_USER
            or (username and not username.isprintable())
        ):
            raise ConfigurationError("settings_inventory_unavailable")
        _SYNC.read(row)
        ids.add(identifier)
        numbers.add(number)
        rows.append(dict(row))
    return tuple(rows)


def phonebook_account_targets(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Expose only operations whose current book prerequisites are known."""
    if setting_id not in PHONEBOOK_ACCOUNT_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        row
        for row in phonebook_account_rows(raw)
        if setting_id != "telephony_phonebook_disconnect" or _SYNC.read(row)
    )


def _selected(setting_id: str, target_id: str, raw: SettingValues) -> dict[str, Any]:
    matches = [
        row
        for row in phonebook_account_targets(setting_id, raw)
        if row["id"] == target_id
    ]
    if len(matches) != 1:
        raise ConfigurationError("settings_target_unavailable")
    return matches[0]


def phonebook_account_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Build one selected native form with its hidden identity fields preserved."""
    spec = PHONEBOOK_ACCOUNT_TARGET_SPECS.get(setting_id)
    if (
        spec is None
        or not isinstance(target_id, str)
        or _ID.fullmatch(target_id) is None
    ):
        raise ConfigurationError("settings_target_unavailable")

    def read(raw: SettingValues) -> dict[str, Any]:
        row = _selected(setting_id, target_id, raw)
        return (
            {"onlbuch_name": row["onlbuch_name"]}
            if setting_id.endswith("rename")
            else {"execute": False}
        )

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        row = _selected(setting_id, target_id, raw)
        if setting_id.endswith("rename"):
            name = _NAME.validate(changes.get("onlbuch_name"))
            if not isinstance(name, str) or _NAME_PATTERN.fullmatch(name) is None:
                raise ConfigurationError("invalid_settings")
            return {
                "id": target_id,
                "onlbuch_nr": row["onlbuch_nr"],
                "onlbuch_bname": row["onlbuch_bname"],
                "onlbuch_name": name,
            }
        if changes != {"execute": True}:
            raise ConfigurationError("invalid_settings")
        if setting_id.endswith("delete"):
            return {
                "id": target_id,
                "onlbuch_nr": row["onlbuch_nr"],
                "deleteEntry": "delete",
            }
        return {"id": target_id, "disconnectEntry": "disconnect"}

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        expected = {row["id"]: row for row in phonebook_account_rows(before)}
        actual = {row["id"]: row for row in phonebook_account_rows(after)}
        if setting_id.endswith("delete"):
            expected.pop(target_id)
        elif setting_id.endswith("rename"):
            expected[target_id]["onlbuch_name"] = changes["onlbuch_name"]
        else:
            target = actual.get(target_id)
            if target is None or _SYNC.read(target):
                return False
            # Disconnection may clear credentials; never require resending them.
            for name in (
                "onlbuch_bname",
                "onlbuch_pwd",
                "onlbuch_domain",
                "onlbuch_sync",
            ):
                expected[target_id].pop(name, None)
                actual[target_id].pop(name, None)
        return actual == expected

    return SettingsContract(
        setting_id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        reader=read,
        builder=build,
        payload_validator=lambda raw, payload: (
            set(payload)
            == set(
                build(
                    raw,
                    {
                        "onlbuch_name": _selected(setting_id, target_id, raw)[
                            "onlbuch_name"
                        ]
                    }
                    if setting_id.endswith("rename")
                    else {"execute": True},
                )
            )
        ),
        revision_fields=(_COLLECTION,),
        target_scope=target_id,
        verifier=verify,
        verifier_owns_fields=not setting_id.endswith("rename"),
        warning=spec.warning,
        confirmation=spec.confirmation,
    )


def phonebook_account_metadata() -> list[dict[str, Any]]:
    """Publish static schema only; current account names remain private."""
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "section": "Telephony",
            "fields": [field.metadata() for field in spec.fields],
            "warning": spec.warning,
            "confirmation": spec.confirmation,
            "requires_target": True,
            "live_write_verified": False,
        }
        for spec in PHONEBOOK_ACCOUNT_TARGET_SPECS.values()
    ]


def _new_book_number(raw: SettingValues) -> str:
    rows = phonebook_account_rows(raw)
    if len(rows) >= _MAX_BOOKS:
        raise ConfigurationError("settings_capacity_reached")
    used = {row["onlbuch_nr"] for row in rows}
    # phone_onlbuch.js starts at one and picks an available native slot.
    return next(
        str(number) for number in range(1, _MAX_BOOKS + 1) if str(number) not in used
    )


def _create_read(raw: SettingValues) -> dict[str, str]:
    _new_book_number(raw)
    return {"onlbuch_name": ""}


def _create_payload(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    name = changes.get("onlbuch_name")
    if not isinstance(name, str) or _NAME_PATTERN.fullmatch(name) is None:
        raise ConfigurationError("invalid_settings")
    return {
        "id": "-1",
        "onlbuch_nr": _new_book_number(raw),
        "onlbuch_name": name,
        "onlbuch_bname": "",
    }


def _create_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    expected = _create_payload(before, changes)
    old = {row["id"]: row for row in phonebook_account_rows(before)}
    new = {row["id"]: row for row in phonebook_account_rows(after)}
    added = set(new) - set(old)
    if len(added) != 1 or not all(
        new.get(identifier) == row for identifier, row in old.items()
    ):
        return False
    created = new[added.pop()]
    return (
        all(created.get(key) == value for key, value in expected.items() if key != "id")
        and created["onlbuch_sync"] == "0"
    )


PHONEBOOK_ACCOUNT_CREATE_SETTINGS: Final = (
    SettingsContract(
        "telephony_phonebook_account_create",
        "Create local phonebook",
        "Telephony",
        PHONEBOOK_ACCOUNTS_ENDPOINT,
        PHONEBOOK_ACCOUNTS_REFERER,
        (
            SettingsField(
                "onlbuch_name", "New phonebook name", "text", minimum=0, maximum=16
            ),
        ),
        reader=_create_read,
        builder=_create_payload,
        payload_keys=frozenset({"id", "onlbuch_nr", "onlbuch_name", "onlbuch_bname"}),
        revision_fields=(_COLLECTION,),
        verifier=_create_verify,
        verifier_owns_fields=True,
        warning=(
            "This creates an empty local phonebook in the next free native "
            "slot. It does not link an online account or add contacts."
        ),
        confirmation="CREATE LOCAL PHONEBOOK",
    ),
)
