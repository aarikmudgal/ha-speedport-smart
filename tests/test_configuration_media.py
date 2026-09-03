"""Complete typed media-folder forms without router I/O."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_media import (
    MEDIA_CREATE_SETTINGS,
    MEDIA_DELETE_SETTING_ID,
    MEDIA_SETTING_ID,
    media_index_status,
    media_reindex_payload,
    media_target_contract,
    media_target_metadata,
    media_target_rows,
)


def _raw() -> dict[str, Any]:
    return {
        "use_usb": "1",
        "addnasmediareplay": [
            {
                "id": "2",
                "mediareplay_name": "Music",
                "mediareplay_folder": "/Disk/Music",
                "mediareplay_status": "1",
                "mediareplay_active": "1",
            },
            {
                "id": "5",
                "mediareplay_name": "Videos",
                "mediareplay_folder": "/Disk/Videos",
                "mediareplay_status": "0",
                "mediareplay_active": "0",
            },
        ],
    }


def test_media_full_payload_and_static_metadata() -> None:
    """The preserved hidden status and exact form identity travel with edits."""
    contract = media_target_contract(MEDIA_SETTING_ID, "2")
    assert contract.build(_raw(), {"mediareplay_name": "Songs"}) == {
        "id": "2",
        "mediareplay_name": "Songs",
        "mediareplay_folder": "/Disk/Music",
        "mediareplay_status": "1",
        "mediareplay_active": 1,
    }
    assert contract.endpoint == "data/NASMediaReplay.json"
    metadata = media_target_metadata()[0]
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()
    assert contract.confirmation == "SAVE MEDIA FOLDER"


@pytest.mark.parametrize(
    "changes",
    [
        {"mediareplay_name": "Videos"},
        {"mediareplay_folder": "/Disk/Videos"},
        {"mediareplay_name": "<iframe>"},
        {"mediareplay_name": ""},
        {"mediareplay_name": "x" * 21},
        {"mediareplay_folder": "/Disk/../Private"},
        {"mediareplay_folder": "Disk/Music"},
        {"mediareplay_active": 1},
        {"id": "5"},
        {"mediareplay_status": "0"},
    ],
)
def test_invalid_or_duplicate_form_values_fail(changes: dict[str, Any]) -> None:
    """The router's duplicate name/path checks apply across the full inventory."""
    with pytest.raises(ConfigurationError):
        media_target_contract(MEDIA_SETTING_ID, "2").build(_raw(), changes)


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"use_usb": "0", "addnasmediareplay": []},
        {"use_usb": "1"},
        {"use_usb": "1", "addnasmediareplay": None},
        {"use_usb": "1", "addnasmediareplay": [{"id": "1"}, {"id": "1"}]},
    ],
)
def test_missing_disabled_or_ambiguous_inventory_fails(raw: dict[str, Any]) -> None:
    """No global fallback or duplicate identity is an editable collection."""
    with pytest.raises(ConfigurationError):
        media_target_rows(MEDIA_SETTING_ID, raw)


def test_verifier_requires_target_and_sibling_preservation() -> None:
    """Folder changes cannot be verified against a different row or changed sibling."""
    contract = media_target_contract(MEDIA_SETTING_ID, "2")
    before = _raw()
    after = deepcopy(before)
    after["addnasmediareplay"][0]["mediareplay_name"] = "Songs"
    assert contract.verifier is not None
    assert contract.verifier(before, {"mediareplay_name": "Songs"}, after)
    after["addnasmediareplay"][0]["mediareplay_status"] = "Indexing"
    assert contract.verifier(before, {"mediareplay_name": "Songs"}, after)
    after["addnasmediareplay"][1]["mediareplay_folder"] = "/Other/Videos"
    assert not contract.verifier(before, {"mediareplay_name": "Songs"}, after)


def test_media_reindex_requires_enabled_folder_and_valid_index_metrics() -> None:
    """Only the proven action payload is emitted; no fake time remaining."""
    assert media_reindex_payload(_raw()) == {"makeindex": "true"}
    assert media_index_status(
        {"DLNA_IndexStatus": "Counting", "DLNA_IndexFileLeft": "120"}
    ) == {"status": "Counting", "files_remaining": 120}
    with pytest.raises(ConfigurationError):
        media_reindex_payload({"use_usb": "1", "addnasmediareplay": []})
    with pytest.raises(ConfigurationError):
        media_index_status({"DLNA_IndexStatus": "", "DLNA_IndexFileLeft": "0"})
    with pytest.raises(ConfigurationError):
        media_index_status({"DLNA_IndexStatus": "Finished", "DLNA_IndexFileLeft": "-1"})


def test_delete_media_folder_removes_configuration_only_and_verifies_siblings() -> None:
    """The generic firmware delete form is not a filesystem deletion endpoint."""
    contract = media_target_contract(MEDIA_DELETE_SETTING_ID, "2")
    before = _raw()
    assert contract.read(before) == {"execute": False}
    assert contract.build(before, {"execute": True}) == {
        "id": "2",
        "deleteEntry": "delete",
    }
    assert contract.verifier is not None
    after = {**before, "addnasmediareplay": [before["addnasmediareplay"][1]]}
    assert contract.verifier(before, {"execute": True}, after)
    assert not contract.verifier(before, {"execute": True}, before)
    with pytest.raises(ConfigurationError):
        contract.verifier(before, {"execute": True}, {"use_usb": "1"})
    metadata = media_target_metadata()[1]
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()


def test_media_create_uses_exact_template_defaults_and_unique_new_row() -> None:
    """The captured hidden status is success, not a guessed empty field."""
    contract = MEDIA_CREATE_SETTINGS[0]
    before = _raw()
    changes = {
        "mediareplay_name": "Photos",
        "mediareplay_folder": "/Disk/Photos",
        "mediareplay_active": True,
    }
    payload = contract.build(before, changes)
    assert payload == {
        "id": "-1",
        "mediareplay_status": "success",
        **changes,
        "mediareplay_active": 1,
    }
    after = deepcopy(before)
    after["addnasmediareplay"].append({**payload, "id": "7"})
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    after["addnasmediareplay"][0]["mediareplay_name"] = "Changed old folder"
    assert not contract.verifier(before, changes, after)
    with pytest.raises(ConfigurationError):
        contract.build(before, {**changes, "mediareplay_name": "Music"})


def test_media_create_explicit_empty_inventory_not_global_fallback() -> None:
    """No attached device or omitted media list is not a creation-ready empty list."""
    contract = MEDIA_CREATE_SETTINGS[0]
    assert contract.read({"use_usb": "1", "addnasmediareplay": []}) == {
        "mediareplay_name": "",
        "mediareplay_folder": "",
        "mediareplay_active": False,
    }
    with pytest.raises(ConfigurationError):
        contract.read({"use_usb": "1"})


def test_reindex_requires_idle_then_independently_observed_work() -> None:
    """An ACK or unchanged Finished sample cannot falsely prove another index run."""
    contract = MEDIA_CREATE_SETTINGS[1]
    before = {
        **_raw(),
        "index": {"DLNA_IndexStatus": "Finished", "DLNA_IndexFileLeft": "0"},
    }
    assert contract.build(before, {"execute": True}) == {"makeindex": "true"}
    assert contract.verifier is not None
    assert not contract.verifier(before, {"execute": True}, before)
    after = {
        **before,
        "index": {"DLNA_IndexStatus": "Indexing", "DLNA_IndexFileLeft": "12"},
    }
    assert contract.verifier(before, {"execute": True}, after)
    with pytest.raises(ConfigurationError):
        contract.build(after, {"execute": True})
