"""Complete guest and prioritized Wi-Fi forms from the reviewed firmware."""

from __future__ import annotations

from typing import Any

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    SettingValues,
    boolean,
    choice,
)

_ENCRYPTION = (
    ("6", "WPA3"),
    ("5", "WPA2 / WPA3"),
    ("4", "WPA2"),
    ("0", "Open network (no encryption)"),
)
_LIFETIMES = (
    ("0", "Always"),
    *(
        (str(hours * 60), f"{hours} hours")
        for hours in (1, 2, 3, 4, 5, 6, 12, 18, 24, 36, 48)
    ),
)
_MAIN_ENABLED = boolean("use_wlan", "Main Wi-Fi")
_WPS_ENABLED = boolean("use_wps", "WPS")
_SSID_NAMES = ("wlan_ssid", "wlan_5ghz_ssid", "wlan_guest_ssid", "wlan_office_ssid")


def _ascii(value: object) -> str:
    """Match the firmware's ASCII32to126 validator without stripping spaces."""
    if not isinstance(value, str) or not value.isascii() or not value.isprintable():
        raise ConfigurationError("invalid_wifi_text")
    return value


def _contract(kind: str) -> SettingsContract:
    """Construct one of two static forms, not a caller-controlled prefix."""
    guest = kind == "guest"
    prefix = f"wlan_{kind}_"
    fields: tuple[SettingsField, ...] = (
        boolean(prefix + "active", "Network enabled"),
        SettingsField(prefix + "ssid", "Network name", "text", minimum=1, maximum=32),
        choice(prefix + "enc", "Encryption", _ENCRYPTION),
        boolean(prefix + "pmf", "Protected management frames (WPA2 only)"),
        SettingsField(
            prefix + "key",
            "Wi-Fi password",
            "secret",
            minimum=8,
            maximum=63,
            description=(
                "Leave blank to preserve a readable current key. Re-enter a masked key."
            ),
        ),
    )
    if guest:
        fields += (
            choice(prefix + "time", "Guest access duration", _LIFETIMES),
            boolean(prefix + "fdis", "End access even when devices are connected"),
            boolean(prefix + "display_key", "Show guest key on the router display"),
            boolean(prefix + "wps", "Use WPS for the guest network"),
            boolean(prefix + "inet", "Internet-only access (isolate the home network)"),
        )
    by_name = {field.name: field for field in fields}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        if not _MAIN_ENABLED.read(raw):
            raise ConfigurationError("wifi_disabled")

        def value(suffix: str) -> str | int | bool:
            field = by_name[prefix + suffix]
            result = (
                field.validate(changes[field.name])
                if field.name in changes
                else field.read(raw)
            )
            if isinstance(result, list):
                raise ConfigurationError("invalid_wifi_text")
            return result

        enabled = value("active")
        encryption = value("enc")
        # Hidden selects still serialize in the native template engine.
        selected = {prefix + "active", prefix + "enc"}
        if guest:
            selected.add(prefix + "time")
        if enabled:
            selected.add(prefix + "ssid")
            if encryption == "4":
                selected.add(prefix + "pmf")
            if encryption != "0":
                selected.add(prefix + "key")
                if guest:
                    selected.add(prefix + "display_key")
            if guest:
                selected.update({prefix + "fdis", prefix + "inet"})
                if _WPS_ENABLED.read(raw) and encryption != "6":
                    selected.add(prefix + "wps")
        editable = selected if enabled else {prefix + "active"}
        if not changes.keys() <= editable:
            raise ConfigurationError("inactive_settings_field")
        values = {name: value(name.removeprefix(prefix)) for name in selected}
        if enabled:
            ssid = _ascii(values[prefix + "ssid"])
            for other in _SSID_NAMES:
                if other == prefix + "ssid":
                    continue
                other_value = raw.get(other)
                if not isinstance(other_value, str):
                    raise ConfigurationError("incomplete_wifi_identity")
                if other_value.casefold() == ssid.casefold():
                    raise ConfigurationError("duplicate_wifi_name")
            if encryption != "0":
                _ascii(values[prefix + "key"])
        if (
            guest
            and prefix + "display_key" in values
            and {prefix + "ssid", prefix + "key"} & changes.keys()
            and prefix + "display_key" not in changes
        ):
            values[prefix + "display_key"] = False
        return {
            name: ("1" if val else "0") if type(val) is bool else val
            for name, val in values.items()
        }

    def read(raw: SettingValues) -> dict[str, Any]:
        return {
            field.name: field.read(raw) for field in fields if field.kind != "secret"
        }

    return SettingsContract(
        f"wifi_{kind}_settings",
        "Guest Wi-Fi settings" if guest else "Office / prioritized Wi-Fi settings",
        "Wi-Fi",
        "data/WLANBasic.json",
        f"html/content/network/wlan_{kind}.html",
        fields,
        reader=read,
        builder=build,
        revision_fields=(*_SSID_NAMES, "use_wlan", "use_wps"),
        warning=(
            "Changing the network name, key or encryption disconnects its clients. "
            "An open network has no encryption. Disabling guest Internet-only access "
            "allows guests to reach the home network. Hidden security fields cannot "
            "be changed while their network or encryption mode is inactive."
            if guest
            else "Changing name, key or encryption disconnects clients. "
            "An open network has no encryption. Hidden security fields cannot be "
            "changed while their network or encryption mode is inactive."
        ),
        confirmation="SAVE WI-FI SETTINGS",
    )


WIFI_EXTRA_SETTINGS = (_contract("guest"), _contract("office"))
