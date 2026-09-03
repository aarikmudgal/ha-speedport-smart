"""Offline proof of bounded, administrator-private native IP-information reads."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.api.exceptions import SpeedportProtocolError
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.hub import AdminQueryRateLimitError, SpeedportHub
from custom_components.speedport_smart.ip_information import read_ip_information
from custom_components.speedport_smart.panel_queries import (
    PANEL_IP_INFORMATION_WS_TYPE,
    websocket_ip_information,
)


def _raw() -> dict[str, Any]:
    return {
        "public_ip_v4": "192.0.2.1",
        "gateway_ip_v4": "192.0.2.2",
        "dns_v4": "192.0.2.3",
        "sec_dns_v4": "192.0.2.4",
        "transmitted_ip_v6_pool_for_lan": "2001:db8::/56",
        "used_ip_v6_lan": "2001:db8:1::1/64",
        "public_ip_v6": "2001:db8::1",
        "gateway_ip_v6": "fe80::1",
        "dns_v6": "2001:db8::2",
        "sec_dns_v6": "2001:db8::3",
        "unrelated_password": "PRIVATE-SECRET",
    }


def test_exact_native_projection_excludes_unrelated_data() -> None:
    """Ten proven bindings are private; prefix host bits are not rewritten."""
    result = read_ip_information(_raw())
    assert result == {
        "ipv4": {
            "address": "192.0.2.1",
            "gateway": "192.0.2.2",
            "dns_primary": "192.0.2.3",
            "dns_secondary": "192.0.2.4",
        },
        "ipv6": {
            "delegated_prefix": "2001:db8::/56",
            "lan_prefix": "2001:db8:1::1/64",
            "address": "2001:db8::1",
            "gateway": "fe80::1",
            "dns_primary": "2001:db8::2",
            "dns_secondary": "2001:db8::3",
        },
    }
    assert "PRIVATE" not in repr(result)
    assert read_ip_information({"used_ip_v6_lan": "2001:db8::1"})["ipv6"] == {
        "lan_prefix": "2001:db8::1"
    }


@pytest.mark.parametrize("blank", ["", None])
def test_explicit_unreported_values_are_not_invented(blank: Any) -> None:
    """A present native field may be blank; global-only fallback is not a page."""
    assert read_ip_information({"public_ip_v4": blank}) == {"ipv4": {}, "ipv6": {}}
    with pytest.raises(ConfigurationError):
        read_ip_information({"onlinestatus": "online"})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("public_ip_v4", 1),
        ("public_ip_v4", "<script>private</script>"),
        ("public_ip_v4", "192.0.2.1\n"),
        ("public_ip_v4", "2001:db8::1"),
        ("public_ip_v4", ["192.0.2.1", "192.0.2.2"]),
        ("public_ip_v6", "192.0.2.1"),
        ("public_ip_v6", "2001:db8::1/64"),
        ("gateway_ip_v6", "fe80::1%eth0"),
        ("dns_v6", "x" * 129),
        ("transmitted_ip_v6_pool_for_lan", "2001:db8::/129"),
    ],
)
def test_malformed_or_ambiguous_values_fail_closed(key: str, value: Any) -> None:
    """No arbitrary text, family mismatch or ambiguous duplicate is displayed."""
    with pytest.raises(ConfigurationError):
        read_ip_information({**_raw(), key: value})


def test_equal_duplicate_scalars_are_unwrapped() -> None:
    """The native repeated global/page binding is accepted only when equal."""
    assert read_ip_information({"public_ip_v4": ["192.0.2.1"] * 2})["ipv4"] == {
        "address": "192.0.2.1"
    }


async def test_client_uses_only_fixed_authenticated_read() -> None:
    """The query cannot select an endpoint or invoke reconnect/export writes."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with (
        patch.object(client, "get_json", AsyncMock(return_value=_raw())) as get,
        patch.object(client, "_post_json_unlocked", AsyncMock()) as post,
    ):
        assert await client.query_ip_information() == read_ip_information(_raw())
    get.assert_awaited_once_with(
        "data/IPData.json",
        authenticated=True,
        referer="html/content/internet/con_ipdata.html",
    )
    post.assert_not_awaited()


async def test_hub_static_contract_allows_missing_discovery_without_publication(
    hass: Any, mock_speedport_client: MagicMock
) -> None:
    """Reviewed firmware needs no optional tag; it still shares lock/rate/cleanup."""
    assert "ip" not in mock_speedport_client.setup.return_value.feature_endpoints
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=False
    )
    await hub.async_setup()
    before = hub.data
    mock_speedport_client.query_ip_information.return_value = read_ip_information(
        _raw()
    )
    async with hub._operation_lock:  # noqa: SLF001 -- shared ownership assertion
        task = asyncio.create_task(hub.async_query_ip_information())
        await asyncio.sleep(0)
        mock_speedport_client.query_ip_information.assert_not_awaited()
    assert (await task)["ipv4"]["address"] == "192.0.2.1"
    assert hub.data is before
    assert "192.0.2.1" not in repr(hub.data)
    mock_speedport_client.logout.assert_awaited_once()
    with pytest.raises(AdminQueryRateLimitError):
        await hub.async_query_ip_information()
    mock_speedport_client.query_ip_information.assert_awaited_once()


@pytest.mark.parametrize("failure", ["model", "firmware", "authentication", "session"])
async def test_hub_unknown_identity_or_unavailable_management_rejects_before_io(
    hass: Any, mock_speedport_client: MagicMock, failure: str
) -> None:
    """Static evidence is exact firmware/model, not permission to probe any router."""
    if failure in {"model", "firmware"}:
        mock_speedport_client.router_info = replace(
            mock_speedport_client.router_info, **{failure: "unreviewed"}
        )
        mock_speedport_client.get_status.return_value = replace(
            mock_speedport_client.get_status.return_value,
            info=mock_speedport_client.router_info,
        )
    if failure == "authentication":
        mock_speedport_client.setup.return_value = replace(
            mock_speedport_client.setup.return_value, authenticated_json=False
        )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    if failure == "session":
        hub._management_state = "unavailable"  # noqa: SLF001 -- model lifecycle gate
    with pytest.raises(HomeAssistantError):
        await hub.async_query_ip_information()
    mock_speedport_client.query_ip_information.assert_not_awaited()


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_failure_disposes_result_without_private_error_details(
    hass: Any,
    mock_speedport_client: MagicMock,
    caplog: Any,
    cleanup_failure: bool,  # noqa: FBT001 -- parametrized failure phase
) -> None:
    """Read and cleanup failure cannot publish addresses or return partial data."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    mock_speedport_client.query_ip_information.return_value = read_ip_information(
        _raw()
    )
    if cleanup_failure:
        mock_speedport_client.logout.side_effect = RuntimeError("192.0.2.1")
    else:
        mock_speedport_client.query_ip_information.side_effect = RuntimeError(
            "192.0.2.1"
        )
    with pytest.raises(HomeAssistantError) as error:
        await hub.async_query_ip_information()
    assert "192.0.2.1" not in str(error.value) + caplog.text + repr(hub.data)
    mock_speedport_client.logout.assert_awaited_once()


def test_closed_admin_only_dispatch_schema() -> None:
    """No address selector, arbitrary path, or anonymous read is accepted."""
    message = {"id": 1, "type": PANEL_IP_INFORMATION_WS_TYPE, "entry_id": "entry"}
    schema = websocket_ip_information._ws_schema  # noqa: SLF001 -- registered schema
    assert schema(message) == message
    with pytest.raises(vol.Invalid):
        schema({**message, "endpoint": "data/Other.json"})
    hass, connection = MagicMock(), MagicMock()
    connection.user.is_admin = False
    with pytest.raises(Unauthorized):
        websocket_ip_information(hass, connection, message)
    hass.config_entries.async_get_entry.assert_not_called()


@pytest.mark.parametrize("oversized", [False, True])
async def test_ip_transport_body_limit_before_decode(
    oversized: bool,  # noqa: FBT001 -- parametrized bound
) -> None:
    """Chunked reads stop at the byte cap without first buffering response.text."""

    async def chunks(_size: int) -> Any:
        yield b"x" * 16
        yield b"y" * (17 if oversized else 16)

    response = MagicMock()
    response.content = SimpleNamespace(iter_chunked=chunks)
    response.status = 200
    response.text = AsyncMock(side_effect=AssertionError("must not buffer"))
    response.__aenter__.return_value = response
    session = MagicMock()
    session.request.return_value = response
    client = SpeedportClient(session, "router.invalid")
    with patch(
        "custom_components.speedport_smart.api.client._IP_INFORMATION_MAX_RESPONSE_BYTES",
        32,
    ):
        call = client._request_text_unlocked(  # noqa: SLF001 -- transport bound proof
            "GET", "http://router.invalid/data/IPData.json", headers={}
        )
        if oversized:
            with pytest.raises(SpeedportProtocolError, match="private read limit"):
                await call
        else:
            assert await call == "x" * 16 + "y" * 16
    response.text.assert_not_awaited()
    assert session.request.call_args.kwargs["allow_redirects"] is False


async def test_ip_json_transport_enforces_cap_and_native_page_token() -> None:
    """The actual fixed IPData request enables its bounded-body transport."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    client._login_key = bytes(32)  # noqa: SLF001 -- synthetic authenticated state
    with (
        patch.object(client, "_ensure_authenticated_unlocked", AsyncMock()),
        patch.object(
            client, "_get_http_token_unlocked", AsyncMock(return_value="123")
        ) as token,
        patch.object(
            client,
            "_request_text_unlocked",
            AsyncMock(return_value='{"public_ip_v4":"192.0.2.1"}'),
        ) as request,
    ):
        assert await client.query_ip_information() == {
            "ipv4": {"address": "192.0.2.1"},
            "ipv6": {},
        }
    token.assert_awaited_once_with("html/content/internet/con_ipdata.html")
    assert request.await_count == 1
    assert "_tn=123" in request.await_args.args[1]
    assert request.await_args.args[1].startswith(
        "http://router.invalid/data/IPData.json?"
    )
