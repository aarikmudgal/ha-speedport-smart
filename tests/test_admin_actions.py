"""Tests for administrator-only ephemeral router actions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized

from custom_components.speedport_smart import hub as hub_module
from custom_components.speedport_smart.admin_actions import (
    ADMIN_ACTION_CONTRACTS,
    DECT_MOBILES_REFERER,
    DECT_REPEATER_REFERER,
    VOIP_REFERER,
)
from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportMutationOutcomeUnknownError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import (
    AdminActionBusyError,
    AdminActionConfirmationError,
    AdminActionOutcomeUnknownError,
    AdminActionRateLimitError,
    AdminActionRejectedError,
    AdminActionUnavailableError,
    AdminActionVerificationError,
    AdminQueryRateLimitError,
    SpeedportHub,
)
from custom_components.speedport_smart.management import (
    ManagementConfirmation,
    ManagementRisk,
)
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
)
from custom_components.speedport_smart.panel_queries import (
    PANEL_DECT_HANDSET_ENROLL_WS_TYPE,
    PANEL_DECT_HANDSET_SET_PAGING_WS_TYPE,
    PANEL_DECT_REPEATER_ENROLL_WS_TYPE,
    PANEL_VOIP_LINE_SET_ACTIVE_WS_TYPE,
    PANEL_VOIP_LINE_TARGETS_WS_TYPE,
    _send_admin_action_result,
    websocket_dect_handset_enroll,
    websocket_dect_handset_set_paging,
    websocket_dect_repeater_enroll,
    websocket_voip_line_set_active,
    websocket_voip_line_targets,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_EXACT_CAPABILITIES = {
    "dect": EndpointCapability(
        "dect",
        "data/DECTStation.json",
        authenticated=True,
        referer=DECT_MOBILES_REFERER,
    ),
    "dect_status": EndpointCapability(
        "dect_status",
        "data/DECTInfo.json",
        authenticated=True,
        referer=DECT_MOBILES_REFERER,
    ),
    "voip_lines": EndpointCapability(
        "voip_lines",
        "data/IPPhoneNumbers.json",
        authenticated=True,
        referer=VOIP_REFERER,
    ),
}
_REQUESTER = ("user-1", "session-1")


def _report(*families: str) -> CapabilityReport:
    """Build one exact authenticated capability report."""
    return CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {family: _EXACT_CAPABILITIES[family] for family in families}
        ),
    )


async def _ready_hub(
    hass: HomeAssistant,
    client: MagicMock,
    report: CapabilityReport,
) -> SpeedportHub:
    """Return a management-ready hub with an exact action report."""
    client.setup.return_value = report
    client.last_management_error = None
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="entry",
        controls_enabled=True,
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()
    client.logout.reset_mock()
    client.logout_ephemeral.reset_mock()
    return hub


def _issue_target_token(
    hub: SpeedportHub,
    action: str,
    target_id: str,
    *,
    state: bool = False,
    requester: tuple[str, str] = _REQUESTER,
) -> str:
    """Issue one in-memory action grant through the production projection."""
    contract = ADMIN_ACTION_CONTRACTS[action]
    state_field = "paging" if action == "dect_handset_set_paging" else "active"
    result = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {
            "targets": [
                {
                    "target_id": target_id,
                    "target_fingerprint": "a" * 64,
                    "reference": target_id,
                    state_field: state,
                }
            ],
            "truncated": False,
        },
        requester=requester,
    )
    token = result["targets"][0]["target_token"]
    assert isinstance(token, str)
    return token


@pytest.mark.parametrize(
    ("action", "endpoint", "referer", "risk"),
    [
        (
            "dect_handset_enroll",
            "data/DECT.json",
            DECT_MOBILES_REFERER,
            ManagementRisk.SENSITIVE,
        ),
        (
            "dect_repeater_enroll",
            "data/DECTRepeater.json",
            DECT_REPEATER_REFERER,
            ManagementRisk.SENSITIVE,
        ),
        (
            "dect_handset_set_paging",
            "data/DECT.json",
            DECT_MOBILES_REFERER,
            ManagementRisk.SENSITIVE,
        ),
        (
            "voip_line_set_active",
            "data/IPPhoneNumbers.json",
            VOIP_REFERER,
            ManagementRisk.DISRUPTIVE,
        ),
    ],
)
def test_admin_action_contracts_are_exact_and_confirmed(
    action: str,
    endpoint: str,
    referer: str,
    risk: ManagementRisk,
) -> None:
    """Every action binds exact reviewed firmware transport and policy."""
    contract = ADMIN_ACTION_CONTRACTS[action]

    assert contract.endpoint == endpoint
    assert contract.referer == referer
    assert contract.risk is risk
    assert contract.confirmation is ManagementConfirmation.CONFIRM
    assert contract.supports("Speedport Smart 4R Typ A", "010152.5.0.001.0")
    assert not contract.supports("Speedport Smart 4 Typ A", "010152.5.0.001.0")
    assert not contract.supports("Speedport Smart 4R Typ A", "010152.5.0.001.1")


def test_destructive_contracts_require_bound_typed_confirmation() -> None:
    """Future destructive actions cannot bypass typed operation binding."""
    contract = ADMIN_ACTION_CONTRACTS["voip_line_set_active"]

    with pytest.raises(ValueError, match="typed confirmation"):
        replace(contract, risk=ManagementRisk.DESTRUCTIVE)
    typed = replace(
        contract,
        risk=ManagementRisk.DESTRUCTIVE,
        confirmation=ManagementConfirmation.TYPED,
        typed_confirmation="DISABLE VOIP LINE",
    )

    assert typed.typed_confirmation == "DISABLE VOIP LINE"


@pytest.mark.parametrize(
    ("method", "kwargs", "endpoint", "payload", "referer"),
    [
        (
            "start_dect_handset_enrollment",
            {},
            "data/DECT.json",
            {"scan_dect": "scan dect phones"},
            DECT_MOBILES_REFERER,
        ),
        (
            "start_dect_repeater_enrollment",
            {},
            "data/DECTRepeater.json",
            {"scan_repeater": "scan dect repeater"},
            DECT_REPEATER_REFERER,
        ),
        (
            "toggle_dect_handset_paging",
            {"handset_id": "handset_2"},
            "data/DECT.json",
            {"ring": "start paging", "id": "handset_2"},
            DECT_MOBILES_REFERER,
        ),
        (
            "set_voip_line_active",
            {"line_id": "line-3", "active": False},
            "data/IPPhoneNumbers.json",
            {"id": "line-3", "no_delete": "keep", "number_status": "inactive"},
            VOIP_REFERER,
        ),
    ],
)
async def test_client_sends_each_action_once_and_allows_missing_ack(
    method: str,
    kwargs: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any],
    referer: str,
) -> None:
    """Exact firmware actions use one mutation POST and readback owns success."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(return_value={})
    authenticate = AsyncMock()
    token = AsyncMock(return_value=None)

    with (
        patch.object(client, "_ensure_authenticated_unlocked", authenticate),
        patch.object(client, "_get_http_token_unlocked", token),
        patch.object(client, "_post_json_unlocked", post),
    ):
        assert await getattr(client, method)(**kwargs) == {}

    authenticate.assert_awaited_once_with()
    token.assert_awaited_once_with(referer)
    post.assert_awaited_once_with(
        endpoint,
        payload,
        authenticated=True,
        referer=referer,
        ensure_auth=False,
        resolve_http_token=False,
    )


@pytest.mark.parametrize(
    "response",
    [
        {"status": "failed"},
        {"result": False},
        {"error": "PRIVATE-ROUTER-DETAIL"},
    ],
)
async def test_client_rejects_explicit_negative_action_reply(
    response: dict[str, Any],
) -> None:
    """An explicit router rejection never becomes a successful action result."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(return_value=response)
    authenticate = AsyncMock()
    token = AsyncMock(return_value=None)

    with (
        patch.object(client, "_ensure_authenticated_unlocked", authenticate),
        patch.object(client, "_get_http_token_unlocked", token),
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportCommandRejectedError),
    ):
        await client.start_dect_handset_enrollment()

    post.assert_awaited_once()


async def test_client_distinguishes_pre_send_and_post_send_failures() -> None:
    """Only a failure after entering the POST boundary is outcome-unknown."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock()
    authenticate = AsyncMock(side_effect=SpeedportAuthenticationError("PRIVATE"))

    with (
        patch.object(client, "_ensure_authenticated_unlocked", authenticate),
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportAuthenticationError),
    ):
        await client.start_dect_handset_enrollment()
    post.assert_not_awaited()

    authenticate.side_effect = None
    token = AsyncMock(return_value=None)
    post.side_effect = SpeedportConnectionError("PRIVATE-AFTER-SEND")
    with (
        patch.object(client, "_ensure_authenticated_unlocked", authenticate),
        patch.object(client, "_get_http_token_unlocked", token),
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportMutationOutcomeUnknownError) as failure,
    ):
        await client.start_dect_handset_enrollment()

    post.assert_awaited_once()
    assert "PRIVATE" not in str(failure.value)


async def test_strict_ephemeral_logout_reports_unconfirmed_cleanup() -> None:
    """Both failed logout forms become one safe observable cleanup error."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    client._session_cleanup_key = b"0" * 16  # noqa: SLF001
    client._login_key = b"0" * 16  # noqa: SLF001
    client._authenticated = True  # noqa: SLF001
    post = AsyncMock(side_effect=SpeedportConnectionError("PRIVATE"))

    with (
        patch.object(client, "_post_json_unlocked", post),
        patch.object(hub_module.asyncio, "sleep", AsyncMock()),
        pytest.raises(SpeedportProtocolError) as failure,
    ):
        await client.logout_ephemeral()

    assert post.await_count == 2
    assert "PRIVATE" not in str(failure.value)
    assert client._session_cleanup_key is None  # noqa: SLF001


async def test_strict_ephemeral_logout_accepts_successful_fallback() -> None:
    """A confirmed fallback logout completes without a false cleanup error."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    client._session_cleanup_key = b"0" * 16  # noqa: SLF001
    post = AsyncMock(
        side_effect=[
            SpeedportConnectionError("PRIVATE"),
            {"status": "ok"},
        ]
    )

    with (
        patch.object(client, "_post_json_unlocked", post),
        patch.object(hub_module.asyncio, "sleep", AsyncMock()),
    ):
        await client.logout_ephemeral()

    assert post.await_count == 2
    assert client._session_cleanup_key is None  # noqa: SLF001


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "unknown"},
        {"status": "ok", "result": "failed"},
        {"status": "ok", "error": "denied"},
    ],
)
async def test_strict_ephemeral_logout_rejects_unconfirmed_responses(
    response: dict[str, str],
) -> None:
    """Empty or unknown logout replies cannot publish session release."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    client._session_cleanup_key = b"0" * 16  # noqa: SLF001
    post = AsyncMock(side_effect=[response, response])

    with (
        patch.object(client, "_post_json_unlocked", post),
        patch(
            "custom_components.speedport_smart.api.client.asyncio.sleep", AsyncMock()
        ),
        pytest.raises(SpeedportProtocolError),
    ):
        await client.logout_ephemeral()

    assert post.await_count == 2
    assert client._session_cleanup_key is None  # noqa: SLF001


async def test_strict_logout_unknown_reply_accepts_confirmed_fallback() -> None:
    """A fallback must provide an explicit positive acknowledgement."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    client._session_cleanup_key = b"0" * 16  # noqa: SLF001
    post = AsyncMock(side_effect=[{}, {"status": "ok"}])

    with (
        patch.object(client, "_post_json_unlocked", post),
        patch(
            "custom_components.speedport_smart.api.client.asyncio.sleep", AsyncMock()
        ),
    ):
        await client.logout_ephemeral()

    assert post.await_count == 2
    assert client._session_cleanup_key is None  # noqa: SLF001


async def test_client_rejects_unsafe_targets_and_truthy_booleans_before_post() -> None:
    """Opaque IDs and Boolean values stay strict at the protocol boundary."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock()

    with patch.object(client, "_post_json_unlocked", post):
        with pytest.raises(SpeedportProtocolError):
            await client.toggle_dect_handset_paging(handset_id="../../admin")
        with pytest.raises(SpeedportProtocolError):
            await client.set_voip_line_active(line_id="line-1", active=1)  # type: ignore[arg-type]

    post.assert_not_awaited()


async def test_dect_target_query_uses_exact_reads_and_filters_private_fields() -> None:
    """Handset action IDs are fresh, bounded, and contain no assignments."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get = AsyncMock(
        side_effect=[
            {
                "adddectdevice": [
                    {
                        "id": "2",
                        "dect_name": "Office",
                        "assigned_number": "PRIVATE-NUMBER",
                    }
                ]
            },
            {"PagingStat2": "1", "private": "PRIVATE-STATUS"},
        ]
    )

    with patch.object(client, "_get_json_with_recovery_unlocked", get):
        result = await client.query_dect_handset_targets()

    assert get.await_args_list == [
        call(
            "data/DECTStation.json",
            authenticated=True,
            referer=DECT_MOBILES_REFERER,
        ),
        call(
            "data/DECTInfo.json",
            authenticated=True,
            referer=DECT_MOBILES_REFERER,
        ),
    ]
    assert result["truncated"] is False
    target = result["targets"][0]
    assert target["target_id"] == "2"
    assert target["reference"] == "2"
    assert target["paging"] is True
    assert target["name"] == "Office"
    assert len(target["target_fingerprint"]) == 64
    assert "PRIVATE" not in repr(result)


async def test_dect_target_query_marks_real_truncation() -> None:
    """Eligible rows beyond the response cap set the truncation marker."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get = AsyncMock(
        side_effect=[
            {"adddectdevice": [{"id": str(index)} for index in range(17)]},
            {f"PagingStat{index}": "0" for index in range(17)},
        ]
    )

    with patch.object(client, "_get_json_with_recovery_unlocked", get):
        result = await client.query_dect_handset_targets()

    assert len(result["targets"]) == 16
    assert result["truncated"] is True


async def test_voip_target_query_proves_ids_without_exposing_numbers() -> None:
    """VoIP mutations use a separate action-safe identity handshake."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get = AsyncMock(
        return_value={
            "addipnumber": [
                {
                    "id": "line-1",
                    "number_status": "ok",
                    "ip_number": "+49 30 123456",
                    "private_note": "PRIVATE-NUMBER",
                },
                {"id": "line-2", "number_status": "inactive"},
            ]
        }
    )

    with patch.object(client, "get_json", get):
        result = await client.query_voip_line_targets()

    get.assert_awaited_once_with(
        "data/IPPhoneNumbers.json",
        authenticated=True,
        referer=VOIP_REFERER,
    )
    assert result["truncated"] is False
    first, second = result["targets"]
    assert first["target_id"] == "line-1"
    assert first["reference"] == "line-1"
    assert first["active"] is True
    assert first["number_suffix"] == "3456"
    assert len(first["target_fingerprint"]) == 64
    assert second["target_id"] == "line-2"
    assert second["reference"] == "line-2"
    assert second["active"] is False
    assert "PRIVATE" not in repr(result)


async def test_voip_preflight_rejects_reused_id_with_changed_fingerprint() -> None:
    """A fresh read must still identify the exact row bound to the token."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    initial = {
        "addipnumber": [
            {"id": "line-1", "number_status": "ok", "ip_number": "+49 123456"}
        ]
    }
    get = AsyncMock(return_value=initial)
    with patch.object(client, "get_json", get):
        targets = await client.query_voip_line_targets()
    fingerprint = targets["targets"][0]["target_fingerprint"]

    with patch.object(client, "get_json", AsyncMock(return_value=initial)):
        assert await client.get_voip_line_active(
            line_id="line-1",
            target_fingerprint=fingerprint,
        )

    changed = {
        "addipnumber": [
            {"id": "line-1", "number_status": "ok", "ip_number": "+49 999999"}
        ]
    }
    with (
        patch.object(client, "get_json", AsyncMock(return_value=changed)),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.get_voip_line_active(
            line_id="line-1",
            target_fingerprint=fingerprint,
        )


async def test_broad_capability_never_advertises_admin_actions(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Broad DECT/telephony names cannot substitute exact endpoint proofs."""
    broad = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "dect": EndpointCapability(
                    "dect",
                    "data/OtherDect.json",
                    authenticated=True,
                    referer=DECT_MOBILES_REFERER,
                ),
                "telephony": EndpointCapability(
                    "telephony",
                    "data/PhoneCalls.json",
                    authenticated=True,
                ),
            }
        ),
    )
    hub = await _ready_hub(hass, mock_speedport_client, broad)

    assert all(
        not item["supported"]
        for item in hub.admin_actions_metadata()
        if item.get("execution_policy") != "maintenance"
    )
    assert all(
        item["preflight_required"] is True
        for item in hub.admin_actions_metadata()
        if item.get("execution_policy") == "maintenance"
    )


async def test_enrollment_is_available_with_empty_inventory_proof(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Exact lifecycle proof is sufficient when no handset/repeater exists yet."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))

    assert hub.admin_action_decision("dect_handset_enroll").available
    assert hub.admin_action_decision("dect_repeater_enroll").available
    assert not hub.admin_action_decision("dect_handset_set_paging").supported


async def test_action_metadata_is_bounded_and_value_free(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Panel metadata carries policy, never a target or router private value."""
    hub = await _ready_hub(
        hass,
        mock_speedport_client,
        _report("dect", "dect_status", "voip_lines"),
    )

    metadata = hub.admin_actions_metadata()

    assert {item["id"] for item in metadata} == set(ADMIN_ACTION_CONTRACTS)
    repeater = next(item for item in metadata if item["id"] == "dect_repeater_enroll")
    assert repeater["prerequisite"] == "dect_repeater_requirements"
    assert repeater["prerequisite_confirmation_required"] is True
    assert repeater["typed_confirmation"] is None
    paging = next(item for item in metadata if item["id"] == "dect_handset_set_paging")
    assert paging["target_query"] == "dect_handset_targets"
    assert paging["target_token_ttl_seconds"] == 60
    assert "target_id" not in repr(metadata).casefold()
    assert "dect_repeater_requirements" in repr(metadata)
    assert hub.get("management.access.generation") == 1


async def test_target_grant_is_action_bound_single_use_and_expires(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Tokens cannot cross actions, replay, or pass the exact expiry boundary."""
    hub = await _ready_hub(
        hass,
        mock_speedport_client,
        _report("dect", "dect_status", "voip_lines"),
    )
    voip = ADMIN_ACTION_CONTRACTS["voip_line_set_active"]
    paging = ADMIN_ACTION_CONTRACTS["dect_handset_set_paging"]
    token = _issue_target_token(hub, voip.action, "line-1")

    with pytest.raises(AdminActionUnavailableError):
        hub._resolve_admin_action_target(  # noqa: SLF001
            paging,
            {"target_token": token, "enabled": True},
            now=100.0,
            requester=_REQUESTER,
        )
    with pytest.raises(AdminActionUnavailableError):
        hub._resolve_admin_action_target(  # noqa: SLF001
            voip,
            {"target_token": token, "active": True},
            now=100.0,
            requester=_REQUESTER,
        )

    token = _issue_target_token(hub, voip.action, "line-1")
    resolved = hub._resolve_admin_action_target(  # noqa: SLF001
        voip,
        {"target_token": token, "active": True},
        now=100.0,
        requester=_REQUESTER,
    )
    assert resolved == {
        "active": True,
        "line_id": "line-1",
        "target_fingerprint": "a" * 64,
    }
    with pytest.raises(AdminActionUnavailableError):
        hub._resolve_admin_action_target(  # noqa: SLF001
            voip,
            {"target_token": token, "active": True},
            now=100.0,
            requester=_REQUESTER,
        )

    expired = _issue_target_token(hub, voip.action, "line-2")
    grant = hub._admin_action_target_grants[expired]  # noqa: SLF001
    hub._admin_action_target_grants[expired] = replace(  # noqa: SLF001
        grant,
        expires_at=100.0,
    )
    with pytest.raises(AdminActionUnavailableError):
        hub._resolve_admin_action_target(  # noqa: SLF001
            voip,
            {"target_token": expired, "active": True},
            now=100.0,
            requester=_REQUESTER,
        )


async def test_management_generation_change_clears_target_grants(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Availability generation changes invalidate all prior target authority."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    token = _issue_target_token(hub, "voip_line_set_active", "line-1")
    generation = hub.get("management.access.generation")

    hub._set_management_access("unavailable")  # noqa: SLF001

    assert hub.get("management.access.generation") == generation + 1
    assert token not in hub._admin_action_target_grants  # noqa: SLF001


async def test_target_grant_issuance_is_atomic_and_bounded(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Malformed or oversized router rows leave no partially issued authority."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    contract = ADMIN_ACTION_CONTRACTS["voip_line_set_active"]
    existing = _issue_target_token(hub, contract.action, "line-existing")
    original = dict(hub._admin_action_target_grants)  # noqa: SLF001
    malformed = {
        "targets": [
            {
                "target_id": "line-1",
                "target_fingerprint": "b" * 64,
                "reference": "line-1",
                "active": True,
            },
            {"target_id": "../unsafe", "target_fingerprint": "c" * 64},
        ],
        "truncated": False,
    }

    with pytest.raises(AdminActionUnavailableError):
        hub._issue_admin_action_targets(  # noqa: SLF001
            contract, malformed, requester=_REQUESTER
        )

    assert hub._admin_action_target_grants == original  # noqa: SLF001
    assert existing in original
    oversized = {
        "targets": [
            {
                "target_id": f"line-{index}",
                "target_fingerprint": "d" * 64,
                "reference": f"line-{index}",
                "active": True,
            }
            for index in range(33)
        ],
        "truncated": True,
    }
    with pytest.raises(AdminActionUnavailableError):
        hub._issue_admin_action_targets(  # noqa: SLF001
            contract, oversized, requester=_REQUESTER
        )
    assert hub._admin_action_target_grants == original  # noqa: SLF001


async def test_target_token_collision_fails_closed_without_overwrite(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Bounded token generation never overwrites another action's grant."""
    hub = await _ready_hub(
        hass,
        mock_speedport_client,
        _report("dect", "dect_status", "voip_lines"),
    )
    with patch.object(hub_module.secrets, "token_hex", return_value="a" * 32):
        handset = _issue_target_token(
            hub,
            "dect_handset_set_paging",
            "handset-1",
        )
        with pytest.raises(AdminActionUnavailableError):
            _issue_target_token(hub, "voip_line_set_active", "line-1")

    assert handset == "a" * 32
    assert set(hub._admin_action_target_grants) == {handset}  # noqa: SLF001


async def test_target_query_replaces_ids_and_fingerprints_with_tokens(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Only a masked label and short-lived authority cross the WebSocket seam."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.query_voip_line_targets.return_value = {
        "targets": [
            {
                "target_id": "line-1",
                "target_fingerprint": "a" * 64,
                "reference": "line-1",
                "number_suffix": "3456",
                "active": True,
            }
        ],
        "truncated": False,
    }

    result = await hub.async_query_voip_line_targets(requester=_REQUESTER)

    assert result["targets"][0]["number_suffix"] == "3456"
    assert result["targets"][0]["reference"] == "line-1"
    assert result["targets"][0]["active"] is True
    assert len(result["targets"][0]["target_token"]) == 32
    assert "target_id" not in repr(result)
    assert "fingerprint" not in repr(result)
    assert "line-1" not in repr(hub.data)
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


async def test_concurrent_target_queries_serialize_and_share_rate_limit(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Concurrent private work cannot bypass the single session owner or cadence."""
    hub = await _ready_hub(
        hass,
        mock_speedport_client,
        _report("dect", "dect_status", "voip_lines"),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_targets() -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"targets": [], "truncated": False}

    mock_speedport_client.query_dect_handset_targets.side_effect = _slow_targets
    first = asyncio.create_task(
        hub.async_query_dect_handset_targets(requester=_REQUESTER)
    )
    await started.wait()
    second = asyncio.create_task(
        hub.async_query_voip_line_targets(requester=_REQUESTER)
    )
    await asyncio.sleep(0)

    mock_speedport_client.query_voip_line_targets.assert_not_awaited()
    release.set()
    assert await first == {"targets": [], "truncated": False}
    with pytest.raises(AdminQueryRateLimitError):
        await second
    mock_speedport_client.query_voip_line_targets.assert_not_awaited()


async def test_scan_requires_false_to_true_and_one_mutation(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Enrollment succeeds only after an observed lifecycle transition."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))
    mock_speedport_client.get_dect_scan_active.side_effect = [False, False, True]
    mock_speedport_client.start_dect_handset_enrollment.return_value = {}

    with patch.object(hub_module.asyncio, "sleep", AsyncMock()) as sleep:
        result = await hub.async_execute_admin_action(
            "dect_handset_enroll",
            confirmed=True,
        )

    assert result == {"status": "verified", "lifecycle": "scan_active"}
    mock_speedport_client.start_dect_handset_enrollment.assert_awaited_once_with()
    assert mock_speedport_client.get_dect_scan_active.await_count == 3
    sleep.assert_awaited_once_with(1.0)
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


async def test_already_active_scan_is_busy_and_never_writes(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An existing ambiguous enrollment lifecycle rejects with zero writes."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))
    mock_speedport_client.get_dect_scan_active.return_value = True

    with pytest.raises(AdminActionBusyError):
        await hub.async_execute_admin_action(
            "dect_handset_enroll",
            confirmed=True,
        )

    mock_speedport_client.start_dect_handset_enrollment.assert_not_awaited()
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


async def test_explicit_mutation_rejection_is_single_shot_and_typed(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A known rejection after the POST is typed and never retried."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))
    mock_speedport_client.get_dect_scan_active.return_value = False
    mock_speedport_client.start_dect_handset_enrollment.side_effect = (
        SpeedportCommandRejectedError("PRIVATE-REJECTION")
    )

    with pytest.raises(AdminActionRejectedError) as failure:
        await hub.async_execute_admin_action(
            "dect_handset_enroll",
            confirmed=True,
        )

    mock_speedport_client.start_dect_handset_enrollment.assert_awaited_once_with()
    assert mock_speedport_client.get_dect_scan_active.await_count == 1
    assert "PRIVATE" not in str(failure.value)


@pytest.mark.parametrize(
    ("error", "expected_error", "expected_reads"),
    [
        (
            SpeedportAuthenticationError("PRIVATE-BEFORE-SEND"),
            AdminActionUnavailableError,
            1,
        ),
        (
            SpeedportMutationOutcomeUnknownError("PRIVATE-AFTER-SEND"),
            AdminActionOutcomeUnknownError,
            6,
        ),
    ],
)
async def test_mutation_phase_controls_safe_error_classification(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    error: Exception,
    expected_error: type[Exception],
    expected_reads: int,
) -> None:
    """Pre-send failure differs from an indeterminate post-send outcome."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))
    mock_speedport_client.get_dect_scan_active.return_value = False
    mock_speedport_client.start_dect_handset_enrollment.side_effect = error

    with pytest.raises(expected_error) as failure:
        await hub.async_execute_admin_action(
            "dect_handset_enroll",
            confirmed=True,
        )

    mock_speedport_client.start_dect_handset_enrollment.assert_awaited_once()
    assert mock_speedport_client.get_dect_scan_active.await_count == expected_reads
    assert "PRIVATE" not in str(failure.value)


@pytest.mark.parametrize(
    "parameters",
    [
        {
            "pin_is_default": False,
            "full_power_enabled": True,
            "full_eco_disabled": True,
        },
        {
            "pin_is_default": True,
            "full_power_enabled": False,
            "full_eco_disabled": True,
        },
        {
            "pin_is_default": True,
            "full_power_enabled": True,
            "full_eco_disabled": False,
        },
    ],
)
async def test_repeater_requires_every_explicit_prerequisite_before_io(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    parameters: dict[str, bool],
) -> None:
    """Every unobservable repeater prerequisite requires explicit attestation."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect_status"))

    with pytest.raises(AdminActionConfirmationError):
        await hub.async_execute_admin_action(
            "dect_repeater_enroll",
            confirmed=True,
            **parameters,
        )

    mock_speedport_client.get_dect_repeater_scan_active.assert_not_awaited()
    mock_speedport_client.start_dect_repeater_enrollment.assert_not_awaited()
    mock_speedport_client.logout_ephemeral.assert_not_awaited()


@pytest.mark.parametrize(
    "case",
    [
        (
            "dect_handset_set_paging",
            ("dect", "dect_status"),
            "get_dect_handset_paging",
            "toggle_dect_handset_paging",
            "2",
            {"enabled": True},
        ),
        (
            "voip_line_set_active",
            ("voip_lines",),
            "get_voip_line_active",
            "set_voip_line_active",
            "line-2",
            {"active": True},
        ),
    ],
)
async def test_setter_returns_unchanged_without_mutation(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    case: tuple[str, tuple[str, ...], str, str, str, dict[str, Any]],
) -> None:
    """Fresh matching state is a verified no-op and performs zero POSTs."""
    action, families, preflight, mutation, target_id, parameters = case
    hub = await _ready_hub(hass, mock_speedport_client, _report(*families))
    getattr(mock_speedport_client, preflight).return_value = True
    target_token = _issue_target_token(hub, action, target_id, state=True)

    result = await hub.async_execute_admin_action(
        action,
        confirmed=True,
        requester=_REQUESTER,
        target_token=target_token,
        **parameters,
    )

    assert result == {"status": "unchanged", "active": True}
    getattr(mock_speedport_client, mutation).assert_not_awaited()
    mock_speedport_client.logout_ephemeral.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected_calls", "expected_state"),
    [
        (SpeedportConnectionError("transient"), 5, "unavailable"),
        (SpeedportProtocolError("transient"), 5, "unavailable"),
        (SpeedportDecodeError("authentication failed"), 2, "unavailable"),
        (SpeedportAuthenticationError("authentication failed"), 2, "unavailable"),
        (SpeedportInvalidCredentialsError("invalid"), 2, "unavailable"),
        (SpeedportLoginLockedError(retry_after=90), 2, "locked"),
        (SpeedportSessionBusyError("busy"), 2, "blocked"),
        (SpeedportUnsupportedError("unsupported"), 2, "available"),
        (SpeedportCommandRejectedError("rejected"), 2, "available"),
    ],
)
async def test_readback_retries_only_closed_transient_errors(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    error: Exception,
    expected_calls: int,
    expected_state: str,
) -> None:
    """Deterministic/auth/session failures cannot amplify router lockouts."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.get_voip_line_active.side_effect = [
        False,
        error,
        error,
        error,
        error,
    ]
    mock_speedport_client.set_voip_line_active.return_value = {}
    target_token = _issue_target_token(
        hub,
        "voip_line_set_active",
        "line-1",
    )

    with (
        patch.object(hub_module.asyncio, "sleep", AsyncMock()),
        pytest.raises(AdminActionVerificationError),
    ):
        await hub.async_execute_admin_action(
            "voip_line_set_active",
            confirmed=True,
            requester=_REQUESTER,
            target_token=target_token,
            active=True,
        )

    assert mock_speedport_client.get_voip_line_active.await_count == expected_calls
    mock_speedport_client.set_voip_line_active.assert_awaited_once()
    assert hub.get("management.access.state") == expected_state


async def test_unexpected_readback_error_stops_and_is_value_free(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected local errors stop at once and never expose their text."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.get_voip_line_active.side_effect = [
        False,
        RuntimeError("PRIVATE-LOCAL-DETAIL"),
    ]
    target_token = _issue_target_token(
        hub,
        "voip_line_set_active",
        "line-1",
    )

    with pytest.raises(AdminActionVerificationError) as failure:
        await hub.async_execute_admin_action(
            "voip_line_set_active",
            confirmed=True,
            requester=_REQUESTER,
            target_token=target_token,
            active=True,
        )

    assert mock_speedport_client.get_voip_line_active.await_count == 2
    assert "PRIVATE" not in str(failure.value)
    assert "PRIVATE" not in repr(hub.data)
    assert "PRIVATE" not in caplog.text


async def test_unexpected_logout_preserves_verified_result_and_safe_state(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cleanup failure cannot replace success or leak a local exception."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.get_voip_line_active.side_effect = [False, True]
    mock_speedport_client.logout_ephemeral.side_effect = RuntimeError(
        "PRIVATE-LOGOUT-DETAIL"
    )
    target_token = _issue_target_token(
        hub,
        "voip_line_set_active",
        "line-1",
    )

    result = await hub.async_execute_admin_action(
        "voip_line_set_active",
        confirmed=True,
        requester=_REQUESTER,
        target_token=target_token,
        active=True,
    )

    assert result == {"status": "verified", "active": True}
    assert hub.get("management.access.state") == "unavailable"
    assert "PRIVATE" not in repr(hub.data)
    assert "PRIVATE" not in caplog.text


async def test_action_result_is_never_published_into_hub_state(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Ephemeral action targets and results never enter Recorder-facing data."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.get_voip_line_active.side_effect = [False, True]
    before = repr(hub.data)
    target_token = _issue_target_token(
        hub,
        "voip_line_set_active",
        "PRIVATE_SAFE_ID",
    )

    result = await hub.async_execute_admin_action(
        "voip_line_set_active",
        confirmed=True,
        requester=_REQUESTER,
        target_token=target_token,
        active=True,
    )

    assert result == {"status": "verified", "active": True}
    assert repr(hub.data) == before
    assert "PRIVATE_SAFE_ID" not in repr(hub.data)


async def test_typed_confirmation_is_enforced_by_executor(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Typed phrase comparison is bound to the selected immutable contract."""
    base = ADMIN_ACTION_CONTRACTS["voip_line_set_active"]
    typed = replace(
        base,
        risk=ManagementRisk.DESTRUCTIVE,
        confirmation=ManagementConfirmation.TYPED,
        typed_confirmation="DISABLE VOIP LINE",
    )
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))

    with (
        patch.object(hub_module, "get_admin_action_contract", return_value=typed),
        pytest.raises(AdminActionConfirmationError),
    ):
        await hub.async_execute_admin_action(
            typed.action,
            confirmed=True,
            confirmation_text="DELETE DIFFERENT TARGET",
            requester=_REQUESTER,
            target_token="0" * 32,
            active=False,
        )

    mock_speedport_client.get_voip_line_active.assert_not_awaited()

    mock_speedport_client.get_voip_line_active.side_effect = [True, False]
    mock_speedport_client.set_voip_line_active.return_value = {}
    target_token = _issue_target_token(
        hub,
        "voip_line_set_active",
        "line-1",
        state=True,
    )
    with patch.object(hub_module, "get_admin_action_contract", return_value=typed):
        result = await hub.async_execute_admin_action(
            typed.action,
            confirmed=True,
            confirmation_text="DISABLE VOIP LINE",
            requester=_REQUESTER,
            target_token=target_token,
            active=False,
        )

    assert result == {"status": "verified", "active": False}
    mock_speedport_client.set_voip_line_active.assert_awaited_once_with(
        line_id="line-1",
        active=False,
    )


@pytest.mark.parametrize(
    ("handler", "valid", "invalid"),
    [
        (
            websocket_dect_handset_enroll,
            {
                "id": 1,
                "type": PANEL_DECT_HANDSET_ENROLL_WS_TYPE,
                "entry_id": "entry-1",
                "confirmed": True,
            },
            {"confirmed": False},
        ),
        (
            websocket_dect_repeater_enroll,
            {
                "id": 1,
                "type": PANEL_DECT_REPEATER_ENROLL_WS_TYPE,
                "entry_id": "entry-1",
                "confirmed": True,
                "pin_is_default": True,
                "full_power_enabled": True,
                "full_eco_disabled": True,
            },
            {"pin_is_default": False},
        ),
        (
            websocket_dect_handset_set_paging,
            {
                "id": 1,
                "type": PANEL_DECT_HANDSET_SET_PAGING_WS_TYPE,
                "entry_id": "entry-1",
                "confirmed": True,
                "target_token": "0" * 32,
                "enabled": True,
            },
            {"target_token": "../unsafe"},
        ),
        (
            websocket_voip_line_set_active,
            {
                "id": 1,
                "type": PANEL_VOIP_LINE_SET_ACTIVE_WS_TYPE,
                "entry_id": "entry-1",
                "confirmed": True,
                "target_token": "1" * 32,
                "active": False,
            },
            {"active": 0},
        ),
    ],
)
def test_action_websocket_schemas_are_strict(
    handler: Any,
    valid: dict[str, Any],
    invalid: dict[str, Any],
) -> None:
    """WebSocket schemas reject missing affirmation and crafted primitives."""
    schema = handler._ws_schema  # noqa: SLF001

    assert schema(valid) == valid
    with pytest.raises(vol.Invalid):
        schema({**valid, **invalid})
    with pytest.raises(vol.Invalid):
        schema({**valid, "unexpected": "PRIVATE"})


def test_action_websocket_requires_admin_before_hub_resolution() -> None:
    """A non-admin cannot resolve or invoke any action hub."""
    hass = MagicMock()
    connection = MagicMock()
    connection.user.id = "user-1"
    connection.refresh_token_id = _REQUESTER[1]
    connection.user.is_admin = False
    msg = {
        "id": 1,
        "type": PANEL_DECT_HANDSET_ENROLL_WS_TYPE,
        "entry_id": "entry-1",
        "confirmed": True,
    }

    with pytest.raises(Unauthorized):
        websocket_dect_handset_enroll(hass, connection, msg)

    hass.config_entries.async_get_entry.assert_not_called()


async def test_voip_target_websocket_returns_ephemeral_envelope() -> None:
    """The action-safe target query uses the private versioned response only."""
    result = {
        "targets": [
            {
                "target_token": "1" * 32,
                "reference": "line-1",
                "active": True,
            }
        ],
        "truncated": False,
    }
    hub = SimpleNamespace(async_query_voip_line_targets=AsyncMock(return_value=result))
    entry = SimpleNamespace(
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = MagicMock()
    connection = MagicMock()
    connection.user.id = _REQUESTER[0]
    connection.refresh_token_id = _REQUESTER[1]
    msg = {
        "id": 9,
        "type": PANEL_VOIP_LINE_TARGETS_WS_TYPE,
        "entry_id": "entry-1",
    }

    handler = websocket_voip_line_targets.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await handler(hass, connection, msg)

    connection.send_result.assert_called_once_with(
        9,
        {"schema_version": 1, "query": "voip_line_targets", "result": result},
    )
    connection.send_error.assert_not_called()
    hub.async_query_voip_line_targets.assert_awaited_once_with(requester=_REQUESTER)


async def test_successful_action_refreshes_and_publishes_cached_family(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Verified actions refresh cached state before returning their result."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    mock_speedport_client.get_voip_line_active.side_effect = [False, True]
    mock_speedport_client.set_voip_line_active.return_value = {}
    token = _issue_target_token(hub, "voip_line_set_active", "line-1")
    refreshed = {
        "telephony": {
            "numbers": [{"id": "line-1", "enabled": True}],
        }
    }
    fetch = AsyncMock(return_value=refreshed)
    coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.NORMAL, coordinator)

    with patch.object(hub, "_async_fetch_families", fetch):
        result = await hub.async_execute_admin_action(
            "voip_line_set_active",
            confirmed=True,
            requester=_REQUESTER,
            target_token=token,
            active=True,
        )

    assert result == {"status": "verified", "active": True}
    fetch.assert_awaited_once_with(
        ("voip_lines",),
        propagate_errors=True,
        release_authenticated_session=False,
        update_management_access=False,
    )
    assert hub.get("telephony.numbers") == (
        MappingProxyType({"id": "line-1", "enabled": True}),
    )
    snapshot = coordinator.async_set_updated_data.call_args.args[0]
    assert snapshot.data["telephony"]["numbers"] == hub.get("telephony.numbers")


async def test_action_cache_refresh_failure_invalidates_without_replacing_result(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A failed follow-up cache refresh clears stale data but preserves success."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("voip_lines"))
    previous = {
        "telephony": {
            "numbers": [{"id": "line-1", "enabled": False}],
        }
    }
    hub._family_data["voip_lines"] = previous  # noqa: SLF001
    hub._merge_data(previous)  # noqa: SLF001
    mock_speedport_client.get_voip_line_active.side_effect = [False, True]
    mock_speedport_client.set_voip_line_active.return_value = {}
    token = _issue_target_token(hub, "voip_line_set_active", "line-1")

    with patch.object(
        hub,
        "_async_fetch_families",
        AsyncMock(side_effect=SpeedportConnectionError("PRIVATE-REFRESH")),
    ):
        result = await hub.async_execute_admin_action(
            "voip_line_set_active",
            confirmed=True,
            requester=_REQUESTER,
            target_token=token,
            active=True,
        )

    assert result == {"status": "verified", "active": True}
    assert hub.get("telephony.numbers") is None
    assert hub.get("management.access.state") == "unavailable"


async def test_action_websocket_sends_value_free_success_envelope() -> None:
    """Action output identifies the operation but never echoes its target."""
    hub = SimpleNamespace(
        async_execute_admin_action=AsyncMock(
            return_value={"status": "verified", "active": True}
        )
    )
    entry = SimpleNamespace(
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = MagicMock()
    connection = MagicMock()
    connection.user.id = "user-1"
    connection.refresh_token_id = _REQUESTER[1]
    msg = {
        "id": 10,
        "type": PANEL_VOIP_LINE_SET_ACTIVE_WS_TYPE,
        "entry_id": "entry-1",
        "confirmed": True,
        "target_token": "1" * 32,
        "active": True,
    }

    handler = websocket_voip_line_set_active.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await handler(hass, connection, msg)

    response = connection.send_result.call_args.args[1]
    assert response == {
        "schema_version": 1,
        "action": "voip_line_set_active",
        "result": {"status": "verified", "active": True},
    }
    assert "target_token" not in repr(response)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AdminActionRateLimitError(1.2), "action_rate_limited"),
        (AdminActionConfirmationError("PRIVATE"), "confirmation_required"),
        (AdminActionBusyError("PRIVATE"), "action_busy"),
        (AdminActionRejectedError("PRIVATE"), "action_rejected"),
        (AdminActionUnavailableError("PRIVATE"), "action_unavailable"),
        (AdminActionOutcomeUnknownError("PRIVATE"), "action_outcome_unknown"),
        (AdminActionVerificationError("PRIVATE"), "action_verification_failed"),
    ],
)
async def test_action_websocket_errors_are_typed_and_value_free(
    error: Exception,
    code: str,
) -> None:
    """Action failures expose only a fixed code/message, never exception details."""
    connection = MagicMock()
    response = AsyncMock(side_effect=error)()

    await _send_admin_action_result(
        connection,
        {"id": 11},
        "voip_line_set_active",
        response,
    )

    assert connection.send_error.call_args.args[1] == code
    assert "PRIVATE" not in repr(connection.send_error.call_args)
    connection.send_result.assert_not_called()


async def test_action_target_query_unexpected_cleanup_is_value_free(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Target query cleanup also preserves output behind a safe diagnostic."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect", "dect_status"))
    mock_speedport_client.query_dect_handset_targets.return_value = {
        "targets": [
            {
                "target_id": "handset-1",
                "target_fingerprint": "a" * 64,
                "reference": "handset-1",
                "paging": False,
            }
        ],
        "truncated": False,
    }
    mock_speedport_client.logout_ephemeral.side_effect = RuntimeError("PRIVATE-LOGOUT")

    with pytest.raises(AdminActionUnavailableError):
        await hub.async_query_dect_handset_targets(requester=_REQUESTER)

    assert hub.get("management.access.state") == "unavailable"
    assert "PRIVATE" not in caplog.text
    assert "PRIVATE" not in repr(hub.data)


async def test_empty_action_target_query_cleanup_failure_is_unavailable(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An empty target list cannot hide a failed ephemeral-session cleanup."""
    hub = await _ready_hub(hass, mock_speedport_client, _report("dect", "dect_status"))
    mock_speedport_client.query_dect_handset_targets.return_value = {
        "targets": [],
        "truncated": False,
    }
    mock_speedport_client.logout_ephemeral.side_effect = RuntimeError("PRIVATE-LOGOUT")

    with pytest.raises(AdminActionUnavailableError):
        await hub.async_query_dect_handset_targets(requester=_REQUESTER)

    mock_speedport_client.query_dect_handset_targets.assert_awaited_once_with()
    mock_speedport_client.logout_ephemeral.assert_awaited_once_with()
    assert hub.get("management.access.state") == "unavailable"
    assert not hub._admin_action_target_grants  # noqa: SLF001


async def test_mismatched_referer_keeps_action_unavailable(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An endpoint match without its exact authenticated referer fails closed."""
    wrong = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "voip_lines": EndpointCapability(
                    "voip_lines",
                    "data/IPPhoneNumbers.json",
                    authenticated=True,
                    referer="html/content/index.html",
                )
            }
        ),
    )
    hub = await _ready_hub(hass, mock_speedport_client, wrong)

    with pytest.raises(AdminActionUnavailableError):
        await hub.async_execute_admin_action(
            "voip_line_set_active",
            confirmed=True,
            target_token="0" * 32,
            active=True,
        )

    mock_speedport_client.set_voip_line_active.assert_not_awaited()
