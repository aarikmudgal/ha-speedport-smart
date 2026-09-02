"""Existing manually configured VoIP providers, preserving every assigned number."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    normalize_configuration_payload,
)
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

_COLLECTION: Final = "addipphoneprovider"
_REFERER: Final = "html/content/phone/phone_internet.html"
_READ: Final = "data/IPPhoneHandler.json"
_WRITE: Final = "data/IPPhoneHandler.json"
_LIMIT: Final = 64
_MAX_PORT: Final = 65535
_NUMBER: Final = re.compile(r"(?:0|[1-9][0-9]{0,9})")
_EMAIL: Final = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


@dataclass(frozen=True, slots=True)
class ProviderTargetSpec(PhoneTargetSpec):
    """One existing provider type, with a fixed visible form and independent GET."""

    provider: str
    read_endpoint: str = _READ


PROVIDER_TARGET_SPECS: Final = MappingProxyType(
    {
        "telephony_provider_telekom": ProviderTargetSpec(
            "telephony_provider_telekom",
            "Existing Telekom telephone provider",
            _WRITE,
            _REFERER,
            _COLLECTION,
            "t_mail",
            (
                SettingsField("t_mail", "Telephone account email", "text", maximum=64),
                SettingsField(
                    "t_phonepwd", "Telephone account password", "secret", maximum=255
                ),
            ),
            "0",
        ),
        "telephony_provider_regio": ProviderTargetSpec(
            "telephony_provider_regio",
            "Existing MagentaZuhause Regio provider",
            _WRITE,
            _REFERER,
            _COLLECTION,
            "areacode",
            (SettingsField("areacode", "Area code", "text", maximum=6),),
            "89",
        ),
        "telephony_provider_other": ProviderTargetSpec(
            "telephony_provider_other",
            "Existing other telephone provider",
            _WRITE,
            _REFERER,
            _COLLECTION,
            "other_phonename",
            (
                SettingsField(
                    "other_phonename", "Telephone account name", "text", maximum=32
                ),
                SettingsField(
                    "other_phoneuser", "Telephone account username", "text", maximum=64
                ),
                SettingsField(
                    "other_pass", "Telephone account password", "secret", maximum=255
                ),
                SettingsField(
                    "other_registrar", "Registrar or proxy", "text", maximum=255
                ),
                SettingsField("other_port", "Registrar port", "text", maximum=5),
            ),
            "1",
        ),
    }
)
_WARNING: Final = (
    "Changing telephone credentials can interrupt calls, including emergency calls. "
    "All existing numbers are preserved. Masked credentials must be re-entered. "
    "Automatically managed providers cannot be edited here."
)


def _id(value: object) -> str:
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise ConfigurationError("settings_target_unavailable")
    return value


def _rows(value: object, identity: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, Mapping) and value:
        value = [value]
    if not isinstance(value, list) or len(value) > _LIMIT:
        raise ConfigurationError("settings_inventory_unavailable")
    rows = []
    identifiers = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        row = normalize_configuration_payload(item)
        identifier = _id(row.get(identity))
        if identifier in identifiers:
            raise ConfigurationError("settings_inventory_unavailable")
        identifiers.add(identifier)
        rows.append(row)
    return tuple(rows)


def provider_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Select only manual providers of the fixed type; ID 99 is router-managed."""
    spec = PROVIDER_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    rows = _rows(raw.get(_COLLECTION), "id")
    return tuple(
        row
        for row in rows
        if row["id"] != "99" and row.get("isp_selection") == spec.provider
    )


def _selected(
    spec: ProviderTargetSpec, target_id: str, raw: SettingValues
) -> tuple[int, dict[str, Any]]:
    if not any(row["id"] == target_id for row in provider_target_rows(spec.id, raw)):
        raise ConfigurationError("settings_target_unavailable")
    for ordinal, row in enumerate(_rows(raw.get(_COLLECTION), "id"), 1):
        if row["id"] == target_id:
            return ordinal, row
    raise ConfigurationError("settings_target_unavailable")


def _numbers(row: SettingValues) -> tuple[dict[str, Any], ...]:
    numbers = _rows(row.get("addipnumber"), "ipphonenumber_id")
    if not numbers:
        raise ConfigurationError("settings_inventory_unavailable")
    for number in numbers:
        SettingsField(
            "ip_number", "Telephone number", "text", minimum=1, maximum=32
        ).read(number)
    return numbers


def provider_inventory(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Share the complete existing provider parser with explicit lifecycle forms."""
    return _rows(raw.get(_COLLECTION), "id")


def provider_number_rows(row: SettingValues) -> tuple[dict[str, Any], ...]:
    """Share exact existing number identities without exposing them publicly."""
    return _numbers(row)


def _read(spec: ProviderTargetSpec, row: SettingValues) -> dict[str, Any]:
    _numbers(row)
    return _read_fields(spec, row)


def _read_fields(spec: ProviderTargetSpec, row: SettingValues) -> dict[str, Any]:
    values: dict[str, str] = {}
    for item in spec.fields:
        if item.kind != "secret":
            value = item.read(row)
            if not isinstance(value, str):
                raise ConfigurationError("invalid_settings")
            values[item.name] = value
    if (
        spec.provider == "0"
        and values["t_mail"]
        and _EMAIL.fullmatch(values["t_mail"]) is None
    ):
        raise ConfigurationError("invalid_settings")
    if (
        spec.provider == "89"
        and values["areacode"]
        and re.fullmatch(r"[0-9]{3,6}", values["areacode"]) is None
    ):
        raise ConfigurationError("invalid_settings")
    if (
        spec.provider == "1"
        and values["other_port"]
        and not (
            re.fullmatch(r"[0-9]{1,5}", values["other_port"])
            and 1 <= int(values["other_port"]) <= _MAX_PORT
        )
    ):
        raise ConfigurationError("invalid_settings")
    return values


def _online(raw: SettingValues) -> None:
    """Match the page's synchronous InternetConnection preflight, never connect."""
    connection = raw.get("internet_connection")
    if not isinstance(connection, Mapping):
        raise ConfigurationError("settings_prerequisites_unavailable")
    status = connection.get("onlinestatus")
    if status == "notconf":
        raise ConfigurationError("settings_prerequisites_unavailable")
    external = connection.get("auto_external_modem") == "1" and (
        (connection.get("extwan_typ") == "2" and connection.get("extwan_status") == "1")
        or (
            connection.get("extwan_typ") == "3"
            and connection.get("lte_status") in {"10", "11"}
        )
    )
    if status != "online" and not external:
        raise ConfigurationError("settings_prerequisites_unavailable")


def _changed_values(
    spec: ProviderTargetSpec, row: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    _numbers(row)
    return _changed_fields(spec, row, changes)


def _changed_fields(
    spec: ProviderTargetSpec, row: SettingValues, changes: SettingValues
) -> dict[str, Any]:
    modified = {**row, **changes}
    if spec.provider == "0" and "t_mail" in changes:
        # The page's visible email keyup handler lowercases the submitted
        # hidden t_mail value. Unedited saved addresses remain untouched.
        value = changes["t_mail"]
        if not isinstance(value, str):
            raise ConfigurationError("invalid_settings")
        modified["t_mail"] = value.lower()
    return _read_fields(spec, modified)


def provider_credential_payload(
    provider: str, row: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Reuse the exact visible provider fields for existing and new account forms."""
    spec = next(
        (item for item in PROVIDER_TARGET_SPECS.values() if item.provider == provider),
        None,
    )
    if spec is None or not set(changes) <= {item.name for item in spec.fields}:
        raise ConfigurationError("invalid_settings")
    result: dict[str, str | int | bool] = _changed_fields(spec, row, changes)
    for item in spec.fields:
        if item.kind == "secret":
            value = changes[item.name] if item.name in changes else row.get(item.name)
            if value == "" and item.name not in changes:
                result[item.name] = ""
            else:
                password = item.validate(value)
                if not isinstance(password, str):
                    raise ConfigurationError("invalid_settings")
                result[item.name] = password
    return result


def require_provider_online(raw: SettingValues) -> None:
    """Reuse the same read-only Internet prerequisite for provider lifecycle forms."""
    _online(raw)


def stable_provider_state(row: SettingValues) -> dict[str, Any]:
    """Expose the existing complete sibling comparator to lifecycle verification."""
    return _stable_provider(row)


def _payload(
    spec: ProviderTargetSpec, target_id: str, raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _online(raw)
    ordinal, row = _selected(spec, target_id, raw)
    _numbers(row)
    result: dict[str, str | int | bool] = {
        "id": target_id,
        "isp_selection": spec.provider,
        **provider_credential_payload(spec.provider, row, changes),
    }
    for index, number in enumerate(_numbers(row), 1):
        suffix = f"{ordinal}{index}"
        result[f"ip_number[{suffix}]"] = number["ip_number"]
        result[f"ipphonenumber_id[{suffix}]"] = number["ipphonenumber_id"]
    return result


def _verify(
    target_id: str,
    before: SettingValues,
    changes: SettingValues,
    after: SettingValues,
) -> bool:
    before_rows = _rows(before.get(_COLLECTION), "id")
    after_rows = _rows(after.get(_COLLECTION), "id")
    if {row["id"] for row in before_rows} != {row["id"] for row in after_rows}:
        return False
    actual = {row["id"]: row for row in after_rows}
    for row in before_rows:
        current = actual[row["id"]]
        if row.get("isp_selection") != current.get("isp_selection"):
            return False
        expected = _stable_provider(row)
        observed = _stable_provider(current)
        if row["id"] == target_id:
            row_spec = next(
                (
                    item
                    for item in PROVIDER_TARGET_SPECS.values()
                    if item.provider == row.get("isp_selection")
                ),
                None,
            )
            if row_spec is None:
                return False
            expected.update(_changed_values(row_spec, row, changes))
            for item in row_spec.fields:
                if item.kind == "secret" and item.name in changes:
                    # Credential persistence is separately reported unverified.
                    expected.pop(item.name, None)
                    observed.pop(item.name, None)
        if observed != expected:
            return False
    return True


def _stable_provider(row: SettingValues) -> dict[str, Any]:
    """Preserve unknown/automatic siblings without applying editable-form rules."""
    result = dict(row)
    if "addipnumber" in row:
        result["addipnumber"] = {
            number["ipphonenumber_id"]: {
                key: value
                for key, value in number.items()
                if key not in {"number_status", "errnr"}
            }
            for number in _rows(row["addipnumber"], "ipphonenumber_id")
        }
    return result


def provider_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind an existing provider, never allow caller-supplied endpoint/form keys."""
    spec = PROVIDER_TARGET_SPECS.get(setting_id)
    if spec is None:
        raise ConfigurationError("setting_unavailable")
    target_id = _id(target_id)
    if target_id == "99":
        raise ConfigurationError("settings_target_unavailable")

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        ordinal, row = _selected(spec, target_id, raw)
        expected = {"id", "isp_selection", *(item.name for item in spec.fields)}
        expected.update(
            f"{name}[{ordinal}{index}]"
            for index, _ in enumerate(_numbers(row), 1)
            for name in ("ip_number", "ipphonenumber_id")
        )
        return set(payload) == expected

    return SettingsContract(
        spec.id,
        spec.title,
        "Telephony",
        spec.endpoint,
        spec.referer,
        spec.fields,
        read_endpoint=spec.read_endpoint,
        reader=lambda raw: _read(spec, _selected(spec, target_id, raw)[1]),
        builder=lambda raw, changes: _payload(spec, target_id, raw, changes),
        payload_validator=validate_payload,
        revision_fields=(_COLLECTION,),
        expected_values=lambda raw, changes: _changed_values(
            spec, _selected(spec, target_id, raw)[1], changes
        ),
        verifier=lambda before, changes, after: _verify(
            target_id, before, changes, after
        ),
        warning=_WARNING,
        confirmation="SAVE TELEPHONE PROVIDER",
    )


def provider_target_metadata() -> list[dict[str, Any]]:
    """Describe forms without current providers, numbers, or credentials."""
    return [
        {
            "id": spec.id,
            "title": spec.title,
            "section": "Telephony",
            "fields": [item.metadata() for item in spec.fields],
            "warning": _WARNING,
            "confirmation": "SAVE TELEPHONE PROVIDER",
            "requires_target": True,
            "live_write_verified": False,
        }
        for spec in PROVIDER_TARGET_SPECS.values()
    ]
