"""Private call-history integration contracts with synthetic offline histories."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.call_history import CALL_HISTORY_SPECS
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_call_history import (
    CALL_HISTORY_SETTINGS,
    call_history_private_export,
    call_history_private_read,
    call_history_read_source,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_OWNER = ("synthetic-admin", "synthetic-websocket")


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for name, spec in CALL_HISTORY_SPECS.items():
        row = {
            f"{spec.prefix}_date": "02.09.2026",
            f"{spec.prefix}_time": "12:34",
            f"{spec.prefix}_who": "=private-caller",
            f"{spec.prefix}_{spec.local_suffix}": f"private-{name}-line",
        }
        if spec.has_duration:
            row[f"{spec.prefix}_duration"] = "12"
        raw[spec.collection] = [row]
    return raw


@pytest.mark.parametrize("contract", CALL_HISTORY_SETTINGS)
def test_three_exact_native_clear_contracts_without_private_record_fields(
    contract: Any,
) -> None:
    """Category is immutable metadata; no path or raw body can be provided."""
    category = contract.id.removeprefix("call_history_clear_")
    spec = CALL_HISTORY_SPECS[category]
    assert contract.endpoint == spec.clear_endpoint
    assert contract.read_endpoint == "data/PhoneCalls.json"
    assert contract.referer == spec.referer
    assert contract.acknowledgement == "readback"
    assert contract.build(_raw(), {"clear_history": True}) == {
        "action_clearlist": "true"
    }
    assert contract.read(_raw()) == {"clear_history": False}
    assert "private-caller" not in str(contract.read(_raw())) + str(contract.metadata())
    for changes in (
        {"clear_history": False},
        {"clear_history": "true"},
        {"clear_history": 1},
        {"clear_history": True, "category": "missed"},
        {"action_clearlist": "true"},
        {"endpoint": spec.clear_endpoint},
    ):
        with pytest.raises(ConfigurationError):
            contract.build(_raw(), changes)


@pytest.mark.parametrize("contract", CALL_HISTORY_SETTINGS)
@pytest.mark.parametrize("raw", [{}, {"router_state": "OK"}, {"addtakencalls": None}])
def test_absent_selected_history_is_not_an_empty_list(
    contract: Any, raw: dict[str, Any]
) -> None:
    """A page-level global fallback cannot authorize destructive clearing."""
    with pytest.raises(ConfigurationError):
        contract.read(raw)
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"clear_history": True})


@pytest.mark.parametrize("contract", CALL_HISTORY_SETTINGS)
async def test_real_session_clear_requires_exact_explicit_empty_readback(
    contract: Any,
) -> None:
    """The sole POST is followed by independent readback, never an ACK-only result."""
    category = contract.id.removeprefix("call_history_clear_")
    before, after = _raw(), _raw()
    after[CALL_HISTORY_SPECS[category].collection] = []
    read = AsyncMock(side_effect=[before, before, after])
    write = AsyncMock(return_value={})
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert "private-caller" not in str(initial) + repr(vars(session))
    result = await session.save(
        contract,
        _OWNER,
        initial["revision"],
        {"clear_history": True},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once()
    assert read.await_count == 3


@pytest.mark.parametrize("failure", ["missing", "retained", "new_call", "sibling_loss"])
async def test_uncertain_clear_never_retries_the_write(failure: str) -> None:
    """Only GET verification retries are safe after a destructive list clear."""
    contract = CALL_HISTORY_SETTINGS[2]
    before, after = _raw(), _raw()
    after["addtakencalls"] = []
    if failure == "missing":
        after.pop("addtakencalls")
    elif failure == "retained":
        after = deepcopy(before)
    elif failure == "new_call":
        after["addtakencalls"] = deepcopy(before["addtakencalls"])
        after["addtakencalls"][0]["takencalls_time"] = "12:35"
    else:
        after["addmissedcalls"] = []
    read = AsyncMock(side_effect=[before, before, after, after, after, after])
    write = AsyncMock(return_value={"status": "ok"})
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            contract,
            _OWNER,
            initial["revision"],
            {"clear_history": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
    assert read.await_count == 6
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            _OWNER,
            initial["revision"],
            {"clear_history": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


@pytest.mark.parametrize(
    "mutation", ["caller", "new_call", "different_owner", "category"]
)
async def test_grant_binds_private_content_category_and_requester(
    mutation: str,
) -> None:
    """An identical public checkbox cannot transfer a private destructive grant."""
    contract = CALL_HISTORY_SETTINGS[2]
    before, current = _raw(), _raw()
    if mutation == "caller":
        current["addtakencalls"][0]["takencalls_who"] = "changed-private-caller"
    elif mutation == "new_call":
        current["addtakencalls"].append(deepcopy(current["addtakencalls"][0]))
    read, write = AsyncMock(side_effect=[before, current]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    if mutation == "category":
        contract = CALL_HISTORY_SETTINGS[0]
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            ("different-admin", "different-websocket")
            if mutation == "different_owner"
            else _OWNER,
            initial["revision"],
            {"clear_history": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


@pytest.mark.parametrize("category", CALL_HISTORY_SPECS)
def test_private_read_and_local_export_reuse_exact_existing_download_seam(
    category: str,
) -> None:
    """Explicit private output contains only the selected category and inert CSV."""
    raw = _raw()
    previous = deepcopy(raw)
    endpoint, referer = call_history_read_source(category)
    assert endpoint == "data/PhoneCalls.json"
    assert referer == CALL_HISTORY_SPECS[category].referer
    snapshot = call_history_private_read(raw, category)
    assert snapshot["category"] == category
    assert snapshot["total"] == 1
    download = call_history_private_export(raw, category)["private_download"]
    assert download["filename"] == f"Speedport-{category}-calls.csv"
    assert download["media_type"] == "text/csv;charset=utf-8"
    assert "'=private-caller" in download["content"]
    assert f"private-{category}-line" in download["content"]
    for other in set(CALL_HISTORY_SPECS) - {category}:
        assert f"private-{other}-line" not in download["content"]
    assert raw == previous


@pytest.mark.parametrize("category", ["../PhoneCalls.json", "TAKEN", "", None, []])
def test_private_export_selector_is_closed(category: Any) -> None:
    """User strings cannot select an arbitrary router resource or download name."""
    for helper in (call_history_private_read, call_history_private_export):
        with pytest.raises(ConfigurationError):
            helper(_raw(), category)
    with pytest.raises(ConfigurationError):
        call_history_read_source(category)


def test_explicit_empty_history_is_known_but_cannot_be_cleared_again() -> None:
    """An already-empty category never needs a destructive router request."""
    raw = _raw()
    raw["addtakencalls"] = []
    contract = CALL_HISTORY_SETTINGS[2]
    assert contract.read(raw) == {"clear_history": True}
    with pytest.raises(ConfigurationError, match="call_history_already_empty"):
        contract.build(raw, {"clear_history": True})


def test_sibling_additions_are_allowed_but_duplicate_loss_is_not() -> None:
    """Preservation compares complete multisets, not only category row counts."""
    before = _raw()
    before["addmissedcalls"].append(deepcopy(before["addmissedcalls"][0]))
    after = deepcopy(before)
    after["addtakencalls"] = []
    after["adddialedcalls"].append(deepcopy(after["adddialedcalls"][0]))
    contract = CALL_HISTORY_SETTINGS[2]
    assert contract.verifier is not None
    assert contract.verifier(before, {"clear_history": True}, after)
    after["addmissedcalls"].pop()
    assert not contract.verifier(before, {"clear_history": True}, after)
