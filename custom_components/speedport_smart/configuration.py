"""Closed, typed configuration forms for reviewed router firmware."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

SettingKind = Literal[
    "boolean", "enum", "integer", "text", "secret", "time", "identifiers"
]
SettingValues = Mapping[str, Any]
SettingBuilder = Callable[[SettingValues, SettingValues], dict[str, str | int | bool]]
SettingReader = Callable[[SettingValues], dict[str, Any]]
SettingChoices = Callable[[SettingValues], Mapping[str, tuple[tuple[str, str], ...]]]
PayloadValidator = Callable[[SettingValues, SettingValues], bool]
SettingVerifier = Callable[[SettingValues, SettingValues, SettingValues], bool]
_FIRST_PRINTABLE = 32
_DELETE_CHARACTER = 127
_KINDS = frozenset(
    {"boolean", "enum", "integer", "text", "secret", "time", "identifiers"}
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_MAX_CHOICES = 256
_CHOICE_PARTS = 2
_MAX_CHOICE_LABEL = 256
_SECRET_MASK = re.compile(
    r"(?:\[|<)?(?:\*\*)?redacted(?:\*\*)?(?:\]|>)?", re.IGNORECASE
)


class ConfigurationError(ValueError):
    """Value-free configuration rejection, safe for administrator responses."""

    def __init__(self, code: str = "invalid_settings") -> None:
        """Retain a fixed, value-free error code."""
        super().__init__(code)
        self.code = code


def normalize_configuration_payload(raw: SettingValues) -> dict[str, Any]:
    """Unwrap only duplicated identical top-level scalar router variables."""
    normalized = dict(raw)
    for name, value in raw.items():
        if (
            isinstance(value, list)
            and value
            and type(value[0]) in {str, int, bool}
            and all(type(item) is type(value[0]) and item == value[0] for item in value)
        ):
            normalized[name] = value[0]
    return normalized


@dataclass(frozen=True, slots=True)
class SettingsField:
    """One reviewed field; bounds and choices also drive the dashboard editor."""

    name: str
    label: str
    kind: SettingKind
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int = 0
    maximum: int = 256
    read_key: str | None = None
    description: str = ""
    dynamic_choices: bool = False

    def __post_init__(self) -> None:
        """Reject malformed static declarations at import time."""
        if (
            not self.name.isidentifier()
            or self.kind not in _KINDS
            or type(self.minimum) is not int
            or type(self.maximum) is not int
            or self.minimum > self.maximum
        ):
            raise ValueError("Invalid static settings field")
        if self.dynamic_choices and self.kind not in {"enum", "identifiers"}:
            raise ValueError("Dynamic choices require a selection field")
        if self.kind == "enum" and not self.choices and not self.dynamic_choices:
            raise ValueError("Enum settings require reviewed choices")

    def validate(self, value: object) -> str | int | bool | list[str]:
        """Reject coercion, control characters and unreviewed enum values."""
        if self.kind == "identifiers":
            if (
                type(value) is list
                and self.minimum <= len(value) <= min(self.maximum, _MAX_CHOICES)
                and all(
                    type(item) is str and _IDENTIFIER.fullmatch(item) for item in value
                )
                and len(set(value)) == len(value)
            ):
                return sorted(value)
        elif self.kind == "boolean":
            if type(value) is bool:
                return value
        elif self.kind == "integer":
            if type(value) is int and self.minimum <= value <= self.maximum:
                return value
        elif type(value) is str and not any(
            ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER
            for char in value
        ):
            if self.kind == "enum" and (
                value in {key for key, _ in self.choices}
                or (self.dynamic_choices and _IDENTIFIER.fullmatch(value))
            ):
                return value
            if self.kind == "time" and re.fullmatch(
                r"(?:[01]\d|2[0-3]):[0-5]\d", value
            ):
                return value
            if (
                self.kind in {"text", "secret"}
                and self.minimum <= len(value) <= self.maximum
                and (
                    self.kind != "secret"
                    or (
                        value
                        and not re.fullmatch(r"[*•●]+", value)
                        and _SECRET_MASK.fullmatch(value) is None
                    )
                )
            ):
                return value
        raise ConfigurationError

    def read(self, raw: SettingValues) -> str | int | bool | list[str]:
        """Decode only the wire representation of this exact field."""
        value = raw.get(self.read_key or self.name)
        if self.kind == "boolean":
            if type(value) is str and value in {"0", "1"}:
                value = value == "1"
            elif type(value) is int and value in {0, 1}:
                value = value == 1
        elif (
            self.kind == "integer"
            and type(value) is str
            and re.fullmatch(r"\d+", value)
        ):
            value = int(value)
        elif self.kind == "enum" and type(value) is int:
            value = str(value)
        return self.validate(value)

    def metadata(self) -> dict[str, Any]:
        """Return static UI metadata, never a current router value."""
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "choices": [{"value": key, "label": label} for key, label in self.choices],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "description": self.description,
            "dynamic_choices": self.dynamic_choices,
        }


@dataclass(frozen=True, slots=True)
class SettingsContract:
    """One allowlisted form, not a generic endpoint or payload passthrough."""

    id: str
    title: str
    section: str
    endpoint: str
    referer: str
    fields: tuple[SettingsField, ...]
    read_endpoint: str | None = None
    read_referer: str | None = None
    builder: SettingBuilder | None = field(default=None, repr=False)
    reader: SettingReader | None = field(default=None, repr=False)
    warning: str = "Changing these settings may interrupt connected devices."
    confirmation: str = "SAVE SETTINGS"
    payload_keys: frozenset[str] | None = None
    revision_fields: tuple[str, ...] = ()
    acknowledgement: Literal["status_ok", "result_ok", "readback"] = "status_ok"
    readback_policy: Literal["exact", "reconnect_required", "manual_required"] = "exact"
    field_choices: SettingChoices | None = field(default=None, repr=False)
    revision_values: SettingReader | None = field(default=None, repr=False)
    payload_validator: PayloadValidator | None = field(default=None, repr=False)
    verifier: SettingVerifier | None = field(default=None, repr=False)
    verifier_owns_fields: bool = False
    expected_values: Callable[[SettingValues, SettingValues], dict[str, Any]] | None = (
        field(default=None, repr=False)
    )
    response_validator: Callable[[SettingValues], None] | None = field(
        default=None, repr=False
    )
    target_scope: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Keep endpoints, field names and form identity closed and static."""
        if not self.id.isidentifier() or not self.fields:
            raise ValueError("Invalid static settings contract")
        if self.target_scope is not None and (
            type(self.target_scope) is not str
            or not _IDENTIFIER.fullmatch(self.target_scope)
        ):
            raise ValueError("Invalid settings target scope")
        for endpoint in (self.endpoint, self.read_endpoint or self.endpoint):
            if not re.fullmatch(r"data/[A-Za-z0-9_]+\.json", endpoint):
                raise ValueError("Settings endpoint must be static")
        if not re.fullmatch(r"html/content/[a-z_]+/[a-z_]+\.html", self.referer):
            raise ValueError("Settings referer must be static")
        if self.read_referer is not None and not re.fullmatch(
            r"html/content/[a-z_]+/[a-z_]+\.html", self.read_referer
        ):
            raise ValueError("Settings read referer must be static")
        if len({item.name for item in self.fields}) != len(self.fields):
            raise ValueError("Duplicate settings field")
        if self.payload_validator is not None and self.builder is None:
            raise ValueError("Indexed payload validation requires a closed builder")
        if self.verifier_owns_fields and self.verifier is None:
            raise ValueError("Collection verification requires a reviewed verifier")
        if any(item.dynamic_choices for item in self.fields) != (
            self.field_choices is not None
        ):
            raise ValueError("Dynamic choices require a reviewed inventory reader")
        if (
            self.acknowledgement not in {"status_ok", "result_ok", "readback"}
            or self.readback_policy
            not in {"exact", "reconnect_required", "manual_required"}
            or not self.confirmation.strip()
            or len(set(self.revision_fields)) != len(self.revision_fields)
            or any(not name.isidentifier() for name in self.revision_fields)
        ):
            raise ValueError("Invalid static settings policy")

    def read(self, raw: SettingValues) -> dict[str, Any]:
        """Read typed known fields; secrets never leave this local boundary."""
        source = self.reader(raw) if self.reader else raw
        values = {
            item.name: item.read(source)
            for item in self.fields
            if item.kind != "secret"
        }
        self._validate_choices(raw, values)
        return values

    def choices(self, raw: SettingValues) -> dict[str, list[dict[str, str]]]:
        """Expose only reviewed non-secret labels and identifiers from a fresh read."""
        if self.field_choices is None:
            return {}
        choices = self.field_choices(raw)
        expected = {item.name for item in self.fields if item.dynamic_choices}
        if set(choices) != expected:
            raise ConfigurationError("invalid_settings_choices")
        result: dict[str, list[dict[str, str]]] = {}
        for name, options in choices.items():
            if not isinstance(options, (tuple, list)) or len(options) > _MAX_CHOICES:
                raise ConfigurationError("invalid_settings_choices")
            seen: set[str] = set()
            result[name] = []
            for option in options:
                if (
                    not isinstance(option, (tuple, list))
                    or len(option) != _CHOICE_PARTS
                ):
                    raise ConfigurationError("invalid_settings_choices")
                key, label = option
                if (
                    type(key) is not str
                    or not _IDENTIFIER.fullmatch(key)
                    or key in seen
                    or type(label) is not str
                    or not 0 < len(label) <= _MAX_CHOICE_LABEL
                    or any(
                        ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER
                        for char in label
                    )
                ):
                    raise ConfigurationError("invalid_settings_choices")
                seen.add(key)
                result[name].append({"value": key, "label": label})
        return result

    def _validate_choices(self, raw: SettingValues, values: SettingValues) -> None:
        options = self.choices(raw)
        for item in self.fields:
            if item.name not in values or not item.dynamic_choices:
                continue
            accepted = {choice["value"] for choice in options[item.name]}
            value = values[item.name]
            selected = value if item.kind == "identifiers" else [value]
            if any(key not in accepted for key in selected):
                raise ConfigurationError("invalid_settings_choices")

    def revision(self, raw: SettingValues) -> dict[str, Any]:
        """Bind hidden dependencies and credentials without exposing their values."""
        names = set(self.revision_fields)
        names.update(
            item.read_key or item.name for item in self.fields if item.kind == "secret"
        )
        return {
            "fields": self.read(raw),
            "target_scope": self.target_scope,
            "dependencies": {name: raw.get(name) for name in sorted(names)},
            "choices": self.choices(raw),
            "context": self.revision_values(raw) if self.revision_values else {},
        }

    def build(
        self, raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        """Preserve the complete known form and reject extra client fields."""
        names = {item.name for item in self.fields}
        if not changes or not set(changes) <= names:
            raise ConfigurationError
        for item in self.fields:
            if item.name in changes:
                item.validate(changes[item.name])
        self._validate_choices(raw, changes)
        if self.builder:
            payload = self.builder(raw, changes)
        else:
            source = self.reader(raw) if self.reader else raw
            values = {
                item.name: (
                    item.validate(changes[item.name])
                    if item.name in changes
                    else item.read(source)
                )
                for item in self.fields
            }
            payload = {}
            for key, value in values.items():
                if isinstance(value, list):
                    raise ConfigurationError("invalid_contract_payload")
                payload[key] = ("1" if value else "0") if type(value) is bool else value
        if not payload:
            raise ConfigurationError("invalid_contract_payload")
        if any(type(value) not in {str, int, bool} for value in payload.values()):
            raise ConfigurationError("invalid_contract_payload")
        if self.payload_validator is not None:
            if self.payload_validator(raw, payload) is not True:
                raise ConfigurationError("invalid_contract_payload")
        elif not set(payload) <= (self.payload_keys or names):
            raise ConfigurationError("invalid_contract_payload")
        return payload

    def metadata(self) -> dict[str, Any]:
        """Expose the full editor, without exposing transport endpoints."""
        return {
            "id": self.id,
            "title": self.title,
            "section": self.section,
            "fields": [item.metadata() for item in self.fields],
            "warning": self.warning,
            "confirmation": self.confirmation,
            "live_write_verified": False,
        }


def boolean(name: str, label: str, **kwargs: Any) -> SettingsField:
    """Describe a firmware 0/1 boolean."""
    return SettingsField(name, label, "boolean", **kwargs)


def choice(
    name: str, label: str, choices: tuple[tuple[str, str], ...], **kwargs: Any
) -> SettingsField:
    """Describe an exact firmware enum."""
    return SettingsField(name, label, "enum", choices=choices, **kwargs)


_PHONE = "html/content/phone/"
_BASIC_CONTRACTS = (
    SettingsContract(
        "telephony_hd_voice",
        "HD Voice",
        "Telephony",
        "data/Phone.json",
        _PHONE + "phone_linehdvoice.html",
        (boolean("hdvoice", "HD Voice"),),
    ),
    SettingsContract(
        "telephony_dial_delay",
        "Dial delay",
        "Telephony",
        "data/Phone.json",
        _PHONE + "phone_linedialdelay.html",
        (
            choice(
                "dialdelay",
                "Dial delay",
                (
                    ("0", "3 seconds"),
                    ("1", "5 seconds"),
                    ("2", "7 seconds"),
                    ("3", "9 seconds"),
                ),
            ),
        ),
    ),
    SettingsContract(
        "telephony_status_audio",
        "Status announcements",
        "Telephony",
        "data/Phone.json",
        _PHONE + "phone_linestataudio.html",
        (boolean("stataudio", "Status announcements"),),
    ),
    SettingsContract(
        "nas_workgroup",
        "SMB workgroup",
        "Storage",
        "data/NASWorkgroup.json",
        "html/content/network/nas_workgroup.html",
        (SettingsField("smb_workgroup", "Workgroup", "text", minimum=1, maximum=15),),
    ),
)


def settings_contracts() -> Mapping[str, SettingsContract]:
    """Return reviewed forms; family modules extend this closed registry."""
    # Family modules depend on the contract types above; avoid an import cycle.
    from .configuration_call_history import CALL_HISTORY_SETTINGS  # noqa: PLC0415
    from .configuration_device_selection import (  # noqa: PLC0415
        DEVICE_SELECTION_SETTINGS,
    )
    from .configuration_internet import INTERNET_SETTINGS  # noqa: PLC0415
    from .configuration_ip_phone_create import ip_phone_create_contract  # noqa: PLC0415
    from .configuration_media import MEDIA_CREATE_SETTINGS  # noqa: PLC0415
    from .configuration_nas_create import NAS_CREATE_SETTINGS  # noqa: PLC0415
    from .configuration_network import NETWORK_SETTINGS  # noqa: PLC0415
    from .configuration_network_controls import (  # noqa: PLC0415
        NETWORK_CONTROL_SETTINGS,
    )
    from .configuration_network_rules import NETWORK_RULE_SETTINGS  # noqa: PLC0415
    from .configuration_parental import PARENTAL_SETTINGS  # noqa: PLC0415
    from .configuration_password import PASSWORD_SETTINGS  # noqa: PLC0415
    from .configuration_phonebook_accounts import (  # noqa: PLC0415
        PHONEBOOK_ACCOUNT_CREATE_SETTINGS,
    )
    from .configuration_port_blocking import PORT_BLOCKING_SETTINGS  # noqa: PLC0415
    from .configuration_provider_create import PROVIDER_CREATE_SETTINGS  # noqa: PLC0415
    from .configuration_small_controls import SMALL_CONTROL_SETTINGS  # noqa: PLC0415
    from .configuration_system import SYSTEM_SETTINGS  # noqa: PLC0415
    from .configuration_system_extra import SYSTEM_EXTRA_SETTINGS  # noqa: PLC0415
    from .configuration_telephony import TELEPHONY_SETTINGS  # noqa: PLC0415
    from .configuration_vpn import VPN_SETTINGS  # noqa: PLC0415
    from .configuration_wifi_extra import WIFI_EXTRA_SETTINGS  # noqa: PLC0415
    from .system_actions import SYSTEM_ACTION_SETTINGS  # noqa: PLC0415

    return MappingProxyType(
        {
            item.id: item
            for item in (
                *_BASIC_CONTRACTS,
                *CALL_HISTORY_SETTINGS,
                *DEVICE_SELECTION_SETTINGS,
                *INTERNET_SETTINGS,
                ip_phone_create_contract(),
                *MEDIA_CREATE_SETTINGS,
                *NETWORK_SETTINGS,
                *NETWORK_CONTROL_SETTINGS,
                *NETWORK_RULE_SETTINGS,
                *PARENTAL_SETTINGS,
                *PASSWORD_SETTINGS,
                *PHONEBOOK_ACCOUNT_CREATE_SETTINGS,
                *NAS_CREATE_SETTINGS,
                *PORT_BLOCKING_SETTINGS,
                *PROVIDER_CREATE_SETTINGS,
                *SMALL_CONTROL_SETTINGS,
                *SYSTEM_SETTINGS,
                *SYSTEM_EXTRA_SETTINGS,
                *SYSTEM_ACTION_SETTINGS,
                *TELEPHONY_SETTINGS,
                *WIFI_EXTRA_SETTINGS,
                *VPN_SETTINGS,
            )
        }
    )
