"""Conformance tests for unified normalized read-surface ownership."""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType

from custom_components.speedport_smart.panel_read import (
    ADMIN_READ_COLLECTION_SPECS,
    ADMIN_READ_RECORD_SPECS,
)
from custom_components.speedport_smart.read_contracts import (
    NATIVE_SCALAR_READ_CONTRACTS,
)
from custom_components.speedport_smart.read_surfaces import (
    ADMINISTRATOR_READ_SURFACES,
    NATIVE_READ_SURFACES,
    READ_SURFACES,
    SENSITIVE_READ_PRIVACY,
    ReadCadence,
    ReadPrivacy,
    ReadSurfaceOwner,
    ReadValueKind,
)


def _admin_path(path: tuple[str, ...], field: str, *, collection: bool) -> str:
    root = ".".join(path)
    return f"{root}[].{field}" if collection else f"{root}.{field}"


def test_native_scalar_contracts_have_one_exact_surface_classification() -> None:
    """Every fixed entity path is classified, with no stale native surface."""
    assert isinstance(NATIVE_READ_SURFACES, MappingProxyType)
    assert set(NATIVE_READ_SURFACES) == set(NATIVE_SCALAR_READ_CONTRACTS)
    assert len(NATIVE_READ_SURFACES) == len(NATIVE_SCALAR_READ_CONTRACTS) == 231

    for contract_id, contract in NATIVE_SCALAR_READ_CONTRACTS.items():
        surface = NATIVE_READ_SURFACES[contract_id]
        assert surface.canonical_path == contract.data_path
        assert surface.owner is ReadSurfaceOwner.NATIVE_SCALAR
        assert surface.native_contract_id == contract_id
        assert surface.administrator_section_id is None
        assert surface.cadence in {
            ReadCadence.FAST,
            ReadCadence.NORMAL,
            ReadCadence.SLOW,
        }


def test_every_administrator_section_field_is_classified_exactly_once() -> None:
    """The administrator allowlist and unified registry cannot drift apart."""
    expected: dict[str, tuple[ReadSurfaceOwner, str]] = {}
    for owner, specs, collection in (
        (ReadSurfaceOwner.ADMIN_COLLECTION, ADMIN_READ_COLLECTION_SPECS, True),
        (ReadSurfaceOwner.ADMIN_RECORD, ADMIN_READ_RECORD_SPECS, False),
    ):
        for spec in specs:
            for field in spec.fields:
                path = _admin_path(spec.path, field, collection=collection)
                assert path not in expected
                expected[path] = (owner, spec.section_id)

    assert set(ADMINISTRATOR_READ_SURFACES) == set(expected)
    for path, (owner, section_id) in expected.items():
        surface = ADMINISTRATOR_READ_SURFACES[path]
        assert surface.owner is owner
        assert surface.administrator_section_id == section_id
        assert surface.administration_feature_ids
        assert surface.cadence in {ReadCadence.NORMAL, ReadCadence.SLOW}


def test_sensitive_and_internal_surfaces_cannot_be_native() -> None:
    """Personal, secret, and implementation data never becomes a native entity."""
    assert all(
        surface.owner is not ReadSurfaceOwner.NATIVE_SCALAR
        for surface in READ_SURFACES.values()
        if surface.privacy in SENSITIVE_READ_PRIVACY
    )
    assert READ_SURFACES["wifi.radio_2_4.key"].owner is ReadSurfaceOwner.PRIVATE
    assert READ_SURFACES["wifi.radio_2_4.key"].privacy is ReadPrivacy.SECRET
    assert (
        READ_SURFACES["clients.items[]._identity_fingerprint"].owner
        is ReadSurfaceOwner.EXCLUDED
    )
    assert (
        READ_SURFACES["clients.items[]._identity_fingerprint"].value_kind
        is ReadValueKind.OPAQUE
    )


def test_read_surface_paths_have_one_immutable_owner() -> None:
    """No canonical path is shared by native, administrator, or hidden owners."""
    assert isinstance(READ_SURFACES, MappingProxyType)
    assert len(READ_SURFACES) == len(set(READ_SURFACES))
    assert all(
        path == surface.canonical_path for path, surface in READ_SURFACES.items()
    )
    assert all(surface.value_kind for surface in READ_SURFACES.values())
    assert all(surface.cadence for surface in READ_SURFACES.values())
    assert all(surface.privacy for surface in READ_SURFACES.values())


def test_private_and_excluded_surfaces_are_never_polled_as_public_reads() -> None:
    """Hidden paths document their boundary instead of silently disappearing."""
    hidden = {
        path: surface
        for path, surface in READ_SURFACES.items()
        if surface.owner in {ReadSurfaceOwner.PRIVATE, ReadSurfaceOwner.EXCLUDED}
    }
    assert hidden
    assert all(surface.cadence is ReadCadence.NEVER for surface in hidden.values())
    assert all(surface.native_contract_id is None for surface in hidden.values())
    assert all(surface.administrator_section_id is None for surface in hidden.values())


def test_administrator_read_metadata_references_current_frontend_features() -> None:
    """Read ownership cannot retain a feature ID removed by catalog expansion."""
    panel_source = (
        Path(__file__).parents[1]
        / "custom_components/speedport_smart/frontend/speedport-smart-panel.js"
    ).read_text(encoding="utf-8")
    frontend_feature_ids = frozenset(
        re.findall(r'fixedAdminFeature\("([a-z0-9_]+)"', panel_source)
    )
    referenced_feature_ids = {
        feature_id
        for surface in ADMINISTRATOR_READ_SURFACES.values()
        for feature_id in surface.administration_feature_ids
    }

    assert referenced_feature_ids <= frontend_feature_ids


def test_value_kinds_distinguish_counts_identifiers_and_durations() -> None:
    """Structural metadata does not mislabel identifiers as numeric counters."""
    assert READ_SURFACES["nat.port_forward_rules"].value_kind is ReadValueKind.COUNT
    assert READ_SURFACES["internet.mtu"].value_kind is ReadValueKind.NUMBER
    assert READ_SURFACES["pbx.clients[].id"].value_kind is ReadValueKind.TEXT
    assert READ_SURFACES["mesh.nodes[].client_count"].value_kind is ReadValueKind.COUNT
    assert (
        READ_SURFACES["mesh.nodes[].uptime_seconds"].value_kind
        is ReadValueKind.DURATION
    )
