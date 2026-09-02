"""Conformance tests for unified normalized read-surface ownership."""

from __future__ import annotations

import re
from pathlib import Path
from types import MappingProxyType

import pytest

import custom_components.speedport_smart.read_surfaces as read_surfaces_module
from custom_components.speedport_smart.binary_sensor import (
    CHILD_BINARY_SENSOR_COLLECTIONS,
)
from custom_components.speedport_smart.panel_read import (
    ADMIN_READ_COLLECTION_SPECS,
    ADMIN_READ_RECORD_SPECS,
)
from custom_components.speedport_smart.read_contracts import (
    NATIVE_SCALAR_READ_CONTRACTS,
)
from custom_components.speedport_smart.read_surfaces import (
    ADMINISTRATOR_READ_SURFACES,
    DERIVED_READ_SURFACES,
    NATIVE_READ_SURFACES,
    READ_PUBLICATIONS,
    READ_SURFACES,
    SENSITIVE_READ_PRIVACY,
    ReadCadence,
    ReadPrivacy,
    ReadPublicationContract,
    ReadPublicationSurface,
    ReadValueKind,
)
from custom_components.speedport_smart.sensor import (
    CHILD_SENSOR_COLLECTIONS,
    ENDPOINT_FAILURE_SENSOR_DESCRIPTION,
    POLLING_HEALTH_SENSOR_DESCRIPTIONS,
    WAN_TELEMETRY_SENSOR_DESCRIPTIONS,
)


def _admin_path(path: tuple[str, ...], field: str, *, collection: bool) -> str:
    root = ".".join(path)
    return f"{root}[].{field}" if collection else f"{root}.{field}"


def _publication(
    path: str,
    surface: ReadPublicationSurface,
    publication_id: str,
) -> ReadPublicationContract:
    matches = tuple(
        publication
        for publication in READ_SURFACES[path].publications
        if publication.surface is surface
        and publication.publication_id == publication_id
    )
    assert len(matches) == 1
    return matches[0]


def _child_path(root: str, field: str) -> str:
    return f"{root}[].{field}"


def _child_fallback_paths(roots: tuple[str, ...], field: str) -> tuple[str, ...]:
    return tuple(
        f"{root}.{field}" if root == "receiver" else _child_path(root, field)
        for root in roots[1:]
    )


def test_native_scalar_contracts_have_one_exact_publication() -> None:
    """Every fixed entity path has one exact native publication."""
    assert isinstance(NATIVE_READ_SURFACES, MappingProxyType)
    assert set(NATIVE_READ_SURFACES) == set(NATIVE_SCALAR_READ_CONTRACTS)
    assert len(NATIVE_READ_SURFACES) == len(NATIVE_SCALAR_READ_CONTRACTS)

    for contract_id, contract in NATIVE_SCALAR_READ_CONTRACTS.items():
        surface = NATIVE_READ_SURFACES[contract_id]
        publication = _publication(
            contract.data_path,
            ReadPublicationSurface.NATIVE_SCALAR,
            f"{contract.platform.value}:{contract_id[1]}",
        )
        assert surface.canonical_path == contract.data_path
        assert publication.native_contract_id == contract_id
        assert publication.administrator_section_id is None
        assert surface.cadence in {
            ReadCadence.FAST,
            ReadCadence.NORMAL,
            ReadCadence.SLOW,
        }


def test_every_native_entity_factory_has_an_exact_publication() -> None:
    """Descriptor-backed and custom sensor factories share one audit boundary."""
    expected_ids = {
        f"{contract.platform.value}:{contract_id[1]}"
        for contract_id, contract in NATIVE_SCALAR_READ_CONTRACTS.items()
    }
    expected_ids.update(
        f"sensor:{description.key}"
        for description in (
            *WAN_TELEMETRY_SENSOR_DESCRIPTIONS,
            *POLLING_HEALTH_SENSOR_DESCRIPTIONS,
        )
    )
    expected_ids.update(
        {
            f"sensor:{ENDPOINT_FAILURE_SENSOR_DESCRIPTION.key}",
            "sensor:management_access",
        }
    )
    actual_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.NATIVE_SCALAR
    }
    assert actual_ids == expected_ids

    endpoint = _publication(
        "runtime.endpoint_errors",
        ReadPublicationSurface.NATIVE_SCALAR,
        "sensor:endpoint_failures",
    )
    assert endpoint.output_kind is ReadValueKind.COUNT
    management = _publication(
        "management.access.state",
        ReadPublicationSurface.NATIVE_SCALAR,
        "sensor:management_access",
    )
    assert management.output_kind is ReadValueKind.ENUM


def test_every_administrator_field_has_one_exact_publication() -> None:
    """The administrator allowlist and unified registry cannot drift apart."""
    expected: dict[str, tuple[ReadPublicationSurface, str, str]] = {}
    for publication_surface, specs, collection in (
        (
            ReadPublicationSurface.ADMIN_COLLECTION,
            ADMIN_READ_COLLECTION_SPECS,
            True,
        ),
        (ReadPublicationSurface.ADMIN_RECORD, ADMIN_READ_RECORD_SPECS, False),
    ):
        for spec in specs:
            for field in spec.fields:
                path = _admin_path(spec.path, field, collection=collection)
                assert path not in expected
                expected[path] = (
                    publication_surface,
                    spec.section_id,
                    field,
                )

    assert set(ADMINISTRATOR_READ_SURFACES) == set(expected)
    for path, (publication_surface, section_id, field) in expected.items():
        surface = ADMINISTRATOR_READ_SURFACES[path]
        publication = _publication(
            path,
            publication_surface,
            f"{section_id}:{field}",
        )
        assert publication.administrator_section_id == section_id
        assert publication.administration_feature_ids
        assert surface.cadence in {ReadCadence.NORMAL, ReadCadence.SLOW}


def test_child_descriptor_catalog_has_exact_entity_publications() -> None:
    """Every child entity and attribute descriptor owns an indexed publication."""
    expected_ids: set[str] = set()
    for platform, specs in (
        ("sensor", CHILD_SENSOR_COLLECTIONS),
        ("binary_sensor", CHILD_BINARY_SENSOR_COLLECTIONS),
    ):
        for spec in specs:
            for description in spec.fields:
                path = _child_path(spec.data_paths[0], description.field)
                publication_id = f"{platform}:{spec.kind}:{description.key}"
                publication = _publication(
                    path,
                    ReadPublicationSurface.CHILD_ENTITY,
                    publication_id,
                )
                expected_ids.add(publication_id)
                assert publication.derived_from == _child_fallback_paths(
                    spec.data_paths,
                    description.field,
                )
                attribute_fields = getattr(description, "attribute_fields", ())
                for attribute_field in attribute_fields:
                    attribute_id = (
                        f"sensor:{spec.kind}:{description.key}:"
                        f"attribute:{attribute_field}"
                    )
                    attribute = _publication(
                        _child_path(spec.data_paths[0], attribute_field),
                        ReadPublicationSurface.ENTITY_ATTRIBUTE,
                        attribute_id,
                    )
                    assert attribute.derived_from == _child_fallback_paths(
                        spec.data_paths,
                        attribute_field,
                    )

    actual_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.CHILD_ENTITY
    }
    assert actual_ids == expected_ids


def test_tracker_publications_cover_state_properties_and_attributes() -> None:
    """Tracker publication ownership includes fallbacks and all bounded attrs."""
    expected_attributes = {
        "reserved_ipv4",
        "ipv6",
        "ipv6_ula",
        "ipv6_gua",
        "medium",
        "wifi_generation",
        "wifi_standard",
        "has_web_ui",
        "web_ui_port",
        "web_ui_scheme",
        "signal_dbm",
        "link_speed_bps",
        "access_point",
        "mesh_node",
        "last_seen",
        "parental_profile",
        "internet_paused",
        "internet_access_allowed",
    }
    expected_ids = {
        "device_tracker:client:state",
        "device_tracker:client:hostname",
        "device_tracker:client:ip_address",
        "device_tracker:client:mac_address",
        *(f"device_tracker:client:attribute:{field}" for field in expected_attributes),
    }
    actual_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.DEVICE_TRACKER
    }
    assert actual_ids == expected_ids
    assert _publication(
        "clients.items[].connected",
        ReadPublicationSurface.DEVICE_TRACKER,
        "device_tracker:client:state",
    ).derived_from == ("clients.items[].active",)
    assert _publication(
        "clients.items[].ipv4",
        ReadPublicationSurface.DEVICE_TRACKER,
        "device_tracker:client:ip_address",
    ).derived_from == (
        "clients.items[].ip",
        "clients.items[].ipv6",
        "clients.items[].ipv6_gua",
        "clients.items[].ipv6_ula",
    )


def test_device_info_and_update_metadata_are_explicit_publications() -> None:
    """Device registry and UpdateEntity metadata no longer bypass ownership."""
    expected_device_info_ids = {
        "device_info:router:identifier",
        "device_info:router:serial_number",
        "device_info:router:model",
        "device_info:router:name",
        "device_info:router:sw_version",
        "device_info:router:hw_version",
    }
    child_kinds = {
        spec.kind
        for spec in (*CHILD_SENSOR_COLLECTIONS, *CHILD_BINARY_SENSOR_COLLECTIONS)
    }
    for kind in child_kinds:
        expected_device_info_ids.update(
            {
                f"device_info:{kind}:identifier",
                f"device_info:{kind}:name",
                f"device_info:{kind}:manufacturer",
                f"device_info:{kind}:model",
                f"device_info:{kind}:sw_version",
                f"device_info:{kind}:hw_version",
            }
        )
    device_info_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.DEVICE_INFO
    }
    assert device_info_ids == expected_device_info_ids

    update_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.UPDATE_METADATA
    }
    assert update_ids == {
        "update:firmware:installed_version",
        "update:firmware:latest_version",
        "update:firmware:release_url",
        "update:firmware:in_progress",
        "update:firmware:update_percentage",
    }
    assert (
        _publication(
            "system.firmware_update_progress",
            ReadPublicationSurface.UPDATE_METADATA,
            "update:firmware:in_progress",
        ).output_kind
        is ReadValueKind.BOOLEAN
    )


def test_fixed_entity_attributes_have_exact_publication_ownership() -> None:
    """Bounded entity attributes cannot silently bypass the registry."""
    expected_ids = {
        "sensor:wan_interface:attribute:index",
        "sensor:wan_interface:attribute:alias",
        "sensor:dhcp_pool_size:attribute:start_ipv4",
        "sensor:dhcp_pool_size:attribute:end_ipv4",
        "sensor:update_failures:attribute:last_failed_group",
        "sensor:update_failures:attribute:last_error_class",
        "sensor:wan_polling_state:attribute:mode",
        "sensor:wan_polling_state:attribute:target_interval_seconds",
        "sensor:wan_polling_state:attribute:runtime_floor_seconds",
        "sensor:wan_polling_state:attribute:last_stable_interval_seconds",
        "sensor:wan_polling_state:attribute:retry_in_seconds",
        "sensor:wan_polling_state:attribute:success_streak",
        "sensor:wan_polling_state:attribute:source_available",
        "sensor:endpoint_failures:attribute:failures",
        "sensor:management_access:attribute:owner_ip_address",
        "sensor:management_access:attribute:retry_after_seconds",
        "sensor:management_access:attribute:browser_logout_required",
        "sensor:management_access:attribute:controls_available",
        "sensor:management_access:attribute:last_changed",
        "sensor:management_access:attribute:last_successful_update",
    }
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ):
        expected_ids.update(
            {
                f"sensor:wifi_schedule_weekly:attribute:{day}_from",
                f"sensor:wifi_schedule_weekly:attribute:{day}_to",
            }
        )
    for group in ("fast", "normal", "slow"):
        expected_ids.update(
            {
                f"sensor:{group}_polling_health:attribute:update_interval_seconds",
                f"sensor:{group}_polling_health:attribute:last_successful_update",
                f"sensor:{group}_polling_health:attribute:last_error_class",
            }
        )
    for spec in CHILD_SENSOR_COLLECTIONS:
        for description in spec.fields:
            expected_ids.update(
                f"sensor:{spec.kind}:{description.key}:attribute:{field}"
                for field in description.attribute_fields
            )

    actual_ids = {
        publication_id
        for (surface, publication_id) in READ_PUBLICATIONS
        if surface is ReadPublicationSurface.ENTITY_ATTRIBUTE
    }
    assert actual_ids == expected_ids
    assert _publication(
        "runtime.wan_counter_telemetry.source_available",
        ReadPublicationSurface.ENTITY_ATTRIBUTE,
        "sensor:wan_polling_state:attribute:source_available",
    ).derived_from == ("runtime.endpoint_errors.wan_counters",)


def test_intentional_mirrors_keep_one_owner_and_distinct_publications() -> None:
    """Known mirrors are declared rather than rejected as duplicate ownership."""
    assert {
        publication.surface
        for publication in READ_SURFACES["clients.items[].connected"].publications
    } == {
        ReadPublicationSurface.ADMIN_COLLECTION,
        ReadPublicationSurface.CHILD_ENTITY,
        ReadPublicationSurface.DEVICE_TRACKER,
    }
    assert {
        publication.surface
        for publication in READ_SURFACES["mesh.nodes[].ipv4"].publications
    } == {
        ReadPublicationSurface.ADMIN_COLLECTION,
        ReadPublicationSurface.ENTITY_ATTRIBUTE,
    }
    assert {
        publication.surface
        for publication in READ_SURFACES["router.firmware"].publications
    } == {
        ReadPublicationSurface.DEVICE_INFO,
        ReadPublicationSurface.UPDATE_METADATA,
    }


def test_every_derived_input_is_owned_and_metadata_is_conservative() -> None:
    """Lineage cannot reference an unclassified or less-protected input."""
    references = {
        source_path
        for surface in READ_SURFACES.values()
        for publication in surface.publications
        for source_path in publication.derived_from
    }
    assert isinstance(DERIVED_READ_SURFACES, MappingProxyType)
    assert set(DERIVED_READ_SURFACES) == references
    assert references <= set(READ_SURFACES)
    assert {
        path for path, surface in READ_SURFACES.items() if not surface.publications
    } == set(read_surfaces_module._REVIEWED_SOURCE_ONLY_METADATA)  # noqa: SLF001

    cadence_order = {
        ReadCadence.FAST: 0,
        ReadCadence.NORMAL: 1,
        ReadCadence.SLOW: 2,
        ReadCadence.NEVER: 3,
    }
    privacy_order = {
        ReadPrivacy.GENERAL: 0,
        ReadPrivacy.LOCAL_NETWORK: 1,
        ReadPrivacy.PERSONAL: 2,
        ReadPrivacy.INTERNAL: 3,
        ReadPrivacy.SECRET: 4,
    }
    for surface in READ_SURFACES.values():
        for publication in surface.publications:
            for source_path in publication.derived_from:
                source = READ_SURFACES[source_path]
                assert cadence_order[surface.cadence] >= cadence_order[source.cadence]
                assert privacy_order[surface.privacy] >= privacy_order[source.privacy]

    assert READ_SURFACES["management.access.state"].value_kind is ReadValueKind.ENUM
    assert (
        READ_SURFACES["runtime.endpoint_errors.wan_counters"].value_kind
        is ReadValueKind.TEXT
    )
    assert READ_SURFACES["dect.handsets[].hostname"].privacy is ReadPrivacy.PERSONAL
    assert READ_SURFACES["telephony.numbers[].label"].privacy is ReadPrivacy.PERSONAL


def test_derived_lineage_is_acyclic() -> None:
    """Every derivation graph walk terminates at a classified source."""
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(path: str) -> None:
        if path in visited:
            return
        assert path not in visiting
        visiting.add(path)
        for publication in READ_SURFACES[path].publications:
            for source_path in publication.derived_from:
                visit(source_path)
        visiting.remove(path)
        visited.add(path)

    for path in READ_SURFACES:
        visit(path)


def test_unknown_derived_source_fails_closed() -> None:
    """A new lineage input requires an explicit reviewed source contract."""
    declaration = read_surfaces_module._ReadSurfaceDeclaration(  # noqa: SLF001
        canonical_path="known.output",
        value_kind=ReadValueKind.TEXT,
        cadence=ReadCadence.NORMAL,
        privacy=ReadPrivacy.GENERAL,
        publication=ReadPublicationContract(
            surface=ReadPublicationSurface.ENTITY_ATTRIBUTE,
            publication_id="test:known_output",
            derived_from=("unknown.source",),
        ),
    )
    with pytest.raises(ValueError, match="Unreviewed derivation sources"):
        read_surfaces_module._derived_source_surfaces((declaration,))  # noqa: SLF001


def test_read_surface_paths_and_publications_are_immutable_and_unique() -> None:
    """One canonical owner may have many uniquely indexed publications."""
    assert isinstance(READ_SURFACES, MappingProxyType)
    assert isinstance(READ_PUBLICATIONS, MappingProxyType)
    assert len(READ_SURFACES) == len(set(READ_SURFACES))
    assert all(
        path == surface.canonical_path for path, surface in READ_SURFACES.items()
    )
    publication_count = sum(
        len(surface.publications) for surface in READ_SURFACES.values()
    )
    assert len(READ_PUBLICATIONS) == publication_count
    for key, binding in READ_PUBLICATIONS.items():
        assert key == (
            binding.publication.surface,
            binding.publication.publication_id,
        )
        assert binding.publication in READ_SURFACES[binding.canonical_path].publications
        assert binding.canonical_path not in binding.publication.derived_from
        assert len(binding.publication.derived_from) == len(
            set(binding.publication.derived_from)
        )


def test_sensitive_and_internal_surfaces_cannot_be_native() -> None:
    """Personal, secret, and implementation data never becomes a native entity."""
    assert all(
        not surface.has_publication(ReadPublicationSurface.NATIVE_SCALAR)
        for surface in READ_SURFACES.values()
        if surface.privacy in SENSITIVE_READ_PRIVACY
    )
    assert READ_SURFACES["wifi.radio_2_4.key"].has_publication(
        ReadPublicationSurface.PRIVATE
    )
    assert READ_SURFACES["wifi.radio_2_4.key"].privacy is ReadPrivacy.SECRET
    fingerprint = READ_SURFACES["clients.items[]._identity_fingerprint"]
    assert fingerprint.has_publication(ReadPublicationSurface.EXCLUDED)
    assert fingerprint.value_kind is ReadValueKind.OPAQUE


def test_private_and_excluded_raw_values_are_not_direct_public_reads() -> None:
    """Hidden raw paths may only coexist with a declared derived publication."""
    for surface in READ_SURFACES.values():
        hidden = {
            ReadPublicationSurface.PRIVATE,
            ReadPublicationSurface.EXCLUDED,
        }
        if not any(item.surface in hidden for item in surface.publications):
            continue
        assert not surface.has_publication(ReadPublicationSurface.NATIVE_SCALAR)
        assert not surface.has_publication(ReadPublicationSurface.ADMIN_COLLECTION)
        assert not surface.has_publication(ReadPublicationSurface.ADMIN_RECORD)


def test_administrator_metadata_references_current_frontend_features() -> None:
    """Administrator mirrors cannot retain a removed frontend feature ID."""
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
        for publication in surface.publications
        if publication.surface
        in {
            ReadPublicationSurface.ADMIN_COLLECTION,
            ReadPublicationSurface.ADMIN_RECORD,
        }
        for feature_id in publication.administration_feature_ids
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
    assert READ_SURFACES["lan.ipv6_pext_flag"].value_kind is ReadValueKind.BOOLEAN
    assert READ_SURFACES["lan.ipv6_arec_flag"].value_kind is ReadValueKind.BOOLEAN
    assert (
        READ_SURFACES["receiver.items[].cell_id"].privacy is ReadPrivacy.LOCAL_NETWORK
    )
    assert READ_SURFACES["receiver.cell_id"].privacy is ReadPrivacy.LOCAL_NETWORK
