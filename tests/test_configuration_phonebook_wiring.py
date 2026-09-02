"""Private phonebook editor transactions exercised only with fake transports."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook import PHONEBOOK_FIELDS
from custom_components.speedport_smart.configuration_phonebook_lifecycle import (
    phonebook_create_payload,
    phonebook_create_settings,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
    target_settings_ids,
    target_settings_metadata,
)

REQUESTER = ("administrator", "refresh-session")
REFERER = "html/content/phone/phone_book_entries.html"


def books() -> dict[str, Any]:
    """Return five explicitly identified synthetic local books."""
    return {
        "addonlbuchentry": [
            {
                "id": str(book),
                "onlbuch_nr": str(book),
                "onlbuch_name": f"Local {book}",
                "onlbuch_bname": "",
                "onlbuch_sync": "0",
            }
            for book in range(5)
        ]
    }


@pytest.fixture(autouse=True)
def mock_book_membership() -> Iterator[AsyncMock]:
    """Keep every wiring test offline and prove book membership independently."""
    with patch.object(
        SpeedportClient, "_get_json_unlocked", AsyncMock(return_value=books())
    ) as get:
        yield get


def inventory() -> dict[str, Any]:
    """Return a synthetic complete search result."""
    return {
        "status": "ok",
        "num_entries": "1",
        "free_entry_num": "99",
        "addbookentry": [
            {
                "id": "7",
                "name": "Existing",
                "vorname": "Contact",
                "number:1": "00000007",
            }
        ],
    }


def contact() -> dict[str, str]:
    """Return a synthetic complete contact form."""
    return {
        **{field.name: "" for field in PHONEBOOK_FIELDS},
        "name": "Existing",
        "vorname": "Contact",
        "number_p": "00000007",
    }


def before() -> dict[str, Any]:
    """Return explicit empty-book capacity proof."""
    return {
        "phonebook_id": 0,
        "prefix": "",
        "truncated": False,
        "total": 0,
        "free_entries": 100,
        "entries": [],
    }


def after() -> dict[str, Any]:
    """Return independent list and complete new-contact proof."""
    values = phonebook_create_payload(
        before(), {"vorname": "New", "number_p": "00000008"}, phonebook_id=0
    )
    return {
        **before(),
        "total": 1,
        "free_entries": 99,
        "assigned_id": "8",
        "entries": [{"contact_id": "8", "first_name": "New", "number": "00000008"}],
        "created_contact": {
            "phonebook_id": 0,
            "contact_id": "8",
            "contact": {field.name: values[field.name] for field in PHONEBOOK_FIELDS},
        },
    }


def test_registry_requires_explicit_local_target() -> None:
    """The registry cannot invent a contact or local phonebook selection."""
    for setting_id in ("telephony_phonebook_contact", "telephony_phonebook_create"):
        assert setting_id in target_settings_ids()
        assert next(
            item for item in target_settings_metadata() if item["id"] == setting_id
        )["requires_target"]
        with pytest.raises(ConfigurationError, match="settings_target_required"):
            resolve_settings_contract(setting_id)


async def test_existing_detail_query_never_sends_a_save_and_preserves_every_field() -> (
    None
):
    """Only exact fixed list/detail read queries precede an existing editor."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(
        client, "_post_json_unlocked", AsyncMock(side_effect=[inventory(), contact()])
    ) as post:
        result = await client.read_configuration("telephony_phonebook_contact", "0:7")
    assert result == {
        "phonebook_id": 0,
        "contact_id": "7",
        "contact": contact(),
        "book_identity": {"id": "0", "onlbuch_nr": "0", "onlbuch_sync": "0"},
    }
    assert [(call.args[0], call.args[1]) for call in post.await_args_list] == [
        ("data/PhoneBook.json", {"obnr": 0, "search": ""}),
        ("data/PhoneBookEntry.json", {"obnr": 0, "chgid": "7"}),
    ]
    assert all(call.kwargs["referer"] == REFERER for call in post.await_args_list)


async def test_missing_contact_or_missing_field_never_becomes_blank_edit() -> None:
    """Incomplete reads fail closed instead of overwriting unedited data."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with (
        patch.object(
            client,
            "_post_json_unlocked",
            AsyncMock(
                return_value={
                    "status": "ok",
                    "num_entries": "0",
                    "free_entry_num": "100",
                }
            ),
        ) as post,
        pytest.raises(ConfigurationError, match="settings_target_unavailable"),
    ):
        await client.read_configuration("telephony_phonebook_contact", "0:7")
    assert post.await_count == 1
    partial = contact()
    del partial["adresse"]
    with (
        patch.object(
            client, "_post_json_unlocked", AsyncMock(side_effect=[inventory(), partial])
        ),
        pytest.raises(ConfigurationError),
    ):
        await client.read_configuration("telephony_phonebook_contact", "0:7")


async def test_empty_books_list_only_after_explicit_success_and_capacity() -> None:
    """Each offered local book has an explicit complete inventory."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(
        client,
        "_post_json_unlocked",
        AsyncMock(
            return_value={"status": "ok", "num_entries": "0", "free_entry_num": "100"}
        ),
    ) as post:
        result = await client.query_configuration_targets("telephony_phonebook_create")
    assert [item["id"] for item in result["targets"]] == ["0", "1", "2", "3", "4"]
    assert post.await_count == 5
    with (
        patch.object(
            client,
            "_post_json_unlocked",
            AsyncMock(
                return_value={
                    "status": "error",
                    "num_entries": "0",
                    "free_entry_num": "100",
                }
            ),
        ),
        pytest.raises(ConfigurationError, match="settings_inventory_unavailable"),
    ):
        await client.read_configuration("telephony_phonebook_create", "0")


async def test_created_id_is_validated_before_followup_queries() -> None:
    """Missing or unsafe acknowledgement IDs never select a detail query."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(client, "_post_json_unlocked", AsyncMock()) as post:
        for response in ({"status": "ok"}, {"status": "ok", "assignedID": "../"}, None):
            with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
                await client.read_created_phonebook_configuration(
                    "0", before(), response
                )
    post.assert_not_awaited()


async def test_creation_ack_is_not_success_without_exact_independent_readback() -> None:
    """Exact independent readback is required, and revisions remain single-use."""
    contract = phonebook_create_settings("0")
    session = ConfigurationSession()
    read = AsyncMock(return_value=before())
    approval = await session.read(contract, REQUESTER, read)
    write = AsyncMock(return_value={"status": "ok", "assignedID": "8"})
    readback = AsyncMock(return_value=after())
    result = await session.save(
        contract,
        REQUESTER,
        approval["revision"],
        {"vorname": "New", "number_p": "00000008"},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
        readback=readback,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once()
    readback.assert_awaited_once_with(before(), {"status": "ok", "assignedID": "8"})
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            REQUESTER,
            approval["revision"],
            {"vorname": "New"},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
            readback=readback,
        )
    assert write.await_count == 1


async def test_missing_assigned_id_is_unknown_after_one_write_not_retry_loop() -> None:
    """Missing IDs remain unknown and cannot cause repeated contact creation."""
    contract = phonebook_create_settings("0")
    session = ConfigurationSession()
    read = AsyncMock(return_value=before())
    approval = await session.read(contract, REQUESTER, read)
    write = AsyncMock(return_value={"status": "ok"})
    readback = AsyncMock(side_effect=ConfigurationError("action_outcome_unknown"))
    with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
        await session.save(
            contract,
            REQUESTER,
            approval["revision"],
            {"vorname": "New", "number_p": "00000008"},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
            readback=readback,
        )
    write.assert_awaited_once()
    readback.assert_awaited_once()


async def test_malformed_postwrite_proof_is_verification_failure() -> None:
    """Malformed readback after a write must not be reported as an invalid draft."""
    contract = phonebook_create_settings("0")
    session = ConfigurationSession()
    read = AsyncMock(return_value=before())
    approval = await session.read(contract, REQUESTER, read)
    write = AsyncMock(return_value={"status": "ok", "assignedID": "8"})
    malformed = deepcopy(after())
    malformed["created_contact"]["contact"].pop("adresse")
    readback = AsyncMock(return_value=malformed)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            contract,
            REQUESTER,
            approval["revision"],
            {"vorname": "New", "number_p": "00000008"},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
            readback=readback,
        )
    write.assert_awaited_once()
    assert readback.await_count == 4
