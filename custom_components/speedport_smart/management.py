"""Reviewed management command contracts for Speedport routers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class RouterWriteContract:
    """One exact router model and firmware reviewed for write operations."""

    model: str
    firmware: str

    def matches(self, model: str | None, firmware: str | None) -> bool:
        """Return whether a reported router identity exactly matches this target."""
        return (model or "").strip().casefold() == self.model.casefold() and (
            firmware or ""
        ).strip().casefold() == self.firmware.casefold()


@dataclass(frozen=True, slots=True)
class ManagementCommandContract:
    """Capability and firmware boundary for one reviewed management command."""

    command: str
    capability: str
    supported_routers: frozenset[RouterWriteContract]
    aliases: frozenset[str] = frozenset()

    def supports(self, model: str | None, firmware: str | None) -> bool:
        """Return whether this command was reviewed for the reported router."""
        return any(target.matches(model, firmware) for target in self.supported_routers)


_SPEEDPORT_SMART_4R_TYP_A_010152: Final = RouterWriteContract(
    model="Speedport Smart 4R Typ A",
    firmware="010152.5.0.001.0",
)
_SMART_4R_TYP_A_TARGETS: Final = frozenset({_SPEEDPORT_SMART_4R_TYP_A_010152})


def _contract(
    command: str,
    capability: str,
    *aliases: str,
) -> ManagementCommandContract:
    """Build a command contract for the currently reviewed router firmware."""
    return ManagementCommandContract(
        command=command,
        capability=capability,
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        aliases=frozenset(aliases),
    )


_CONTRACTS: Final = (
    _contract("rename_client", "clients"),
    _contract("set_client_fixed_dhcp", "clients"),
    _contract("set_guest_wifi", "wifi", "guest_wifi_set_enabled"),
    _contract("set_hybrid_bonding", "hybrid"),
    _contract("set_internet_privacy_level", "connection_privacy"),
    _contract("set_office_wifi", "wifi"),
    _contract("wifi_set_enabled", "wifi"),
    _contract("set_receiver_led_mode", "receiver"),
    _contract("reconnect", "internet", "internet_reconnect"),
    _contract(
        "set_port_forward_rule",
        "port_forwarding",
        "port_mapping_set_enabled",
    ),
    _contract("reboot", "system", "router_reboot"),
    _contract("wps", "wps", "wps_start"),
)


def _build_registry() -> Mapping[str, ManagementCommandContract]:
    """Index canonical commands and aliases without permitting duplicate names."""
    registry: dict[str, ManagementCommandContract] = {}
    for contract in _CONTRACTS:
        for command in (contract.command, *contract.aliases):
            if command in registry:
                msg = f"Duplicate management command contract: {command}"
                raise ValueError(msg)
            registry[command] = contract
    return MappingProxyType(registry)


COMMAND_WRITE_CONTRACTS: Final[Mapping[str, ManagementCommandContract]] = (
    _build_registry()
)


def get_command_write_contract(command: str) -> ManagementCommandContract | None:
    """Return the reviewed contract for a command or alias."""
    return COMMAND_WRITE_CONTRACTS.get(command)
