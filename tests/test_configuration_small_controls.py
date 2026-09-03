"""Synthetic small native forms and one-shot safety; no live router writes."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_small_controls import (
    SMALL_CONTROL_SETTINGS,
)

if TYPE_CHECKING:
    from custom_components.speedport_smart.configuration import SettingsContract

_QOS, _DNS, _CLEAR, _LOG = SMALL_CONTROL_SETTINGS
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw() -> dict[str, Any]:
    return {
        "use_priovoip": "0",
        "qos_add": {
            "id": "1",
            "sid": [
                {"sid": "device-a", "mdevice_name": "1"},
                {"sid": "device-b", "mdevice_name": "0"},
            ],
        },
        "qos_addmdevice": [
            {
                "sid": "device-a",
                "mdevice_name": "Synthetic A",
                "mdevice_mac": "02-00-00-00-00-01",
                "mdevice_ip": "192.0.2.1",
            },
            {
                "sid": "device-b",
                "mdevice_name": "Synthetic B",
                "mdevice_mac": "02-00-00-00-00-02",
            },
        ],
        "use_dnsrebind": "1",
        "adddnsexcept": [{"id": "2", "dns_except": "synthetic.example"}],
        "use_speeddial": "1",
        "filter_log": "0",
        "addmessage": [{"message": "PRIVATE MESSAGE"}],
        "uptime": "10",
    }


def test_exact_bound_endpoints_payloads_and_no_current_values_in_metadata() -> None:
    """Use Modules only for attached flags, not for bespoke clear/filter actions."""
    raw = _raw()
    original = deepcopy(raw)
    assert _QOS.endpoint == _DNS.endpoint == "data/Modules.json"
    assert _QOS.read_endpoint == "data/QOS.json"
    assert _DNS.read_endpoint == "data/DNSExcept.json"
    assert _QOS.build(raw, {"use_priovoip": True}) == {"use_priovoip": "1"}
    assert _DNS.build(raw, {"use_dnsrebind": False}) == {"use_dnsrebind": "0"}
    assert _CLEAR.endpoint == "data/PhoneLineset.json"
    assert _CLEAR.build(raw, {"clear_number_memory": True}) == {
        "speeddial_delete": "true"
    }
    assert _LOG.endpoint == "data/SystemMessages.json"
    assert _LOG.referer == "html/content/config/system_log.html"
    assert raw == original
    for contract in SMALL_CONTROL_SETTINGS:
        assert contract.acknowledgement == "readback"
        assert contract.metadata()["live_write_verified"] is False
        public = str(contract.read(raw)) + str(contract.metadata())
        for secret in ("PRIVATE MESSAGE", "synthetic.example", "Synthetic A", "02-00"):
            assert secret not in public


@pytest.mark.parametrize(
    ("contract", "changes"),
    [
        (_QOS, {"use_priovoip": "1"}),
        (_QOS, {"use_priovoip": 1}),
        (_DNS, {"use_dnsrebind": "0"}),
        (_DNS, {"use_dnsrebind": False, "id": "2"}),
        (_CLEAR, {"clear_number_memory": False}),
        (_CLEAR, {"clear_number_memory": 1}),
        (_CLEAR, {"speeddial_delete": "true"}),
        (_LOG, {"filter_categories": ["unknown"]}),
        (_LOG, {"filter_categories": ["sys", "sys"]}),
        (_LOG, {"filter_categories": "sys"}),
        (_LOG, {"filter_categories": ["sys"], "search": "true"}),
    ],
)
def test_closed_fields_reject_coercion_and_arbitrary_payload(
    contract: SettingsContract, changes: dict[str, object]
) -> None:
    """Only exact field names and reviewed native values are accepted."""
    with pytest.raises(ConfigurationError):
        contract.build(_raw(), changes)


def test_module_revisions_preserve_settings_identity_not_telemetry() -> None:
    """Revision checks bind hidden settings without changing counters."""
    before, after = _raw(), _raw()
    after["uptime"] = "11"
    after["qos_addmdevice"][0]["mdevice_ip"] = "192.0.2.20"
    assert _QOS.revision(before) == _QOS.revision(after)
    assert _DNS.revision(before) == _DNS.revision(after)
    after["qos_add"]["sid"][0]["mdevice_name"] = "0"
    assert _QOS.revision(before) != _QOS.revision(after)
    after["adddnsexcept"][0]["dns_except"] = "changed.example"
    assert _DNS.revision(before) != _DNS.revision(after)


@pytest.mark.parametrize("mutation", ["membership", "identity", "missing", "duplicate"])
def test_qos_voice_readback_rejects_changed_or_ambiguous_device_context(
    mutation: str,
) -> None:
    """Preserve membership and physical identity across a voice-priority update."""
    before, after = _raw(), _raw()
    after["use_priovoip"] = "1"
    assert _QOS.verifier is not None
    assert _QOS.verifier(before, {"use_priovoip": True}, after)
    if mutation == "membership":
        after["qos_add"]["sid"][0]["mdevice_name"] = "0"
    elif mutation == "identity":
        after["qos_addmdevice"][0]["mdevice_mac"] = "02-00-00-00-00-09"
    elif mutation == "missing":
        after.pop("qos_add")
    else:
        after["qos_addmdevice"].append(deepcopy(after["qos_addmdevice"][0]))
    assert not _QOS.verifier(before, {"use_priovoip": True}, after)


def test_dns_readback_preserves_exact_exception_collection() -> None:
    """A flag update cannot silently erase exception domains."""
    before, after = _raw(), _raw()
    after["use_dnsrebind"] = "0"
    assert _DNS.verifier is not None
    assert _DNS.verifier(before, {"use_dnsrebind": False}, after)
    after["adddnsexcept"] = []
    assert not _DNS.verifier(before, {"use_dnsrebind": False}, after)
    assert _DNS.read({"use_dnsrebind": "1"}) == {"use_dnsrebind": True}
    with pytest.raises(ConfigurationError):
        _DNS.read({})


@pytest.mark.parametrize("mask", range(128))
def test_all_native_filter_masks_match_exact_indexed_fields(mask: int) -> None:
    """The native bitmask has seven ordered categories, with zero unfiltered."""
    keys = ("inet", "tel", "wifi", "sys", "shom", "esup", "sec")
    raw = {"filter_log": str(mask)}
    values = _LOG.read(raw)
    expected = sorted(key for index, key in enumerate(keys) if mask & (1 << index))
    assert values == {"filter_categories": expected}
    payload = _LOG.build(raw, values)
    assert payload == (
        {"search": "false"}
        if mask == 0
        else {
            "search": "true",
            **{
                f"search{index + 1}": key
                for index, key in enumerate(keys)
                if key in expected
            },
        }
    )
    assert _LOG.payload_validator is not None
    assert _LOG.payload_validator(raw, payload)
    assert not _LOG.payload_validator(raw, {**payload, "action_clearlist": "true"})


@pytest.mark.parametrize(
    "value", [None, "", "128", "-1", True, 0.0, [], "0x7", "\uff11\uff12"]
)
def test_invalid_or_missing_filter_state_never_defaults_to_unfiltered(
    value: Any,
) -> None:
    """Malformed state does not authorize an inferred default filter."""
    with pytest.raises(ConfigurationError):
        _LOG.read({"filter_log": value})


@pytest.mark.parametrize(
    ("contract", "changes", "after_fields"),
    [
        (_QOS, {"use_priovoip": True}, {"use_priovoip": "1"}),
        (_DNS, {"use_dnsrebind": False}, {"use_dnsrebind": "0"}),
        (_LOG, {"filter_categories": ["sys", "sec"]}, {"filter_log": "72"}),
        (_LOG, {"filter_categories": []}, {"filter_log": "0"}),
    ],
)
async def test_flags_and_filter_require_exact_independent_readback(
    contract: SettingsContract,
    changes: dict[str, Any],
    after_fields: dict[str, str],
) -> None:
    """A successful callback is insufficient without the requested GET state."""
    before, after = _raw(), _raw()
    if contract is _LOG and not changes["filter_categories"]:
        before["filter_log"] = "72"
    after.update(after_fields)
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
    assert read.await_count == 3


async def test_failed_filter_readback_never_retries_write() -> None:
    """Repeat independent reads only; never repeat the mutation."""
    read, write = AsyncMock(return_value=_raw()), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_LOG, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            _LOG,
            _OWNER,
            initial["revision"],
            {"filter_categories": ["sys"]},
            confirmed=True,
            confirmation_text=_LOG.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


async def test_clear_is_one_shot_manual_unknown_not_a_false_success() -> None:
    """No learned-list readback exists, so no success can be claimed."""
    read, write = AsyncMock(return_value=_raw()), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_CLEAR, _OWNER, read)
    assert initial["values"] == {"clear_number_memory": False}
    assert await session.save(
        _CLEAR,
        _OWNER,
        initial["revision"],
        {"clear_number_memory": True},
        confirmed=True,
        confirmation_text=_CLEAR.confirmation,
        read=read,
        write=write,
    ) == {"status": "outcome_unknown", "verification": "manual_required"}
    write.assert_awaited_once()
    assert read.await_count == 2
    with pytest.raises(ConfigurationError):
        await session.save(
            _CLEAR,
            _OWNER,
            initial["revision"],
            {"clear_number_memory": True},
            confirmed=True,
            confirmation_text=_CLEAR.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


@pytest.mark.parametrize("reason", ["requester", "confirmation", "stale"])
async def test_clear_rejects_wrong_requester_unconfirmed_or_stale_before_post(
    reason: str,
) -> None:
    """Destructive confirmation and requester-bound fresh state precede POST."""
    before, after = _raw(), _raw()
    if reason == "stale":
        after["use_speeddial"] = "0"
    read, write = AsyncMock(side_effect=[before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_CLEAR, _OWNER, read)
    with pytest.raises(ConfigurationError):
        await session.save(
            _CLEAR,
            ("other-admin", "other-session") if reason == "requester" else _OWNER,
            initial["revision"],
            {"clear_number_memory": True},
            confirmed=reason != "confirmation",
            confirmation_text=_CLEAR.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()
