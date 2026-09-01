"""Tests for reviewed management command contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from custom_components.speedport_smart import hub as hub_module
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.management import (
    COMMAND_WRITE_CONTRACTS,
    ManagementCommandContract,
    RouterWriteContract,
    get_command_write_contract,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import RouterInfo


_EXPECTED_COMMANDS = {
    "guest_wifi_set_enabled": ("set_guest_wifi", "wifi"),
    "internet_reconnect": ("reconnect", "internet"),
    "port_mapping_set_enabled": ("set_port_forward_rule", "port_forwarding"),
    "reboot": ("reboot", "system"),
    "reconnect": ("reconnect", "internet"),
    "rename_client": ("rename_client", "clients"),
    "router_reboot": ("reboot", "system"),
    "set_client_fixed_dhcp": ("set_client_fixed_dhcp", "clients"),
    "set_guest_wifi": ("set_guest_wifi", "wifi"),
    "set_hybrid_bonding": ("set_hybrid_bonding", "hybrid"),
    "set_internet_privacy_level": (
        "set_internet_privacy_level",
        "connection_privacy",
    ),
    "set_office_wifi": ("set_office_wifi", "wifi"),
    "set_port_forward_rule": ("set_port_forward_rule", "port_forwarding"),
    "set_receiver_led_mode": ("set_receiver_led_mode", "receiver"),
    "wifi_set_enabled": ("wifi_set_enabled", "wifi"),
    "wps": ("wps", "wps"),
    "wps_start": ("wps", "wps"),
}


def test_registry_covers_only_existing_commands_and_aliases() -> None:
    """Every existing command and alias resolves to its canonical contract."""
    assert set(COMMAND_WRITE_CONTRACTS) == set(_EXPECTED_COMMANDS)

    for name, (canonical, capability) in _EXPECTED_COMMANDS.items():
        contract = get_command_write_contract(name)
        assert contract is not None
        assert contract.command == canonical
        assert contract.capability == capability
        assert contract is get_command_write_contract(canonical)

    assert get_command_write_contract("factory_reset") is None


def test_read_only_management_telemetry_has_no_write_contracts() -> None:
    """Newly discovered management fields cannot become guessed commands."""
    pseudo_commands = {
        "set_connection_privacy",
        "set_dect",
        "set_dns_rebind",
        "set_easy_support",
        "set_firmware_automatic_updates",
        "set_nas",
        "set_pbx",
        "set_port_blocking",
        "set_qos",
        "set_receiver_mode",
        "set_telephony",
        "set_usb_tethering",
        "set_wifi_access",
        "set_wifi_band_mode",
        "set_wifi_schedule",
    }

    assert all(
        get_command_write_contract(command) is None for command in pseudo_commands
    )


def test_every_command_contract_contains_its_exact_firmware_gate() -> None:
    """Each command owns the exact router identity approved for that write."""
    expected_target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
    )

    for contract in COMMAND_WRITE_CONTRACTS.values():
        assert contract.supported_routers == frozenset({expected_target})
        assert contract.supports(" SPEEDPORT SMART 4R TYP A ", " 010152.5.0.001.0 ")
        assert not contract.supports("Speedport Smart 4R Typ A", "unreviewed")
        assert not contract.supports("Speedport Smart 4 Typ A", "010152.5.0.001.0")


def test_registry_and_contract_values_are_immutable() -> None:
    """Runtime code cannot widen the reviewed write boundary by mutation."""
    contract = COMMAND_WRITE_CONTRACTS["reboot"]

    with pytest.raises(TypeError):
        COMMAND_WRITE_CONTRACTS["factory_reset"] = contract  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        contract.capability = "factory_reset"  # type: ignore[misc]


def test_hub_uses_the_requested_commands_firmware_contract(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One command's reviewed firmware cannot authorize another command."""
    reviewed_target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
    )
    future_target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="future",
    )
    contracts = {
        "wifi_set_enabled": ManagementCommandContract(
            command="wifi_set_enabled",
            capability="wifi",
            supported_routers=frozenset({reviewed_target}),
        ),
        "reboot": ManagementCommandContract(
            command="reboot",
            capability="system",
            supported_routers=frozenset({future_target}),
        ),
    }
    monkeypatch.setattr(
        hub_module,
        "get_command_write_contract",
        contracts.get,
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    hub._router_info = router_info  # noqa: SLF001 - explicit safety boundary
    hub._capabilities = frozenset(  # noqa: SLF001 - explicit safety boundary
        {"authenticated_json", "system", "wifi"}
    )

    assert hub.supports_command("wifi_set_enabled")
    assert not hub.supports_command("reboot")
