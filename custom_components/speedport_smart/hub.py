"""Runtime owner for a Speedport Smart router."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast

from homeassistant.core import HassJob
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .admin_actions import (
    ADMIN_ACTION_CONTRACTS,
    AdminActionContract,
    AdminActionDecision,
    get_admin_action_contract,
    valid_target_id,
)
from .api import (
    SpeedportAuthenticationError,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportMutationOutcomeUnknownError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from .const import DOMAIN, RATE_WINDOW_SECONDS
from .coordinator import GroupSnapshot, PollGroup, SpeedportDataUpdateCoordinator
from .diagnostics import safe_error_class_name
from .management import (
    ManagementCommandDecision,
    ManagementConfirmation,
    ManagementExecutionSurface,
    ManagementVerificationPolicy,
    ManagementVerificationStrategy,
    get_command_write_contract,
)
from .normalizers import normalize_feature_payload, normalize_status_payload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

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
        "receiver_led",
        "mesh_topology",
        "wifi",
        "clients",
        "telephony",
        "calls",
        "active_calls",
        "dect_status",
        "ip",
        "wps",
        "wps_status",
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
_ADMIN_QUERY_GLOBAL_INTERVAL_SECONDS: Final = 1.0
_ADMIN_ACTION_REQUESTER_ID_MAX_LENGTH: Final = 128
_ADMIN_ACTION_REQUESTER_PARTS: Final = 2
_ADMIN_QUERY_INTERVAL_SECONDS: Final = MappingProxyType(
    {
        "dect_handset_targets": 1.0,
        "dect_handset_disconnect_targets": 1.0,
        "dect_repeater_disconnect_targets": 1.0,
        "voip_provider_delete_targets": 1.0,
        "voip_line_delete_targets": 1.0,
        "ip_pbx_client_delete_targets": 1.0,
        "phonebook_entry_delete_targets": 1.0,
        "nas_share_delete_targets": 1.0,
        "ip_pbx_refresh": 5.0,
        "phonebook_search": 1.0,
        "phonebook_contact": 1.0,
        "voip_line_targets": 1.0,
    }
)
_ADMIN_QUERY_CAPABILITY_PROOFS: Final = MappingProxyType(
    {
        "ip_pbx_refresh": ("pbx_clients", "data/IPClients.json"),
        "phonebook_search": ("phonebook", "data/PhoneBook.json"),
        "phonebook_contact": ("phonebook", "data/PhoneBook.json"),
    }
)
_ADMIN_ACTION_GLOBAL_INTERVAL_SECONDS: Final = 1.0
_ADMIN_ACTION_TARGET_FINGERPRINT_LENGTH: Final = 64
_ADMIN_ACTION_TARGET_LABEL_MAX_LENGTH: Final = 64
_ADMIN_ACTION_NUMBER_SUFFIX_LENGTH: Final = 4
_ADMIN_ACTION_TARGET_MAX_ROWS: Final = 32
_ADMIN_ACTION_TOKEN_GENERATION_ATTEMPTS: Final = 4
_ADMIN_ACTION_INTERVAL_SECONDS: Final = MappingProxyType(
    {
        "dect_handset_enroll": 30.0,
        "dect_repeater_enroll": 30.0,
        "dect_handset_set_paging": 2.0,
        "voip_line_set_active": 2.0,
        "dect_handset_disconnect": 30.0,
        "dect_repeater_disconnect": 30.0,
        "voip_provider_delete": 30.0,
        "voip_line_delete": 30.0,
        "ip_pbx_client_delete": 30.0,
        "phonebook_entry_delete": 30.0,
        "nas_share_delete": 30.0,
    }
)
_ADMIN_ACTION_REFRESH_FAMILIES: Final = MappingProxyType(
    {
        "dect_handset_enroll": ("dect_status", "dect"),
        "dect_repeater_enroll": ("dect_status", "dect_repeater"),
        "dect_handset_set_paging": ("dect", "dect_status"),
        "voip_line_set_active": ("voip_lines",),
        "dect_handset_disconnect": ("dect", "dect_status"),
        "dect_repeater_disconnect": ("dect_repeater",),
        "voip_provider_delete": ("voip_providers", "voip_lines"),
        "voip_line_delete": ("voip_lines",),
        "ip_pbx_client_delete": ("pbx_clients",),
        "phonebook_entry_delete": ("phonebook",),
        "nas_share_delete": ("nas_folders",),
    }
)
# Only canonical roots emitted by reviewed normalizers may become read capabilities.
# Endpoint-family names are deliberately not mapped ahead of a successful read.
_NORMALIZED_READ_CAPABILITY_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "clients",
        "ddns",
        "dect",
        "dhcp",
        "diagnostics",
        "dsl",
        "hybrid",
        "internet",
        "lan",
        "mesh",
        "mobile",
        "nat",
        "parental",
        "pbx",
        "powerline",
        "qos",
        "receiver",
        "security",
        "smarthome",
        "system",
        "telephony",
        "usb",
        "vpn",
        "wifi",
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


def _same_exact_value(current: object, expected: object) -> bool:
    """Compare normalized command state without bool/int type widening."""
    return type(current) is type(expected) and current == expected


def _mapping_has_path(data: Mapping[str, Any], path: str) -> bool:
    """Return whether normalized family data owns one dotted path."""
    current: object = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _retryable_verification_error(error: SpeedportError) -> bool:
    """Return whether another read-only verification attempt is safe."""
    if isinstance(
        error,
        (
            SpeedportAuthenticationError,
            SpeedportCommandRejectedError,
            SpeedportDecodeError,
            SpeedportSessionBusyError,
            SpeedportUnsupportedError,
        ),
    ):
        return False
    return isinstance(error, (SpeedportConnectionError, SpeedportProtocolError))


async def _capture_admin_boundary[T](
    awaitable: Awaitable[T],
) -> T | BaseException:
    """Capture an unexpected local failure without leaking its details."""
    outcome = (await asyncio.gather(awaitable, return_exceptions=True))[0]
    if isinstance(outcome, asyncio.CancelledError):
        raise outcome
    return outcome


class _ContractVerificationSentinel:
    """Marker for callers that leave verification entirely to the contract."""


_CONTRACT_VERIFICATION = _ContractVerificationSentinel()


class AdminQueryRateLimitError(HomeAssistantError):
    """Raised when an administrator private query exceeds its bounded cadence."""

    def __init__(self, retry_after: float) -> None:
        """Retain only a bounded retry delay, never query values."""
        super().__init__("Administrator router query rate limit exceeded")
        self.retry_after = max(retry_after, 0.0)


class AdminActionRateLimitError(HomeAssistantError):
    """Raised before I/O when an administrator action exceeds its cadence."""

    def __init__(self, retry_after: float) -> None:
        """Retain only a bounded retry delay, never action parameters."""
        super().__init__("Administrator router action rate limit exceeded")
        self.retry_after = max(retry_after, 0.0)


class AdminActionUnavailableError(HomeAssistantError):
    """Raised when an administrator action lacks an exact execution proof."""


class AdminActionConfirmationError(HomeAssistantError):
    """Raised when server-side action confirmation is absent."""


class AdminActionBusyError(HomeAssistantError):
    """Raised when an enrollment lifecycle is already active."""


class AdminActionOutcomeUnknownError(HomeAssistantError):
    """Raised after one mutation attempt whose acceptance was not proven."""


class AdminActionVerificationError(HomeAssistantError):
    """Raised when independent readback does not prove the requested state."""


class AdminActionRejectedError(HomeAssistantError):
    """Raised when the router explicitly rejects a sent administrator action."""


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


@dataclass(frozen=True, slots=True)
class _AdminActionTargetGrant:
    """One short-lived in-memory binding from UI token to firmware row."""

    action: str
    target_id: str
    target_fingerprint: str
    target_context: Mapping[str, str | int | bool]
    requester: tuple[str, str]
    management_generation: int
    expires_at: float


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
        self._poll_group_succeeded: dict[PollGroup, bool | None] = dict.fromkeys(
            PollGroup
        )
        self._poll_group_last_success: dict[PollGroup, datetime | None] = dict.fromkeys(
            PollGroup
        )
        self._poll_group_last_error: dict[PollGroup, str | None] = dict.fromkeys(
            PollGroup
        )
        self._generation = 0
        self._operation_lock = asyncio.Lock()
        self._admin_query_global_next_at = 0.0
        self._admin_query_next_at: dict[str, float] = {}
        self._admin_action_global_next_at = 0.0
        self._admin_action_next_at: dict[str, float] = {}
        self._admin_action_target_grants: dict[str, _AdminActionTargetGrant] = {}
        self._admin_action_grant_expiry_cancel: Callable[[], None] | None = None
        self._management_generation = 0
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
        self._candidate_inventory_status = "not_run"
        self._candidate_inventory_counts = {
            "attempted": 0,
            "succeeded": 0,
            "unsupported": 0,
            "failed": 0,
            "observed": 0,
            "excluded": 0,
        }
        self._candidate_inventory_last_attempt: datetime | None = None
        self._candidate_inventory_last_completed: datetime | None = None
        self._candidate_inventory_last_error: str | None = None
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

    def poll_group_health(self, group: PollGroup) -> Mapping[str, Any]:
        """Return actual poll outcome without cross-group publication artifacts."""
        succeeded = self._poll_group_succeeded[group]
        last_success = self._poll_group_last_success[group]
        return MappingProxyType(
            {
                "state": (
                    "initializing"
                    if succeeded is None
                    else "healthy"
                    if succeeded
                    else "failed"
                ),
                "last_successful_update": (
                    last_success.isoformat() if last_success is not None else None
                ),
                "last_error_class": self._poll_group_last_error[group],
            }
        )

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
            self._poll_group_succeeded[group] is True for group in self._coordinators
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
        self._cancel_admin_action_grant_expiry()
        self._admin_action_target_grants.clear()
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

    async def async_capture_candidate_inventory(self) -> None:
        """Capture every readable candidate schema through one explicit session."""
        async with self._operation_lock:
            self._candidate_inventory_status = "running"
            self._candidate_inventory_last_attempt = datetime.now(UTC)
            self._candidate_inventory_last_error = None
            self._set_management_access("recovering", owner=self._management_owner)
            try:
                result = await self.client.capture_candidate_inventory()
            except SpeedportSessionBusyError as err:
                self._record_candidate_inventory_failure(err)
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Log out in the Speedport web interface before capturing the "
                    "read-only capability inventory"
                ) from err
            except SpeedportLoginLockedError as err:
                self._record_candidate_inventory_failure(err)
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Speedport login is temporarily locked; retry after the cooldown"
                ) from err
            except SpeedportInvalidCredentialsError as err:
                self._record_candidate_inventory_failure(err)
                self._publish_authenticated_failure(err)
                raise HomeAssistantError(
                    "Speedport rejected the configured device password"
                ) from err
            except SpeedportError as err:
                self._record_candidate_inventory_failure(err)
                self._publish_authenticated_failure(err, force_unavailable=True)
                raise HomeAssistantError(
                    "The read-only Speedport capability inventory could not be captured"
                ) from err

            self._set_management_access("available")
            self._candidate_inventory_status = (
                "partial" if result.failed else "complete"
            )
            self._candidate_inventory_counts = {
                "attempted": result.attempted,
                "succeeded": result.succeeded,
                "unsupported": result.unsupported,
                "failed": result.failed,
                "observed": result.observed,
                "excluded": result.excluded,
            }
            self._candidate_inventory_last_completed = datetime.now(UTC)

    async def async_query_ip_pbx_client(self, *, client_id: str) -> dict[str, Any]:
        """Return one ephemeral IP-PBX status refresh through the session owner."""
        return await self._async_admin_query(
            "ip_pbx_refresh",
            lambda: self.client.query_ip_pbx_client(client_id=client_id),
        )

    async def async_query_phonebook_entries(
        self,
        *,
        phonebook_id: int,
        prefix: str,
    ) -> dict[str, Any]:
        """Return one ephemeral, bounded phonebook search through the owner."""
        return await self._async_admin_query(
            "phonebook_search",
            lambda: self.client.query_phonebook_entries(
                phonebook_id=phonebook_id,
                prefix=prefix,
            ),
        )

    async def async_query_phonebook_contact(
        self,
        *,
        phonebook_id: int,
        contact_id: str,
    ) -> dict[str, Any]:
        """Return one ephemeral, bounded contact detail through the owner."""
        return await self._async_admin_query(
            "phonebook_contact",
            lambda: self.client.query_phonebook_contact(
                phonebook_id=phonebook_id,
                contact_id=contact_id,
            ),
        )

    def admin_action_decision(self, action: str) -> AdminActionDecision:
        """Explain one ephemeral action without broad capability inference."""
        contract = get_admin_action_contract(action)
        identity = self.router_identity
        handlers_available = bool(
            contract is not None
            and all(
                callable(getattr(self.client, name, None))
                for name in (
                    contract.handler,
                    contract.preflight_handler,
                    contract.verification_handler,
                )
            )
        )
        return AdminActionDecision(
            configured=self.controls_enabled,
            firmware_supported=bool(
                contract is not None
                and contract.supports(identity.model, identity.firmware)
            ),
            capability_supported=bool(
                contract is not None
                and self.has_capability("authenticated_json")
                and contract.proofs_satisfied(self._capability_report)
            ),
            handlers_available=handlers_available,
            session_available=self.management_controls_available,
        )

    def admin_actions_metadata(self) -> list[dict[str, Any]]:
        """Return bounded value-free action support metadata for the panel."""
        metadata: list[dict[str, Any]] = []
        for action, contract in ADMIN_ACTION_CONTRACTS.items():
            decision = self.admin_action_decision(action)
            metadata.append(
                {
                    "id": action,
                    "feature_id": contract.feature_id,
                    "supported": decision.supported,
                    "available": decision.available,
                    "unavailable_reason": decision.unavailable_reason,
                    "risk": contract.risk.value,
                    "confirmation": contract.confirmation.value,
                    "typed_confirmation": contract.typed_confirmation,
                    "target_query": contract.target_query,
                    "target_token_ttl_seconds": (contract.target_token_ttl_seconds),
                    "prerequisite": contract.prerequisite,
                    "prerequisite_confirmation_required": (
                        contract.prerequisite is not None
                    ),
                }
            )
        return metadata

    async def async_query_dect_handset_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return exact handset action IDs only through an ephemeral response."""
        contract = get_admin_action_contract("dect_handset_set_paging")
        return await self._async_admin_action_target_query(
            contract,
            "dect_handset_targets",
            self.client.query_dect_handset_targets,
            requester=requester,
        )

    async def async_query_voip_line_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return exact VoIP action IDs only through an ephemeral response."""
        contract = get_admin_action_contract("voip_line_set_active")
        return await self._async_admin_action_target_query(
            contract,
            "voip_line_targets",
            self.client.query_voip_line_targets,
            requester=requester,
        )

    async def async_query_dect_handset_disconnect_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound DECT handset deletion targets."""
        return await self._query_destructive_targets(
            "dect_handset_disconnect",
            self.client.query_dect_handset_disconnect_targets,
            requester=requester,
        )

    async def async_query_dect_repeater_disconnect_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound DECT repeater deletion targets."""
        return await self._query_destructive_targets(
            "dect_repeater_disconnect",
            self.client.query_dect_repeater_disconnect_targets,
            requester=requester,
        )

    async def async_query_voip_provider_delete_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound VoIP provider deletion targets."""
        return await self._query_destructive_targets(
            "voip_provider_delete",
            self.client.query_voip_provider_delete_targets,
            requester=requester,
        )

    async def async_query_voip_line_delete_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound VoIP number deletion targets."""
        return await self._query_destructive_targets(
            "voip_line_delete",
            self.client.query_voip_line_delete_targets,
            requester=requester,
        )

    async def async_query_ip_pbx_client_delete_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound IP-PBX client deletion targets."""
        return await self._query_destructive_targets(
            "ip_pbx_client_delete",
            self.client.query_ip_pbx_client_delete_targets,
            requester=requester,
        )

    async def async_query_phonebook_entry_delete_targets(
        self,
        *,
        phonebook_id: int,
        requester: tuple[str, str],
    ) -> dict[str, Any]:
        """Return action-bound contact deletion targets for one phonebook."""
        return await self._query_destructive_targets(
            "phonebook_entry_delete",
            lambda: self.client.query_phonebook_entry_delete_targets(
                phonebook_id=phonebook_id,
            ),
            requester=requester,
        )

    async def async_query_nas_share_delete_targets(
        self, *, requester: tuple[str, str]
    ) -> dict[str, Any]:
        """Return action-bound NAS-share deletion targets."""
        return await self._query_destructive_targets(
            "nas_share_delete",
            self.client.query_nas_share_delete_targets,
            requester=requester,
        )

    async def _query_destructive_targets(
        self,
        action: str,
        query: Callable[[], Awaitable[dict[str, Any]]],
        *,
        requester: tuple[str, str],
    ) -> dict[str, Any]:
        """Run one destructive action's private exact target query."""
        contract = get_admin_action_contract(action)
        return await self._async_admin_action_target_query(
            contract,
            f"{action}_targets",
            query,
            requester=requester,
        )

    async def _async_admin_action_target_query(
        self,
        contract: AdminActionContract | None,
        query_kind: str,
        query: Callable[[], Awaitable[dict[str, Any]]],
        *,
        requester: tuple[str, str],
    ) -> dict[str, Any]:
        """Run one action-target query without retaining its private result."""
        if (
            contract is None
            or not self.admin_action_decision(contract.action).supported
        ):
            raise AdminActionUnavailableError(
                "Administrator action targets are unavailable"
            )
        issued: dict[str, Any] | None = None
        async with self._operation_lock:
            if not self.admin_action_decision(contract.action).available:
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            now = self._monotonic_time()
            next_allowed = max(
                self._admin_query_global_next_at,
                self._admin_query_next_at.get(query_kind, 0.0),
            )
            if now < next_allowed:
                raise AdminQueryRateLimitError(next_allowed - now)
            self._admin_query_global_next_at = (
                now + _ADMIN_QUERY_GLOBAL_INTERVAL_SECONDS
            )
            self._admin_query_next_at[query_kind] = (
                now + _ADMIN_QUERY_INTERVAL_SECONDS[query_kind]
            )
            cleanup_succeeded = False
            try:
                outcome = await _capture_admin_boundary(query())
                if isinstance(outcome, SpeedportError):
                    self._publish_authenticated_failure(outcome)
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    ) from None
                if isinstance(outcome, BaseException):
                    self._publish_authenticated_failure(
                        SpeedportProtocolError(
                            "Administrator action target query failed locally"
                        ),
                        force_unavailable=True,
                    )
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    ) from None
                if not isinstance(outcome, dict):
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    )
                issued = self._issue_admin_action_targets(
                    contract,
                    outcome,
                    requester=requester,
                )
            finally:
                cleanup_succeeded = await self._async_cleanup_admin_session()
            if (
                not cleanup_succeeded
                or issued is None
                or any(
                    self._admin_action_target_grants.get(target.get("target_token"))
                    is None
                    for target in issued["targets"]
                )
            ):
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            return issued

    async def async_execute_admin_action(
        self,
        action: str,
        *,
        confirmed: bool,
        confirmation_text: str | None = None,
        requester: tuple[str, str] | None = None,
        **parameters: Any,
    ) -> dict[str, Any]:
        """Execute one confirmed action without publishing private runtime state."""
        contract = get_admin_action_contract(action)
        if contract is None:
            raise AdminActionUnavailableError("Administrator action is unavailable")
        if type(confirmed) is not bool or not confirmed:
            raise AdminActionConfirmationError(
                "Administrator action confirmation is required"
            )
        if contract.confirmation is ManagementConfirmation.TYPED and (
            not isinstance(confirmation_text, str)
            or confirmation_text != contract.typed_confirmation
        ):
            raise AdminActionConfirmationError(
                "Administrator typed confirmation does not match the action"
            )
        if contract.confirmation is ManagementConfirmation.CONFIRM and (
            confirmation_text is not None
        ):
            raise AdminActionConfirmationError(
                "Administrator confirmation does not match the action policy"
            )
        if not contract.accepts_parameters(parameters):
            raise AdminActionUnavailableError("Administrator action is unavailable")
        if contract.prerequisite == "dect_repeater_requirements" and any(
            parameters.get(name) is not True
            for name in (
                "pin_is_default",
                "full_power_enabled",
                "full_eco_disabled",
            )
        ):
            raise AdminActionConfirmationError(
                "Administrator action prerequisite confirmation is required"
            )
        if not self.admin_action_decision(action).supported:
            raise AdminActionUnavailableError("Administrator action is unavailable")

        async with self._operation_lock:
            if not self.admin_action_decision(action).available:
                raise AdminActionUnavailableError("Administrator action is unavailable")
            now = self._monotonic_time()
            interval = _ADMIN_ACTION_INTERVAL_SECONDS[action]
            next_allowed = max(
                self._admin_action_global_next_at,
                self._admin_action_next_at.get(action, 0.0),
            )
            if now < next_allowed:
                raise AdminActionRateLimitError(next_allowed - now)
            resolved_parameters = self._resolve_admin_action_target(
                contract,
                parameters,
                now=now,
                requester=requester,
            )
            self._admin_action_global_next_at = (
                now + _ADMIN_ACTION_GLOBAL_INTERVAL_SECONDS
            )
            self._admin_action_next_at[action] = now + interval
            try:
                try:
                    result = await self._async_execute_admin_action_locked(
                        contract,
                        resolved_parameters,
                    )
                finally:
                    await self._async_refresh_admin_action_state_locked(contract)
                return result
            finally:
                await self._async_cleanup_admin_session()

    async def _async_execute_admin_action_locked(
        self,
        contract: AdminActionContract,
        parameters: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Perform one preflight, at most one mutation, and bounded readbacks."""
        preflight = getattr(self.client, contract.preflight_handler)
        mutation = getattr(self.client, contract.handler)
        verification = getattr(self.client, contract.verification_handler)
        expected = contract.expected(parameters)

        preflight_outcome = await _capture_admin_boundary(
            preflight(
                **_admin_action_arguments(parameters, contract.preflight_parameters)
            )
        )
        if isinstance(preflight_outcome, SpeedportError):
            self._publish_authenticated_failure(preflight_outcome)
            raise AdminActionUnavailableError(
                "Administrator action preflight could not be completed"
            ) from None
        if isinstance(preflight_outcome, BaseException):
            self._publish_authenticated_failure(
                SpeedportProtocolError("Administrator action preflight failed locally"),
                force_unavailable=True,
            )
            raise AdminActionUnavailableError(
                "Administrator action preflight could not be completed"
            ) from None
        current = preflight_outcome
        if type(current) is not bool:
            raise AdminActionUnavailableError(
                "Administrator action preflight could not be completed"
            )
        if current is expected:
            if contract.already_expected_is_error:
                raise AdminActionBusyError(
                    "A DECT enrollment lifecycle is already active"
                )
            return _admin_action_success_result(
                contract,
                status="unchanged",
                expected=expected,
            )

        mutation_outcome = await _capture_admin_boundary(
            mutation(
                **_admin_action_arguments(parameters, contract.mutation_parameters)
            )
        )
        if isinstance(mutation_outcome, SpeedportCommandRejectedError):
            raise AdminActionRejectedError(
                "Router explicitly rejected the administrator action"
            ) from None
        mutation_uncertain: SpeedportError | None = None
        mutation_force_unavailable = False
        if isinstance(mutation_outcome, SpeedportMutationOutcomeUnknownError):
            mutation_uncertain = mutation_outcome
        elif isinstance(mutation_outcome, SpeedportError):
            self._publish_authenticated_failure(mutation_outcome)
            raise AdminActionUnavailableError(
                "Administrator action could not be sent"
            ) from None
        elif isinstance(mutation_outcome, BaseException):
            mutation_uncertain = SpeedportProtocolError(
                "Administrator action failed locally"
            )
            mutation_force_unavailable = True

        readback_error: SpeedportError | None = None
        for delay in contract.readback_delays:
            if delay:
                await asyncio.sleep(delay)
            verification_outcome = await _capture_admin_boundary(
                verification(
                    **_admin_action_arguments(
                        parameters,
                        contract.verification_parameters,
                    )
                )
            )
            if isinstance(verification_outcome, SpeedportError):
                if not _retryable_verification_error(verification_outcome):
                    self._publish_authenticated_failure(verification_outcome)
                    if mutation_uncertain is not None:
                        self._publish_authenticated_failure(
                            mutation_uncertain,
                            force_unavailable=mutation_force_unavailable,
                        )
                        raise AdminActionOutcomeUnknownError(
                            "Router action outcome is unknown; inspect state before "
                            "retrying"
                        ) from None
                    raise AdminActionVerificationError(
                        "Router action result could not be independently verified"
                    ) from None
                readback_error = verification_outcome
                continue
            if isinstance(verification_outcome, BaseException):
                self._publish_authenticated_failure(
                    SpeedportProtocolError(
                        "Administrator action verification failed locally"
                    ),
                    force_unavailable=True,
                )
                if mutation_uncertain is not None:
                    raise AdminActionOutcomeUnknownError(
                        "Router action outcome is unknown; inspect state before "
                        "retrying"
                    ) from None
                raise AdminActionVerificationError(
                    "Router action result could not be independently verified"
                ) from None
            current = verification_outcome
            if type(current) is bool and current is expected:
                if mutation_uncertain is not None:
                    raise AdminActionOutcomeUnknownError(
                        "Router action acknowledgement is unknown; inspect state "
                        "before retrying"
                    ) from None
                return _admin_action_success_result(
                    contract,
                    status="verified",
                    expected=expected,
                )

        if readback_error is not None:
            self._publish_authenticated_failure(readback_error)
        if mutation_uncertain is not None:
            self._publish_authenticated_failure(
                mutation_uncertain,
                force_unavailable=mutation_force_unavailable,
            )
            raise AdminActionOutcomeUnknownError(
                "Router action outcome is unknown; inspect state before retrying"
            ) from None
        raise AdminActionVerificationError(
            "Router action result could not be independently verified"
        )

    async def _async_refresh_admin_action_state_locked(
        self,
        contract: AdminActionContract,
    ) -> None:
        """Refresh or invalidate every cached family affected by an action."""
        partial: dict[str, Any] = {}
        for family in _ADMIN_ACTION_REFRESH_FAMILIES[contract.action]:
            outcome = await _capture_admin_boundary(
                self._async_fetch_families(
                    (family,),
                    propagate_errors=True,
                    release_authenticated_session=False,
                    update_management_access=False,
                )
            )
            if isinstance(outcome, SpeedportUnsupportedError):
                self._endpoint_errors[family] = safe_error_class_name(outcome)
                partial = _deep_merge_dicts(
                    partial,
                    self._unavailable_family_data(family),
                )
                continue
            if isinstance(outcome, SpeedportError):
                self._publish_authenticated_failure(outcome)
                partial = self._invalidate_authenticated_families(
                    partial,
                    error_name=safe_error_class_name(outcome),
                )
                break
            if isinstance(outcome, BaseException):
                error = SpeedportProtocolError(
                    "Administrator action cache refresh failed locally"
                )
                self._publish_authenticated_failure(error, force_unavailable=True)
                partial = self._invalidate_authenticated_families(
                    partial,
                    error_name=safe_error_class_name(error),
                )
                break
            partial = _deep_merge_dicts(partial, outcome)

        if not partial:
            return
        now = datetime.now(UTC)
        transitions = self._merge_data(partial)
        self._generation += 1
        self._last_transitions = transitions
        self._protected_invalidation_pending = False
        for group, coordinator in self._coordinators.items():
            coordinator.async_set_updated_data(
                GroupSnapshot(
                    group=group,
                    data=self._data,
                    generation=self._generation,
                    updated_at=now,
                    transitions=transitions,
                )
            )

    async def _async_cleanup_admin_session(self) -> bool:
        """Release an ephemeral session and report only bounded success."""
        cleanup = getattr(self.client, "logout_ephemeral", self.client.logout)
        outcome = await _capture_admin_boundary(cleanup())
        if isinstance(outcome, SpeedportError):
            self._publish_authenticated_failure(outcome, force_unavailable=True)
            return False
        if isinstance(outcome, BaseException):
            self._publish_authenticated_failure(
                SpeedportProtocolError("Router session cleanup failed"),
                force_unavailable=True,
            )
            return False
        return True

    def _issue_admin_action_targets(
        self,
        contract: AdminActionContract,
        result: Mapping[str, Any],
        *,
        requester: tuple[str, str],
    ) -> dict[str, Any]:
        """Replace one action's grants and return only safe ephemeral targets."""
        raw_targets = result.get("targets")
        truncated = result.get("truncated")
        if (
            not isinstance(raw_targets, list)
            or len(raw_targets) > _ADMIN_ACTION_TARGET_MAX_ROWS
            or type(truncated) is not bool
        ):
            raise AdminActionUnavailableError(
                "Administrator action targets are unavailable"
            )
        requester = _require_admin_action_requester(requester)
        now = self._monotonic_time()
        token_ttl = contract.target_token_ttl_seconds
        if token_ttl is None:
            raise AdminActionUnavailableError(
                "Administrator action targets are unavailable"
            )
        retained_grants = {
            token: grant
            for token, grant in self._admin_action_target_grants.items()
            if (
                grant.expires_at > now
                and (grant.action != contract.action or grant.requester != requester)
            )
        }
        new_grants: dict[str, _AdminActionTargetGrant] = {}
        targets: list[dict[str, Any]] = []
        projected_identities: list[tuple[tuple[str, str | int | bool], ...]] = []
        seen_targets: set[tuple[str, tuple[tuple[str, str | int | bool], ...]]] = set()
        allowed_target_fields = {
            "target_id",
            "target_fingerprint",
            *contract.target_context_specs,
            *contract.target_projection_specs,
        }
        for raw_target in raw_targets:
            if not isinstance(raw_target, Mapping) or not set(raw_target) <= (
                allowed_target_fields
            ):
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            target_id = raw_target.get("target_id")
            fingerprint = raw_target.get("target_fingerprint")
            if (
                not valid_target_id(target_id)
                or not isinstance(fingerprint, str)
                or len(fingerprint) != _ADMIN_ACTION_TARGET_FINGERPRINT_LENGTH
                or any(character not in "0123456789abcdef" for character in fingerprint)
            ):
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            target_context: dict[str, str | int | bool] = {}
            for field, specification in contract.target_context_specs.items():
                value = raw_target.get(field, _MISSING)
                if value is _MISSING or not specification.accepts(value):
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    )
                if not isinstance(value, (str, int, bool)):
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    )
                target_context[field] = value
            target_identity = (target_id, tuple(target_context.items()))
            if target_identity in seen_targets:
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            seen_targets.add(target_identity)

            projected_values: dict[str, Any] = {}
            for field, specification in contract.target_projection_specs.items():
                value = raw_target.get(field, _MISSING)
                if value is _MISSING or value is None:
                    if specification.allow_none:
                        continue
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    )
                if not specification.accepts(value) or (
                    isinstance(value, str)
                    and (
                        not value.isprintable()
                        or (
                            field == "number_suffix"
                            and (not value.isascii() or not value.isdigit())
                        )
                    )
                ):
                    raise AdminActionUnavailableError(
                        "Administrator action targets are unavailable"
                    )
                projected_values[field] = value
            projected_identities.append(tuple(projected_values.items()))
            token: str | None = None
            for _attempt in range(_ADMIN_ACTION_TOKEN_GENERATION_ATTEMPTS):
                candidate = secrets.token_hex(16)
                if candidate not in retained_grants and candidate not in new_grants:
                    token = candidate
                    break
            if token is None:
                raise AdminActionUnavailableError(
                    "Administrator action targets are unavailable"
                )
            new_grants[token] = _AdminActionTargetGrant(
                action=contract.action,
                target_id=target_id,
                target_fingerprint=fingerprint,
                target_context=MappingProxyType(target_context),
                requester=requester,
                management_generation=self._management_generation,
                expires_at=now + token_ttl,
            )
            targets.append({"target_token": token, **projected_values})
        if len(set(projected_identities)) != len(projected_identities):
            raise AdminActionUnavailableError(
                "Administrator action targets are not uniquely identifiable"
            )
        self._admin_action_target_grants = {**retained_grants, **new_grants}
        self._schedule_admin_action_grant_expiry()
        return {"targets": targets, "truncated": truncated}

    def _resolve_admin_action_target(
        self,
        contract: AdminActionContract,
        parameters: Mapping[str, Any],
        *,
        now: float,
        requester: tuple[str, str] | None,
    ) -> dict[str, Any]:
        """Consume one valid token and restore only internal handler arguments."""
        self._purge_expired_admin_action_grants(now=now)
        resolved = dict(parameters)
        if contract.target_query is None:
            return resolved
        requester = _require_admin_action_requester(requester)
        token = resolved.pop("target_token", None)
        grant = (
            self._admin_action_target_grants.get(token)
            if isinstance(token, str)
            else None
        )
        if (
            grant is None
            or grant.action != contract.action
            or grant.requester != requester
            or grant.management_generation != self._management_generation
            or grant.expires_at <= now
            or contract.target_id_parameter is None
            or contract.target_fingerprint_parameter is None
        ):
            if isinstance(token, str) and (
                grant is None or grant.requester == requester
            ):
                self._admin_action_target_grants.pop(token, None)
            raise AdminActionUnavailableError(
                "Administrator action target authorization is unavailable"
            )
        self._admin_action_target_grants.pop(token, None)
        self._schedule_admin_action_grant_expiry()
        resolved[contract.target_id_parameter] = grant.target_id
        resolved[contract.target_fingerprint_parameter] = grant.target_fingerprint
        resolved.update(grant.target_context)
        return resolved

    def _cancel_admin_action_grant_expiry(self) -> None:
        """Cancel the pending in-memory grant expiry callback."""
        cancel = self._admin_action_grant_expiry_cancel
        self._admin_action_grant_expiry_cancel = None
        if cancel is not None:
            cancel()

    def _schedule_admin_action_grant_expiry(self) -> None:
        """Erase unused target grants as soon as their shortest TTL expires."""
        self._cancel_admin_action_grant_expiry()
        if self._closed or not self._admin_action_target_grants:
            return
        now = self._monotonic_time()
        next_expiry = min(
            grant.expires_at for grant in self._admin_action_target_grants.values()
        )
        self._admin_action_grant_expiry_cancel = async_call_later(
            self.hass,
            max(next_expiry - now, 0.001),
            HassJob(
                self._purge_expired_admin_action_grants,
                "expire Speedport administrator action grants",
                cancel_on_shutdown=True,
            ),
        )

    def _purge_expired_admin_action_grants(
        self,
        _scheduled_at: datetime | None = None,
        *,
        now: float | None = None,
    ) -> None:
        """Drop expired private grants and schedule the next bounded purge."""
        self._admin_action_grant_expiry_cancel = None
        current = self._monotonic_time() if now is None else now
        self._admin_action_target_grants = {
            token: grant
            for token, grant in self._admin_action_target_grants.items()
            if grant.expires_at > current
        }
        self._schedule_admin_action_grant_expiry()

    async def _async_admin_query(
        self,
        query_kind: str,
        query: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Serialize one rate-limited private query without publishing its result."""
        interval = _ADMIN_QUERY_INTERVAL_SECONDS.get(query_kind)
        capability_proof = _ADMIN_QUERY_CAPABILITY_PROOFS.get(query_kind)
        if interval is None or capability_proof is None:
            raise HomeAssistantError("Administrator router query is unsupported")

        async with self._operation_lock:
            family, endpoint = capability_proof
            report = self._capability_report
            capability = (
                report.feature_endpoints.get(family) if report is not None else None
            )
            if (
                capability is None
                or capability.endpoint != endpoint
                or not capability.authenticated
            ):
                raise HomeAssistantError(
                    "Administrator router query is unsupported by this router"
                )
            now = self._monotonic_time()
            next_allowed = max(
                self._admin_query_global_next_at,
                self._admin_query_next_at.get(query_kind, 0.0),
            )
            if now < next_allowed:
                raise AdminQueryRateLimitError(next_allowed - now)
            if (
                self._closed
                or not self.has_capability("authenticated_json")
                or self._management_state != "available"
                or now < self._protected_retry_at
            ):
                raise HomeAssistantError(
                    "The router management session is not currently available"
                )

            self._admin_query_global_next_at = (
                now + _ADMIN_QUERY_GLOBAL_INTERVAL_SECONDS
            )
            self._admin_query_next_at[query_kind] = now + interval
            result: dict[str, Any] | None = None
            query_error: SpeedportError | None = None
            unexpected_error: Exception | None = None
            try:
                try:
                    result = await query()
                except SpeedportError as err:
                    query_error = err
                except Exception as err:  # noqa: BLE001 - private error boundary
                    unexpected_error = err
            finally:
                try:
                    await self.client.logout()
                except SpeedportError as err:
                    if query_error is None and unexpected_error is None:
                        query_error = err
                except Exception as err:  # noqa: BLE001 - private error boundary
                    if query_error is None and unexpected_error is None:
                        unexpected_error = err
            if query_error is not None:
                self._publish_authenticated_failure(query_error)
                raise HomeAssistantError(
                    "The private router query could not be completed"
                ) from query_error
            if unexpected_error is not None:
                raise HomeAssistantError(
                    "The private router query could not be completed"
                ) from unexpected_error
            if result is None:
                raise HomeAssistantError("The private router query returned no result")
            return result

    def _record_candidate_inventory_failure(self, error: SpeedportError) -> None:
        """Retain prior capture counts while recording a safe failed attempt."""
        self._candidate_inventory_status = "failed"
        self._candidate_inventory_last_error = safe_error_class_name(error)

    def has_capability(self, capability: str) -> bool:
        """Return whether router exposes capability."""
        return capability.casefold() in self._capabilities

    def supports_command(self, command: str) -> bool:
        """Return whether a native entity may expose an implemented command."""
        return self.command_decision(command).exposed

    def command_decision(self, command: str) -> ManagementCommandDecision:
        """Explain command support without collapsing independent safety gates."""
        contract = get_command_write_contract(command)
        handler_name = contract.handler if contract is not None else None
        handler = (
            getattr(self.client, handler_name, None)
            if handler_name is not None
            else None
        )
        identity = self.router_identity
        firmware_supported = contract is not None and contract.supports(
            identity.model,
            identity.firmware,
        )
        return ManagementCommandDecision(
            configured=self.controls_enabled,
            authenticated_capability=self.has_capability("authenticated_json"),
            contract_known=contract is not None,
            surface_allowed=(
                contract is not None
                and contract.execution_surface
                is ManagementExecutionSurface.NATIVE_ENTITY
            ),
            firmware_supported=firmware_supported,
            capability_supported=(
                contract is not None
                and contract.capability.casefold() in self._feature_families
                and self.has_capability(contract.capability)
            ),
            handler_available=callable(handler),
            session_available=self.management_controls_available,
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
                {}, error_name=safe_error_class_name(err)
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
        self._poll_group_succeeded[group] = True
        self._poll_group_last_success[group] = now
        self._poll_group_last_error[group] = None
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

    async def _async_update_verification_family_locked(
        self,
        family: str,
        group: PollGroup,
    ) -> GroupSnapshot:
        """Refresh only one command family's readback endpoint."""
        report = self._capability_report
        capability = (
            report.feature_endpoints.get(family) if report is not None else None
        )
        if capability is not None and capability.endpoint == "data/Status.json":
            status = await self.client.get_status()
            self._router_info = status.info
            partial, inferred_capabilities = normalize_status_payload(status)
            self._public_status_data = _thaw(partial)
            self._capabilities = self._capabilities | inferred_capabilities
            self._endpoint_errors.pop("status", None)
            self._public_status_next_poll_at = (
                self._monotonic_time() + self._public_status_interval
            )
        else:
            partial = await self._async_fetch_families(
                (family,),
                propagate_errors=True,
                release_authenticated_session=False,
            )
        now = datetime.now(UTC)
        transitions = self._merge_data(partial)
        self._generation += 1
        self._last_transitions = transitions
        return GroupSnapshot(
            group=group,
            data=self._data,
            generation=self._generation,
            updated_at=now,
            transitions=transitions,
        )

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
        self._poll_group_succeeded[group] = False
        self._poll_group_last_error[group] = safe_error_class_name(error)
        self._update_failures += 1
        self._merge_data(
            {
                "diagnostics": {
                    "failed_group": group.value,
                    "last_error": safe_error_class_name(error),
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
            "generation": self._management_generation,
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
            self._management_generation += 1
            self._cancel_admin_action_grant_expiry()
            self._admin_action_target_grants.clear()
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
            {}, error_name=safe_error_class_name(error)
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
                self._endpoint_errors["status"] = safe_error_class_name(err)
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
                self._endpoint_errors["wan_counters"] = safe_error_class_name(err)
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
                    self._endpoint_errors["wan_counters"] = safe_error_class_name(err)
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
                self._endpoint_errors["wan_counters"] = safe_error_class_name(err)
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
                self._endpoint_errors["dsl_metrics"] = safe_error_class_name(err)
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._unavailable_dsl_optional_values()},
                )
            except SpeedportUnsupportedError as err:
                self._defer_dsl_metrics_retry(unsupported=True)
                self._endpoint_errors["dsl_metrics"] = safe_error_class_name(err)
                partial = _deep_merge_dicts(
                    partial,
                    {"dsl": self._unavailable_dsl_optional_values()},
                )
            except SpeedportError as err:
                self._defer_dsl_metrics_retry(unsupported=False)
                self._endpoint_errors["dsl_metrics"] = safe_error_class_name(err)
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

    async def _async_fetch_families(
        self,
        families: Iterable[str],
        *,
        propagate_errors: bool = False,
        release_authenticated_session: bool = True,
        update_management_access: bool = True,
    ) -> dict[str, Any]:
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
        protected_retry_deferred = not propagate_errors and (
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
                    if propagate_errors:
                        raise
                    authenticated_blocked = True
                    self._mark_management_locked(err)
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=safe_error_class_name(err)
                    )
                    break
                except SpeedportAuthenticationError as err:
                    if propagate_errors:
                        raise
                    authenticated_blocked = True
                    self._mark_management_unavailable()
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=safe_error_class_name(err)
                    )
                    break
                except SpeedportSessionBusyError as err:
                    if propagate_errors:
                        raise
                    authenticated_blocked = True
                    self._mark_management_busy(err)
                    partial = self._invalidate_authenticated_families(
                        partial, error_name=safe_error_class_name(err)
                    )
                    break
                except SpeedportUnsupportedError as err:
                    if propagate_errors:
                        raise
                    failed_families = frozenset(endpoint_families)
                    for family in endpoint_families:
                        self._endpoint_errors[family] = safe_error_class_name(err)
                    for family in endpoint_families:
                        partial = _deep_merge_dicts(
                            partial,
                            self._unavailable_family_data(
                                family,
                                excluded_families=failed_families,
                            ),
                        )
                except SpeedportError as err:
                    if propagate_errors:
                        raise
                    if authenticated:
                        authenticated_blocked = True
                        self._mark_management_unavailable()
                        partial = self._invalidate_authenticated_families(
                            partial, error_name=safe_error_class_name(err)
                        )
                        break
                    for family in endpoint_families:
                        self._endpoint_errors[family] = safe_error_class_name(err)
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
                        self._observe_normalized_read_capabilities(normalized)
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
            if authenticated_attempted and release_authenticated_session:
                await self.client.logout()

        if (
            update_management_access
            and authenticated_attempted
            and not authenticated_blocked
        ):
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

    def _matches_command_readback(
        self,
        verification: ManagementVerificationPolicy,
        parameters: Mapping[str, Any],
    ) -> bool:
        """Match refreshed normalized state to one exact command target."""
        if (
            verification.strategy is not ManagementVerificationStrategy.EXACT
            or verification.expected_parameter is None
            or len(verification.readback_paths) != 1
        ):
            return False
        expected = parameters[verification.expected_parameter]
        current = self.get(verification.readback_paths[0], _MISSING)
        value_field = verification.collection_value_field
        if value_field is None:
            return _same_exact_value(current, expected)
        if not isinstance(current, Sequence) or isinstance(
            current, (str, bytes, bytearray)
        ):
            return False

        matches: list[Mapping[str, Any]] = []
        for item in current:
            if not isinstance(item, Mapping):
                continue
            identity_matches = True
            for identity in verification.collection_identity:
                identity_expected = parameters[identity.parameter]
                if identity.ignore_when_none and identity_expected is None:
                    continue
                if not _same_exact_value(
                    item.get(identity.field, _MISSING),
                    identity_expected,
                ):
                    identity_matches = False
                    break
            if identity_matches:
                matches.append(item)
        return len(matches) == 1 and _same_exact_value(
            matches[0].get(value_field, _MISSING),
            expected,
        )

    def _verification_readback_family(
        self,
        verification: ManagementVerificationPolicy,
    ) -> str:
        """Choose family proven to own one exact normalized readback path."""
        readback_path = verification.readback_paths[0]
        for family in verification.readback_families:
            if family in self._feature_families and _mapping_has_path(
                self._family_data.get(family, {}), readback_path
            ):
                return family
        for family in verification.readback_families:
            if family in self._feature_families:
                return family
        return verification.readback_families[0]

    async def async_execute(
        self,
        command: str,
        *,
        verify_group: PollGroup | _ContractVerificationSentinel | None = (
            _CONTRACT_VERIFICATION
        ),
        **parameters: Any,
    ) -> Any:
        """Run one allowed command through its immutable verification contract."""
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

        contract = get_command_write_contract(command)
        handler = (
            getattr(self.client, contract.handler, None)
            if contract is not None and contract.handler is not None
            else None
        )
        if not callable(handler):
            raise HomeAssistantError(
                "This router does not support the requested action.",
                translation_domain=DOMAIN,
                translation_key="command_unsupported",
            )
        if contract is None or not contract.accepts_parameters(parameters):
            raise HomeAssistantError(
                "The requested action parameters do not match its reviewed contract.",
                translation_domain=DOMAIN,
                translation_key="command_unsupported",
            )
        verification = contract.verification
        if verification is None:
            raise HomeAssistantError(
                "This router does not support the requested action.",
                translation_domain=DOMAIN,
                translation_key="command_unsupported",
            )
        contract_verify_group = (
            PollGroup(verification.cadence.value)
            if verification.cadence is not None
            else None
        )
        if (
            verify_group is not _CONTRACT_VERIFICATION
            and verify_group is not contract_verify_group
        ):
            raise HomeAssistantError(
                "The requested verification policy does not match its reviewed "
                "contract.",
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
            if not self.command_decision(command).executable:
                raise HomeAssistantError(
                    "The router management capability is not currently available.",
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

                if contract_verify_group is None:
                    return result

                retry_delays = (
                    verification.readback_retry_delays
                    if verification.strategy is ManagementVerificationStrategy.EXACT
                    else ()
                )
                readback_family = (
                    self._verification_readback_family(verification)
                    if verification.strategy is ManagementVerificationStrategy.EXACT
                    else None
                )
                for attempt, delay in enumerate((0.0, *retry_delays)):
                    if delay:
                        await asyncio.sleep(delay)
                    try:
                        if readback_family is None:
                            await self._async_update_group_locked(contract_verify_group)
                        else:
                            await self._async_update_verification_family_locked(
                                readback_family,
                                contract_verify_group,
                            )
                    except SpeedportError as err:
                        if attempt < len(
                            retry_delays
                        ) and _retryable_verification_error(err):
                            continue
                        self._publish_authenticated_failure(err)
                        raise HomeAssistantError(
                            "The router action was sent, but its resulting state could "
                            "not be verified. Check the router state before trying "
                            "again.",
                            translation_domain=DOMAIN,
                            translation_key="command_verification_failed",
                        ) from err

                    matches = (
                        verification.strategy
                        is not ManagementVerificationStrategy.EXACT
                        or self._matches_command_readback(verification, parameters)
                    )
                    if not matches and attempt < len(retry_delays):
                        continue

                    coordinator = self._coordinators.get(contract_verify_group)
                    if coordinator is not None:
                        coordinator.async_set_updated_data(
                            GroupSnapshot(
                                group=contract_verify_group,
                                data=self._data,
                                generation=self._generation,
                                updated_at=datetime.now(UTC),
                                transitions=self._last_transitions,
                            )
                        )
                    if not matches:
                        raise HomeAssistantError(
                            "The router action was sent, but its resulting state did "
                            "not match the requested value.",
                            translation_domain=DOMAIN,
                            translation_key="command_verification_failed",
                        )
                    return result

                raise AssertionError("Command verification schedule was empty")
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
            "capability_report": _diagnostic_capability_report(self._capability_report),
            "data": _thaw(self._data),
            "observed_feature_schema": _thaw(observed_schema),
            "observed_candidate_schema": _thaw(observed_candidate_schema),
            "candidate_inventory": {
                "status": self._candidate_inventory_status,
                **self._candidate_inventory_counts,
                "last_attempted_at": (
                    self._candidate_inventory_last_attempt.isoformat()
                    if self._candidate_inventory_last_attempt is not None
                    else None
                ),
                "last_completed_at": (
                    self._candidate_inventory_last_completed.isoformat()
                    if self._candidate_inventory_last_completed is not None
                    else None
                ),
                "last_error": self._candidate_inventory_last_error,
            },
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
                    "available": self._poll_group_succeeded[group] is True,
                    **dict(self.poll_group_health(group)),
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
        feature_families = tuple(
            str(name).casefold() for name in report.feature_endpoints
        )
        capabilities = set(feature_families)
        if report.status_json:
            capabilities.update({"status", "diagnostics"})
        if report.tr064:
            capabilities.add("tr064")
        if report.wan_counters or self._wan_counter_probe_pending:
            capabilities.update({"wan_counters", "wan"})
        if report.authenticated_json:
            capabilities.add("authenticated_json")
        self._capabilities = frozenset(capabilities)

    def _observe_normalized_read_capabilities(
        self,
        normalized: Mapping[str, Any],
    ) -> None:
        """Publish only non-empty canonical roots from one successful read."""
        observed = frozenset(
            root
            for root, payload in normalized.items()
            if root in _NORMALIZED_READ_CAPABILITY_ROOTS
            and isinstance(payload, Mapping)
            and payload
        )
        self._capabilities = self._capabilities | observed

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


def _admin_action_success_result(
    contract: AdminActionContract,
    *,
    status: str,
    expected: bool,
) -> dict[str, Any]:
    """Return only contract-owned, value-free action completion state."""
    if contract.deletion_result:
        return {"status": status, "deleted": True}
    if contract.expected_parameter is None:
        return {"status": status, "lifecycle": "scan_active"}
    return {"status": status, "active": expected}


def _require_admin_action_requester(
    requester: tuple[str, str] | None,
) -> tuple[str, str]:
    """Validate one server-derived Home Assistant user and login-session pair."""
    if (
        not isinstance(requester, tuple)
        or len(requester) != _ADMIN_ACTION_REQUESTER_PARTS
        or any(
            not isinstance(value, str)
            or not value
            or len(value) > _ADMIN_ACTION_REQUESTER_ID_MAX_LENGTH
            or not value.isprintable()
            for value in requester
        )
    ):
        raise AdminActionUnavailableError(
            "Administrator action requester is unavailable"
        )
    return requester


def _admin_action_arguments(
    parameters: Mapping[str, Any],
    names: tuple[str, ...],
) -> dict[str, Any]:
    """Select only statically declared handler arguments."""
    return {name: parameters[name] for name in names}


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


def _diagnostic_capability_report(report: object) -> Any:
    """Return capability evidence with failure messages reduced to class names."""
    thawed = _thaw(report)
    if not isinstance(thawed, dict):
        return thawed
    failures = thawed.get("failures")
    if isinstance(failures, Mapping):
        thawed["failures"] = {
            str(family): safe_error_class_name(error)
            for family, error in failures.items()
        }
    return thawed


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
