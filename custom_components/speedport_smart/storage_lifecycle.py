"""Private, target-bound USB safe-removal contracts and readback proof."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import ConfigurationError, SettingsContract, boolean
from .configuration_phone_targets import PhoneTargetSpec

if TYPE_CHECKING:
    from .configuration import SettingValues

USB_DEVICE_ENDPOINT: Final = "data/NASDevice.json"
USB_DEVICE_REFERER: Final = "html/content/network/nas_overview.html"
USB_UNMOUNT_ENDPOINT: Final = "data/OtherDevice.json"
USB_UNMOUNT_CONFIRMATION: Final = "SAFELY REMOVE USB DEVICE"
_USB: Final = boolean("use_usb", "USB enabled")
_ID: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}")
_MAX_ROWS: Final = 64  # Defensive bound; not a claimed hardware port count.
_MAX_SERIAL: Final = 256
_VOLATILE: Final = frozenset({"nas_device_used", "nas_device_total"})
USB_UNMOUNT_SETTING_ID: Final = "storage_usb_safe_remove"
_EXECUTE: Final = boolean("execute", "Safely remove this USB device")


@dataclass(frozen=True, slots=True)
class UsbTargetSpec(PhoneTargetSpec):
    """The read endpoint intentionally differs from the mutation form action."""

    read_endpoint: str


STORAGE_TARGET_SPECS: Final = MappingProxyType(
    {
        USB_UNMOUNT_SETTING_ID: UsbTargetSpec(
            USB_UNMOUNT_SETTING_ID,
            "Safely remove USB storage",
            USB_UNMOUNT_ENDPOINT,
            USB_DEVICE_REFERER,
            "addnasdevice",
            "nas_device_name",
            (_EXECUTE,),
            USB_DEVICE_ENDPOINT,
        )
    }
)


def usb_device_rows(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Require an explicit complete inventory before selecting or proving absence."""
    if not _USB.read(raw):
        raise ConfigurationError("setting_unavailable")
    keys = [key for key in raw if str(key).casefold() == "addnasdevice"]
    if keys != ["addnasdevice"]:
        raise ConfigurationError("settings_inventory_unavailable")
    value = raw["addnasdevice"]
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, list) or len(value) > _MAX_ROWS:
        raise ConfigurationError("settings_inventory_unavailable")
    result = []
    seen = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ConfigurationError("settings_inventory_unavailable")
        identifier = row.get("id")
        serial = row.get("serial")
        if (
            not isinstance(identifier, str)
            or _ID.fullmatch(identifier) is None
            or identifier in seen
            or not isinstance(serial, str)
            or not 0 < len(serial) <= _MAX_SERIAL
            or not serial.isprintable()
            or not isinstance(row.get("nas_device_type"), str)
        ):
            raise ConfigurationError("settings_inventory_unavailable")
        seen.add(identifier)
        result.append(dict(row))
    return tuple(result)


def usb_unmount_targets(raw: SettingValues) -> tuple[dict[str, Any], ...]:
    """Only the two exact firmware branches expose a safe-removal operation."""
    return tuple(
        row
        for row in usb_device_rows(raw)
        if row["nas_device_type"] in {"NAS", "adhoc"}
    )


def usb_unmount_payload(raw: SettingValues, target_id: str) -> dict[str, str]:
    """Bind the exact current serial and ID; never accept a user-supplied serial."""
    matches = [row for row in usb_unmount_targets(raw) if row["id"] == target_id]
    if len(matches) != 1:
        raise ConfigurationError("settings_target_unavailable")
    return {"deleteEntry": "delete", "serial": matches[0]["serial"], "id": target_id}


def verify_usb_unmount(
    before: SettingValues, after: SettingValues, target_id: str
) -> bool:
    """Prove exact device absence and unchanged sibling identity, not lost access."""
    selected = usb_unmount_payload(before, target_id)
    previous = usb_device_rows(before)
    current = usb_device_rows(after)
    if any(
        row["id"] == target_id or row["serial"] == selected["serial"] for row in current
    ):
        return False
    expected = {
        row["id"]: {key: value for key, value in row.items() if key not in _VOLATILE}
        for row in previous
        if row["id"] != target_id
    }
    actual = {
        row["id"]: {key: value for key, value in row.items() if key not in _VOLATILE}
        for row in current
    }
    return expected == actual


def usb_unmount_metadata() -> dict[str, Any]:
    """Describe explicit interruption and proof requirements without current values."""
    return {
        "id": USB_UNMOUNT_SETTING_ID,
        "title": "Safely remove USB storage",
        "warning": (
            "This disconnects the selected USB storage device and interrupts file "
            "transfers and media playback. It does not delete its files. Wait for "
            "verified removal before unplugging it."
        ),
        "confirmation": USB_UNMOUNT_CONFIRMATION,
        "requires_target": True,
        "live_write_verified": False,
    }


def storage_target_rows(
    setting_id: str, raw: SettingValues
) -> tuple[dict[str, Any], ...]:
    """Expose only fixed safe-removal targets through the shared settings dispatcher."""
    if setting_id != USB_UNMOUNT_SETTING_ID:
        raise ConfigurationError("setting_unavailable")
    return usb_unmount_targets(raw)


def storage_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Use the existing revision/confirmation/single-send transaction for removal."""
    if (
        setting_id != USB_UNMOUNT_SETTING_ID
        or not isinstance(target_id, str)
        or _ID.fullmatch(target_id) is None
    ):
        raise ConfigurationError("invalid_settings_target")

    def read(raw: SettingValues) -> dict[str, bool]:
        usb_unmount_payload(raw, target_id)
        return {"execute": False}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        if changes != {"execute": True}:
            raise ConfigurationError("invalid_settings")
        return dict(usb_unmount_payload(raw, target_id))

    return SettingsContract(
        setting_id,
        "Safely remove USB storage",
        "Storage",
        USB_UNMOUNT_ENDPOINT,
        USB_DEVICE_REFERER,
        (_EXECUTE,),
        read_endpoint=USB_DEVICE_ENDPOINT,
        reader=read,
        builder=build,
        payload_keys=frozenset({"deleteEntry", "serial", "id"}),
        revision_fields=("use_usb", "addnasdevice"),
        verifier=lambda before, _changes, after: verify_usb_unmount(
            before, after, target_id
        ),
        verifier_owns_fields=True,
        warning=usb_unmount_metadata()["warning"],
        confirmation=USB_UNMOUNT_CONFIRMATION,
    )


def storage_target_metadata() -> list[dict[str, Any]]:
    """Describe the command field without selecting a device or pretending state."""
    return [
        {
            **usb_unmount_metadata(),
            "section": "Storage",
            "fields": [_EXECUTE.metadata()],
        }
    ]
