"""Private password form; only the isolated password owner may execute it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .configuration import ConfigurationError, SettingsContract, SettingsField, boolean
from .models import normalize_status
from .password_change import (
    PASSWORD_CHANGE_CONFIRMATION,
    PASSWORD_CHANGE_ENDPOINT,
    PASSWORD_CHANGE_ID,
    PASSWORD_CHANGE_REFERER,
    PasswordChangeIdentity,
    PasswordChangeRequest,
    password_change_identity,
    password_change_metadata,
)


def password_configuration_context(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Use a fresh serial-bearing status, never the host as same-router proof."""
    info = normalize_status(dict(raw)).info
    context = {
        "model": info.model,
        "firmware": info.firmware,
        "router_identifier": info.serial_number,
    }
    password_configuration_identity(context)
    return context


def password_configuration_identity(raw: Mapping[str, Any]) -> PasswordChangeIdentity:
    """Bind exact firmware and a privately held router serial."""
    return password_change_identity(
        model=raw.get("model"),
        firmware=raw.get("firmware"),
        router_identifier=raw.get("router_identifier"),
    )


def password_configuration_request(
    raw: Mapping[str, Any], changes: Mapping[str, Any]
) -> PasswordChangeRequest:
    """Create a private one-use draft only after complete explicit user input."""
    if set(changes) != {"password", "new_password", "new_pw_repeat", "recovery_ready"}:
        raise ConfigurationError("invalid_settings")
    return PasswordChangeRequest(
        {name: changes[name] for name in ("password", "new_password", "new_pw_repeat")},
        identity=password_configuration_identity(raw),
        confirmed=True,
        confirmation_text=PASSWORD_CHANGE_CONFIRMATION,
        recovery_ready=changes["recovery_ready"],
    )


def _read(raw: Mapping[str, Any]) -> dict[str, Any]:
    password_configuration_identity(raw)
    return {"recovery_ready": False}


def _build(
    raw: Mapping[str, Any], changes: Mapping[str, Any]
) -> dict[str, str | int | bool]:
    draft = password_configuration_request(raw, changes)
    try:
        # This validates the form only. SpeedportClient.save_configuration rejects
        # this ID, so the payload cannot bypass isolated old/new login proofs.
        return {
            name: str(changes[name])
            for name in ("password", "new_password", "new_pw_repeat")
        }
    finally:
        draft.clear()


PASSWORD_SETTINGS: Final = (
    SettingsContract(
        PASSWORD_CHANGE_ID,
        "Change router password",
        "System",
        PASSWORD_CHANGE_ENDPOINT,
        PASSWORD_CHANGE_REFERER,
        (
            SettingsField(
                "password", "Current router password", "secret", minimum=1, maximum=32
            ),
            SettingsField(
                "new_password", "New router password", "secret", minimum=8, maximum=32
            ),
            SettingsField(
                "new_pw_repeat", "Repeat new password", "secret", minimum=8, maximum=32
            ),
            boolean(
                "recovery_ready",
                "I have saved the new password securely and can recover access",
            ),
        ),
        reader=_read,
        builder=_build,
        read_endpoint="data/Status.json",
        revision_fields=("model", "firmware", "router_identifier"),
        confirmation=PASSWORD_CHANGE_CONFIRMATION,
        warning=password_change_metadata()["warning"],
        payload_keys=frozenset({"password", "new_password", "new_pw_repeat"}),
    ),
)
