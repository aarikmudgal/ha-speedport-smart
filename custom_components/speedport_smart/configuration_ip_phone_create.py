"""One-shot allocation of native IP-PBX clients before ordinary row editing."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, boolean
from .configuration_phone_targets import phone_target_rows

if TYPE_CHECKING:
    from .configuration import SettingValues

SETTING_ID: Final = "telephony_ip_phone_create"
_FIELD: Final = boolean("create", "Create IP phone credentials")
_MAX_CLIENTS: Final = 3  # global.js routerConfig.hardware.maxIPPBX
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_WARNING: Final = (
    "This allocates one IP phone credential set in the router. The generated "
    "credential values remain private. If the new row cannot be identified after "
    "the single request, inspect IP phone settings before trying again."
)


def _inventory(raw: SettingValues) -> dict[str, dict[str, Any]]:
    rows = phone_target_rows("telephony_ip_phone", raw)
    if len(rows) > _MAX_CLIENTS:
        raise ConfigurationError("settings_inventory_unavailable")
    return {row["id"]: row for row in rows}


def _read(raw: SettingValues) -> dict[str, bool]:
    if len(_inventory(raw)) >= _MAX_CLIENTS:
        raise ConfigurationError("settings_capacity_reached")
    return {"create": False}


def _response(raw: SettingValues) -> None:
    """Require the native allocation callback's bounded newestID."""
    identifier = raw.get("newestID")
    if not isinstance(identifier, str) or _ID.fullmatch(identifier) is None:
        raise ConfigurationError("action_outcome_unknown")


def ip_phone_created_id(before: SettingValues, response: SettingValues) -> str:
    """Bind the exact allocated identity to subsequent independent GET readback."""
    _response(response)
    identifier = str(response["newestID"])
    if identifier in _inventory(before):
        raise ConfigurationError("action_outcome_unknown")
    return identifier


def _verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    if changes != {"create": True}:
        return False
    old = _inventory(before)
    new = _inventory(after)
    added = set(new) - set(old)
    if added != {after.get("_created_ip_phone_id")}:
        return False
    return (
        len(added) == 1
        and set(old) < set(new)
        and all(new[identifier] == row for identifier, row in old.items())
    )


def ip_phone_create_contract() -> SettingsContract:
    """Allocate exactly one row through the firmware's explicit command."""
    return SettingsContract(
        SETTING_ID,
        "Create IP phone",
        "Telephony",
        "data/IPClients.json",
        "html/content/phone/phone_ippbx.html",
        (_FIELD,),
        read_endpoint="data/IPPBX.json",
        reader=_read,
        builder=lambda raw, changes: (
            {"add_ipcl": "add ip phone"}
            if _read(raw) == {"create": False} and changes == {"create": True}
            else _invalid()
        ),
        payload_validator=lambda _raw, payload: payload == {"add_ipcl": "add ip phone"},
        revision_fields=("addipclient",),
        response_validator=_response,
        expected_values=lambda _raw, _changes: {"create": True},
        verifier=_verify,
        verifier_owns_fields=True,
        warning=_WARNING,
        confirmation="CREATE IP PHONE",
    )


def _invalid() -> dict[str, str | int | bool]:
    raise ConfigurationError("invalid_settings")


def ip_phone_create_metadata() -> list[dict[str, Any]]:
    """Return only static catalog data, never generated credentials."""
    return [ip_phone_create_contract().metadata()]
