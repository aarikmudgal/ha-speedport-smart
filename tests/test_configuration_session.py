"""Offline coverage for bounded, requester-isolated configuration approvals."""

from __future__ import annotations

import secrets
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

OWNER = ("admin", "browser-session")
RAW = {"enabled": "0"}


def contract(index: int) -> SettingsContract:
    """Return a distinct synthetic form without any router transport."""
    return SettingsContract(
        f"synthetic_form_{index}",
        "Synthetic form",
        "Testing",
        "data/Example.json",
        "html/content/config/example.html",
        (boolean("enabled", "Enabled"),),
    )


async def fill(
    session: ConfigurationSession,
    clock: list[float],
    owners: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Admit successful synthetic reads one second apart."""
    results = []
    for index, owner in enumerate(owners):
        clock[0] = float(index)
        results.append(
            await session.read(contract(index), owner, AsyncMock(return_value=RAW))
        )
    return results


async def test_same_requester_can_browse_more_than_32_forms_within_ttl() -> None:
    """New valid forms replace only the oldest approvals, never grow the map."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    results = await fill(session, clock, [OWNER] * 40)
    assert clock[0] < 120
    assert len(session._grants) == 32  # noqa: SLF001
    assert set(session._grants) == {item["revision"] for item in results[8:]}  # noqa: SLF001
    assert all(item["expires_in"] == 120 for item in results)

    read = AsyncMock(return_value=RAW)
    write = AsyncMock()
    for index in range(8):
        with pytest.raises(ConfigurationError, match="stale_settings"):
            await session.save(
                contract(index),
                OWNER,
                results[index]["revision"],
                {"enabled": True},
                confirmed=True,
                confirmation_text=contract(index).confirmation,
                read=read,
                write=write,
            )
    read.assert_not_awaited()
    write.assert_not_awaited()
    for index in range(8, 40):
        await session.consume(
            contract(index),
            OWNER,
            results[index]["revision"],
            {"enabled": True},
            confirmed=True,
            confirmation_text=contract(index).confirmation,
            read=read,
        )
    assert read.await_count == 32
    assert not session._grants  # noqa: SLF001


@pytest.mark.parametrize(
    "other", [("different-admin", OWNER[1]), (OWNER[0], "different-session")]
)
async def test_capacity_evicts_only_exact_requester_even_when_other_grants_older(
    other: tuple[str, str],
) -> None:
    """Neither a shared user nor a shared session permits cross-owner eviction."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    results = await fill(session, clock, [other] * 31 + [OWNER])
    before = dict(session._grants)  # noqa: SLF001
    clock[0] = 32.0
    latest = await session.read(contract(32), OWNER, AsyncMock(return_value=RAW))
    assert len(session._grants) == 32  # noqa: SLF001
    assert results[31]["revision"] not in session._grants  # noqa: SLF001
    for previous in results[:31]:
        key = previous["revision"]
        assert session._grants[key] is before[key]  # noqa: SLF001
    assert latest["revision"] in session._grants  # noqa: SLF001


async def test_full_capacity_without_requester_grant_retains_typed_error() -> None:
    """A new requester cannot invalidate any other administrator's approval."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    await fill(session, clock, [("other", "session")] * 32)
    before = dict(session._grants)  # noqa: SLF001
    clock[0] = 32.0
    with pytest.raises(ConfigurationError, match="too_many_editors"):
        await session.read(contract(32), OWNER, AsyncMock(return_value=RAW))
    assert session._grants == before  # noqa: SLF001


@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.parametrize("failure", ["values", "fingerprint", "choices", "token"])
async def test_failed_read_preparation_never_revokes_existing_valid_grants(
    failure: str,
    *,
    replacement: bool,
) -> None:
    """Prepare values, revision context, response choices and token atomically."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    await fill(session, clock, [OWNER] * 32)
    before = dict(session._grants)  # noqa: SLF001
    clock[0] = 32.0
    spec = contract(0 if replacement else 32)
    raw = RAW
    if failure == "values":
        raw = {"enabled": "invalid"}
    elif failure == "fingerprint":
        spec = replace(spec, revision_values=lambda _raw: {"unserializable": object()})
    elif failure == "choices":
        spec = replace(
            spec,
            fields=(SettingsField("enabled", "Enabled", "enum", dynamic_choices=True),),
            field_choices=Mock(
                side_effect=[
                    {"enabled": (("0", "Disabled"),)},
                    {"enabled": (("0", "Disabled"),)},
                    {"enabled": (("0", "Disabled"),)},
                    ConfigurationError("invalid_settings_choices"),
                ]
            ),
        )
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.secrets.token_hex",
            **(
                {"side_effect": RuntimeError("synthetic token failure")}
                if failure == "token"
                else {"wraps": secrets.token_hex}
            ),
        ),
        pytest.raises(
            (ConfigurationError, TypeError, RuntimeError),
            match={
                "values": "invalid_settings",
                "fingerprint": "not JSON serializable",
                "choices": "invalid_settings_choices",
                "token": "synthetic token failure",
            }[failure],
        ),
    ):
        await session.read(spec, OWNER, AsyncMock(return_value=raw))
    assert session._grants == before  # noqa: SLF001


async def test_expiry_pruning_frees_capacity_without_evicting_active_other_owner() -> (
    None
):
    """Expired approvals disappear while all still-live approvals remain exact."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    results = await fill(session, clock, [("other", "session")] * 32)
    clock[0] = 120.0
    newest = await session.read(contract(32), OWNER, AsyncMock(return_value=RAW))
    assert len(session._grants) == 32  # noqa: SLF001
    assert results[0]["revision"] not in session._grants  # noqa: SLF001
    expected = {item["revision"] for item in results[1:]} | {newest["revision"]}
    assert set(session._grants) == expected  # noqa: SLF001


async def test_read_pacing_still_applies_at_capacity_before_any_io() -> None:
    """Eviction cannot bypass the existing one-second admission limit."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    await fill(session, clock, [OWNER] * 32)
    before = dict(session._grants)  # noqa: SLF001
    read = AsyncMock(return_value=RAW)
    with pytest.raises(ConfigurationError, match="rate_limited"):
        await session.read(contract(32), OWNER, read)
    read.assert_not_awaited()
    assert session._grants == before  # noqa: SLF001


async def test_new_capacity_grant_can_save_once_and_never_replay() -> None:
    """Eviction changes only admission, not confirmation or one-shot writes."""
    clock = [0.0]
    session = ConfigurationSession(clock=lambda: clock[0])
    await fill(session, clock, [OWNER] * 32)
    clock[0] = 32.0
    spec = contract(32)
    loaded = await session.read(spec, OWNER, AsyncMock(return_value=RAW))
    read = AsyncMock(side_effect=[RAW, {"enabled": "1"}])
    write = AsyncMock()
    result = await session.save(
        spec,
        OWNER,
        loaded["revision"],
        {"enabled": True},
        confirmed=True,
        confirmation_text=spec.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once_with(RAW, {"enabled": True})
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            spec,
            OWNER,
            loaded["revision"],
            {"enabled": True},
            confirmed=True,
            confirmation_text=spec.confirmation,
            read=read,
            write=write,
        )
    assert read.await_count == 2
    assert write.await_count == 1
