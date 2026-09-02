"""Tests for privacy-preserving diagnostics."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speedport_smart.const import (
    CONF_HOST,
    CONF_PASSWORD,
    DOMAIN,
    REDACTED,
)
from custom_components.speedport_smart.diagnostics import (
    _redact,
    async_get_config_entry_diagnostics,
    safe_error_class_name,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import CapabilityReport

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def test_recursive_redaction() -> None:
    """Sensitive router identifiers and network data never leave diagnostics."""
    result = _redact(
        {
            "password": "admin-secret",
            "public_key": "wireguard-public-material",
            "imsi": "262010123456789",
            "client_mac": "aa:bb:cc:dd:ee:ff",
            "_identity_fingerprint": "rule-target-hash",
            "source_row_id": "private-router-row",
            "number": "+49 30 123456",
            "wan_ip": "203.0.113.4",
            "domain": "private.customer.example",
            "domain_name": "speedport.ip",
            "ssid": "Private Wi-Fi",
            "target": "Office workstation",
            "system_log": "phone and client history",
            "message": "peer aa:bb:cc:dd:ee:ff used 203.0.113.5",
            "safe": 42,
        }
    )

    assert result["password"] == REDACTED
    assert result["public_key"] == REDACTED
    assert result["imsi"] == REDACTED
    assert result["client_mac"] == REDACTED
    assert result["_identity_fingerprint"] == REDACTED
    assert result["source_row_id"] == REDACTED
    assert result["number"] == REDACTED
    assert result["wan_ip"] == REDACTED
    assert result["domain"] == REDACTED
    assert result["domain_name"] == REDACTED
    assert result["ssid"] == REDACTED
    assert result["target"] == REDACTED
    assert result["system_log"] == REDACTED
    assert result["message"] == REDACTED
    assert result["safe"] == 42


def test_error_class_name_is_bounded_and_never_exposes_message_text() -> None:
    """Only a strict exception class identifier may reach visible diagnostics."""
    assert safe_error_class_name(RuntimeError("private router text")) == "RuntimeError"
    assert safe_error_class_name("SpeedportSessionBusyError") == (
        "SpeedportSessionBusyError"
    )
    assert safe_error_class_name("SpeedportError: private router text") == (
        "SpeedportError"
    )
    assert safe_error_class_name("unsafe error: 192.0.2.1") == "UnknownError"
    assert safe_error_class_name("E" * 65) == "UnknownError"
    assert safe_error_class_name(object()) == "UnknownError"


def test_router_reason_text_is_always_redacted() -> None:
    """Provider and protocol reason text can contain subscriber identifiers."""
    result = _redact(
        {
            "internet": {
                "failure_reason": "account alice@example.net at customer.example",
            },
            "telephony": {
                "numbers": [
                    {
                        "error_reason": "SIP user +49 30 123456 rejected",
                        "status": "failed",
                    }
                ]
            },
        }
    )

    assert result["internet"]["failure_reason"] == REDACTED
    assert result["telephony"]["numbers"][0]["error_reason"] == REDACTED
    assert result["telephony"]["numbers"][0]["status"] == "failed"


def test_ddns_identity_is_redacted_but_safe_transport_state_remains() -> None:
    """Diagnostics never export subscriber DDNS identity."""
    result = _redact(
        {
            "ddns": {
                "domain": "subscriber.private.example",
                "update_server": "updates.private.example",
                "update_protocol": "https",
                "update_port": 443,
            }
        }
    )["ddns"]

    assert result == {
        "domain": REDACTED,
        "update_server": REDACTED,
        "update_protocol": "https",
        "update_port": 443,
    }


def test_telephony_secrets_names_and_assignments_are_redacted() -> None:
    """Telephony diagnostics retain safe counts but no subscriber material."""
    result = _redact(
        {
            "dect_pin": "1234",
            "contact_name": "Private person",
            "incoming_number": "+49 30 123456",
            "number_assignment": "line-1 to handset-1",
            "phonebook_entry_count": 42,
            "repeaters": [{"id": "repeater-1", "registered": True}],
        }
    )

    assert result["dect_pin"] == REDACTED
    assert result["contact_name"] == REDACTED
    assert result["incoming_number"] == REDACTED
    assert result["number_assignment"] == REDACTED
    assert result["phonebook_entry_count"] == 42
    assert result["repeaters"] == [{"id": REDACTED, "registered": True}]


def test_nested_client_relationship_metadata_is_redacted() -> None:
    """Client placement and parental-profile labels never leave diagnostics."""
    result = _redact(
        {
            "clients": [
                {
                    "access_point": "Living Room",
                    "mesh_node": "Repeater Upstairs",
                    "parental_profile": "Children",
                    "target": "Private web server",
                    "configured_reserved_ipv4": "192.168.2.55",
                    "ipv6_ula": "fd00::55",
                    "ipv6_gua": "2001:db8::55",
                    "connected": True,
                    "transport": "wifi",
                }
            ]
        }
    )

    client = result["clients"][0]
    assert client["access_point"] == REDACTED
    assert client["mesh_node"] == REDACTED
    assert client["parental_profile"] == REDACTED
    assert client["target"] == REDACTED
    assert client["configured_reserved_ipv4"] == REDACTED
    assert client["ipv6_ula"] == REDACTED
    assert client["ipv6_gua"] == REDACTED
    assert client["connected"] is True
    assert client["transport"] == "wifi"


def test_nested_mesh_relationship_metadata_is_redacted() -> None:
    """Mesh parent identifiers and addresses never leave diagnostics."""
    result = _redact(
        {
            "mesh": {
                "nodes": [
                    {
                        "parent": "Repeater Upstairs",
                        "mesh_parent": "private-router-row",
                        "ipv4": "192.168.2.10",
                        "connected": True,
                    }
                ]
            }
        }
    )

    node = result["mesh"]["nodes"][0]
    assert node["parent"] == REDACTED
    assert node["mesh_parent"] == REDACTED
    assert node["ipv4"] == REDACTED
    assert node["connected"] is True


def test_policy_inventory_domains_are_redacted_but_boolean_state_remains() -> None:
    """Administrator-only DNS values never enter exported diagnostics."""
    result = _redact(
        {
            "security": {
                "dns_rebind_exceptions": [
                    {"domain": "private-service.example", "active": True}
                ]
            },
            "qos": {"prioritized_clients": [{"slot": 1, "prioritized": True}]},
        }
    )

    assert result["security"]["dns_rebind_exceptions"][0]["domain"] == REDACTED
    assert result["security"]["dns_rebind_exceptions"][0]["active"] is True
    assert result["qos"]["prioritized_clients"] == [{"slot": 1, "prioritized": True}]


async def test_config_entry_diagnostics(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Config-entry diagnostics include runtime health with secrets removed."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=False,
        failures=MappingProxyType(
            {
                "authentication": (
                    "SpeedportAuthenticationError: private subscriber message"
                )
            }
        ),
    )
    mock_speedport_client.observed_feature_schema = MappingProxyType(
        {
            "wifi": (
                MappingProxyType({"path": "rows[].enabled", "shape": "boolean"}),
                MappingProxyType({"path": "192.0.2.55", "shape": "string"}),
            )
        }
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    hub._merge_data(  # noqa: SLF001
        {"telephony": {"number": "+4930123456"}, "system_log": "private"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Router",
        data={
            CONF_HOST: "speedport.ip",
            CONF_PASSWORD: "secret",
        },
        options={},
        version=1,
    )
    entry.runtime_data = hub

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config_entry"]["title"] == REDACTED
    assert result["config_entry"]["data"][CONF_HOST] == REDACTED
    assert result["config_entry"]["data"][CONF_PASSWORD] == REDACTED
    assert result["runtime"]["data"]["telephony"]["number"] == REDACTED
    assert result["runtime"]["data"]["system_log"] == REDACTED
    assert result["runtime"]["router"]["model"] == "Speedport Smart 4R Typ A"
    assert result["runtime"]["router"]["serial_number"] == REDACTED
    assert result["runtime"]["observed_feature_schema"] == {
        "wifi": [
            {"path": "rows[].enabled", "shape": "boolean"},
            {"path": REDACTED, "shape": "string"},
        ]
    }
    assert result["runtime"]["capability_report"]["failures"] == {
        "authentication": "SpeedportAuthenticationError"
    }
    assert "private subscriber message" not in repr(result)
