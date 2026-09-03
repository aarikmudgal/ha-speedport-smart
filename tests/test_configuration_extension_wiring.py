"""Offline coverage for extended family registration and private read routing."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    settings_contracts,
)
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
    target_settings_ids,
    target_settings_limit,
    target_settings_read_pairs,
)


def test_every_registered_editor_has_a_structured_dashboard_home() -> None:
    """New backend forms cannot disappear from the hierarchical feature view."""
    source = (
        Path(__file__).parents[1]
        / "custom_components/speedport_smart/frontend/speedport-smart-panel.js"
    ).read_text()
    links = source.split("export const SETTINGS_FEATURE_LINKS =", 1)[1].split(
        "const MAINTENANCE_FEATURE_LINKS", 1
    )[0]
    linked = {
        identifier
        for values in re.findall(r"ids:\s*\[([^]]+)\]", links)
        for identifier in re.findall(r'"([a-z0-9_]+)"', values)
    }
    registered = set(settings_contracts()) | target_settings_ids()
    assert registered == linked


@pytest.mark.parametrize("identifier", sorted(target_settings_ids()))
def test_every_target_family_requires_and_binds_an_exact_target(
    identifier: str,
) -> None:
    """No target family can silently become a scalar or cross-row approval."""
    with pytest.raises(ConfigurationError, match="settings_target_required"):
        resolve_settings_contract(identifier)


def test_nested_target_limits_cover_native_capacity() -> None:
    """Large inventories remain bounded without silently hiding valid rows."""
    assert target_settings_limit("port_forward_range_edit") == 2048
    assert target_settings_limit("port_forward_range_delete") == 2048
    assert target_settings_limit("telephony_phonebook_contact") == 5000


def test_powerline_read_source_is_not_the_mutation_endpoint() -> None:
    """Target discovery uses DeviceList, never probes PWLineDevice as a read."""
    contract = resolve_settings_contract("powerline_rename", "00:11:22:33:44:55")
    assert contract.target_scope == "00:11:22:33:44:55"
    assert contract.endpoint == "data/PWLineDevice.json"
    assert contract.read_endpoint == "data/DeviceList.json"
    assert (contract.read_endpoint, contract.referer) in target_settings_read_pairs()


@pytest.mark.parametrize(
    ("setting_id", "namespace", "endpoint", "referer"),
    [
        (
            "storage_media_reindex",
            "index",
            "data/NASFileCount.json",
            "html/content/network/nas_mediareplay.html",
        ),
        (
            "telephony_handset_phonebook",
            "phonebooks",
            "data/PhoneOnlbuch.json",
            "html/content/phone/phone_book_assign.html",
        ),
        (
            "receiver_bonding",
            "network_prerequisites",
            "data/EasySupport.json",
            "html/content/config/easy_support.html",
        ),
    ],
)
async def test_private_prerequisites_have_fixed_sources(
    setting_id: str, namespace: str, endpoint: str, referer: str
) -> None:
    """Each joined read is allowlisted, private and nonmutating."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    target = "0" if setting_id == "telephony_handset_phonebook" else None
    with (
        patch.object(
            client,
            "get_json",
            AsyncMock(
                side_effect=[
                    {
                        "ex5g_serial_number": "receiver-test",
                        "ex5g_model_name": "receiver-model",
                    }
                    if setting_id == "receiver_bonding"
                    else {},
                    {
                        "easy_support_deactive": "1",
                        "unrelated_secret": "DO-NOT-PROJECT",
                    },
                ]
            ),
        ) as get,
        patch.object(client, "_post_ephemeral_action", AsyncMock()) as post,
    ):
        result = await client.read_configuration(setting_id, target)
    assert get.await_count == 2
    call = get.await_args_list[1]
    assert call.args == (endpoint,)
    assert call.kwargs["referer"] == referer
    assert call.kwargs["authenticated"] is True
    assert namespace in result
    if setting_id == "receiver_bonding":
        assert result[namespace] == {"easy_support_deactive": "1"}
    post.assert_not_awaited()


async def test_ip_phone_creation_readback_binds_response_identity_before_io() -> None:
    """An allocation response never substitutes for independently read state."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(
        client,
        "read_configuration",
        AsyncMock(
            return_value={
                "addipclient": [],
            }
        ),
    ) as read:
        result = await client.read_created_ip_phone_configuration(
            {"addipclient": []}, {"newestID": "2"}
        )
        assert result["_created_ip_phone_id"] == "2"
        read.assert_awaited_once_with("telephony_ip_phone_create")
        read.reset_mock()
        for response in ({}, {"newestID": "../"}, None):
            with pytest.raises(ConfigurationError, match="action_outcome_unknown"):
                await client.read_created_ip_phone_configuration({}, response)
        read.assert_not_awaited()
