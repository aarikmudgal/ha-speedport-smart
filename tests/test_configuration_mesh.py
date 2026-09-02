"""Offline exact mesh forms, complete target binding and honest identification."""

# Scenario names document each parametrized proof.
# ruff: noqa: D103

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_mesh import (
    MESH_TARGET_SPECS,
    mesh_identity,
    mesh_rows,
    mesh_target_contract,
    mesh_target_metadata,
    mesh_target_rows,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

OWNER = ("admin", "refresh-token")


def mesh_node(identifier: str = "1", *, connected: str = "1") -> dict[str, str]:
    """Synthetic full hidden form; no captured private values."""
    return {
        "id": identifier,
        "mesh_name": f"Node-{identifier}",
        "mesh_mac": f"02:00:00:00:00:{int(identifier):02x}",
        "mesh_serial": f"synthetic-serial-{identifier}",
        "mesh_connected": connected,
        "mesh_device_type": "0",
        "mesh_type": "1",
        "mesh_ipv4": "192.0.2.5",
        "mesh_mac_wlan": "",
        "mesh_mac_wlan5": "",
        "mesh_downspeed": "400",
        "mesh_upspeed": "300",
        "mesh_rssi": "-60",
        "mesh_upd_local": "0",
        "mesh_upd_avail": "1",
        "mesh_firmware": "1.0",
        "mesh_upd_firmware": "2.0",
        "newFwImageURL": "https://firmware.example.test/mesh.bin",
        "newFwDigest": "synthetic-offer-digest",
    }


def mesh_raw(*nodes: dict[str, str]) -> dict:
    return {"router_state": "OK", "addmeshdevice": list(nodes)}


def test_metadata_has_only_closed_static_forms() -> None:
    metadata = mesh_target_metadata()
    assert len(metadata) == len(MESH_TARGET_SPECS) == 4
    assert all(item["requires_target"] for item in metadata)
    assert all(item["live_write_verified"] is False for item in metadata)
    assert "serial" not in repr(metadata)
    assert "192.0.2" not in repr(metadata)
    assert "data/" not in repr(metadata)


@pytest.mark.parametrize("collection", [[], {}])
def test_explicit_empty_inventory_proves_no_targets(collection: object) -> None:
    assert mesh_rows({"router_state": "OK", "addmeshdevice": collection}) == ()


def test_observed_omitted_template_requires_exact_no_mesh_flag() -> None:
    assert mesh_rows({"router_state": "OK", "mesh_exist": "0"}) == ()
    for value in (None, "", "1", False, 0, ["0", "1"]):
        with pytest.raises(ConfigurationError):
            mesh_rows({"router_state": "OK", "mesh_exist": value})
    with pytest.raises(ConfigurationError):
        mesh_rows({"router_state": "OK", "mesh_exist": "0", "addmeshdevice": None})


def test_empty_mac_template_is_not_a_node() -> None:
    placeholder = {"id": "0", "mesh_mac": "", "mesh_serial": "", "mesh_connected": "0"}
    assert mesh_rows(mesh_raw(placeholder)) == ()
    placeholder["mesh_connected"] = "1"
    with pytest.raises(ConfigurationError):
        mesh_rows(mesh_raw(placeholder))


@pytest.mark.parametrize(
    "replacement", [None, "", 1, ["junk"], {"id": ["1"], "mesh_mac": []}]
)
def test_incomplete_inventory_rejected(replacement: object) -> None:
    with pytest.raises(ConfigurationError):
        mesh_rows({"router_state": "OK", "addmeshdevice": replacement})


def test_columnar_inventory_and_identical_scalar_duplicates() -> None:
    nodes = [mesh_node("1"), mesh_node("2")]
    columns = {key: [row[key] for row in nodes] for key in nodes[0]}
    raw = {"router_state": ["OK", "OK"], "addmeshdevice": columns}
    assert [row["id"] for row in mesh_rows(raw)] == ["1", "2"]
    columns["mesh_name"].pop()
    with pytest.raises(ConfigurationError):
        mesh_rows(raw)


@pytest.mark.parametrize("key", ["id", "mesh_mac", "mesh_serial"])
def test_duplicate_private_identity_rejected(key: str) -> None:
    first, second = mesh_node("1"), mesh_node("2")
    second[key] = first[key]
    with pytest.raises(ConfigurationError):
        mesh_rows(mesh_raw(first, second))


@pytest.mark.parametrize("key", ["has_more", "truncated", "next_page", "next_cursor"])
def test_partial_inventory_never_proves_absence(key: str) -> None:
    with pytest.raises(ConfigurationError):
        mesh_rows({**mesh_raw(mesh_node()), key: "1"})


@pytest.mark.parametrize("value", ["3", [], ["0", "1"], None])
def test_bad_connection_flags_not_silently_filtered(value: object) -> None:
    row = mesh_node()
    row["mesh_connected"] = value
    with pytest.raises(ConfigurationError):
        mesh_target_rows("network_mesh_node_delete", mesh_raw(row))


def test_target_selection_filters_only_after_complete_validation() -> None:
    raw = mesh_raw(mesh_node("1"), mesh_node("2", connected="0"))
    assert [row["id"] for row in mesh_target_rows("network_mesh_node_delete", raw)] == [
        "2"
    ]
    assert [
        row["id"] for row in mesh_target_rows("network_mesh_identify_start", raw)
    ] == ["1"]
    assert len(mesh_target_rows("network_mesh_node_rename", raw)) == 2


def test_rename_exact_full_form_and_private_revision() -> None:
    contract = mesh_target_contract("network_mesh_node_rename", "1")
    raw = mesh_raw(mesh_node())
    assert contract.read(raw) == {"mesh_name": "Node-1"}
    payload = contract.build(raw, {"mesh_name": "New-Name"})
    assert set(payload) == {
        "id",
        "mesh_name",
        "mesh_device_type",
        "mesh_connected",
        "mesh_mac",
        "mesh_mac_wlan",
        "mesh_mac_wlan5",
        "mesh_type",
        "mesh_ipv4",
        "mesh_downspeed",
        "mesh_upspeed",
        "mesh_rssi",
        "mesh_serial",
    }
    assert payload["mesh_name"] == "New-Name"
    assert payload["mesh_serial"] == "synthetic-serial-1"
    assert contract.revision(raw)["context"] == mesh_identity(raw)
    assert "synthetic" not in repr(contract.read(raw))
    assert "synthetic" not in repr(contract)


@pytest.mark.parametrize(
    "name", ["", "too long " * 5, "With space", "with_underscore", "ä", "a\n"]
)
def test_rename_exact_static_alphabet(name: str) -> None:
    with pytest.raises(ConfigurationError):
        mesh_target_contract("network_mesh_node_rename", "1").build(
            mesh_raw(mesh_node()),
            {"mesh_name": name},
        )


def test_client_cannot_inject_identity_or_raw_endpoint() -> None:
    contract = mesh_target_contract("network_mesh_node_rename", "1")
    for extra in ("id", "mesh_serial", "endpoint", "mesh_mac"):
        with pytest.raises(ConfigurationError):
            contract.build(mesh_raw(mesh_node()), {"mesh_name": "New", extra: "2"})


def test_delete_is_serial_based_and_disconnected_only() -> None:
    contract = mesh_target_contract("network_mesh_node_delete", "1")
    with pytest.raises(ConfigurationError):
        contract.build(mesh_raw(mesh_node()), {"execute": True})
    raw = mesh_raw(mesh_node(connected="0"))
    assert contract.read(raw) == {"execute": False}
    assert contract.build(raw, {"execute": True}) == {
        "deleteEntry": "delete",
        "mesh_serial_number": "synthetic-serial-1",
    }
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"execute": False})


def test_delete_complete_readback_preserves_siblings() -> None:
    contract = mesh_target_contract("network_mesh_node_delete", "1")
    first, second = mesh_node("1", connected="0"), mesh_node("2")
    before = mesh_raw(first, second)
    assert contract.verifier(before, {"execute": True}, mesh_raw(second))
    assert not contract.verifier(before, {"execute": True}, mesh_raw())
    assert not contract.verifier(before, {"execute": True}, before)
    changed = {**second, "mesh_name": "Unexpected"}
    assert not contract.verifier(before, {"execute": True}, mesh_raw(changed))


def test_rename_complete_readback_preserves_identity_and_siblings() -> None:
    contract = mesh_target_contract("network_mesh_node_rename", "1")
    before = mesh_raw(mesh_node("1"), mesh_node("2"))
    after = deepcopy(before)
    after["addmeshdevice"][0]["mesh_name"] = "Renamed"
    assert contract.verifier(before, {"mesh_name": "Renamed"}, after)
    after["addmeshdevice"][1]["mesh_serial"] = "Replacement"
    assert not contract.verifier(before, {"mesh_name": "Renamed"}, after)


@pytest.mark.parametrize(("operation", "paging"), [("start", "1"), ("stop", "0")])
def test_identification_exact_payload_without_led_success_claim(
    operation: str, paging: str
) -> None:
    contract = mesh_target_contract("network_mesh_identify_" + operation, "1")
    row = mesh_node()
    row["mesh_mac"] = "02-00-00-00-00-01"
    assert contract.build(mesh_raw(row), {"execute": True}) == {
        "mesh_paging": paging,
        "mesh_mac": "02:00:00:00:00:01",
    }
    assert contract.acknowledgement == "readback"
    assert contract.readback_policy == "manual_required"
    assert contract.verifier is None


async def test_identify_session_sends_once_returns_manual_unknown() -> None:
    contract = mesh_target_contract("network_mesh_identify_start", "1")
    session = ConfigurationSession()
    read = AsyncMock(return_value=mesh_raw(mesh_node()))
    write = AsyncMock(return_value={})
    review = await session.read(contract, OWNER, read)
    result = await session.save(
        contract,
        OWNER,
        review["revision"],
        {"execute": True},
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "outcome_unknown", "verification": "manual_required"}
    assert read.await_count == 2
    write.assert_awaited_once()
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            review["revision"],
            {"execute": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )


async def test_target_replacement_invalidates_approval_before_any_write() -> None:
    contract = mesh_target_contract("network_mesh_node_delete", "1")
    session = ConfigurationSession()
    before = mesh_raw(mesh_node(connected="0"))
    after = deepcopy(before)
    after["addmeshdevice"][0]["mesh_serial"] = "replaced-device"
    read = AsyncMock(side_effect=[before, after])
    write = AsyncMock()
    review = await session.read(contract, OWNER, read)
    assert "synthetic" not in repr(review)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            review["revision"],
            {"execute": True},
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()
