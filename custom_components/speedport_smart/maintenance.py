"""
One-shot maintenance actions with private preflight and honest recovery results.

The caller owns administrator authorization, the operation lock, rate limits,
cache invalidation and session cleanup. The transport must reject explicit
negative responses and distinguish failures before a POST from indeterminate
outcomes after sending. No mutation or private value is retried or published.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol

from .admin_actions import ADMIN_ACTION_CONTRACTS, AdminActionContract
from .api.exceptions import (
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportError,
    SpeedportMutationOutcomeUnknownError,
)

if TYPE_CHECKING:
    from .models import CapabilityReport

_MAX_LOG_ROWS: Final = 4096
_MAX_LOG_MESSAGE: Final = 8192
_LOG_FIELDS: Final = ("timestamp", "message_id", "message")
_ATTESTATIONS: Final = frozenset(
    {"backup_saved", "physical_access", "link_lan1_ready", "firewall_warning_accepted"}
)
MAINTENANCE_ACTION_IDS: Final = frozenset(
    key
    for key, contract in ADMIN_ACTION_CONTRACTS.items()
    if contract.execution_policy == "maintenance"
)
_TITLES: Final = {
    "system_factory_reset": "Factory reset router",
    "system_dect_reset": "Reset DECT settings",
    "system_dsl_modem_mode": "Enable DSL modem mode",
    "system_log_clear": "Clear system messages",
}
_INPUT_LABELS: Final = {
    "backup_saved": "I have saved a usable router configuration backup",
    "physical_access": "I have physical access and a recovery plan",
    "link_lan1_ready": "The downstream router and Link/LAN1 cabling are ready",
    "firewall_warning_accepted": (
        "I understand the firewall and other router functions will be disabled"
    ),
    "retain_registrations": "Keep DECT handsets and repeaters registered",
}


def maintenance_metadata(contract: AdminActionContract) -> dict[str, Any]:
    """Expose only immutable labels, inputs and the honest preflight policy."""
    if contract.action not in MAINTENANCE_ACTION_IDS:
        return {}
    return {
        "title": _TITLES[contract.action],
        "execution_policy": "maintenance",
        "readback_policy": contract.readback_policy,
        "preflight_required": True,
        "live_write_verified": False,
        "warning": contract.warning,
        "inputs": [
            {
                "name": name,
                "kind": "boolean",
                "label": _INPUT_LABELS[name],
                "must_be_true": name in _ATTESTATIONS,
            }
            for name in contract.input_specs
        ],
    }


class MaintenanceError(ValueError):
    """Closed value-free failures safe to map onto administrator error codes."""

    def __init__(self, code: str = "action_unavailable") -> None:
        """Retain only a known error code, never transport or router text."""
        if code not in {
            "action_unavailable",
            "confirmation_required",
            "action_rejected",
            "action_busy",
            "action_verification_failed",
        }:
            raise ValueError("Unknown maintenance error code")
        super().__init__(code)
        self.code = code


class MaintenanceTransport(Protocol):
    """Existing serialized GET owner plus a fixed one-shot maintenance sender."""

    async def get_json(
        self, endpoint: str, *, authenticated: bool, referer: str
    ) -> dict[str, Any]:
        """Read fresh state through the current configured router connection."""

    async def post_maintenance_action(
        self, action: str, parameters: Mapping[str, object]
    ) -> object:
        """Build maintenance_payload and send it once, rejecting explicit errors."""


@dataclass(frozen=True, slots=True)
class SystemLogSnapshot:
    """Private bounded fingerprints; raw messages never survive the read."""

    fingerprints: frozenset[str] = field(repr=False)

    @property
    def empty(self) -> bool:
        """Return whether the complete unfiltered list is explicitly empty."""
        return not self.fingerprints


def _scalar(raw: Mapping[str, Any], name: str) -> object:
    """Permit only identical duplicated scalars produced by the shared codec."""
    value = raw.get(name)
    if (
        isinstance(value, list)
        and value
        and type(value[0]) in {str, int, bool}
        and all(type(item) is type(value[0]) and item == value[0] for item in value)
    ):
        return value[0]
    return value


def _flag(raw: Mapping[str, Any], name: str) -> bool:
    value = _scalar(raw, name)
    if type(value) is bool:
        return value
    if type(value) is int and value in {0, 1}:
        return value == 1
    if type(value) is str and value in {"0", "1"}:
        return value == "1"
    raise MaintenanceError


def _ready(raw: Mapping[str, Any]) -> None:
    """Block thrown, modem, competing-session and DECT-update router modes."""
    if _scalar(raw, "router_state") != "OK":
        raise MaintenanceError


def _log_text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MaintenanceError
    return value


def system_log_snapshot(raw: Mapping[str, Any]) -> SystemLogSnapshot:
    """Require an explicit whole unfiltered collection without dropping a row."""
    _ready(raw)
    filter_value = _scalar(raw, "filter_log")
    if not (
        (type(filter_value) is int and filter_value == 0)
        or (type(filter_value) is str and filter_value == "0")
    ):
        raise MaintenanceError
    if any(
        name in raw and raw[name] not in (False, 0, "0", None, "")
        for name in ("truncated", "has_more", "next_page", "next_cursor")
    ):
        raise MaintenanceError
    value = raw.get("addmessage")
    if isinstance(value, Mapping):
        if not value:
            rows: list[Mapping[str, Any]] = []
        elif any(isinstance(value.get(key), list) for key in _LOG_FIELDS):
            columns = [value.get(key) for key in _LOG_FIELDS]
            if not all(isinstance(column, list) for column in columns):
                raise MaintenanceError
            checked_columns = [column for column in columns if isinstance(column, list)]
            lengths = {len(column) for column in checked_columns}
            if len(lengths) != 1 or lengths.pop() > _MAX_LOG_ROWS:
                raise MaintenanceError
            rows = [
                dict(zip(_LOG_FIELDS, items, strict=True))
                for items in zip(*checked_columns, strict=True)
            ]
        else:
            rows = [value]
    elif isinstance(value, list):
        if len(value) > _MAX_LOG_ROWS or any(
            not isinstance(row, Mapping) for row in value
        ):
            raise MaintenanceError
        rows = value
    else:
        # Missing templates do not prove an empty collection.
        raise MaintenanceError
    fingerprints = set()
    for row in rows:
        timestamp = _log_text(row.get("timestamp"), 128)
        message = _log_text(row.get("message"), _MAX_LOG_MESSAGE)
        message_id = row.get("message_id")
        if type(message_id) is int and message_id >= 0:
            message_id = str(message_id)
        message_id = _log_text(message_id, 64)
        fingerprints.add(
            hashlib.sha256(
                json.dumps((timestamp, message_id, message), ensure_ascii=True).encode()
            ).hexdigest()
        )
    return SystemLogSnapshot(frozenset(fingerprints))


def maintenance_payload(
    action: str, parameters: Mapping[str, object]
) -> dict[str, str | int]:
    """Construct only one of four exact fixed payloads; never accept raw fields."""
    contract = ADMIN_ACTION_CONTRACTS.get(action)
    if (
        contract is None
        or contract.execution_policy != "maintenance"
        or not contract.accepts_parameters(parameters)
    ):
        raise MaintenanceError
    if any(parameters[name] is not True for name in _ATTESTATIONS & parameters.keys()):
        raise MaintenanceError("confirmation_required")
    if action == "system_factory_reset":
        return {"reset_device": "true"}
    if action == "system_dect_reset":
        return {
            "reboot_hs": "true",
            "HSregister": 1 if parameters["retain_registrations"] is True else 0,
        }
    if action == "system_dsl_modem_mode":
        return {"activatemodem": "true"}
    if action == "system_log_clear":
        return {"action_clearlist": "true"}
    raise MaintenanceError


async def _read(
    transport: MaintenanceTransport, endpoint: str, referer: str
) -> dict[str, Any]:
    raw = await transport.get_json(endpoint, authenticated=True, referer=referer)
    if not isinstance(raw, Mapping):
        raise MaintenanceError
    return raw


async def _preflight(
    transport: MaintenanceTransport, contract: AdminActionContract
) -> SystemLogSnapshot | None:
    """Read actual router state, not a fabricated Boolean 'ready' lifecycle."""
    if contract.action == "system_dect_reset":
        raw = await _read(transport, "data/DECTSettings.json", contract.referer)
        _ready(raw)
        _flag(raw, "dect_halb")
        _flag(raw, "dect_eco")
        scan = await _read(
            transport,
            "data/DECTInfo.json",
            "html/content/phone/phone_dect_mobiles.html",
        )
        _ready(scan)
        if _flag(scan, "dect_detect_status"):
            raise MaintenanceError("action_busy")
        return None
    raw = await _read(transport, contract.endpoint, contract.referer)
    _ready(raw)
    if contract.action == "system_log_clear":
        return system_log_snapshot(raw)
    if contract.action == "system_dsl_modem_mode":
        energy = await _read(
            transport, "data/Energy.json", "html/content/config/energy.html"
        )
        _ready(energy)
        connection = _scalar(energy, "config_connection")
        if not (
            (type(connection) is int and connection == 0)
            or (type(connection) is str and connection == "0")
        ):
            raise MaintenanceError
    return None


def _unknown(contract: AdminActionContract) -> dict[str, object]:
    """No reviewed callback proves acceptance for these maintenance actions."""
    return {
        "status": "outcome_unknown",
        "verification": contract.readback_policy,
        "retry_safe": False,
    }


async def execute_maintenance_action(
    transport: MaintenanceTransport,
    action: str,
    *,
    parameters: Mapping[str, object],
    confirmed: bool,
    confirmation_text: str | None,
    model: str | None,
    firmware: str | None,
    capability_report: CapabilityReport | None,
) -> dict[str, object]:
    """Preflight once, send at most once, never follow a new management address."""
    contract = ADMIN_ACTION_CONTRACTS.get(action)
    if contract is None or contract.execution_policy != "maintenance":
        raise MaintenanceError
    if confirmed is not True or confirmation_text != contract.typed_confirmation:
        raise MaintenanceError("confirmation_required")
    parameters = MappingProxyType(dict(parameters))
    maintenance_payload(action, parameters)
    if (
        not contract.supports(model, firmware)
        or capability_report is None
        or capability_report.authenticated_json is not True
    ):
        raise MaintenanceError
    try:
        before = await _preflight(transport, contract)
    except MaintenanceError:
        raise
    except Exception:  # noqa: BLE001 - private transport errors never reach the panel
        raise MaintenanceError from None
    if before is not None and before.empty:
        return {"status": "unchanged", "previous_messages_absent": True}
    try:
        # The fixed sender rebuilds the payload, obtains the token before the
        # mutation boundary, and does not retry the POST under any condition.
        await transport.post_maintenance_action(action, parameters)
    except SpeedportCommandRejectedError:
        raise MaintenanceError("action_rejected") from None
    except SpeedportMutationOutcomeUnknownError:
        return _unknown(contract)
    except SpeedportError:
        # The sender reports ordinary errors only before crossing the boundary.
        raise MaintenanceError from None
    except Exception:  # noqa: BLE001 - a local failure after sending is indeterminate
        return _unknown(contract)
    if contract.readback_policy == "reconnect_required":
        return _unknown(contract)
    if before is None:
        return _unknown(contract)
    for delay in contract.readback_delays:
        if delay:
            await asyncio.sleep(delay)
        try:
            after = system_log_snapshot(
                await _read(transport, contract.endpoint, contract.referer)
            )
        except (SpeedportConnectionError, SpeedportDecodeError):
            continue
        except Exception:  # noqa: BLE001 - stop without exposing private response text
            break
        if before.fingerprints.isdisjoint(after.fingerprints):
            return {"status": "verified", "previous_messages_absent": True}
    raise MaintenanceError("action_verification_failed")
