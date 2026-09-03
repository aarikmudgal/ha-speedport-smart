"""Reviewed telephony scalar forms with complete payload preservation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_PHONE: Final = "html/content/phone/"
_DECT_ENABLED: Final = boolean("use_dect", "DECT base station")
_SMART_HOME: Final = boolean("use_smarthome", "Smart Home")
_DECT_PIN: Final = SettingsField(
    "dect_pin",
    "DECT PIN",
    "secret",
    minimum=4,
    maximum=8,
    description=(
        "Four to eight digits. Leave blank to preserve a readable current PIN; "
        "if the router masks it, re-enter it before saving other DECT settings."
    ),
)
_DECT_POWER: Final = choice(
    "dect_halb", "Transmission power", (("0", "Full"), ("1", "Reduced"))
)
_DECT_ECO: Final = choice("dect_eco", "Full Eco mode", (("0", "Off"), ("1", "On")))
_VOSIP: Final = choice(
    "phone_vosip_policy",
    "Voice encryption",
    (("0", "Off"), ("1", "Level 1"), ("2", "Level 2")),
    description="Requires a configured Telekom telephone provider.",
)
_EXTERNAL_MODEM: Final = boolean("auto_external_modem", "External modem")


def _wire_value(
    field: SettingsField, raw: SettingValues, changes: SettingValues
) -> str | int | bool:
    """Return an exact changed value or the current field, without coercion."""
    value = (
        field.validate(changes[field.name])
        if field.name in changes
        else field.read(raw)
    )
    if isinstance(value, list):
        raise ConfigurationError("invalid_contract_payload")
    return ("1" if value else "0") if type(value) is bool else value


def _dect_module_read(raw: SettingValues) -> dict[str, Any]:
    """Hide manual DECT switching while Smart Home owns the base."""
    if _SMART_HOME.read(raw):
        raise ConfigurationError("dect_owned_by_smarthome")
    return {"use_dect": _DECT_ENABLED.read(raw)}


def _dect_module_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Recheck ownership immediately before the single-field Modules write."""
    _dect_module_read(raw)
    return {"use_dect": _wire_value(_DECT_ENABLED, raw, changes)}


def _repeater_rows(raw: SettingValues) -> list[Mapping[str, Any]]:
    """Require a complete explicit repeater list, never guess absent means zero."""
    rows = raw.get("addrepeater")
    if isinstance(rows, Mapping) and rows:
        rows = [rows]
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ConfigurationError("dect_repeater_state_unavailable")
    return rows


def normalize_dect_station_payload(
    raw: SettingValues, *, authenticated: bool
) -> dict[str, Any]:
    """
    Recognize zero templates only in a complete authenticated station read.

    Firmware getREPCount counts addrepeater templates and returns zero when
    none exist. Do not extend that convention to partial or unauthenticated
    payloads, explicit nulls, empty mappings, or other collections.
    """
    result = dict(raw)
    if "addrepeater" in result or authenticated is not True:
        return result
    if any(
        not isinstance(raw.get(name), str)
        for name in ("router_state", "loginstate", "dect_pin")
    ):
        return result
    try:
        for item in (_DECT_ENABLED, _SMART_HOME, _DECT_POWER, _DECT_ECO):
            item.read(raw)
    except ConfigurationError:
        return result
    result["addrepeater"] = []
    return result


def _dect_settings_read(raw: SettingValues) -> dict[str, Any]:
    """Validate prerequisites without exposing the current DECT PIN."""
    _repeater_rows(raw)
    return {
        "dect_halb": _DECT_POWER.read(raw),
        "dect_eco": _DECT_ECO.read(raw),
    }


def _dect_settings_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Preserve the PIN and omit radio options hidden by an existing repeater."""
    repeaters = _repeater_rows(raw)
    pin = _wire_value(_DECT_PIN, raw, changes)
    if not isinstance(pin, str) or re.fullmatch(r"[0-9]{4,8}", pin) is None:
        raise ConfigurationError("dect_pin_unavailable_or_invalid")
    payload: dict[str, str | int | bool] = {"dect_pin": pin}
    if repeaters:
        if {"dect_halb", "dect_eco"} & changes.keys():
            raise ConfigurationError("dect_radio_settings_blocked_by_repeater")
        return payload
    payload.update(
        dect_halb=_wire_value(_DECT_POWER, raw, changes),
        dect_eco=_wire_value(_DECT_ECO, raw, changes),
    )
    return payload


def _vosip_prerequisites(raw: SettingValues) -> bool:
    """Return active external-5G state only after all necessary facts are known."""
    providers = raw.get("addipphoneprovider")
    # The firmware codec represents one template row as a mapping, while two
    # or more rows form a list. Normalize this one proven collection locally.
    if isinstance(providers, Mapping):
        providers = [providers]
    if not isinstance(providers, list) or not providers:
        raise ConfigurationError("vosip_provider_unavailable")
    choices = []
    for provider in providers:
        if not isinstance(provider, Mapping):
            raise ConfigurationError("vosip_provider_unavailable")
        value = provider.get("isp_selection")
        if type(value) is int and value >= 0:
            value = str(value)
        if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
            raise ConfigurationError("vosip_provider_unavailable")
        choices.append(value)
    if "0" not in choices:
        raise ConfigurationError("vosip_requires_telekom_provider")
    if not _EXTERNAL_MODEM.read(raw):
        return False
    kind = raw.get("extwan_typ")
    if type(kind) is int:
        kind = str(kind)
    if not isinstance(kind, str) or re.fullmatch(r"[0-9]+", kind) is None:
        raise ConfigurationError("vosip_external_modem_state_unavailable")
    if kind != "3":
        return False
    status = raw.get("lte_status")
    if type(status) is int:
        status = str(status)
    if not isinstance(status, str) or re.fullmatch(r"[0-9]+", status) is None:
        raise ConfigurationError("vosip_external_modem_state_unavailable")
    return status in {"10", "11"}


def _vosip_read(raw: SettingValues) -> dict[str, Any]:
    """Expose the policy only when its prerequisite data is complete."""
    _vosip_prerequisites(raw)
    return {"phone_vosip_policy": _VOSIP.read(raw)}


def _vosip_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Match the firmware's external-5G restriction on entering level two."""
    external_5g = _vosip_prerequisites(raw)
    current = _VOSIP.read(raw)
    value = _wire_value(_VOSIP, raw, changes)
    if external_5g and current != "2" and value == "2":
        raise ConfigurationError("vosip_level_two_unavailable_on_external_5g")
    return {"phone_vosip_policy": value}


TELEPHONY_SETTINGS: Final = (
    SettingsContract(
        "telephony_dect_enabled",
        "DECT base station",
        "Telephony",
        "data/Modules.json",
        _PHONE + "phone_dect_settings.html",
        (_DECT_ENABLED,),
        read_endpoint="data/DECTStation.json",
        reader=_dect_module_read,
        builder=_dect_module_build,
        revision_fields=("use_smarthome",),
        acknowledgement="readback",
        warning="Switching off DECT disconnects registered cordless phones.",
    ),
    SettingsContract(
        "telephony_dect_settings",
        "DECT PIN, transmission power and Eco mode",
        "Telephony",
        "data/DECTSettings.json",
        _PHONE + "phone_dect_settings.html",
        (_DECT_PIN, _DECT_POWER, _DECT_ECO),
        read_endpoint="data/DECTStation.json",
        reader=_dect_settings_read,
        builder=_dect_settings_build,
        revision_fields=("addrepeater",),
        warning=(
            "Changing the PIN affects future pairing. Reduced power changes coverage. "
            "Full Eco mode increases handset power use and call setup delay. "
            "Radio options cannot be changed while a DECT repeater is registered."
        ),
    ),
    SettingsContract(
        "telephony_voice_encryption",
        "Voice encryption (VoSIP)",
        "Telephony",
        "data/Phone.json",
        _PHONE + "phone_linevosip.html",
        (_VOSIP,),
        read_endpoint="data/PhoneLineset.json",
        reader=_vosip_read,
        builder=_vosip_build,
        revision_fields=(
            "addipphoneprovider",
            "auto_external_modem",
            "extwan_typ",
            "lte_status",
        ),
        warning=(
            "Changing voice encryption may interrupt telephone registration or calls. "
            "The router can reject levels unsupported by the provider."
        ),
    ),
    SettingsContract(
        "telephony_ip_pbx_enabled",
        "IP telephone system",
        "Telephony",
        "data/Modules.json",
        _PHONE + "phone_ippbx.html",
        (boolean("use_ippbx", "IP telephone system"),),
        read_endpoint="data/IPPBX.json",
        acknowledgement="readback",
        warning="Switching off the IP telephone system disconnects IP phone clients.",
    ),
    SettingsContract(
        "telephony_automatic_speed_dial",
        "Automatic phone number memory",
        "Telephony",
        "data/Modules.json",
        _PHONE + "phone_linespeeddial.html",
        (boolean("use_speeddial", "Automatic phone number memory"),),
        read_endpoint="data/PhoneLineset.json",
        acknowledgement="readback",
        warning="This changes automatic number learning, not the stored phonebook.",
    ),
    SettingsContract(
        "telephony_phonebook_update_interval",
        "Online phonebook update interval",
        "Telephony",
        "data/DECTSettings.json",
        _PHONE + "phone_book_basic.html",
        (
            choice(
                "phonebook_int",
                "Update interval",
                (("1", "15 minutes"), ("2", "30 minutes"), ("3", "60 minutes")),
            ),
        ),
        warning="The interval applies to all linked online address books.",
    ),
)
