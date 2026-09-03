"""Complete local contact edits verified with synthetic offline detail responses."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phonebook import (
    PHONEBOOK_FIELDS,
    parse_phonebook_target,
    phonebook_contact_metadata,
    phonebook_contact_settings,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession


def _raw() -> dict[str, Any]:
    return {
        "phonebook_id": 0,
        "contact_id": "7",
        "contact": {
            "name": "Example",
            "vorname": "Sam",
            "number_p": "+49 00000001",
            "number_a": "",
            "number_m": "",
            "number_n": "",
            "adresse": "Example Street 1",
            "plz": "00000",
            "ort": "Example City",
            "geburtstag": "29.02.2000",
        },
    }


def test_static_metadata_requires_existing_local_target() -> None:
    """No contact values, online books or create sentinels appear in metadata."""
    metadata = phonebook_contact_metadata()
    assert metadata.pop("requires_target") is True
    assert metadata == phonebook_contact_settings("0:7").metadata()
    assert "Sam" not in str(metadata)
    assert parse_phonebook_target("4:Abc_7") == (4, "Abc_7")


@pytest.mark.parametrize(
    "target", ["6:7", "100:7", "0:-1", "0", "0:../7", "0:7:8", "00:7", 7, None]
)
def test_invalid_or_online_target_cannot_be_edited(target: object) -> None:
    """Only local indexes 0-4 and an exact existing contact ID are accepted."""
    with pytest.raises(ConfigurationError):
        phonebook_contact_settings(target)  # type: ignore[arg-type]


def test_edit_preserves_every_field_and_uses_obnr_id_not_query_keys() -> None:
    """Write form is distinct from the fixed obnr/chgid read query."""
    raw = _raw()
    before = deepcopy(raw)
    contract = phonebook_contact_settings("0:7")
    assert contract.build(raw, {"vorname": "Alex"}) == {
        "obnr": 0,
        "id": "7",
        **raw["contact"],
        "vorname": "Alex",
        "number_p": "+4900000001",
    }
    assert raw == before
    assert contract.expected_values is not None
    assert contract.expected_values(raw, {"number_m": "01 23"})["number_m"] == "0123"


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "8"},
        {"obnr": 1},
        {"chgid": "8"},
        {"name": "", "vorname": ""},
        {"number_p": ""},
        {"number_p": "ABC"},
        {"number_p": "++49"},
        {"plz": "ABCDE"},
        {"name": "A" * 17},
        {"adresse": "A" * 41},
        {"geburtstag": "29.02.1900"},
        {"geburtstag": "31.04.2000"},
        {"geburtstag": "01.01.2100"},
        {"geburtstag": "1.1.2000"},
        {"ort": "Bad\nCity"},
    ],
)
def test_invalid_or_incomplete_contact_never_builds(changes: dict[str, Any]) -> None:
    """Exact bounds, required name/number and calendar validity apply before send."""
    with pytest.raises(ConfigurationError):
        phonebook_contact_settings("0:7").build(_raw(), changes)


def test_unknown_empty_address_is_not_silently_cleared() -> None:
    """Optional fields still must exist in a complete current detail response."""
    for name in (field.name for field in PHONEBOOK_FIELDS):
        raw = _raw()
        raw["contact"].pop(name)
        with pytest.raises(ConfigurationError):
            phonebook_contact_settings("0:7").build(raw, {"vorname": "Alex"})


def test_cross_book_or_contact_response_rejected() -> None:
    """The same numeric contact ID in another book cannot authorize this edit."""
    for changes in ({"phonebook_id": 1}, {"phonebook_id": "0"}, {"contact_id": "8"}):
        with pytest.raises(ConfigurationError):
            phonebook_contact_settings("0:7").read({**_raw(), **changes})


@pytest.mark.asyncio
async def test_one_write_then_fresh_complete_contact_verification() -> None:
    """Whitespace normalization is expected; every preserved contact field matches."""
    state = _raw()
    contract = phonebook_contact_settings("0:7")
    session = ConfigurationSession()
    writes = []

    async def read() -> dict[str, Any]:
        return deepcopy(state)

    async def write(raw: dict[str, Any], changes: dict[str, Any]) -> None:
        payload = contract.build(raw, changes)
        writes.append(payload)
        state["contact"] = {
            field.name: payload[field.name] for field in PHONEBOOK_FIELDS
        }

    loaded = await session.read(contract, ("admin", "connection"), read)
    assert await session.save(
        contract,
        ("admin", "connection"),
        loaded["revision"],
        {"number_m": "01 23"},
        confirmed=True,
        confirmation_text="SAVE PHONEBOOK CONTACT",
        read=read,
        write=write,
    ) == {"status": "verified"}
    assert len(writes) == 1
