"""Immutable contracts for administrator-only ephemeral router actions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, TypeGuard

from .management import (
    ManagementConfirmation,
    ManagementInputKind,
    ManagementInputSpec,
    ManagementRisk,
    RouterWriteContract,
)

if TYPE_CHECKING:
    from .models import CapabilityReport

_MIN_TYPED_CONFIRMATION_LENGTH: Final = 8
_MAX_TYPED_CONFIRMATION_LENGTH: Final = 64
_MAX_READBACK_ATTEMPTS: Final = 5
_MAX_READBACK_TOTAL_DELAY: Final = 15
_MAX_READBACK_DELAY: Final = 8
_ACTION_TOKEN_LENGTH: Final = 32
_MIN_ACTION_TOKEN_TTL_SECONDS: Final = 10
_MAX_ACTION_TOKEN_TTL_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class AdminActionCapabilityProof:
    """One exact authenticated endpoint identity required by an action."""

    family: str
    endpoint: str
    referer: str

    def is_proven_by(self, report: CapabilityReport | None) -> bool:
        """Return whether the current report contains this exact proof."""
        if report is None:
            return False
        capability = report.feature_endpoints.get(self.family)
        return bool(
            capability is not None
            and capability.endpoint == self.endpoint
            and capability.authenticated is True
            and capability.referer == self.referer
        )


@dataclass(frozen=True, slots=True)
class AdminActionContract:
    """One exact, non-persistent administrator action contract."""

    action: str
    feature_id: str
    endpoint: str
    referer: str
    supported_routers: frozenset[RouterWriteContract]
    capability_proofs: tuple[AdminActionCapabilityProof, ...]
    handler: str
    preflight_handler: str
    verification_handler: str
    input_specs: Mapping[str, ManagementInputSpec]
    preflight_parameters: tuple[str, ...]
    mutation_parameters: tuple[str, ...]
    verification_parameters: tuple[str, ...]
    expected_parameter: str | None
    expected_value: bool | None
    risk: ManagementRisk
    confirmation: ManagementConfirmation
    typed_confirmation: str | None = None
    target_query: str | None = None
    target_token_ttl_seconds: int | None = None
    target_id_parameter: str | None = None
    target_fingerprint_parameter: str | None = None
    target_context_specs: Mapping[str, ManagementInputSpec] = MappingProxyType({})
    target_projection_specs: Mapping[str, ManagementInputSpec] = MappingProxyType({})
    prerequisite: str | None = None
    already_expected_is_error: bool = False
    deletion_result: bool = False
    readback_delays: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

    def __post_init__(self) -> None:
        """Reject ambiguous action contracts at import time."""
        if not self.action.isidentifier() or self.action.casefold() != self.action:
            raise ValueError("Administrator action IDs must be lowercase identifiers")
        if (
            not self.feature_id.isidentifier()
            or self.feature_id.casefold() != self.feature_id
        ):
            raise ValueError("Administrator action feature IDs must be identifiers")
        if not self.supported_routers or not self.capability_proofs:
            raise ValueError("Administrator actions require router and endpoint proofs")
        if self.confirmation is ManagementConfirmation.NONE:
            raise ValueError("Administrator actions require server-side confirmation")
        if self.risk is ManagementRisk.DESTRUCTIVE and (
            self.confirmation is not ManagementConfirmation.TYPED
        ):
            raise ValueError(
                "Destructive administrator actions require typed confirmation"
            )
        if self.deletion_result and (
            self.risk is not ManagementRisk.DESTRUCTIVE
            or self.expected_parameter is not None
            or self.expected_value is not False
        ):
            raise ValueError("Deletion results require a destructive false target")
        if self.confirmation is ManagementConfirmation.TYPED:
            if (
                self.typed_confirmation is None
                or not self.typed_confirmation.isascii()
                or not _MIN_TYPED_CONFIRMATION_LENGTH
                <= len(self.typed_confirmation)
                <= _MAX_TYPED_CONFIRMATION_LENGTH
            ):
                raise ValueError(
                    "Typed administrator actions require one immutable phrase"
                )
        elif self.typed_confirmation is not None:
            raise ValueError("Confirm-only actions cannot declare a typed phrase")
        if self.target_query is not None and (
            not self.target_query.isidentifier()
            or self.target_query.casefold() != self.target_query
        ):
            raise ValueError("Administrator action target queries must be identifiers")
        target_fields = (
            self.target_id_parameter,
            self.target_fingerprint_parameter,
        )
        if self.target_query is None:
            if any(field is not None for field in target_fields) or (
                self.target_token_ttl_seconds is not None
            ):
                raise ValueError("Untargeted actions cannot declare target parameters")
        elif (
            any(field is None or not field.isidentifier() for field in target_fields)
            or len(set(target_fields)) != len(target_fields)
            or "target_token" not in self.input_specs
            or type(self.target_token_ttl_seconds) is not int
            or not _MIN_ACTION_TOKEN_TTL_SECONDS
            <= self.target_token_ttl_seconds
            <= _MAX_ACTION_TOKEN_TTL_SECONDS
        ):
            raise ValueError("Targeted actions require token and internal parameters")
        if not all(
            name.isidentifier()
            for name in (
                self.handler,
                self.preflight_handler,
                self.verification_handler,
            )
        ):
            raise ValueError("Administrator action handlers must be identifiers")
        inputs = MappingProxyType(dict(self.input_specs))
        object.__setattr__(self, "input_specs", inputs)
        context_specs = MappingProxyType(dict(self.target_context_specs))
        projection_specs = MappingProxyType(dict(self.target_projection_specs))
        object.__setattr__(self, "target_context_specs", context_specs)
        object.__setattr__(self, "target_projection_specs", projection_specs)
        if self.target_query is None and (context_specs or projection_specs):
            raise ValueError("Untargeted actions cannot declare target fields")
        if any(
            not name.isidentifier()
            for name in (*context_specs.keys(), *projection_specs.keys())
        ):
            raise ValueError("Administrator action target fields must be identifiers")
        if set(context_specs) & set(projection_specs):
            raise ValueError("Private and projected target fields cannot overlap")
        if set(context_specs) & (set(inputs) | set(target_fields)):
            raise ValueError("Private target fields cannot overlap action parameters")
        if {"target_id", "target_fingerprint", "target_token"} & set(projection_specs):
            raise ValueError("Projected target fields cannot use reserved names")
        parameter_names = (
            set(inputs)
            | {field for field in target_fields if field is not None}
            | set(context_specs)
        )
        for declared in (
            self.preflight_parameters,
            self.mutation_parameters,
            self.verification_parameters,
        ):
            if (
                len(set(declared)) != len(declared)
                or not set(declared) <= parameter_names
            ):
                raise ValueError(
                    "Administrator action handler parameters must be declared inputs"
                )
        if self.expected_parameter is not None:
            specification = inputs.get(self.expected_parameter)
            if (
                specification is None
                or specification.kind is not ManagementInputKind.BOOLEAN
            ):
                raise ValueError(
                    "Administrator action expected parameters must be Boolean inputs"
                )
            if self.expected_value is not None:
                raise ValueError(
                    "Administrator actions cannot mix parameter and fixed expectations"
                )
        elif type(self.expected_value) is not bool:
            raise ValueError(
                "Administrator actions require one exact Boolean expectation"
            )
        if (
            not self.readback_delays
            or self.readback_delays[0] != 0
            or len(self.readback_delays) > _MAX_READBACK_ATTEMPTS
            or sum(self.readback_delays) > _MAX_READBACK_TOTAL_DELAY
            or any(
                type(delay) is not float or not 0 <= delay <= _MAX_READBACK_DELAY
                for delay in self.readback_delays
            )
        ):
            raise ValueError("Administrator action readback must be strictly bounded")

    def supports(self, model: str | None, firmware: str | None) -> bool:
        """Return whether this action was reviewed for the exact router build."""
        return any(target.matches(model, firmware) for target in self.supported_routers)

    def accepts_parameters(self, parameters: Mapping[str, object]) -> bool:
        """Validate exact parameter names and primitive types before router I/O."""
        return set(parameters) == set(self.input_specs) and all(
            specification.accepts(parameters[name])
            and (not name.endswith("_id") or valid_target_id(parameters[name]))
            and (name != "target_token" or valid_action_token(parameters[name]))
            for name, specification in self.input_specs.items()
        )

    def proofs_satisfied(self, report: CapabilityReport | None) -> bool:
        """Return whether every endpoint and referer is currently proven."""
        return all(proof.is_proven_by(report) for proof in self.capability_proofs)

    def expected(self, parameters: Mapping[str, object]) -> bool:
        """Return the exact lifecycle value this action must independently prove."""
        if self.expected_parameter is None:
            return self.expected_value is True
        value = parameters[self.expected_parameter]
        if type(value) is not bool:
            raise ValueError("Administrator action expected value is not Boolean")
        return value


@dataclass(frozen=True, slots=True)
class AdminActionDecision:
    """Safe availability metadata for an administrator action."""

    configured: bool
    firmware_supported: bool
    capability_supported: bool
    handlers_available: bool
    session_available: bool

    @property
    def supported(self) -> bool:
        """Return whether the action has every static and runtime support proof."""
        return all(
            (
                self.configured,
                self.firmware_supported,
                self.capability_supported,
                self.handlers_available,
            )
        )

    @property
    def available(self) -> bool:
        """Return whether the action can execute at this instant."""
        return self.supported and self.session_available

    @property
    def unavailable_reason(self) -> str | None:
        """Return one closed, value-free reason code."""
        if not self.configured:
            return "controls_disabled"
        if not self.firmware_supported:
            return "unsupported_firmware"
        if not self.capability_supported:
            return "capability_not_proven"
        if not self.handlers_available:
            return "implementation_unavailable"
        if not self.session_available:
            return "management_unavailable"
        return None


_TARGET_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
ACTION_TOKEN_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    minimum=_ACTION_TOKEN_LENGTH,
    maximum=_ACTION_TOKEN_LENGTH,
)
BOOLEAN_INPUT: Final = ManagementInputSpec(ManagementInputKind.BOOLEAN)
REFERENCE_INPUT: Final = ManagementInputSpec(
    ManagementInputKind.STRING,
    minimum=1,
    maximum=32,
)

SPEEDPORT_SMART_4R_TYP_A_010152: Final = RouterWriteContract(
    model="Speedport Smart 4R Typ A",
    firmware="010152.5.0.001.0",
)
_TARGETS: Final = frozenset({SPEEDPORT_SMART_4R_TYP_A_010152})

DECT_MOBILES_REFERER: Final = "html/content/phone/phone_dect_mobiles.html"
DECT_REPEATER_REFERER: Final = "html/content/phone/phone_dect_repeater.html"
VOIP_REFERER: Final = "html/content/phone/phone_internet.html"
IP_PBX_REFERER: Final = "html/content/phone/phone_ippbx.html"
PHONEBOOK_REFERER: Final = "html/content/phone/phone_book.html"
NAS_SHARE_REFERER: Final = "html/content/network/nas_share.html"

DECT_STATION_PROOF: Final = AdminActionCapabilityProof(
    "dect",
    "data/DECTStation.json",
    DECT_MOBILES_REFERER,
)
DECT_STATUS_PROOF: Final = AdminActionCapabilityProof(
    "dect_status",
    "data/DECTInfo.json",
    DECT_MOBILES_REFERER,
)
DECT_REPEATER_PROOF: Final = AdminActionCapabilityProof(
    "dect_repeater",
    "data/DECTRepeater.json",
    DECT_REPEATER_REFERER,
)
VOIP_LINE_PROOF: Final = AdminActionCapabilityProof(
    "voip_lines",
    "data/IPPhoneNumbers.json",
    VOIP_REFERER,
)
VOIP_PROVIDER_PROOF: Final = AdminActionCapabilityProof(
    "voip_providers",
    "data/IPPhone.json",
    VOIP_REFERER,
)
IP_PBX_CLIENT_PROOF: Final = AdminActionCapabilityProof(
    "pbx_clients",
    "data/IPClients.json",
    IP_PBX_REFERER,
)
PHONEBOOK_PROOF: Final = AdminActionCapabilityProof(
    "phonebook",
    "data/PhoneBook.json",
    PHONEBOOK_REFERER,
)
NAS_SHARE_PROOF: Final = AdminActionCapabilityProof(
    "nas_folders",
    "data/NASFolder.json",
    NAS_SHARE_REFERER,
)


def valid_target_id(value: object) -> TypeGuard[str]:
    """Return whether a value is one bounded opaque firmware row ID."""
    return isinstance(value, str) and _TARGET_ID_PATTERN.fullmatch(value) is not None


def valid_action_token(value: object) -> TypeGuard[str]:
    """Return whether a value is one server-issued action token shape."""
    return (
        isinstance(value, str)
        and len(value) == _ACTION_TOKEN_LENGTH
        and value.isascii()
        and value.isalnum()
        and value.casefold() == value
        and all(character in "0123456789abcdef" for character in value)
    )


def _action(
    action: str,
    *,
    feature_id: str,
    endpoint: str,
    referer: str,
    capability_proofs: tuple[AdminActionCapabilityProof, ...],
    handler: str,
    preflight_handler: str,
    verification_handler: str,
    input_specs: Mapping[str, ManagementInputSpec],
    preflight_parameters: tuple[str, ...],
    mutation_parameters: tuple[str, ...],
    verification_parameters: tuple[str, ...],
    expected_parameter: str | None = None,
    expected_value: bool | None = None,
    risk: ManagementRisk = ManagementRisk.SENSITIVE,
    target_query: str | None = None,
    target_token_ttl_seconds: int | None = None,
    target_id_parameter: str | None = None,
    target_fingerprint_parameter: str | None = None,
    target_context_specs: Mapping[str, ManagementInputSpec] | None = None,
    target_projection_specs: Mapping[str, ManagementInputSpec] | None = None,
    prerequisite: str | None = None,
    already_expected_is_error: bool = False,
    deletion_result: bool = False,
    readback_delays: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0),
    confirmation: ManagementConfirmation = ManagementConfirmation.CONFIRM,
    typed_confirmation: str | None = None,
) -> AdminActionContract:
    """Build one immutable contract for the reviewed firmware."""
    return AdminActionContract(
        action=action,
        feature_id=feature_id,
        endpoint=endpoint,
        referer=referer,
        supported_routers=_TARGETS,
        capability_proofs=capability_proofs,
        handler=handler,
        preflight_handler=preflight_handler,
        verification_handler=verification_handler,
        input_specs=input_specs,
        preflight_parameters=preflight_parameters,
        mutation_parameters=mutation_parameters,
        verification_parameters=verification_parameters,
        expected_parameter=expected_parameter,
        expected_value=expected_value,
        risk=risk,
        confirmation=confirmation,
        typed_confirmation=typed_confirmation,
        target_query=target_query,
        target_token_ttl_seconds=target_token_ttl_seconds,
        target_id_parameter=target_id_parameter,
        target_fingerprint_parameter=target_fingerprint_parameter,
        target_context_specs=target_context_specs or {},
        target_projection_specs=target_projection_specs or {},
        prerequisite=prerequisite,
        already_expected_is_error=already_expected_is_error,
        deletion_result=deletion_result,
        readback_delays=readback_delays,
    )


ADMIN_ACTION_CONTRACTS: Final[Mapping[str, AdminActionContract]] = MappingProxyType(
    {
        contract.action: contract
        for contract in (
            _action(
                "dect_handset_enroll",
                feature_id="telephony_dect_handset_enrollment",
                endpoint="data/DECT.json",
                referer=DECT_MOBILES_REFERER,
                capability_proofs=(DECT_STATUS_PROOF,),
                handler="start_dect_handset_enrollment",
                preflight_handler="get_dect_scan_active",
                verification_handler="get_dect_scan_active",
                input_specs={},
                preflight_parameters=(),
                mutation_parameters=(),
                verification_parameters=(),
                expected_value=True,
                already_expected_is_error=True,
                readback_delays=(0.0, 1.0, 2.0, 4.0, 8.0),
            ),
            _action(
                "dect_repeater_enroll",
                feature_id="telephony_dect_repeater_enrollment",
                endpoint="data/DECTRepeater.json",
                referer=DECT_REPEATER_REFERER,
                capability_proofs=(DECT_STATUS_PROOF,),
                handler="start_dect_repeater_enrollment",
                preflight_handler="get_dect_repeater_scan_active",
                verification_handler="get_dect_repeater_scan_active",
                input_specs={
                    "pin_is_default": BOOLEAN_INPUT,
                    "full_power_enabled": BOOLEAN_INPUT,
                    "full_eco_disabled": BOOLEAN_INPUT,
                },
                preflight_parameters=(),
                mutation_parameters=(),
                verification_parameters=(),
                expected_value=True,
                prerequisite="dect_repeater_requirements",
                already_expected_is_error=True,
                readback_delays=(0.0, 1.0, 2.0, 4.0, 8.0),
            ),
            _action(
                "dect_handset_set_paging",
                feature_id="telephony_dect_handset_paging",
                endpoint="data/DECT.json",
                referer=DECT_MOBILES_REFERER,
                capability_proofs=(
                    DECT_STATION_PROOF,
                    DECT_STATUS_PROOF,
                ),
                handler="toggle_dect_handset_paging",
                preflight_handler="get_dect_handset_paging",
                verification_handler="get_dect_handset_paging",
                input_specs={
                    "target_token": ACTION_TOKEN_INPUT,
                    "enabled": BOOLEAN_INPUT,
                },
                preflight_parameters=("handset_id", "target_fingerprint"),
                mutation_parameters=("handset_id",),
                verification_parameters=("handset_id", "target_fingerprint"),
                expected_parameter="enabled",
                target_query="dect_handset_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="handset_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "paging": BOOLEAN_INPUT,
                    "name": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=1,
                        maximum=64,
                    ),
                },
            ),
            _action(
                "voip_line_set_active",
                feature_id="telephony_number_activation",
                endpoint="data/IPPhoneNumbers.json",
                referer=VOIP_REFERER,
                capability_proofs=(VOIP_LINE_PROOF,),
                handler="set_voip_line_active",
                preflight_handler="get_voip_line_active",
                verification_handler="get_voip_line_active",
                input_specs={
                    "target_token": ACTION_TOKEN_INPUT,
                    "active": BOOLEAN_INPUT,
                },
                preflight_parameters=("line_id", "target_fingerprint"),
                mutation_parameters=("line_id", "active"),
                verification_parameters=("line_id", "target_fingerprint"),
                expected_parameter="active",
                risk=ManagementRisk.DISRUPTIVE,
                target_query="voip_line_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="line_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "active": BOOLEAN_INPUT,
                    "number_suffix": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=4,
                        maximum=4,
                    ),
                },
            ),
            _action(
                "dect_handset_disconnect",
                feature_id="telephony_dect_handset_disconnect",
                endpoint="data/DECT.json",
                referer=DECT_MOBILES_REFERER,
                capability_proofs=(DECT_STATION_PROOF,),
                handler="disconnect_dect_handset",
                preflight_handler="get_dect_handset_present",
                verification_handler="get_dect_handset_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("handset_id", "target_fingerprint"),
                mutation_parameters=("handset_id",),
                verification_parameters=("handset_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DISCONNECT DECT HANDSET",
                deletion_result=True,
                target_query="dect_handset_disconnect_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="handset_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "name": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=1,
                        maximum=64,
                    ),
                },
                readback_delays=(0.0, 1.0, 2.0, 4.0, 8.0),
            ),
            _action(
                "dect_repeater_disconnect",
                feature_id="telephony_dect_repeater_disconnect",
                endpoint="data/DECTRepeater.json",
                referer=DECT_REPEATER_REFERER,
                capability_proofs=(DECT_REPEATER_PROOF,),
                handler="disconnect_dect_repeater",
                preflight_handler="get_dect_repeater_present",
                verification_handler="get_dect_repeater_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("repeater_id", "target_fingerprint"),
                mutation_parameters=("repeater_id",),
                verification_parameters=("repeater_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DISCONNECT DECT REPEATER",
                deletion_result=True,
                target_query="dect_repeater_disconnect_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="repeater_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                },
                readback_delays=(0.0, 1.0, 2.0, 4.0, 8.0),
            ),
            _action(
                "voip_provider_delete",
                feature_id="telephony_provider_delete",
                endpoint="data/IPPhone.json",
                referer=VOIP_REFERER,
                capability_proofs=(VOIP_PROVIDER_PROOF,),
                handler="delete_voip_provider",
                preflight_handler="get_voip_provider_present",
                verification_handler="get_voip_provider_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("provider_id", "target_fingerprint"),
                mutation_parameters=("provider_id",),
                verification_parameters=("provider_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DELETE VOIP PROVIDER",
                deletion_result=True,
                target_query="voip_provider_delete_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="provider_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "provider_code": ManagementInputSpec(
                        ManagementInputKind.INTEGER,
                        allow_none=True,
                        minimum=0,
                        maximum=9_999,
                    ),
                },
            ),
            _action(
                "voip_line_delete",
                feature_id="telephony_number_delete",
                endpoint="data/IPPhoneNumbers.json",
                referer=VOIP_REFERER,
                capability_proofs=(VOIP_LINE_PROOF,),
                handler="delete_voip_line",
                preflight_handler="get_voip_line_present",
                verification_handler="get_voip_line_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("line_id", "target_fingerprint"),
                mutation_parameters=("line_id",),
                verification_parameters=("line_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DELETE VOIP NUMBER",
                deletion_result=True,
                target_query="voip_line_delete_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="line_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "active": ManagementInputSpec(
                        ManagementInputKind.BOOLEAN,
                        allow_none=True,
                    ),
                    "number_suffix": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=4,
                        maximum=4,
                    ),
                },
            ),
            _action(
                "ip_pbx_client_delete",
                feature_id="telephony_ip_pbx_client_delete",
                endpoint="data/IPClients.json",
                referer=IP_PBX_REFERER,
                capability_proofs=(IP_PBX_CLIENT_PROOF,),
                handler="delete_ip_pbx_client",
                preflight_handler="get_ip_pbx_client_present",
                verification_handler="get_ip_pbx_client_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("client_id", "target_fingerprint"),
                mutation_parameters=("client_id",),
                verification_parameters=("client_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DELETE IP PBX CLIENT",
                deletion_result=True,
                target_query="ip_pbx_client_delete_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="client_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "name": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=1,
                        maximum=64,
                    ),
                    "status": ManagementInputSpec(
                        ManagementInputKind.ENUM,
                        allow_none=True,
                        choices=frozenset({"disconnected", "registered", "locked"}),
                    ),
                },
            ),
            _action(
                "phonebook_entry_delete",
                feature_id="telephony_phonebook_entry_delete",
                endpoint="data/PhoneBook.json",
                referer=PHONEBOOK_REFERER,
                capability_proofs=(PHONEBOOK_PROOF,),
                handler="delete_phonebook_entry",
                preflight_handler="get_phonebook_entry_present",
                verification_handler="get_phonebook_entry_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=(
                    "contact_id",
                    "target_fingerprint",
                    "phonebook_id",
                ),
                mutation_parameters=("contact_id", "phonebook_id"),
                verification_parameters=(
                    "contact_id",
                    "target_fingerprint",
                    "phonebook_id",
                ),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DELETE PHONEBOOK ENTRY",
                deletion_result=True,
                target_query="phonebook_entry_delete_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="contact_id",
                target_fingerprint_parameter="target_fingerprint",
                target_context_specs={
                    "phonebook_id": ManagementInputSpec(
                        ManagementInputKind.INTEGER,
                        minimum=0,
                        maximum=4,
                    ),
                },
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "display_name": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=1,
                        maximum=64,
                    ),
                },
            ),
            _action(
                "nas_share_delete",
                feature_id="storage_nas_share_delete",
                endpoint="data/NASFolder.json",
                referer=NAS_SHARE_REFERER,
                capability_proofs=(NAS_SHARE_PROOF,),
                handler="delete_nas_share",
                preflight_handler="get_nas_share_present",
                verification_handler="get_nas_share_present",
                input_specs={"target_token": ACTION_TOKEN_INPUT},
                preflight_parameters=("share_id", "target_fingerprint"),
                mutation_parameters=("share_id",),
                verification_parameters=("share_id", "target_fingerprint"),
                expected_value=False,
                risk=ManagementRisk.DESTRUCTIVE,
                confirmation=ManagementConfirmation.TYPED,
                typed_confirmation="DELETE NAS SHARE",
                deletion_result=True,
                target_query="nas_share_delete_targets",
                target_token_ttl_seconds=60,
                target_id_parameter="share_id",
                target_fingerprint_parameter="target_fingerprint",
                target_projection_specs={
                    "reference": REFERENCE_INPUT,
                    "name": ManagementInputSpec(
                        ManagementInputKind.STRING,
                        allow_none=True,
                        minimum=1,
                        maximum=64,
                    ),
                },
            ),
        )
    }
)


def get_admin_action_contract(action: str) -> AdminActionContract | None:
    """Return one reviewed administrator action contract."""
    return ADMIN_ACTION_CONTRACTS.get(action)
