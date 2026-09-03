"""Offline port-forward contract proof with synthetic IDs, MACs and ranges."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.api.codec import normalize_document
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_port_rules import (
    PORT_RULE_SETTINGS,
    port_rule_target_contract,
    port_rule_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

if TYPE_CHECKING:
    from custom_components.speedport_smart.configuration import SettingsContract

_CREATE = PORT_RULE_SETTINGS[0]
_EDIT = port_rule_target_contract("port_forward_edit", "7")
_DELETE = port_rule_target_contract("port_forward_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")


def _range(
    protocol: str, identifier: str, start: str, end: str, destination: str
) -> dict[str, str]:
    return {
        f"portuw{protocol}_id": identifier,
        f"{protocol}_public_from": start,
        f"{protocol}_public_to": end,
        f"{protocol}_private_dest": destination,
        f"{protocol}_private_to": str(int(destination) + int(end) - int(start))
        if end
        else "",
    }


def _raw(*, empty: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "portuw_addmdevice": [
            {
                "sid": "device-a",
                "mdevice_name": "Device A",
                "mdevice_mac": "02:00:00:00:00:01",
                "mdevice_rssi": "-40",
            },
            {
                "sid": "device-b",
                "mdevice_name": "Device B",
                "mdevice_mac": "02:00:00:00:00:02",
                "mdevice_rssi": "-50",
            },
        ],
        "tcpreservedports": "21,80,500-505",
        "udpreservedports": "53,1000-1005",
    }
    if not empty:
        raw["addportuw"] = [
            {
                "id": "2",
                "portuw_name": "Sibling",
                "portuw_active": "1",
                "portuw_device": "device-b",
                "portuw_template": "-1",
                "addtcpportuw": _range("tcp", "11", "9000", "", "9000"),
            },
            {
                "id": "7",
                "portuw_name": "Current",
                "portuw_active": "1",
                "portuw_device": "device-a",
                "portuw_template": "-1",
                "addtcpportuw": [
                    _range("tcp", "4", "8080", "8082", "80"),
                    _range("tcp", "9", "8443", "", "443"),
                ],
                "addudpportuw": _range("udp", "6", "2000", "2001", "3000"),
            },
        ]
    return raw


def _changes() -> dict[str, Any]:
    return {
        "portuw_name": "New rule",
        "portuw_device": "device-b",
        "portuw_active": True,
        "tcp_enabled": True,
        "tcp_public_from": 4000,
        "tcp_public_to": 4002,
        "tcp_private_dest": 5000,
    }


def _created(raw: dict[str, Any]) -> dict[str, Any]:
    after = deepcopy(raw)
    after.setdefault("addportuw", []).append(
        {
            "id": "15",
            "portuw_name": "New rule",
            "portuw_device": "device-b",
            "portuw_active": "1",
            "portuw_template": "-1",
            "addtcpportuw": _range("tcp", "30", "4000", "4002", "5000"),
        }
    )
    return after


def test_empty_real_shape_and_dynamic_identity_choices() -> None:
    """Read an unconfigured new draft without fabricating an existing target."""
    raw = _raw(empty=True)
    assert _CREATE.read(raw)["portuw_device"] == "0"
    assert _CREATE.read(raw)["tcp_public_from"] == 0
    assert _CREATE.choices(raw)["portuw_device"] == [
        {"value": "0", "label": "Select a destination device"},
        {"value": "device-a", "label": "Device A (device-a)"},
        {"value": "device-b", "label": "Device B (device-b)"},
    ]
    assert "02:00:00" not in str(_CREATE.read(raw)) + str(_CREATE.choices(raw))
    with pytest.raises(ConfigurationError):
        _CREATE.read({})


def test_exact_create_payload_has_full_native_empty_udp_placeholder() -> None:
    """Match outer ordinal plus inner ordinal, including unused hidden new IDs."""
    raw = _raw()
    before = deepcopy(raw)
    assert _CREATE.build(raw, _changes()) == {
        "id": "-1",
        "portuw_name": "New rule",
        "portuw_active": "1",
        "portuw_device": "device-b",
        "portuw_template": "-1",
        "portuwtcp_id[31]": "-1",
        "tcp_public_from[31]": "4000",
        "tcp_public_to[31]": "4002",
        "tcp_private_dest[31]": "5000",
        "portuwudp_id[31]": "-1",
        "udp_public_from[31]": "",
        "udp_public_to[31]": "",
        "udp_private_dest[31]": "",
    }
    assert raw == before
    assert _CREATE.endpoint == "data/PortuwMain.json"
    assert _CREATE.referer == "html/content/internet/portforwarding.html"


def test_udp_only_and_both_protocol_creation() -> None:
    """Permit one range for either or both protocols with independent namespaces."""
    changes = {
        "portuw_name": "UDP",
        "portuw_device": "device-a",
        "udp_enabled": True,
        "udp_public_from": 8080,
        "udp_private_dest": 53,
    }
    assert _CREATE.build(_raw(), changes)["udp_public_from[31]"] == "8080"
    assert _CREATE.build(_raw(), changes)["tcp_public_from[31]"] == ""
    changes.update(
        {key: value for key, value in _changes().items() if key.startswith("tcp_")}
    )
    assert "tcp_private_to[31]" not in _CREATE.build(_raw(), changes)


def test_edit_preserves_all_current_range_ids_values_and_native_ordinal() -> None:
    """Changing only a name still sends the complete selected rule form."""
    raw = _raw()
    before = deepcopy(raw)
    payload = _EDIT.build(raw, {"portuw_name": "Renamed"})
    assert payload["id"] == "7"
    assert payload["portuw_name"] == "Renamed"
    assert payload["portuw_device"] == "device-a"
    assert payload["portuw_template"] == "-1"
    assert payload["portuwtcp_id[21]"] == "4"
    assert payload["tcp_public_from[21]"] == "8080"
    assert "tcp_private_to[21]" not in payload
    assert payload["portuwtcp_id[22]"] == "9"
    assert payload["tcp_public_to[22]"] == ""
    assert payload["portuwudp_id[21]"] == "6"
    assert len(payload) == 17
    assert raw == before
    assert port_rule_target_rows("port_forward_edit", raw) == (
        {"id": "2", "portuw_name": "Sibling"},
        {"id": "7", "portuw_name": "Current"},
    )


def test_delete_exact_outer_rule_payload_and_absence_readback() -> None:
    """Delete only the exact selected stable outer ID with generic deleteEntry."""
    raw = _raw()
    assert _DELETE.build(raw, {"delete_entry": True}) == {
        "id": "7",
        "deleteEntry": "delete",
    }
    after = deepcopy(raw)
    after["addportuw"].pop()
    assert _DELETE.read(after) == {"delete_entry": True}
    assert _DELETE.verifier is not None
    assert _DELETE.verifier(raw, {"delete_entry": True}, after)
    with pytest.raises(ConfigurationError):
        _DELETE.build(after, {"delete_entry": True})


@pytest.mark.parametrize(
    "change",
    [
        {"tcp_public_from": 0},
        {"tcp_public_from": -1},
        {"tcp_public_from": 65536},
        {"tcp_public_from": True},
        {"tcp_public_from": "4000"},
        {"tcp_public_to": 3999},
        {"tcp_public_to": 4000},
        {"tcp_private_dest": 65535},
        {"portuw_device": "0"},
        {"portuw_device": "unknown"},
        {"portuw_name": ""},
        {"portuw_name": "<bad>"},
        {"portuw_name": "x" * 21},
        {"portuw_name": "😀"},
        {"portuw_name": "bad\nname"},
        {"portuw_name": "bad\x7fname"},
    ],
)
def test_new_range_bounds_names_and_target_rejected(change: dict[str, object]) -> None:
    """Reject invalid ranges and exact identity errors before serialization."""
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw(), {**_changes(), **change})


@pytest.mark.parametrize(
    ("start", "end"),
    [(21, 0), (79, 81), (499, 500), (505, 506), (8081, 8085), (8999, 9000)],
)
def test_reserved_and_existing_public_ranges_cannot_overlap(
    start: int, end: int
) -> None:
    """Check intersections rather than merely equal first ports."""
    with pytest.raises(ConfigurationError, match="port_range_in_use"):
        _CREATE.build(
            _raw(), {**_changes(), "tcp_public_from": start, "tcp_public_to": end}
        )


@pytest.mark.parametrize(
    "value", [None, "TCP: 21,80", "1;2", "0", "65536", "4-2", "1,,2", "1-2-3", "-1"]
)
def test_unknown_reserved_grammar_fails_closed(value: object) -> None:
    """Use only captured comma-separated integers and inclusive range syntax."""
    with pytest.raises(ConfigurationError):
        _CREATE.read({**_raw(), "tcpreservedports": value})


@pytest.mark.parametrize(
    "changes",
    [
        {"portuw_name": "Only name"},
        {"portuw_name": "Empty", "portuw_device": "device-a"},
        {"id": "7"},
        {"tcp_public_from[11]": "80"},
        {"endpoint": "data/Other.json"},
        {},
    ],
)
def test_incomplete_create_and_raw_wire_injection_rejected(
    changes: dict[str, object],
) -> None:
    """Do not expose a generic key or arbitrary endpoint write path."""
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_outer",
        "duplicate_range",
        "negative_outer",
        "negative_range",
        "missing_device_mac",
        "duplicate_device",
        "bad_derived",
        "missing_public_end",
        "mixed_ranges",
        "empty_ranges",
    ],
)
def test_malformed_existing_state_fails_closed(mutation: str) -> None:
    """Current outer and nested identities must be unambiguous and complete."""
    raw = _raw()
    row = raw["addportuw"][1]
    if mutation == "duplicate_outer":
        row["id"] = "2"
    elif mutation == "duplicate_range":
        row["addtcpportuw"][1]["portuwtcp_id"] = "4"
    elif mutation == "negative_outer":
        row["id"] = "-1"
    elif mutation == "negative_range":
        row["addtcpportuw"][0]["portuwtcp_id"] = "-1"
    elif mutation == "missing_device_mac":
        raw["portuw_addmdevice"][0].pop("mdevice_mac")
    elif mutation == "duplicate_device":
        raw["portuw_addmdevice"][1]["sid"] = "device-a"
    elif mutation == "bad_derived":
        row["addtcpportuw"][0]["tcp_private_to"] = "999"
    elif mutation == "missing_public_end":
        row["addtcpportuw"][0].pop("tcp_public_to")
    elif mutation == "mixed_ranges":
        row["addtcpportuw"] = ["unknown"]
    else:
        row.pop("addtcpportuw")
        row.pop("addudpportuw")
    with pytest.raises(ConfigurationError):
        _CREATE.read(raw)


def test_missing_preserved_preset_blocks_edit_but_not_exact_deletion() -> None:
    """Do not invent an active selector value for an existing full-form save."""
    raw = _raw()
    raw["addportuw"][1].pop("portuw_template")
    with pytest.raises(ConfigurationError, match="missing_preserved_port_template"):
        _EDIT.build(raw, {"portuw_name": "Changed"})
    assert _DELETE.build(raw, {"delete_entry": True})["id"] == "7"


def test_create_verifier_requires_exact_new_rule_and_unchanged_siblings() -> None:
    """Assigned IDs alone are insufficient; every persisted range must match."""
    before = _raw()
    after = _created(before)
    assert _CREATE.verifier is not None
    assert _CREATE.verifier(before, _changes(), after)
    assert not _CREATE.verifier(before, _changes(), before)
    for key, value in (
        ("portuw_name", "Wrong"),
        ("portuw_device", "device-a"),
        ("portuw_active", "0"),
    ):
        changed = deepcopy(after)
        changed["addportuw"][-1][key] = value
        assert not _CREATE.verifier(before, _changes(), changed)
    changed = deepcopy(after)
    changed["addportuw"][0]["portuw_name"] = "Changed sibling"
    assert not _CREATE.verifier(before, _changes(), changed)
    changed = deepcopy(after)
    changed["addportuw"][-1]["addtcpportuw"]["tcp_private_dest"] = "80"
    assert not _CREATE.verifier(before, _changes(), changed)


def test_revision_ignores_telemetry_but_binds_mac_order_and_ranges() -> None:
    """Private stable context prevents stale device or range identity reuse."""
    before = _raw()
    changed = deepcopy(before)
    changed["portuw_addmdevice"][0]["mdevice_rssi"] = "-75"
    assert _CREATE.revision(before) == _CREATE.revision(changed)
    changed["portuw_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert _CREATE.revision(before) != _CREATE.revision(changed)


def test_hyphen_mac_notation_normalizes_without_allowing_mixed_separators() -> None:
    """MAC spelling changes cannot invalidate identity or bypass validation."""
    raw, native = _raw(), _raw()
    for row in native["portuw_addmdevice"]:
        row["mdevice_mac"] = row["mdevice_mac"].replace(":", "-").upper()
    assert _CREATE.revision(native) == _CREATE.revision(raw)
    assert _CREATE.build(native, _changes()) == _CREATE.build(raw, _changes())
    native["portuw_addmdevice"][0]["mdevice_mac"] = "02-00:00-00-00-01"
    with pytest.raises(ConfigurationError):
        _CREATE.read(native)


def test_nested_native_template_records_normalize_without_identity_loss() -> None:
    """Trace the firmware template varids through the real private read decoder."""
    raw = _raw()

    def records(value: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for key, item in value.items():
            if isinstance(item, dict):
                result.append(
                    {"varid": key, "vartype": "template", "varvalue": records(item)}
                )
            elif isinstance(item, list):
                result.extend(
                    {"varid": key, "vartype": "template", "varvalue": records(row)}
                    for row in item
                )
            else:
                result.append({"varid": key, "vartype": "value", "varvalue": item})
        return result

    normalized = normalize_document(records(raw), preserve_compounds=True)
    assert _EDIT.build(normalized, {"portuw_name": "New name"}) == _EDIT.build(
        raw, {"portuw_name": "New name"}
    )


@pytest.mark.parametrize(
    "tamper",
    ["extra", "outer_id", "range_id", "sid", "omitted", "wrong_index", "derived_end"],
)
def test_dynamic_payload_validator_rejects_every_noncontract_map(tamper: str) -> None:
    """No arbitrary keys, target substitutions or omitted placeholder fields."""
    raw = _raw()
    payload = _CREATE.build(raw, _changes())
    if tamper == "extra":
        payload["path"] = "data/Other.json"
    elif tamper == "outer_id":
        payload["id"] = "7"
    elif tamper == "range_id":
        payload["portuwtcp_id[31]"] = "4"
    elif tamper == "sid":
        payload["portuw_device"] = "unknown"
    elif tamper == "omitted":
        payload.pop("portuwudp_id[31]")
    elif tamper == "wrong_index":
        payload["portuwtcp_id[11]"] = payload.pop("portuwtcp_id[31]")
    else:
        payload["tcp_private_to[31]"] = "5003"
    assert _CREATE.payload_validator is not None
    assert not _CREATE.payload_validator(raw, payload)


def test_create_rule_limit_and_invalid_target_arguments() -> None:
    """Apply firmware collection bounds and reject external target coercion."""
    raw = _raw()
    raw["addportuw"] = [
        {**deepcopy(raw["addportuw"][0]), "id": str(index)} for index in range(32)
    ]
    with pytest.raises(ConfigurationError, match="port_rule_limit"):
        _CREATE.build(raw, _changes())
    for target in (None, "", "-1", "01", "../7", 7, True):
        with pytest.raises(ConfigurationError):
            port_rule_target_contract("port_forward_edit", target)  # type: ignore[arg-type]


async def test_device_identity_change_invalidates_grant_before_any_write() -> None:
    """A same-SID replacement device cannot reuse a previous confirmation."""
    before = _raw()
    changed = deepcopy(before)
    changed["portuw_addmdevice"][1]["mdevice_mac"] = "02:00:00:00:00:09"
    read, write = AsyncMock(side_effect=[before, changed]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            _changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


@pytest.mark.parametrize("action", ["create", "edit", "delete"])
async def test_real_session_one_write_and_exact_readback(action: str) -> None:
    """Exercise grants and complete collection proof with fake transports."""
    before = _raw()
    contract: SettingsContract
    if action == "create":
        contract, changes, after = _CREATE, _changes(), _created(before)
    elif action == "edit":
        contract, changes, after = _EDIT, {"portuw_name": "Changed"}, deepcopy(before)
        after["addportuw"][1]["portuw_name"] = "Changed"
    else:
        contract, changes, after = _DELETE, {"delete_entry": True}, deepcopy(before)
        after["addportuw"].pop()
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert "02:00:00" not in str(initial)
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


async def test_ack_echo_never_proves_created_rule_or_retries_write() -> None:
    """Only independent fresh state can establish a successful creation."""
    read, write = (
        AsyncMock(return_value=_raw()),
        AsyncMock(return_value={"status": "ok", "id": "15"}),
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
            _changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
