"""Typed protocol models for Speedport Smart routers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime


def _empty_mapping() -> Mapping[str, Any]:
    """Return an immutable empty mapping."""
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class RouterInfo:
    """Stable router identity reported by router."""

    model: str = "Speedport"
    firmware: str | None = None
    serial_number: str | None = None
    hardware_version: str | None = None
    mac_address: str | None = None


@dataclass(frozen=True, slots=True)
class RouterStatus:
    """Normalized public status data."""

    info: RouterInfo
    internet_state: str | None = None
    dsl_state: str | None = None
    dsl_downstream_bps: int | None = None
    dsl_upstream_bps: int | None = None
    wan_download_capacity_bps: int | None = None
    wan_upload_capacity_bps: int | None = None
    raw: Mapping[str, Any] = field(default_factory=_empty_mapping, repr=False)


@dataclass(frozen=True, slots=True)
class ParameterValue:
    """One value returned by ToTR64 GetParameterValues."""

    name: str
    value: str | int | float | bool
    data_type: str | None = None


@dataclass(frozen=True, slots=True)
class DslMetrics:
    """Read-only DSL line and channel telemetry."""

    line_index: int
    channel_index: int
    status: str | None
    downstream_current_bps: int | None
    upstream_current_bps: int | None
    downstream_max_bps: int | None
    upstream_max_bps: int | None
    downstream_noise_margin_db: float | None
    upstream_noise_margin_db: float | None
    downstream_attenuation_db: float | None
    upstream_attenuation_db: float | None
    sampled_at: datetime


@dataclass(frozen=True, slots=True)
class WanInterface:
    """TR-181 IP interface and optional traffic counters."""

    index: int
    alias: str | None = None
    name: str | None = None
    status: str | None = None
    enabled: bool | None = None
    bytes_received: int | None = None
    bytes_sent: int | None = None
    packets_received: int | None = None
    packets_sent: int | None = None
    errors_received: int | None = None
    errors_sent: int | None = None
    discard_packets_received: int | None = None
    discard_packets_sent: int | None = None

    @property
    def is_up(self) -> bool:
        """Return whether router reports interface as active."""
        return (self.status or "").casefold() in {"up", "online", "connected"}

    @property
    def is_aggregate(self) -> bool:
        """Return whether interface represents aggregate Hybrid WAN."""
        identity = f"{self.alias or ''} {self.name or ''}".casefold()
        return "bond" in identity or "habond" in identity


@dataclass(frozen=True, slots=True)
class WanCounters:
    """Monotonic WAN traffic counter sample."""

    interface: WanInterface
    bytes_received: int
    bytes_sent: int
    sampled_at: datetime
    packets_received: int | None = None
    packets_sent: int | None = None
    errors_received: int | None = None
    errors_sent: int | None = None
    discard_packets_received: int | None = None
    discard_packets_sent: int | None = None


@dataclass(frozen=True, slots=True)
class EndpointCapability:
    """Confirmed JSON endpoint for semantic feature family."""

    family: str
    endpoint: str
    authenticated: bool = False
    referer: str | None = None
    evidence_keys: tuple[str, ...] = ()
    automatic_probe: bool = False
    inventory_safe: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """Capabilities proven by non-mutating router probes."""

    status_json: bool = False
    tr064: bool = False
    wan_counters: bool = False
    authenticated_json: bool = False
    feature_endpoints: Mapping[str, EndpointCapability] = field(
        default_factory=_empty_mapping
    )
    failures: Mapping[str, str] = field(default_factory=_empty_mapping)

    def supports(self, family: str) -> bool:
        """Return whether semantic feature family was confirmed."""
        return family in self.feature_endpoints


@dataclass(frozen=True, slots=True)
class CandidateInventoryResult:
    """Value-free outcome of one explicit candidate inventory capture."""

    attempted: int
    succeeded: int
    unsupported: int
    failed: int
    observed: int
    excluded: int = 0


def normalize_status(raw: Mapping[str, Any]) -> RouterStatus:
    """Normalize public Status.json values without fabricating missing fields."""
    info = RouterInfo(
        model=_first_text(
            raw,
            "device_name",
            "model_name",
            "product_name",
        )
        or "Speedport",
        firmware=_first_text(raw, "firmware_version", "firmware", "sw_version"),
        serial_number=_first_text(raw, "serial_number", "serial", "serialno"),
        hardware_version=_first_text(
            raw, "hardware_version", "hardware_revision", "hw_version"
        ),
        mac_address=_first_text(raw, "router_mac", "mac_address", "device_mac"),
    )
    return RouterStatus(
        info=info,
        internet_state=_first_text(
            raw,
            "onlinestatus",
            "online_status",
            "internet_status",
            "inet_status",
        ),
        dsl_state=_first_text(raw, "dsl_link_status", "dsl_status"),
        dsl_downstream_bps=_first_int(raw, "dsl_downstream"),
        dsl_upstream_bps=_first_int(raw, "dsl_upstream"),
        wan_download_capacity_bps=_first_int(raw, "inet_download"),
        wan_upload_capacity_bps=_first_int(raw, "inet_upload"),
        raw=MappingProxyType(dict(raw)),
    )


def select_active_wan_interface(
    interfaces: tuple[WanInterface, ...] | list[WanInterface],
) -> WanInterface:
    """Select aggregate active WAN, avoiding LTE tunnel double counting."""
    candidates = [
        interface
        for interface in interfaces
        if interface.bytes_received is not None and interface.bytes_sent is not None
    ]
    if not candidates:
        msg = "No interface exposes both WAN byte counters"
        raise ValueError(msg)

    def score(interface: WanInterface) -> tuple[int, int]:
        identity = f"{interface.alias or ''} {interface.name or ''}".casefold()
        value = 100 if interface.is_up else 0
        if interface.is_aggregate:
            value += 1_000
        elif any(token in identity for token in ("wan", "internet", "ppp")):
            value += 600
        if any(token in identity for token in ("tunnel_lte", "lte", "mobile")):
            value -= 500
        if interface.enabled is True:
            value += 10
        return value, -interface.index

    return max(candidates, key=score)


def _first_text(raw: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_int(raw: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None
