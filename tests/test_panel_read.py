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
                    "wifi_2_4_mac": "AA:BB:CC:DD:EE:01",
                    "wifi_5_mac": "AA:BB:CC:DD:EE:02",
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
                    "target": "Web server",
                    "tcp_mappings": "443 -> 443",
                    "udp_mappings": "443 -> 443",
                    "_identity_fingerprint": "rule-fingerprint",
                    "payload": {"active": "1"},
                }
            ]
        },
        "security": {
            "port_block_rules": [
                {
                    "rule_group": "extended",
                    "id": "block-rule-1",
                    "active": True,
                    "tcp_ports": "80,443",
                    "udp_ports": "53",
                    "client_scope": "must-not-leak",
                }
            ]
        },
        "wifi": {
            "radio_2_4": {"ssid": "Private 2.4 GHz", "key": "hidden"},
            "radio_5": {"ssid": "Private 5 GHz", "key": "hidden"},
            "guest": {"ssid": "Private guest", "key": "hidden"},
            "office": {"ssid": "Private office", "key": "hidden"},
        },
        "ddns": {
            "domain": "subscriber.example.net",
            "update_server": "updates.example.net",
            "username": "hidden-user",
            "password": "hidden-password",
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
        "dect": {
            "handsets": [{"name": "Handset", "battery_percent": 80}],
            "repeaters": [{"id": "repeater-1", "registered": True}],
        },
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
        "port_block_rules",
        "vpn_peers",
        "telephone_lines",
        "dect_handsets",
        "dect_repeaters",
        "ip_phones",
        "usb_devices",
        "receivers",
        "ddns_identity",
        "wifi_2_4_identity",
        "wifi_5_identity",
        "wifi_guest_identity",
        "wifi_office_identity",
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
        {
            "name": "Mesh repeater",
            "connected": True,
            "wifi_2_4_mac": "AA:BB:CC:DD:EE:01",
            "wifi_5_mac": "AA:BB:CC:DD:EE:02",
            "role": "agent",
        }
    ]
    assert sections["port_forward_rules"]["rows"] == [
        {
            "name": "HTTPS",
            "active": True,
            "target": "Web server",
            "tcp_mappings": "443 -> 443",
            "udp_mappings": "443 -> 443",
        }
    ]
    assert sections["port_block_rules"]["rows"] == [
        {
            "rule_group": "extended",
            "id": "block-rule-1",
            "active": True,
            "tcp_ports": "80,443",
            "udp_ports": "53",
        }
    ]
    assert sections["vpn_peers"]["rows"] == [
        {"connected": False, "last_handshake": observed_at.isoformat()}
    ]
    assert sections["dect_repeaters"]["rows"] == [
        {"id": "repeater-1", "registered": True}
    ]
    assert sections["ddns_identity"]["rows"] == [
        {
            "domain": "subscriber.example.net",
            "update_server": "updates.example.net",
        }
    ]
    assert sections["wifi_2_4_identity"]["rows"] == [{"ssid": "Private 2.4 GHz"}]
    assert sections["wifi_5_identity"]["rows"] == [{"ssid": "Private 5 GHz"}]
    assert sections["wifi_guest_identity"]["rows"] == [{"ssid": "Private guest"}]
    assert sections["wifi_office_identity"]["rows"] == [{"ssid": "Private office"}]
    serialized = json.dumps(result)
    for forbidden in (
        "internal-client-id",
        "firmware-row-id",
        "private-fingerprint",
        "rule-fingerprint",
        "must-not-leak",
        "/data/hidden.json",
        "hidden-user",
        "hidden-password",
        '"key"',
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


def test_admin_read_payload_exposes_only_reviewed_lan_ipv6_firmware_flags() -> None:
    """Undocumented LAN flags stay technical, bounded, and administrator-only."""
    data = {
        "lan": {
            "ipv6_pext_flag": True,
            "ipv6_arec_flag": False,
            "ula_address": "must-not-leak-through-this-section",
        }
    }

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["sections"] == [
        {
            "id": "lan_ipv6_technical",
            "source": "protected_json",
            "rows": [
                {"ipv6_pext_flag": True, "ipv6_arec_flag": False},
            ],
            "truncated": False,
        }
    ]
    assert "must-not-leak-through-this-section" not in json.dumps(result)


def test_admin_read_payload_exposes_bounded_public_status_field() -> None:
    """One exact Status field is administrator-only and source-labelled."""
    data = {
        "system": {
            "domain_name": "speedport.ip",
            "device_password_changed": True,
            "loginstate": "must-not-leak",
        }
    }

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["sections"] == [
        {
            "id": "status_technical",
            "source": "public_status",
            "rows": [{"domain_name": "speedport.ip"}],
            "truncated": False,
        }
    ]
    assert "must-not-leak" not in json.dumps(result)
    assert "device_password_changed" not in json.dumps(result)


def test_admin_read_payload_exposes_only_closed_internet_status_code() -> None:
    """The Internet technical section publishes only its reviewed cached field."""
    data = {
        "internet": {
            "failure_reason": "net",
            "ipv4_address": "must-not-leak-through-this-section",
        }
    }

    result = admin_read_payload(data, entry_id="entry-1")

    assert result["sections"] == [
        {
            "id": "internet_status_technical",
            "source": "public_status",
            "rows": [{"failure_reason": "net"}],
            "truncated": False,
        }
    ]
    assert "must-not-leak-through-this-section" not in json.dumps(result)


def test_admin_read_payload_rejects_unknown_internet_failure_text() -> None:
    """Projection remains closed even if an invalid value reaches hub data."""
    result = admin_read_payload(
        {"internet": {"failure_reason": "account@example.net"}},
        entry_id="entry-1",
    )

    assert result["sections"] == []
    assert "account@example.net" not in json.dumps(result)


def test_admin_read_payload_projects_new_management_collections() -> None:
    """New collections remain fixed, admin-only, and secret-free."""
    data = {
        "clients": {
            "items": [
                {
                    "name": "Laptop",
                    "wifi_standard": "IEEE 802.11ax",
                    "has_web_ui": True,
                    "web_ui_port": 443,
                    "web_ui_scheme": "https",
                    "ipv6_ula": "fd00::40",
                    "ipv6_gua": "2001:db8::40",
                }
            ]
        },
        "vpn": {
            "peers": [
                {
                    "id": "peer-1",
                    "name": "Road warrior",
                    "enabled": True,
                    "connected": True,
                    "vpn_userip": "192.0.2.50",
                }
            ]
        },
        "security": {
            "dns_rebind_exceptions": [
                {
                    "domain": "private-service.example",
                    "password": "hidden",
                }
            ]
        },
        "qos": {
            "prioritized_clients": [
                {"slot": 2, "prioritized": True, "hostname": "hidden-host"}
            ]
        },
        "telephony": {
            "providers": [
                {"id": "provider-1", "provider_code": 99, "password": "hidden"}
            ],
            "numbers": [
                {
                    "id": "line-1",
                    "status": "warning",
                    "provider_code": 99,
                    "provider_id": "provider-1",
                    "error_code": "403",
                    "error_reason": "registration rejected",
                    "ip_number": "+49 30 123456",
                }
            ],
        },
        "pbx": {
            "clients": [
                {
                    "id": "pbx-1",
                    "status": "registered",
                    "name": "Desk phone",
                    "ipv4": "192.0.2.20",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "password": "hidden",
                }
            ]
        },
        "usb": {
            "storage_items": [
                {
                    "name": "Backup SSD",
                    "storage_type": "NAS",
                    "connection": "USB",
                    "total_bytes": 4096,
                    "used_bytes": 1024,
                    "free_bytes": 3072,
                    "serial": "hidden-serial",
                }
            ],
            "shares": [
                {
                    "id": "share-1",
                    "name": "Backup",
                    "path": "/mnt/backup",
                    "enabled": True,
                    "read_only": True,
                    "secure": True,
                    "username": "hidden-user",
                }
            ],
        },
        "powerline": {
            "nodes": [
                {
                    "id": "powerline-1",
                    "name": "Living room",
                    "parent": "aa:bb:cc:dd:ee:ff",
                    "manufacturer": "Devolo",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "firmware": "1.2.3",
                    "mode": "mesh",
                    "download_link_speed_bps": 750_000_000,
                    "upload_link_speed_bps": 250_000_000,
                    "management_url": "http://192.0.2.30",
                }
            ]
        },
    }

    result = admin_read_payload(data, entry_id="entry-1")
    sections = {section["id"]: section["rows"] for section in result["sections"]}

    assert sections["clients"] == [
        {
            "name": "Laptop",
            "wifi_standard": "IEEE 802.11ax",
            "has_web_ui": True,
            "web_ui_port": 443,
            "web_ui_scheme": "https",
            "ipv6_ula": "fd00::40",
            "ipv6_gua": "2001:db8::40",
        }
    ]
    assert sections["vpn_peers"] == [
        {
            "id": "peer-1",
            "name": "Road warrior",
            "enabled": True,
            "connected": True,
        }
    ]
    assert sections["dns_rebind_exceptions"] == [{"domain": "private-service.example"}]
    assert sections["qos_prioritized_clients"] == [{"slot": 2, "prioritized": True}]
    assert sections["telephony_providers"] == [
        {"id": "provider-1", "provider_code": 99}
    ]
    assert sections["telephone_lines"] == [
        {
            "id": "line-1",
            "status": "warning",
            "provider_code": 99,
            "provider_id": "provider-1",
            "error_code": "403",
        }
    ]
    assert sections["pbx_clients"] == [
        {
            "id": "pbx-1",
            "status": "registered",
            "name": "Desk phone",
            "ipv4": "192.0.2.20",
            "mac": "aa:bb:cc:dd:ee:ff",
        }
    ]
    assert sections["storage_devices"] == [
        {
            "name": "Backup SSD",
            "serial": "hidden-serial",
            "storage_type": "NAS",
            "connection": "USB",
            "total_bytes": 4096,
            "used_bytes": 1024,
            "free_bytes": 3072,
        }
    ]
    assert sections["nas_shares"] == [
        {
            "id": "share-1",
            "name": "Backup",
            "enabled": True,
            "read_only": True,
            "secure": True,
        }
    ]
    assert sections["powerline_nodes"] == [
        {
            "id": "powerline-1",
            "name": "Living room",
            "parent": "aa:bb:cc:dd:ee:ff",
            "manufacturer": "Devolo",
            "mac": "aa:bb:cc:dd:ee:ff",
            "firmware": "1.2.3",
            "mode": "mesh",
            "download_link_speed_bps": 750_000_000,
            "upload_link_speed_bps": 250_000_000,
        }
    ]
    serialized = json.dumps(result)
    for forbidden in (
        "192.0.2.50",
        "+49 30 123456",
        "registration rejected",
        "hidden-user",
        "/mnt/backup",
        "http://192.0.2.30",
    ):
        assert forbidden not in serialized
