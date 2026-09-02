"""Privacy-bounded cached data projection for the administrator panel."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

ADMIN_READ_SCHEMA_VERSION: Final = 2
MAX_ADMIN_READ_ROWS: Final = 256
MAX_ADMIN_READ_TEXT_LENGTH: Final = 256
_MAX_ADMIN_READ_INTEGER: Final = (1 << 64) - 1
_INTERNET_FAILURE_REASONS: Final = frozenset({"user", "net", "dsl", "router"})

type JsonScalar = str | int | float | bool


@dataclass(frozen=True, slots=True)
class _CollectionSpec:
    """One exact normalized collection allowed through the admin read API."""

    section_id: str
    path: tuple[str, ...]
    fields: tuple[str, ...]
    source: str = "protected_json"


@dataclass(frozen=True, slots=True)
class _RecordSpec:
    """One exact normalized mapping allowed through the admin read API."""

    section_id: str
    path: tuple[str, ...]
    fields: tuple[str, ...]
    source: str = "protected_json"


_COMMON_DEVICE_FIELDS: Final = (
    "name",
    "hostname",
    "manufacturer",
    "model",
    "firmware",
    "hardware_version",
    "serial",
    "mac",
)

_TRAFFIC_FIELDS: Final = (
    "link_speed_bps",
    "download_rate_bps",
    "upload_rate_bps",
    "download_link_speed_bps",
    "upload_link_speed_bps",
    "bytes_received",
    "bytes_sent",
)

_COLLECTIONS: Final = (
    _CollectionSpec(
        section_id="clients",
        path=("clients", "items"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "ipv4",
            "configured_reserved_ipv4",
            "reserved_ipv4",
            "ipv6",
            "ipv6_ula",
            "ipv6_gua",
            "connected",
            "medium",
            "wifi_generation",
            "wifi_standard",
            "has_web_ui",
            "web_ui_port",
            "web_ui_scheme",
            "signal_dbm",
            *_TRAFFIC_FIELDS,
            "access_point",
            "mesh_node",
            "band",
            "channel",
            "last_seen",
            "parental_profile",
            "internet_paused",
            "internet_access_allowed",
            "fixed_dhcp",
            "uses_dhcp",
            "uses_rule",
        ),
    ),
    _CollectionSpec(
        section_id="mesh_nodes",
        path=("mesh", "nodes"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "connected",
            "parent",
            "device_type",
            "medium",
            "ipv4",
            "wifi_enabled",
            *_TRAFFIC_FIELDS,
            "signal_dbm",
            "band",
            "channel",
            "client_count",
            "role",
            "backhaul",
            "uptime_seconds",
            "linked_lan_port_count",
            "lan_port_1_speed_bps",
            "lan_port_2_speed_bps",
        ),
    ),
    _CollectionSpec(
        section_id="port_forward_rules",
        path=("nat", "port_forward_rules"),
        fields=("name", "active", "target", "tcp_mappings", "udp_mappings"),
    ),
    _CollectionSpec(
        section_id="port_block_rules",
        path=("security", "port_block_rules"),
        fields=("rule_group", "id", "active", "tcp_ports", "udp_ports"),
    ),
    _CollectionSpec(
        section_id="dns_rebind_exceptions",
        path=("security", "dns_rebind_exceptions"),
        fields=("domain",),
    ),
    _CollectionSpec(
        section_id="qos_prioritized_clients",
        path=("qos", "prioritized_clients"),
        fields=("slot", "prioritized"),
    ),
    _CollectionSpec(
        section_id="vpn_peers",
        path=("vpn", "peers"),
        fields=("name", "enabled", "connected", "last_handshake"),
    ),
    _CollectionSpec(
        section_id="telephony_providers",
        path=("telephony", "providers"),
        fields=("id", "provider_code"),
    ),
    _CollectionSpec(
        section_id="telephone_lines",
        path=("telephony", "numbers"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "registered",
            "enabled",
            "active_call",
            "call_state",
            "id",
            "status",
            "provider_code",
            "error_code",
        ),
    ),
    _CollectionSpec(
        section_id="dect_handsets",
        path=("dect", "handsets"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "connected",
            "registered",
            "active_call",
            "charging",
            "battery_percent",
            "signal_dbm",
            "signal_percent",
            "call_state",
            "paging",
        ),
    ),
    _CollectionSpec(
        section_id="dect_repeaters",
        path=("dect", "repeaters"),
        fields=("id", "registered"),
    ),
    _CollectionSpec(
        section_id="ip_phones",
        path=("pbx", "ip_phones"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "connected",
            "registered",
            "active_call",
            "call_state",
        ),
    ),
    _CollectionSpec(
        section_id="pbx_clients",
        path=("pbx", "clients"),
        fields=("id", "status", "name", "ipv4", "mac"),
    ),
    _CollectionSpec(
        section_id="usb_devices",
        path=("usb", "items"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "connected",
            "mounted",
            "total_bytes",
            "used_bytes",
            "free_bytes",
            "usage_percent",
            "temperature_celsius",
            "media_type",
        ),
    ),
    _CollectionSpec(
        section_id="receivers",
        path=("receiver", "items"),
        fields=(
            *_COMMON_DEVICE_FIELDS,
            "connected",
            *_TRAFFIC_FIELDS,
            "network_type",
            "operator",
            "rsrp_dbm",
            "rsrq_db",
            "sinr_db",
            "rssi_dbm",
            "band",
            "frequency_mhz",
            "cell_id",
            "temperature_celsius",
        ),
    ),
    _CollectionSpec(
        section_id="storage_devices",
        path=("usb", "storage_items"),
        fields=(
            "name",
            "storage_type",
            "connection",
            "total_bytes",
            "used_bytes",
            "free_bytes",
        ),
    ),
    _CollectionSpec(
        section_id="nas_shares",
        path=("usb", "shares"),
        fields=("name", "enabled", "read_only", "secure"),
    ),
    _CollectionSpec(
        section_id="powerline_nodes",
        path=("powerline", "nodes"),
        fields=(
            "id",
            "name",
            "parent",
            "manufacturer",
            "mac",
            "firmware",
            "mode",
            "download_link_speed_bps",
            "upload_link_speed_bps",
        ),
    ),
)

_RECORDS: Final = (
    _RecordSpec(
        section_id="internet_status_technical",
        path=("internet",),
        fields=("failure_reason",),
        source="public_status",
    ),
    _RecordSpec(
        section_id="status_technical",
        path=("system",),
        fields=("domain_name",),
        source="public_status",
    ),
    _RecordSpec(
        section_id="lan_ipv6_technical",
        path=("lan",),
        fields=("ipv6_pext_flag", "ipv6_arec_flag"),
    ),
    _RecordSpec(
        section_id="ddns_identity",
        path=("ddns",),
        fields=("domain", "update_server"),
    ),
    _RecordSpec(
        section_id="wifi_2_4_identity",
        path=("wifi", "radio_2_4"),
        fields=("ssid",),
    ),
    _RecordSpec(
        section_id="wifi_5_identity",
        path=("wifi", "radio_5"),
        fields=("ssid",),
    ),
    _RecordSpec(
        section_id="wifi_guest_identity",
        path=("wifi", "guest"),
        fields=("ssid",),
    ),
    _RecordSpec(
        section_id="wifi_office_identity",
        path=("wifi", "office"),
        fields=("ssid",),
    ),
)

# Public, immutable schema views used by the unified read-surface registry.
# The projection implementation continues to own these declarations; consumers
# can audit coverage without duplicating the administrator allowlist.
ADMIN_READ_COLLECTION_SPECS: Final = _COLLECTIONS
ADMIN_READ_RECORD_SPECS: Final = _RECORDS


def admin_read_payload(
    data: Mapping[str, Any],
    *,
    entry_id: str,
) -> dict[str, Any]:
    """Return a bounded, allowlisted projection of immutable normalized data."""
    sections: list[dict[str, Any]] = []
    for spec in _COLLECTIONS:
        collection = _nested_value(data, spec.path)
        if not isinstance(collection, list | tuple):
            continue
        projected_rows = [
            row
            for item in collection[:MAX_ADMIN_READ_ROWS]
            if isinstance(item, Mapping)
            if (row := _project_row(item, spec.fields))
        ]
        projected_rows.sort(key=_row_sort_key)
        sections.append(
            {
                "id": spec.section_id,
                "source": spec.source,
                "rows": projected_rows,
                "truncated": len(collection) > MAX_ADMIN_READ_ROWS,
            }
        )

    for record_spec in _RECORDS:
        record = _nested_value(data, record_spec.path)
        if not isinstance(record, Mapping):
            continue
        projected = _project_row(record, record_spec.fields)
        if not projected:
            continue
        sections.append(
            {
                "id": record_spec.section_id,
                "source": record_spec.source,
                "rows": [projected],
                "truncated": False,
            }
        )

    return {
        "schema_version": ADMIN_READ_SCHEMA_VERSION,
        "entry_id": entry_id,
        "sections": sections,
    }


def _nested_value(data: Mapping[str, Any], path: tuple[str, ...]) -> object:
    """Read one fixed path without exposing a generic path API."""
    current: object = data
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _project_row(
    item: Mapping[str, Any], fields: tuple[str, ...]
) -> dict[str, JsonScalar]:
    """Copy only explicitly reviewed scalar fields from one normalized row."""
    projected: dict[str, JsonScalar] = {}
    for field in fields:
        if field not in item:
            continue
        value = _project_scalar(item[field])
        if value is not None:
            if field == "failure_reason" and value not in _INTERNET_FAILURE_REASONS:
                continue
            projected[field] = value
    return projected


def _project_scalar(value: object) -> JsonScalar | None:
    """Return a bounded JSON scalar or reject the value."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) <= _MAX_ADMIN_READ_INTEGER else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        return value[:MAX_ADMIN_READ_TEXT_LENGTH]
    return None


def _row_sort_key(row: Mapping[str, JsonScalar]) -> tuple[str, ...]:
    """Return a deterministic ordering without exposing hidden identifiers."""
    return tuple(f"{key}={row[key]}" for key in sorted(row))
