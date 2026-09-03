"""Synthetic network-rule CRUD proof; never contact or modify a live router."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_network_rules import (
    NETWORK_RULE_SETTINGS,
    NETWORK_RULE_TARGET_SPECS,
    network_rule_target_contract,
    network_rule_target_metadata,
    network_rule_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

if TYPE_CHECKING:
    from custom_components.speedport_smart.configuration import SettingsContract

_CREATE = next(
    item for item in NETWORK_RULE_SETTINGS if item.id == "dns_exception_create"
)
_EDIT = network_rule_target_contract("dns_exception_edit", "7")
_DELETE = network_rule_target_contract("dns_exception_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw() -> dict[str, Any]:
    return {
        "use_dnsrebind": "1",
        "adddnsexcept": [
            {"id": "7", "dns_except": "one.example"},
            {"id": "2", "dns_except": "two.example"},
        ],
        "unrelated_private": "must-not-leak",
    }


def _after(action: str) -> dict[str, Any]:
    raw = _raw()
    if action == "create":
        raw["adddnsexcept"].append({"id": "9", "dns_except": "new.example"})
    elif action == "edit":
        raw["adddnsexcept"][0]["dns_except"] = "new.example"
    else:
        raw["adddnsexcept"].pop(0)
    return raw


def test_static_metadata_and_exact_endpoints() -> None:
    """Expose closed typed contracts without leaking current rule values."""
    for item in network_rule_target_metadata():
        assert item.pop("requires_target") is True
        target = getattr(NETWORK_RULE_TARGET_SPECS[item["id"]], "metadata_target", "7")
        assert item == network_rule_target_contract(item["id"], target).metadata()
        assert item["live_write_verified"] is False
        assert "one.example" not in str(item)
    for contract in (_CREATE, _EDIT, _DELETE):
        assert contract.endpoint == "data/DNSExcept.json"
        assert contract.referer == "html/content/network/dns_rebind.html"
        assert contract.acknowledgement == "status_ok"
    assert set(NETWORK_RULE_TARGET_SPECS) >= {
        "dns_exception_edit",
        "dns_exception_delete",
    }


def test_exact_create_edit_delete_payloads_preserve_source() -> None:
    """Use static new-ID sentinel or exact selected ID, never an ordinal."""
    raw = _raw()
    before = deepcopy(raw)
    assert _CREATE.build(raw, {"dns_except": "New.Example."}) == {
        "id": "-1",
        "dns_except": "new.example",
    }
    assert _EDIT.build(raw, {"dns_except": "New.Example."}) == {
        "id": "7",
        "dns_except": "new.example",
    }
    assert _DELETE.build(raw, {"delete_entry": True}) == {
        "id": "7",
        "deleteEntry": "delete",
    }
    assert raw == before
    assert _CREATE.read(raw) == {"dns_except": ""}
    assert _EDIT.read(raw) == {"dns_except": "one.example"}
    assert _DELETE.read(raw) == {"delete_entry": False}
    assert _DELETE.read(_after("delete")) == {"delete_entry": True}


def test_captured_empty_response_is_valid_only_with_protection_flag() -> None:
    """Support the real empty GET without treating arbitrary missing data as empty."""
    for raw in ({"use_dnsrebind": "0"}, {"use_dnsrebind": "1", "adddnsexcept": []}):
        assert _CREATE.read(raw) == {"dns_except": ""}
        assert _CREATE.build(raw, {"dns_except": "first.example"})["id"] == "-1"
    with pytest.raises(ConfigurationError):
        _CREATE.read({})


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        "",
        ["id"],
        [{"id": "7"}],
        [{"id": "7", "dns_except": "one.example"}] * 2,
    ],
)
def test_malformed_or_duplicate_collection_fails_closed(value: object) -> None:
    """Do not read or build against ambiguous existing rule identities."""
    raw = {**_raw(), "adddnsexcept": value}
    with pytest.raises(ConfigurationError):
        _CREATE.read(raw)
    with pytest.raises(ConfigurationError):
        _EDIT.build(raw, {"dns_except": "new.example"})


def test_singleton_and_target_listing_use_exact_ids() -> None:
    """Handle one normalized row without replacing its ID with its position."""
    raw = {
        "use_dnsrebind": "1",
        "adddnsexcept": {"id": "7", "dns_except": "One.Example."},
    }
    assert network_rule_target_rows("dns_exception_edit", raw) == (
        {"id": "7", "dns_except": "one.example"},
    )
    assert _EDIT.read(raw)["dns_except"] == "one.example"


@pytest.mark.parametrize(
    "target", [None, "", "-1", "01", "../7", "7\n", "2147483648", 7, True]
)
def test_target_identity_is_strict_and_bounded(target: object) -> None:
    """Reject malformed or synthetic target identities at contract creation."""
    with pytest.raises(ConfigurationError):
        network_rule_target_contract("dns_exception_edit", target)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "https://one.example",
        "*.example",
        "192.0.2.1",
        "2001:db8::1",
        "bad name.example",
        "bad\nname.example",
        "-bad.example",
        "bad-.example",
        "a..example",
        "one.example..",
        "x" * 64 + ".example",
        "ä.example",
        True,
        123,
    ],
)
def test_invalid_domains_and_unsupported_syntax_fail_closed(domain: object) -> None:
    """Keep the editor inside the reviewed literal ASCII DNS-name slice."""
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw(), {"dns_except": domain})


@pytest.mark.parametrize("contract", [_CREATE, _EDIT])
def test_duplicate_domain_rejected_case_insensitively(
    contract: SettingsContract,
) -> None:
    """Never add another exception that denotes an existing domain."""
    with pytest.raises(ConfigurationError, match="duplicate_dns_exception"):
        contract.build(_raw(), {"dns_except": "TWO.EXAMPLE."})


def test_firmware_limit_blocks_only_create() -> None:
    """Enforce the ten-entry limit while preserving existing-row administration."""
    raw = {
        "use_dnsrebind": "1",
        "adddnsexcept": [
            {"id": str(index), "dns_except": f"entry{index}.example"}
            for index in range(10)
        ],
    }
    with pytest.raises(ConfigurationError, match="dns_exception_limit"):
        _CREATE.build(raw, {"dns_except": "new.example"})
    assert _EDIT.build(raw, {"dns_except": "new.example"})["id"] == "7"


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"id": "2"},
        {"deleteEntry": "delete"},
        {"dns_except": "new.example", "path": "data/Other.json"},
    ],
)
def test_raw_fields_and_paths_cannot_be_injected(changes: dict[str, object]) -> None:
    """Expose no generic JSON or arbitrary endpoint write path."""
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw(), changes)
    with pytest.raises(ConfigurationError):
        _EDIT.build(_raw(), changes)


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_delete_requires_explicit_typed_true(value: object) -> None:
    """Do not infer deletion from truthiness or unchecked controls."""
    with pytest.raises(ConfigurationError):
        _DELETE.build(_raw(), {"delete_entry": value})


def test_absent_target_never_authorizes_edit_or_delete() -> None:
    """Deletion post-read may show absence, but pre-write still requires identity."""
    raw = _after("delete")
    for contract, changes in (
        (_EDIT, {"dns_except": "new.example"}),
        (_DELETE, {"delete_entry": True}),
    ):
        with pytest.raises(ConfigurationError, match="stale_settings"):
            contract.build(raw, changes)


@pytest.mark.parametrize(
    ("action", "contract", "changes"),
    [
        ("create", _CREATE, {"dns_except": "new.example"}),
        ("edit", _EDIT, {"dns_except": "new.example"}),
        ("delete", _DELETE, {"delete_entry": True}),
    ],
)
def test_full_collection_readback_requires_exact_change_and_unchanged_siblings(
    action: str, contract: SettingsContract, changes: dict[str, object]
) -> None:
    """Verify state independently of ACK, including protection and every other ID."""
    before, after = _raw(), _after(action)
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    assert not contract.verifier(before, changes, before)
    changed_flag = {**after, "use_dnsrebind": "0"}
    assert not contract.verifier(before, changes, changed_flag)
    mutated = deepcopy(after)
    next(row for row in mutated["adddnsexcept"] if row["id"] == "2")["dns_except"] = (
        "other.example"
    )
    assert not contract.verifier(before, changes, mutated)
    extra = deepcopy(after)
    extra["adddnsexcept"].append({"id": "20", "dns_except": "extra.example"})
    assert not contract.verifier(before, changes, extra)


@pytest.mark.parametrize(
    ("action", "contract", "changes"),
    [
        ("create", _CREATE, {"dns_except": "New.Example."}),
        ("edit", _EDIT, {"dns_except": "New.Example."}),
        ("delete", _DELETE, {"delete_entry": True}),
    ],
)
async def test_real_session_one_write_then_collection_verification(
    action: str, contract: SettingsContract, changes: dict[str, object]
) -> None:
    """Exercise requester-bound grants and collection readback with fake transport."""
    read = AsyncMock(side_effect=[_raw(), _raw(), _after(action)])
    write = AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert "must-not-leak" not in str(initial)
    result = await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once()


async def test_changed_sibling_invalidates_grant_before_write() -> None:
    """Bind whole collection, not merely the selected row or blank create draft."""
    read = AsyncMock(side_effect=[_raw(), _after("edit")])
    write = AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            {"dns_except": "new.example"},
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_ack_echo_never_substitutes_for_create_readback_or_retries_write() -> (
    None
):
    """Treat unchanged fresh collections as failure despite a positive write echo."""
    read = AsyncMock(return_value=_raw())
    write = AsyncMock(
        return_value={"status": "ok", "id": "9", "dns_except": "new.example"}
    )
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            {"dns_except": "new.example"},
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
