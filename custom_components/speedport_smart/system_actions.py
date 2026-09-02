"""
Firmware-proven system requests adapted to the private configuration session.

An ``execute`` field is a one-shot user approval, never a synthetic router state.
The shared owner authenticates the administrator, checks the exact supported
router firmware, binds the private revision, sends once and cleans up its session.
Online offer URLs/digests are read from fixed router endpoints; they are neither
accepted from the browser nor fetched by Home Assistant.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from .api.exceptions import (
    SpeedportCommandRejectedError,
    SpeedportMutationOutcomeUnknownError,
)
from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    normalize_configuration_payload,
)
from .configuration_mesh import mesh_flag, mesh_identity, mesh_rows

if TYPE_CHECKING:
    from .configuration import SettingValues

_ROUTER_FW: Final = "system_router_firmware_online"
_MESH_FW: Final = "system_mesh_firmware_online"
_MESH_RESTART: Final = "system_mesh_restart"
_MESH_RESET: Final = "system_mesh_reset"
_SH_ACTIVATE: Final = "network_smarthome_activate"
_SH_DEACTIVATE: Final = "network_smarthome_deactivate"
_RECEIVER_FW: Final = "internet_receiver_firmware_update"
_RECEIVER_RESET: Final = "internet_receiver_factory_esim_restore"
_CONFIG: Final = "html/content/config/"
_SH_REFERER: Final = "html/content/network/smarthome.html"
_RECEIVER_REFERER: Final = "html/content/internet/lte_firmware.html"
_OFFER_KEY: Final = "system_firmware_offer"
_MESH_WIFI6_TYPE: Final = 2
_SMARTHOME_READY: Final = 2
_EXECUTE: Final = boolean(
    "execute",
    "Send this one-shot request",
    description="This is approval to send a request, not a reported router state.",
)
_PHYSICAL: Final = boolean(
    "physical_access",
    "I have physical access and a recovery plan",
)
_BACKUP: Final = boolean(
    "backup_saved",
    "I have saved the configuration needed for recovery",
)
_ESIM: Final = boolean(
    "reset_esim",
    "Also delete the receiver's eSIM profiles",
)
_ESIM_RECOVERY: Final = boolean(
    "esim_recovery_ready",
    "If deleting eSIM profiles, I have confirmed how to activate replacements",
)
_CODE_FIELDS: Final = tuple(
    SettingsField(
        f"acode_{part}",
        f"Activation code block {part - 1}",
        "secret",
        minimum=4,
        maximum=4,
        description="Enter exactly four ASCII digits. This value is never read back.",
    )
    for part in (2, 3, 4)
)
_ONLINE_FIELDS: Final = (
    "onlinestatus",
    "extwan_typ",
    "lte_status",
    "use_tethering",
    "tethering_status",
)


def _ready(raw: SettingValues) -> dict[str, Any]:
    source = normalize_configuration_payload(raw)
    if source.get("router_state") != "OK":
        raise ConfigurationError("system_action_unavailable")
    return source


def _text(value: object, maximum: int = 256) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise ConfigurationError("system_action_unavailable")
    return value


def _number(value: object, maximum: int = 3600) -> int:
    if type(value) is str and re.fullmatch(r"[0-9]{1,10}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= maximum:
        raise ConfigurationError("system_action_unavailable")
    return value


def _online(raw: SettingValues) -> dict[str, Any]:
    source = _ready(raw)
    online = source.get("onlinestatus") == "online"
    mobile = source.get("extwan_typ") in (3, "3") and source.get("lte_status") in (
        "10",
        "11",
        10,
        11,
    )
    tethered = source.get("use_tethering") in (1, "1") and source.get(
        "tethering_status"
    ) in (2, "2")
    if not (online or mobile or tethered):
        raise ConfigurationError("system_action_offline")
    return {name: source.get(name) for name in _ONLINE_FIELDS}


def _offer_values(raw: SettingValues) -> dict[str, str]:
    url = _text(raw.get("newFwImageURL"), 2048)
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
        # Validate malformed port syntax without imposing an invented vendor port.
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError("system_firmware_offer_unavailable")
    return {"url": url, "digest": _text(raw.get("newFwDigest"))}


def _firmware_offer(raw: SettingValues) -> dict[str, Any]:
    offer = raw.get(_OFFER_KEY)
    if not isinstance(offer, Mapping):
        raise ConfigurationError("system_firmware_offer_unavailable")
    offer = normalize_configuration_payload(offer)
    if offer.get("status") != "ok":
        raise ConfigurationError("system_firmware_offer_unavailable")
    return offer


def _router_firmware_base(raw: SettingValues) -> dict[str, Any]:
    source = _ready(raw)
    context = _online(source)
    provider = str(_number(source.get("inet_isp"), 999))
    automatic = not mesh_flag(source, "autofw_deactive")
    # firmware.js disables the explicit update check for these managed providers.
    if provider in {"1", "89"} and automatic:
        raise ConfigurationError("system_firmware_managed_automatically")
    return {
        **context,
        "inet_isp": provider,
        "autofw_deactive": not automatic,
        "firmware_version": _text(source.get("firmware_version"), 128),
    }


def _mesh_firmware_base(raw: SettingValues) -> dict[str, Any]:
    context = _online(raw)
    rows = mesh_rows(raw)
    connected = [row for row in rows if mesh_flag(row, "mesh_connected")]
    if not connected:
        raise ConfigurationError("system_mesh_unavailable")
    for row in connected:
        _number(row.get("mesh_device_type"), 255)
        mesh_flag(row, "mesh_upd_local")
    if not any(not mesh_flag(row, "mesh_upd_local") for row in connected):
        raise ConfigurationError("system_mesh_local_update_only")
    return {
        **context,
        "mesh": mesh_identity(raw),
        "mesh_update_modes": {
            row["id"]: {
                "type": _number(row.get("mesh_device_type"), 255),
                "local": mesh_flag(row, "mesh_upd_local"),
            }
            for row in connected
        },
    }


def system_action_extra_read(
    setting_id: str,
    raw: SettingValues,
) -> tuple[str, str] | None:
    """
    Select only the static explicit-check GET, with counts from fresh inventory.

    The client reads the contract's base page first and calls this function only
    for these two IDs. It appends its normal fresh page token, not a browser URL.
    """
    if setting_id == _ROUTER_FW:
        _router_firmware_base(raw)
        return "data/FwCheckForUpdate.json", _CONFIG + "check_for_updates.html"
    if setting_id == _MESH_FW:
        _mesh_firmware_base(raw)
        connected = [row for row in mesh_rows(raw) if mesh_flag(row, "mesh_connected")]
        shwl = sum(
            _number(row.get("mesh_device_type"), 255) == _MESH_WIFI6_TYPE
            for row in connected
        )
        return (
            (
                "data/FwCheckForUpdateMesh.json"
                f"?shw_num={len(connected) - shwl}&shwl_num={shwl}"
            ),
            _CONFIG + "check_for_updates_mesh.html",
        )
    return None


def merge_system_action_offer(
    setting_id: str,
    raw: SettingValues,
    offer: SettingValues,
) -> dict[str, Any]:
    """Keep the offer in a separate private namespace and validate it immediately."""
    if system_action_extra_read(setting_id, raw) is None or _OFFER_KEY in raw:
        raise ConfigurationError("system_firmware_offer_unavailable")
    combined = {**normalize_configuration_payload(raw), _OFFER_KEY: dict(offer)}
    _context(setting_id, combined)
    return combined


def _online_firmware_context(setting_id: str, raw: SettingValues) -> dict[str, Any]:
    offer = _firmware_offer(raw)
    if setting_id == _ROUTER_FW:
        base = _router_firmware_base(raw)
        if not mesh_flag(offer, "fwupd_avail"):
            raise ConfigurationError("system_firmware_offer_unavailable")
        version = _text(offer.get("fwupd_version"), 128)
        if version == base["firmware_version"]:
            raise ConfigurationError("system_firmware_offer_unavailable")
        return {**base, "offer": {**_offer_values(offer), "version": version}}
    base = _mesh_firmware_base(raw)
    # The check response must describe the same complete inventory. A partial
    # offer or a node replacement requires a new review, never a guessed target.
    if "router_state" in offer and offer["router_state"] != "OK":
        raise ConfigurationError("system_firmware_offer_unavailable")
    checked = {"router_state": "OK", **offer}
    if mesh_identity(raw) != mesh_identity(checked):
        raise ConfigurationError("stale_settings")
    checked_modes = {
        row["id"]: {
            "type": _number(row.get("mesh_device_type"), 255),
            "local": mesh_flag(row, "mesh_upd_local"),
        }
        for row in mesh_rows(checked)
        if mesh_flag(row, "mesh_connected")
    }
    if checked_modes != base["mesh_update_modes"]:
        raise ConfigurationError("stale_settings")
    managed = [
        row
        for row in mesh_rows(checked)
        if mesh_flag(row, "mesh_connected") and not mesh_flag(row, "mesh_upd_local")
    ]
    if not any(mesh_flag(row, "mesh_upd_avail") for row in managed):
        raise ConfigurationError("system_firmware_offer_unavailable")
    # firmware_mesh.js uses the first connected non-local offer, not an arbitrary
    # URL from whichever row happened to advertise an available update.
    selected = _offer_values(managed[0])
    offers = {}
    for row in managed:
        available = mesh_flag(row, "mesh_upd_avail")
        current = _text(row.get("mesh_firmware"), 128)
        mesh_version = _text(row.get("mesh_upd_firmware"), 128) if available else None
        if available and mesh_version == current:
            raise ConfigurationError("system_firmware_offer_unavailable")
        offers[row["id"]] = {
            "available": available,
            "current": current,
            "version": mesh_version,
            **(_offer_values(row) if available else {}),
        }
    return {**base, "offer": selected, "node_offers": offers}


def _receiver_context(raw: SettingValues) -> dict[str, Any]:
    source = _ready(raw)
    if not mesh_flag(source, "auto_external_modem") or source.get("extwan_typ") not in (
        3,
        "3",
    ):
        raise ConfigurationError("system_receiver_unavailable")
    return {
        "model": _text(source.get("ex5g_model_name"), 128),
        "serial": _text(source.get("ex5g_serial_number"), 128),
        "firmware": _text(source.get("ex5g_fw_version"), 128),
        "eid": _text(source.get("ex5g_eid"), 128),
    }


def _smarthome_context(setting_id: str, raw: SettingValues) -> dict[str, Any]:
    source = _ready(raw)
    active = mesh_flag(source, "use_smarthome")
    state = _number(source.get("smarthome_state_check"), 2)
    if state == 1 or active != (setting_id == _SH_DEACTIVATE):
        raise ConfigurationError("system_smarthome_unavailable")
    context = {"active": active, "state": state}
    if setting_id == _SH_ACTIVATE:
        context.update(_online(source))
        # jsonvariables.js getVar returns false when absent; smarthome.js tests
        # that return value with `if (seconds)`. Absence therefore means no
        # advertised lock, not a missing required Smart Home state variable.
        if _number(source.get("acode_locked", 0)) != 0:
            raise ConfigurationError("system_smarthome_code_locked")
    return context


def _context(setting_id: str, raw: SettingValues) -> dict[str, Any]:
    """Fresh private prerequisites also supply the session's revision material."""
    source = _ready(raw)
    if setting_id in {_ROUTER_FW, _MESH_FW}:
        return _online_firmware_context(setting_id, source)
    if setting_id in {_MESH_RESTART, _MESH_RESET}:
        identities = mesh_identity(source)
        if not identities:
            raise ConfigurationError("system_mesh_unavailable")
        return {"mesh": identities}
    if setting_id in {_SH_ACTIVATE, _SH_DEACTIVATE}:
        return _smarthome_context(setting_id, source)
    if setting_id in {_RECEIVER_FW, _RECEIVER_RESET}:
        context = _receiver_context(source)
        if setting_id == _RECEIVER_FW:
            if not mesh_flag(source, "ex5g_fwupd_avail"):
                raise ConfigurationError("system_firmware_offer_unavailable")
            version = _text(source.get("ex5g_fwupd_version"), 128)
            if version == context["firmware"]:
                raise ConfigurationError("system_firmware_offer_unavailable")
            context["offered_version"] = version
        return context
    raise ConfigurationError("setting_unavailable")


def _build(
    setting_id: str,
    raw: SettingValues,
    changes: SettingValues,
) -> dict[str, str | int | bool]:
    context = _context(setting_id, raw)
    if changes.get("execute") is not True:
        raise ConfigurationError("confirmation_required")
    if (
        setting_id in {_ROUTER_FW, _MESH_FW, _RECEIVER_FW, _MESH_RESET, _RECEIVER_RESET}
        and changes.get("physical_access") is not True
    ):
        raise ConfigurationError("confirmation_required")
    if setting_id in {_ROUTER_FW, _MESH_FW}:
        prefix = "fw" if setting_id == _ROUTER_FW else "Mesh"
        return {
            prefix + "AutoUpdateImageUrl": context["offer"]["url"],
            prefix + "AutoUpdateImageDigest": context["offer"]["digest"],
        }
    if setting_id == _MESH_RESET:
        if changes.get("backup_saved") is not True:
            raise ConfigurationError("confirmation_required")
        return {"reset_device": "true"}
    if setting_id == _MESH_RESTART:
        return {"reboot_device": "true"}
    if setting_id == _SH_ACTIVATE:
        values: dict[str, str | int | bool] = {}
        for item in _CODE_FIELDS:
            value = changes.get(item.name)
            if type(value) is not str or re.fullmatch(r"[0-9]{4}", value) is None:
                raise ConfigurationError("invalid_smarthome_code")
            values[item.name] = value
        return values
    if setting_id == _SH_DEACTIVATE:
        return {"deact_shome": "true"}
    if setting_id == _RECEIVER_FW:
        return {"auto_update": "true"}
    if setting_id == _RECEIVER_RESET:
        reset = changes.get("reset_esim", False)
        if type(reset) is not bool:
            raise ConfigurationError
        if reset and (
            context["eid"] == "not supported"
            or changes.get("esim_recovery_ready") is not True
        ):
            raise ConfigurationError("system_esim_recovery_required")
        return {"restore": "1" if reset else "0"}
    raise ConfigurationError("setting_unavailable")


def validate_smarthome_response(response: Mapping[str, Any]) -> None:
    """Classify the firmware's explicit code errors without exposing code values."""
    keys = [key for key in response if str(key).casefold() == "smarthome_reg"]
    if keys and keys != ["smarthome_reg"]:
        raise SpeedportMutationOutcomeUnknownError("Smart Home response is ambiguous")
    value = response.get("smarthome_reg")
    if value is not None and type(value) is not str:
        raise SpeedportMutationOutcomeUnknownError("Smart Home response is ambiguous")
    if value in {"codewrong", "codeused"}:
        raise SpeedportCommandRejectedError("The router rejected the activation code")


def _verify_smarthome(setting_id: str, after: SettingValues) -> bool:
    source = _ready(after)
    active = mesh_flag(source, "use_smarthome")
    state = _number(source.get("smarthome_state_check"), 2)
    return (
        (active and state == _SMARTHOME_READY)
        if setting_id == _SH_ACTIVATE
        else (not active and state != 1)
    )


def _contract(  # noqa: PLR0917 -- Mirrors the closed static SettingsContract declaration.
    setting_id: str,
    title: str,
    endpoint: str,
    referer: str,
    fields: tuple[SettingsField, ...],
    payload_keys: tuple[str, ...],
    confirmation: str,
    warning: str,
    *,
    read_endpoint: str | None = None,
    read_referer: str | None = None,
) -> SettingsContract:
    smarthome = setting_id in {_SH_ACTIVATE, _SH_DEACTIVATE}

    def read(raw: SettingValues) -> dict[str, Any]:
        _context(setting_id, raw)
        return {item.name: False for item in fields if item.kind != "secret"}

    return SettingsContract(
        setting_id,
        title,
        "Home network" if smarthome else "System",
        endpoint,
        referer,
        fields,
        read_endpoint=read_endpoint,
        read_referer=read_referer,
        reader=read,
        builder=lambda raw, changes: _build(setting_id, raw, changes),
        revision_values=lambda raw: _context(setting_id, raw),
        payload_keys=frozenset(payload_keys),
        acknowledgement="result_ok"
        if setting_id in {_ROUTER_FW, _MESH_FW}
        else "readback"
        if setting_id in {_MESH_RESTART, _MESH_RESET}
        else "status_ok",
        readback_policy="exact" if smarthome else "reconnect_required",
        response_validator=validate_smarthome_response
        if setting_id == _SH_ACTIVATE
        else None,
        verifier=(lambda _before, _changes, after: _verify_smarthome(setting_id, after))
        if smarthome
        else None,
        verifier_owns_fields=smarthome,
        warning=warning,
        confirmation=confirmation,
    )


SYSTEM_ACTION_SETTINGS: Final = (
    _contract(
        _ROUTER_FW,
        "Install offered router firmware",
        "data/FwCheckForUpdate.json",
        _CONFIG + "check_for_updates.html",
        (_EXECUTE, _PHYSICAL),
        ("fwAutoUpdateImageUrl", "fwAutoUpdateImageDigest"),
        "INSTALL ROUTER UPDATE",
        "This starts the freshly offered router firmware update and may interrupt "
        "all connectivity. Keep power connected and allow the router to finish. "
        "An acknowledgement is not proof of installation. Reconnect and check "
        "the firmware version before retrying. No URL or digest comes from "
        "the browser.",
        read_endpoint="data/FirmwareUpdate.json",
    ),
    _contract(
        _MESH_FW,
        "Install offered mesh firmware",
        "data/FwCheckForUpdateMesh.json",
        _CONFIG + "check_for_updates_mesh.html",
        (_EXECUTE, _PHYSICAL),
        ("MeshAutoUpdateImageUrl", "MeshAutoUpdateImageDigest"),
        "INSTALL MESH UPDATE",
        "This starts the router-managed mesh firmware update, which may affect "
        "multiple connected nodes and interrupt their clients. Local-only node "
        "updates are not proxied. Keep power connected. An acknowledgement does "
        "not prove any node installed the update; inspect versions after recovery.",
        read_endpoint="data/FirmwareUpdateMesh.json",
    ),
    _contract(
        _MESH_RESTART,
        "Restart mesh devices",
        "data/RebootMesh.json",
        _CONFIG + "problem_handling_mesh.html",
        (_EXECUTE,),
        ("reboot_device",),
        "RESTART ALL MESH DEVICES",
        "This is a mesh-wide restart, not an individual-node command. Connected "
        "clients may lose connectivity. No exact positive response or independent "
        "completion proof is exposed; inspect mesh status after recovery "
        "before retrying.",
        read_endpoint="data/DeviceList.json",
        read_referer="html/content/network/devices.html",
    ),
    _contract(
        _MESH_RESET,
        "Factory reset mesh devices",
        "data/RebootMesh.json",
        _CONFIG + "problem_handling_mesh.html",
        (_EXECUTE, _PHYSICAL, _BACKUP),
        ("reset_device",),
        "FACTORY RESET ALL MESH DEVICES",
        "This is a mesh-wide factory reset, not deletion of one node. Mesh "
        "configuration can be lost and devices may require physical setup again. "
        "Clients may lose connectivity. No exact positive response or complete "
        "reset readback is available; inspect and recover devices before retrying.",
        read_endpoint="data/DeviceList.json",
        read_referer="html/content/network/devices.html",
    ),
    _contract(
        _SH_ACTIVATE,
        "Activate Smart Home",
        "data/SmartHome.json",
        _SH_REFERER,
        (_EXECUTE, *_CODE_FIELDS),
        tuple(item.name for item in _CODE_FIELDS),
        "ACTIVATE SMART HOME",
        "This submits the three private four-digit activation-code blocks once. "
        "Incorrect codes can lock further attempts. Activation may take longer "
        "than the bounded readback window; inspect Smart Home status before "
        "retrying. Credentials are never returned or retained in diagnostics.",
    ),
    _contract(
        _SH_DEACTIVATE,
        "Deactivate Smart Home",
        "data/SmartHome.json",
        _SH_REFERER,
        (_EXECUTE,),
        ("deact_shome",),
        "DEACTIVATE SMART HOME",
        "This deactivates the router's Smart Home service and can interrupt "
        "connected Smart Home devices. The service's inactive state is checked "
        "independently; this does not verify the state of each attached device.",
    ),
    _contract(
        _RECEIVER_FW,
        "Install offered receiver firmware",
        "data/LTE.json",
        _RECEIVER_REFERER,
        (_EXECUTE, _PHYSICAL),
        ("auto_update",),
        "INSTALL RECEIVER UPDATE",
        "This starts the offered external 5G receiver firmware update. Mobile "
        "connectivity can be interrupted. Keep power connected. An acknowledgement "
        "does not prove installation; inspect the receiver version after recovery.",
    ),
    _contract(
        _RECEIVER_RESET,
        "Factory reset external receiver",
        "data/LTE.json",
        _RECEIVER_REFERER,
        (_EXECUTE, _PHYSICAL, _ESIM, _ESIM_RECOVERY),
        ("restore",),
        "FACTORY RESET RECEIVER",
        "This resets the external 5G receiver and can interrupt mobile service. "
        "Selecting eSIM deletion also permanently removes its profiles and may "
        "require new provider activation. Confirm recovery arrangements first. "
        "An acknowledgement is not proof of reset or profile deletion; verify "
        "the receiver after recovery. eSIM deletion is off by default.",
    ),
)
