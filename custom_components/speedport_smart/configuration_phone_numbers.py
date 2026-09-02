"""Add one number to an existing manual provider without replacing its others."""

from __future__ import annotations

import re
from copy import deepcopy
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField
from .configuration_phone_providers import (
    PROVIDER_TARGET_SPECS,
    ProviderTargetSpec,
    provider_inventory,
    provider_number_rows,
    provider_target_contract,
    provider_target_rows,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_NUMBER: Final = SettingsField("new_number", "New telephone number", "text", maximum=32)
_LIMIT: Final = 10
_VOIP_NUMBER: Final = re.compile(r"\+?[0-9 /\-.()\[\]<>]*")
_OTHER_NUMBER: Final = re.compile(r"[\x20-\x3B\x3D\x3F-\x7E\x80-\xFF]+")
_KEYS: Final = {
    key.replace("telephony_provider_", "telephony_number_create_"): key
    for key in PROVIDER_TARGET_SPECS
}
NUMBER_TARGET_SPECS: Final = MappingProxyType(
    {
        key: ProviderTargetSpec(
            key,
            f"Add number to {spec.title.removeprefix('Existing ')}",
            spec.endpoint,
            spec.referer,
            spec.collection,
            spec.label_key,
            (_NUMBER, *spec.fields),
            spec.provider,
            spec.read_endpoint,
        )
        for key, original in _KEYS.items()
        if (spec := PROVIDER_TARGET_SPECS[original])
    }
)
_WARNING: Final = (
    "Adding a telephone number resubmits its provider account and may interrupt "
    "calls, including emergency calls. Existing numbers and their options are "
    "preserved. A save is sent once; inspect an uncertain result before retrying."
)


def normalize_new_phone_number(value: object, provider: str) -> str:
    """Apply the exact visible provider-specific validation and Telekom conversion."""
    value = _NUMBER.validate(value)
    if not isinstance(value, str) or not value or provider not in {"0", "1", "89"}:
        raise ConfigurationError("invalid_settings")
    pattern = _OTHER_NUMBER if provider == "1" else _VOIP_NUMBER
    if pattern.fullmatch(value) is None:
        raise ConfigurationError("invalid_settings")
    if provider == "0":
        value = re.sub(r"[ /\-.()\[\]<>]", "", value)
        if value.startswith("00"):
            value = "+" + value[2:]
        if value.startswith("0"):
            value = "+49" + value[1:]
        if not value.startswith("+49") or len(value) <= len("+49"):
            raise ConfigurationError("invalid_settings")
    return value


def _aliases(value: str) -> set[str]:
    alternate = (
        "+49" + value[1:]
        if value.startswith("0")
        else "0" + value[3:]
        if value.startswith("+49")
        else value
    )
    return {value, alternate}


def number_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """List only existing manual providers of the declared type with capacity."""
    original = _KEYS.get(setting_id)
    if original is None:
        raise ConfigurationError("setting_unavailable")
    if sum(len(provider_number_rows(row)) for row in provider_inventory(raw)) >= _LIMIT:
        raise ConfigurationError("settings_capacity_reached")
    return tuple(
        row
        for row in provider_target_rows(original, raw)
        if len(provider_number_rows(row)) < _LIMIT
    )


def _selected(
    setting_id: str, target_id: str, raw: SettingValues
) -> tuple[int, dict[str, Any]]:
    if not any(row["id"] == target_id for row in number_target_rows(setting_id, raw)):
        raise ConfigurationError("settings_target_unavailable")
    for ordinal, row in enumerate(provider_inventory(raw), 1):
        if row["id"] == target_id:
            return ordinal, row
    raise ConfigurationError("settings_target_unavailable")


def _new_number(setting_id: str, raw: SettingValues, changes: SettingValues) -> str:
    value = normalize_new_phone_number(
        changes.get("new_number"), NUMBER_TARGET_SPECS[setting_id].provider
    )
    for row in provider_inventory(raw):
        for number in provider_number_rows(row):
            if _aliases(value) & _aliases(number["ip_number"]):
                raise ConfigurationError("invalid_settings")
    return value


def number_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind complete provider-form reuse plus one new nested number sentinel."""
    spec = NUMBER_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    original = provider_target_contract(_KEYS[setting_id], target_id)

    def read(raw: SettingValues) -> dict[str, Any]:
        _selected(setting_id, target_id, raw)
        return {**original.read(raw), "new_number": ""}

    def credential_changes(changes: SettingValues) -> dict[str, Any]:
        return {
            **{key: value for key, value in changes.items() if key != "new_number"},
        }

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        ordinal, row = _selected(setting_id, target_id, raw)
        value = _new_number(setting_id, raw, changes)
        # Empty account changes preserve exact spelling; no artificial edit or
        # extra POST is added while reusing the existing complete-form builder.
        if original.builder is None:
            raise ConfigurationError("setting_unavailable")
        result = original.builder(raw, credential_changes(changes))
        suffix = f"{ordinal}{len(provider_number_rows(row)) + 1}"
        result.update(
            {f"ip_number[{suffix}]": value, f"ipphonenumber_id[{suffix}]": "-1"}
        )
        return result

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        ordinal, row = _selected(setting_id, target_id, raw)
        names = {"id", "isp_selection", *(field.name for field in original.fields)}
        names.update(
            f"{name}[{ordinal}{index}]"
            for index in range(1, len(provider_number_rows(row)) + 2)
            for name in ("ip_number", "ipphonenumber_id")
        )
        return set(payload) == names

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        _, previous = _selected(setting_id, target_id, before)
        matches = [row for row in provider_inventory(after) if row["id"] == target_id]
        if len(matches) != 1:
            return False
        current = matches[0]
        old_ids = {
            number["ipphonenumber_id"] for number in provider_number_rows(previous)
        }
        new_rows = provider_number_rows(current)
        added = [
            number for number in new_rows if number["ipphonenumber_id"] not in old_ids
        ]
        if (
            len(added) != 1
            or len(new_rows) != len(old_ids) + 1
            or added[0]["ip_number"] != _new_number(setting_id, before, changes)
            or added[0]["ipphonenumber_id"]
            in {
                number["ipphonenumber_id"]
                for provider in provider_inventory(before)
                for number in provider_number_rows(provider)
            }
        ):
            return False
        stripped = deepcopy(dict(after))
        stripped["addipphoneprovider"] = [
            dict(row) for row in provider_inventory(after)
        ]
        for row in stripped["addipphoneprovider"]:
            if row["id"] == target_id:
                row["addipnumber"] = [
                    number
                    for number in new_rows
                    if number["ipphonenumber_id"] in old_ids
                ]
        return original.verifier is not None and original.verifier(
            before, credential_changes(changes), stripped
        )

    return SettingsContract(
        setting_id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        read_endpoint=spec.read_endpoint,
        reader=read,
        builder=build,
        payload_validator=validate_payload,
        revision_fields=("addipphoneprovider",),
        verifier=verify,
        verifier_owns_fields=True,
        warning=_WARNING,
        confirmation="ADD TELEPHONE NUMBER",
    )


def number_target_metadata() -> list[dict[str, Any]]:
    """Describe new-number forms without exposing account details or numbers."""
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "section": "Telephony",
            "fields": [field.metadata() for field in spec.fields],
            "warning": _WARNING,
            "confirmation": "ADD TELEPHONE NUMBER",
            "requires_target": True,
            "live_write_verified": False,
        }
        for spec in NUMBER_TARGET_SPECS.values()
    ]
