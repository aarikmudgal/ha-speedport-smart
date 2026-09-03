"""Offline proof of the receiver identity prerequisite's fixed private read."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
)


@pytest.mark.parametrize("setting", ["receiver_led_mode", "receiver_bonding"])
async def test_mode_only_response_gets_fresh_firmware_identity(setting: str) -> None:
    """Only identity joins the Mode response; hidden credentials never join it."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    mode = {"ex5g_led_mode": "1", "use_bonding": "1", "easy_support_deactive": "1"}
    identity = {
        "ex5g_serial_number": "TEST-RECEIVER",
        "ex5g_model_name": ["TEST-MODEL", "TEST-MODEL"],
        "ex5g_led_mode": "2",
        "use_bonding": "0",
        "ex5g_imsi": "PRIVATE-SIM",
    }
    with (
        patch.object(
            client, "get_json", AsyncMock(side_effect=[mode, identity])
        ) as get,
        patch.object(client, "_post_json_unlocked", AsyncMock()) as post,
    ):
        raw = await client.read_configuration(setting)
    assert raw == {
        **mode,
        "ex5g_serial_number": "TEST-RECEIVER",
        "ex5g_model_name": "TEST-MODEL",
    }
    assert "PRIVATE-SIM" not in repr(raw)
    assert get.await_count == 2
    get.assert_awaited_with(
        "data/LTE.json",
        authenticated=True,
        referer="html/content/internet/lte_firmware.html",
    )
    values = resolve_settings_contract(setting).read(raw)
    assert values == (
        {"ex5g_led_mode": "1"}
        if setting == "receiver_led_mode"
        else {"use_bonding": True}
    )
    post.assert_not_awaited()


@pytest.mark.parametrize(
    ("mode", "identity"),
    [
        ({}, {}),
        ({}, {"ex5g_serial_number": "SERIAL"}),
        ({}, {"ex5g_serial_number": "", "ex5g_model_name": "MODEL"}),
        (
            {"ex5g_model_name": "OTHER"},
            {"ex5g_serial_number": "SERIAL", "ex5g_model_name": "MODEL"},
        ),
        (
            {"ex5g_serial_number": "OTHER"},
            {"ex5g_serial_number": "SERIAL", "ex5g_model_name": "MODEL"},
        ),
        ({}, {"ex5g_serial_number": ["ONE", "TWO"], "ex5g_model_name": "MODEL"}),
    ],
)
async def test_missing_or_conflicting_identity_rejects_without_write(
    mode: dict[str, Any], identity: dict[str, Any]
) -> None:
    """Partial/mismatched receiver observations cannot mint a valid settings read."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with (
        patch.object(
            client,
            "get_json",
            AsyncMock(side_effect=[{**mode, "ex5g_led_mode": "1"}, identity]),
        ),
        patch.object(client, "_post_json_unlocked", AsyncMock()) as post,
        pytest.raises(ConfigurationError),
    ):
        await client.read_configuration("receiver_led_mode")
    post.assert_not_awaited()


async def test_complete_mode_identity_requires_no_supplement() -> None:
    """Already complete private reads keep their existing single-query behavior."""
    raw = {
        "ex5g_led_mode": "1",
        "ex5g_serial_number": "SERIAL",
        "ex5g_model_name": "MODEL",
    }
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(client, "get_json", AsyncMock(return_value=raw)) as get:
        assert await client.read_configuration("receiver_led_mode") == raw
    get.assert_awaited_once_with(
        "data/LTE.json",
        authenticated=True,
        referer="html/content/internet/lte_mode.html",
    )
