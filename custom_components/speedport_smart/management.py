"""Reviewed management command contracts for Speedport routers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final


@unique
class ManagementRisk(StrEnum):
    """Stable risk tier for one reviewed router mutation."""

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    DISRUPTIVE = "disruptive"
    LOCKOUT = "lockout"
    DESTRUCTIVE = "destructive"


@unique
class ManagementConfirmation(StrEnum):
    """Dashboard confirmation presentation for one reviewed mutation."""

    NONE = "none"
    CONFIRM = "confirm"
    TYPED = "typed"


@unique
class ManagementExecutionSurface(StrEnum):
    """Backend surface allowed to expose one reviewed mutation."""

    NATIVE_ENTITY = "native_entity"
    ADMIN_ACTION = "admin_action"


@dataclass(frozen=True, slots=True)
class ManagementCommandDecision:
    """Orthogonal reasons one reviewed command can be shown or executed."""

    configured: bool
    authenticated_capability: bool
    contract_known: bool
    surface_allowed: bool
    firmware_supported: bool
    capability_supported: bool
    handler_available: bool
    session_available: bool

    @property
    def exposed(self) -> bool:
        """Return whether the command may exist as a Home Assistant control."""
        return all(
            (
                self.configured,
                self.contract_known,
                self.surface_allowed,
                self.firmware_supported,
                self.handler_available,
            )
        )

    @property
    def executable(self) -> bool:
        """Return whether current router session state also permits execution."""
        return (
            self.exposed
            and self.authenticated_capability
            and self.capability_supported
            and self.session_available
        )


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
    risk: ManagementRisk
    confirmation: ManagementConfirmation
    execution_surface: ManagementExecutionSurface
    feature_id: str | None = None
    handler: str | None = None
    parameter_names: frozenset[str] | None = None
    aliases: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Reject destructive commands that could bypass an admin action grant."""
        if self.risk is ManagementRisk.DESTRUCTIVE and (
            self.execution_surface is not ManagementExecutionSurface.ADMIN_ACTION
            or self.confirmation is not ManagementConfirmation.TYPED
        ):
            msg = "Destructive commands require a typed admin action surface"
            raise ValueError(msg)
        if self.feature_id is not None and (
            not self.feature_id
            or not self.feature_id.isascii()
            or not self.feature_id[0].isalpha()
            or not self.feature_id.replace("_", "").isalnum()
            or self.feature_id.casefold() != self.feature_id
        ):
            msg = "Management feature IDs must be lowercase semantic identifiers"
            raise ValueError(msg)
        if self.handler is not None and not self.handler.isidentifier():
            msg = "Management handlers must be Python identifiers"
            raise ValueError(msg)
        if self.execution_surface is ManagementExecutionSurface.NATIVE_ENTITY and (
            self.feature_id is None
            or self.handler is None
            or self.parameter_names is None
        ):
            msg = (
                "Native management contracts require a feature, handler, and exact "
                "parameter set"
            )
            raise ValueError(msg)

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
    feature_id: str,
    *aliases: str,
    handler: str,
    parameter_names: frozenset[str],
    risk: ManagementRisk,
    confirmation: ManagementConfirmation,
    execution_surface: ManagementExecutionSurface = (
        ManagementExecutionSurface.NATIVE_ENTITY
    ),
) -> ManagementCommandContract:
    """Build a command contract for the currently reviewed router firmware."""
    return ManagementCommandContract(
        command=command,
        capability=capability,
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        risk=risk,
        confirmation=confirmation,
        execution_surface=execution_surface,
        feature_id=feature_id,
        handler=handler,
        parameter_names=parameter_names,
        aliases=frozenset(aliases),
    )


_CONTRACTS: Final = (
    _contract(
        "rename_client",
        "clients",
        "network_client_rename",
        handler="rename_client",
        parameter_names=frozenset({"source_kind", "row_id", "stable_mac", "name"}),
        risk=ManagementRisk.NORMAL,
        confirmation=ManagementConfirmation.NONE,
    ),
    _contract(
        "set_client_fixed_dhcp",
        "clients",
        "network_client_fixed_dhcp",
        handler="set_client_fixed_dhcp",
        parameter_names=frozenset({"source_kind", "row_id", "stable_mac", "enabled"}),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_guest_wifi",
        "wifi",
        "network_wifi_guest",
        "guest_wifi_set_enabled",
        handler="set_guest_wifi",
        parameter_names=frozenset({"enabled"}),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_hybrid_bonding",
        "hybrid",
        "internet_hybrid_bonding",
        handler="set_hybrid_bonding",
        parameter_names=frozenset({"enabled"}),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_internet_privacy_level",
        "connection_privacy",
        "internet_privacy",
        handler="set_internet_privacy_level",
        parameter_names=frozenset({"level"}),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_office_wifi",
        "wifi",
        "network_wifi_office",
        handler="set_office_wifi",
        parameter_names=frozenset({"enabled"}),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "wifi_set_enabled",
        "wifi",
        "network_wifi_main",
        handler="execute_wifi_set_enabled",
        parameter_names=frozenset({"enabled"}),
        risk=ManagementRisk.LOCKOUT,
        confirmation=ManagementConfirmation.TYPED,
    ),
    _contract(
        "set_receiver_led_mode",
        "receiver",
        "internet_receiver_led",
        handler="set_receiver_led_mode",
        parameter_names=frozenset({"mode"}),
        risk=ManagementRisk.NORMAL,
        confirmation=ManagementConfirmation.NONE,
    ),
    _contract(
        "reconnect",
        "internet",
        "internet_reconnect",
        "internet_reconnect",
        handler="reconnect",
        parameter_names=frozenset(),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_port_forward_rule",
        "port_forwarding",
        "internet_port_forward_toggle",
        "port_mapping_set_enabled",
        handler="set_port_forward_rule",
        parameter_names=frozenset(
            {"rule_id", "enabled", "expected_name", "expected_fingerprint"}
        ),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "reboot",
        "system",
        "system_reboot",
        "router_reboot",
        handler="reboot",
        parameter_names=frozenset(),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "wps",
        "wps",
        "network_wifi_wps_start",
        "wps_start",
        handler="wps",
        parameter_names=frozenset(),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
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


_ENTITY_WRITE_COMMANDS: Final[Mapping[tuple[str, str], str]] = MappingProxyType(
    {
        ("button", "reboot_router"): "reboot",
        ("button", "reconnect_internet"): "reconnect",
        ("button", "wps"): "wps",
        ("select", "internet_privacy_level_control"): ("set_internet_privacy_level"),
        ("select", "receiver_led_mode_control"): "set_receiver_led_mode",
        ("switch", "client_fixed_dhcp"): "set_client_fixed_dhcp",
        ("switch", "guest_wifi"): "set_guest_wifi",
        ("switch", "hybrid_bonding"): "set_hybrid_bonding",
        ("switch", "office_wifi"): "set_office_wifi",
        ("switch", "port_forward_rule"): "set_port_forward_rule",
        ("switch", "wifi"): "wifi_set_enabled",
        ("text", "client_name"): "rename_client",
    }
)


def get_command_write_contract(command: str) -> ManagementCommandContract | None:
    """Return the reviewed contract for a command or alias."""
    return COMMAND_WRITE_CONTRACTS.get(command)


def get_entity_write_contract(
    domain: str,
    translation_key: str,
) -> ManagementCommandContract | None:
    """Return safety metadata for one exact Home Assistant control entity."""
    command = _ENTITY_WRITE_COMMANDS.get((domain, translation_key))
    contract = COMMAND_WRITE_CONTRACTS.get(command) if command is not None else None
    if (
        contract is None
        or contract.execution_surface is not ManagementExecutionSurface.NATIVE_ENTITY
    ):
        return None
    return contract
