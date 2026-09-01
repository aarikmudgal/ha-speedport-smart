"""Runtime owner for a Speedport Smart router."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .api import (
    SpeedportAuthenticationError,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from .const import DOMAIN, RATE_WINDOW_SECONDS
from .coordinator import GroupSnapshot, PollGroup, SpeedportDataUpdateCoordinator
from .management import ManagementExecutionSurface, get_command_write_contract
from .normalizers import normalize_feature_payload, normalize_status_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .api import SpeedportClient
    from .models import (
        CapabilityReport,
        DslMetrics,
        RouterInfo,
        RouterStatus,
        WanCounters,
    )

_LOGGER = logging.getLogger(__name__)

NORMAL_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "internet",
        "dsl",
        "hybrid",
        "mobile",
        "lte",
        "5g",
        "receiver",
        "mesh_topology",
        "wifi",
        "clients",
        "telephony",
        "calls",
        "active_calls",
        "dect_status",
        "ip",
        "wps",
    }
)
FAST_FAMILIES: Final[frozenset[str]] = frozenset()
_MIN_RATE_SAMPLES: Final = 2
_RATE_RETENTION_WINDOWS: Final = 2.0
_WAN_COUNTER_SAFE_START_SECONDS: Final = 5.0
_WAN_COUNTER_MAX_INTERVAL_SECONDS: Final = 60.0
_WAN_COUNTER_BUSY_RETRY_BASE_SECONDS: Final = 5.0
_WAN_COUNTER_ADAPT_SUCCESS_SAMPLES: Final = 12
_WAN_COUNTER_ADAPT_STEP_SECONDS: Final = 1.0
_DSL_BUSY_RETRY_SECONDS: Final = 5.0
_DSL_TRANSIENT_RETRY_SECONDS: Final = 60.0
_DSL_UNSUPPORTED_RETRY_SECONDS: Final = 300.0
_DSL_MAX_RETRY_SECONDS: Final = 3_600.0
_TRANSIENT_TELEMETRY_ENDPOINTS: Final = frozenset({"dsl_metrics", "wan_counters"})
_DSL_TRANSIENT_GRACE_FAILURES: Final = 1
_PROTECTED_RETRY_SECONDS: Final = 60.0
_PROTECTED_MAX_RETRY_SECONDS: Final = 900.0
_MANAGEMENT_ISSUE_KEY: Final = "management_session_blocked"
_FAMILY_ROUTES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "5g": ("mobile", "5g"),
        "active_calls": ("telephony", "active_calls"),
        "calls": ("telephony", "calls"),
        "connection_privacy": ("internet", "privacy"),
        "dect": ("dect",),
        "dect_status": ("dect", "status"),
        "dect_repeater": ("dect", "repeaters"),
        "dns_rebind": ("security", "dns_rebind"),
        "easy_support": ("system", "easy_support"),
        "firmware": ("system", "firmware_details"),
        "firewall": ("security", "firewall"),
        "ip": ("internet", "ip"),
        "ip_phones": ("pbx", "ip_phones"),
        "lte": ("mobile", "lte"),
        "mobile": ("mobile",),
        "mesh_topology": ("mesh", "nodes"),
        "media_server": ("usb", "media_server"),
        "nas": ("usb", "nas"),
        "parental_controls": ("parental", "configuration"),
        "pbx": ("pbx",),
        "phonebook": ("dect", "telephony", "phonebook"),
        "port_blocking": ("security", "port_blocking"),
        "port_forwarding": ("nat", "port_forwarding"),
        "qos": ("qos",),
        "receiver": ("receiver",),
        "telephony": ("telephony",),
        "upnp": ("nat", "upnp"),
        "usb_tethering": ("usb", "tethering"),
        "wifi_access": ("wifi", "access"),
        "wifi_configuration": ("wifi", "configuration"),
        "wifi_schedule": ("wifi", "schedule"),
        "wireguard": ("vpn", "wireguard"),
        "vpn_details": ("vpn", "details"),
        "wps": ("wifi", "wps"),
    }
)
_TRANSITION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "active",
        "available",
        "connected",
        "enabled",
        "firmware",
        "online",
        "present",
        "registered",
        "state",
        "status",
        "version",
    }
)
_MISSING = object()
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class RouterIdentity:
    """Stable router identity used by Home Assistant devices."""

    identifier: str
    model: str | None
    firmware: str | None
    serial_number: str | None
    hardware_version: str | None


@dataclass(frozen=True, slots=True)
class StateTransition:
    """One meaningful router state transition."""

    path: str
    previous: Any
    current: Any
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class _CounterSample:
    """Monotonic WAN counter sample."""

    sampled_at: float
    received: int
    sent: int


class SpeedportHub:
    """Coordinate router polling, normalization, transitions, and commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SpeedportClient,
        *,
        fallback_identifier: str,
        entry_id: str | None = None,
        controls_enabled: bool = False,
        rate_window_seconds: float = RATE_WINDOW_SECONDS,
        public_status_interval_seconds: float = 5.0,
        wan_counter_interval_seconds: float = 0.0,
        monotonic_time: Callable[[], float] | None = None,
    ) -> None:
        """Initialize hub."""
        self.hass = hass
        self.client = client
        self.controls_enabled = controls_enabled
        self.rate_window_seconds = max(rate_window_seconds, 1.0)
        self._public_status_interval = max(float(public_status_interval_seconds), 1.0)
        self._public_status_next_poll_at = 0.0
        configured_wan_interval = float(wan_counter_interval_seconds)
        self._wan_counter_auto_interval = configured_wan_interval <= 0
        self._wan_counter_target_interval = (
            1.0
            if self._wan_counter_auto_interval
            else max(configured_wan_interval, 1.0)
        )
        self._wan_counter_effective_interval = (
            _WAN_COUNTER_SAFE_START_SECONDS
            if self._wan_counter_auto_interval
            else self._wan_counter_target_interval
        )
        self._wan_counter_last_stable_interval = max(
            self._wan_counter_target_interval,
            _WAN_COUNTER_SAFE_START_SECONDS,
        )
        self._wan_counter_fastest_proven_interval: float | None = None
        self._wan_counter_runtime_floor = self._wan_counter_target_interval
        self._wan_counter_success_streak = 0
        self._monotonic_time = monotonic_time or hass.loop.time
        self.logger = _LOGGER

        self._fallback_identifier = fallback_identifier
        self._entry_id = entry_id
        self._router_info: RouterInfo | None = None
        self._capability_report: CapabilityReport | None = None
        self._capabilities: frozenset[str] = frozenset()
        self._data: Mapping[str, Any] = MappingProxyType({})
        self._mutable_data: dict[str, Any] = {}
        self._coordinators: dict[PollGroup, SpeedportDataUpdateCoordinator] = {}
        self._generation = 0
        self._operation_lock = asyncio.Lock()
        self._counter_samples: deque[_CounterSample] = deque(maxlen=64)
        self._wan_counter_probe_pending = False
        self._wan_counter_failures = 0
        self._wan_counter_busy_failures = 0
        self._wan_counter_retry_at = 0.0
        self._wan_counter_next_poll_at = 0.0
        self._dsl_metrics_failures = 0
        self._dsl_metrics_retry_at = 0.0
        self._transition_values: dict[str, Any] = {}
        self._last_transitions: tuple[StateTransition, ...] = ()
        self._endpoint_errors: dict[str, str] = {}
        self._update_failures = 0
        self._last_successful_update: datetime | None = None
        self._family_data: dict[str, dict[str, Any]] = {}
        self._public_status_data: dict[str, Any] = {}
        self._settings_write_blocked_latch: bool | None = None
        self._management_state = "unknown"
        self._management_owner: str | None = None
        self._management_retry_after: int | None = None
        self._management_changed_at = datetime.now(UTC)
        self._management_last_success: datetime | None = None
        self._protected_retry_at = 0.0
        self._protected_retry_failures = 0
        self._protected_invalidation_pending = False
        self._closed = False

    @property
    def router_info(self) -> RouterInfo | None:
        """Return router information reported by protocol layer."""
        return self._router_info

    @property
    def router_identity(self) -> RouterIdentity:
        """Return stable normalized router identity."""
        info = self._router_info
        serial = _clean_identifier(_model_value(info, "serial_number"))
        return RouterIdentity(
            identifier=serial or self._fallback_identifier,
            model=_string_or_none(_model_value(info, "model")),
            firmware=_string_or_none(_model_value(info, "firmware")),
            serial_number=_string_or_none(_model_value(info, "serial_number")),
            hardware_version=_string_or_none(_model_value(info, "hardware_version")),
        )

    @property
    def router_identifier(self) -> str:
        """Return stable identifier suitable for entity unique IDs."""
        return self.router_identity.identifier

    @property
    def data(self) -> Mapping[str, Any]:
        """Return immutable merged normalized data."""
        return self._data

    @property
    def capabilities(self) -> frozenset[str]:
        """Return discovered capability names."""
        return self._capabilities

    @property
    def capability_report(self) -> CapabilityReport | None:
        """Return latest capability report."""
        return self._capability_report

    @property
    def endpoint_errors(self) -> Mapping[str, str]:
        """Return a small immutable snapshot of current endpoint failures."""
        return MappingProxyType(dict(self._endpoint_errors))

    def has_endpoint_error(self, endpoint: str) -> bool:
        """Return whether one endpoint currently has a recorded failure."""
        return endpoint in self._endpoint_errors

    @property
    def wan_counter_telemetry(self) -> Mapping[str, Any]:
        """Return lightweight immutable adaptive WAN scheduler diagnostics."""
        monotonic_now = self._monotonic_time()
        return MappingProxyType(
            {
                "mode": ("auto" if self._wan_counter_auto_interval else "manual"),
                "state": self._wan_counter_adaptation_state(monotonic_now),
                "target_interval_seconds": self._wan_counter_target_interval,
                "effective_interval_seconds": self._wan_counter_effective_interval,
                "runtime_floor_seconds": self._wan_counter_runtime_floor,
                "last_stable_interval_seconds": (
                    self._wan_counter_fastest_proven_interval
                ),
                "success_streak": self._wan_counter_success_streak,
                "retrying": (monotonic_now < self._wan_counter_retry_at),
                "retry_in_seconds": max(
                    self._wan_counter_retry_at - monotonic_now,
                    0.0,
                ),
                "last_sampled_at": self.get("wan.sampled_at"),
            }
        )

    @property
    def last_transitions(self) -> tuple[StateTransition, ...]:
        """Return transitions emitted by latest update."""
        return self._last_transitions

    @property
    def available(self) -> bool:
        """Return whether any attached coordinator is available."""
        return any(
            coordinator.last_update_success
            for coordinator in self._coordinators.values()
        )

    @property
    def management_controls_available(self) -> bool:
        """Return whether a mutating request may start without bypassing backoff."""
        return (
            self._management_state == "available"
            and self._monotonic_time() >= self._protected_retry_at
            and self._settings_write_blocked_latch is not True
        )

    async def async_setup(self) -> None:
        """Open protocol client and discover router capabilities."""
        if self._closed:
            message = "Cannot set up a closed Speedport hub"
            raise SpeedportError(message)
        report = await self.client.setup(allow_protected_degraded=True)
        self._apply_capability_report(report)
        self._router_info = self.client.router_info
        management_error = self.client.last_management_error
        if isinstance(management_error, SpeedportSessionBusyError):
            self._mark_management_busy(management_error)
        elif isinstance(management_error, SpeedportLoginLockedError):
            self._mark_management_locked(management_error)
        elif management_error is not None or not report.authenticated_json:
            self._mark_management_unavailable()
        else:
            self._set_management_access("available")
        self._merge_data(
            {
                "router": _normalise_router_info(self._router_info),
                "management": {"access": self._management_access_payload()},
            }
        )

    async def async_close(self) -> None:
        """Close router client exactly once."""
        if self._closed:
            return
        self._closed = True
        await self.client.close()

    def attach_coordinator(
        self, group: PollGroup, coordinator: SpeedportDataUpdateCoordinator
    ) -> None:
        """Attach one coordinator to hub."""
        self._coordinators[group] = coordinator

    def coordinator(self, group: PollGroup | str) -> SpeedportDataUpdateCoordinator:
        """Return attached coordinator for group."""
        return self._coordinators[PollGroup(group)]

    @property
    def management_issue_id(self) -> str | None:
        """Return the per-entry repair issue identifier when available."""
        if self._entry_id is None:
            return None
        return f"{_MANAGEMENT_ISSUE_KEY}_{self._entry_id}"

    async def async_retry_protected_data(self) -> None:
        """Retry read-only protected discovery after the browser session logs out."""
        async with self._operation_lock:
            self._set_management_access("recovering", owner=self._management_owner)
            try:
                report = await self.client.probe_capabilities()
            except SpeedportSessionBusyError as err:
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Log out in the Speedport web interface before retrying"
                ) from err
            except SpeedportLoginLockedError as err:
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Speedport login is temporarily locked; retry after the cooldown"
                ) from err
            except SpeedportInvalidCredentialsError as err:
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Speedport rejected the configured device password"
                ) from err
            except SpeedportError as err:
                self._publish_authenticated_failure(err, force_unavailable=True)
                raise HomeAssistantError(
                    "Protected Speedport data could not be refreshed"
                ) from err

            if not report.authenticated_json:
                self._publish_authenticated_failure(
                    SpeedportAuthenticationError(
                        "Protected Speedport access was not confirmed"
                    )
                )
                raise HomeAssistantError("Protected Speedport access was not confirmed")
            self._apply_capability_report(report)
            self._set_management_access("available")
            if self._entry_id is not None:
                self.hass.config_entries.async_schedule_reload(self._entry_id)

    def has_capability(self, capability: str) -> bool:
        """Return whether router exposes capability."""
        return capability.casefold() in self._capabilities

    def supports_command(self, command: str) -> bool:
        """Return whether a native entity may expose an implemented command."""
        contract = get_command_write_contract(command)
        handler = getattr(self.client, command, None) or getattr(
            self.client, f"execute_{command}", None
        )
        identity = self.router_identity
        return (
            self.controls_enabled
            and self.has_capability("authenticated_json")
            and contract is not None
            and contract.execution_surface is ManagementExecutionSurface.NATIVE_ENTITY
            and contract.supports(identity.model, identity.firmware)
            and self.has_capability(contract.capability)
            and callable(handler)
        )

    def get(
        self,
        path: str | Iterable[str | int],
        default: _T | None = None,
    ) -> Any | _T | None:
        """Read nested normalized data using dotted string or path components."""
        parts: Iterable[str | int]
        parts = path.split(".") if isinstance(path, str) else path
        current: Any = self._data
        for part in parts:
            if isinstance(current, Mapping):
                if part not in current:
                    return default
                current = current[part]
            elif isinstance(current, (list, tuple)) and isinstance(part, int):
                if part >= len(current) or part < -len(current):
                    return default
                current = current[part]
            else:
                return default
        return current

    async def async_update_group(self, group: PollGroup) -> GroupSnapshot:
        """Update one group while keeping multi-request router work serialized."""
        async with self._operation_lock:
            return await self._async_update_group_locked(group)

    async def _async_update_group_locked(self, group: PollGroup) -> GroupSnapshot:
        """Update one group while operation lock is held."""
        started_at = time.perf_counter()
        if self._closed:
            message = "Speedport hub is closed"
            raise SpeedportConnectionError(message)

        try:
            if group is PollGroup.FAST:
                partial = await self._async_fetch_fast()
            elif group is PollGroup.NORMAL:
                partial = await self._async_fetch_normal()
            else:
                partial = await self._async_fetch_families(
                    self._feature_families - NORMAL_FAMILIES - FAST_FAMILIES
                )
        except SpeedportInvalidCredentialsError as err:
            self._mark_management_unavailable()
            invalidated = self._invalidate_authenticated_families(
                {}, error_name=type(err).__name__
            )
            transitions = self._merge_data(invalidated)
            self._generation += 1
            self._last_transitions = transitions
            self._publish_protected_invalidation(
                updated_group=group,
                updated_at=datetime.now(UTC),
                transitions=transitions,
            )
            raise

        now = datetime.now(UTC)
        self._last_successful_update = now
        partial = _deep_merge_dicts(
            partial,
            {
                "diagnostics": {
                    "last_successful_update": now.isoformat(),
                    "problem": self._has_router_problem(),
                    "request_latency_ms": round(
                        (time.perf_counter() - started_at) * 1_000,
                        3,
                    ),
                    "update_failures": self._update_failures,
                }
            },
        )
        transitions = self._merge_data(partial)
        self._generation += 1
        snapshot = GroupSnapshot(
            group=group,
            data=self._data,
            generation=self._generation,
            updated_at=now,
            transitions=transitions,
        )
        self._last_transitions = transitions
        self._publish_protected_invalidation(
            updated_group=group,
            updated_at=now,
            transitions=transitions,
        )
        return snapshot

    def _publish_protected_invalidation(
        self,
        *,
        updated_group: PollGroup | None,
        updated_at: datetime,
        transitions: tuple[StateTransition, ...],
    ) -> None:
        """Publish one protected-state invalidation to other poll groups."""
        if not self._protected_invalidation_pending:
            return
        self._protected_invalidation_pending = False
        for other_group, coordinator in self._coordinators.items():
            if updated_group is not None and other_group is updated_group:
                continue
            coordinator.async_set_updated_data(
                GroupSnapshot(
                    group=other_group,
                    data=self._data,
                    generation=self._generation,
                    updated_at=updated_at,
                    transitions=transitions,
                )
            )

    def record_update_failure(self, group: PollGroup, error: Exception) -> None:
        """Record coordinator failure without exposing error text or router data."""
        self._update_failures += 1
        self._merge_data(
            {
                "diagnostics": {
                    "failed_group": group.value,
                    "last_error": type(error).__name__,
                    "last_successful_update": (
                        self._last_successful_update.isoformat()
                        if self._last_successful_update
                        else None
                    ),
                    "problem": True,
                    "update_failures": self._update_failures,
                }
            }
        )

    def _management_access_payload(self) -> dict[str, Any]:
        """Return normalized, UI-safe management access state."""
        return {
            "state": self._management_state,
            "owner_ip_address": self._management_owner,
            "retry_after_seconds": self._management_retry_after,
            "last_changed": self._management_changed_at.isoformat(),
            "last_successful_update": (
                self._management_last_success.isoformat()
                if self._management_last_success is not None
                else None
            ),
            "browser_logout_required": self._management_state
            in {"blocked", "other_session"},
        }

    def _set_management_access(
        self,
        state: str,
        *,
        owner: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        """Update management state and its actionable repair issue."""
        now = datetime.now(UTC)
        changed = (
            state != self._management_state
            or owner != self._management_owner
            or retry_after != self._management_retry_after
        )
        self._management_state = state
        self._management_owner = owner
        self._management_retry_after = retry_after
        if changed:
            self._management_changed_at = now
        if state == "available":
            self._management_last_success = now
            self._protected_retry_at = 0.0
            self._protected_retry_failures = 0
            self._delete_management_issue()
        self._merge_data({"management": {"access": self._management_access_payload()}})

    def _mark_management_busy(self, error: SpeedportSessionBusyError) -> None:
        """Expose an occupied management lease and schedule a safe retry."""
        self._protected_retry_failures += 1
        delay = min(
            _PROTECTED_RETRY_SECONDS
            * (2 ** min(self._protected_retry_failures - 1, 4)),
            _PROTECTED_MAX_RETRY_SECONDS,
        )
        self._protected_retry_at = self._monotonic_time() + delay
        owner = error.owner or self._management_owner
        state = "other_session" if owner is not None else "blocked"
        self._set_management_access(state, owner=owner)
        self._create_management_issue()

    def _mark_management_locked(self, error: SpeedportLoginLockedError) -> None:
        """Expose router-enforced login cooldown without treating it as bad auth."""
        retry_after = error.retry_after or int(_PROTECTED_RETRY_SECONDS)
        self._protected_retry_at = self._monotonic_time() + retry_after
        self._set_management_access("locked", retry_after=retry_after)

    def _mark_management_unavailable(self) -> None:
        """Back off a protected-session failure while public polling continues."""
        self._protected_retry_failures += 1
        delay = min(
            _PROTECTED_RETRY_SECONDS
            * (2 ** min(self._protected_retry_failures - 1, 4)),
            _PROTECTED_MAX_RETRY_SECONDS,
        )
        self._protected_retry_at = self._monotonic_time() + delay
        self._set_management_access("unavailable")

    def _record_authenticated_failure(self, error: SpeedportError) -> bool:
        """Reflect an authenticated failure; return whether session state changed."""
        if isinstance(error, SpeedportCommandRejectedError):
            return False
        if isinstance(error, SpeedportSessionBusyError):
            self._mark_management_busy(error)
            return True
        if isinstance(error, SpeedportLoginLockedError):
            self._mark_management_locked(error)
            return True
        if isinstance(error, SpeedportConnectionError):
            self._mark_management_unavailable()
            return True
        if isinstance(error, SpeedportAuthenticationError) or (
            isinstance(error, SpeedportProtocolError)
            and not isinstance(error, SpeedportUnsupportedError)
        ):
            self._mark_management_unavailable()
            return True
        return False

    def _publish_authenticated_failure(
        self,
        error: SpeedportError,
        *,
        force_unavailable: bool = False,
    ) -> None:
        """Clear protected caches discovered stale outside coordinator polling."""
        if not self._record_authenticated_failure(error):
            if not force_unavailable:
                return
            self._mark_management_unavailable()
        if isinstance(error, SpeedportInvalidCredentialsError):
            self._start_reauth()
        invalidated = self._invalidate_authenticated_families(
            {}, error_name=type(error).__name__
        )
        transitions = self._merge_data(invalidated)
        self._generation += 1
        self._last_transitions = transitions
        # Publish management state even when no protected family had cached data.
        self._protected_invalidation_pending = True
        self._publish_protected_invalidation(
            updated_group=None,
            updated_at=datetime.now(UTC),
            transitions=transitions,
        )

    def _start_reauth(self) -> None:
        """Start Home Assistant reauthentication for definitive credentials loss."""
        if self._entry_id is None:
            return
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None:
            entry.async_start_reauth(self.hass)

    def _create_management_issue(self) -> None:
        """Create one persistent, per-entry repair for browser session contention."""
        issue_id = self.management_issue_id
        if issue_id is None or self._entry_id is None:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            data={"entry_id": self._entry_id},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key=_MANAGEMENT_ISSUE_KEY,
        )

    def _delete_management_issue(self) -> None:
        """Remove the browser-session repair only after protected access succeeds."""
        issue_id = self.management_issue_id
        if issue_id is not None:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _async_retry_degraded_access(self) -> None:
        """Periodically retry read-only discovery after a blocked startup."""
        if self._management_state not in {
            "blocked",
            "locked",
            "other_session",
            "unavailable",
        }:
            return
        if self._monotonic_time() < self._protected_retry_at:
            return
        report = await self.client.probe_capabilities(allow_protected_degraded=True)
        management_error = self.client.last_management_error
        if isinstance(management_error, SpeedportSessionBusyError):
            self._mark_management_busy(management_error)
            return
        if isinstance(management_error, SpeedportLoginLockedError):
            self._mark_management_locked(management_error)
            return
        if management_error is not None:
            self._mark_management_unavailable()
            return
        if not report.authenticated_json:
            self._mark_management_unavailable()
            return
        self._apply_capability_report(report)
        self._set_management_access("available")
        if self._entry_id is not None:
            self.hass.config_entries.async_schedule_reload(self._entry_id)

    async def _async_fetch_fast(self) -> dict[str, Any]:
        """Fetch status and aggregate WAN counters."""
        now = self._monotonic_time()
        status: RouterStatus | None = None
        partial: dict[str, Any] = {}
        if now >= self._public_status_next_poll_at:
            try:
                status = await self.client.get_status()
            except SpeedportInvalidCredentialsError:
                raise
            except SpeedportError as err:
                self._endpoint_errors["status"] = type(err).__name__
                partial = self._unavailable_public_status_values()
            else:
                self._router_info = status.info
                partial, inferred_capabilities = normalize_status_payload(status)
                self._public_status_data = _thaw(partial)
                self._capabilities = self._capabilities | inferred_capabilities
                self._endpoint_errors.pop("status", None)
            self._public_status_next_poll_at = (
                self._monotonic_time() + self._public_status_interval
            )

        report = self._capability_report
        wan_counters_confirmed = report is not None and report.wan_counters
        wan_retry_deferred = now < self._wan_counter_retry_at
        wan_poll_deferred = now < self._wan_counter_next_poll_at
        if wan_retry_deferred:
            self._counter_samples.clear()
            if wan_counters_confirmed:
                partial["wan"] = _deep_merge_dicts(
                    cast("dict[str, Any]", partial.get("wan", {})),
                    self._unavailable_wan_live_values(),
                )
        elif wan_poll_deferred:
            # Public status and ToTR64 use independent due times on the same 1-second
            # scheduler. Keep the latest counter sample until its cadence is due.
            pass
        elif wan_counters_confirmed or self._wan_counter_probe_pending:
            # Rate-limit every ToTR64 attempt, including protocol errors that do not
            # enter the dedicated session-busy retry path.
            self._wan_counter_next_poll_at = now + self._wan_counter_effective_interval
            try:
                counters = await self.client.get_wan_counters(busy_retries=0)
            except SpeedportSessionBusyError as err:
                self._counter_samples.clear()
                self._endpoint_errors["wan_counters"] = type(err).__name__
                self._defer_wan_counter_retry()
                if wan_counters_confirmed:
                    partial["wan"] = _deep_merge_dicts(
                        cast("dict[str, Any]", partial.get("wan", {})),
                        self._unavailable_wan_live_values(),
                    )
            except SpeedportUnsupportedError as err:
                self._counter_samples.clear()
                self._wan_counter_busy_failures = 0
                self._wan_counter_success_streak = 0
                self._wan_counter_retry_at = 0.0
                self._wan_counter_next_poll_at = (
                    self._monotonic_time() + self._wan_counter_effective_interval
                )
                if not wan_counters_confirmed:
                    self._reject_pending_wan_counter_capability()
                    self._endpoint_errors.pop("wan_counters", None)
                else:
                    self._wan_counter_failures += 1
                    self._endpoint_errors["wan_counters"] = type(err).__name__
                    partial["wan"] = _deep_merge_dicts(
                        cast("dict[str, Any]", partial.get("wan", {})),
                        self._unavailable_wan_live_values(),
                    )
            except SpeedportError as err:
                self._counter_samples.clear()
                self._wan_counter_busy_failures = 0
                self._wan_counter_success_streak = 0
                self._wan_counter_retry_at = 0.0
                self._wan_counter_next_poll_at = (
                    self._monotonic_time() + self._wan_counter_effective_interval
                )
                self._endpoint_errors["wan_counters"] = type(err).__name__
                if wan_counters_confirmed:
                    partial["wan"] = _deep_merge_dicts(
                        cast("dict[str, Any]", partial.get("wan", {})),
                        self._degraded_wan_values(),
                    )
            else:
                self._wan_counter_probe_pending = False
                self._wan_counter_failures = 0
                self._wan_counter_busy_failures = 0
                self._wan_counter_retry_at = 0.0
                self._record_wan_counter_success()
                self._wan_counter_next_poll_at = (
                    self._monotonic_time() + self._wan_counter_effective_interval
                )
                self._confirm_tr064_capability(wan_counters=True)
                self._endpoint_errors.pop("wan_counters", None)
                partial["wan"] = _deep_merge_dicts(
                    cast("dict[str, Any]", partial.get("wan", {})),
                    self._normalise_wan_counters(
                        counters,
                        download_capacity=(
                            status.wan_download_capacity_bps
                            if status
                            else self.get("internet.download_capacity_bps")
                        ),
                        upload_capacity=(
                            status.wan_upload_capacity_bps
                            if status
                            else self.get("internet.upload_capacity_bps")
                        ),
                    ),
                )

        return partial

    def _has_router_problem(self) -> bool:
        """Exclude an isolated ToTR64 lease retry from global router health."""
        return any(
            family not in _TRANSIENT_TELEMETRY_ENDPOINTS
            or error_name != SpeedportSessionBusyError.__name__
            for family, error_name in self._endpoint_errors.items()
        )

    async def _async_fetch_normal(self) -> dict[str, Any]:
        """Fetch medium-frequency feature data and verified DSL telemetry."""
        await self._async_retry_degraded_access()
        partial = await self._async_fetch_families(NORMAL_FAMILIES)
        now = self._monotonic_time()
        if (
            self.has_capability("dsl")
            and self.has_capability("tr064")
            and now >= self._dsl_metrics_retry_at
        ):
            try:
                metrics = await self.client.get_dsl_metrics()
            except SpeedportSessionBusyError as err:
                self._defer_dsl_metrics_busy_retry()
                self._endpoint_errors["dsl_metrics"] = type(err).__name__
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._unavailable_dsl_optional_values()},
                )
            except SpeedportUnsupportedError as err:
                self._defer_dsl_metrics_retry(unsupported=True)
                self._endpoint_errors["dsl_metrics"] = type(err).__name__
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._unavailable_dsl_optional_values()},
                )
            except SpeedportError as err:
                self._defer_dsl_metrics_retry(unsupported=False)
                self._endpoint_errors["dsl_metrics"] = type(err).__name__
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._degraded_dsl_optional_values()},
                )
            else:
                self._dsl_metrics_failures = 0
                self._dsl_metrics_retry_at = 0.0
                self._confirm_tr064_capability(dsl_metrics=True)
                self._endpoint_errors.pop("dsl_metrics", None)
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._normalise_dsl_metrics(metrics)},
                )
        return partial

    def _normalise_dsl_metrics(self, metrics: DslMetrics) -> dict[str, Any]:
        """Map typed ToTR64 DSL telemetry onto the entity contract."""
        values: dict[str, Any] = {
            "line_index": metrics.line_index,
            "channel_index": metrics.channel_index,
        }
        live_values = {
            "state": _connection_state(metrics.status),
            "downstream_bps": metrics.downstream_current_bps,
            "upstream_bps": metrics.upstream_current_bps,
        }
        optional_values = {
            "attainable_downstream_bps": metrics.downstream_max_bps,
            "attainable_upstream_bps": metrics.upstream_max_bps,
            "snr_downstream_db": metrics.downstream_noise_margin_db,
            "snr_upstream_db": metrics.upstream_noise_margin_db,
            "attenuation_downstream_db": metrics.downstream_attenuation_db,
            "attenuation_upstream_db": metrics.upstream_attenuation_db,
        }
        values.update(
            {key: value for key, value in live_values.items() if value is not None}
        )
        values.update(
            {
                key: value
                for key, value in optional_values.items()
                if value is not None or self.get(("dsl", key), _MISSING) is not _MISSING
            }
        )
        return values

    def _defer_dsl_metrics_retry(self, *, unsupported: bool) -> None:
        """Back off optional DSL telemetry without disabling it permanently."""
        self._dsl_metrics_failures += 1
        base = (
            _DSL_UNSUPPORTED_RETRY_SECONDS
            if unsupported
            else _DSL_TRANSIENT_RETRY_SECONDS
        )
        exponent = min(self._dsl_metrics_failures - 1, 6)
        delay = min(base * (2**exponent), _DSL_MAX_RETRY_SECONDS)
        self._dsl_metrics_retry_at = self._monotonic_time() + delay

    def _defer_wan_counter_retry(self) -> None:
        """Adaptively back off a ToTR64 lease without blocking web access."""
        self._wan_counter_busy_failures += 1
        self._wan_counter_success_streak = 0
        now = self._monotonic_time()
        if (
            self._wan_counter_effective_interval
            < self._wan_counter_last_stable_interval
        ):
            self._wan_counter_effective_interval = (
                self._wan_counter_last_stable_interval
            )
            self._wan_counter_runtime_floor = max(
                self._wan_counter_runtime_floor,
                self._wan_counter_last_stable_interval,
            )
        exponent = min(self._wan_counter_busy_failures - 1, 4)
        retry_delay = min(
            _WAN_COUNTER_BUSY_RETRY_BASE_SECONDS * (2**exponent),
            _WAN_COUNTER_MAX_INTERVAL_SECONDS,
        )
        self._wan_counter_retry_at = now + max(
            self._wan_counter_effective_interval,
            retry_delay,
        )

    def _record_wan_counter_success(self) -> None:
        """Probe toward the requested cadence only after sustained stable reads."""
        adaptation_target = max(
            self._wan_counter_target_interval,
            self._wan_counter_runtime_floor,
        )
        if (
            self._wan_counter_runtime_floor > self._wan_counter_target_interval
            and self._wan_counter_effective_interval <= adaptation_target
        ) or (
            self._wan_counter_effective_interval <= self._wan_counter_target_interval
            and self._wan_counter_fastest_proven_interval is not None
            and self._wan_counter_effective_interval
            >= self._wan_counter_last_stable_interval
        ):
            self._wan_counter_success_streak = 0
            return
        self._wan_counter_success_streak += 1
        if self._wan_counter_success_streak < _WAN_COUNTER_ADAPT_SUCCESS_SAMPLES:
            return
        if self._wan_counter_fastest_proven_interval is None:
            self._wan_counter_fastest_proven_interval = (
                self._wan_counter_effective_interval
            )
        else:
            self._wan_counter_fastest_proven_interval = min(
                self._wan_counter_fastest_proven_interval,
                self._wan_counter_effective_interval,
            )
        self._wan_counter_last_stable_interval = min(
            self._wan_counter_last_stable_interval,
            self._wan_counter_effective_interval,
        )
        self._wan_counter_effective_interval = max(
            adaptation_target,
            self._wan_counter_effective_interval - _WAN_COUNTER_ADAPT_STEP_SECONDS,
        )
        self._wan_counter_success_streak = 0

    def _defer_dsl_metrics_busy_retry(self) -> None:
        """Retry a transient ToTR64 DSL lease on the next normal poll."""
        self._dsl_metrics_failures += 1
        self._dsl_metrics_retry_at = self._monotonic_time() + _DSL_BUSY_RETRY_SECONDS

    def _confirm_tr064_capability(
        self,
        *,
        dsl_metrics: bool = False,
        wan_counters: bool = False,
    ) -> None:
        """Promote a successful ToTR64 read and retire stale busy failures."""
        capabilities = {"tr064"}
        if dsl_metrics:
            capabilities.add("dsl_metrics")
        if wan_counters:
            capabilities.update({"wan", "wan_counters"})
        self._capabilities = self._capabilities | capabilities

        report = self._capability_report
        if report is None:
            return
        failures = dict(report.failures)
        failures.pop("tr064", None)
        if wan_counters:
            failures.pop("wan_counters", None)
        self._capability_report = replace(
            report,
            tr064=True,
            wan_counters=report.wan_counters or wan_counters,
            failures=MappingProxyType(failures),
        )

    def _unavailable_dsl_optional_values(self) -> dict[str, None]:
        """Clear only previously observed optional DSL telemetry."""
        fields = (
            "attainable_downstream_bps",
            "attainable_upstream_bps",
            "snr_downstream_db",
            "snr_upstream_db",
            "attenuation_downstream_db",
            "attenuation_upstream_db",
            "line_index",
            "channel_index",
        )
        return {
            field: None
            for field in fields
            if self.get(("dsl", field), _MISSING) is not _MISSING
        }

    def _degraded_dsl_optional_values(self) -> dict[str, None]:
        """Preserve slow DSL metrics through one transient retry window."""
        if self._dsl_metrics_failures <= _DSL_TRANSIENT_GRACE_FAILURES:
            return {}
        return self._unavailable_dsl_optional_values()

    def _degraded_wan_values(self) -> dict[str, None]:
        """Clear only derived live values after a transient counter failure."""
        self._wan_counter_failures += 1
        return self._unavailable_wan_live_values()

    @staticmethod
    def _unavailable_wan_live_values() -> dict[str, None]:
        """Clear rates that must never remain stale after a counter failure."""
        return {
            "download_rate_bps": None,
            "upload_rate_bps": None,
            "download_utilization": None,
            "upload_utilization": None,
        }

    def _unavailable_public_status_values(self) -> dict[str, Any]:
        """Invalidate cached public status while retaining other source values."""
        unavailable = _null_values(self._public_status_data)
        for family, family_data in self._family_data.items():
            if family in self._endpoint_errors:
                continue
            unavailable = _restore_values_at_paths(unavailable, family_data)
        return unavailable

    def _reject_pending_wan_counter_capability(self) -> None:
        """Remove a disproved setup probe without hiding independent WAN data."""
        self._wan_counter_probe_pending = False
        capabilities = set(self._capabilities)
        capabilities.discard("wan_counters")
        if not self._has_independent_wan_capability():
            capabilities.discard("wan")
        self._capabilities = frozenset(capabilities)

        report = self._capability_report
        if report is None:
            return
        failures = dict(report.failures)
        failures.pop("wan_counters", None)
        self._capability_report = replace(
            report,
            failures=MappingProxyType(failures),
        )

    def _has_independent_wan_capability(self) -> bool:
        """Return whether a source other than ToTR64 counters contributes WAN."""
        report = self._capability_report
        if report is not None and any(
            str(family).casefold() == "wan" for family in report.feature_endpoints
        ):
            return True
        public_wan = self._public_status_data.get("wan")
        return isinstance(public_wan, Mapping) and bool(public_wan)

    async def _async_fetch_families(self, families: Iterable[str]) -> dict[str, Any]:
        """Fetch feature endpoints, isolating failures between families."""
        selected = sorted(set(families) & self._feature_families)
        if not selected:
            return {}

        partial: dict[str, Any] = {}
        report = self._capability_report
        if report is None:
            return partial

        endpoint_groups: dict[tuple[str, bool, str | None], list[str]] = {}
        for family in selected:
            capability = report.feature_endpoints.get(family)
            if capability is None or capability.endpoint == "data/Status.json":
                continue
            endpoint_groups.setdefault(
                (
                    capability.endpoint,
                    capability.authenticated,
                    capability.referer,
                ),
                [],
            ).append(family)

        authenticated_attempted = False
        authenticated_succeeded = False
        authenticated_blocked = False
        ordered_endpoint_groups = sorted(
            endpoint_groups.items(),
            key=lambda item: (
                item[0][1],
                item[0][0],
                item[0][2] or "",
            ),
        )
        protected_retry_deferred = (
            self._management_state
            in {"blocked", "locked", "other_session", "unavailable"}
            and self._monotonic_time() < self._protected_retry_at
        )
        if protected_retry_deferred:
            partial = self._invalidate_authenticated_families(partial)
        try:
            for (
                endpoint,
                authenticated,
                referer,
            ), endpoint_families in ordered_endpoint_groups:
                if authenticated and protected_retry_deferred:
                    continue
                authenticated_attempted |= authenticated
                try:
                    value = await self.client.get_json(
                        endpoint,
                        authenticated=authenticated,
                        referer=referer,
                    )
                except SpeedportInvalidCredentialsError:
                    raise
                except SpeedportLoginLockedError as err:
                    authenticated_blocked = True
                    self._mark_management_locked(err)
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=type(err).__name__
                    )
                    break
                except SpeedportAuthenticationError as err:
                    authenticated_blocked = True
                    self._mark_management_unavailable()
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=type(err).__name__
                    )
                    break
                except SpeedportSessionBusyError as err:
                    authenticated_blocked = True
                    self._mark_management_busy(err)
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=type(err).__name__
                    )
                    break
                except SpeedportUnsupportedError as err:
                    failed_families = frozenset(endpoint_families)
                    for family in endpoint_families:
                        self._endpoint_errors[family] = type(err).__name__
                    for family in endpoint_families:
                        partial = _deep_merge_dicts(
                            partial,
                            self._unavailable_family_data(
                                family,
                                excluded_families=failed_families,
                            ),
                        )
                except SpeedportError as err:
                    if authenticated:
                        authenticated_blocked = True
                        self._mark_management_unavailable()
                        partial = self._invalidate_authenticated_families(
                            partial, error_name=type(err).__name__
                        )
                        break
                    for family in endpoint_families:
                        self._endpoint_errors[family] = type(err).__name__
                    failed_families = frozenset(endpoint_families)
                    for family in endpoint_families:
                        partial = _deep_merge_dicts(
                            partial,
                            self._unavailable_family_data(
                                family,
                                excluded_families=failed_families,
                            ),
                        )
                else:
                    authenticated_succeeded |= authenticated
                    for family in endpoint_families:
                        self._endpoint_errors.pop(family, None)
                        self.client.observe_feature_data(family, value)
                        normalized = normalize_feature_payload(family, value)
                        previous = self._family_data.get(family)
                        if previous is not None:
                            partial = _deep_merge_dicts(
                                partial,
                                _restore_values_at_paths(
                                    _removed_values(previous, normalized),
                                    self._family_fallback_data(
                                        excluded_families=(family,)
                                    ),
                                ),
                            )
                        self._family_data[family] = normalized
                        partial = _deep_merge_dicts(
                            partial,
                            normalized,
                        )
        finally:
            if authenticated_attempted:
                await self.client.logout()

        if authenticated_attempted and not authenticated_blocked:
            if authenticated_succeeded:
                self._set_management_access("available")
            else:
                self._mark_management_unavailable()

        return partial

    def _authenticated_feature_families(self) -> frozenset[str]:
        """Return every feature family requiring the protected router session."""
        report = self._capability_report
        if report is None:
            return frozenset()
        return frozenset(
            family
            for family, capability in report.feature_endpoints.items()
            if capability.authenticated and capability.endpoint != "data/Status.json"
        )

    def _invalidate_authenticated_families(
        self,
        partial: Mapping[str, Any],
        *,
        error_name: str | None = None,
    ) -> dict[str, Any]:
        """Clear all protected fields and flag other poll groups for notification."""
        invalidated: dict[str, Any] = {}
        authenticated_families = self._authenticated_feature_families()
        for family in authenticated_families:
            if error_name is not None:
                self._endpoint_errors[family] = error_name
            invalidated = _deep_merge_dicts(
                invalidated,
                self._unavailable_family_data(
                    family,
                    excluded_families=authenticated_families,
                ),
            )

        before = _deep_merge_dicts(self._mutable_data, partial)
        after = _deep_merge_dicts(before, invalidated)
        if after != before:
            self._protected_invalidation_pending = True
        return _deep_merge_dicts(partial, invalidated)

    def _unavailable_family_data(
        self,
        family: str,
        *,
        excluded_families: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Replace only values previously contributed by one family with nulls."""
        previous = self._family_data.get(family)
        if previous is None:
            return {}
        return _restore_values_at_paths(
            _null_values(previous),
            self._family_fallback_data(excluded_families=(*excluded_families, family)),
        )

    def _family_fallback_data(
        self,
        *,
        excluded_families: Iterable[str],
    ) -> dict[str, Any]:
        """Merge healthy alternate sources used when one family drops a field."""
        excluded = frozenset(excluded_families)
        fallback = _deep_merge_dicts({}, self._public_status_data)
        for source_family in sorted(self._family_data):
            if source_family in excluded or source_family in self._endpoint_errors:
                continue
            fallback = _deep_merge_dicts(
                fallback,
                self._family_data[source_family],
            )
        return fallback

    def _normalise_wan_counters(
        self,
        counters: WanCounters,
        *,
        download_capacity: int | None = None,
        upload_capacity: int | None = None,
    ) -> dict[str, Any]:
        """Normalize counters and calculate non-negative monotonic rates."""
        received = max(int(counters.bytes_received), 0)
        sent = max(int(counters.bytes_sent), 0)
        now = self._monotonic_time()
        sample = _CounterSample(now, received, sent)

        if self._counter_samples:
            previous = self._counter_samples[-1]
            if received < previous.received or sent < previous.sent:
                self._counter_samples.clear()

        self._counter_samples.append(sample)
        while (
            len(self._counter_samples) > _MIN_RATE_SAMPLES
            and now - self._counter_samples[0].sampled_at
            > self.rate_window_seconds * _RATE_RETENTION_WINDOWS
        ):
            self._counter_samples.popleft()

        baseline = self._rate_baseline(now)
        download_rate: float | None = None
        upload_rate: float | None = None
        if baseline is not None:
            elapsed = now - baseline.sampled_at
            received_delta = received - baseline.received
            sent_delta = sent - baseline.sent
            if elapsed > 0 and received_delta >= 0 and sent_delta >= 0:
                download_rate = received_delta * 8 / elapsed
                upload_rate = sent_delta * 8 / elapsed

        interface = counters.interface
        wan: dict[str, Any] = {
            "bytes_received": received,
            "bytes_sent": sent,
            "sampled_at": counters.sampled_at.isoformat(),
            "download_rate_bps": download_rate,
            "upload_rate_bps": upload_rate,
            "interface": {
                "index": interface.index,
                "alias": interface.alias,
                "name": interface.name,
                "status": interface.status,
                "enabled": interface.enabled,
            },
        }
        for field_name in (
            "packets_received",
            "packets_sent",
            "errors_received",
            "errors_sent",
            "discard_packets_received",
            "discard_packets_sent",
        ):
            value = getattr(counters, field_name, None)
            if value is not None:
                wan[field_name] = max(int(value), 0)
            elif self.get(("wan", field_name), _MISSING) is not _MISSING:
                wan[field_name] = None
        if download_capacity is None:
            download_capacity = self.get("internet.download_capacity_bps")
        if upload_capacity is None:
            upload_capacity = self.get("internet.upload_capacity_bps")
        wan["download_utilization"] = _utilization(download_rate, download_capacity)
        wan["upload_utilization"] = _utilization(upload_rate, upload_capacity)
        return wan

    def _rate_baseline(self, now: float) -> _CounterSample | None:
        """Choose oldest sample within rolling rate window."""
        if len(self._counter_samples) < _MIN_RATE_SAMPLES:
            return None
        eligible = [
            sample
            for sample in self._counter_samples
            if 0 < now - sample.sampled_at <= self.rate_window_seconds
        ]
        return eligible[0] if eligible else self._counter_samples[-2]

    async def async_execute(
        self,
        command: str,
        *,
        verify_group: PollGroup | None = PollGroup.NORMAL,
        **parameters: Any,
    ) -> Any:
        """Run one allowed native-entity command and optionally publish readback."""
        if not self.controls_enabled:
            raise HomeAssistantError(
                "Router controls are disabled in the Telekom Speedport Smart "
                "integration options.",
                translation_domain=DOMAIN,
                translation_key="controls_disabled",
            )
        if not self.supports_command(command):
            raise HomeAssistantError(
                "This router does not support the requested action.",
                translation_domain=DOMAIN,
                translation_key="command_unsupported",
            )

        handler = getattr(self.client, command, None)
        if handler is None:
            handler = getattr(self.client, f"execute_{command}", None)
        if not callable(handler):
            raise HomeAssistantError(
                "This router does not support the requested action.",
                translation_domain=DOMAIN,
                translation_key="command_unsupported",
            )

        async with self._operation_lock:
            if not self.management_controls_available:
                raise HomeAssistantError(
                    "The router management session is not currently available.",
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                )
            try:
                try:
                    result = await handler(**parameters)
                except SpeedportError as err:
                    self._publish_authenticated_failure(err)
                    raise HomeAssistantError(
                        "The router could not complete the requested action. Check the "
                        "Home Assistant log before trying again.",
                        translation_domain=DOMAIN,
                        translation_key="command_failed",
                    ) from err

                if verify_group is None:
                    return result

                try:
                    await self._async_update_group_locked(verify_group)
                except SpeedportError as err:
                    self._publish_authenticated_failure(err)
                    raise HomeAssistantError(
                        "The router action was sent, but its resulting state could not "
                        "be verified. Check the router state before trying again.",
                        translation_domain=DOMAIN,
                        translation_key="command_verification_failed",
                    ) from err
                coordinator = self._coordinators.get(verify_group)
                if coordinator is not None:
                    coordinator.async_set_updated_data(
                        GroupSnapshot(
                            group=verify_group,
                            data=self._data,
                            generation=self._generation,
                            updated_at=datetime.now(UTC),
                            transitions=self._last_transitions,
                        )
                    )
                return result
            finally:
                await self.client.logout()

    def diagnostics(self) -> dict[str, Any]:
        """Return plain diagnostic data; diagnostics module performs redaction."""
        monotonic_now = self._monotonic_time()
        observed_schema: object = self.client.observed_feature_schema
        if not isinstance(observed_schema, Mapping):
            observed_schema = MappingProxyType({})
        observed_candidate_schema: object = self.client.observed_candidate_schema
        if not isinstance(observed_candidate_schema, Mapping):
            observed_candidate_schema = MappingProxyType({})
        return {
            "router": _normalise_router_info(self._router_info),
            "capabilities": sorted(self._capabilities),
            "capability_report": _thaw(self._capability_report),
            "data": _thaw(self._data),
            "observed_feature_schema": _thaw(observed_schema),
            "observed_candidate_schema": _thaw(observed_candidate_schema),
            "endpoint_errors": dict(self.endpoint_errors),
            "telemetry": {
                "public_status": {
                    "interval_seconds": self._public_status_interval,
                    "next_poll_in_seconds": max(
                        self._public_status_next_poll_at - monotonic_now,
                        0.0,
                    ),
                },
                "wan_counters": dict(self.wan_counter_telemetry),
            },
            "polling": {
                group.value: {
                    "available": coordinator.last_update_success,
                    "last_exception": (
                        type(coordinator.last_exception).__name__
                        if coordinator.last_exception
                        else None
                    ),
                    "update_interval_seconds": (
                        coordinator.update_interval.total_seconds()
                        if coordinator.update_interval
                        else None
                    ),
                }
                for group, coordinator in self._coordinators.items()
            },
        }

    def _wan_counter_adaptation_state(self, now: float) -> str:
        """Return a stable, UI-safe WAN telemetry scheduler state."""
        if now < self._wan_counter_retry_at:
            return "retrying"
        if self._wan_counter_runtime_floor > self._wan_counter_target_interval:
            return "limited"
        if self._wan_counter_effective_interval > self._wan_counter_target_interval or (
            self._wan_counter_auto_interval
            and self._wan_counter_effective_interval
            < self._wan_counter_last_stable_interval
        ):
            return "learning"
        return "stable"

    @property
    def _feature_families(self) -> frozenset[str]:
        """Return semantic families exposed by capability report."""
        report = self._capability_report
        if report is None:
            return frozenset()
        return frozenset(str(name).casefold() for name in report.feature_endpoints)

    def _apply_capability_report(self, report: CapabilityReport) -> None:
        """Store report and flatten it to stable semantic capability names."""
        self._capability_report = report
        wan_counter_failure = report.failures.get("wan_counters", "")
        self._wan_counter_probe_pending = (
            not report.wan_counters
            and wan_counter_failure.startswith("SpeedportSessionBusyError:")
        )
        capabilities = {str(name).casefold() for name in report.feature_endpoints}
        capabilities.update(
            _FAMILY_ROUTES[family][0] for family in capabilities & _FAMILY_ROUTES.keys()
        )
        if report.status_json:
            capabilities.update({"status", "system", "diagnostics"})
        if report.tr064:
            capabilities.add("tr064")
        if report.wan_counters or self._wan_counter_probe_pending:
            capabilities.update({"wan_counters", "wan"})
        if report.authenticated_json:
            capabilities.add("authenticated_json")
        self._capabilities = frozenset(capabilities)

    def _merge_data(self, partial: Mapping[str, Any]) -> tuple[StateTransition, ...]:
        """Deep-merge normalized data and collect meaningful state transitions."""
        system = partial.get("system")
        if isinstance(system, Mapping):
            write_blocked = system.get("settings_write_blocked", _MISSING)
            if isinstance(write_blocked, bool):
                self._settings_write_blocked_latch = write_blocked
        previous_values = dict(self._transition_values)
        self._mutable_data = _deep_merge_dicts(self._mutable_data, _thaw(partial))
        self._data = cast("Mapping[str, Any]", _freeze(self._mutable_data))
        current_values = dict(_iter_transition_values(self._data))
        occurred_at = datetime.now(UTC)
        transitions = tuple(
            StateTransition(path, previous_values[path], current, occurred_at)
            for path, current in current_values.items()
            if path in previous_values and previous_values[path] != current
        )
        self._transition_values = current_values
        return transitions


def _normalise_router_info(info: RouterInfo | None) -> dict[str, Any]:
    """Normalize protocol router information."""
    return {
        "model": _model_value(info, "model"),
        "firmware": _model_value(info, "firmware"),
        "serial_number": _model_value(info, "serial_number"),
        "hardware_version": _model_value(info, "hardware_version"),
    }


def _normalise_status(status: RouterStatus) -> dict[str, Any]:
    """Normalize core status model into stable platform-facing paths."""
    normalized, _ = normalize_status_payload(status)
    return normalized


def _utilization(rate: float | None, capacity: Any) -> float | None:
    """Calculate clamped utilization ratio."""
    if rate is None or not isinstance(capacity, (int, float)) or capacity <= 0:
        return None
    return min(max(rate / capacity * 100, 0.0), 100.0)


def _connection_state(value: Any) -> bool | str | None:
    """Normalize equivalent router connection-state spellings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "connected", "online", "up"}:
        return True
    if normalized in {"0", "disconnected", "down", "offline"}:
        return False
    return str(value).strip() or None


def _model_value(model: Any, name: str) -> Any:
    """Read typed model field safely."""
    return getattr(model, name, None) if model is not None else None


def _string_or_none(value: Any) -> str | None:
    """Normalize optional string."""
    if value is None:
        return None
    value_string = str(value).strip()
    return value_string or None


def _clean_identifier(value: Any) -> str | None:
    """Normalize router identifier without changing its stable value."""
    value_string = _string_or_none(value)
    if value_string is None:
        return None
    return "".join(
        character
        for character in value_string
        if character.isalnum() or character in "-_"
    )


def _deep_merge_dicts(
    base: Mapping[str, Any], update: Mapping[str, Any]
) -> dict[str, Any]:
    """Deep merge mappings while replacing non-mapping leaves."""
    merged = {str(key): _thaw(value) for key, value in base.items()}
    for key, value in update.items():
        normalized_key = str(key)
        existing = merged.get(normalized_key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[normalized_key] = _deep_merge_dicts(existing, value)
        else:
            merged[normalized_key] = _thaw(value)
    return merged


def _null_values(value: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve discovered paths while making their stale values unavailable."""
    return {
        str(key): _null_values(item) if isinstance(item, Mapping) else None
        for key, item in value.items()
    }


def _removed_values(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Null only previously observed fields omitted by a successful refresh."""
    removed: dict[str, Any] = {}
    for key, previous_value in previous.items():
        if key not in current:
            removed[str(key)] = (
                _null_values(previous_value)
                if isinstance(previous_value, Mapping)
                else None
            )
            continue
        current_value = current[key]
        if isinstance(previous_value, Mapping) and isinstance(current_value, Mapping):
            nested = _removed_values(previous_value, current_value)
            if nested:
                removed[str(key)] = nested
    return removed


def _restore_values_at_paths(
    cleared: Mapping[str, Any], fallback: Mapping[str, Any]
) -> dict[str, Any]:
    """Restore fallback values only where a source would otherwise clear them."""
    restored = {str(key): _thaw(value) for key, value in cleared.items()}
    for key, cleared_value in cleared.items():
        if key not in fallback:
            continue
        fallback_value = fallback[key]
        if isinstance(cleared_value, Mapping) and isinstance(fallback_value, Mapping):
            restored[str(key)] = _restore_values_at_paths(
                cleared_value,
                fallback_value,
            )
        else:
            restored[str(key)] = _thaw(fallback_value)
    return restored


def _freeze(value: Any) -> Any:
    """Recursively freeze normalized runtime data."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return _freeze(asdict(value))
    return value


def _thaw(value: Any) -> Any:
    """Convert models and immutable structures to plain diagnostics-safe data."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _thaw(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_thaw(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _iter_transition_values(
    value: Any, prefix: tuple[str, ...] = ()
) -> Iterable[tuple[str, Any]]:
    """Yield state-like scalar values used for transition events."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() == "raw":
                continue
            yield from _iter_transition_values(item, (*prefix, str(key)))
        return
    if isinstance(value, tuple):
        return
    if prefix and prefix[-1].casefold() in _TRANSITION_KEYS:
        yield ".".join(prefix), value
