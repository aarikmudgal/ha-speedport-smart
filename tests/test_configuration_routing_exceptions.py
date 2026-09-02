"""Synthetic exact existing routing exception controls, without router requests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_routing_exceptions import (
    routing_exception_target_contract,
    routing_exception_target_metadata,
    routing_exception_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_EDIT = routing_exception_target_contract("routing_exception_enabled", "7")
_DELETE = routing_exception_target_contract("routing_exception_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw() -> dict[str, Any]:
    return {
        "except_addmdevice": [
            {
                "sid": "dev-a",
                "mdevice_name": "Example",
                "mdevice_mac": "02-00-00-00-00-01",
            }
        ],
        "addexceptentry": [
            {
                "id": "2",
                "except_name": "Devices",
                "except_status": "1",
                "except_type": "0",
                "sid": {"sid": "dev-a", "mdevice_name": "1"},
            },
            {
                "id": "7",
                "except_name": "Domain",
                "except_status": "1",
                "except_type": "1",
                "except_url": "private.example.invalid",
                "except_port": "443",
            },
        ],
    }


def test_exact_existing_toggle_and_deletion_leave_full_form_context_untouched() -> None:
    """The native direct toggle is distinct from the unproven large creation form."""
    raw = _raw()
    previous = deepcopy(raw)
    assert _EDIT.build(raw, {"except_status": False}) == {"id": "7", "except_status": 0}
    assert _DELETE.build(raw, {"delete_entry": True}) == {
        "id": "7",
        "deleteEntry": "delete",
    }
    assert _EDIT.endpoint == "data/Except.json"
    assert _EDIT.read_endpoint == "data/INetExcept.json"
    assert _EDIT.referer == "html/content/internet/except.html"
    assert _EDIT.acknowledgement == _DELETE.acknowledgement == "readback"
    assert raw == previous
    assert routing_exception_target_rows("routing_exception_enabled", raw)[1] == {
        "id": "7",
        "except_name": "Domain",
    }
    assert len(routing_exception_target_metadata()) == 2
    assert "private.example.invalid" not in str(_EDIT.read(raw))


@pytest.mark.parametrize(
    "changes",
    [
        {"except_status": 0},
        {"except_status": "0"},
        {"except_type": "2"},
        {"except_url": "other.example.invalid"},
        {"id": "2"},
        {"endpoint": "data/Other.json"},
        {"sid": "dev-a"},
    ],
)
def test_unreviewed_edit_and_raw_identity_fields_rejected(
    changes: dict[str, object],
) -> None:
    """Only a typed active flag crosses this exact existing-rule boundary."""
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation", ["duplicate_id", "unknown_type", "missing_compound", "missing_mac"]
)
def test_ambiguous_or_incomplete_current_context_rejected(mutation: str) -> None:
    """Full sibling and device context is required before any minimal mutation."""
    raw = _raw()
    if mutation == "duplicate_id":
        raw["addexceptentry"][1]["id"] = "2"
    elif mutation == "unknown_type":
        raw["addexceptentry"][1]["except_type"] = "6"
    elif mutation == "missing_compound":
        raw["addexceptentry"][0]["sid"].pop("mdevice_name")
    else:
        raw["except_addmdevice"][0].pop("mdevice_mac")
    with pytest.raises(ConfigurationError):
        _EDIT.read(raw)


@pytest.mark.parametrize("action", ["toggle", "delete"])
async def test_real_session_exact_target_and_preserved_sibling_readback(
    action: str,
) -> None:
    """Positive completion must be followed by exact independently observed state."""
    contract = _EDIT if action == "toggle" else _DELETE
    changes = {"except_status": False} if action == "toggle" else {"delete_entry": True}
    before, after = _raw(), _raw()
    if action == "toggle":
        after["addexceptentry"][1]["except_status"] = "0"
    else:
        after["addexceptentry"].pop()
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    altered = deepcopy(after)
    altered["addexceptentry"][0]["except_name"] = "Collateral"
    assert not contract.verifier(before, changes, altered)
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()


def test_revision_binds_destination_and_devices_but_not_link_telemetry() -> None:
    """A rule changed elsewhere cannot inherit an older grant."""
    raw, changed = _raw(), _raw()
    changed["except_addmdevice"][0]["mdevice_rssi"] = "-90"
    assert _EDIT.revision(raw) == _EDIT.revision(changed)
    changed["addexceptentry"][1]["except_url"] = "other.example.invalid"
    assert _EDIT.revision(raw) != _EDIT.revision(changed)
