"""Offline migration proof for every private panel command and retired WebSocket."""

# ruff: noqa: D103, SLF001

from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import StreamReader
from aiohttp.test_utils import make_mocked_request
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID, KEY_HASS_USER
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.http import KEY_AUTHENTICATED, request_handler_factory

from custom_components.speedport_smart.admin_actions import get_admin_action_contract
from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.api.codec import DEFAULT_KEY
from custom_components.speedport_smart.call_history import (
    export_call_history_csv,
    read_call_history,
)
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
)
from custom_components.speedport_smart.panel_private_http import (
    _REQUEST_LIMIT,
    _RESPONSE_LIMIT,
    PrivatePanelView,
    async_register_private_panel_view,
)
from custom_components.speedport_smart.panel_queries import (
    async_register_admin_query_commands,
    private_panel_command_handlers,
)

PREFIX = "speedport_smart/panel/"
ENTRY = "entry-a"
REQUESTER = ("administrator-a", "refresh-a")


class Request(dict):
    """Small authenticated HTTP request with no real network transport."""

    def __init__(
        self, user: Any, body: Any = None, *, raw: bytes | None = None
    ) -> None:
        """Provide a bounded synthetic JSON stream and server-owned identity."""
        super().__init__({KEY_HASS_USER: user, KEY_HASS_REFRESH_TOKEN_ID: REQUESTER[1]})
        self.headers: dict[str, str] = {}
        self.content_type = "application/json"
        self.query_string = ""
        content = raw if raw is not None else json.dumps(body).encode()
        self.content_length: int | None = len(content)
        self.content = SimpleNamespace(read=AsyncMock(side_effect=[content, b""]))


def _cases() -> list[tuple[str, dict[str, Any], str]]:
    cases: list[tuple[str, dict[str, Any], str]] = [
        (
            "settings/read",
            {"setting_id": "system_router_password_change"},
            "async_read_configuration",
        ),
        (
            "settings/targets",
            {"setting_id": "telephony_phonebook_link"},
            "async_query_configuration_targets",
        ),
        (
            "settings/save",
            {
                "setting_id": "system_router_password_change",
                "revision": "a" * 48,
                "changes": {"new_password": "synthetic-private-password"},
                "confirmed": True,
                "confirmation_text": "CHANGE ROUTER PASSWORD",
            },
            "async_save_configuration",
        ),
        (
            "phonebook_link/finish",
            {
                "pending_link": "b" * 48,
                "target_id": "book-a",
                "phonebook_id": 2,
                "confirmed": True,
                "confirmation_text": "MERGE ONLINE PHONEBOOK CONTACTS",
                "merge_existing": True,
            },
            "async_finish_phonebook_link",
        ),
        (
            "call_history",
            {"category": "taken", "export": True},
            "async_query_call_history",
        ),
        ("ip_information", {}, "async_query_ip_information"),
        ("ip_pbx_refresh", {"client_id": "client-a"}, "async_query_ip_pbx_client"),
        (
            "phonebook_search",
            {"phonebook_id": 2, "prefix": "A"},
            "async_query_phonebook_entries",
        ),
        (
            "phonebook_contact",
            {"phonebook_id": 2, "contact_id": "contact-a"},
            "async_query_phonebook_contact",
        ),
        (
            "maintenance",
            {
                "action": "system_factory_reset",
                "parameters": {"backup_saved": True},
                "confirmed": True,
                "confirmation_text": "FACTORY RESET ROUTER",
            },
            "async_execute_admin_action",
        ),
    ]
    for query in (
        "dect_handset_targets",
        "voip_line_targets",
        "dect_handset_disconnect_targets",
        "dect_repeater_disconnect_targets",
        "voip_provider_delete_targets",
        "voip_line_delete_targets",
        "ip_pbx_client_delete_targets",
        "phonebook_entry_delete_targets",
        "nas_share_delete_targets",
    ):
        cases.append(  # noqa: PERF401 - keep the closed protocol cases readable
            (
                "action/" + query,
                {"phonebook_id": 2}
                if query == "phonebook_entry_delete_targets"
                else {},
                "async_query_" + query,
            )
        )
    for action in (
        "dect_handset_enroll",
        "dect_repeater_enroll",
        "dect_handset_set_paging",
        "voip_line_set_active",
        "dect_handset_disconnect",
        "dect_repeater_disconnect",
        "voip_provider_delete",
        "voip_line_delete",
        "ip_pbx_client_delete",
        "phonebook_entry_delete",
        "nas_share_delete",
    ):
        values: dict[str, Any] = {"confirmed": True}
        if action == "dect_repeater_enroll":
            values.update(
                pin_is_default=True, full_power_enabled=True, full_eco_disabled=True
            )
        elif action == "dect_handset_set_paging":
            values.update(target_token="c" * 32, enabled=True)
        elif action == "voip_line_set_active":
            values.update(target_token="c" * 32, active=True)
        elif action != "dect_handset_enroll":
            contract = get_admin_action_contract(action)
            assert contract is not None
            values.update(
                target_token="c" * 32, confirmation_text=contract.typed_confirmation
            )
        cases.append(("action/" + action, values, "async_execute_admin_action"))
    return cases


CASES = _cases()


def _context() -> SimpleNamespace:
    user = SimpleNamespace(id=REQUESTER[0], is_admin=True, is_active=True)
    hub = SimpleNamespace(_closed=False, data={}, capability_report=None)
    for _, _, method in CASES:
        setattr(
            hub, method, AsyncMock(return_value={"private": "synthetic-private-value"})
        )
    entry = SimpleNamespace(
        entry_id=ENTRY,
        domain="speedport_smart",
        state=ConfigEntryState.LOADED,
        runtime_data=hub,
    )
    hass = SimpleNamespace(
        data={},
        http=SimpleNamespace(register_view=MagicMock()),
        auth=SimpleNamespace(
            async_get_refresh_token=MagicMock(return_value=SimpleNamespace(user=user))
        ),
        config_entries=SimpleNamespace(async_get_entry=MagicMock(return_value=entry)),
        async_create_background_task=MagicMock(),
    )
    return SimpleNamespace(
        user=user, hub=hub, entry=entry, hass=hass, view=PrivatePanelView(hass)
    )


def _message(suffix: str = "settings/read", **values: Any) -> dict[str, Any]:
    return {"type": PREFIX + suffix, "entry_id": ENTRY, **values}


@pytest.mark.parametrize(("suffix", "parameters", "method"), CASES)
async def test_all_private_dispatchers_use_http_without_websocket_tasks_or_logs(
    suffix: str,
    parameters: dict[str, Any],
    method: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _context()
    caplog.set_level(
        logging.DEBUG, logger="homeassistant.components.websocket_api.http.connection"
    )
    response = await context.view.post(
        Request(context.user, _message(suffix, **parameters)), ENTRY
    )
    assert response.status == 200
    assert "synthetic-private-value" in response.text
    getattr(context.hub, method).assert_awaited_once()
    context.hass.async_create_background_task.assert_not_called()
    assert "synthetic-private" not in caplog.text
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "ETag" not in response.headers
    assert "Location" not in response.headers


def test_case_inventory_exactly_covers_every_migrated_dispatcher() -> None:
    assert {PREFIX + suffix for suffix, _, _ in CASES} == set(
        private_panel_command_handlers()
    )


async def test_cached_admin_read_uses_same_private_http_transport() -> None:
    context = _context()
    projected = {"schema_version": 1, "private_identifier": "synthetic-device-id"}
    with patch(
        "custom_components.speedport_smart.panel.admin_read_payload",
        return_value=projected,
    ):
        response = await context.view.post(
            Request(context.user, _message("admin_read")), ENTRY
        )
    assert json.loads(response.body) == {"result": projected}
    assert projected["private_identifier"] == "synthetic-device-id"
    context.hass.async_create_background_task.assert_not_called()


async def test_credentials_use_server_owned_requester_and_are_released() -> None:
    context = _context()
    calls: list[dict] = []
    changes_ref: list[dict] = []

    async def save(setting_id: str, **kwargs: Any) -> dict:
        assert setting_id == "system_router_password_change"
        calls.append(deepcopy(kwargs))
        changes_ref.append(kwargs["changes"])
        return {"status": "outcome_unknown"}

    context.hub.async_save_configuration.side_effect = save
    body = _message(
        "settings/save",
        setting_id="system_router_password_change",
        revision="a" * 48,
        changes={"password": "synthetic-private-password"},
        confirmed=True,
        confirmation_text="CHANGE ROUTER PASSWORD",
    )
    response = await context.view.post(Request(context.user, body), ENTRY)
    assert response.status == 200
    assert calls[0]["requester"] == REQUESTER
    assert calls[0]["changes"] == {"password": "synthetic-private-password"}
    assert changes_ref == [{}]
    assert "synthetic-private-password" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 1},
        {"entry_id": "entry-b"},
        {"type": PREFIX + "unknown"},
        {"requester": ["other", "other"]},
        {"setting_id": []},
        {"confirmed": True},
    ],
)
async def test_closed_schema_rejects_unreviewed_fields_without_router_work(
    changes: dict,
) -> None:
    context = _context()
    message = _message(setting_id="system_router_password_change")
    message.update(changes)
    response = await context.view.post(Request(context.user, message), ENTRY)
    assert response.status == 400
    assert set(json.loads(response.body)) == {"error"}
    context.hub.async_read_configuration.assert_not_awaited()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"type":"x","type":"y"}',
        b'{"changes":{"password":"x","password":"y"}}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b"[]",
        b"not json",
        b"\xff",
        b"[" * 40 + b"0" + b"]" * 40,
    ],
)
async def test_malformed_duplicate_nonfinite_or_deep_json_is_private_error(
    raw: bytes,
) -> None:
    context = _context()
    response = await context.view.post(Request(context.user, raw=raw), ENTRY)
    assert response.status == 400
    context.hub.async_read_configuration.assert_not_awaited()


@pytest.mark.parametrize("case", ["length", "chunked", "encoding", "query", "type"])
async def test_bounded_body_and_no_private_query_string(case: str) -> None:
    context = _context()
    request = Request(
        context.user, _message(setting_id="system_router_password_change")
    )
    if case in {"length", "chunked"}:
        request.content_length = _REQUEST_LIMIT + 1 if case == "length" else None
        request.content.read.side_effect = [b"x" * (_REQUEST_LIMIT + 1), b""]
    elif case == "encoding":
        request.headers["Content-Encoding"] = "gzip"
    elif case == "query":
        request.query_string = "password=synthetic-private-password"
    else:
        request.content_type = "text/plain"
    assert (await context.view.post(request, ENTRY)).status == 400
    context.hub.async_read_configuration.assert_not_awaited()


@pytest.mark.parametrize(
    "case",
    ["nonadmin", "inactive", "revoked", "foreign", "domain", "unloaded", "closed"],
)
async def test_live_administrator_refresh_entry_and_runtime_binding(case: str) -> None:
    context = _context()
    if case == "nonadmin":
        context.user.is_admin = False
    elif case == "inactive":
        context.user.is_active = False
    elif case == "revoked":
        context.hass.auth.async_get_refresh_token.return_value = None
    elif case == "foreign":
        context.hass.auth.async_get_refresh_token.return_value = SimpleNamespace(
            user=SimpleNamespace(id="other", is_active=True, is_admin=True)
        )
    elif case == "domain":
        context.entry.domain = "other"
    elif case == "unloaded":
        context.entry.state = ConfigEntryState.NOT_LOADED
    else:
        context.hub._closed = True
    request = Request(
        context.user, _message(setting_id="system_router_password_change")
    )
    if case == "nonadmin":
        with pytest.raises(Unauthorized):
            await context.view.post(request, ENTRY)
    else:
        assert (await context.view.post(request, ENTRY)).status == 400
    context.hub.async_read_configuration.assert_not_awaited()


@pytest.mark.parametrize("stage", ["body", "response"])
async def test_entry_replacement_cannot_start_or_release_private_operation(
    stage: str,
) -> None:
    context = _context()
    request = Request(
        context.user, _message(setting_id="system_router_password_change")
    )
    if stage == "body":
        body = json.dumps(_message(setting_id="system_router_password_change")).encode()
        calls = [body, b""]

        async def read(_size: int) -> bytes:
            context.entry.runtime_data = SimpleNamespace()
            return calls.pop(0)

        request.content.read.side_effect = read
    else:

        async def private_read(*_args: Any, **_kwargs: Any) -> dict:
            context.entry.runtime_data = SimpleNamespace()
            return {"private": "synthetic-private-value"}

        context.hub.async_read_configuration.side_effect = private_read
    response = await context.view.post(request, ENTRY)
    assert response.status == 400
    assert "synthetic-private" not in response.text
    assert context.hub.async_read_configuration.await_count == (stage == "response")


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (RuntimeError("synthetic-private-password"), "settings_failed"),
        (ConfigurationError("synthetic_private_password"), "private_operation_failed"),
    ],
)
async def test_exceptions_and_unrecognized_error_codes_never_echo_private_text(
    failure: Exception,
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _context()
    context.hub.async_read_configuration.side_effect = failure
    response = await context.view.post(
        Request(context.user, _message(setting_id="system_router_password_change")),
        ENTRY,
    )
    assert response.status == 400
    assert json.loads(response.body)["error"]["code"] == code
    assert "synthetic" not in response.text
    assert "synthetic" not in caplog.text


@pytest.mark.parametrize(
    "code",
    [
        "bonding_managed_by_easy_support",
        "settings_prerequisites_unavailable",
        "settings_unavailable",
        "usb_disabled",
        "tethering_unavailable_with_receiver",
    ],
)
async def test_fixed_prerequisite_errors_survive_real_ha_http_serialization(
    code: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The actual HA wrapper and bounded request stream retain only safe codes."""
    context = _context()
    context.hass.is_stopping = False
    setting_id = (
        "usb_tethering_enabled"
        if code in {"usb_disabled", "tethering_unavailable_with_receiver"}
        else "receiver_bonding"
    )

    async def read(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if code == "bonding_managed_by_easy_support":
            return resolve_settings_contract("receiver_bonding").read(
                {
                    "ex5g_serial_number": "synthetic-private-serial",
                    "ex5g_model_name": "synthetic-private-model",
                    "easy_support_deactive": "0",
                    "use_bonding": "1",
                }
            )
        if setting_id == "usb_tethering_enabled":
            return resolve_settings_contract(setting_id).read(
                {
                    "use_usb": "0" if code == "usb_disabled" else "1",
                    "auto_external_modem": "0",
                    "use_lte": "1",
                    "hybrid_tunnel": "1",
                    "use_tethering": "0",
                    "private_extra": "synthetic-private-receiver",
                }
            )
        raise ConfigurationError(code)

    context.hub.async_read_configuration.side_effect = read
    body = json.dumps(_message(setting_id=setting_id)).encode()
    stream = StreamReader(MagicMock(), limit=_REQUEST_LIMIT)
    stream.feed_data(body)
    stream.feed_eof()
    request = make_mocked_request(
        "POST",
        f"/api/speedport_smart/private/{ENTRY}",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        match_info={"entry_id": ENTRY},
        payload=stream,
    )
    request[KEY_HASS_USER] = context.user
    request[KEY_HASS_REFRESH_TOKEN_ID] = REQUESTER[1]
    request[KEY_AUTHENTICATED] = True
    handle = request_handler_factory(context.hass, context.view, context.view.post)
    response = await handle(request)
    envelope = json.loads(response.body)
    assert response.status == 400
    assert set(envelope) == {"error"}
    assert envelope["error"]["code"] == code
    assert response.headers["Cache-Control"] == "no-store, private"
    assert "synthetic" not in response.text + caplog.text
    context.hub.async_read_configuration.assert_awaited_once_with(
        setting_id, requester=REQUESTER, target_id=None
    )


@pytest.mark.parametrize(
    ("setting_id", "values", "code"),
    [
        (
            "system_mesh_restart",
            {"mesh_exist": "0"},
            "system_mesh_unavailable",
        ),
        (
            "system_mesh_firmware_online",
            {
                "addmeshdevice": [
                    {
                        "id": "1",
                        "mesh_connected": "1",
                        "mesh_mac": "02:00:00:00:00:01",
                        "mesh_serial": "synthetic-private-serial",
                        "mesh_name": "synthetic-private-node",
                        "mesh_device_type": "2",
                        "mesh_upd_local": "1",
                    }
                ]
            },
            "system_mesh_local_update_only",
        ),
        (
            "system_router_firmware_online",
            {"inet_isp": "1", "autofw_deactive": "0"},
            "system_firmware_managed_automatically",
        ),
        (
            "system_router_firmware_online",
            {
                "inet_isp": "0",
                "autofw_deactive": "1",
                "system_firmware_offer": {"status": "ok", "fwupd_avail": "0"},
            },
            "system_firmware_offer_unavailable",
        ),
        (
            "vpn_ipsec_key_rotate",
            {"vpn_typ": "0", "vpn_key": "synthetic-private-key", "addvpn": []},
            "vpn_key_rotation_unavailable",
        ),
        (
            "vpn_ipsec_key_rotate",
            {"vpn_typ": "1", "vpn_key": "synthetic-private-key", "addvpn": []},
            "vpn_key_rotation_unavailable",
        ),
        (
            "network_smarthome_deactivate",
            {"use_smarthome": "0", "smarthome_state_check": "0"},
            "system_smarthome_unavailable",
        ),
        (
            "network_smarthome_deactivate",
            {"use_smarthome": "1", "smarthome_state_check": "1"},
            "system_smarthome_unavailable",
        ),
        (
            "network_smarthome_activate",
            {"use_smarthome": "1", "smarthome_state_check": "0"},
            "system_smarthome_unavailable",
        ),
        *[
            (f"call_history_clear_{category}", {}, "call_history_unavailable")
            for category in ("missed", "taken", "dialed")
        ],
        (
            "call_history_clear_missed",
            {"addmissedcalls": [{"missedcalls_who": "synthetic-private-caller"}]},
            "call_history_unavailable",
        ),
    ],
)
async def test_fixed_contract_prerequisites_forward_without_issuing_revision(
    setting_id: str,
    values: dict[str, Any],
    code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Actual strict contracts reject privately, before an editor grant or write."""
    context = _context()
    session = ConfigurationSession()
    contract = resolve_settings_contract(setting_id)
    raw = {
        "router_state": "OK",
        "onlinestatus": "online",
        "firmware_version": "1.0",
        "system_firmware_offer": {"status": "ok"},
        "private_extra": "synthetic-private-settings",
        **values,
    }

    async def read(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return await session.read(contract, REQUESTER, AsyncMock(return_value=raw))

    context.hub.async_read_configuration.side_effect = read
    response = await context.view.post(
        Request(context.user, _message(setting_id=setting_id)), ENTRY
    )
    envelope = json.loads(response.body)
    assert response.status == 400
    assert set(envelope) == {"error"}
    assert envelope["error"]["code"] == code
    assert "synthetic" not in response.text + caplog.text
    assert session._grants == {}
    context.hub.async_read_configuration.assert_awaited_once_with(
        setting_id, requester=REQUESTER, target_id=None
    )
    context.hub.async_save_configuration.assert_not_awaited()


async def test_cancelled_dispatch_runs_cleanup_and_is_not_retried() -> None:
    context = _context()
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def save(*_args: Any, **_kwargs: Any) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    context.hub.async_save_configuration.side_effect = save
    _, parameters, _ = CASES[2]
    task = asyncio.create_task(
        context.view.post(
            Request(context.user, _message("settings/save", **parameters)), ENTRY
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()
    context.hub.async_save_configuration.assert_awaited_once()


def test_private_view_registration_is_idempotent() -> None:
    context = _context()
    async_register_private_panel_view(context.hass)
    async_register_private_panel_view(context.hass)
    context.hass.http.register_view.assert_called_once()
    view = context.hass.http.register_view.call_args.args[0]
    assert view.url == "/api/speedport_smart/private/{entry_id}"
    assert view.requires_auth


def test_all_legacy_websocket_commands_are_inert_upgrade_stubs() -> None:
    with patch(
        "custom_components.speedport_smart.panel_queries.websocket_api.async_register_command"
    ) as register:
        async_register_admin_query_commands(MagicMock())
    handlers = private_panel_command_handlers()
    assert len(register.call_args_list) == len(handlers)
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True), send_error=MagicMock()
    )
    hass = MagicMock()
    for call in register.call_args_list:
        stub = call.args[1]
        assert stub is not handlers[stub._ws_command]
        stub(
            hass,
            connection,
            {
                "id": 1,
                "type": stub._ws_command,
                "password": "synthetic-private-password",
            },
        )
    assert connection.send_error.call_count == len(handlers)
    assert all(
        call.args[1] == "private_transport_required"
        for call in connection.send_error.call_args_list
    )
    assert "synthetic" not in str(connection.send_error.call_args_list)
    assert not hass.mock_calls


def test_maximum_unicode_call_history_and_csv_fit_bounded_response() -> None:
    value = "\U0001f600" * 512
    raw = {
        "addtakencalls": [
            {
                "takencalls_date": value,
                "takencalls_time": value,
                "takencalls_who": value,
                "takencalls_as": value,
                "takencalls_duration": "1",
            }
            for _ in range(1000)
        ]
    }
    payload = {
        **read_call_history(raw, "taken"),
        "private_download": {"content": export_call_history_csv(raw, "taken")},
    }
    response = _context().view._response({"result": payload})
    assert 4 * 1024 * 1024 < len(response.body) < _RESPONSE_LIMIT


async def test_revocation_while_page_token_is_pending_prevents_actual_router_post() -> (
    None
):
    context = _context()
    client = SpeedportClient(MagicMock(), "router.invalid")
    client._authenticated = True
    client._login_key = DEFAULT_KEY
    client._encrypted_mode = False

    async def token(_referer: str) -> str:
        context.user.is_active = False
        return "123"

    async def save(*_args: Any, **_kwargs: Any) -> dict:
        return await client._post_ephemeral_action(
            "data/Energy.json",
            {"led": "1"},
            referer="html/content/config/energy.html",
            require_status_ok=True,
        )

    context.hub.async_save_configuration.side_effect = save
    with (
        patch.object(client, "_get_http_token_unlocked", side_effect=token),
        patch.object(
            client, "_request_text_unlocked", AsyncMock(return_value='{"status":"ok"}')
        ) as post,
    ):
        _, parameters, _ = CASES[2]
        response = await context.view.post(
            Request(context.user, _message("settings/save", **parameters)), ENTRY
        )
    assert response.status == 400
    post.assert_not_awaited()
