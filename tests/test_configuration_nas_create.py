"""New NAS share lifecycle is guarded and tested without router writes."""

# ruff: noqa: S105, S106 - synthetic credentials only

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_nas_create import (
    NAS_CREATE_SETTINGS,
    nas_share_create_payload,
    verify_nas_share_creation,
)


def _empty() -> dict[str, Any]:
    return {
        "sid": "-1",
        "use_usb": "1",
        "printer_connected": "0",
        "nas_active": "0",
        "nas_secure": "0",
        "nas_folder_nur_lesen": "0",
        "nas_folder_name": "",
        "nas_user_name": "",
    }


def _draft() -> dict[str, Any]:
    return {
        "nas_active": True,
        "nas_folder_name": "/Disk/Shared",
        "nas_folder_nur_lesen": True,
    }


def test_create_requires_real_empty_sentinel_and_exact_payload() -> None:
    """A new share uses the reviewed sentinel, never an invented existing row."""
    contract = NAS_CREATE_SETTINGS[0]
    assert contract.build(_empty(), _draft()) == {
        "sid": "-1",
        "nas_active": 1,
        "nas_folder_name": "/Disk/Shared",
        "nas_folder_nur_lesen": 1,
        "nas_secure": 0,
    }
    assert contract.confirmation == "CREATE NAS SHARE"
    assert contract.acknowledgement == "readback"
    assert contract.verifier_owns_fields is True
    assert "nas_user_pwd" not in contract.read(_empty())


@pytest.mark.parametrize(
    "changed",
    [
        {"sid": "0"},
        {"sid": None},
        {"nas_active": "1"},
        {"nas_folder_name": "/Existing"},
        {"use_usb": "0"},
        {"printer_connected": "1"},
        {"printer_connected": []},
        {"nas_user_name": None},
    ],
)
def test_missing_or_nonempty_form_never_overwrites_share(
    changed: dict[str, Any],
) -> None:
    """Creation cannot repurpose an existing share or printer-mode state."""
    with pytest.raises(ConfigurationError):
        nas_share_create_payload({**_empty(), **changed}, _draft())


def test_secure_create_requires_fresh_valid_credentials() -> None:
    """Credentials reuse the existing NAS validator and never appear in read state."""
    secure = {**_draft(), "nas_secure": True}
    with pytest.raises(ConfigurationError):
        nas_share_create_payload(_empty(), secure)
    secure.update(nas_user_name="share-user", nas_user_pwd="Synthetic-Pass-1")
    payload = nas_share_create_payload(_empty(), secure)
    assert payload["nas_user_pwd"] == "Synthetic-Pass-1"
    with pytest.raises(ConfigurationError):
        nas_share_create_payload(_empty(), {**secure, "nas_user_pwd": "[REDACTED]"})


def test_creation_verifier_requires_fresh_id_and_exact_readable_fields() -> None:
    """HTTP success, an unchanged sentinel, or the wrong path never proves creation."""
    before, changes = _empty(), _draft()
    after = {**before, **nas_share_create_payload(before, changes), "sid": "7"}
    assert verify_nas_share_creation(before, changes, after)
    assert not verify_nas_share_creation(before, changes, {**after, "sid": "-1"})
    assert not verify_nas_share_creation(
        before, changes, {**after, "nas_folder_name": "/Different"}
    )
    assert not verify_nas_share_creation(before, changes, {"status": "ok"})


@pytest.mark.parametrize("path", ["relative", "/Disk/../Private", "/", "/" + "x" * 512])
def test_invalid_new_share_path_rejected(path: str) -> None:
    """No path normalization, directory creation or traversal is hidden in save."""
    with pytest.raises(ConfigurationError):
        NAS_CREATE_SETTINGS[0].build(_empty(), {**_draft(), "nas_folder_name": path})
