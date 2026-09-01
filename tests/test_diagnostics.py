"""Tests for privacy-preserving diagnostics."""

from __future__ import annotations

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
)
from custom_components.speedport_smart.hub import SpeedportHub

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
    assert result["system_log"] == REDACTED
    assert result["message"] == f"peer {REDACTED} used {REDACTED}"
    assert result["safe"] == 42


def test_nested_client_relationship_metadata_is_redacted() -> None:
    """Client placement and parental-profile labels never leave diagnostics."""
    result = _redact(
        {
            "clients": [
                {
                    "access_point": "Living Room",
                    "mesh_node": "Repeater Upstairs",
                    "parental_profile": "Children",
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


async def test_config_entry_diagnostics(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Config-entry diagnostics include runtime health with secrets removed."""
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
