"""
Unified ownership and privacy contracts for reviewed read surfaces.

This module is declarative. It does not fetch router data, publish entities, or
authorize controls. Its purpose is to give every path admitted to this registry
one owner and to keep private or implementation-only paths out of native scalar
entities. Child-device entities, entity attributes, and device metadata remain
governed by their platform-specific allowlists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .binary_sensor import BINARY_SENSOR_DESCRIPTIONS
from .panel_read import ADMIN_READ_COLLECTION_SPECS, ADMIN_READ_RECORD_SPECS
from .read_contracts import (
    NATIVE_SCALAR_READ_CONTRACTS,
    NativeReadContractId,
    NativeReadPlatform,
)
from .sensor import SENSOR_DESCRIPTIONS

if TYPE_CHECKING:
    from .coordinator import PollGroup


class ReadSurfaceOwner(StrEnum):
    """Publication owner inside the reviewed read-surface registry."""

    NATIVE_SCALAR = "native_scalar"
    ADMIN_COLLECTION = "administrator_collection"
    ADMIN_RECORD = "administrator_record"
    PRIVATE = "private"
    EXCLUDED = "explicit_exclusion"


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
class ReadSurfaceContract:
    """One canonical normalized path with exactly one publication owner."""

    canonical_path: str
    owner: ReadSurfaceOwner
    value_kind: ReadValueKind
    cadence: ReadCadence
    privacy: ReadPrivacy
    administration_feature_ids: tuple[str, ...] = ()
    native_contract_id: NativeReadContractId | None = None
    administrator_section_id: str | None = None


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
        "dect_handsets": ("telephony_dect_handset_configuration",),
        "dect_repeaters": ("telephony_dect_repeater_enrollment",),
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
_NUMBER_FIELDS: Final = frozenset(
    {
        "channel",
        "provider_code",
        "slot",
        "web_ui_port",
    }
)
_LOCAL_NETWORK_FIELDS: Final = frozenset(
    {
        "access_point",
        "configured_reserved_ipv4",
        "domain",
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


def _native_surfaces() -> tuple[ReadSurfaceContract, ...]:
    descriptions = _native_description_registry()
    if descriptions.keys() != NATIVE_SCALAR_READ_CONTRACTS.keys():
        msg = "Native descriptions and normalized contracts differ"
        raise ValueError(msg)
    surfaces: list[ReadSurfaceContract] = []
    for contract_id, contract in NATIVE_SCALAR_READ_CONTRACTS.items():
        description = descriptions[contract_id]
        if description.data_path != contract.data_path:
            msg = f"Native path mismatch: {contract_id!r}"
            raise ValueError(msg)
        surfaces.append(
            ReadSurfaceContract(
                canonical_path=contract.data_path,
                owner=ReadSurfaceOwner.NATIVE_SCALAR,
                value_kind=_native_value_kind(contract.platform, description),
                cadence=_read_cadence(description.coordinator_group),
                privacy=_native_privacy(contract.data_path),
                native_contract_id=contract_id,
            )
        )
    return tuple(surfaces)


def _administrator_surfaces() -> tuple[ReadSurfaceContract, ...]:
    surfaces: list[ReadSurfaceContract] = []
    for owner, specs, collection in (
        (ReadSurfaceOwner.ADMIN_COLLECTION, ADMIN_READ_COLLECTION_SPECS, True),
        (ReadSurfaceOwner.ADMIN_RECORD, ADMIN_READ_RECORD_SPECS, False),
    ):
        for spec in specs:
            cadence = _ADMIN_CADENCE_BY_SECTION.get(spec.section_id, ReadCadence.SLOW)
            feature_ids = _ADMIN_FEATURE_IDS_BY_SECTION[spec.section_id]
            surfaces.extend(
                ReadSurfaceContract(
                    canonical_path=_admin_path(
                        spec.path,
                        field,
                        collection=collection,
                    ),
                    owner=owner,
                    value_kind=_admin_value_kind(field),
                    cadence=cadence,
                    privacy=_admin_privacy(spec.section_id, field),
                    administration_feature_ids=feature_ids,
                    administrator_section_id=spec.section_id,
                )
                for field in spec.fields
            )
    return tuple(surfaces)


def _fixed_surface(
    path: str,
    *,
    owner: ReadSurfaceOwner,
    privacy: ReadPrivacy,
    value_kind: ReadValueKind = ReadValueKind.TEXT,
) -> ReadSurfaceContract:
    return ReadSurfaceContract(
        canonical_path=path,
        owner=owner,
        value_kind=value_kind,
        cadence=ReadCadence.NEVER,
        privacy=privacy,
    )


_PRIVATE_SURFACES: Final = tuple(
    _fixed_surface(path, owner=ReadSurfaceOwner.PRIVATE, privacy=privacy)
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
        owner=ReadSurfaceOwner.EXCLUDED,
        privacy=ReadPrivacy.INTERNAL,
        value_kind=ReadValueKind.OPAQUE,
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


def _build_registry(
    surfaces: Iterable[ReadSurfaceContract],
) -> Mapping[str, ReadSurfaceContract]:
    registry: dict[str, ReadSurfaceContract] = {}
    for surface in surfaces:
        if not surface.canonical_path:
            msg = "Read surface path cannot be empty"
            raise ValueError(msg)
        if surface.canonical_path in registry:
            msg = f"Duplicate read-surface ownership: {surface.canonical_path}"
            raise ValueError(msg)
        if (
            surface.owner is ReadSurfaceOwner.NATIVE_SCALAR
            and surface.privacy in SENSITIVE_READ_PRIVACY
        ):
            msg = f"Sensitive path cannot be native: {surface.canonical_path}"
            raise ValueError(msg)
        if (
            surface.owner
            in {ReadSurfaceOwner.ADMIN_COLLECTION, ReadSurfaceOwner.ADMIN_RECORD}
            and surface.administrator_section_id is None
        ):
            msg = f"Administrator path lacks section: {surface.canonical_path}"
            raise ValueError(msg)
        registry[surface.canonical_path] = surface
    return MappingProxyType(registry)


READ_SURFACES: Final[Mapping[str, ReadSurfaceContract]] = _build_registry(
    (
        *_native_surfaces(),
        *_administrator_surfaces(),
        *_PRIVATE_SURFACES,
        *_EXCLUDED_SURFACES,
    )
)

NATIVE_READ_SURFACES: Final = MappingProxyType(
    {
        surface.native_contract_id: surface
        for surface in READ_SURFACES.values()
        if surface.owner is ReadSurfaceOwner.NATIVE_SCALAR
        and surface.native_contract_id is not None
    }
)

ADMINISTRATOR_READ_SURFACES: Final = MappingProxyType(
    {
        path: surface
        for path, surface in READ_SURFACES.items()
        if surface.owner
        in {ReadSurfaceOwner.ADMIN_COLLECTION, ReadSurfaceOwner.ADMIN_RECORD}
    }
)
