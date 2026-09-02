"""Closed two-stage online phonebook payloads; the owner provides one-use grants."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsField
from .configuration_phonebook_accounts import phonebook_account_rows

if TYPE_CHECKING:
    from .configuration import SettingValues

_MAX_CONTACTS: Final = 1000
_COUNT: Final = re.compile(r"0|[1-9][0-9]{0,3}")
_USER: Final = SettingsField(
    "onlbuch_bname", "Online account user", "text", minimum=1, maximum=255
)
_PASSWORD: Final = SettingsField(
    "onlbuch_pwd", "Online account password", "secret", minimum=1, maximum=255
)


@dataclass(frozen=True, slots=True, repr=False)
class OnlinePhonebookStage:
    """Keep only an exact book binding and bounded server count, never passwords."""

    target_id: str
    book_number: str
    name: str
    username: str = field(repr=False)
    domain: str
    online_count: str


def _book(raw: SettingValues, target_id: str) -> dict[str, Any]:
    matches = [row for row in phonebook_account_rows(raw) if row["id"] == target_id]
    if len(matches) != 1:
        raise ConfigurationError("settings_target_unavailable")
    return matches[0]


def online_phonebook_link_payload(
    raw: SettingValues, target_id: str, *, username: str, domain: str, password: str
) -> dict[str, str]:
    """Authenticate one existing unlinked book without choosing merge or replace."""
    row = _book(raw, target_id)
    if row["onlbuch_sync"] != "0" or domain not in {"0", "1", "2"}:
        raise ConfigurationError("invalid_settings")
    return {
        "id": target_id,
        "onlbuch_name": row["onlbuch_name"],
        "onlbuch_bname": str(_USER.validate(username)),
        "onlbuch_domain": domain,
        "onlbuch_pwd": str(_PASSWORD.validate(password)),
    }


def online_phonebook_link_stage(
    before: SettingValues,
    target_id: str,
    *,
    username: str,
    domain: str,
    response: SettingValues,
) -> OnlinePhonebookStage:
    """Require the native first-stage ACK and a bounded count before any next step."""
    row = _book(before, target_id)
    _USER.validate(username)
    count = response.get("sum_onlineContacts")
    assigned_id = response.get("assignedID", target_id)
    if (
        domain not in {"0", "1", "2"}
        or response.get("status") != "ok"
        or assigned_id != target_id
        or not isinstance(count, str)
        or _COUNT.fullmatch(count) is None
        or int(count) > _MAX_CONTACTS
    ):
        raise ConfigurationError("action_outcome_unknown")
    return OnlinePhonebookStage(
        target_id, row["onlbuch_nr"], row["onlbuch_name"], username, domain, count
    )


def online_phonebook_finish_payload(
    fresh: SettingValues, stage: OnlinePhonebookStage, *, merge_existing: bool
) -> dict[str, str | bool]:
    """Build the separately confirmed merge/replace step after fresh account binding."""
    if type(merge_existing) is not bool:
        raise ConfigurationError("confirmation_required")
    row = _book(fresh, stage.target_id)
    if (
        row["onlbuch_nr"] != stage.book_number
        or row["onlbuch_name"] != stage.name
        or row["onlbuch_bname"] != stage.username
        or row.get("onlbuch_domain") != stage.domain
    ):
        raise ConfigurationError("stale_settings")
    return {
        "id": stage.target_id,
        "join_availEntries": merge_existing,
        "sum_onlineContacts": stage.online_count,
    }
