"""Offline two-stage phonebook wiring: explicit writes and private approval state."""

# ruff: noqa: D103, SLF001

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.speedport_smart.api import SpeedportProtocolError
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook_link import (
    LINK_SETTING_ID,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
)
from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.phonebook_link_flow import (
    begin_online_phonebook_link,
    finish_online_phonebook_link,
)
from custom_components.speedport_smart.phonebook_link_session import (
    OnlinePhonebookSession,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

REQUESTER = ("administrator", "refresh-session")
USERNAME = "private-account-user"
PASSWORD = "private-account-password"  # noqa: S105 - synthetic fixture only


def _local(book: int = 2) -> dict[str, Any]:
    return {
        "phonebook_id": book,
        "prefix": "",
        "entries": [{"contact_id": "1", "first_name": "Private contact"}],
        "total": 1,
        "free_entries": 999,
        "truncated": False,
    }


def _raw() -> dict[str, Any]:
    return {
        "addonlbuchentry": [
            {
                "id": "book-a",
                "onlbuch_nr": "2",
                "onlbuch_name": "Family",
                "onlbuch_bname": "",
                "onlbuch_domain": "0",
                "onlbuch_sync": "0",
            }
        ],
        "local_inventory": _local(),
    }


@pytest.fixture
def context() -> SimpleNamespace:
    raw = _raw()
    clock = [0.0]
    user = SimpleNamespace(id=REQUESTER[0], is_active=True, is_admin=True)
    auth = SimpleNamespace(
        async_get_refresh_token=MagicMock(return_value=SimpleNamespace(user=user))
    )
    entries = SimpleNamespace(async_get_entry=MagicMock())
    client = SimpleNamespace(
        read_configuration=AsyncMock(return_value=raw),
        save_configuration=AsyncMock(
            return_value={
                "status": "ok",
                "assignedID": "book-a",
                "sum_onlineContacts": "4",
            }
        ),
        _phonebook_transfer_inventory=AsyncMock(),
        _post_ephemeral_action=AsyncMock(return_value={"status": "ok"}),
    )
    hub = SimpleNamespace(
        _entry_id="entry-a",
        _closed=False,
        hass=SimpleNamespace(auth=auth, config_entries=entries),
        client=client,
        _configuration_session=ConfigurationSession(clock=lambda: clock[0]),
        online_phonebook_session=OnlinePhonebookSession(clock=lambda: clock[0]),
        invalidate_file_transfer_state=MagicMock(),
    )
    entry = SimpleNamespace(
        domain=DOMAIN, state=ConfigEntryState.LOADED, runtime_data=hub
    )
    entries.async_get_entry.return_value = entry
    fresh = deepcopy(raw)
    fresh["addonlbuchentry"][0].update(
        onlbuch_bname=USERNAME, onlbuch_domain="1", onlbuch_sync="1"
    )
    client._phonebook_transfer_inventory.return_value = {
        "books": fresh,
        "content": fresh["local_inventory"],
    }
    return SimpleNamespace(
        hub=hub,
        client=client,
        user=user,
        auth=auth,
        entry=entry,
        clock=clock,
        raw=raw,
        fresh=fresh,
    )


async def _read(context: SimpleNamespace) -> str:
    contract = resolve_settings_contract(LINK_SETTING_ID, "book-a")
    read = await context.hub._configuration_session.read(
        contract, REQUESTER, context.client.read_configuration
    )
    assert read["values"] == {"onlbuch_domain": "0"}
    assert USERNAME not in str(read)
    assert PASSWORD not in str(read)
    return read["revision"]


async def _begin(context: SimpleNamespace, revision: str | None = None) -> dict:
    return await begin_online_phonebook_link(
        context.hub,
        resolve_settings_contract(LINK_SETTING_ID, "book-a"),
        "book-a",
        REQUESTER,
        revision or await _read(context),
        {"onlbuch_bname": USERNAME, "onlbuch_domain": "1", "onlbuch_pwd": PASSWORD},
        confirmed=True,
        confirmation_text="AUTHENTICATE ONLINE PHONEBOOK",
    )


async def _finish(context: SimpleNamespace, pending: dict, **overrides: Any) -> dict:
    return await finish_online_phonebook_link(
        context.hub,
        **{
            "requester": REQUESTER,
            "pending_link": pending["pending_link"],
            "target_id": pending["target_id"],
            "phonebook_id": pending["phonebook_id"],
            "confirmed": True,
            "confirmation_text": "MERGE ONLINE PHONEBOOK CONTACTS",
            "merge_existing": True,
            **overrides,
        },
    )


async def test_first_stage_is_one_post_no_automatic_merge_and_no_private_result(
    context: SimpleNamespace,
) -> None:
    revision = await _read(context)
    result = await _begin(context, revision)
    assert result["status"] == "pending_confirmation"
    assert result["online_contacts"] == 4
    assert result["local_contacts"] == 1
    assert all(value not in str(result) for value in (USERNAME, PASSWORD, "Private"))
    context.client.save_configuration.assert_awaited_once()
    context.client._post_ephemeral_action.assert_not_awaited()
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await _begin(context, revision)
    assert context.client.save_configuration.await_count == 1


async def test_second_stage_is_separately_confirmed_once_and_never_claims_sync(
    context: SimpleNamespace,
) -> None:
    pending = await _begin(context)
    captured: list[dict] = []

    async def post(endpoint: str, payload: dict, **kwargs: Any) -> dict:
        assert endpoint == "data/PhoneOnlbuch.json"
        assert kwargs["referer"] == "html/content/phone/phone_book_basic.html"
        assert payload == {
            "id": "book-a",
            "join_availEntries": True,
            "sum_onlineContacts": "4",
        }
        captured.append(deepcopy(payload))
        return {"status": "ok"}

    context.client._post_ephemeral_action.side_effect = post
    assert await _finish(context, pending) == {
        "status": "outcome_unknown",
        "verification": "manual_required",
    }
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await _finish(context, pending)
    assert len(captured) == 1
    context.hub.invalidate_file_transfer_state.assert_called_once()


@pytest.mark.parametrize(
    "override",
    [
        {"target_id": "book-b"},
        {"phonebook_id": 3},
        {"requester": ("other-admin", REQUESTER[1])},
    ],
)
async def test_foreign_context_rejected_before_private_inventory_read(
    context: SimpleNamespace,
    override: dict,
) -> None:
    pending = await _begin(context)
    with pytest.raises(ConfigurationError):
        await _finish(context, pending, **override)
    context.client._phonebook_transfer_inventory.assert_not_awaited()
    context.client._post_ephemeral_action.assert_not_awaited()


@pytest.mark.parametrize("change", ["contact", "book", "user", "domain", "expiry"])
async def test_stale_context_never_sends_continuation(
    context: SimpleNamespace,
    change: str,
) -> None:
    pending = await _begin(context)
    if change == "expiry":
        context.clock[0] = 121
    elif change == "contact":
        context.fresh["local_inventory"]["entries"][0]["first_name"] = "Changed"
    else:
        field = {
            "book": "onlbuch_name",
            "user": "onlbuch_bname",
            "domain": "onlbuch_domain",
        }[change]
        context.fresh["addonlbuchentry"][0][field] = "changed"
    with pytest.raises(ConfigurationError):
        await _finish(context, pending)
    context.client._post_ephemeral_action.assert_not_awaited()


async def test_revocation_during_fresh_read_burns_grant_before_mutation(
    context: SimpleNamespace,
) -> None:
    pending = await _begin(context)
    inventory = context.client._phonebook_transfer_inventory.return_value

    async def read(_book: int) -> dict:
        context.user.is_active = False
        return inventory

    context.client._phonebook_transfer_inventory.side_effect = read
    with pytest.raises(ConfigurationError, match="administrator_required"):
        await _finish(context, pending)
    context.user.is_active = True
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await _finish(context, pending)
    context.client._post_ephemeral_action.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [RuntimeError("private response"), asyncio.CancelledError()]
)
async def test_failed_or_cancelled_second_post_is_never_replayed(
    context: SimpleNamespace,
    failure: BaseException,
) -> None:
    pending = await _begin(context)
    context.client._post_ephemeral_action.side_effect = failure
    with pytest.raises(type(failure)):
        await _finish(context, pending)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await _finish(context, pending)
    context.client._post_ephemeral_action.assert_awaited_once()
    context.hub.invalidate_file_transfer_state.assert_called_once()


async def test_first_stage_revocation_always_clears_owned_credentials(
    context: SimpleNamespace,
) -> None:
    owned = {"onlbuch_bname": USERNAME, "onlbuch_pwd": PASSWORD, "onlbuch_domain": "1"}
    context.hub._configuration_session = SimpleNamespace(
        consume=AsyncMock(return_value=(context.raw, {}, owned)), clear=MagicMock()
    )
    context.user.is_admin = False
    with pytest.raises(ConfigurationError, match="administrator_required"):
        await _begin(context, "approved-revision")
    assert owned == {}
    context.client.save_configuration.assert_not_awaited()


async def test_production_resolver_binds_equal_empty_books_to_exact_target() -> None:
    raw = _raw()
    raw["local_inventory"].update(entries=[], total=0, free_entries=1000)
    raw["addonlbuchentry"].append(
        {**raw["addonlbuchentry"][0], "id": "book-b", "onlbuch_nr": "3"}
    )
    other = deepcopy(raw)
    other["local_inventory"]["phonebook_id"] = 3
    session = ConfigurationSession()
    original = resolve_settings_contract(LINK_SETTING_ID, "book-a")
    target = resolve_settings_contract(LINK_SETTING_ID, "book-b")
    grant = await session.read(original, REQUESTER, AsyncMock(return_value=raw))
    assert original.target_scope == "book-a"
    assert target.target_scope == "book-b"
    read = AsyncMock(return_value=other)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.consume(
            target,
            REQUESTER,
            grant["revision"],
            {"onlbuch_domain": "1"},
            confirmed=True,
            confirmation_text=target.confirmation,
            read=read,
        )
    read.assert_not_awaited()


async def test_session_loss_revokes_settings_and_pending_link_approvals(
    context: SimpleNamespace,
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    pending = await _begin(context)
    context.clock[0] = 2
    revision = await _read(context)
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry-a", entry_id="entry-a"
    )
    hub._configuration_session = context.hub._configuration_session
    hub.online_phonebook_session = context.hub.online_phonebook_session
    hub._publish_authenticated_failure(
        SpeedportProtocolError("Synthetic session loss"), force_unavailable=True
    )
    # Recovering management access cannot revive approval from the old session.
    hub._set_management_access("available")
    assert revision not in hub._configuration_session._grants
    with pytest.raises(ConfigurationError, match="stale_settings"):
        hub.online_phonebook_session.context(
            pending["pending_link"], requester=REQUESTER, entry_id="entry-a"
        )
