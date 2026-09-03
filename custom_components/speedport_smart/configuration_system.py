"""
Fixed system-setting forms proven by the reviewed firmware UI.

The two Energy forms are independent. Protect and the module switches do not
POST to their page's JSONSource. Maintenance actions, credential changes and
file transfers deliberately use separate execution paths.
"""

from __future__ import annotations

import re
from typing import Any

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    SettingValues,
    boolean,
    choice,
)

_CONFIG = "html/content/config/"

_LED_FIELDS = (
    choice(
        "led_mode",
        "Front LED mode",
        (("0", "Use all LEDs"), ("1", "Switch LEDs off by time")),
    ),
    SettingsField(
        "led_from",
        "Switch off from",
        "text",
        minimum=5,
        maximum=5,
        description="HH:MM, including 24:00 for the end of the day.",
    ),
    SettingsField(
        "led_to",
        "Switch off until",
        "text",
        minimum=5,
        maximum=5,
        description="HH:MM, including 24:00; must differ from the start time.",
    ),
)
_ENERGY_FIELDS = (
    boolean("use_wlan", "Wi-Fi enabled"),
    choice(
        "wlan_band",
        "Wi-Fi bands",
        (("0", "2.4 GHz and 5 GHz"), ("1", "2.4 GHz only"), ("2", "5 GHz only")),
    ),
    choice(
        "wlan_power",
        "Wi-Fi transmit power",
        (("0", "Full"), ("1", "Medium"), ("2", "Low")),
    ),
    boolean("use_usb", "USB port enabled"),
)
_HTTPS_FIELDS = (boolean("use_https", "HTTPS access enabled"),)
_EXTERNAL_MODEM_FIELDS = (
    boolean("auto_external_modem", "Use Link/LAN1 for an external modem"),
)
_CLOUD_BACKUP_FIELDS = (boolean("br_active", "Automatic cloud backup enabled"),)
_EXTENDED_LOG_FIELDS = (boolean("use_extendlog", "Detailed system logging enabled"),)
_LTE_PREREQUISITE = boolean("use_lte", "5G receiver enabled")
_EASY_SUPPORT_PREREQUISITE = boolean("easy_support_deactive", "EasySupport disabled")


def _read_fields(
    fields: tuple[SettingsField, ...], raw: SettingValues
) -> dict[str, Any]:
    """Require every current form field, without retaining unrelated values."""
    return {item.name: item.read(raw) for item in fields}


def _changed_values(
    fields: tuple[SettingsField, ...], raw: SettingValues, changes: SettingValues
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the complete fresh state even when all fields are replaced."""
    before = _read_fields(fields, raw)
    after = dict(before)
    for item in fields:
        if item.name in changes:
            after[item.name] = item.validate(changes[item.name])
    return before, after


def _wire(values: SettingValues) -> dict[str, str | int | bool]:
    """Encode only already-validated form values."""
    return {
        key: ("1" if value else "0") if type(value) is bool else value
        for key, value in values.items()
    }


def _build_led(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Mirror the separate LED form, including its hidden schedule fields."""
    before = _read_led(raw)
    after = _read_led({**before, **changes})
    if after["led_mode"] == "0":
        if any(after[key] != before[key] for key in ("led_from", "led_to")):
            raise ConfigurationError
        return {"led_mode": "0"}
    if after["led_from"] == after["led_to"]:
        raise ConfigurationError
    return _wire(after)


def _read_led(raw: SettingValues) -> dict[str, Any]:
    """Keep the Energy-specific timehhmm range out of other time controls."""
    values = _read_fields(_LED_FIELDS, raw)
    if any(
        re.fullmatch(r"(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)", values[key]) is None
        for key in ("led_from", "led_to")
    ):
        raise ConfigurationError
    return values


def _build_energy(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Preserve the shared energy form and its firmware visibility branches."""
    before, after = _changed_values(_ENERGY_FIELDS, raw, changes)
    if not after["use_wlan"]:
        if any(after[key] != before[key] for key in ("wlan_band", "wlan_power")):
            raise ConfigurationError
        if before["use_wlan"]:
            connection = raw.get("config_connection")
            if not (
                (type(connection) is int and connection == 0)
                or (type(connection) is str and connection == "0")
            ):
                # The firmware uses a separate Modules action when the current
                # connection is wireless. Do not substitute an Energy POST.
                raise ConfigurationError("settings_unavailable")
        # The form serializer includes hidden selects, but not hidden radios.
        after.pop("wlan_band")
    return _wire(after)


def _build_https(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Use Protect.json while reading the flag from the Energy page source."""
    return _wire(_changed_values(_HTTPS_FIELDS, raw, changes)[1])


def _build_external_modem(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Refuse the local mode switch while the firmware's 5G guard is active."""
    if _LTE_PREREQUISITE.read(raw):
        raise ConfigurationError("settings_unavailable")
    return _wire(_changed_values(_EXTERNAL_MODEM_FIELDS, raw, changes)[1])


def _build_cloud_backup(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Keep cloud-backup consent separate from remote-support state."""
    if _EASY_SUPPORT_PREREQUISITE.read(raw):
        raise ConfigurationError("settings_unavailable")
    return _wire(_changed_values(_CLOUD_BACKUP_FIELDS, raw, changes)[1])


def _build_extended_log(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Never copy message contents or filters into the module-switch request."""
    return _wire(_changed_values(_EXTENDED_LOG_FIELDS, raw, changes)[1])


SYSTEM_SETTINGS: tuple[SettingsContract, ...] = (
    SettingsContract(
        id="system_led_schedule",
        title="Front LED schedule",
        section="System",
        endpoint="data/Energy.json",
        referer=_CONFIG + "energy.html",
        fields=_LED_FIELDS,
        builder=_build_led,
        reader=_read_led,
        warning=(
            "The daily LED-off interval may cross midnight. Schedule times can "
            "be changed only while scheduled mode is selected."
        ),
        confirmation="CHANGE LED SCHEDULE",
        payload_keys=frozenset({"led_mode", "led_from", "led_to"}),
    ),
    SettingsContract(
        id="system_energy",
        title="Wi-Fi and USB energy settings",
        section="System",
        endpoint="data/Energy.json",
        referer=_CONFIG + "energy.html",
        fields=_ENERGY_FIELDS,
        builder=_build_energy,
        warning=(
            "Changing Wi-Fi bands or power can disconnect devices. Disabling "
            "Wi-Fi through this form requires a wired management connection. "
            "Disabling USB interrupts attached storage and printers."
        ),
        confirmation="CHANGE ENERGY SETTINGS",
        payload_keys=frozenset({"use_wlan", "wlan_band", "wlan_power", "use_usb"}),
        revision_fields=("config_connection",),
    ),
    SettingsContract(
        id="system_https",
        title="Secure local web access",
        section="System",
        endpoint="data/Protect.json",
        referer=_CONFIG + "protect.html",
        fields=_HTTPS_FIELDS,
        read_endpoint="data/Energy.json",
        builder=_build_https,
        warning=(
            "This changes the router's management connection scheme and can "
            "disconnect Home Assistant. HTTPS uses the router certificate; "
            "the integration connection and certificate policy may need updating. "
            "The old HTTP or HTTPS address is not guaranteed to remain reachable."
        ),
        confirmation="CHANGE HTTPS ACCESS",
        payload_keys=frozenset({"use_https"}),
        acknowledgement="readback",
        readback_policy="reconnect_required",
    ),
    SettingsContract(
        id="system_external_modem",
        title="External modem / Link-LAN1 mode",
        section="System",
        endpoint="data/ExtModem.json",
        referer=_CONFIG + "external_modem.html",
        fields=_EXTERNAL_MODEM_FIELDS,
        builder=_build_external_modem,
        warning=(
            "Changing Link/LAN1 mode restarts the router and can disconnect "
            "Internet access. Check cabling and retain a wired recovery path. "
            "The firmware blocks this switch while the 5G receiver is enabled."
        ),
        confirmation="CHANGE LINK LAN MODE",
        payload_keys=frozenset({"auto_external_modem"}),
        revision_fields=("use_lte",),
        acknowledgement="readback",
        readback_policy="reconnect_required",
    ),
    SettingsContract(
        id="system_cloud_backup",
        title="Automatic Telekom cloud backup",
        section="System",
        endpoint="data/BackupRestore.json",
        referer=_CONFIG + "save_settings.html",
        fields=_CLOUD_BACKUP_FIELDS,
        builder=_build_cloud_backup,
        warning=(
            "This controls automatic backup and restoration of private router "
            "settings through Telekom. Changes require EasySupport to be "
            "enabled; this is not a remote-support switch."
        ),
        confirmation="CHANGE CLOUD BACKUP",
        payload_keys=frozenset({"br_active"}),
        revision_fields=("easy_support_deactive",),
        acknowledgement="readback",
    ),
    SettingsContract(
        id="system_extended_logging",
        title="Detailed system logging",
        section="System",
        endpoint="data/Modules.json",
        referer=_CONFIG + "system_log.html",
        fields=_EXTENDED_LOG_FIELDS,
        read_endpoint="data/SystemMessages.json",
        builder=_build_extended_log,
        warning=(
            "Detailed router logs may contain network and telephone data. "
            "This editor returns only the logging flag, never log contents."
        ),
        confirmation="CHANGE DETAILED LOGGING",
        payload_keys=frozenset({"use_extendlog"}),
        acknowledgement="readback",
    ),
)
