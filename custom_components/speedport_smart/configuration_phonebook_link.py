"""Private first-stage account editor; contact synchronization is separate."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, choice
from .configuration_phone_targets import PhoneTargetSpec
from .configuration_phonebook_accounts import (
    PHONEBOOK_ACCOUNTS_ENDPOINT,
    PHONEBOOK_ACCOUNTS_REFERER,
    phonebook_account_rows,
)
from .configuration_phonebook_lifecycle import phonebook_inventory
from .phonebook_link import online_phonebook_link_payload

if TYPE_CHECKING:
    from .configuration import SettingValues

LINK_SETTING_ID: Final = "telephony_phonebook_link"
_FIELDS: Final = (
    SettingsField(
        "onlbuch_bname", "Online account user", "secret", minimum=1, maximum=255
    ),
    choice(
        "onlbuch_domain",
        "Account domain (native firmware option)",
        (
            ("0", "Firmware option 0"),
            ("1", "Firmware option 1"),
            ("2", "Firmware option 2"),
        ),
    ),
    SettingsField(
        "onlbuch_pwd", "Online account password", "secret", minimum=1, maximum=255
    ),
)
PHONEBOOK_LINK_TARGET_SPECS: Final = MappingProxyType(
    {
        LINK_SETTING_ID: PhoneTargetSpec(
            LINK_SETTING_ID,
            "Link online phonebook (step 1)",
            PHONEBOOK_ACCOUNTS_ENDPOINT,
            PHONEBOOK_ACCOUNTS_REFERER,
            "addonlbuchentry",
            "onlbuch_name",
            _FIELDS,
        ),
    }
)


def phonebook_link_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Offer only explicitly returned, currently unlinked books."""
    if setting_id != LINK_SETTING_ID:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        row for row in phonebook_account_rows(raw) if row["onlbuch_sync"] == "0"
    )


def phonebook_link_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind credentials and local contact contents before the first single POST."""
    spec = PHONEBOOK_LINK_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")

    def selected(raw: SettingValues) -> dict[str, Any]:
        matches = [
            row
            for row in phonebook_link_rows(setting_id, raw)
            if row["id"] == target_id
        ]
        if len(matches) != 1:
            raise ConfigurationError("settings_target_unavailable")
        return matches[0]

    def read(raw: SettingValues) -> dict[str, Any]:
        selected(raw)
        return {"onlbuch_domain": "0"}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        selected(raw)
        return dict(
            online_phonebook_link_payload(
                raw,
                target_id,
                username=changes.get("onlbuch_bname", ""),
                domain=changes.get("onlbuch_domain", "0"),
                password=changes.get("onlbuch_pwd", ""),
            )
        )

    def revision(raw: SettingValues) -> dict[str, Any]:
        row = selected(raw)
        local = raw.get("local_inventory")
        if not isinstance(local, dict):
            raise ConfigurationError("settings_inventory_unavailable")
        return {
            "books": phonebook_account_rows(raw),
            "contacts": phonebook_inventory(
                local,
                phonebook_id=int(row["onlbuch_nr"]),
            ),
        }

    return SettingsContract(
        spec.id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        target_scope=target_id,
        reader=read,
        builder=build,
        revision_values=revision,
        payload_keys=frozenset(
            {"id", "onlbuch_name", "onlbuch_bname", "onlbuch_domain", "onlbuch_pwd"}
        ),
        readback_policy="manual_required",
        confirmation="AUTHENTICATE ONLINE PHONEBOOK",
        warning=(
            "Authenticates the selected online account once. This first step may "
            "save its account binding, but does not authorize merging or replacing "
            "contacts. A second explicit confirmation is required. Domain values "
            "are native firmware option numbers; check the router UI if unsure."
        ),
    )


def phonebook_link_metadata() -> list[dict[str, Any]]:
    """Expose only static field descriptors, never usernames or contact values."""
    return [
        {
            **phonebook_link_contract(LINK_SETTING_ID, "0").metadata(),
            "requires_target": True,
        }
    ]
