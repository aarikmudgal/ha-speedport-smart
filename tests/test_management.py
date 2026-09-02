"""Tests for reviewed management command contracts."""

from __future__ import annotations

import importlib.util
import inspect
import sys
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.speedport_smart import hub as hub_module
from custom_components.speedport_smart import management as management_module
from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.management import (
    COMMAND_WRITE_CONTRACTS,
    ManagementCommandContract,
    ManagementCommandDecision,
    ManagementConfirmation,
    ManagementExecutionSurface,
    ManagementInputKind,
    ManagementInputSpec,
    ManagementReadbackIdentity,
    ManagementRisk,
    ManagementStringFormat,
    ManagementVerificationCadence,
    ManagementVerificationPolicy,
    ManagementVerificationStrategy,
    RouterWriteContract,
    get_command_write_contract,
    get_entity_write_contract,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import RouterInfo


_EXPECTED_CANONICAL_COMMANDS = {
    "reboot": (
        "system",
        frozenset({"router_reboot"}),
        ManagementRisk.DISRUPTIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "reconnect": (
        "internet",
        frozenset({"internet_reconnect"}),
        ManagementRisk.DISRUPTIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "rename_client": (
        "clients",
        frozenset(),
        ManagementRisk.NORMAL,
        ManagementConfirmation.NONE,
    ),
    "set_client_fixed_dhcp": (
        "clients",
        frozenset(),
        ManagementRisk.SENSITIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_guest_wifi": (
        "wifi",
        frozenset({"guest_wifi_set_enabled"}),
        ManagementRisk.SENSITIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_hybrid_bonding": (
        "hybrid",
        frozenset(),
        ManagementRisk.DISRUPTIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_internet_privacy_level": (
        "connection_privacy",
        frozenset(),
        ManagementRisk.DISRUPTIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_office_wifi": (
        "wifi",
        frozenset(),
        ManagementRisk.SENSITIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_port_forward_rule": (
        "port_forwarding",
        frozenset({"port_mapping_set_enabled"}),
        ManagementRisk.SENSITIVE,
        ManagementConfirmation.CONFIRM,
    ),
    "set_receiver_led_mode": (
        "receiver",
        frozenset(),
        ManagementRisk.NORMAL,
        ManagementConfirmation.NONE,
    ),
    "wifi_set_enabled": (
        "wifi",
        frozenset(),
        ManagementRisk.LOCKOUT,
        ManagementConfirmation.TYPED,
    ),
    "wps": (
        "wps",
        frozenset({"wps_start"}),
        ManagementRisk.SENSITIVE,
        ManagementConfirmation.CONFIRM,
    ),
}

_EXPECTED_ENTITY_COMMANDS = {
    ("button", "reboot_router"): "reboot",
    ("button", "reconnect_internet"): "reconnect",
    ("button", "wps"): "wps",
    ("select", "internet_privacy_level_control"): "set_internet_privacy_level",
    ("select", "receiver_led_mode_control"): "set_receiver_led_mode",
    ("switch", "client_fixed_dhcp"): "set_client_fixed_dhcp",
    ("switch", "guest_wifi"): "set_guest_wifi",
    ("switch", "hybrid_bonding"): "set_hybrid_bonding",
    ("switch", "office_wifi"): "set_office_wifi",
    ("switch", "port_forward_rule"): "set_port_forward_rule",
    ("switch", "wifi"): "wifi_set_enabled",
    ("text", "client_name"): "rename_client",
}

_EXPECTED_FEATURES = {
    "reboot": "system_reboot",
    "reconnect": "internet_reconnect",
    "rename_client": "network_client_rename",
    "set_client_fixed_dhcp": "network_client_fixed_dhcp",
    "set_guest_wifi": "network_wifi_guest",
    "set_hybrid_bonding": "internet_hybrid_bonding",
    "set_internet_privacy_level": "internet_privacy",
    "set_office_wifi": "network_wifi_office",
    "set_port_forward_rule": "internet_port_forward_toggle",
    "set_receiver_led_mode": "internet_receiver_led",
    "wifi_set_enabled": "network_wifi_main",
    "wps": "network_wifi_wps_start",
}

_EXPECTED_EXECUTION = {
    "reboot": ("reboot", frozenset()),
    "reconnect": ("reconnect", frozenset()),
    "rename_client": (
        "rename_client",
        frozenset({"source_kind", "row_id", "stable_mac", "name"}),
    ),
    "set_client_fixed_dhcp": (
        "set_client_fixed_dhcp",
        frozenset({"source_kind", "row_id", "stable_mac", "enabled"}),
    ),
    "set_guest_wifi": ("set_guest_wifi", frozenset({"enabled"})),
    "set_hybrid_bonding": ("set_hybrid_bonding", frozenset({"enabled"})),
    "set_internet_privacy_level": (
        "set_internet_privacy_level",
        frozenset({"level"}),
    ),
    "set_office_wifi": ("set_office_wifi", frozenset({"enabled"})),
    "set_port_forward_rule": (
        "set_port_forward_rule",
        frozenset({"rule_id", "enabled", "expected_name", "expected_fingerprint"}),
    ),
    "set_receiver_led_mode": ("set_receiver_led_mode", frozenset({"mode"})),
    "wifi_set_enabled": ("execute_wifi_set_enabled", frozenset({"enabled"})),
    "wps": ("wps", frozenset()),
}

_EXPECTED_VERIFICATION = {
    "reboot": (None, ()),
    "reconnect": (None, ()),
    "rename_client": (ManagementVerificationCadence.NORMAL, ("clients.items",)),
    "set_client_fixed_dhcp": (
        ManagementVerificationCadence.NORMAL,
        ("clients.items",),
    ),
    "set_guest_wifi": (
        ManagementVerificationCadence.NORMAL,
        ("wifi.guest.enabled",),
    ),
    "set_hybrid_bonding": (
        ManagementVerificationCadence.NORMAL,
        ("hybrid.enabled",),
    ),
    "set_internet_privacy_level": (
        ManagementVerificationCadence.SLOW,
        ("internet.privacy_level",),
    ),
    "set_office_wifi": (
        ManagementVerificationCadence.NORMAL,
        ("wifi.office.enabled",),
    ),
    "set_port_forward_rule": (
        ManagementVerificationCadence.SLOW,
        ("nat.port_forward_rules",),
    ),
    "set_receiver_led_mode": (
        ManagementVerificationCadence.NORMAL,
        ("receiver.led_mode",),
    ),
    "wifi_set_enabled": (
        ManagementVerificationCadence.NORMAL,
        ("wifi.enabled",),
    ),
    "wps": (ManagementVerificationCadence.NORMAL, ("wifi.wps_status",)),
}

_EXPECTED_VALUE_PARAMETERS = {
    "rename_client": ("name", "name"),
    "set_client_fixed_dhcp": ("enabled", "fixed_dhcp"),
    "set_guest_wifi": ("enabled", None),
    "set_hybrid_bonding": ("enabled", None),
    "set_internet_privacy_level": ("level", None),
    "set_office_wifi": ("enabled", None),
    "set_port_forward_rule": ("enabled", "active"),
    "set_receiver_led_mode": ("mode", None),
    "wifi_set_enabled": ("enabled", None),
}

_VALID_PARAMETERS = {
    "reboot": {},
    "reconnect": {},
    "rename_client": {
        "source_kind": "addmdevice",
        "row_id": "7",
        "stable_mac": "00:11:22:33:44:55",
        "name": "Living-Room",
    },
    "set_client_fixed_dhcp": {
        "source_kind": "addmwlandevice",
        "row_id": "7",
        "stable_mac": "00:11:22:33:44:55",
        "enabled": True,
    },
    "set_guest_wifi": {"enabled": True},
    "set_hybrid_bonding": {"enabled": False},
    "set_internet_privacy_level": {"level": 2},
    "set_office_wifi": {"enabled": True},
    "set_port_forward_rule": {
        "rule_id": "3",
        "enabled": False,
        "expected_name": None,
        "expected_fingerprint": "a" * 64,
    },
    "set_receiver_led_mode": {"mode": 0},
    "wifi_set_enabled": {"enabled": True},
    "wps": {},
}


def test_registry_covers_only_existing_commands_and_aliases() -> None:
    """Every existing command and alias resolves to its canonical contract."""
    expected_names = set(_EXPECTED_CANONICAL_COMMANDS)
    expected_names.update(
        alias
        for _capability, aliases, _risk, _confirmation in (
            _EXPECTED_CANONICAL_COMMANDS.values()
        )
        for alias in aliases
    )
    assert set(COMMAND_WRITE_CONTRACTS) == expected_names

    for canonical, (
        capability,
        aliases,
        risk,
        confirmation,
    ) in _EXPECTED_CANONICAL_COMMANDS.items():
        contract = get_command_write_contract(canonical)
        assert contract is not None
        assert contract.command == canonical
        assert contract.capability == capability
        assert contract.aliases == aliases
        assert contract.risk is risk
        assert contract.confirmation is confirmation
        assert contract.execution_surface is ManagementExecutionSurface.NATIVE_ENTITY
        assert contract.feature_id == _EXPECTED_FEATURES[canonical]
        assert (contract.handler, contract.parameter_names) == _EXPECTED_EXECUTION[
            canonical
        ]
        assert contract.verification is not None
        expected_cadence, expected_paths = _EXPECTED_VERIFICATION[canonical]
        assert contract.verification.cadence is expected_cadence
        assert contract.verification.readback_paths == expected_paths
        if expected_cadence is None:
            assert (
                contract.verification.strategy
                is ManagementVerificationStrategy.DEFERRED
            )
        elif canonical == "wps":
            assert (
                contract.verification.strategy
                is ManagementVerificationStrategy.REFRESH_ONLY
            )
        else:
            assert (
                contract.verification.strategy is ManagementVerificationStrategy.EXACT
            )
            expected_parameter, collection_field = _EXPECTED_VALUE_PARAMETERS[canonical]
            assert contract.verification.expected_parameter == expected_parameter
            assert contract.verification.collection_value_field == collection_field
            assert all(
                isinstance(identity, ManagementReadbackIdentity)
                for identity in contract.verification.collection_identity
            )
            assert bool(contract.verification.collection_identity) is (
                collection_field is not None
            )
        for alias in aliases:
            assert get_command_write_contract(alias) is contract
    assert get_command_write_contract("factory_reset") is None


def test_management_contract_registry_loads_without_package_context() -> None:
    """Parity tooling can inspect contracts without importing HA runtime modules."""
    module_path = management_module.__file__
    assert module_path is not None
    spec = importlib.util.spec_from_file_location(
        "speedport_management_standalone_test",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    standalone_contracts = module.COMMAND_WRITE_CONTRACTS
    assert set(standalone_contracts) == set(COMMAND_WRITE_CONTRACTS)


def test_safety_metadata_vocabulary_is_stable_and_complete() -> None:
    """Future controls can rely on one closed risk and confirmation vocabulary."""
    assert {risk.value for risk in ManagementRisk} == {
        "normal",
        "sensitive",
        "disruptive",
        "lockout",
        "destructive",
    }
    assert {confirmation.value for confirmation in ManagementConfirmation} == {
        "none",
        "confirm",
        "typed",
    }
    assert {surface.value for surface in ManagementExecutionSurface} == {
        "native_entity",
        "admin_action",
    }
    assert {kind.value for kind in ManagementInputKind} == {
        "bool",
        "int",
        "str",
        "enum",
    }
    assert {string_format.value for string_format in ManagementStringFormat} == {
        "nonblank",
        "device_name",
        "normalized_mac",
        "lowercase_sha256",
    }
    assert {strategy.value for strategy in ManagementVerificationStrategy} == {
        "exact",
        "refresh_only",
        "deferred",
    }
    assert {cadence.value for cadence in ManagementVerificationCadence} == {
        "fast",
        "normal",
        "slow",
    }


def test_command_decision_keeps_exposure_and_session_availability_separate() -> None:
    """A temporary browser session conflict cannot erase supported controls."""
    supported_but_busy = ManagementCommandDecision(
        configured=True,
        authenticated_capability=False,
        contract_known=True,
        surface_allowed=True,
        firmware_supported=True,
        capability_supported=True,
        handler_available=True,
        session_available=False,
    )

    assert supported_but_busy.exposed is True
    assert supported_but_busy.executable is False
    assert (
        ManagementCommandDecision(
            configured=False,
            authenticated_capability=True,
            contract_known=True,
            surface_allowed=True,
            firmware_supported=True,
            capability_supported=True,
            handler_available=True,
            session_available=True,
        ).exposed
        is False
    )


def test_reviewed_firmware_keeps_native_controls_visible_without_session(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """A temporary protected-session loss changes availability, not discovery."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    hub._router_info = router_info  # noqa: SLF001 - exact reviewed identity
    hub._capabilities = frozenset({"status", "system"})  # noqa: SLF001
    hub._mark_management_unavailable()  # noqa: SLF001 - simulate GUI ownership

    decision = hub.command_decision("wifi_set_enabled")

    assert decision.authenticated_capability is False
    assert decision.firmware_supported is True
    assert decision.capability_supported is False
    assert decision.exposed is True
    assert decision.executable is False


def test_entity_controls_resolve_only_to_reviewed_write_contracts() -> None:
    """Panel safety metadata cannot invent a command from an entity domain."""
    assert set(_EXPECTED_ENTITY_COMMANDS.values()) == set(_EXPECTED_CANONICAL_COMMANDS)
    for entity_key, command in _EXPECTED_ENTITY_COMMANDS.items():
        assert get_entity_write_contract(*entity_key) is get_command_write_contract(
            command
        )

    for entity_key in (
        ("button", "factory_reset"),
        ("switch", "upnp"),
        ("text", "router_password"),
        ("update", "firmware"),
    ):
        assert get_entity_write_contract(*entity_key) is None


def test_every_native_contract_is_complete_and_matches_client_signature() -> None:
    """A native control owns one exact semantic handler and parameter set."""
    canonical_contracts = {
        contract.command: contract for contract in COMMAND_WRITE_CONTRACTS.values()
    }
    for contract in canonical_contracts.values():
        assert contract.feature_id is not None
        assert contract.handler is not None
        assert contract.parameter_names is not None
        handler = getattr(SpeedportClient, contract.handler)
        signature = inspect.signature(handler)
        actual_parameters = frozenset(
            name
            for name, parameter in signature.parameters.items()
            if name != "self"
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        assert actual_parameters == contract.parameter_names


def test_every_native_contract_owns_typed_runtime_inputs() -> None:
    """Current commands accept their exact valid values and reject type widening."""
    canonical_contracts = {
        contract.command: contract for contract in COMMAND_WRITE_CONTRACTS.values()
    }
    assert set(canonical_contracts) == set(_VALID_PARAMETERS)

    for command, parameters in _VALID_PARAMETERS.items():
        contract = canonical_contracts[command]
        assert contract.accepts_parameters(parameters)
        if not parameters:
            assert not contract.accepts_parameters({"unexpected": True})
            continue
        first_name = next(iter(parameters))
        wrong_type = dict(parameters)
        wrong_type[first_name] = object()
        assert not contract.accepts_parameters(wrong_type)
        assert not contract.accepts_parameters(
            {name: value for name, value in parameters.items() if name != first_name}
        )


def test_input_specs_enforce_bool_int_string_enum_and_ranges() -> None:
    """Primitive types are exact, including bool/int separation and closed bounds."""
    boolean = ManagementInputSpec(ManagementInputKind.BOOLEAN)
    integer = ManagementInputSpec(ManagementInputKind.INTEGER, minimum=1, maximum=3)
    string = ManagementInputSpec(ManagementInputKind.STRING, minimum=2, maximum=4)
    enum = ManagementInputSpec(
        ManagementInputKind.ENUM,
        choices=frozenset({"one", "two"}),
    )
    nullable = ManagementInputSpec(ManagementInputKind.STRING, allow_none=True)

    assert boolean.accepts(value=True)
    assert not boolean.accepts(1)
    assert integer.accepts(2)
    assert not integer.accepts(value=True)
    assert not integer.accepts(0)
    assert string.accepts("abc")
    assert not string.accepts("a")
    assert enum.accepts("one")
    assert not enum.accepts("three")
    assert nullable.accepts(None)


def test_string_formats_match_client_facing_write_constraints() -> None:
    """Formatted strings fail before the client can perform a pre-read."""
    nonblank = ManagementInputSpec(
        ManagementInputKind.STRING,
        string_format=ManagementStringFormat.NONBLANK,
    )
    device_name = ManagementInputSpec(
        ManagementInputKind.STRING,
        string_format=ManagementStringFormat.DEVICE_NAME,
    )
    normalized_mac = ManagementInputSpec(
        ManagementInputKind.STRING,
        string_format=ManagementStringFormat.NORMALIZED_MAC,
    )
    fingerprint = ManagementInputSpec(
        ManagementInputKind.STRING,
        string_format=ManagementStringFormat.LOWERCASE_SHA256,
    )

    assert nonblank.accepts(" 7 ")
    assert not nonblank.accepts(" \t")
    assert device_name.accepts("Living-Room-7")
    assert not device_name.accepts("Living Room")
    assert not device_name.accepts("a" * 29)
    assert normalized_mac.accepts("00:11:22:AA:BB:CC")
    assert not normalized_mac.accepts("00-11-22-AA-BB-CC")
    assert not normalized_mac.accepts("00:11:22:aa:bb:cc")
    assert fingerprint.accepts("a" * 64)
    assert not fingerprint.accepts("A" * 64)
    assert not fingerprint.accepts("g" * 64)


def test_verification_policies_reject_ambiguous_declarations() -> None:
    """A command cannot silently mix immediate and deferred verification."""
    with pytest.raises(ValueError, match="requires one readback path"):
        ManagementVerificationPolicy(
            ManagementVerificationStrategy.EXACT,
            None,
        )
    with pytest.raises(ValueError, match="requires stable identity"):
        ManagementVerificationPolicy(
            ManagementVerificationStrategy.EXACT,
            ManagementVerificationCadence.NORMAL,
            ("clients.items",),
            expected_parameter="enabled",
            collection_value_field="fixed_dhcp",
        )
    with pytest.raises(ValueError, match="cannot declare an expected value"):
        ManagementVerificationPolicy(
            ManagementVerificationStrategy.REFRESH_ONLY,
            ManagementVerificationCadence.NORMAL,
            ("wifi.wps_status",),
            expected_parameter="enabled",
        )
    with pytest.raises(ValueError, match="cannot declare immediate readback"):
        ManagementVerificationPolicy(
            ManagementVerificationStrategy.DEFERRED,
            ManagementVerificationCadence.NORMAL,
            ("wifi.enabled",),
        )


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


def test_destructive_commands_cannot_use_native_entity_surface() -> None:
    """Destructive work must use a future admin-only one-time grant flow."""
    target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
    )

    with pytest.raises(
        ValueError,
        match="Destructive commands require a typed admin action surface",
    ):
        ManagementCommandContract(
            command="factory_reset",
            capability="system",
            supported_routers=frozenset({target}),
            risk=ManagementRisk.DESTRUCTIVE,
            confirmation=ManagementConfirmation.TYPED,
            execution_surface=ManagementExecutionSurface.NATIVE_ENTITY,
        )

    contract = ManagementCommandContract(
        command="factory_reset",
        capability="system",
        supported_routers=frozenset({target}),
        risk=ManagementRisk.DESTRUCTIVE,
        confirmation=ManagementConfirmation.TYPED,
        execution_surface=ManagementExecutionSurface.ADMIN_ACTION,
    )
    assert contract.execution_surface is ManagementExecutionSurface.ADMIN_ACTION


def test_native_contracts_require_complete_execution_metadata() -> None:
    """A native entity cannot rely on inferred placement or handler arguments."""
    target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
    )
    with pytest.raises(
        ValueError,
        match="require a feature, handler, exact inputs, and verification policy",
    ):
        ManagementCommandContract(
            command="example",
            capability="system",
            supported_routers=frozenset({target}),
            risk=ManagementRisk.NORMAL,
            confirmation=ManagementConfirmation.NONE,
            execution_surface=ManagementExecutionSurface.NATIVE_ENTITY,
        )


@pytest.mark.parametrize(
    "feature_id",
    ["", "1wifi", "Network_Wifi", "network-wifi", "wifi settings", "wïfi"],
)
def test_management_feature_ids_are_stable_semantic_identifiers(
    feature_id: str,
) -> None:
    """Panel placement IDs cannot depend on display text or punctuation."""
    target = RouterWriteContract(
        model="Speedport Smart 4R Typ A",
        firmware="010152.5.0.001.0",
    )
    with pytest.raises(
        ValueError,
        match="Management feature IDs must be lowercase semantic identifiers",
    ):
        ManagementCommandContract(
            command="example",
            capability="system",
            supported_routers=frozenset({target}),
            risk=ManagementRisk.NORMAL,
            confirmation=ManagementConfirmation.NONE,
            execution_surface=ManagementExecutionSurface.NATIVE_ENTITY,
            feature_id=feature_id,
        )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(("reboot", "system"), id="button"),
        pytest.param(("wifi_set_enabled", "wifi"), id="switch"),
        pytest.param(
            ("set_receiver_led_mode", "receiver"),
            id="select",
        ),
        pytest.param(("rename_client", "clients"), id="text"),
    ],
)
async def test_admin_actions_cannot_use_native_entity_command_gate(
    case: tuple[str, str],
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native entity discovery and execution reject admin-only contracts."""
    command, capability = case
    contract = ManagementCommandContract(
        command=command,
        capability=capability,
        supported_routers=frozenset(
            {
                RouterWriteContract(
                    model="Speedport Smart 4R Typ A",
                    firmware="010152.5.0.001.0",
                )
            }
        ),
        risk=ManagementRisk.DESTRUCTIVE,
        confirmation=ManagementConfirmation.TYPED,
        execution_surface=ManagementExecutionSurface.ADMIN_ACTION,
    )
    monkeypatch.setattr(
        hub_module,
        "get_command_write_contract",
        lambda requested: contract if requested == command else None,
    )
    handler = AsyncMock()
    setattr(mock_speedport_client, command, handler)
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    hub._router_info = router_info  # noqa: SLF001 - explicit safety boundary
    hub._capabilities = frozenset(  # noqa: SLF001 - explicit safety boundary
        {"authenticated_json", capability}
    )

    assert not hub.supports_command(command)
    with pytest.raises(HomeAssistantError, match="does not support"):
        await hub.async_execute(command, verify_group=None)
    handler.assert_not_awaited()


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
    with pytest.raises(FrozenInstanceError):
        contract.risk = ManagementRisk.DESTRUCTIVE  # type: ignore[misc]

    wifi = COMMAND_WRITE_CONTRACTS["wifi_set_enabled"]
    assert wifi.input_specs is not None
    with pytest.raises(TypeError):
        wifi.input_specs["enabled"] = ManagementInputSpec(  # type: ignore[index]
            ManagementInputKind.STRING
        )


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
            risk=ManagementRisk.LOCKOUT,
            confirmation=ManagementConfirmation.TYPED,
            execution_surface=ManagementExecutionSurface.NATIVE_ENTITY,
            feature_id="network_wifi_main",
            handler="execute_wifi_set_enabled",
            input_specs={"enabled": ManagementInputSpec(ManagementInputKind.BOOLEAN)},
            verification=ManagementVerificationPolicy(
                ManagementVerificationStrategy.EXACT,
                ManagementVerificationCadence.NORMAL,
                ("wifi.enabled",),
                expected_parameter="enabled",
            ),
        ),
        "reboot": ManagementCommandContract(
            command="reboot",
            capability="system",
            supported_routers=frozenset({future_target}),
            risk=ManagementRisk.DISRUPTIVE,
            confirmation=ManagementConfirmation.CONFIRM,
            execution_surface=ManagementExecutionSurface.NATIVE_ENTITY,
            feature_id="system_reboot",
            handler="reboot",
            input_specs={},
            verification=ManagementVerificationPolicy(
                ManagementVerificationStrategy.DEFERRED,
                None,
            ),
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

    wifi_decision = hub.command_decision("wifi_set_enabled")
    reboot_decision = hub.command_decision("reboot")
    assert wifi_decision.exposed is True
    assert wifi_decision.contract_known is True
    assert wifi_decision.firmware_supported is True
    assert reboot_decision.exposed is False
    assert reboot_decision.contract_known is True
    assert reboot_decision.firmware_supported is False
