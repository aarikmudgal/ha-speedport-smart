"""Offline target-bound NAS editor contracts and single-send transactions."""

# ruff: noqa: S105 - synthetic credentials only

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    settings_contracts,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_storage import (
    NAS_SHARE_SETTING_ID,
    nas_share_settings,
    nas_share_settings_metadata,
)


def _row() -> dict[str, Any]:
    return {
        "sid": "7",
        "use_usb": "1",
        "printer_connected": "0",
        "nas_active": "1",
        "nas_folder_nur_lesen": "0",
        "nas_secure": "0",
        "nas_folder_name": "/Existing/Path",
        "nas_user_name": "share-user",
        "nas_user_pwd": "NEVER-REUSE-ME",
    }


def test_target_factory_is_not_unbound_scalar_registration() -> None:
    """Only a separately validated existing target can obtain this contract."""
    assert NAS_SHARE_SETTING_ID not in settings_contracts()
    contract = nas_share_settings("7")
    assert contract.endpoint == "data/NASFolder.json"
    assert contract.acknowledgement == "readback"
    assert contract.confirmation == "SAVE SHARE SETTINGS"
    assert contract.metadata()["live_write_verified"] is False
    assert "nas_folder_name" in {field.name for field in contract.fields}
    metadata = nas_share_settings_metadata()
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()


def test_existing_share_flag_edit_preserves_path_and_private_credentials() -> None:
    """Exact untouched state is retained without passing back a stored secret."""
    contract = nas_share_settings("7")
    assert "nas_user_pwd" not in contract.read(_row())
    assert contract.build(_row(), {"nas_folder_nur_lesen": True}) == {
        "sid": "7",
        "nas_active": 1,
        "nas_folder_nur_lesen": 1,
        "nas_secure": 0,
        "nas_folder_name": "/Existing/Path",
    }
    assert contract.build(_row(), {"nas_active": False}) == {
        "sid": "7",
        "nas_active": 0,
    }


@pytest.mark.parametrize("target", ["-1", "", "../7", "7\n", 7, True])
def test_missing_new_or_malformed_target_rejected(target: object) -> None:
    """No path, new-row sentinel, or untyped target reaches a router command."""
    with pytest.raises(ConfigurationError):
        nas_share_settings(target)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changed",
    [
        {"sid": "8"},
        {"id": "8"},
        {"use_usb": "0"},
        {"use_usb": None},
        {"nas_folder_name": ""},
        {"nas_active": "bad"},
    ],
)
def test_mismatched_target_and_missing_state_rejected(changed: dict[str, Any]) -> None:
    """Ambiguous targets or disabled/missing USB cannot become editable."""
    with pytest.raises(ConfigurationError):
        nas_share_settings("7").build({**_row(), **changed}, {"nas_active": False})


def test_secure_edit_requires_fresh_password_and_keeps_it_out_of_views() -> None:
    """Do not recycle a returned password, plaintext or redacted."""
    contract = nas_share_settings("7")
    raw = {**_row(), "nas_secure": "1"}
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"nas_folder_nur_lesen": True})
    payload = contract.build(raw, {"nas_user_pwd": "Fresh-Pass-1"})
    assert payload["nas_user_pwd"] == "Fresh-Pass-1"
    assert payload["nas_user_name"] == "share-user"
    assert "NEVER-REUSE-ME" not in str(payload)
    assert "NEVER-REUSE-ME" not in str(contract.read(raw))


@pytest.mark.parametrize(
    "changes",
    [
        {"sid": "8"},
        {"nas_folder_name": "/Other/../Private"},
        {"nas_active": False, "nas_secure": True},
        {"nas_secure": True, "nas_user_name": "short", "nas_user_pwd": "Fresh-Pass-1"},
        {"nas_secure": True, "nas_user_pwd": "x" * 33},
        {"nas_secure": True, "nas_user_pwd": "[REDACTED]"},
        {"nas_secure": True, "nas_user_pwd": "bad[chars]"},
    ],
)
def test_unknown_or_invalid_changes_never_reach_payload(
    changes: dict[str, Any],
) -> None:
    """Only the exact conditional firmware form can be built."""
    with pytest.raises(ConfigurationError):
        nas_share_settings("7").build(_row(), changes)


def test_unprotected_share_can_read_empty_username() -> None:
    """Unused credentials do not hide the existing share controls."""
    assert (
        nas_share_settings("7").read({**_row(), "nas_user_name": ""})["nas_user_name"]
        == ""
    )


def test_folder_path_edit_preserves_identity_flags_and_other_fields() -> None:
    """The exact bounded folder path is editable without creating directories."""
    contract = nas_share_settings("7")
    payload = contract.build(_row(), {"nas_folder_name": "/Storage/New Folder"})
    assert payload == {
        "sid": "7",
        "nas_active": 1,
        "nas_folder_name": "/Storage/New Folder",
        "nas_folder_nur_lesen": 0,
        "nas_secure": 0,
    }


@pytest.mark.parametrize(
    "path",
    [
        "relative",
        "/",
        "//disk",
        "/disk/",
        "/disk/../private",
        "/disk/./folder",
        "/disk\\folder",
        "/disk\nfolder",
        "/" + "x" * 512,
    ],
)
def test_folder_path_rejects_ambiguous_and_unbounded_inputs(path: str) -> None:
    """Never normalize traversal or guess which storage path was intended."""
    with pytest.raises(ConfigurationError):
        nas_share_settings("7").build(_row(), {"nas_folder_name": path})


@pytest.mark.asyncio
async def test_session_target_revision_write_once_and_independent_readback() -> None:
    """The shared transaction machinery binds target and returns verified state."""
    state = _row()
    writes: list[dict[str, Any]] = []
    contract = nas_share_settings("7")
    session = ConfigurationSession()

    async def read() -> dict[str, Any]:
        return dict(state)

    async def write(raw: dict[str, Any], changes: dict[str, Any]) -> None:
        payload = contract.build(raw, changes)
        writes.append(payload)
        state.update(payload)

    loaded = await session.read(contract, ("admin", "connection"), read)
    assert await session.save(
        contract,
        ("admin", "connection"),
        loaded["revision"],
        {"nas_folder_nur_lesen": True},
        confirmed=True,
        confirmation_text="SAVE SHARE SETTINGS",
        read=read,
        write=write,
    ) == {"status": "verified"}
    assert len(writes) == 1
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            ("admin", "connection"),
            loaded["revision"],
            {"nas_folder_nur_lesen": False},
            confirmed=True,
            confirmation_text="SAVE SHARE SETTINGS",
            read=read,
            write=write,
        )
    assert len(writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"sid": "8"}, {"nas_folder_name": "/Changed"}])
async def test_revision_binds_exact_share_and_preserved_path(
    change: dict[str, Any],
) -> None:
    """Another target or independently changed folder cannot reuse a read."""
    state = _row()
    session = ConfigurationSession()
    contract = nas_share_settings("7")

    async def read() -> dict[str, Any]:
        return dict(state)

    async def write(_raw: dict[str, Any], _changes: dict[str, Any]) -> None:
        pytest.fail("A stale target must not be sent")

    loaded = await session.read(contract, ("admin", "connection"), read)
    state.update(change)
    selected = nas_share_settings(state["sid"])
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            selected,
            ("admin", "connection"),
            loaded["revision"],
            {"nas_active": False},
            confirmed=True,
            confirmation_text="SAVE SHARE SETTINGS",
            read=read,
            write=write,
        )
