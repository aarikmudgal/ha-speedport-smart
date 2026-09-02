"""Exact separate module flags and an explicitly unverified learned-number clear."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .configuration_device_selection import DEVICE_SELECTION_SETTINGS
from .configuration_network_rules import network_rule_target_rows

if TYPE_CHECKING:
    from .configuration import SettingReader, SettingValues

_QOS: Final = next(
    item for item in DEVICE_SELECTION_SETTINGS if item.id == "qos_devices"
)


def _qos_context(raw: SettingValues) -> dict[str, Any]:
    """Reuse the complete checked-state/physical-identity parser, not raw telemetry."""
    _QOS.read(raw)
    return {
        "selection": _QOS.read(raw),
        "identity": _QOS.revision_values(raw) if _QOS.revision_values else {},
    }


def _dns_context(raw: SettingValues) -> dict[str, Any]:
    """Reuse exact domain/ID and known-empty rules from the exception editor."""
    return {"exceptions": network_rule_target_rows("dns_exception_edit", raw)}


def _module(
    identifier: str,
    title: str,
    name: str,
    *,
    endpoint: str,
    referer: str,
    context: SettingReader,
    warning: str,
    confirmation: str,
) -> SettingsContract:
    flag = boolean(name, title)

    def read(raw: SettingValues) -> dict[str, Any]:
        context(raw)
        return {name: flag.read(raw)}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        read(raw)
        if set(changes) != {name}:
            raise ConfigurationError("invalid_module_change")
        return {name: "1" if flag.validate(changes[name]) else "0"}

    def validate_payload(raw: SettingValues, payload: SettingValues) -> bool:
        # A reviewed validator also enables compound-preserving private GETs.
        read(raw)
        return (
            set(payload) == {name}
            and type(payload[name]) is str
            and payload[name] in {"0", "1"}
        )

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            return flag.read(after) == changes[name] and context(before) == context(
                after
            )
        except ConfigurationError:
            return False

    return SettingsContract(
        identifier,
        title,
        "Network",
        "data/Modules.json",
        referer,
        (flag,),
        read_endpoint=endpoint,
        reader=read,
        builder=build,
        payload_validator=validate_payload,
        revision_values=context,
        verifier=verify,
        acknowledgement="readback",
        payload_keys=frozenset({name}),
        warning=warning,
        confirmation=confirmation,
    )


def _speed_read(raw: SettingValues) -> dict[str, Any]:
    boolean("use_speeddial", "Automatic number memory").read(raw)
    # This checkbox is an action confirmation. No list/count/epoch proves that
    # learned numbers are absent, so a current flag cannot represent cleared.
    return {"clear_number_memory": False}


def _speed_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _speed_read(raw)
    if changes != {"clear_number_memory": True}:
        raise ConfigurationError("number_memory_clear_confirmation_required")
    return {"speeddial_delete": "true"}


_LOG_CATEGORIES: Final = (
    ("inet", "Internet"),
    ("tel", "Telephony"),
    ("wifi", "Wi-Fi"),
    ("sys", "System"),
    ("shom", "Smart Home"),
    ("esup", "EasySupport"),
    ("sec", "Security"),
)
_LOG_FIELD: Final = SettingsField(
    "filter_categories",
    "System message categories",
    "identifiers",
    choices=_LOG_CATEGORIES,
    maximum=len(_LOG_CATEGORIES),
    description=(
        "Select categories to filter. Clear every selection to show all messages."
    ),
)
_LOG_MASK_DIGITS: Final = 3


def _log_read(raw: SettingValues) -> dict[str, Any]:
    value = raw.get("filter_log")
    if (
        type(value) is str
        and value.isascii()
        and value.isdecimal()
        and len(value) <= _LOG_MASK_DIGITS
    ):
        value = int(value)
    if type(value) is not int or not 0 <= value < 1 << len(_LOG_CATEGORIES):
        raise ConfigurationError("invalid_log_filter")
    return {
        "filter_categories": [
            key
            for index, (key, _) in enumerate(_LOG_CATEGORIES)
            if value & (1 << index)
        ]
    }


def _log_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _log_read(raw)
    if set(changes) != {"filter_categories"}:
        raise ConfigurationError("invalid_log_filter_change")
    selected = _LOG_FIELD.validate(changes["filter_categories"])
    if not isinstance(selected, list) or not set(selected) <= {
        key for key, _ in _LOG_CATEGORIES
    }:
        raise ConfigurationError("invalid_log_filter_category")
    if not selected:
        return {"search": "false"}
    return {
        "search": "true",
        **{
            f"search{index}": key
            for index, (key, _) in enumerate(_LOG_CATEGORIES, 1)
            if key in selected
        },
    }


def _log_payload(raw: SettingValues, payload: SettingValues) -> bool:
    _log_read(raw)
    if payload == {"search": "false"}:
        return True
    if payload.get("search") != "true":
        return False
    selected = [
        key
        for index, (key, _) in enumerate(_LOG_CATEGORIES, 1)
        if payload.get(f"search{index}") == key
    ]
    return bool(selected) and payload == _log_build(
        raw, {"filter_categories": selected}
    )


SMALL_CONTROL_SETTINGS: Final = (
    _module(
        "qos_voice_priority",
        "Prioritize telephone traffic",
        "use_priovoip",
        endpoint="data/QOS.json",
        referer="html/content/network/qos.html",
        context=_qos_context,
        warning=(
            "Changes voice traffic priority, preserving selected priority devices. "
            "Readback verifies configuration, not telephone-call quality."
        ),
        confirmation="CHANGE VOICE PRIORITY",
    ),
    _module(
        "dns_rebind_protection",
        "DNS rebind protection",
        "use_dnsrebind",
        endpoint="data/DNSExcept.json",
        referer="html/content/network/dns_rebind.html",
        context=_dns_context,
        warning="Disabling DNS rebind protection removes a security safeguard. "
        "Existing exception domains are preserved; prefer a specific exception "
        "when only one service needs access.",
        confirmation="CHANGE DNS REBIND PROTECTION",
    ),
    SettingsContract(
        "telephony_number_memory_clear",
        "Clear learned telephone numbers",
        "Telephony",
        "data/PhoneLineset.json",
        "html/content/phone/phone_linespeeddial.html",
        (boolean("clear_number_memory", "Permanently clear learned numbers"),),
        reader=_speed_read,
        builder=_speed_build,
        revision_fields=("use_speeddial",),
        payload_keys=frozenset({"speeddial_delete"}),
        acknowledgement="readback",
        readback_policy="manual_required",
        confirmation="CLEAR LEARNED TELEPHONE NUMBERS",
        warning=(
            "Permanently clears automatically learned telephone numbers, not the "
            "phonebook. The firmware exposes no learned-list, count or generation "
            "readback. This one-shot action always reports an unknown outcome; "
            "inspect the router before trying again. No automatic retry occurs."
        ),
    ),
    SettingsContract(
        "system_log_filter",
        "Filter system messages",
        "System",
        "data/SystemMessages.json",
        "html/content/config/system_log.html",
        (_LOG_FIELD,),
        reader=_log_read,
        builder=_log_build,
        payload_validator=_log_payload,
        acknowledgement="readback",
        confirmation="CHANGE SYSTEM MESSAGE FILTER",
        warning=(
            "Changes the router's system-message view, not logging or stored messages. "
            "Empty selection disables the filter. Only the category bitmask is read "
            "back; this editor does not return private message contents."
        ),
    ),
)
