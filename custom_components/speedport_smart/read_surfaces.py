"""
Unified ownership and privacy contracts for reviewed read surfaces.

This module is declarative. It does not fetch router data, publish entities, or
authorize controls. Each admitted normalized path has one canonical data
contract and any number of explicit publication contracts. This models a value
that is intentionally mirrored into, for example, a child entity and the
administrator panel without pretending that either publication surface owns the
normalized data. Private and implementation-only paths remain excluded from
public Home Assistant state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    CHILD_BINARY_SENSOR_COLLECTIONS,
)
from .panel_read import ADMIN_READ_COLLECTION_SPECS, ADMIN_READ_RECORD_SPECS
from .read_contracts import (
    NATIVE_SCALAR_READ_CONTRACTS,
    NativeReadContractId,
    NativeReadPlatform,
)
from .sensor import (
    CHILD_SENSOR_COLLECTIONS,
    ENDPOINT_FAILURE_SENSOR_DESCRIPTION,
    POLLING_HEALTH_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    WAN_TELEMETRY_SENSOR_DESCRIPTIONS,
)

if TYPE_CHECKING:
    from .coordinator import PollGroup


class ReadPublicationSurface(StrEnum):
    """Reviewed Home Assistant publication surface for normalized data."""

    NATIVE_SCALAR = "native_scalar"
    CHILD_ENTITY = "child_entity"
    DEVICE_TRACKER = "device_tracker"
    ENTITY_ATTRIBUTE = "entity_attribute"
    DEVICE_INFO = "device_info"
    UPDATE_METADATA = "update_metadata"
    ADMIN_COLLECTION = "administrator_collection"
    ADMIN_RECORD = "administrator_record"
    PRIVATE = "private"
    EXCLUDED = "explicit_exclusion"


# Compatibility name for downstream imports while callers migrate from the old
# one-owner model. It now names a publication surface, not a data owner.
ReadSurfaceOwner = ReadPublicationSurface


class ReadValueKind(StrEnum):
    """Stable semantic shape of a reviewed value."""

    BOOLEAN = "boolean"
    COUNT = "count"
    NUMBER = "number"
    TEXT = "text"
    ENUM = "enum"
    TIMESTAMP = "timestamp"
    DURATION = "duration"
    DATA_SIZE = "data_size"
    DATA_RATE = "data_rate"
    PERCENTAGE = "percentage"
    SIGNAL_STRENGTH = "signal_strength"
    TEMPERATURE = "temperature"
    FREQUENCY = "frequency"
    OPAQUE = "opaque"


class ReadCadence(StrEnum):
    """Coordinator cadence or deliberate absence of polling."""

    FAST = "fast"
    NORMAL = "normal"
    SLOW = "slow"
    NEVER = "never"


class ReadPrivacy(StrEnum):
    """Privacy sensitivity of one normalized value."""

    GENERAL = "general"
    LOCAL_NETWORK = "local_network"
    PERSONAL = "personal"
    SECRET = "secret"  # noqa: S105 - privacy classification, not a credential
    INTERNAL = "internal"


SENSITIVE_READ_PRIVACY: Final = frozenset(
    {ReadPrivacy.PERSONAL, ReadPrivacy.SECRET, ReadPrivacy.INTERNAL}
)


@dataclass(frozen=True, slots=True)
class ReadPublicationContract:
    """One intentional publication of a canonical normalized value."""

    surface: ReadPublicationSurface
    publication_id: str
    output_kind: ReadValueKind | None = None
    derived_from: tuple[str, ...] = ()
    administration_feature_ids: tuple[str, ...] = ()
    native_contract_id: NativeReadContractId | None = None
    administrator_section_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadSurfaceContract:
    """One canonical normalized path and every reviewed publication of it."""

    canonical_path: str
    value_kind: ReadValueKind
    cadence: ReadCadence
    privacy: ReadPrivacy
    publications: tuple[ReadPublicationContract, ...]

    def has_publication(self, surface: ReadPublicationSurface) -> bool:
        """Return whether this normalized value is intentionally published."""
        return any(publication.surface is surface for publication in self.publications)


@dataclass(frozen=True, slots=True)
class ReadPublicationBinding:
    """Index one publication back to its canonical normalized data owner."""

    canonical_path: str
    publication: ReadPublicationContract


@dataclass(frozen=True, slots=True)
class _ReadSurfaceDeclaration:
    """Internal unmerged declaration for a publication or derivation source."""

    canonical_path: str
    value_kind: ReadValueKind
    cadence: ReadCadence
    privacy: ReadPrivacy
    publication: ReadPublicationContract | None


_ADMIN_FEATURE_IDS_BY_SECTION: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "clients": ("network_client_inventory",),
        "mesh_nodes": (
            "network_mesh_management",
            "system_mesh_restart",
            "system_mesh_reset",
            "system_mesh_firmware",
        ),
        "port_forward_rules": (
            "internet_port_forward_toggle",
            "internet_port_forward_editor",
        ),
        "port_block_rules": ("internet_port_blocking",),
        "dns_rebind_exceptions": ("network_dns_rebind",),
        "qos_prioritized_clients": ("network_traffic_prioritization",),
        "vpn_peers": ("network_vpn_management",),
        "telephony_providers": ("telephony_provider_registration",),
        "telephone_lines": (
            "telephony_provider_registration",
            "telephony_number_assignment",
        ),
        "dect_handsets": (
            "telephony_dect_handset_configuration",
            "telephony_dect_handset_disconnect",
        ),
        "dect_repeaters": (
            "telephony_dect_repeater_enrollment",
            "telephony_dect_repeater_disconnect",
        ),
        "ip_phones": ("telephony_ip_phone_enrollment",),
        "pbx_clients": ("telephony_ip_pbx",),
        "usb_devices": ("network_usb_printer_media",),
        "receivers": ("internet_receiver_mode",),
        "storage_devices": (
            "network_usb_printer_media",
            "network_nas_shares",
        ),
        "nas_shares": ("network_nas_shares",),
        "powerline_nodes": ("network_powerline_management",),
        "internet_status_technical": ("internet_connection_diagnostics",),
        "status_technical": ("system_information_services",),
        "lan_ipv6_technical": ("network_lan_identity",),
        "ddns_identity": ("internet_ddns_management",),
        "wifi_2_4_identity": ("network_wifi_radio_settings",),
        "wifi_5_identity": ("network_wifi_radio_settings",),
        "wifi_guest_identity": ("network_wifi_identity_security",),
        "wifi_office_identity": ("network_wifi_identity_security",),
    }
)

_ADMIN_CADENCE_BY_SECTION: Final[Mapping[str, ReadCadence]] = MappingProxyType(
    {
        "clients": ReadCadence.NORMAL,
        "mesh_nodes": ReadCadence.NORMAL,
        "receivers": ReadCadence.NORMAL,
        "telephone_lines": ReadCadence.NORMAL,
        "powerline_nodes": ReadCadence.NORMAL,
        "internet_status_technical": ReadCadence.FAST,
        "status_technical": ReadCadence.NORMAL,
        "wifi_2_4_identity": ReadCadence.NORMAL,
        "wifi_5_identity": ReadCadence.NORMAL,
        "wifi_guest_identity": ReadCadence.NORMAL,
        "wifi_office_identity": ReadCadence.NORMAL,
    }
)

_BOOLEAN_FIELDS: Final = frozenset(
    {
        "active",
        "active_call",
        "charging",
        "connected",
        "enabled",
        "fixed_dhcp",
        "has_web_ui",
        "internet_access_allowed",
        "internet_paused",
        "ipv6_arec_flag",
        "ipv6_pext_flag",
        "mounted",
        "paging",
        "prioritized",
        "read_only",
        "registered",
        "secure",
        "uses_dhcp",
        "uses_rule",
        "wifi_enabled",
    }
)
_TIMESTAMP_FIELDS: Final = frozenset({"last_handshake", "last_seen"})
_ENUM_FIELDS: Final = frozenset({"failure_reason"})
_NUMBER_FIELDS: Final = frozenset(
    {
        "channel",
        "provider_code",
        "slot",
        "web_ui_port",
        "device_type",
        "wifi_generation",
    }
)
_LOCAL_NETWORK_FIELDS: Final = frozenset(
    {
        "access_point",
        "cell_id",
        "configured_reserved_ipv4",
        "domain",
        "domain_name",
        "hostname",
        "ipv4",
        "ipv6",
        "ipv6_gua",
        "ipv6_ula",
        "last_handshake",
        "last_seen",
        "mac",
        "mesh_node",
        "name",
        "parent",
        "parental_profile",
        "reserved_ipv4",
        "serial",
        "ssid",
        "target",
        "update_server",
        "web_ui_port",
        "web_ui_scheme",
    }
)
_PERSONAL_ADMIN_SECTIONS: Final = frozenset(
    {
        "dect_handsets",
        "dect_repeaters",
        "ip_phones",
        "pbx_clients",
        "telephone_lines",
    }
)


def _native_description_registry() -> Mapping[NativeReadContractId, Any]:
    """Return fixed platform descriptions keyed like native read contracts."""
    descriptions: dict[NativeReadContractId, Any] = {}
    for platform, platform_descriptions in (
        (NativeReadPlatform.SENSOR, SENSOR_DESCRIPTIONS),
        (NativeReadPlatform.BINARY_SENSOR, BINARY_SENSOR_DESCRIPTIONS),
    ):
        for description in platform_descriptions:
            contract_id = (platform, description.key)
            if contract_id in descriptions:
                msg = f"Duplicate native description: {contract_id!r}"
                raise ValueError(msg)
            descriptions[contract_id] = description
    return MappingProxyType(descriptions)


def _read_cadence(group: PollGroup) -> ReadCadence:
    """Translate a runtime coordinator group into stable read metadata."""
    return ReadCadence(group.value)


def _native_value_kind(
    platform: NativeReadPlatform,
    description: Any,
) -> ReadValueKind:
    """Classify an entity value without duplicating its display metadata."""
    if platform is NativeReadPlatform.BINARY_SENSOR:
        return ReadValueKind.BOOLEAN
    device_class = getattr(getattr(description, "device_class", None), "value", None)
    if device_class in {
        "data_rate",
        "data_size",
        "duration",
        "enum",
        "frequency",
        "signal_strength",
        "temperature",
        "timestamp",
    }:
        return ReadValueKind(device_class)
    unit = str(getattr(description, "native_unit_of_measurement", "") or "")
    if unit == "%":
        return ReadValueKind.PERCENTAGE
    path = str(description.data_path)
    transform_name = getattr(getattr(description, "transform", None), "__name__", "")
    if path.endswith(
        (
            "_count",
            ".items",
            ".leases",
            ".nodes",
            ".peers",
            ".phonebooks",
            ".profiles",
        )
    ):
        return ReadValueKind.COUNT
    if transform_name == "count_items":
        return ReadValueKind.COUNT
    if path.endswith("_bytes"):
        return ReadValueKind.DATA_SIZE
    if path.endswith("_bps"):
        return ReadValueKind.DATA_RATE
    if path.endswith(("_percent", "_utilization")):
        return ReadValueKind.PERCENTAGE
    if transform_name == "as_int":
        return ReadValueKind.NUMBER
    return ReadValueKind.NUMBER if unit else ReadValueKind.TEXT


def _native_privacy(path: str) -> ReadPrivacy:
    """Classify network identifiers separately from general router state."""
    if any(
        marker in path
        for marker in (
            ".cell_id",
            ".ipv4",
            ".ipv6",
            ".subnet_mask",
            ".ula_address",
            ".usable_ipv6_range",
        )
    ):
        return ReadPrivacy.LOCAL_NETWORK
    return ReadPrivacy.GENERAL


def _admin_value_kind(field: str) -> ReadValueKind:
    """Classify one fixed administrator projection field."""
    if field in _BOOLEAN_FIELDS:
        return ReadValueKind.BOOLEAN
    if field in _TIMESTAMP_FIELDS:
        return ReadValueKind.TIMESTAMP
    if field in _ENUM_FIELDS:
        return ReadValueKind.ENUM
    if field.endswith("_bytes"):
        return ReadValueKind.DATA_SIZE
    if field.endswith("_bps"):
        return ReadValueKind.DATA_RATE
    if field.endswith("_percent"):
        return ReadValueKind.PERCENTAGE
    if field.endswith("_celsius"):
        return ReadValueKind.TEMPERATURE
    if field.endswith(("_db", "_dbm")):
        return ReadValueKind.SIGNAL_STRENGTH
    if field.endswith("_mhz"):
        return ReadValueKind.FREQUENCY
    if field.endswith("_seconds"):
        return ReadValueKind.DURATION
    if field.endswith("_count"):
        return ReadValueKind.COUNT
    if field in _NUMBER_FIELDS:
        return ReadValueKind.NUMBER
    return ReadValueKind.TEXT


def _admin_privacy(section_id: str, field: str) -> ReadPrivacy:
    """Return reviewed privacy for one administrator-only field."""
    if section_id in _PERSONAL_ADMIN_SECTIONS and field in {
        "id",
        "mac",
        "name",
        "serial",
    }:
        return ReadPrivacy.PERSONAL
    if field in {"id", "provider_code", "rule_group", "slot"}:
        return ReadPrivacy.INTERNAL
    if field in _LOCAL_NETWORK_FIELDS:
        return ReadPrivacy.LOCAL_NETWORK
    return ReadPrivacy.GENERAL


def _admin_path(path: Sequence[str], field: str, *, collection: bool) -> str:
    """Build one canonical path for a reviewed administrator field."""
    root = ".".join(path)
    return f"{root}[].{field}" if collection else f"{root}.{field}"


def _publication(
    surface: ReadPublicationSurface,
    publication_id: str,
    *,
    output_kind: ReadValueKind | None = None,
    derived_from: tuple[str, ...] = (),
    administration_feature_ids: tuple[str, ...] = (),
    native_contract_id: NativeReadContractId | None = None,
    administrator_section_id: str | None = None,
) -> ReadPublicationContract:
    """Build one immutable publication declaration."""
    return ReadPublicationContract(
        surface=surface,
        publication_id=publication_id,
        output_kind=output_kind,
        derived_from=derived_from,
        administration_feature_ids=administration_feature_ids,
        native_contract_id=native_contract_id,
        administrator_section_id=administrator_section_id,
    )


def _declaration(
    path: str,
    *,
    publication: ReadPublicationContract,
    value_kind: ReadValueKind,
    cadence: ReadCadence,
    privacy: ReadPrivacy,
) -> _ReadSurfaceDeclaration:
    """Build one unmerged publication declaration."""
    return _ReadSurfaceDeclaration(
        canonical_path=path,
        value_kind=value_kind,
        cadence=cadence,
        privacy=privacy,
        publication=publication,
    )


def _source_declaration(
    path: str,
    *,
    value_kind: ReadValueKind,
    cadence: ReadCadence,
    privacy: ReadPrivacy,
) -> _ReadSurfaceDeclaration:
    """Classify one normalized input used only through derivation."""
    return _ReadSurfaceDeclaration(
        canonical_path=path,
        value_kind=value_kind,
        cadence=cadence,
        privacy=privacy,
        publication=None,
    )


def _native_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    descriptions = _native_description_registry()
    if descriptions.keys() != NATIVE_SCALAR_READ_CONTRACTS.keys():
        msg = "Native descriptions and normalized contracts differ"
        raise ValueError(msg)
    surfaces: list[_ReadSurfaceDeclaration] = []
    for contract_id, contract in NATIVE_SCALAR_READ_CONTRACTS.items():
        description = descriptions[contract_id]
        if description.data_path != contract.data_path:
            msg = f"Native path mismatch: {contract_id!r}"
            raise ValueError(msg)
        surfaces.append(
            _declaration(
                contract.data_path,
                publication=_publication(
                    ReadPublicationSurface.NATIVE_SCALAR,
                    f"{contract.platform.value}:{description.key}",
                    native_contract_id=contract_id,
                ),
                value_kind=_native_value_kind(contract.platform, description),
                cadence=_read_cadence(description.coordinator_group),
                privacy=_native_privacy(contract.data_path),
            )
        )
    return tuple(surfaces)


def _special_native_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare native sensor states built outside the fixed descriptors."""
    surfaces: list[_ReadSurfaceDeclaration] = []
    wan_sources = {
        "wan_polling_mode": (
            "runtime.wan_counter_telemetry.mode",
            ReadValueKind.ENUM,
        ),
        "wan_polling_interval": (
            "runtime.wan_counter_telemetry.effective_interval_seconds",
            ReadValueKind.DURATION,
        ),
        "wan_polling_state": (
            "runtime.wan_counter_telemetry.state",
            ReadValueKind.ENUM,
        ),
        "wan_fastest_proven_interval": (
            "runtime.wan_counter_telemetry.last_stable_interval_seconds",
            ReadValueKind.DURATION,
        ),
        "wan_last_sample": (
            "runtime.wan_counter_telemetry.last_sampled_at",
            ReadValueKind.TIMESTAMP,
        ),
    }
    if {description.key for description in WAN_TELEMETRY_SENSOR_DESCRIPTIONS} != set(
        wan_sources
    ):
        msg = "WAN telemetry descriptions and read surfaces differ"
        raise ValueError(msg)
    for description in WAN_TELEMETRY_SENSOR_DESCRIPTIONS:
        path, value_kind = wan_sources[description.key]
        surfaces.append(
            _declaration(
                path,
                publication=_publication(
                    ReadPublicationSurface.NATIVE_SCALAR,
                    f"sensor:{description.key}",
                    output_kind=value_kind,
                ),
                value_kind=value_kind,
                cadence=ReadCadence.FAST,
                privacy=ReadPrivacy.GENERAL,
            )
        )

    for description in POLLING_HEALTH_SENSOR_DESCRIPTIONS:
        group = description.key.removesuffix("_polling_health")
        cadence = ReadCadence(group)
        surfaces.append(
            _declaration(
                f"runtime.polling_health.{group}.state",
                publication=_publication(
                    ReadPublicationSurface.NATIVE_SCALAR,
                    f"sensor:{description.key}",
                    output_kind=ReadValueKind.ENUM,
                ),
                value_kind=ReadValueKind.ENUM,
                cadence=cadence,
                privacy=ReadPrivacy.GENERAL,
            )
        )

    surfaces.extend(
        (
            _declaration(
                "runtime.endpoint_errors",
                publication=_publication(
                    ReadPublicationSurface.NATIVE_SCALAR,
                    f"sensor:{ENDPOINT_FAILURE_SENSOR_DESCRIPTION.key}",
                    output_kind=ReadValueKind.COUNT,
                ),
                value_kind=ReadValueKind.OPAQUE,
                cadence=ReadCadence.FAST,
                privacy=ReadPrivacy.GENERAL,
            ),
            _declaration(
                "management.access.state",
                publication=_publication(
                    ReadPublicationSurface.NATIVE_SCALAR,
                    "sensor:management_access",
                    output_kind=ReadValueKind.ENUM,
                ),
                value_kind=ReadValueKind.ENUM,
                cadence=ReadCadence.NORMAL,
                privacy=ReadPrivacy.GENERAL,
            ),
        )
    )
    return tuple(surfaces)


def _administrator_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    surfaces: list[_ReadSurfaceDeclaration] = []
    for publication_surface, specs, collection in (
        (
            ReadPublicationSurface.ADMIN_COLLECTION,
            ADMIN_READ_COLLECTION_SPECS,
            True,
        ),
        (ReadPublicationSurface.ADMIN_RECORD, ADMIN_READ_RECORD_SPECS, False),
    ):
        for spec in specs:
            cadence = _ADMIN_CADENCE_BY_SECTION.get(spec.section_id, ReadCadence.SLOW)
            feature_ids = _ADMIN_FEATURE_IDS_BY_SECTION[spec.section_id]
            surfaces.extend(
                _declaration(
                    _admin_path(
                        spec.path,
                        field,
                        collection=collection,
                    ),
                    publication=_publication(
                        publication_surface,
                        f"{spec.section_id}:{field}",
                        administration_feature_ids=feature_ids,
                        administrator_section_id=spec.section_id,
                    ),
                    value_kind=_admin_value_kind(field),
                    cadence=cadence,
                    privacy=_admin_privacy(spec.section_id, field),
                )
                for field in spec.fields
            )
    return tuple(surfaces)


_CHILD_ADMIN_SECTION_BY_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "client": "clients",
        "dect_handset": "dect_handsets",
        "dect_repeater": "dect_repeaters",
        "ip_phone": "ip_phones",
        "mesh_node": "mesh_nodes",
        "powerline_node": "powerline_nodes",
        "receiver": "receivers",
        "telephone_line": "telephone_lines",
        "usb_device": "usb_devices",
    }
)


def _collection_field_path(root: str, field: str) -> str:
    """Return a canonical field path beneath one normalized collection."""
    return f"{root}[].{field}"


def _alternate_collection_paths(
    roots: tuple[str, ...],
    field: str,
) -> tuple[str, ...]:
    """Return ordered firmware fallback paths for a collection field."""
    return tuple(
        f"{root}.{field}" if root == "receiver" else _collection_field_path(root, field)
        for root in roots[1:]
    )


def _child_entity_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare every descriptor-backed child entity and child attribute."""
    surfaces: list[_ReadSurfaceDeclaration] = []
    for platform, specs in (
        ("sensor", CHILD_SENSOR_COLLECTIONS),
        ("binary_sensor", CHILD_BINARY_SENSOR_COLLECTIONS),
    ):
        for spec in specs:
            section_id = _CHILD_ADMIN_SECTION_BY_KIND[spec.kind]
            primary_root = spec.data_paths[0]
            for description in spec.fields:
                path = _collection_field_path(primary_root, description.field)
                derived_from = _alternate_collection_paths(
                    spec.data_paths,
                    description.field,
                )
                surfaces.append(
                    _declaration(
                        path,
                        publication=_publication(
                            ReadPublicationSurface.CHILD_ENTITY,
                            f"{platform}:{spec.kind}:{description.key}",
                            derived_from=derived_from,
                        ),
                        value_kind=(
                            ReadValueKind.BOOLEAN
                            if platform == "binary_sensor"
                            else _admin_value_kind(description.field)
                        ),
                        cadence=_read_cadence(spec.coordinator_group),
                        privacy=_admin_privacy(section_id, description.field),
                    )
                )
                if platform != "sensor":
                    continue
                surfaces.extend(
                    [
                        _declaration(
                            _collection_field_path(primary_root, attribute_field),
                            publication=_publication(
                                ReadPublicationSurface.ENTITY_ATTRIBUTE,
                                (
                                    f"sensor:{spec.kind}:{description.key}:"
                                    f"attribute:{attribute_field}"
                                ),
                                derived_from=_alternate_collection_paths(
                                    spec.data_paths,
                                    attribute_field,
                                ),
                            ),
                            value_kind=_admin_value_kind(attribute_field),
                            cadence=_read_cadence(spec.coordinator_group),
                            privacy=_admin_privacy(section_id, attribute_field),
                        )
                        for attribute_field in getattr(
                            description, "attribute_fields", ()
                        )
                    ]
                )
    return tuple(surfaces)


def _device_tracker_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare every normalized client value published by the tracker."""
    surfaces: list[_ReadSurfaceDeclaration] = []

    def add(
        field: str,
        publication_id: str,
        *,
        derived_from: tuple[str, ...] = (),
    ) -> None:
        surfaces.append(
            _declaration(
                _collection_field_path("clients.items", field),
                publication=_publication(
                    ReadPublicationSurface.DEVICE_TRACKER,
                    publication_id,
                    output_kind=(
                        ReadValueKind.ENUM
                        if publication_id == "device_tracker:client:state"
                        else None
                    ),
                    derived_from=tuple(
                        _collection_field_path("clients.items", fallback)
                        for fallback in derived_from
                    ),
                ),
                value_kind=_admin_value_kind(field),
                cadence=ReadCadence.NORMAL,
                privacy=_admin_privacy("clients", field),
            )
        )

    add("connected", "device_tracker:client:state", derived_from=("active",))
    add("hostname", "device_tracker:client:hostname", derived_from=("name",))
    add(
        "ipv4",
        "device_tracker:client:ip_address",
        derived_from=("ip", "ipv6", "ipv6_gua", "ipv6_ula"),
    )
    add("mac", "device_tracker:client:mac_address")
    for field in (
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
    ):
        add(field, f"device_tracker:client:attribute:{field}")
    return tuple(surfaces)


def _child_collection_metadata() -> Mapping[str, tuple[tuple[str, ...], ReadCadence]]:
    """Return each child family once and reject descriptor drift."""
    metadata: dict[str, tuple[tuple[str, ...], ReadCadence]] = {}
    all_specs: tuple[Any, ...] = (
        *CHILD_SENSOR_COLLECTIONS,
        *CHILD_BINARY_SENSOR_COLLECTIONS,
    )
    for spec in all_specs:
        candidate = (spec.data_paths, _read_cadence(spec.coordinator_group))
        existing = metadata.setdefault(spec.kind, candidate)
        if existing != candidate:
            msg = f"Child collection metadata differs: {spec.kind}"
            raise ValueError(msg)
    return MappingProxyType(metadata)


def _device_info_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare normalized identity values copied into DeviceInfo metadata."""
    surfaces: list[_ReadSurfaceDeclaration] = []

    def add_router(
        field: str,
        metadata_name: str,
        *,
        privacy: ReadPrivacy = ReadPrivacy.GENERAL,
    ) -> None:
        surfaces.append(
            _declaration(
                f"router.{field}",
                publication=_publication(
                    ReadPublicationSurface.DEVICE_INFO,
                    f"device_info:router:{metadata_name}",
                ),
                value_kind=ReadValueKind.TEXT,
                cadence=ReadCadence.SLOW,
                privacy=privacy,
            )
        )

    add_router("serial_number", "identifier", privacy=ReadPrivacy.LOCAL_NETWORK)
    add_router("serial_number", "serial_number", privacy=ReadPrivacy.LOCAL_NETWORK)
    add_router("model", "model")
    add_router("model", "name")
    add_router("firmware", "sw_version")
    add_router("hardware_version", "hw_version")

    for kind, (roots, cadence) in _child_collection_metadata().items():
        section_id = _CHILD_ADMIN_SECTION_BY_KIND[kind]
        primary_root = roots[0]
        metadata_fields = [
            ("id", "identifier", ("uuid", "uid", "serial", "mac")),
            (
                "label" if kind == "telephone_line" else "hostname",
                "name",
                ("name",) if kind == "telephone_line" else ("name", "label"),
            ),
            ("manufacturer", "manufacturer", ()),
            ("model", "model", ("type",)),
            ("firmware", "sw_version", ()),
            ("hardware_version", "hw_version", ()),
        ]
        for field, metadata_name, fallback_fields in metadata_fields:
            derived = tuple(
                _collection_field_path(primary_root, fallback)
                for fallback in fallback_fields
            )
            derived += _alternate_collection_paths(roots, field)
            derived += tuple(
                path
                for fallback in fallback_fields
                for path in _alternate_collection_paths(roots, fallback)
            )
            surfaces.append(
                _declaration(
                    _collection_field_path(primary_root, field),
                    publication=_publication(
                        ReadPublicationSurface.DEVICE_INFO,
                        f"device_info:{kind}:{metadata_name}",
                        derived_from=derived,
                    ),
                    value_kind=ReadValueKind.TEXT,
                    cadence=cadence,
                    privacy=_admin_privacy(section_id, field),
                )
            )
    return tuple(surfaces)


def _update_metadata_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare normalized values copied into the firmware update entity."""
    return (
        _declaration(
            "router.firmware",
            publication=_publication(
                ReadPublicationSurface.UPDATE_METADATA,
                "update:firmware:installed_version",
            ),
            value_kind=ReadValueKind.TEXT,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.GENERAL,
        ),
        _declaration(
            "system.latest_firmware",
            publication=_publication(
                ReadPublicationSurface.UPDATE_METADATA,
                "update:firmware:latest_version",
            ),
            value_kind=ReadValueKind.TEXT,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.GENERAL,
        ),
        _declaration(
            "system.firmware_release_url",
            publication=_publication(
                ReadPublicationSurface.UPDATE_METADATA,
                "update:firmware:release_url",
            ),
            value_kind=ReadValueKind.TEXT,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.GENERAL,
        ),
        _declaration(
            "system.firmware_update_progress",
            publication=_publication(
                ReadPublicationSurface.UPDATE_METADATA,
                "update:firmware:in_progress",
                output_kind=ReadValueKind.BOOLEAN,
            ),
            value_kind=ReadValueKind.PERCENTAGE,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.GENERAL,
        ),
        _declaration(
            "system.firmware_update_progress",
            publication=_publication(
                ReadPublicationSurface.UPDATE_METADATA,
                "update:firmware:update_percentage",
            ),
            value_kind=ReadValueKind.PERCENTAGE,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.GENERAL,
        ),
    )


def _attribute_surfaces() -> tuple[_ReadSurfaceDeclaration, ...]:
    """Declare normalized and bounded runtime entity attributes."""
    surfaces: list[_ReadSurfaceDeclaration] = []

    def add(
        path: str,
        entity_key: str,
        attribute: str,
        *,
        value_kind: ReadValueKind,
        cadence: ReadCadence,
        privacy: ReadPrivacy = ReadPrivacy.GENERAL,
        derived_from: tuple[str, ...] = (),
    ) -> None:
        surfaces.append(
            _declaration(
                path,
                publication=_publication(
                    ReadPublicationSurface.ENTITY_ATTRIBUTE,
                    f"sensor:{entity_key}:attribute:{attribute}",
                    derived_from=derived_from,
                ),
                value_kind=value_kind,
                cadence=cadence,
                privacy=privacy,
            )
        )

    for field in ("index", "alias"):
        add(
            f"wan.interface.{field}",
            "wan_interface",
            field,
            value_kind=(
                ReadValueKind.NUMBER if field == "index" else ReadValueKind.TEXT
            ),
            cadence=ReadCadence.FAST,
        )
    for day in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ):
        for boundary in ("from", "to"):
            add(
                f"wifi.schedule.weekly.{day}.{boundary}",
                "wifi_schedule_weekly",
                f"{day}_{boundary}",
                value_kind=ReadValueKind.TEXT,
                cadence=ReadCadence.SLOW,
            )
    for field in ("start_ipv4", "end_ipv4"):
        add(
            f"dhcp.pool_{field}",
            "dhcp_pool_size",
            field,
            value_kind=ReadValueKind.TEXT,
            cadence=ReadCadence.SLOW,
            privacy=ReadPrivacy.LOCAL_NETWORK,
        )
    add(
        "diagnostics.failed_group",
        "update_failures",
        "last_failed_group",
        value_kind=ReadValueKind.ENUM,
        cadence=ReadCadence.NORMAL,
        privacy=ReadPrivacy.INTERNAL,
    )
    add(
        "diagnostics.last_error",
        "update_failures",
        "last_error_class",
        value_kind=ReadValueKind.TEXT,
        cadence=ReadCadence.NORMAL,
        privacy=ReadPrivacy.INTERNAL,
    )
    for field, value_kind in (
        ("mode", ReadValueKind.ENUM),
        ("target_interval_seconds", ReadValueKind.DURATION),
        ("runtime_floor_seconds", ReadValueKind.DURATION),
        ("last_stable_interval_seconds", ReadValueKind.DURATION),
        ("retry_in_seconds", ReadValueKind.DURATION),
        ("success_streak", ReadValueKind.COUNT),
    ):
        add(
            f"runtime.wan_counter_telemetry.{field}",
            "wan_polling_state",
            field,
            value_kind=value_kind,
            cadence=ReadCadence.FAST,
            privacy=ReadPrivacy.GENERAL,
        )
    add(
        "runtime.wan_counter_telemetry.source_available",
        "wan_polling_state",
        "source_available",
        value_kind=ReadValueKind.BOOLEAN,
        cadence=ReadCadence.FAST,
        privacy=ReadPrivacy.GENERAL,
        derived_from=("runtime.endpoint_errors.wan_counters",),
    )
    for group in ("fast", "normal", "slow"):
        for field, value_kind in (
            ("update_interval_seconds", ReadValueKind.DURATION),
            ("last_successful_update", ReadValueKind.TIMESTAMP),
            ("last_error_class", ReadValueKind.TEXT),
        ):
            add(
                f"runtime.polling_health.{group}.{field}",
                f"{group}_polling_health",
                field,
                value_kind=value_kind,
                cadence=ReadCadence(group),
                privacy=ReadPrivacy.INTERNAL,
            )
    add(
        "runtime.endpoint_errors",
        "endpoint_failures",
        "failures",
        value_kind=ReadValueKind.OPAQUE,
        cadence=ReadCadence.FAST,
        privacy=ReadPrivacy.GENERAL,
    )
    for field, value_kind, privacy in (
        ("owner_ip_address", ReadValueKind.TEXT, ReadPrivacy.LOCAL_NETWORK),
        ("retry_after_seconds", ReadValueKind.DURATION, ReadPrivacy.GENERAL),
        ("browser_logout_required", ReadValueKind.BOOLEAN, ReadPrivacy.GENERAL),
        ("last_changed", ReadValueKind.TIMESTAMP, ReadPrivacy.GENERAL),
        ("last_successful_update", ReadValueKind.TIMESTAMP, ReadPrivacy.GENERAL),
    ):
        add(
            f"management.access.{field}",
            "management_access",
            field,
            value_kind=value_kind,
            cadence=ReadCadence.NORMAL,
            privacy=privacy,
        )
    add(
        "runtime.management.controls_available",
        "management_access",
        "controls_available",
        value_kind=ReadValueKind.BOOLEAN,
        cadence=ReadCadence.NORMAL,
        privacy=ReadPrivacy.INTERNAL,
        derived_from=("management.access.state",),
    )
    return tuple(surfaces)


def _fixed_surface(
    path: str,
    *,
    surface: ReadPublicationSurface,
    privacy: ReadPrivacy,
    value_kind: ReadValueKind = ReadValueKind.TEXT,
) -> _ReadSurfaceDeclaration:
    return _declaration(
        path,
        publication=_publication(surface, f"{surface.value}:{path}"),
        value_kind=value_kind,
        cadence=ReadCadence.NEVER,
        privacy=privacy,
    )


_PRIVATE_SURFACES: Final = tuple(
    _fixed_surface(path, surface=ReadPublicationSurface.PRIVATE, privacy=privacy)
    for path, privacy in (
        ("ddns.password", ReadPrivacy.SECRET),
        ("ddns.username", ReadPrivacy.SECRET),
        ("pbx.clients[].password", ReadPrivacy.SECRET),
        ("telephony.numbers[].ip_number", ReadPrivacy.PERSONAL),
        ("usb.shares[].path", ReadPrivacy.LOCAL_NETWORK),
        ("usb.shares[].username", ReadPrivacy.SECRET),
        ("vpn.peers[].private_key", ReadPrivacy.SECRET),
        ("vpn.peers[].vpn_userip", ReadPrivacy.LOCAL_NETWORK),
        ("wifi.guest.key", ReadPrivacy.SECRET),
        ("wifi.office.key", ReadPrivacy.SECRET),
        ("wifi.radio_2_4.key", ReadPrivacy.SECRET),
        ("wifi.radio_5.key", ReadPrivacy.SECRET),
    )
)

_EXCLUDED_SURFACES: Final = tuple(
    _fixed_surface(
        path,
        surface=ReadPublicationSurface.EXCLUDED,
        privacy=ReadPrivacy.INTERNAL,
        value_kind=(
            ReadValueKind.TEXT if path == "clients.items[].id" else ReadValueKind.OPAQUE
        ),
    )
    for path in (
        "clients.items[]._identity_fingerprint",
        "clients.items[].id",
        "clients.items[].managed_form_supported",
        "clients.items[].source_row_id",
        "mesh.nodes[].endpoint",
        "nat.port_forward_rules[]._identity_fingerprint",
        "nat.port_forward_rules[].payload",
        "powerline.nodes[].management_url",
        "security.port_block_rules[].client_scope",
        "telephony.numbers[].error_reason",
        "usb.storage_items[].serial",
    )
)


_CADENCE_ORDER: Final[Mapping[ReadCadence, int]] = MappingProxyType(
    {
        ReadCadence.FAST: 0,
        ReadCadence.NORMAL: 1,
        ReadCadence.SLOW: 2,
        ReadCadence.NEVER: 3,
    }
)
_PRIVACY_ORDER: Final[Mapping[ReadPrivacy, int]] = MappingProxyType(
    {
        ReadPrivacy.GENERAL: 0,
        ReadPrivacy.LOCAL_NETWORK: 1,
        ReadPrivacy.PERSONAL: 2,
        ReadPrivacy.INTERNAL: 3,
        ReadPrivacy.SECRET: 4,
    }
)
_REVIEWED_SOURCE_ONLY_METADATA: Final[
    Mapping[str, tuple[ReadValueKind, ReadCadence, ReadPrivacy]]
] = MappingProxyType(
    {
        # Client tracker and DeviceInfo fallbacks.
        "clients.items[].active": (
            ReadValueKind.BOOLEAN,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "clients.items[].ip": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "clients.items[].label": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "clients.items[].type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "clients.items[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "clients.items[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        # Telephony child DeviceInfo fallbacks.
        "dect.handsets[].label": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.handsets[].type": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.GENERAL,
        ),
        "dect.handsets[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.handsets[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].label": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].mac": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].name": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].serial": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].type": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.GENERAL,
        ),
        "dect.repeaters[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "dect.repeaters[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "pbx.ip_phones[].label": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "pbx.ip_phones[].type": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.GENERAL,
        ),
        "pbx.ip_phones[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "pbx.ip_phones[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.PERSONAL,
        ),
        "telephony.numbers[].type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "telephony.numbers[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.PERSONAL,
        ),
        "telephony.numbers[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.PERSONAL,
        ),
        # Network-device DeviceInfo fallbacks.
        "mesh.nodes[].label": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "mesh.nodes[].type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "mesh.nodes[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "mesh.nodes[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "powerline.nodes[].label": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "powerline.nodes[].serial": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "powerline.nodes[].type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "powerline.nodes[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "powerline.nodes[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "usb.items[].label": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "usb.items[].type": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.GENERAL,
        ),
        "usb.items[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.INTERNAL,
        ),
        "usb.items[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.SLOW,
            ReadPrivacy.INTERNAL,
        ),
        # Receiver singleton fallback and its collection identity fallbacks.
        "receiver.band": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.bytes_received": (
            ReadValueKind.DATA_SIZE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.bytes_sent": (
            ReadValueKind.DATA_SIZE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.cell_id": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.connected": (
            ReadValueKind.BOOLEAN,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.download_rate_bps": (
            ReadValueKind.DATA_RATE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.firmware": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.frequency_mhz": (
            ReadValueKind.FREQUENCY,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.hardware_version": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.hostname": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.id": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "receiver.items[].label": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.items[].type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.items[].uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "receiver.items[].uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "receiver.label": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.link_speed_bps": (
            ReadValueKind.DATA_RATE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.mac": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.manufacturer": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.name": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.network_type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.operator": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.rsrp_dbm": (
            ReadValueKind.SIGNAL_STRENGTH,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.rsrq_db": (
            ReadValueKind.SIGNAL_STRENGTH,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.rssi_dbm": (
            ReadValueKind.SIGNAL_STRENGTH,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.serial": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.LOCAL_NETWORK,
        ),
        "receiver.sinr_db": (
            ReadValueKind.SIGNAL_STRENGTH,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.temperature_celsius": (
            ReadValueKind.TEMPERATURE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.type": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.uid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "receiver.upload_rate_bps": (
            ReadValueKind.DATA_RATE,
            ReadCadence.NORMAL,
            ReadPrivacy.GENERAL,
        ),
        "receiver.uuid": (
            ReadValueKind.TEXT,
            ReadCadence.NORMAL,
            ReadPrivacy.INTERNAL,
        ),
        "runtime.endpoint_errors.wan_counters": (
            ReadValueKind.TEXT,
            ReadCadence.FAST,
            ReadPrivacy.GENERAL,
        ),
    }
)


def _merged_source_metadata(
    path: str,
    declarations: Sequence[_ReadSurfaceDeclaration],
) -> tuple[ReadValueKind, ReadCadence, ReadPrivacy]:
    """Return one conservative classification for a derivation input."""
    value_kinds = {declaration.value_kind for declaration in declarations}
    if len(value_kinds) != 1:
        msg = f"Derived source value-kind mismatch for {path}: {value_kinds!r}"
        raise ValueError(msg)
    cadence = min(
        (declaration.cadence for declaration in declarations),
        key=_CADENCE_ORDER.__getitem__,
    )
    privacy = max(
        (declaration.privacy for declaration in declarations),
        key=_PRIVACY_ORDER.__getitem__,
    )
    return next(iter(value_kinds)), cadence, privacy


def _derived_source_surfaces(
    declarations: Sequence[_ReadSurfaceDeclaration],
) -> tuple[_ReadSurfaceDeclaration, ...]:
    """Give every derivation input a first-class canonical classification."""
    by_path: dict[str, list[_ReadSurfaceDeclaration]] = {}
    references: dict[str, list[_ReadSurfaceDeclaration]] = {}
    for declaration in declarations:
        by_path.setdefault(declaration.canonical_path, []).append(declaration)
        publication = declaration.publication
        if publication is None:
            continue
        for source_path in publication.derived_from:
            references.setdefault(source_path, []).append(declaration)

    source_only_paths = set(references) - set(by_path)
    unknown_paths = source_only_paths - set(_REVIEWED_SOURCE_ONLY_METADATA)
    if unknown_paths:
        msg = f"Unreviewed derivation sources: {sorted(unknown_paths)!r}"
        raise ValueError(msg)
    stale_paths = set(_REVIEWED_SOURCE_ONLY_METADATA) - source_only_paths
    if stale_paths:
        msg = f"Stale derivation source classifications: {sorted(stale_paths)!r}"
        raise ValueError(msg)

    sources: list[_ReadSurfaceDeclaration] = []
    for path in references:
        existing_declarations = by_path.get(path)
        if existing_declarations is not None:
            value_kind, cadence, privacy = _merged_source_metadata(
                path,
                existing_declarations,
            )
        else:
            value_kind, cadence, privacy = _REVIEWED_SOURCE_ONLY_METADATA[path]
        sources.append(
            _source_declaration(
                path,
                value_kind=value_kind,
                cadence=cadence,
                privacy=privacy,
            )
        )
    return tuple(sources)


def _validate_publication(
    path: str,
    publication: ReadPublicationContract,
    privacy: ReadPrivacy,
) -> None:
    """Reject ambiguous metadata or an unsafe direct publication."""
    if not publication.publication_id:
        msg = f"Read publication ID cannot be empty: {path}"
        raise ValueError(msg)
    if path in publication.derived_from or len(publication.derived_from) != len(
        set(publication.derived_from)
    ):
        msg = f"Invalid derived-from paths: {publication.publication_id}"
        raise ValueError(msg)
    if publication.surface is ReadPublicationSurface.NATIVE_SCALAR:
        if privacy in SENSITIVE_READ_PRIVACY:
            msg = f"Sensitive path cannot be native: {path}"
            raise ValueError(msg)
    elif publication.native_contract_id is not None:
        msg = f"Non-native publication has native contract: {path}"
        raise ValueError(msg)
    if publication.surface in {
        ReadPublicationSurface.ADMIN_COLLECTION,
        ReadPublicationSurface.ADMIN_RECORD,
    }:
        if publication.administrator_section_id is None:
            msg = f"Administrator publication lacks section: {path}"
            raise ValueError(msg)
        if not publication.administration_feature_ids:
            msg = f"Administrator publication lacks feature owner: {path}"
            raise ValueError(msg)
    elif (
        publication.administrator_section_id is not None
        or publication.administration_feature_ids
    ):
        msg = f"Non-administrator publication has administrator metadata: {path}"
        raise ValueError(msg)


def _build_registry(
    surfaces: Iterable[_ReadSurfaceDeclaration],
) -> Mapping[str, ReadSurfaceContract]:
    """Merge publication declarations into one owner per canonical path."""
    declarations: dict[str, list[_ReadSurfaceDeclaration]] = {}
    publication_ids: set[tuple[ReadPublicationSurface, str]] = set()
    for declaration in surfaces:
        if not declaration.canonical_path:
            msg = "Read surface path cannot be empty"
            raise ValueError(msg)
        publication = declaration.publication
        if publication is None:
            declarations.setdefault(declaration.canonical_path, []).append(declaration)
            continue
        _validate_publication(
            declaration.canonical_path,
            publication,
            declaration.privacy,
        )
        publication_key = (
            publication.surface,
            publication.publication_id,
        )
        if publication_key in publication_ids:
            msg = f"Duplicate read publication: {publication_key!r}"
            raise ValueError(msg)
        publication_ids.add(publication_key)
        declarations.setdefault(declaration.canonical_path, []).append(declaration)

    registry: dict[str, ReadSurfaceContract] = {}
    for path, path_declarations in declarations.items():
        value_kinds = {declaration.value_kind for declaration in path_declarations}
        if len(value_kinds) != 1:
            msg = f"Read value-kind mismatch for {path}: {sorted(value_kinds)!r}"
            raise ValueError(msg)
        cadence = min(
            (declaration.cadence for declaration in path_declarations),
            key=_CADENCE_ORDER.__getitem__,
        )
        privacy = max(
            (declaration.privacy for declaration in path_declarations),
            key=_PRIVACY_ORDER.__getitem__,
        )
        publications = tuple(
            declaration.publication
            for declaration in path_declarations
            if declaration.publication is not None
        )
        if privacy in SENSITIVE_READ_PRIVACY and any(
            publication.surface is ReadPublicationSurface.NATIVE_SCALAR
            for publication in publications
        ):
            msg = f"Sensitive path cannot be native after merge: {path}"
            raise ValueError(msg)
        registry[path] = ReadSurfaceContract(
            canonical_path=path,
            value_kind=next(iter(value_kinds)),
            cadence=cadence,
            privacy=privacy,
            publications=publications,
        )
    return MappingProxyType(registry)


def _fold_lineage_metadata(
    registry: Mapping[str, ReadSurfaceContract],
) -> Mapping[str, ReadSurfaceContract]:
    """Fold source cadence/privacy into owners and reject cyclic lineage."""
    resolved: dict[str, ReadSurfaceContract] = {}
    visiting: set[str] = set()

    def resolve(path: str) -> ReadSurfaceContract:
        if path in resolved:
            return resolved[path]
        if path in visiting:
            msg = f"Cyclic read-surface lineage: {path}"
            raise ValueError(msg)
        visiting.add(path)
        contract = registry[path]
        cadence = contract.cadence
        privacy = contract.privacy
        for publication in contract.publications:
            for source_path in publication.derived_from:
                if source_path not in registry:
                    msg = (
                        f"Unclassified derivation source {source_path!r} "
                        f"for {publication.publication_id!r}"
                    )
                    raise ValueError(msg)
                source = resolve(source_path)
                cadence = max(cadence, source.cadence, key=_CADENCE_ORDER.__getitem__)
                privacy = max(privacy, source.privacy, key=_PRIVACY_ORDER.__getitem__)
        visiting.remove(path)
        if privacy in SENSITIVE_READ_PRIVACY and contract.has_publication(
            ReadPublicationSurface.NATIVE_SCALAR
        ):
            msg = f"Derived sensitive path cannot be native: {path}"
            raise ValueError(msg)
        resolved[path] = ReadSurfaceContract(
            canonical_path=contract.canonical_path,
            value_kind=contract.value_kind,
            cadence=cadence,
            privacy=privacy,
            publications=contract.publications,
        )
        return resolved[path]

    for path in registry:
        resolve(path)
    return MappingProxyType(resolved)


_READ_PUBLICATION_DECLARATIONS: Final = (
    *_native_surfaces(),
    *_special_native_surfaces(),
    *_administrator_surfaces(),
    *_child_entity_surfaces(),
    *_device_tracker_surfaces(),
    *_device_info_surfaces(),
    *_update_metadata_surfaces(),
    *_attribute_surfaces(),
    *_PRIVATE_SURFACES,
    *_EXCLUDED_SURFACES,
)
_READ_DERIVATION_SOURCE_DECLARATIONS: Final = _derived_source_surfaces(
    _READ_PUBLICATION_DECLARATIONS
)

READ_SURFACES: Final[Mapping[str, ReadSurfaceContract]] = _fold_lineage_metadata(
    _build_registry(
        (
            *_READ_PUBLICATION_DECLARATIONS,
            *_READ_DERIVATION_SOURCE_DECLARATIONS,
        )
    )
)

DERIVED_READ_SURFACES: Final[Mapping[str, ReadSurfaceContract]] = MappingProxyType(
    {
        declaration.canonical_path: READ_SURFACES[declaration.canonical_path]
        for declaration in _READ_DERIVATION_SOURCE_DECLARATIONS
    }
)

READ_PUBLICATIONS: Final[
    Mapping[tuple[ReadPublicationSurface, str], ReadPublicationBinding]
] = MappingProxyType(
    {
        (publication.surface, publication.publication_id): ReadPublicationBinding(
            canonical_path=path,
            publication=publication,
        )
        for path, surface in READ_SURFACES.items()
        for publication in surface.publications
    }
)

NATIVE_READ_SURFACES: Final[Mapping[NativeReadContractId, ReadSurfaceContract]] = (
    MappingProxyType(
        {
            publication.native_contract_id: surface
            for surface in READ_SURFACES.values()
            for publication in surface.publications
            if publication.surface is ReadPublicationSurface.NATIVE_SCALAR
            and publication.native_contract_id is not None
        }
    )
)

ADMINISTRATOR_READ_SURFACES: Final[Mapping[str, ReadSurfaceContract]] = (
    MappingProxyType(
        {
            path: surface
            for path, surface in READ_SURFACES.items()
            if any(
                publication.surface
                in {
                    ReadPublicationSurface.ADMIN_COLLECTION,
                    ReadPublicationSurface.ADMIN_RECORD,
                }
                for publication in surface.publications
            )
        }
    )
)
