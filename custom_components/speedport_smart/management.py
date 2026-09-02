"""Reviewed management command contracts for Speedport routers."""

from __future__ import annotations

import re
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


@unique
class ManagementInputKind(StrEnum):
    """Closed primitive vocabulary accepted by reviewed router writes."""

    BOOLEAN = "bool"
    INTEGER = "int"
    STRING = "str"
    ENUM = "enum"


@unique
class ManagementStringFormat(StrEnum):
    """Closed string validators shared by the hub and router client boundary."""

    NONBLANK = "nonblank"
    DEVICE_NAME = "device_name"
    NORMALIZED_MAC = "normalized_mac"
    LOWERCASE_SHA256 = "lowercase_sha256"


_DEVICE_NAME_PATTERN: Final = re.compile(r"[A-Za-z0-9-]{1,28}")
_NORMALIZED_MAC_PATTERN: Final = re.compile(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}")
_LOWERCASE_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ManagementInputSpec:
    """Type and optional closed bounds for one command parameter."""

    kind: ManagementInputKind
    allow_none: bool = False
    minimum: int | None = None
    maximum: int | None = None
    choices: frozenset[str | int] = frozenset()
    string_format: ManagementStringFormat | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous or internally inconsistent input declarations."""
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            msg = "Management input minimum cannot exceed maximum"
            raise ValueError(msg)
        if self.kind in {ManagementInputKind.BOOLEAN, ManagementInputKind.ENUM} and (
            self.minimum is not None or self.maximum is not None
        ):
            msg = "Only integer and string inputs can declare ranges"
            raise ValueError(msg)
        if self.kind is ManagementInputKind.ENUM:
            if not self.choices:
                msg = "Management enum inputs require explicit choices"
                raise ValueError(msg)
            choice_types = {type(choice) for choice in self.choices}
            if len(choice_types) != 1 or not choice_types <= {str, int}:
                msg = "Management enum choices require one exact string or integer type"
                raise ValueError(msg)
        elif self.choices:
            msg = "Only management enum inputs can declare choices"
            raise ValueError(msg)
        if (
            self.kind is not ManagementInputKind.STRING
            and self.string_format is not None
        ):
            msg = "Only management string inputs can declare a string format"
            raise ValueError(msg)
        if self.kind is ManagementInputKind.STRING and (
            (self.minimum is not None and self.minimum < 0)
            or (self.maximum is not None and self.maximum < 0)
        ):
            msg = "Management string length bounds cannot be negative"
            raise ValueError(msg)

    def accepts(self, value: object) -> bool:
        """Return whether one runtime value satisfies this exact input contract."""
        if value is None:
            return self.allow_none
        if self.kind is ManagementInputKind.BOOLEAN:
            return type(value) is bool
        if self.kind is ManagementInputKind.INTEGER:
            if type(value) is not int:
                return False
            return (self.minimum is None or value >= self.minimum) and (
                self.maximum is None or value <= self.maximum
            )
        if self.kind is ManagementInputKind.STRING:
            if type(value) is not str:
                return False
            if not (
                (self.minimum is None or len(value) >= self.minimum)
                and (self.maximum is None or len(value) <= self.maximum)
            ):
                return False
            if self.string_format is ManagementStringFormat.NONBLANK:
                return bool(value.strip())
            if self.string_format is ManagementStringFormat.DEVICE_NAME:
                return _DEVICE_NAME_PATTERN.fullmatch(value) is not None
            if self.string_format is ManagementStringFormat.NORMALIZED_MAC:
                return _NORMALIZED_MAC_PATTERN.fullmatch(value) is not None
            if self.string_format is ManagementStringFormat.LOWERCASE_SHA256:
                return _LOWERCASE_SHA256_PATTERN.fullmatch(value) is not None
            return True
        if not self.choices:
            return False
        choice_type = type(next(iter(self.choices)))
        return type(value) is choice_type and value in self.choices


@unique
class ManagementVerificationStrategy(StrEnum):
    """How the hub proves or safely defers one command's readback."""

    EXACT = "exact"
    REFRESH_ONLY = "refresh_only"
    DEFERRED = "deferred"


@unique
class ManagementVerificationCadence(StrEnum):
    """Runtime-independent refresh cadence required by one command contract."""

    FAST = "fast"
    NORMAL = "normal"
    SLOW = "slow"


@dataclass(frozen=True, slots=True)
class ManagementReadbackIdentity:
    """Map one command parameter to one normalized collection identity field."""

    field: str
    parameter: str
    ignore_when_none: bool = False

    def __post_init__(self) -> None:
        """Require static normalized field and command-parameter names."""
        if not self.field.isidentifier() or not self.parameter.isidentifier():
            msg = "Management readback identity names must be Python identifiers"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ManagementVerificationPolicy:
    """Hub-owned post-command refresh contract."""

    strategy: ManagementVerificationStrategy
    cadence: ManagementVerificationCadence | None
    readback_paths: tuple[str, ...] = ()
    expected_parameter: str | None = None
    collection_value_field: str | None = None
    collection_identity: tuple[ManagementReadbackIdentity, ...] = ()

    def __post_init__(self) -> None:
        """Require a concrete group and path for every immediate readback."""
        if self.strategy is ManagementVerificationStrategy.EXACT:
            if (
                self.cadence is None
                or len(self.readback_paths) != 1
                or self.expected_parameter is None
            ):
                msg = (
                    "Exact verification requires one readback path, a cadence, "
                    "and an expected parameter"
                )
                raise ValueError(msg)
            if self.collection_value_field is None and self.collection_identity:
                msg = "Scalar verification cannot declare collection identity"
                raise ValueError(msg)
            if self.collection_value_field is not None and not self.collection_identity:
                msg = "Collection verification requires stable identity fields"
                raise ValueError(msg)
            return
        if self.strategy is ManagementVerificationStrategy.REFRESH_ONLY:
            if self.cadence is None or not self.readback_paths:
                msg = "Refresh-only verification requires a cadence and readback path"
                raise ValueError(msg)
            if (
                self.expected_parameter is not None
                or self.collection_value_field is not None
                or self.collection_identity
            ):
                msg = "Refresh-only verification cannot declare an expected value"
                raise ValueError(msg)
            return
        if (
            self.cadence is not None
            or self.readback_paths
            or self.expected_parameter is not None
            or self.collection_value_field is not None
            or self.collection_identity
        ):
            msg = "Deferred verification cannot declare immediate readback metadata"
            raise ValueError(msg)


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
    input_specs: Mapping[str, ManagementInputSpec] | None = None
    verification: ManagementVerificationPolicy | None = None
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
        if self.input_specs is not None:
            if any(not name.isidentifier() for name in self.input_specs):
                msg = "Management input names must be Python identifiers"
                raise ValueError(msg)
            object.__setattr__(
                self,
                "input_specs",
                MappingProxyType(dict(self.input_specs)),
            )
        if self.execution_surface is ManagementExecutionSurface.NATIVE_ENTITY and (
            not self.supported_routers
            or self.feature_id is None
            or self.handler is None
            or self.input_specs is None
            or self.verification is None
        ):
            msg = (
                "Native management contracts require a feature, handler, exact "
                "inputs, and verification policy"
            )
            raise ValueError(msg)
        if self.input_specs is not None and self.verification is not None:
            expected_parameters = {
                parameter
                for parameter in (
                    self.verification.expected_parameter,
                    *(
                        identity.parameter
                        for identity in self.verification.collection_identity
                    ),
                )
                if parameter is not None
            }
            if not expected_parameters <= self.input_specs.keys():
                msg = "Management readback parameters must be declared command inputs"
                raise ValueError(msg)

    @property
    def parameter_names(self) -> frozenset[str] | None:
        """Return the exact handler parameter set for compatibility checks."""
        return frozenset(self.input_specs) if self.input_specs is not None else None

    def accepts_parameters(self, parameters: Mapping[str, object]) -> bool:
        """Validate exact names and primitive values before any router I/O."""
        if self.input_specs is None or set(parameters) != set(self.input_specs):
            return False
        return all(
            specification.accepts(parameters[name])
            for name, specification in self.input_specs.items()
        )

    def supports(self, model: str | None, firmware: str | None) -> bool:
        """Return whether this command was reviewed for the reported router."""
        return any(target.matches(model, firmware) for target in self.supported_routers)


_SPEEDPORT_SMART_4R_TYP_A_010152: Final = RouterWriteContract(
    model="Speedport Smart 4R Typ A",
    firmware="010152.5.0.001.0",
)
_SMART_4R_TYP_A_TARGETS: Final = frozenset({_SPEEDPORT_SMART_4R_TYP_A_010152})

_BOOL_INPUT: Final = ManagementInputSpec(ManagementInputKind.BOOLEAN)
_NONEMPTY_STRING_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    minimum=1,
    string_format=ManagementStringFormat.NONBLANK,
)
_NULLABLE_STRING_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    allow_none=True,
)
_MANAGED_SOURCE_KIND_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.ENUM,
    choices=frozenset(
        {
            "addmdevice",
            "addmlandevice",
            "addmwlandevice",
            "addmwlan5device",
        }
    ),
)
_THREE_STATE_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.ENUM,
    choices=frozenset({0, 1, 2}),
)
_DEVICE_NAME_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    minimum=1,
    maximum=28,
    string_format=ManagementStringFormat.DEVICE_NAME,
)
_NORMALIZED_MAC_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    string_format=ManagementStringFormat.NORMALIZED_MAC,
)
_SHA256_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    minimum=64,
    maximum=64,
    string_format=ManagementStringFormat.LOWERCASE_SHA256,
)


def _exact(
    cadence: ManagementVerificationCadence,
    readback_path: str,
    expected_parameter: str,
    *,
    collection_value_field: str | None = None,
    collection_identity: tuple[ManagementReadbackIdentity, ...] = (),
) -> ManagementVerificationPolicy:
    """Declare an immutable exact readback owned by the hub."""
    return ManagementVerificationPolicy(
        ManagementVerificationStrategy.EXACT,
        cadence,
        (readback_path,),
        expected_parameter=expected_parameter,
        collection_value_field=collection_value_field,
        collection_identity=collection_identity,
    )


def _refresh_only(
    cadence: ManagementVerificationCadence,
    *readback_paths: str,
) -> ManagementVerificationPolicy:
    """Declare a refresh for a transient action with no stable target value."""
    return ManagementVerificationPolicy(
        ManagementVerificationStrategy.REFRESH_ONLY,
        cadence,
        readback_paths,
    )


_DEFERRED_VERIFICATION: Final = ManagementVerificationPolicy(
    ManagementVerificationStrategy.DEFERRED,
    None,
)

_MANAGED_CLIENT_READBACK_IDENTITY: Final = (
    ManagementReadbackIdentity("source_kind", "source_kind"),
    ManagementReadbackIdentity("source_row_id", "row_id"),
    ManagementReadbackIdentity("mac", "stable_mac"),
)
_PORT_FORWARD_READBACK_IDENTITY: Final = (
    ManagementReadbackIdentity("id", "rule_id"),
    ManagementReadbackIdentity(
        "name",
        "expected_name",
        ignore_when_none=True,
    ),
    ManagementReadbackIdentity(
        "_identity_fingerprint",
        "expected_fingerprint",
    ),
)


def _contract(
    command: str,
    capability: str,
    feature_id: str,
    *aliases: str,
    supported_routers: frozenset[RouterWriteContract],
    handler: str,
    input_specs: Mapping[str, ManagementInputSpec],
    verification: ManagementVerificationPolicy,
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
        supported_routers=supported_routers,
        risk=risk,
        confirmation=confirmation,
        execution_surface=execution_surface,
        feature_id=feature_id,
        handler=handler,
        input_specs=input_specs,
        verification=verification,
        aliases=frozenset(aliases),
    )


_CONTRACTS: Final = (
    _contract(
        "rename_client",
        "clients",
        "network_client_rename",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="rename_client",
        input_specs={
            "source_kind": _MANAGED_SOURCE_KIND_INPUT,
            "row_id": _NONEMPTY_STRING_INPUT,
            "stable_mac": _NORMALIZED_MAC_INPUT,
            "name": _DEVICE_NAME_INPUT,
        },
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "clients.items",
            "name",
            collection_value_field="name",
            collection_identity=_MANAGED_CLIENT_READBACK_IDENTITY,
        ),
        risk=ManagementRisk.NORMAL,
        confirmation=ManagementConfirmation.NONE,
    ),
    _contract(
        "set_client_fixed_dhcp",
        "clients",
        "network_client_fixed_dhcp",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_client_fixed_dhcp",
        input_specs={
            "source_kind": _MANAGED_SOURCE_KIND_INPUT,
            "row_id": _NONEMPTY_STRING_INPUT,
            "stable_mac": _NORMALIZED_MAC_INPUT,
            "enabled": _BOOL_INPUT,
        },
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "clients.items",
            "enabled",
            collection_value_field="fixed_dhcp",
            collection_identity=_MANAGED_CLIENT_READBACK_IDENTITY,
        ),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_guest_wifi",
        "wifi",
        "network_wifi_guest",
        "guest_wifi_set_enabled",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_guest_wifi",
        input_specs={"enabled": _BOOL_INPUT},
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "wifi.guest.enabled",
            "enabled",
        ),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_hybrid_bonding",
        "hybrid",
        "internet_hybrid_bonding",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_hybrid_bonding",
        input_specs={"enabled": _BOOL_INPUT},
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "hybrid.enabled",
            "enabled",
        ),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_internet_privacy_level",
        "connection_privacy",
        "internet_privacy",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_internet_privacy_level",
        input_specs={"level": _THREE_STATE_INPUT},
        verification=_exact(
            ManagementVerificationCadence.SLOW,
            "internet.privacy_level",
            "level",
        ),
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_office_wifi",
        "wifi",
        "network_wifi_office",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_office_wifi",
        input_specs={"enabled": _BOOL_INPUT},
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "wifi.office.enabled",
            "enabled",
        ),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "wifi_set_enabled",
        "wifi",
        "network_wifi_main",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="execute_wifi_set_enabled",
        input_specs={"enabled": _BOOL_INPUT},
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "wifi.enabled",
            "enabled",
        ),
        risk=ManagementRisk.LOCKOUT,
        confirmation=ManagementConfirmation.TYPED,
    ),
    _contract(
        "set_receiver_led_mode",
        "receiver_led",
        "internet_receiver_led",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_receiver_led_mode",
        input_specs={"mode": _THREE_STATE_INPUT},
        verification=_exact(
            ManagementVerificationCadence.NORMAL,
            "receiver.led_mode",
            "mode",
        ),
        risk=ManagementRisk.NORMAL,
        confirmation=ManagementConfirmation.NONE,
    ),
    _contract(
        "reconnect",
        "internet",
        "internet_reconnect",
        "internet_reconnect",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="reconnect",
        input_specs={},
        verification=_DEFERRED_VERIFICATION,
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "set_port_forward_rule",
        "port_forwarding",
        "internet_port_forward_toggle",
        "port_mapping_set_enabled",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="set_port_forward_rule",
        input_specs={
            "rule_id": _NONEMPTY_STRING_INPUT,
            "enabled": _BOOL_INPUT,
            "expected_name": _NULLABLE_STRING_INPUT,
            "expected_fingerprint": _SHA256_INPUT,
        },
        verification=_exact(
            ManagementVerificationCadence.SLOW,
            "nat.port_forward_rules",
            "enabled",
            collection_value_field="active",
            collection_identity=_PORT_FORWARD_READBACK_IDENTITY,
        ),
        risk=ManagementRisk.SENSITIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "reboot",
        "system",
        "system_reboot",
        "router_reboot",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="reboot",
        input_specs={},
        verification=_DEFERRED_VERIFICATION,
        risk=ManagementRisk.DISRUPTIVE,
        confirmation=ManagementConfirmation.CONFIRM,
    ),
    _contract(
        "wps",
        "wps",
        "network_wifi_wps_start",
        "wps_start",
        supported_routers=_SMART_4R_TYP_A_TARGETS,
        handler="wps",
        input_specs={},
        verification=_refresh_only(
            ManagementVerificationCadence.NORMAL,
            "wifi.wps_status",
        ),
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
