"""Regression tests for guarded destructive administrator actions."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState

from custom_components.speedport_smart import hub as hub_module
from custom_components.speedport_smart import panel_queries
from custom_components.speedport_smart.admin_actions import (
    ADMIN_ACTION_CONTRACTS,
    DECT_MOBILES_REFERER,
    DECT_REPEATER_REFERER,
    IP_PBX_REFERER,
    NAS_SHARE_REFERER,
    PHONEBOOK_REFERER,
    VOIP_REFERER,
)
from custom_components.speedport_smart.api import (
    SpeedportClient,
    SpeedportCommandRejectedError,
    SpeedportMutationOutcomeUnknownError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.hub import (
    AdminActionConfirmationError,
    AdminActionUnavailableError,
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

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


_ACTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "dect_handset_disconnect",
        "data/DECT.json",
        DECT_MOBILES_REFERER,
        "DISCONNECT DECT HANDSET",
    ),
    (
        "dect_repeater_disconnect",
        "data/DECTRepeater.json",
        DECT_REPEATER_REFERER,
        "DISCONNECT DECT REPEATER",
    ),
    (
        "voip_provider_delete",
        "data/IPPhone.json",
        VOIP_REFERER,
        "DELETE VOIP PROVIDER",
    ),
    (
        "voip_line_delete",
        "data/IPPhoneNumbers.json",
        VOIP_REFERER,
        "DELETE VOIP NUMBER",
    ),
    (
        "ip_pbx_client_delete",
        "data/IPClients.json",
        IP_PBX_REFERER,
        "DELETE IP PBX CLIENT",
    ),
    (
        "phonebook_entry_delete",
        "data/PhoneBook.json",
        PHONEBOOK_REFERER,
        "DELETE PHONEBOOK ENTRY",
    ),
    (
        "nas_share_delete",
        "data/NASFolder.json",
        NAS_SHARE_REFERER,
        "DELETE NAS SHARE",
    ),
)
_REQUESTER = ("user-1", "request-1")

_MUTATIONS: tuple[
    tuple[str, dict[str, Any], str, dict[str, Any], str, dict[str, Any]], ...
] = (
    (
        "disconnect_dect_handset",
        {"handset_id": "hs_1"},
        "data/DECT.json",
        {"disconnect": "disconnect", "id": "hs_1"},
        DECT_MOBILES_REFERER,
        {},
    ),
    (
        "disconnect_dect_repeater",
        {"repeater_id": "rp_1"},
        "data/DECTRepeater.json",
        {"disconnect": "disconnect", "id": "rp_1"},
        DECT_REPEATER_REFERER,
        {},
    ),
    (
        "delete_voip_provider",
        {"provider_id": "provider_1"},
        "data/IPPhone.json",
        {"id": "provider_1", "deleteEntry": "delete"},
        VOIP_REFERER,
        {},
    ),
    (
        "delete_voip_line",
        {"line_id": "line_1"},
        "data/IPPhoneNumbers.json",
        {"id": "line_1", "deleteEntry": "delete"},
        VOIP_REFERER,
        {"status": "ok"},
    ),
    (
        "delete_ip_pbx_client",
        {"client_id": "client_1"},
        "data/IPClients.json",
        {"delete": "delete", "id": "client_1"},
        IP_PBX_REFERER,
        {},
    ),
    (
        "delete_phonebook_entry",
        {"contact_id": "contact_1", "phonebook_id": 2},
        "data/PhoneBook.json",
        {"id": "contact_1", "obnr": 2, "deleteEntry": "delete"},
        PHONEBOOK_REFERER,
        {},
    ),
    (
        "delete_nas_share",
        {"share_id": "share_1"},
        "data/NASFolder.json",
        {"sid": "share_1", "deleteEntry": "delete"},
        NAS_SHARE_REFERER,
        {},
    ),
)


def _report_for(action: str) -> CapabilityReport:
    """Build the exact endpoint proof required by one action."""
    contract = ADMIN_ACTION_CONTRACTS[action]
    return CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                proof.family: EndpointCapability(
                    proof.family,
                    proof.endpoint,
                    authenticated=True,
                    referer=proof.referer,
                )
                for proof in contract.capability_proofs
            }
        ),
    )


async def _ready_hub(
    hass: HomeAssistant,
    client: MagicMock,
    action: str,
) -> SpeedportHub:
    """Return a management-ready hub for one destructive action."""
    report = _report_for(action)
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


def _raw_target(action: str, target_id: str = "private_target") -> dict[str, Any]:
    """Return one valid internal target row for an action contract."""
    row: dict[str, Any] = {
        "target_id": target_id,
        "target_fingerprint": "a" * 64,
        "reference": target_id,
    }
    if action == "dect_handset_disconnect":
        row["name"] = "Office"
    elif action == "voip_provider_delete":
        row["provider_code"] = 4
    elif action == "voip_line_delete":
        row.update(active=True, number_suffix="4567")
    elif action == "ip_pbx_client_delete":
        row.update(name="Desk phone", status="registered")
    elif action == "phonebook_entry_delete":
        row.update(phonebook_id=2, display_name="Private Contact")
    elif action == "nas_share_delete":
        row["name"] = "Media"
    return row


@pytest.mark.parametrize(("action", "endpoint", "referer", "phrase"), _ACTIONS)
def test_destructive_contracts_are_exact(
    action: str,
    endpoint: str,
    referer: str,
    phrase: str,
) -> None:
    """Each delete contract binds firmware, transport, confirmation, and result."""
    contract = ADMIN_ACTION_CONTRACTS[action]

    assert contract.endpoint == endpoint
    assert contract.referer == referer
    assert contract.risk is ManagementRisk.DESTRUCTIVE
    assert contract.confirmation is ManagementConfirmation.TYPED
    assert contract.typed_confirmation == phrase
    assert contract.deletion_result is True
    assert contract.target_token_ttl_seconds == 60
    assert set(contract.input_specs) == {"target_token"}
    assert contract.expected_value is False
    assert contract.supports("Speedport Smart 4R Typ A", "010152.5.0.001.0")
    assert not contract.supports("Speedport Smart 4R Typ A", "010152.5.0.001.1")


@pytest.mark.parametrize(
    ("method", "kwargs", "endpoint", "payload", "referer", "response"),
    _MUTATIONS,
)
async def test_destructive_client_posts_once_with_exact_contract(  # noqa: PLR0917
    method: str,
    kwargs: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any],
    referer: str,
    response: dict[str, Any],
) -> None:
    """Each destructive method emits one reviewed POST and never retries it."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    authenticate = AsyncMock()
    token = AsyncMock(return_value=None)
    post = AsyncMock(return_value=response)

    with (
        patch.object(client, "_ensure_authenticated_unlocked", authenticate),
        patch.object(client, "_get_http_token_unlocked", token),
        patch.object(client, "_post_json_unlocked", post),
    ):
        assert await getattr(client, method)(**kwargs) == response

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
    ("method", "kwargs", "response"),
    [
        (method, kwargs, {"error": "PRIVATE"})
        for method, kwargs, _endpoint, _payload, _referer, _response in _MUTATIONS
    ],
)
async def test_destructive_client_rejects_unproven_or_negative_ack(
    method: str,
    kwargs: dict[str, Any],
    response: dict[str, Any],
) -> None:
    """Exact-positive and explicit-negative policies both fail closed."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(return_value=response)

    with (
        patch.object(client, "_ensure_authenticated_unlocked", AsyncMock()),
        patch.object(client, "_get_http_token_unlocked", AsyncMock(return_value=None)),
        patch.object(client, "_post_json_unlocked", post),
        pytest.raises(SpeedportCommandRejectedError) as failure,
    ):
        await getattr(client, method)(**kwargs)

    post.assert_awaited_once()
    assert "PRIVATE" not in str(failure.value)


async def test_exact_ack_action_rejects_missing_ack_as_unknown() -> None:
    """An absent exact acknowledgement is neither success nor explicit rejection."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    with (
        patch.object(client, "_ensure_authenticated_unlocked", AsyncMock()),
        patch.object(client, "_get_http_token_unlocked", AsyncMock(return_value=None)),
        patch.object(client, "_post_json_unlocked", AsyncMock(return_value={})),
        pytest.raises(SpeedportMutationOutcomeUnknownError),
    ):
        await client.delete_voip_line(line_id="line_1")


@pytest.mark.parametrize(("action", "_endpoint", "_referer", "phrase"), _ACTIONS)
async def test_destructive_executor_is_single_shot_and_value_free(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    action: str,
    _endpoint: str,
    _referer: str,
    phrase: str,
) -> None:
    """One-use authority permits one POST and only a fresh absence proves success."""
    hub = await _ready_hub(hass, mock_speedport_client, action)
    contract = ADMIN_ACTION_CONTRACTS[action]
    preflight = getattr(mock_speedport_client, contract.preflight_handler)
    mutation = getattr(mock_speedport_client, contract.handler)
    preflight.side_effect = [True, False]
    mutation.return_value = {}
    issued = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {"targets": [_raw_target(action)], "truncated": False},
        requester=_REQUESTER,
    )
    token = issued["targets"][0]["target_token"]

    with patch.object(hub_module.asyncio, "sleep", AsyncMock()):
        result = await hub.async_execute_admin_action(
            action,
            confirmed=True,
            confirmation_text=phrase,
            requester=_REQUESTER,
            target_token=token,
        )

    assert result == {"status": "verified", "deleted": True}
    mutation.assert_awaited_once()
    assert preflight.await_count == 2
    mock_speedport_client.logout_ephemeral.assert_awaited_once()
    assert "private_target" not in repr(result)
    assert "private_target" not in repr(hub.data)


@pytest.mark.parametrize(("action", "_endpoint", "_referer", "phrase"), _ACTIONS)
async def test_destructive_executor_reports_already_absent_without_post(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    action: str,
    _endpoint: str,
    _referer: str,
    phrase: str,
) -> None:
    """A target that vanished after grant issuance is a verified no-op."""
    hub = await _ready_hub(hass, mock_speedport_client, action)
    contract = ADMIN_ACTION_CONTRACTS[action]
    preflight = getattr(mock_speedport_client, contract.preflight_handler)
    mutation = getattr(mock_speedport_client, contract.handler)
    preflight.return_value = False
    issued = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {"targets": [_raw_target(action)], "truncated": False},
        requester=_REQUESTER,
    )

    result = await hub.async_execute_admin_action(
        action,
        confirmed=True,
        confirmation_text=phrase,
        requester=_REQUESTER,
        target_token=issued["targets"][0]["target_token"],
    )

    assert result == {"status": "unchanged", "deleted": True}
    mutation.assert_not_awaited()
    preflight.assert_awaited_once()


@pytest.mark.parametrize(
    ("action", "families"),
    [
        ("dect_handset_disconnect", ("dect", "dect_status")),
        ("voip_provider_delete", ("voip_providers", "voip_lines")),
    ],
)
async def test_destructive_action_refreshes_every_dependent_family(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    action: str,
    families: tuple[str, ...],
) -> None:
    """Deletion refreshes both its direct inventory and dependent cached state."""
    hub = await _ready_hub(hass, mock_speedport_client, action)
    contract = ADMIN_ACTION_CONTRACTS[action]
    preflight = getattr(mock_speedport_client, contract.preflight_handler)
    preflight.side_effect = [True, False]
    getattr(mock_speedport_client, contract.handler).return_value = {}
    issued = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {"targets": [_raw_target(action)], "truncated": False},
        requester=_REQUESTER,
    )
    fetch = AsyncMock(return_value={})

    with patch.object(hub, "_async_fetch_families", fetch):
        result = await hub.async_execute_admin_action(
            action,
            confirmed=True,
            confirmation_text=contract.typed_confirmation,
            requester=_REQUESTER,
            target_token=issued["targets"][0]["target_token"],
        )

    assert result == {"status": "verified", "deleted": True}
    assert fetch.await_args_list == [
        call(
            (family,),
            propagate_errors=True,
            release_authenticated_session=False,
            update_management_access=False,
        )
        for family in families
    ]


async def test_typed_confirmation_rejects_before_router_io(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A wrong destructive phrase consumes no token and performs no router I/O."""
    action = "nas_share_delete"
    hub = await _ready_hub(hass, mock_speedport_client, action)
    contract = ADMIN_ACTION_CONTRACTS[action]
    issued = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {"targets": [_raw_target(action)], "truncated": False},
        requester=_REQUESTER,
    )

    with pytest.raises(AdminActionConfirmationError):
        await hub.async_execute_admin_action(
            action,
            confirmed=True,
            confirmation_text="DELETE SOMETHING ELSE",
            requester=_REQUESTER,
            target_token=issued["targets"][0]["target_token"],
        )

    mock_speedport_client.get_nas_share_present.assert_not_awaited()
    mock_speedport_client.delete_nas_share.assert_not_awaited()
    mock_speedport_client.logout_ephemeral.assert_not_awaited()


async def test_phonebook_grants_bind_multi_field_identity_with_safe_references(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Each grant binds its exact contact and phonebook context."""
    action = "phonebook_entry_delete"
    hub = await _ready_hub(hass, mock_speedport_client, action)
    contract = ADMIN_ACTION_CONTRACTS[action]
    result = hub._issue_admin_action_targets(  # noqa: SLF001
        contract,
        {
            "targets": [
                {
                    **_raw_target(action, f"contact_{phonebook_id}"),
                    "phonebook_id": phonebook_id,
                    "target_fingerprint": str(phonebook_id + 1) * 64,
                }
                for phonebook_id in (0, 1)
            ],
            "truncated": False,
        },
        requester=_REQUESTER,
    )

    assert len(result["targets"]) == 2
    assert "contact_0" in repr(result)
    assert "contact_1" in repr(result)
    assert "fingerprint" not in repr(result)
    resolved = [
        hub._resolve_admin_action_target(  # noqa: SLF001
            contract,
            {"target_token": target["target_token"]},
            now=100.0,
            requester=_REQUESTER,
        )
        for target in result["targets"]
    ]
    assert [item["phonebook_id"] for item in resolved] == [0, 1]
    assert [item["contact_id"] for item in resolved] == ["contact_0", "contact_1"]

    with pytest.raises(AdminActionUnavailableError):
        hub._issue_admin_action_targets(  # noqa: SLF001
            contract,
            {
                "targets": [
                    _raw_target(action, "duplicate"),
                    _raw_target(action, "duplicate"),
                ],
                "truncated": False,
            },
            requester=_REQUESTER,
        )


async def test_phonebook_absence_requires_complete_exact_count() -> None:
    """A partial or duplicate phonebook response can never prove deletion."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        side_effect=[
            {"addbookentry": [], "num_entries": 1},
            {
                "addbookentry": [{"id": "same"}, {"id": "same"}],
                "num_entries": 2,
            },
        ]
    )

    with patch.object(client, "_post_json_unlocked", post):
        with pytest.raises(SpeedportUnsupportedError, match="incomplete"):
            await client.get_phonebook_entry_present(
                contact_id="contact_1",
                target_fingerprint="a" * 64,
                phonebook_id=0,
            )
        with pytest.raises(SpeedportUnsupportedError, match="ambiguous"):
            await client.get_phonebook_entry_present(
                contact_id="same",
                target_fingerprint="a" * 64,
                phonebook_id=0,
            )


async def test_target_collection_truncation_and_malformed_rows_fail_closed() -> None:
    """Oversized and partially decoded lists do not mint deletion authority."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    get = AsyncMock(
        side_effect=[
            {"addipphoneprovider": [{"id": str(index)} for index in range(257)]},
            {"addipphoneprovider": [{"id": "valid"}, "not-a-row"]},
        ]
    )

    with patch.object(client, "get_json", get):
        with pytest.raises(SpeedportUnsupportedError, match="truncated"):
            await client.query_voip_provider_delete_targets()
        with pytest.raises(SpeedportUnsupportedError, match="truncated"):
            await client.query_voip_provider_delete_targets()


async def test_target_queries_project_only_bounded_safe_fields() -> None:
    """Credential-like router fields are excluded from all target projections."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    payloads = (
        (
            client.query_dect_handset_disconnect_targets,
            {
                "adddectdevice": [
                    {"id": "hs1", "dect_name": "Office", "password": "SECRET"}
                ]
            },
            {"target_id", "target_fingerprint", "reference", "name"},
        ),
        (
            client.query_dect_repeater_disconnect_targets,
            {"addrepeater": [{"id": "rp1", "password": "SECRET"}]},
            {"target_id", "target_fingerprint", "reference"},
        ),
        (
            client.query_voip_provider_delete_targets,
            {
                "addipphoneprovider": [
                    {"id": "p1", "isp_selection": "4", "password": "SECRET"}
                ]
            },
            {"target_id", "target_fingerprint", "reference", "provider_code"},
        ),
        (
            client.query_voip_line_delete_targets,
            {
                "addipnumber": [
                    {
                        "id": "l1",
                        "number_status": "ok",
                        "ip_number": "+4912345678",
                        "password": "SECRET",
                    }
                ]
            },
            {
                "target_id",
                "target_fingerprint",
                "reference",
                "active",
                "number_suffix",
            },
        ),
        (
            client.query_ip_pbx_client_delete_targets,
            {
                "addipclient": [
                    {
                        "id": "c1",
                        "ipclient_status": "1",
                        "ipclient_mdevice_name": "Desk",
                        "password": "SECRET",
                    }
                ]
            },
            {"target_id", "target_fingerprint", "reference", "name", "status"},
        ),
        (
            client.query_nas_share_delete_targets,
            {
                "addnasfolder": [
                    {
                        "sid": "s1",
                        "nas_folder_name": "Media",
                        "nas_password": "SECRET",
                    }
                ]
            },
            {"target_id", "target_fingerprint", "reference", "name"},
        ),
    )

    for query, response, expected_fields in payloads:
        with patch.object(client, "get_json", AsyncMock(return_value=response)):
            result = await query()
        assert set(result["targets"][0]) == expected_fields
        assert "SECRET" not in repr(result)

    phonebook_post = AsyncMock(
        return_value={
            "addbookentry": [
                {
                    "id": "contact1",
                    "vorname": "Private",
                    "name": "Contact",
                    "password": "SECRET",
                }
            ],
            "num_entries": 1,
        }
    )
    with patch.object(client, "_post_json_unlocked", phonebook_post):
        phonebook = await client.query_phonebook_entry_delete_targets(phonebook_id=2)
    assert set(phonebook["targets"][0]) == {
        "target_id",
        "target_fingerprint",
        "phonebook_id",
        "reference",
        "display_name",
    }
    assert "SECRET" not in repr(phonebook)


async def test_phonebook_search_projects_free_entry_capacity() -> None:
    """Exact free-entry capacity remains ephemeral in the private query result."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    post = AsyncMock(
        return_value={
            "addbookentry": [],
            "num_entries": 0,
            "free_entry_num": "237",
        }
    )

    with patch.object(client, "_post_json_unlocked", post):
        result = await client.query_phonebook_entries(phonebook_id=0, prefix="")

    assert result["free_entries"] == 237
    post.assert_awaited_once_with(
        "data/PhoneBook.json",
        {"obnr": 0, "search": ""},
        authenticated=True,
        referer=PHONEBOOK_REFERER,
    )


@pytest.mark.parametrize("count", [33, 100, 256, 1000])
async def test_phonebook_delete_targets_are_complete_not_voip_capped(
    count: int,
) -> None:
    """Every contact in the bounded complete inventory remains selectable."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    response = {
        "addbookentry": [
            {"id": str(index), "name": f"Contact {index}"} for index in range(count)
        ],
        "num_entries": count,
    }
    with patch.object(client, "_post_json_unlocked", AsyncMock(return_value=response)):
        result = await client.query_phonebook_entry_delete_targets(phonebook_id=0)
    assert len(result["targets"]) == count
    assert result["truncated"] is False


@pytest.mark.parametrize(
    "response",
    [
        {
            "addbookentry": [{"id": str(index)} for index in range(1001)],
            "num_entries": 1001,
        },
        {"addbookentry": [{"id": "1"}], "num_entries": 2},
        {"num_entries": 0},
        {"status": "ok", "num_entries": 0, "free_entry_num": 99, "addbookentry": None},
    ],
)
async def test_phonebook_delete_refuses_unproven_or_truncated_inventory(
    response: dict[str, Any],
) -> None:
    """Missing rows and mismatched totals cannot become a partial target list."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    with (
        patch.object(client, "_post_json_unlocked", AsyncMock(return_value=response)),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.query_phonebook_entry_delete_targets(phonebook_id=0)


async def test_phonebook_last_contact_absence_uses_real_zero_count_shape() -> None:
    """The firmware omits addbookentry once the local book becomes empty."""
    client = SpeedportClient(MagicMock(), "speedport.ip")
    response = {"status": "ok", "num_entries": "0", "free_entry_num": "100"}
    with patch.object(client, "_post_json_unlocked", AsyncMock(return_value=response)):
        assert await client.query_phonebook_entry_delete_targets(phonebook_id=0) == {
            "targets": [],
            "truncated": False,
        }
        assert (
            await client.get_phonebook_entry_present(
                phonebook_id=0,
                contact_id="1",
                target_fingerprint="a" * 64,
            )
            is False
        )


async def test_only_phonebook_grants_allow_complete_inventory_above_32(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Increase only phonebook capacity; all other action bounds remain unchanged."""
    action = "phonebook_entry_delete"
    hub = await _ready_hub(hass, mock_speedport_client, action)
    targets = [
        {**_raw_target(action), "target_id": str(index), "reference": str(index)}
        for index in range(1000)
    ]
    result = hub._issue_admin_action_targets(  # noqa: SLF001
        ADMIN_ACTION_CONTRACTS[action],
        {"targets": targets, "truncated": False},
        requester=_REQUESTER,
    )
    assert len(result["targets"]) == 1000
    with pytest.raises(AdminActionUnavailableError):
        hub._issue_admin_action_targets(  # noqa: SLF001
            ADMIN_ACTION_CONTRACTS[action],
            {"targets": targets, "truncated": True},
            requester=_REQUESTER,
        )
    with pytest.raises(AdminActionUnavailableError):
        hub._issue_admin_action_targets(  # noqa: SLF001
            ADMIN_ACTION_CONTRACTS["voip_provider_delete"],
            {"targets": targets[:33], "truncated": False},
            requester=_REQUESTER,
        )


@pytest.mark.parametrize(("action", "_endpoint", "_referer", "phrase"), _ACTIONS)
def test_destructive_websocket_schemas_require_exact_phrase(
    action: str,
    _endpoint: str,
    _referer: str,
    phrase: str,
) -> None:
    """Each WebSocket mutation rejects wrong text and unknown fields."""
    handler = getattr(panel_queries, f"websocket_{action}")
    ws_type = getattr(panel_queries, f"PANEL_{action.upper()}_WS_TYPE")
    valid = {
        "id": 1,
        "type": ws_type,
        "entry_id": "entry-1",
        "confirmed": True,
        "confirmation_text": phrase,
        "target_token": "0" * 32,
    }

    assert handler._ws_schema(valid) == valid  # noqa: SLF001
    with pytest.raises(vol.Invalid):
        handler._ws_schema({**valid, "confirmation_text": "WRONG"})  # noqa: SLF001
    with pytest.raises(vol.Invalid):
        handler._ws_schema({**valid, "private_id": "unsafe"})  # noqa: SLF001


async def test_destructive_websocket_forwards_phrase_and_hides_token() -> None:
    """The transport forwards confirmation but never echoes one-use authority."""
    hub = SimpleNamespace(
        async_execute_admin_action=AsyncMock(
            return_value={"status": "verified", "deleted": True}
        )
    )
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
        "id": 19,
        "type": panel_queries.PANEL_NAS_SHARE_DELETE_WS_TYPE,
        "entry_id": "entry-1",
        "confirmed": True,
        "confirmation_text": "DELETE NAS SHARE",
        "target_token": "1" * 32,
    }

    handler = panel_queries.websocket_nas_share_delete.__wrapped__.__wrapped__
    with patch.object(hass.config_entries, "async_get_entry", return_value=entry):
        await handler(hass, connection, msg)

    hub.async_execute_admin_action.assert_awaited_once_with(
        "nas_share_delete",
        confirmed=True,
        confirmation_text="DELETE NAS SHARE",
        requester=_REQUESTER,
        target_token="1" * 32,
    )
    response = connection.send_result.call_args.args[1]
    assert response == {
        "schema_version": 1,
        "action": "nas_share_delete",
        "result": {"status": "verified", "deleted": True},
    }
    assert "11111111111111111111111111111111" not in repr(response)
