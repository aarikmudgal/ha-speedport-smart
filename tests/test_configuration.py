"""Offline proof of the closed configuration field and transaction boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.api import (
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
)
from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    normalize_configuration_payload,
    settings_contracts,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

OWNER = ("admin", "session")


def test_basic_field_metadata_and_no_private_values() -> None:
    """Metadata is static; aliases and booleans have exact wire semantics."""
    contract = settings_contracts()["telephony_hd_voice"]
    assert contract.read({"hdvoice": "1", "password": "private"}) == {"hdvoice": True}
    assert contract.build({"hdvoice": "0"}, {"hdvoice": True}) == {"hdvoice": "1"}
    assert "private" not in repr(contract.metadata())
    assert not contract.metadata()["live_write_verified"]


@pytest.mark.parametrize("value", [1, "1", None, [], {}, "true"])
def test_boolean_does_not_coerce_user_input(value: object) -> None:
    """Only actual JSON booleans may become checkbox writes."""
    with pytest.raises(ConfigurationError):
        boolean("x", "X").validate(value)


@pytest.mark.parametrize("changes", [{}, {"extra": "x"}, {"hdvoice": "1"}])
def test_extra_missing_and_coerced_fields_rejected(changes: dict[str, object]) -> None:
    """No arbitrary wire key can pass through a form."""
    with pytest.raises(ConfigurationError):
        settings_contracts()["telephony_hd_voice"].build({"hdvoice": "0"}, changes)


@pytest.mark.parametrize(
    "value",
    ["**", "••••", "", "with\nnewline", "with\x7fdelete", "[REDACTED]", "<redacted>"],
)
def test_secret_masks_and_control_characters_rejected(value: str) -> None:
    """Masked read values are never replayed as credentials."""
    with pytest.raises(ConfigurationError):
        SettingsField("password", "Password", "secret").validate(value)


async def test_confirmed_save_and_readback_without_replay() -> None:
    """A complete transaction makes exactly one mutation attempt."""
    contract = settings_contracts()["telephony_hd_voice"]
    session = ConfigurationSession()
    read = AsyncMock(side_effect=[{"hdvoice": "0"}, {"hdvoice": "0"}, {"hdvoice": "1"}])
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    assert len(result["revision"]) == 48
    assert result["values"] == {"hdvoice": False}
    saved = await session.save(
        contract,
        OWNER,
        result["revision"],
        {"hdvoice": True},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert saved == {"status": "verified"}
    write.assert_awaited_once_with({"hdvoice": "0"}, {"hdvoice": True})
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )


@pytest.mark.parametrize(
    ("acknowledgement", "expected"),
    [
        ("status_ok", {"status": "reconnect_required"}),
        (
            "readback",
            {"status": "outcome_unknown", "verification": "reconnect_required"},
        ),
    ],
)
async def test_reconnect_settings_do_not_invent_positive_acknowledgement(
    acknowledgement: str, expected: dict[str, str]
) -> None:
    """No old-address read, duplicate POST or accepted-state claim after disconnect."""
    contract = replace(
        settings_contracts()["telephony_hd_voice"],
        acknowledgement=acknowledgement,
        readback_policy="reconnect_required",
    )
    session = ConfigurationSession()
    read = AsyncMock(return_value={"hdvoice": "0"})
    write = AsyncMock()
    loaded = await session.read(contract, OWNER, read)
    result = await session.save(
        contract,
        OWNER,
        loaded["revision"],
        {"hdvoice": True},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result == expected
    assert read.await_count == 2
    write.assert_awaited_once()


@pytest.mark.parametrize(
    ("requester", "confirmation", "confirmed"),
    [
        (("different", "session"), "SAVE SETTINGS", True),
        (("admin", "other-session"), "SAVE SETTINGS", True),
        (OWNER, "wrong", True),
        (OWNER, "SAVE SETTINGS", False),
    ],
)
async def test_owner_and_confirmation_are_server_enforced(
    requester: tuple[str, str], confirmation: str, *, confirmed: bool
) -> None:
    """A form cannot be submitted by another user/session or without confirmation."""
    contract = settings_contracts()["telephony_hd_voice"]
    session = ConfigurationSession()
    read = AsyncMock(return_value={"hdvoice": "0"})
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    with pytest.raises(ConfigurationError):
        await session.save(
            contract,
            requester,
            result["revision"],
            {"hdvoice": True},
            confirmed=confirmed,
            confirmation_text=confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_external_change_rejects_save() -> None:
    """Router changes since form loading require a new explicit review."""
    contract = settings_contracts()["telephony_hd_voice"]
    session = ConfigurationSession()
    read = AsyncMock(side_effect=[{"hdvoice": "0"}, {"hdvoice": "1"}])
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_timeout_consumes_revision_without_retry() -> None:
    """A timeout after sending cannot trigger an automatic duplicate write."""
    contract = settings_contracts()["telephony_hd_voice"]
    session = ConfigurationSession()
    read = AsyncMock(return_value={"hdvoice": "0"})
    write = AsyncMock(side_effect=SpeedportConnectionError("private response"))
    result = await session.read(contract, OWNER, read)
    with pytest.raises(ConfigurationError, match="action_outcome_unknown") as error:
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    assert "private" not in str(error.value)
    write.assert_awaited_once()


async def test_secret_read_and_revision_do_not_store_secret() -> None:
    """Private credentials are not retained in the editor grant or read response."""
    contract = SettingsContract(
        "example",
        "Example",
        "Testing",
        "data/Example.json",
        "html/content/config/example.html",
        (
            boolean("enabled", "Enabled"),
            SettingsField("password", "Password", "secret"),
        ),
    )
    session = ConfigurationSession()
    read = AsyncMock(return_value={"enabled": "1", "password": "private-secret"})
    result = await session.read(contract, OWNER, read)
    assert result["values"] == {"enabled": True}
    assert "private-secret" not in repr(vars(session))
    write = AsyncMock()
    assert await session.save(
        contract,
        OWNER,
        result["revision"],
        {"password": "new-secret"},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "secret_unverified"}


async def test_expiry_and_unload_revoke_editor() -> None:
    """A long-open or unloaded form cannot later perform a write."""
    now = [0.0]
    session = ConfigurationSession(clock=lambda: now[0])
    contract = settings_contracts()["telephony_hd_voice"]
    read = AsyncMock(return_value={"hdvoice": "0"})
    first = await session.read(contract, OWNER, read)
    now[0] = 121.0
    second = await session.read(contract, OWNER, read)
    session.clear()
    write = AsyncMock()
    for loaded in (first, second):
        with pytest.raises(ConfigurationError, match="stale_settings"):
            await session.save(
                contract,
                OWNER,
                loaded["revision"],
                {"hdvoice": True},
                confirmed=True,
                confirmation_text=contract.confirmation,
                read=read,
                write=write,
            )
    write.assert_not_awaited()


@pytest.mark.parametrize("hidden", ["hidden_dependency", "password"])
async def test_revision_binds_hidden_dependencies_without_storing_values(
    hidden: str,
) -> None:
    """A hidden prerequisite or preserved secret change requires fresh consent."""
    contract = SettingsContract(
        "hidden_form",
        "Hidden form",
        "Testing",
        "data/Example.json",
        "html/content/config/example.html",
        (
            boolean("enabled", "Enabled"),
            SettingsField("password", "Password", "secret"),
        ),
        revision_fields=("hidden_dependency",),
    )
    raw = {
        "enabled": "1",
        "hidden_dependency": "private-context",
        "password": "private-key",
    }
    session = ConfigurationSession()
    read = AsyncMock(side_effect=[raw, {**raw, hidden: "different-private-value"}])
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    assert "private" not in repr(vars(session))
    assert "private" not in repr(result)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"enabled": False},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_derived_payload_fields_are_verified() -> None:
    """Secondary fields forced by the firmware builder are expected, not failures."""

    def builder(
        _raw: Mapping[str, Any], _changes: Mapping[str, Any]
    ) -> dict[str, str | int | bool]:
        return {"enabled": "1", "display": "0"}

    contract = SettingsContract(
        "derived_form",
        "Derived form",
        "Testing",
        "data/Example.json",
        "html/content/config/example.html",
        (boolean("enabled", "Enabled"), boolean("display", "Display")),
        builder=builder,
    )
    session = ConfigurationSession()
    before = {"enabled": "0", "display": "1"}
    read = AsyncMock(side_effect=[before, before, {"enabled": "1", "display": "0"}])
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    assert await session.save(
        contract,
        OWNER,
        result["revision"],
        {"enabled": True},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()


async def test_clear_during_read_cannot_resurrect_grant() -> None:
    """An unloaded session cannot gain an editor from an older pending read."""
    session = ConfigurationSession()
    contract = settings_contracts()["telephony_hd_voice"]

    async def read() -> dict[str, str]:
        session.clear()
        return {"hdvoice": "0"}

    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.read(contract, OWNER, read)
    assert not vars(session)["_grants"]


@pytest.mark.parametrize("reason", ["unload", "expiry"])
async def test_clear_or_expiry_during_preflight_prevents_write(reason: str) -> None:
    """A previously valid revision cannot outlive a slow preflight or unload."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    contract = settings_contracts()["telephony_hd_voice"]
    result = await session.read(
        contract, OWNER, AsyncMock(return_value={"hdvoice": "0"})
    )

    async def read() -> dict[str, str]:
        if reason == "unload":
            session.clear()
        else:
            clock[0] = 121.0
        return {"hdvoice": "0"}

    write = AsyncMock()
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_clear_after_write_stops_readbacks_without_claiming_success() -> None:
    """Unload cannot undo a sent request or validate it using a new session."""
    session = ConfigurationSession()
    contract = settings_contracts()["telephony_hd_voice"]
    read = AsyncMock(return_value={"hdvoice": "0"})
    result = await session.read(contract, OWNER, read)

    async def write(_raw: Mapping[str, Any], _changes: Mapping[str, Any]) -> None:
        session.clear()

    with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    assert read.await_count == 2


async def test_explicit_rejection_preserves_error_meaning_and_never_replays() -> None:
    """A known rejected action is distinguished from an uncertain sent action."""
    session = ConfigurationSession()
    contract = settings_contracts()["telephony_hd_voice"]
    read = AsyncMock(return_value={"hdvoice": "0"})
    write = AsyncMock(side_effect=SpeedportCommandRejectedError("PRIVATE RESPONSE"))
    result = await session.read(contract, OWNER, read)
    with pytest.raises(ConfigurationError, match="command_rejected") as raised:
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    assert "PRIVATE" not in str(raised.value)
    write.assert_awaited_once()
    assert read.await_count == 2


async def test_readback_failure_never_replays_post() -> None:
    """Successful ACK without matching state remains unverified after bounded reads."""
    session = ConfigurationSession()
    contract = settings_contracts()["telephony_hd_voice"]
    read = AsyncMock(return_value={"hdvoice": "0"})
    write = AsyncMock()
    result = await session.read(contract, OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            contract,
            OWNER,
            result["revision"],
            {"hdvoice": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
    assert read.await_count == 6


def test_duplicate_scalar_normalization_does_not_guess_or_flatten_tables() -> None:
    """Only homogeneous identical scalar arrays represent duplicate var wrappers."""
    raw = {
        "flag": ["1", "1"],
        "count": [2, 2],
        "boolean": [True, True],
        "conflict": ["0", "1"],
        "mixed": [True, 1],
        "empty": [],
        "table": [{"id": "1"}, {"id": "1"}],
        "nested": [["1"], ["1"]],
    }
    normalized = normalize_configuration_payload(raw)
    assert normalized["flag"] == "1"
    assert normalized["count"] == 2
    assert normalized["boolean"] is True
    for key in ("conflict", "mixed", "empty", "table", "nested"):
        assert normalized[key] == raw[key]
    assert raw["flag"] == ["1", "1"]
    for key in ("conflict", "mixed", "empty", "table", "nested"):
        with pytest.raises(ConfigurationError):
            boolean("flag", "Flag").read({"flag": normalized[key]})
