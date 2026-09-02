"""Create one manually configured telephone provider with one initial number."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField
from .configuration_phone_numbers import normalize_new_phone_number
from .configuration_phone_providers import (
    PROVIDER_TARGET_SPECS,
    ProviderTargetSpec,
    provider_credential_payload,
    provider_inventory,
    provider_number_rows,
    require_provider_online,
    stable_provider_state,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_MAX_PROVIDERS: Final = 10
_MAX_NUMBERS: Final = 10
_NUMBER: Final = SettingsField(
    "new_number", "Initial telephone number", "text", maximum=32
)
_WARNING: Final = (
    "This creates a new manual telephone-provider account and submits its "
    "credentials to the router. Existing accounts are preserved. Telephone "
    "registration is not guaranteed by saving settings. Check an uncertain "
    "outcome before retrying to avoid duplicate accounts."
)


def _context(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    rows = provider_inventory(raw)
    if (
        len(rows) >= _MAX_PROVIDERS
        or sum(len(provider_number_rows(row)) for row in rows) >= _MAX_NUMBERS
    ):
        raise ConfigurationError("settings_capacity_reached")
    return rows


def _new_number(
    spec: ProviderTargetSpec, raw: SettingValues, changes: SettingValues
) -> str:
    number = normalize_new_phone_number(changes.get("new_number"), spec.provider)
    alternate = (
        "0" + number[3:]
        if number.startswith("+49")
        else "+49" + number[1:]
        if number.startswith("0")
        else number
    )
    for row in _context(raw):
        if any(
            item["ip_number"] in {number, alternate}
            for item in provider_number_rows(row)
        ):
            raise ConfigurationError("invalid_settings")
    return number


def _create_contract(spec: ProviderTargetSpec) -> SettingsContract:
    setting_id = spec.id.replace("telephony_provider_", "telephony_provider_create_")
    fields = (_NUMBER, *spec.fields)

    def read(raw: SettingValues) -> dict[str, str]:
        _context(raw)
        # These are explicit blank inputs for a new form, not guessed saved data.
        return {field.name: "" for field in fields if field.kind != "secret"}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        require_provider_online(raw)
        number = _new_number(spec, raw, changes)
        account_changes = {
            key: value for key, value in changes.items() if key != "new_number"
        }
        credentials = provider_credential_payload(
            spec.provider, {field.name: "" for field in spec.fields}, account_changes
        )
        ordinal = len(_context(raw)) + 1
        return {
            "id": "-1",
            "isp_selection": spec.provider,
            **credentials,
            f"ip_number[{ordinal}1]": number,
            f"ipphonenumber_id[{ordinal}1]": "-1",
        }

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        ordinal = len(_context(raw)) + 1
        return set(payload) == {
            "id",
            "isp_selection",
            *(field.name for field in spec.fields),
            f"ip_number[{ordinal}1]",
            f"ipphonenumber_id[{ordinal}1]",
        }

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        previous = _context(before)
        current = provider_inventory(after)
        previous_ids = {row["id"] for row in previous}
        added = [row for row in current if row["id"] not in previous_ids]
        if (
            len(added) != 1
            or len(current) != len(previous) + 1
            or added[0]["id"] == "99"
        ):
            return False
        indexed = {row["id"]: row for row in current}
        if any(
            stable_provider_state(row)
            != stable_provider_state(indexed.get(row["id"], {}))
            for row in previous
        ):
            return False
        created = added[0]
        if created.get("isp_selection") != spec.provider:
            return False
        numbers = provider_number_rows(created)
        existing_number_ids = {
            number["ipphonenumber_id"]
            for row in previous
            for number in provider_number_rows(row)
        }
        if (
            len(numbers) != 1
            or numbers[0]["ip_number"] != _new_number(spec, before, changes)
            or numbers[0]["ipphonenumber_id"] in existing_number_ids
        ):
            return False
        payload = build(before, changes)
        for field in spec.fields:
            if field.kind != "secret" and field.read(created) != payload[field.name]:
                return False
        return True

    return SettingsContract(
        setting_id,
        spec.title.replace("Existing ", "Create "),
        "Telephony",
        spec.endpoint,
        spec.referer,
        fields,
        read_endpoint=spec.read_endpoint,
        reader=read,
        builder=build,
        payload_validator=validate_payload,
        revision_fields=("addipphoneprovider",),
        verifier=verify,
        verifier_owns_fields=True,
        warning=_WARNING,
        confirmation="CREATE TELEPHONE PROVIDER",
    )


PROVIDER_CREATE_SETTINGS: Final = tuple(
    _create_contract(spec) for spec in PROVIDER_TARGET_SPECS.values()
)
