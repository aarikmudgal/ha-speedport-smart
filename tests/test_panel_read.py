"""Tests for the bounded administrator-only cached read projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType

from custom_components.speedport_smart.panel_read import (
    ADMIN_READ_SCHEMA_VERSION,
    MAX_ADMIN_READ_ROWS,
    MAX_ADMIN_READ_TEXT_LENGTH,
    admin_read_payload,
)


def test_admin_read_payload_projects_only_fixed_reviewed_fields() -> None:
    """Expose useful cached list data without transport or credential fields."""
    observed_at = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
    data = {
        "clients": {
            "items": [
                {
                    "id": "internal-client-id",
                    "source_row_id": "firmware-row-id",
                    "managed_form_supported": True,
                    "_identity_fingerprint": "private-fingerprint",
                    "name": "Laptop",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "ipv4": "192.168.2.10",
                    "connected": True,
                    "last_seen": observed_at,
                    "bytes_sent": 10**1000,
                    "password": "must-not-leak",
                    "nested": {"payload": "must-not-leak"},
                }
            ]
        },
        "mesh": {
            "nodes": [
                {
                    "id": "internal-mesh-id",
                    "name": "Mesh repeater",
                    "connected": True,
                    "role": "agent",
                    "endpoint": "/data/hidden.json",
                }
            ]
        },
        "nat": {
            "port_forward_rules": [
                {
                    "id": "rule-id",
                    "name": "HTTPS",
                    "active": True,
                    "_identity_fingerprint": "rule-fingerprint",
                    "payload": {"active": "1"},
                }
            ]
        },
        "vpn": {
            "peers": [
                {
                    "connected": False,
                    "last_handshake": observed_at,
                    "private_key": "must-not-leak",
                }
            ]
        },
        "telephony": {"numbers": [{"name": "Line 1", "registered": True}]},
        "dect": {"handsets": [{"name": "Handset", "battery_percent": 80}]},
        "pbx": {"ip_phones": [{"name": "Desk phone", "registered": True}]},
        "usb": {"items": [{"name": "Storage", "total_bytes": 1024}]},
        "receiver": {"items": [{"name": "5G receiver", "rsrp_dbm": -84.5}]},
        "raw_endpoint": {"password": "must-not-leak"},
    }

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["schema_version"] == ADMIN_READ_SCHEMA_VERSION
    assert result["entry_id"] == "entry-1"
    sections = {section["id"]: section for section in result["sections"]}
    assert tuple(sections) == (
        "clients",
        "mesh_nodes",
        "port_forward_rules",
        "vpn_peers",
        "telephone_lines",
        "dect_handsets",
        "ip_phones",
        "usb_devices",
        "receivers",
    )
    assert sections["clients"]["rows"] == [
        {
            "name": "Laptop",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ipv4": "192.168.2.10",
            "connected": True,
            "last_seen": observed_at.isoformat(),
        }
    ]
    assert sections["mesh_nodes"]["rows"] == [
        {"name": "Mesh repeater", "connected": True, "role": "agent"}
    ]
    assert sections["port_forward_rules"]["rows"] == [{"name": "HTTPS", "active": True}]
    assert sections["vpn_peers"]["rows"] == [
        {"connected": False, "last_handshake": observed_at.isoformat()}
    ]
    serialized = json.dumps(result)
    for forbidden in (
        "internal-client-id",
        "firmware-row-id",
        "private-fingerprint",
        "rule-fingerprint",
        "must-not-leak",
        "/data/hidden.json",
    ):
        assert forbidden not in serialized


def test_admin_read_payload_bounds_rows_and_text() -> None:
    """Router-controlled collection sizes cannot create an unbounded response."""
    data = {
        "clients": {
            "items": [
                {"name": f"{index:03d}-" + ("x" * MAX_ADMIN_READ_TEXT_LENGTH * 2)}
                for index in range(MAX_ADMIN_READ_ROWS + 1)
            ]
        }
    }

    result = admin_read_payload(data, entry_id="entry-1")

    section = result["sections"][0]
    assert section["id"] == "clients"
    assert section["truncated"] is True
    assert len(section["rows"]) == MAX_ADMIN_READ_ROWS
    assert all(
        len(row["name"]) == MAX_ADMIN_READ_TEXT_LENGTH for row in section["rows"]
    )


def test_admin_read_payload_preserves_observed_empty_and_rejects_non_lists() -> None:
    """An observed empty list differs from an aggregate count or absent endpoint."""
    data = {
        "clients": {"items": []},
        "mesh": {"nodes": 2},
        "vpn": {"peers": ["invalid-row", {"private_key": "hidden"}]},
    }

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["sections"] == [
        {
            "id": "clients",
            "source": "protected_json",
            "rows": [],
            "truncated": False,
        },
        {
            "id": "vpn_peers",
            "source": "protected_json",
            "rows": [],
            "truncated": False,
        },
    ]


def test_admin_read_payload_accepts_recursively_immutable_hub_data() -> None:
    """Projection reads the hub snapshot without thawing or mutating it."""
    client = MappingProxyType({"name": "Tablet", "connected": True})
    data = MappingProxyType({"clients": MappingProxyType({"items": (client,)})})

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["sections"][0]["rows"] == [{"name": "Tablet", "connected": True}]
    assert data["clients"]["items"] == (client,)
