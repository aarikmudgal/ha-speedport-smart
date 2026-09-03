"""Exact tethering, receiver and DDNS actions from captured native bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
)
from .const import RECEIVER_LED_MODE_CODES

if TYPE_CHECKING:
    from .configuration import SettingValues

_TETHER: Final = boolean("use_tethering", "Enable USB tethering")
_ACTIVATE: Final = boolean(
    "activate_tethering", "Switch Internet access to USB tethering"
)
_BOND: Final = boolean("use_bonding", "Use 5G / LTE boost (bonding)")
_LED: Final = choice(
    "ex5g_led_mode",
    "5G receiver LEDs",
    (("0", "Use LEDs"), ("1", "Switch off after timeout"), ("2", "Do not use LEDs")),
)
_DELETE: Final = boolean("delete_provider", "Delete the stored Dynamic DNS provider")
_IDENTITY: Final = SettingsField("identity", "Receiver identity", "text", minimum=1)
_DDNS_TEXT: Final = SettingsField("context", "Stored DDNS field", "text", maximum=2048)
_DDNS_FIELDS: Final = (
    "dyndns_provider",
    "dyndns_domain",
    "dyndns_user",
    "dyndns_password",
    "dyndns_updsrv",
    "dyndns_updurl",
    "dyndns_updprot",
    "dyndns_updport",
)
_DDNS_CREDENTIALS: Final = (
    "dyndns_domain",
    "dyndns_user",
    "dyndns_password",
    "dyndns_updsrv",
)


def _context(raw: SettingValues) -> dict[str, Any]:
    additional = raw.get("network_prerequisites", {})
    if not isinstance(additional, Mapping):
        raise ConfigurationError("missing_network_prerequisites")
    return {**additional, **raw}


def _flag(raw: SettingValues, name: str) -> bool:
    value = boolean(name, name).read(raw)
    if type(value) is not bool:
        raise ConfigurationError("missing_network_prerequisites")
    return value


def _tether_context(raw: SettingValues) -> dict[str, Any]:
    context = _context(raw)
    if not _flag(context, "use_usb"):
        raise ConfigurationError("usb_disabled")
    external = _flag(context, "auto_external_modem")
    lte = _flag(context, "use_lte")
    if (external and context.get("extwan_typ") == "3") or (
        lte and _flag(context, "hybrid_tunnel")
    ):
        raise ConfigurationError("tethering_unavailable_with_receiver")
    if external and context.get("extwan_typ") not in ("0", "1", "2", "3"):
        raise ConfigurationError("missing_network_prerequisites")
    return context


def _tether_revision(raw: SettingValues) -> dict[str, Any]:
    context = _tether_context(raw)
    return {
        name: context.get(name)
        for name in ("use_usb", "use_lte", "auto_external_modem", "extwan_typ")
    }


def _tether_read(raw: SettingValues) -> dict[str, Any]:
    _tether_context(raw)
    return {"use_tethering": _TETHER.read(raw)}


def _tether_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _tether_read(raw)
    if set(changes) != {"use_tethering"}:
        raise ConfigurationError("invalid_tethering_change")
    return {"use_tethering": "1" if _TETHER.validate(changes["use_tethering"]) else "0"}


def _activation_read(raw: SettingValues) -> dict[str, Any]:
    if not _tether_read(raw)["use_tethering"]:
        raise ConfigurationError("tethering_disabled")
    if raw.get("tethering_status") not in ("0", "1", "2"):
        raise ConfigurationError("invalid_tethering_status")
    # This is an explicit action confirmation, not a route-status switch. Native
    # rendering prioritizes DSL/external connectivity even when this status is 2.
    return {"activate_tethering": False}


def _activation_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _activation_read(raw)
    if changes != {"activate_tethering": True}:
        raise ConfigurationError("tethering_activation_confirmation_required")
    if raw["tethering_status"] == "0":
        raise ConfigurationError("tethering_device_missing")
    return {"activate_teth": "true"}


def _receiver(raw: SettingValues) -> dict[str, Any]:
    return {
        name: _IDENTITY.validate(raw.get(name))
        for name in ("ex5g_serial_number", "ex5g_model_name")
    }


def receiver_identity_requires_read(raw: SettingValues) -> bool:
    """Detect absent identity prerequisites without weakening field validation."""
    return any(
        raw.get(name) in (None, "")
        for name in ("ex5g_serial_number", "ex5g_model_name")
    )


def merge_receiver_identity(
    raw: SettingValues, firmware: SettingValues
) -> dict[str, Any]:
    """Join only validated identity from the native receiver-information page."""
    identity = _receiver(firmware)
    if any(
        raw.get(name) not in (None, "") and raw[name] != value
        for name, value in identity.items()
    ):
        raise ConfigurationError("receiver_identity_changed")
    return {**raw, **identity}


def _bond_read(raw: SettingValues) -> dict[str, Any]:
    _receiver(raw)
    if not _flag(_context(raw), "easy_support_deactive"):
        raise ConfigurationError("bonding_managed_by_easy_support")
    return {"use_bonding": _BOND.read(raw)}


def _bond_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _bond_read(raw)
    if set(changes) != {"use_bonding"}:
        raise ConfigurationError("invalid_bonding_change")
    return {"use_bonding": "1" if _BOND.validate(changes["use_bonding"]) else "0"}


def _bond_revision(raw: SettingValues) -> dict[str, Any]:
    return {
        **_receiver(raw),
        "easy_support_deactive": _context(raw).get("easy_support_deactive"),
    }


def _led_read(raw: SettingValues) -> dict[str, Any]:
    _receiver(raw)
    value = raw.get("ex5g_led_mode")
    # The native page submits decimal codes but LTE.json also returns the exact
    # On/Timer/Off spellings already supported by the native entity contract.
    if type(value) is str and value in RECEIVER_LED_MODE_CODES:
        value = str(RECEIVER_LED_MODE_CODES[value])
    return {"ex5g_led_mode": _LED.read({"ex5g_led_mode": value})}


def _led_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _led_read(raw)
    if set(changes) != {"ex5g_led_mode"}:
        raise ConfigurationError("invalid_receiver_led_change")
    mode = _LED.validate(changes["ex5g_led_mode"])
    if type(mode) is not str:
        raise ConfigurationError("invalid_receiver_led_change")
    return {"ex5g_led_mode": mode}


def _led_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _led_build(before, changes)
        return (
            _receiver(before) == _receiver(after)
            and _led_read(after)["ex5g_led_mode"] == changes["ex5g_led_mode"]
        )
    except ConfigurationError:
        return False


def _ddns_state(raw: SettingValues) -> dict[str, Any]:
    result: dict[str, Any] = {"use_dyndns": _flag(raw, "use_dyndns")}
    for name in _DDNS_FIELDS:
        value = raw.get(name)
        if name in _DDNS_CREDENTIALS or value is not None:
            value = _DDNS_TEXT.validate(value)
        result[name] = value
    return result


def _ddns_deleted(raw: SettingValues) -> bool:
    state = _ddns_state(raw)
    return (
        not state["use_dyndns"]
        and all(state[name] == "" for name in _DDNS_CREDENTIALS)
        and state["dyndns_updurl"] in (None, "")
    )


def _ddns_read(raw: SettingValues) -> dict[str, Any]:
    return {"delete_provider": _ddns_deleted(raw)}


def _ddns_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _ddns_state(raw)
    if changes != {"delete_provider": True}:
        raise ConfigurationError("deletion_required")
    return {"delprov": "true"}


def _ddns_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _ddns_build(before, changes)
        return _ddns_deleted(after)
    except ConfigurationError:
        return False


NETWORK_CONTROL_SETTINGS: Final = (
    SettingsContract(
        "usb_tethering_enabled",
        "USB tethering",
        "Internet",
        "data/Modules.json",
        "html/content/internet/usb_tethering.html",
        (_TETHER,),
        read_endpoint="data/INetTeth.json",
        reader=_tether_read,
        builder=_tether_build,
        payload_keys=frozenset({"use_tethering"}),
        revision_values=_tether_revision,
        acknowledgement="readback",
        readback_policy="reconnect_required",
        warning=(
            "Changing tethering can interrupt Internet access; verify connectivity "
            "afterward."
        ),
        confirmation="CHANGE USB TETHERING",
    ),
    SettingsContract(
        "usb_tethering_activate",
        "Switch to USB tethering",
        "Internet",
        "data/INetTeth.json",
        "html/content/internet/usb_tethering.html",
        (_ACTIVATE,),
        reader=_activation_read,
        builder=_activation_build,
        payload_keys=frozenset({"activate_teth"}),
        revision_values=_tether_revision,
        acknowledgement="readback",
        readback_policy="reconnect_required",
        warning=(
            "This can switch the active Internet path. Verify connectivity; do not "
            "retry automatically."
        ),
        confirmation="SWITCH TO USB TETHERING",
    ),
    SettingsContract(
        "receiver_bonding",
        "5G / LTE bonding",
        "Internet",
        "data/LTE.json",
        "html/content/internet/lte_mode.html",
        (_BOND,),
        reader=_bond_read,
        builder=_bond_build,
        payload_keys=frozenset({"use_bonding"}),
        revision_values=_bond_revision,
        acknowledgement="readback",
        readback_policy="reconnect_required",
        warning=(
            "Changing bonding can interrupt Internet access. Available only when "
            "EasySupport does not manage it."
        ),
        confirmation="CHANGE RECEIVER BONDING",
    ),
    SettingsContract(
        "receiver_led_mode",
        "5G receiver LEDs",
        "Internet",
        "data/LTE.json",
        "html/content/internet/lte_mode.html",
        (_LED,),
        reader=_led_read,
        builder=_led_build,
        payload_keys=frozenset({"ex5g_led_mode"}),
        revision_values=_receiver,
        acknowledgement="readback",
        verifier=_led_verify,
        warning=(
            "Changes the external 5G receiver LEDs, not the router's front display."
        ),
        confirmation="CHANGE RECEIVER LED MODE",
    ),
    SettingsContract(
        "dynamic_dns_delete",
        "Delete Dynamic DNS provider",
        "Internet",
        "data/DynDNS.json",
        "html/content/internet/dyn_dns.html",
        (_DELETE,),
        reader=_ddns_read,
        builder=_ddns_build,
        payload_keys=frozenset({"delprov"}),
        revision_values=_ddns_state,
        acknowledgement="readback",
        verifier=_ddns_verify,
        warning=(
            "Removes the stored DDNS domain, login and custom update location and "
            "disables DDNS."
        ),
        confirmation="DELETE DYNAMIC DNS PROVIDER",
    ),
)
