"""Offline password approval, persistence and durable retry-suspension wiring."""

# ruff: noqa: D103, SLF001

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextvars import ContextVar, copy_context
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.exceptions import HomeAssistantError

from custom_components.speedport_smart.api import (
    SpeedportClient,
    SpeedportProtocolError,
)
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_password import (
    PASSWORD_SETTINGS,
    password_configuration_context,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.password_change import (
    PASSWORD_CHANGE_CONFIRMATION,
    PASSWORD_CHANGE_ID,
    PasswordChangeError,
)
from custom_components.speedport_smart.password_change_io import (
    PasswordChangeTransactionResult,
    VerifiedPasswordCredential,
)
from custom_components.speedport_smart.private_authorization import (
    PrivateAuthorizationError,
    check_private_authorization,
    private_authorization,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import RouterInfo

_OLD = "private-old-password"
_NEW = "private-new-password"
_REQUESTER = ("administrator-a", "refresh-session-a")
_CONTRACT = PASSWORD_SETTINGS[0]
_IO = (
    "custom_components.speedport_smart.password_change_io.async_execute_password_change"
)


def _changes(**overrides: object) -> dict[str, object]:
    return {
        "password": _OLD,
        "new_password": _NEW,
        "new_pw_repeat": _NEW,
        "recovery_ready": True,
        **overrides,
    }


@pytest.fixture
def context(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> Iterator[SimpleNamespace]:
    client = mock_speedport_client
    client._password = _OLD
    client.logout_ephemeral = AsyncMock()
    raw = password_configuration_context(
        {
            "device_name": router_info.model,
            "firmware_version": router_info.firmware,
            "serial_number": router_info.serial_number,
        }
    )
    client.read_configuration = AsyncMock(return_value=raw)
    hub = SpeedportHub(
        hass,
        client,
        fallback_identifier="entry-a",
        entry_id="entry-a",
        controls_enabled=True,
    )
    hub._router_info = router_info
    hub._apply_capability_report(client.capabilities)
    hub._management_state = "available"
    clock = [0.0]
    hub._configuration_session = ConfigurationSession(clock=lambda: clock[0])
    hub._start_reauth = MagicMock()
    user = SimpleNamespace(id=_REQUESTER[0], is_active=True, is_admin=True)
    token = SimpleNamespace(user=user)
    entry = SimpleNamespace(
        domain=DOMAIN,
        runtime_data=hub,
        state=ConfigEntryState.LOADED,
        data={CONF_PASSWORD: _OLD, "host": "router.invalid"},
    )

    def update(target: Any, *, data: dict[str, Any]) -> bool:
        assert target is entry
        target.data = data
        return True

    with (
        patch.object(hass.auth, "async_get_refresh_token", return_value=token) as auth,
        patch.object(hass.config_entries, "async_get_entry", return_value=entry) as get,
        patch.object(
            hass.config_entries, "async_update_entry", side_effect=update
        ) as save,
    ):
        yield SimpleNamespace(
            hub=hub,
            client=client,
            user=user,
            entry=entry,
            auth=auth,
            get=get,
            save=save,
            clock=clock,
            raw=raw,
        )


async def _read(context: SimpleNamespace) -> str:
    read = await context.hub.async_read_configuration(
        PASSWORD_CHANGE_ID,
        requester=_REQUESTER,
    )
    assert read["values"] == {"recovery_ready": False}
    assert not any(value in repr(read) for value in (_OLD, _NEW, "SP4R-TEST-001"))
    return str(read["revision"])


async def _save(context: SimpleNamespace, revision: str, **overrides: Any) -> dict:
    kwargs = {
        "requester": _REQUESTER,
        "revision": revision,
        "changes": _changes(),
        "confirmed": True,
        "confirmation_text": PASSWORD_CHANGE_CONFIRMATION,
        **overrides,
    }
    return await context.hub.async_save_configuration(PASSWORD_CHANGE_ID, **kwargs)


def _proven(*, cleanup: bool = True) -> PasswordChangeTransactionResult:
    return PasswordChangeTransactionResult(
        {"status": "outcome_unknown", "verification": "credential_update_required"},
        VerifiedPasswordCredential(_NEW, cleanup_confirmed=cleanup),
    )


async def test_only_independent_private_proof_allows_persistence(
    context: SimpleNamespace,
) -> None:
    revision = await _read(context)
    proof = _proven()

    async def execute(draft: Any, **kwargs: Any) -> PasswordChangeTransactionResult:
        assert context.hub._operation_lock.locked()
        assert revision not in context.hub._configuration_session._grants
        assert context.entry.data[CONF_PASSWORD] == _OLD
        kwargs["check_requester"]()
        assert draft.current_password() == _OLD
        return proof

    with patch(_IO, side_effect=execute) as io:
        result = await _save(context, revision)
        with pytest.raises(ConfigurationError, match="stale_settings"):
            await _save(context, revision)
    assert result["status"] == "verified"
    assert context.entry.data == {CONF_PASSWORD: _NEW, "host": "router.invalid"}
    assert context.client._password == _NEW
    context.save.assert_called_once()
    io.assert_awaited_once()
    context.client.save_configuration.assert_not_awaited()
    context.hub._start_reauth.assert_not_called()
    assert not context.hub._password_reauth_required
    assert not any(value in repr(result) for value in (_OLD, _NEW))
    assert not any(value in repr(context.hub.data) for value in (_OLD, _NEW))
    with pytest.raises(PasswordChangeError):
        proof.proof.take_credential()


async def test_proven_password_publication_keeps_reload_outside_private_scope(
    context: SimpleNamespace,
) -> None:
    """The verified HA update can start fresh polling after this request ends."""
    revision = await _read(context)
    published = []
    marker = ContextVar("test_password_ha_context", default="unrelated")
    marker_token = marker.set("entry-context")

    def publish(entry: Any, *, data: dict[str, Any]) -> bool:
        published.append(copy_context())
        entry.data = data
        return True

    context.save.side_effect = publish
    try:
        with patch(_IO, return_value=_proven()), private_authorization(lambda: None):
            caller = copy_context()
            result = await _save(context, revision)
            check_private_authorization()
            assert marker.get() == "entry-context"
        assert result["status"] == "verified"
        assert len(published) == 1
        published[0].run(check_private_authorization)
        assert published[0].get(marker) == "entry-context"
        with pytest.raises(PrivateAuthorizationError):
            caller.run(check_private_authorization)
    finally:
        marker.reset(marker_token)


@pytest.mark.parametrize("status", ["outcome_unknown", "not_started", "rejected"])
async def test_no_proof_never_updates_stored_credential(
    context: SimpleNamespace, status: str
) -> None:
    revision = await _read(context)
    with patch(_IO, return_value=PasswordChangeTransactionResult({"status": status})):
        result = await _save(context, revision)
    assert result == {"status": status}
    assert context.entry.data[CONF_PASSWORD] == _OLD
    assert context.client._password == _OLD
    context.save.assert_not_called()
    assert context.hub._password_reauth_required is (status == "outcome_unknown")
    assert revision not in context.hub._configuration_session._grants


@pytest.mark.parametrize(
    "overrides",
    [
        {"confirmed": False},
        {"confirmation_text": "CHANGE PASSWORD"},
        {"requester": ("administrator-b", _REQUESTER[1])},
        {"requester": (_REQUESTER[0], "different-refresh-session")},
        {"changes": _changes(recovery_ready=False)},
        {"changes": _changes(new_pw_repeat="not-the-same-password")},
    ],
)
async def test_invalid_approval_and_form_never_reaches_io(
    context: SimpleNamespace, overrides: dict
) -> None:
    revision = await _read(context)
    with patch(_IO, AsyncMock()) as io, pytest.raises(ConfigurationError):
        await _save(context, revision, **overrides)
    io.assert_not_awaited()
    context.save.assert_not_called()


async def test_expired_or_changed_router_revision_never_reaches_io(
    context: SimpleNamespace,
) -> None:
    revision = await _read(context)
    context.clock[0] = 121.0
    with (
        patch(_IO, AsyncMock()) as io,
        pytest.raises(ConfigurationError, match="stale_settings"),
    ):
        await _save(context, revision)
    io.assert_not_awaited()
    revision = await _read(context)
    context.client.read_configuration.return_value = {
        **context.raw,
        "router_identifier": "another-router",
    }
    with (
        patch(_IO, AsyncMock()) as io,
        pytest.raises(ConfigurationError, match="stale_settings"),
    ):
        await _save(context, revision)
    io.assert_not_awaited()
    context.save.assert_not_called()


@pytest.mark.parametrize(
    "failure", [asyncio.CancelledError(), RuntimeError("private backend error")]
)
async def test_cancel_or_unexpected_io_error_latches_protected_access(
    context: SimpleNamespace, failure: BaseException
) -> None:
    revision = await _read(context)
    with patch(_IO, side_effect=failure), pytest.raises(type(failure)):
        await _save(context, revision)
    context.save.assert_not_called()
    context.hub._start_reauth.assert_called_once()
    assert context.hub._password_reauth_required
    assert context.hub._protected_retry_at == float("inf")
    assert not context.hub.management_controls_available
    assert revision not in context.hub._configuration_session._grants


@pytest.mark.parametrize(
    "failure",
    [
        "revoked",
        "inactive",
        "nonadmin",
        "replaced",
        "closed",
        "domain",
        "unloaded",
        "persistence",
    ],
)
async def test_proof_cannot_commit_after_authority_or_entry_changes(
    context: SimpleNamespace, failure: str
) -> None:
    revision = await _read(context)
    proof = _proven()

    async def execute(_draft: Any, **kwargs: Any) -> PasswordChangeTransactionResult:
        kwargs["check_requester"]()
        if failure == "revoked":
            context.auth.return_value = None
        elif failure == "inactive":
            context.user.is_active = False
        elif failure == "nonadmin":
            context.user.is_admin = False
        elif failure == "replaced":
            context.entry.runtime_data = object()
        elif failure == "closed":
            context.hub._closed = True
        elif failure == "domain":
            context.entry.domain = "other"
        elif failure == "unloaded":
            context.entry.state = ConfigEntryState.NOT_LOADED
        else:
            context.save.side_effect = RuntimeError("private persistence error")
        return proof

    with (
        patch(_IO, side_effect=execute),
        pytest.raises((PasswordChangeError, RuntimeError)),
    ):
        await _save(context, revision)
    assert context.entry.data[CONF_PASSWORD] == _OLD
    assert context.client._password == _OLD
    assert context.hub._password_reauth_required
    assert context.hub._protected_retry_at == float("inf")
    context.hub._start_reauth.assert_called_once()
    with pytest.raises(PasswordChangeError):
        proof.proof.take_credential()


async def test_verified_new_credential_is_saved_but_failed_cleanup_stays_suspended(
    context: SimpleNamespace,
) -> None:
    revision = await _read(context)
    with patch(_IO, return_value=_proven(cleanup=False)):
        result = await _save(context, revision)
    assert result["status"] == "outcome_unknown"
    assert result["verification"] == "session_cleanup_failed"
    assert result["credential_updated"] is True
    assert context.entry.data[CONF_PASSWORD] == _NEW
    assert context.hub._password_reauth_required
    assert context.hub._protected_retry_at == float("inf")


async def test_outer_cleanup_and_later_success_cannot_clear_password_latch(
    context: SimpleNamespace,
) -> None:
    revision = await _read(context)
    context.client.logout_ephemeral.side_effect = SpeedportProtocolError(
        "cleanup failed"
    )
    with patch(
        _IO, return_value=PasswordChangeTransactionResult({"status": "outcome_unknown"})
    ):
        result = await _save(context, revision)
    assert result["status"] == "outcome_unknown"
    assert context.hub._protected_retry_at == float("inf")
    context.hub._mark_management_unavailable()
    context.hub._set_management_access("available")
    assert context.hub._password_reauth_required
    assert context.hub._protected_retry_at == float("inf")
    assert context.hub._management_state == "unavailable"
    context.hub._start_reauth.assert_called_once()


async def test_latched_manual_retry_inventory_and_forced_private_fetch_do_no_io(
    context: SimpleNamespace,
) -> None:
    context.hub._suspend_password_management()
    for operation in (
        context.hub.async_retry_protected_data,
        context.hub.async_capture_candidate_inventory,
    ):
        with pytest.raises(HomeAssistantError, match="reauthentication"):
            await operation()
    await context.hub._async_retry_degraded_access()
    await context.hub._async_fetch_families({"wifi"}, propagate_errors=True)
    context.client.probe_capabilities.assert_not_awaited()
    context.client.capture_candidate_inventory.assert_not_awaited()
    context.client.get_json.assert_not_awaited()


async def test_password_latch_preserves_public_and_wan_polling(
    context: SimpleNamespace,
) -> None:
    context.hub._suspend_password_management()
    snapshot = await context.hub.async_update_group(PollGroup.FAST)
    context.client.get_status.assert_awaited_once()
    context.client.get_wan_counters.assert_awaited_once()
    assert snapshot.data["internet"]["state"] is True
    assert context.hub._password_reauth_required
    context.client.probe_capabilities.assert_not_awaited()


async def test_password_client_read_is_public_and_generic_write_is_closed() -> None:
    client = SpeedportClient(MagicMock(), "router.invalid", _OLD)
    raw = {
        "device_name": "Speedport Smart 4R Typ A",
        "firmware_version": "010152.5.0.001.0",
        "serial_number": "private-router-id",
    }
    with (
        patch.object(client, "get_json", AsyncMock(return_value=raw)) as read,
        patch.object(client, "_post_ephemeral_action", AsyncMock()) as write,
    ):
        context = await client.read_configuration(PASSWORD_CHANGE_ID)
        assert _CONTRACT.read(context) == {"recovery_ready": False}
        read.assert_awaited_once_with("data/Status.json", authenticated=False)
        with pytest.raises(
            ConfigurationError, match="password_change_isolated_flow_required"
        ):
            await client.save_configuration(PASSWORD_CHANGE_ID, context, _changes())
        write.assert_not_awaited()


def test_password_contract_revision_is_private_and_fields_never_prefill() -> None:
    raw = {
        "model": "Speedport Smart 4R Typ A",
        "firmware": "010152.5.0.001.0",
        "router_identifier": "private-serial",
    }
    assert _CONTRACT.read(raw) == {"recovery_ready": False}
    assert _CONTRACT.build(raw, _changes()) == {
        "password": _OLD,
        "new_password": _NEW,
        "new_pw_repeat": _NEW,
    }
    assert (
        _CONTRACT.revision(raw)["dependencies"]["router_identifier"] == "private-serial"
    )
    metadata = _CONTRACT.metadata()
    assert metadata["confirmation"] == PASSWORD_CHANGE_CONFIRMATION
    assert all("value" not in field for field in metadata["fields"])
    assert not any(value in repr(metadata) for value in (_OLD, _NEW, "private-serial"))


async def test_ip_phone_create_uses_its_dedicated_readback_callback(
    context: SimpleNamespace,
) -> None:
    context.hub._configuration_session.save = AsyncMock(
        return_value={"status": "verified"}
    )
    await context.hub.async_save_configuration(
        "telephony_ip_phone_create",
        requester=_REQUESTER,
        revision="a" * 48,
        changes={"placeholder": True},
        confirmed=True,
        confirmation_text="CONFIRM",
    )
    callback = context.hub._configuration_session.save.call_args.kwargs["readback"]
    assert callback is context.client.read_created_ip_phone_configuration
    await callback({"before": "state"}, {"response": "ack"})
    context.client.read_created_ip_phone_configuration.assert_awaited_once_with(
        {"before": "state"},
        {"response": "ack"},
    )
