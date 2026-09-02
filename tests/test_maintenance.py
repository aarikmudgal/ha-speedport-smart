"""Offline fixtures for one-shot destructive maintenance, never router calls."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call, patch

import pytest

from custom_components.speedport_smart.admin_actions import ADMIN_ACTION_CONTRACTS
from custom_components.speedport_smart.api.exceptions import (
    SpeedportAuthenticationError,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportMutationOutcomeUnknownError,
)
from custom_components.speedport_smart.maintenance import (
    MaintenanceError,
    execute_maintenance_action,
    maintenance_payload,
    system_log_snapshot,
)
from custom_components.speedport_smart.management import (
    ManagementConfirmation,
    ManagementRisk,
)
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
)

_MODEL = "Speedport Smart 4R Typ A"
_FIRMWARE = "010152.5.0.001.0"
_PARAMETERS = {
    "system_factory_reset": {"backup_saved": True, "physical_access": True},
    "system_dect_reset": {"retain_registrations": True},
    "system_dsl_modem_mode": {
        "backup_saved": True,
        "physical_access": True,
        "link_lan1_ready": True,
        "firewall_warning_accepted": True,
    },
    "system_log_clear": {},
}
_ROW = {
    "timestamp": "2026-09-02 09:00:00",
    "message_id": "SYS001",
    "message": "PRIVATE",
}
_LOG = {"router_state": "OK", "filter_log": "0", "addmessage": [_ROW]}


def _report(action: str) -> CapabilityReport:
    contract = ADMIN_ACTION_CONTRACTS[action]
    return CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                item.family: EndpointCapability(
                    item.family, item.endpoint, authenticated=True, referer=item.referer
                )
                for item in contract.capability_proofs
            }
        ),
    )


def _transport(action: str) -> SimpleNamespace:
    reads: list[dict[str, Any]] = [{"router_state": "OK"}]
    if action == "system_dect_reset":
        reads = [
            {
                "router_state": "OK",
                "dect_halb": "0",
                "dect_eco": "1",
                "dect_pin": "PRIVATE",
            },
            {"router_state": "OK", "dect_detect_status": "0"},
        ]
    elif action == "system_dsl_modem_mode":
        reads.append({"router_state": "OK", "config_connection": "0"})
    elif action == "system_log_clear":
        reads = [_LOG, {**_LOG, "addmessage": []}]
    return SimpleNamespace(
        get_json=AsyncMock(side_effect=reads),
        post_maintenance_action=AsyncMock(return_value={"unreviewed": "PRIVATE"}),
    )


async def _execute(transport: Any, action: str, **overrides: Any) -> dict[str, object]:
    arguments = {
        "parameters": _PARAMETERS[action],
        "confirmed": True,
        "confirmation_text": ADMIN_ACTION_CONTRACTS[action].typed_confirmation,
        "model": _MODEL,
        "firmware": _FIRMWARE,
        "capability_report": _report(action),
        **overrides,
    }
    return await execute_maintenance_action(transport, action, **arguments)


@pytest.mark.parametrize("action", _PARAMETERS)
def test_maintenance_contracts_are_typed_and_have_no_fake_state(action: str) -> None:
    """Destructive operations cannot enter the Boolean lifecycle executor."""
    contract = ADMIN_ACTION_CONTRACTS[action]
    assert contract.execution_policy == "maintenance"
    assert contract.risk is ManagementRisk.DESTRUCTIVE
    assert contract.confirmation is ManagementConfirmation.TYPED
    assert contract.typed_confirmation
    assert contract.warning
    assert contract.expected_value is None
    assert contract.expected_parameter is None
    with pytest.raises(ValueError, match="no Boolean expectation"):
        contract.expected(_PARAMETERS[action])
    with pytest.raises(ValueError, match="cannot claim Boolean"):
        replace(contract, expected_value=True)
    with pytest.raises(ValueError, match="cannot claim Boolean"):
        replace(contract, warning=None)


def test_deferred_maintenance_cannot_declare_immediate_verification() -> None:
    """A reboot timer cannot masquerade as independent verification."""
    contract = ADMIN_ACTION_CONTRACTS["system_factory_reset"]
    with pytest.raises(ValueError, match="readback"):
        replace(contract, verification_handler="get_json")
    with pytest.raises(ValueError, match="readback"):
        replace(contract, readback_policy="exact")


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("system_factory_reset", {"reset_device": "true"}),
        ("system_dect_reset", {"reboot_hs": "true", "HSregister": 1}),
        ("system_dsl_modem_mode", {"activatemodem": "true"}),
        ("system_log_clear", {"action_clearlist": "true"}),
    ],
)
def test_maintenance_payloads_are_exact_and_attestations_never_go_on_wire(
    action: str, expected: dict[str, str | int]
) -> None:
    """Fixed fields are taken from reviewed page scripts, not JSONSource guesses."""
    assert maintenance_payload(action, _PARAMETERS[action]) == expected
    with pytest.raises(MaintenanceError):
        maintenance_payload(action, {**_PARAMETERS[action], "endpoint": "PRIVATE"})


def test_dect_registration_choice_has_exact_firmware_polarity() -> None:
    """Unchecked means both handset and repeater registrations are not retained."""
    assert maintenance_payload(
        "system_dect_reset", {"retain_registrations": False}
    ) == {
        "reboot_hs": "true",
        "HSregister": 0,
    }


@pytest.mark.parametrize("value", [0, 1, "0", "1", None, 1.0])
def test_dect_retention_requires_explicit_boolean(value: object) -> None:
    """Never coerce zero, strings or missing choices into consent."""
    with pytest.raises(MaintenanceError):
        maintenance_payload("system_dect_reset", {"retain_registrations": value})


@pytest.mark.parametrize("action", ["system_factory_reset", "system_dsl_modem_mode"])
def test_each_maintenance_attestation_must_be_explicitly_true(action: str) -> None:
    """These are user attestations, not invented machine-verifiable backups."""
    for name in _PARAMETERS[action]:
        with pytest.raises(MaintenanceError, match="confirmation_required"):
            maintenance_payload(action, {**_PARAMETERS[action], name: False})


@pytest.mark.parametrize("action", _PARAMETERS)
@pytest.mark.parametrize(
    "overrides",
    [
        {"confirmed": False},
        {"confirmed": 1},
        {"confirmation_text": None},
        {"confirmation_text": "PRIVATE"},
        {"confirmation_text": "FACTORY RESET ROUTER "},
        {"model": "Speedport Smart 4 Typ A"},
        {"firmware": "010152.5.0.001.1"},
        {"capability_report": None},
        {"parameters": {"PRIVATE": "value"}},
    ],
)
async def test_confirmation_schema_and_proof_rejection_precedes_all_io(
    action: str, overrides: dict[str, Any]
) -> None:
    """Invalid authority, firmware and input cannot reach a router operation."""
    transport = _transport(action)
    with pytest.raises(MaintenanceError) as error:
        await _execute(transport, action, **overrides)
    assert "PRIVATE" not in str(error.value)
    transport.get_json.assert_not_awaited()
    transport.post_maintenance_action.assert_not_awaited()


@pytest.mark.parametrize("action", _PARAMETERS)
@pytest.mark.parametrize("field", ["endpoint", "referer", "authenticated"])
def test_every_endpoint_proof_is_exact(action: str, field: str) -> None:
    """The contract's read evidence contains exact authenticated transport paths."""
    report = _report(action)
    for family, endpoint in report.feature_endpoints.items():
        changed = replace(
            endpoint, **{field: False if field == "authenticated" else "other"}
        )
        bad = replace(
            report, feature_endpoints={**report.feature_endpoints, family: changed}
        )
        assert not ADMIN_ACTION_CONTRACTS[action].proofs_satisfied(bad)


@pytest.mark.parametrize("action", _PARAMETERS)
@pytest.mark.parametrize(
    "state",
    [
        None,
        "MODEM",
        "THROWN",
        "DECTUPD",
        "TR64",
        "TR69",
        "EMCALL",
        "ok",
        ["OK", "MODEM"],
    ],
)
async def test_actual_preflight_router_state_must_be_ready(
    action: str, state: object
) -> None:
    """Unknown or competing runtime modes block even reviewed firmware."""
    transport = _transport(action)
    transport.get_json.side_effect = [{"router_state": state}]
    with pytest.raises(MaintenanceError):
        await _execute(transport, action)
    transport.post_maintenance_action.assert_not_awaited()


@pytest.mark.parametrize("connection", [None, "1", 1, True, False, 0.0, "00"])
async def test_dsl_modem_requires_fresh_exact_wired_connection(
    connection: object,
) -> None:
    """A cached capability cannot replace the fresh connection-path guard."""
    transport = _transport("system_dsl_modem_mode")
    transport.get_json.side_effect = [
        {"router_state": "OK"},
        {"router_state": "OK", "config_connection": connection},
    ]
    with pytest.raises(MaintenanceError):
        await _execute(transport, "system_dsl_modem_mode")
    transport.post_maintenance_action.assert_not_awaited()


@pytest.mark.parametrize("scan", [None, "1", "unknown", False, 0.0])
async def test_dect_preflight_blocks_enrollment_or_unknown_state(scan: object) -> None:
    """Do not reset DECT during enrollment or without an exact lifecycle flag."""
    transport = _transport("system_dect_reset")
    transport.get_json.side_effect = [
        {"router_state": "OK", "dect_halb": "0", "dect_eco": "1"},
        {"router_state": "OK", "dect_detect_status": scan},
    ]
    if scan is False:
        # A real Boolean false is an exact supported decoded flag.
        assert (await _execute(transport, "system_dect_reset"))[
            "status"
        ] == "outcome_unknown"
    else:
        with pytest.raises(MaintenanceError):
            await _execute(transport, "system_dect_reset")
        transport.post_maintenance_action.assert_not_awaited()


@pytest.mark.parametrize(
    "action", ["system_factory_reset", "system_dect_reset", "system_dsl_modem_mode"]
)
@pytest.mark.parametrize(
    "response", [{}, {"status": "ok"}, {"result": "ok"}, {"PRIVATE": "value"}]
)
async def test_reconnect_actions_never_invent_acknowledgement_or_verification(
    action: str, response: dict[str, Any]
) -> None:
    """HTTP completion, generic status and timer callbacks do not prove reset."""
    transport = _transport(action)
    transport.post_maintenance_action.return_value = response
    result = await _execute(transport, action)
    assert result == {
        "status": "outcome_unknown",
        "verification": "reconnect_required",
        "retry_safe": False,
    }
    transport.post_maintenance_action.assert_awaited_once_with(
        action, _PARAMETERS[action]
    )
    assert transport.get_json.await_count == (
        1 if action == "system_factory_reset" else 2
    )
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize("action", _PARAMETERS)
async def test_explicit_rejection_stops_without_readback_or_second_post(
    action: str,
) -> None:
    """A router refusal cannot be replaced by an inferred eventual success."""
    transport = _transport(action)
    transport.post_maintenance_action.side_effect = SpeedportCommandRejectedError(
        "PRIVATE"
    )
    with pytest.raises(MaintenanceError, match="action_rejected") as error:
        await _execute(transport, action)
    assert "PRIVATE" not in str(error.value)
    assert transport.post_maintenance_action.await_count == 1
    assert transport.get_json.await_count == (
        2 if action in {"system_dect_reset", "system_dsl_modem_mode"} else 1
    )


@pytest.mark.parametrize("action", _PARAMETERS)
@pytest.mark.parametrize(
    "error", [SpeedportMutationOutcomeUnknownError("PRIVATE"), RuntimeError("PRIVATE")]
)
async def test_indeterminate_send_never_retries_or_claims_success(
    action: str, error: Exception
) -> None:
    """After the mutation boundary every uncertain result remains unknown."""
    transport = _transport(action)
    transport.post_maintenance_action.side_effect = error
    result = await _execute(transport, action)
    assert result["status"] == "outcome_unknown"
    assert result["retry_safe"] is False
    assert "PRIVATE" not in repr(result)
    assert transport.post_maintenance_action.await_count == 1


async def test_pre_send_authentication_failure_is_not_misreported_as_sent() -> None:
    """A failure before the sender's mutation boundary is an availability error."""
    transport = _transport("system_factory_reset")
    transport.post_maintenance_action.side_effect = SpeedportAuthenticationError(
        "PRIVATE"
    )
    with pytest.raises(MaintenanceError, match="action_unavailable"):
        await _execute(transport, "system_factory_reset")
    assert transport.post_maintenance_action.await_count == 1


@pytest.mark.parametrize("rows", [[], {}])
async def test_explicit_empty_log_is_unchanged_without_post(rows: object) -> None:
    """Already empty logs need no destructive request."""
    transport = _transport("system_log_clear")
    transport.get_json.side_effect = [{**_LOG, "addmessage": rows}]
    assert await _execute(transport, "system_log_clear") == {
        "status": "unchanged",
        "previous_messages_absent": True,
    }
    transport.post_maintenance_action.assert_not_awaited()


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {**_LOG, "filter_log": "1"},
        {**_LOG, "filter_log": 0.0},
        {**_LOG, "addmessage": None},
        {**_LOG, "addmessage": [None]},
        {**_LOG, "addmessage": [{"message": "PRIVATE"}]},
        {**_LOG, "addmessage": [_ROW] * 4097},
        {**_LOG, "truncated": True},
        {**_LOG, "has_more": "1"},
        {**_LOG, "next_cursor": "PRIVATE"},
        {**_LOG, "addmessage": [{**_ROW, "message": "x" * 8193}]},
        {
            **_LOG,
            "addmessage": {
                "timestamp": ["a"],
                "message_id": ["b", "c"],
                "message": ["PRIVATE"],
            },
        },
    ],
)
def test_log_snapshot_rejects_filtered_missing_partial_or_oversized_collections(
    raw: dict[str, Any],
) -> None:
    """The parser never drops malformed records or mistakes absence for empty."""
    with pytest.raises(MaintenanceError) as error:
        system_log_snapshot(raw)
    assert "PRIVATE" not in str(error.value)


def test_log_snapshot_supports_exact_codec_shapes() -> None:
    """Single, repeated and column-normalized records preserve the same identity."""
    expected = system_log_snapshot(_LOG)
    assert system_log_snapshot({**_LOG, "addmessage": _ROW}) == expected
    assert (
        system_log_snapshot(
            {
                **_LOG,
                "router_state": ["OK", "OK"],
                "filter_log": ["0", "0"],
                "addmessage": {name: [value] for name, value in _ROW.items()},
            }
        )
        == expected
    )
    assert "PRIVATE" not in repr(expected)
    assert "SYS001" not in repr(expected)


async def test_log_clear_requires_independent_absence_and_permits_new_messages() -> (
    None
):
    """Fresh messages may exist, but every previous message must be gone."""
    transport = _transport("system_log_clear")
    transport.get_json.side_effect = [
        _LOG,
        {**_LOG, "addmessage": [{**_ROW, "timestamp": "later"}]},
    ]
    assert await _execute(transport, "system_log_clear") == {
        "status": "verified",
        "previous_messages_absent": True,
    }
    transport.post_maintenance_action.assert_awaited_once()
    transport.get_json.assert_has_awaits(
        [
            call(
                "data/SystemMessages.json",
                authenticated=True,
                referer="html/content/config/system_log.html",
            )
        ]
        * 2
    )


async def test_log_clear_stale_readback_exhausts_bounded_reads_without_reposting() -> (
    None
):
    """Only four reads are attempted and the mutation is never repeated."""
    transport = _transport("system_log_clear")
    transport.get_json.side_effect = [_LOG] * 5
    with (
        patch(
            "custom_components.speedport_smart.maintenance.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
        pytest.raises(MaintenanceError, match="action_verification_failed"),
    ):
        await _execute(transport, "system_log_clear")
    assert transport.get_json.await_count == 5
    assert transport.post_maintenance_action.await_count == 1
    assert sleep.await_args_list == [call(0.5), call(1.0), call(2.0)]


@pytest.mark.parametrize(
    "error", [SpeedportConnectionError("PRIVATE"), SpeedportDecodeError("PRIVATE")]
)
async def test_log_clear_only_retries_safe_reads_after_transient_error(
    error: Exception,
) -> None:
    """Connection and decoding failures may retry only the independent GET."""
    transport = _transport("system_log_clear")
    transport.get_json.side_effect = [_LOG, error, {**_LOG, "addmessage": []}]
    with patch(
        "custom_components.speedport_smart.maintenance.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        assert (await _execute(transport, "system_log_clear"))["status"] == "verified"
    assert transport.get_json.await_count == 3
    assert transport.post_maintenance_action.await_count == 1


async def test_log_clear_never_accepts_empty_filtered_readback_or_auth_retries() -> (
    None
):
    """Incomplete data and session loss stop verification without a new login loop."""
    for after in (
        {**_LOG, "filter_log": "1", "addmessage": []},
        SpeedportAuthenticationError("PRIVATE"),
    ):
        transport = _transport("system_log_clear")
        transport.get_json.side_effect = [_LOG, after]
        with pytest.raises(MaintenanceError, match="action_verification_failed"):
            await _execute(transport, "system_log_clear")
        assert transport.get_json.await_count == 2
        assert transport.post_maintenance_action.await_count == 1


@pytest.mark.parametrize("action", _PARAMETERS)
async def test_fresh_preflight_proves_every_path_without_new_discovery_families(
    action: str,
) -> None:
    """Static eligibility is followed by exact per-execution authenticated reads."""
    transport = _transport(action)
    await _execute(
        transport, action, capability_report=CapabilityReport(authenticated_json=True)
    )
    for proof in ADMIN_ACTION_CONTRACTS[action].capability_proofs:
        assert (
            call(proof.endpoint, authenticated=True, referer=proof.referer)
            in transport.get_json.await_args_list
        )
