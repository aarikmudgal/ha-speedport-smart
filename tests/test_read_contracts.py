"""Conformance tests for the explicit normalized native read registry."""

from __future__ import annotations

import re
from types import MappingProxyType

from custom_components.speedport_smart.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
)
from custom_components.speedport_smart.read_contracts import (
    NATIVE_SCALAR_READ_CONTRACTS,
    NATIVE_SCALAR_READ_PATHS,
    NativeReadContractId,
    NativeReadPlatform,
    NativeScalarReadContract,
)
from custom_components.speedport_smart.sensor import SENSOR_DESCRIPTIONS

_NORMALIZED_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _capabilities(value: str | tuple[str, ...]) -> tuple[str, ...]:
    """Return a stable tuple for one entity description's capability gate."""
    return (value,) if isinstance(value, str) else value


def _platform_contracts() -> dict[NativeReadContractId, NativeScalarReadContract]:
    """Project the runtime descriptions into the independent contract shape."""
    contracts: dict[NativeReadContractId, NativeScalarReadContract] = {}
    for platform, descriptions in (
        (NativeReadPlatform.SENSOR, SENSOR_DESCRIPTIONS),
        (NativeReadPlatform.BINARY_SENSOR, BINARY_SENSOR_DESCRIPTIONS),
    ):
        for description in descriptions:
            contract = NativeScalarReadContract(
                platform=platform,
                entity_key=description.key,
                data_path=description.data_path,
                capabilities=_capabilities(description.capability),
            )
            contracts[(platform, description.key)] = contract
    return contracts


def test_native_scalar_read_registry_matches_platform_surface_exactly() -> None:
    """Every fixed native read must be classified, with no stale contracts."""
    assert dict(NATIVE_SCALAR_READ_CONTRACTS) == _platform_contracts()
    assert len(NATIVE_SCALAR_READ_CONTRACTS) == 234
    assert (
        sum(
            contract.platform is NativeReadPlatform.SENSOR
            for contract in NATIVE_SCALAR_READ_CONTRACTS.values()
        )
        == 153
    )
    assert (
        sum(
            contract.platform is NativeReadPlatform.BINARY_SENSOR
            for contract in NATIVE_SCALAR_READ_CONTRACTS.values()
        )
        == 81
    )


def test_native_scalar_read_paths_are_unique_normalized_and_immutable() -> None:
    """Contracts use exact canonical paths and expose an immutable registry."""
    contracts = tuple(NATIVE_SCALAR_READ_CONTRACTS.values())
    assert isinstance(NATIVE_SCALAR_READ_CONTRACTS, MappingProxyType)
    assert (
        frozenset(contract.data_path for contract in contracts)
        == NATIVE_SCALAR_READ_PATHS
    )
    assert len(NATIVE_SCALAR_READ_PATHS) == len(contracts)
    assert all(_NORMALIZED_PATH.fullmatch(path) for path in NATIVE_SCALAR_READ_PATHS)
    assert all(
        capabilities
        and len(capabilities) == len(set(capabilities))
        and all(capability.isidentifier() for capability in capabilities)
        for capabilities in (contract.capabilities for contract in contracts)
    )
