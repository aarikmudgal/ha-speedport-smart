"""Offline settings wiring: private routes, exact targets and session cleanup."""

# ruff: noqa: SLF001 - inspect explicit security and lifecycle boundaries

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized

from custom_components.speedport_smart import panel_queries
from custom_components.speedport_smart.api import (
    SpeedportClient,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    settings_contracts,
)
from custom_components.speedport_smart.configuration_storage import NAS_SHARE_SETTING_ID
from custom_components.speedport_smart.configuration_targets import target_settings_ids
from custom_components.speedport_smart.hub import SpeedportHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import RouterInfo

_REQUESTER = ("administrator", "login-session")


def _share(sid: str = "7") -> dict[str, Any]:
    return {
        "sid": sid,
        "nas_active": "1",
        "nas_folder_nur_lesen": "0",
        "nas_secure": "0",
        "nas_folder_name": "/Private/Share",
        "nas_user_name": "share-user",
        "nas_user_pwd": "PRIVATE-CREDENTIAL",
        "use_usb": "1",
        "printer_connected": "0",
    }


def _hub(hass: HomeAssistant, client: MagicMock, info: RouterInfo) -> SpeedportHub:
    hub = SpeedportHub(
        hass, client, fallback_identifier="entry-a", controls_enabled=True
    )
    hub._router_info = info
    hub._management_state = "available"
    return hub


@pytest.mark.parametrize("method", ["read", "save"])
async def test_scalar_target_rejected_before_client_io(method: str) -> None:
    """A target cannot turn a reviewed scalar form into an arbitrary row write."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with (
        patch.object(client, "get_json", AsyncMock()) as get,
        patch.object(client, "_post_ephemeral_action", AsyncMock()) as post,
    ):
        operation = (
            client.read_configuration("telephony_hd_voice", "7")
            if method == "read"
            else client.save_configuration(
                "telephony_hd_voice", {}, {"hdvoice": True}, "7"
            )
        )
        with pytest.raises(ConfigurationError, match="invalid_settings_target"):
            await operation
    get.assert_not_awaited()
    post.assert_not_awaited()


async def test_client_targets_normalize_identical_flat_scalar_wrappers() -> None:
    """The target chooser accepts the same proven wrappers as the row reader."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    raw = {key: [value, value] for key, value in _share().items()}
    with patch.object(client, "get_json", AsyncMock(return_value=raw)) as get:
        result = await client.query_configuration_targets(NAS_SHARE_SETTING_ID)
    assert result == {
        "setting_id": NAS_SHARE_SETTING_ID,
        "targets": [{"id": "7", "label": "/Private/Share"}],
    }
    assert "PRIVATE-CREDENTIAL" not in repr(result)
    assert "share-user" not in repr(result)
    get.assert_awaited_once_with(
        "data/NASFolder.json",
        authenticated=True,
        referer="html/content/network/nas_share.html",
    )


@pytest.mark.parametrize("sid", [["7", "8"], ["7", 7], None])
async def test_ambiguous_target_inventory_fails_closed(sid: object) -> None:
    """Conflicting/mixed duplicate scalars are not silently chosen."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with (
        patch.object(
            client, "get_json", AsyncMock(return_value={**_share(), "sid": sid})
        ),
        pytest.raises((ConfigurationError, SpeedportUnsupportedError)),
    ):
        await client.query_configuration_targets(NAS_SHARE_SETTING_ID)


async def test_client_target_selection_preserves_row_and_uses_exact_id() -> None:
    """A selected row retains its private one-shot fields and root prerequisites."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    rows = [_share("7"), _share("8")]
    raw = {"addnasfolder": rows, "use_usb": "1", "printer_connected": "0"}
    with patch.object(client, "get_json", AsyncMock(return_value=raw)):
        result = await client.read_configuration(NAS_SHARE_SETTING_ID, "8")
        assert result["sid"] == "8"
        assert result["use_usb"] == "1"
        with pytest.raises(ConfigurationError, match="stale_settings"):
            await client.read_configuration(NAS_SHARE_SETTING_ID, "9")


async def test_client_nas_write_builds_exact_payload_once() -> None:
    """No raw settings request or credential passthrough is permitted."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    with patch.object(
        client, "_post_ephemeral_action", AsyncMock(return_value={})
    ) as post:
        await client.save_configuration(
            NAS_SHARE_SETTING_ID, _share(), {"nas_active": False}, "7"
        )
    post.assert_awaited_once_with(
        "data/NASFolder.json",
        {"sid": "7", "nas_active": 0},
        referer="html/content/network/nas_share.html",
        require_status_ok=False,
    )


async def test_hub_rejects_cross_target_and_cross_requester_revision(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """A revision for one target or HA session is not authority over another."""
    hub = _hub(hass, mock_speedport_client, router_info)
    mock_speedport_client.read_configuration = AsyncMock(
        side_effect=lambda _setting, target: _share(target)
    )
    with patch.object(
        hub, "_async_cleanup_admin_session", AsyncMock(return_value=True)
    ) as cleanup:
        loaded = await hub.async_read_configuration(
            NAS_SHARE_SETTING_ID, requester=_REQUESTER, target_id="7"
        )
        for target, requester in [
            ("7", ("another-admin", "login-session")),
            ("8", _REQUESTER),
        ]:
            with pytest.raises(ConfigurationError, match="stale_settings"):
                await hub.async_save_configuration(
                    NAS_SHARE_SETTING_ID,
                    requester=requester,
                    target_id=target,
                    revision=loaded["revision"],
                    changes={"nas_active": False},
                    confirmed=True,
                    confirmation_text="SAVE SHARE SETTINGS",
                )
    mock_speedport_client.save_configuration.assert_not_awaited()
    assert cleanup.await_count == 3


@pytest.mark.parametrize("operation", ["targets", "read", "save"])
async def test_hub_settings_share_operation_lock_and_always_cleanup(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
    operation: str,
) -> None:
    """Every private transaction serializes with polling and releases its session."""
    hub = _hub(hass, mock_speedport_client, router_info)
    calls = 0

    async def fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        assert hub._operation_lock.locked()
        raise RuntimeError("PRIVATE-CREDENTIAL")

    mock_speedport_client.query_configuration_targets = AsyncMock(side_effect=fail)
    mock_speedport_client.read_configuration = AsyncMock(side_effect=fail)
    if operation == "save":
        hub._configuration_session.save = AsyncMock(side_effect=fail)
    with patch.object(
        hub, "_async_cleanup_admin_session", AsyncMock(return_value=True)
    ) as cleanup:
        async with hub._operation_lock:
            if operation == "targets":
                pending = asyncio.create_task(
                    hub.async_query_configuration_targets(
                        NAS_SHARE_SETTING_ID, requester=_REQUESTER
                    )
                )
            elif operation == "read":
                pending = asyncio.create_task(
                    hub.async_read_configuration(
                        "telephony_hd_voice", requester=_REQUESTER
                    )
                )
            else:
                pending = asyncio.create_task(
                    hub.async_save_configuration(
                        "telephony_hd_voice",
                        requester=_REQUESTER,
                        revision="a" * 48,
                        changes={"hdvoice": True},
                        confirmed=True,
                        confirmation_text="SAVE SETTINGS",
                    )
                )
            await asyncio.sleep(0)
            assert calls == 0
        with pytest.raises(RuntimeError, match="PRIVATE-CREDENTIAL"):
            await pending
        cleanup.assert_awaited_once()
    assert not hub._operation_lock.locked()


def test_metadata_is_static_and_every_frontend_mapping_resolves(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """Catalog rendering exposes no settings values and never invokes I/O."""
    metadata = _hub(hass, mock_speedport_client, router_info).settings_metadata()
    assert len(metadata) == len(settings_contracts()) + len(target_settings_ids())
    assert len({item["id"] for item in metadata}) == len(metadata)
    assert all(
        not ({"values", "revision", "target_id", "endpoint"} & item.keys())
        for item in metadata
    )
    assert all(item["live_write_verified"] is False for item in metadata)
    mock_speedport_client.read_configuration.assert_not_awaited()
    mock_speedport_client.get_json.assert_not_awaited()
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
    assert linked <= {item["id"] for item in metadata}


@pytest.mark.parametrize(
    "handler",
    [
        panel_queries.websocket_settings_targets,
        panel_queries.websocket_settings_read,
        panel_queries.websocket_settings_save,
    ],
)
def test_settings_websocket_requires_admin_before_any_entry_access(
    handler: Any,
) -> None:
    """The private chooser, read and save all enforce HA administrator authority."""
    hass, connection = MagicMock(), MagicMock()
    connection.user.is_admin = False
    with pytest.raises(Unauthorized):
        handler(hass, connection, {"id": 1, "entry_id": "entry-a"})
    hass.config_entries.async_get_entry.assert_not_called()
    connection.send_result.assert_not_called()


@pytest.mark.parametrize(
    ("suffix", "method"),
    [
        ("targets", "async_query_configuration_targets"),
        ("read", "async_read_configuration"),
        ("save", "async_save_configuration"),
    ],
)
async def test_private_settings_routes_forward_server_requester_and_generic_errors(
    suffix: str, method: str
) -> None:
    """Unknown errors cannot echo submitted secrets into WebSocket responses."""
    method_mock = AsyncMock(side_effect=RuntimeError("PRIVATE-CREDENTIAL"))
    hub = SimpleNamespace(**{method: method_mock})
    entry = SimpleNamespace(
        domain="speedport_smart", state=ConfigEntryState.LOADED, runtime_data=hub
    )
    hass, connection = MagicMock(), MagicMock()
    hass.config_entries.async_get_entry.return_value = entry
    connection.user.id, connection.refresh_token_id = _REQUESTER
    msg = {
        "id": 1,
        "entry_id": "entry-a",
        "setting_id": NAS_SHARE_SETTING_ID,
        "target_id": "7",
        "revision": "a" * 48,
        "changes": {"nas_active": False},
        "confirmed": True,
        "confirmation_text": "SAVE SHARE SETTINGS",
    }
    handler = getattr(
        panel_queries, f"websocket_settings_{suffix}"
    ).__wrapped__.__wrapped__
    await handler(hass, connection, msg)
    assert method_mock.await_args.kwargs["requester"] == _REQUESTER
    if suffix != "targets":
        assert method_mock.await_args.kwargs["target_id"] == "7"
    connection.send_error.assert_called_once_with(
        1, "settings_failed", "Settings operation could not be completed."
    )
    connection.send_result.assert_not_called()


def test_settings_schemas_reject_untyped_authority_and_unknown_fields() -> None:
    """The client supplies a target only, never user identity or an endpoint."""
    schema = panel_queries.websocket_settings_save._ws_schema
    message = {
        "id": 1,
        "type": "speedport_smart/panel/settings/save",
        "entry_id": "entry-a",
        "setting_id": NAS_SHARE_SETTING_ID,
        "target_id": "7",
        "revision": "a" * 48,
        "changes": {"nas_active": False},
        "confirmed": True,
        "confirmation_text": "SAVE SHARE SETTINGS",
    }
    assert schema(message) == message
    for extra in [
        {"target_id": "../7"},
        {"confirmed": 1},
        {"requester": ["admin", "session"]},
        {"endpoint": "data/Other.json"},
    ]:
        with pytest.raises(vol.Invalid):
            schema({**message, **extra})
