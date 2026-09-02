"""USB removal contracts are pure and never change a real device."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.storage_lifecycle import (
    USB_UNMOUNT_ENDPOINT,
    USB_UNMOUNT_SETTING_ID,
    storage_target_contract,
    storage_target_metadata,
    usb_device_rows,
    usb_unmount_metadata,
    usb_unmount_payload,
    usb_unmount_targets,
    verify_usb_unmount,
)


def _raw() -> dict[str, Any]:
    return {
        "use_usb": "1",
        "addnasdevice": [
            {
                "id": "1",
                "serial": "synthetic-disk",
                "nas_device_type": "NAS",
                "nas_device_name": "Disk",
                "nas_device_used": "100",
                "nas_device_total": "1000",
            },
            {
                "id": "2",
                "serial": "synthetic-printer",
                "nas_device_type": "printer",
                "nas_device_name": "Printer",
            },
        ],
    }


def test_exact_usb_target_and_payload_not_printer() -> None:
    """The form uses OtherDevice, not the NAS read endpoint or arbitrary serial."""
    assert USB_UNMOUNT_ENDPOINT == "data/OtherDevice.json"
    assert [row["id"] for row in usb_unmount_targets(_raw())] == ["1"]
    assert usb_unmount_payload(_raw(), "1") == {
        "id": "1",
        "serial": "synthetic-disk",
        "deleteEntry": "delete",
    }
    with pytest.raises(ConfigurationError):
        usb_unmount_payload(_raw(), "2")
    with pytest.raises(ConfigurationError):
        usb_unmount_payload(_raw(), "synthetic-disk")


@pytest.mark.parametrize(
    "changed",
    [
        {"use_usb": "0"},
        {"addnasdevice": None},
        {"addnasdevice": [{}]},
        {"addnasdevice": [{"id": "1", "serial": "", "nas_device_type": "NAS"}]},
        {"AddNasDevice": []},
    ],
)
def test_incomplete_or_ambiguous_device_inventory_rejected(
    changed: dict[str, Any],
) -> None:
    """Device loss cannot be claimed when the read is malformed or access is lost."""
    with pytest.raises(ConfigurationError):
        usb_device_rows({**_raw(), **changed})


def test_removal_verification_preserves_siblings_and_exact_serial() -> None:
    """An unchanged device under a reassigned ID is not verified removal."""
    before = _raw()
    after = deepcopy(before)
    after["addnasdevice"].pop(0)
    assert verify_usb_unmount(before, after, "1")
    after["addnasdevice"][0]["nas_device_name"] = "Changed printer"
    assert not verify_usb_unmount(before, after, "1")
    after = deepcopy(before)
    after["addnasdevice"][0]["id"] = "3"
    assert not verify_usb_unmount(before, after, "1")
    with pytest.raises(ConfigurationError):
        verify_usb_unmount(before, {"use_usb": "1", "status": "ok"}, "1")


def test_metadata_warns_interruption_and_unverified_live_writes() -> None:
    """A published contract must not claim this offline test unplugged a disk."""
    metadata = usb_unmount_metadata()
    assert metadata["requires_target"] is True
    assert metadata["live_write_verified"] is False
    assert metadata["confirmation"] == "SAFELY REMOVE USB DEVICE"
    assert "interrupts file transfers" in metadata["warning"]


def test_settings_adapter_uses_existing_transaction_and_different_read_endpoint() -> (
    None
):
    """Removal has no new grant mechanism or arbitrary command proxy."""
    contract = storage_target_contract(USB_UNMOUNT_SETTING_ID, "1")
    assert contract.read(_raw()) == {"execute": False}
    assert contract.read_endpoint == "data/NASDevice.json"
    assert contract.endpoint == "data/OtherDevice.json"
    assert contract.build(_raw(), {"execute": True}) == usb_unmount_payload(_raw(), "1")
    assert contract.verifier_owns_fields is True
    metadata = storage_target_metadata()[0]
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()
    with pytest.raises(ConfigurationError):
        contract.build(_raw(), {"execute": False})
