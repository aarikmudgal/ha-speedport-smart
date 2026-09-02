"""Tests for grouped Speedport coordinators."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportSessionBusyError,
)
from custom_components.speedport_smart.coordinator import (
    GroupSnapshot,
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.private_authorization import (
    PrivateAuthorizationError,
    check_private_authorization,
    private_authorization,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_coordinator_success_and_error_mapping(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Coordinator converts protocol failures to Home Assistant lifecycle errors."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    snapshot = GroupSnapshot(
        PollGroup.FAST,
        MappingProxyType({"internet": MappingProxyType({"state": "online"})}),
        1,
        datetime.now(UTC),
    )
    hub.async_update_group = AsyncMock(return_value=snapshot)  # type: ignore[method-assign]
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.FAST, timedelta(seconds=5)
    )

    assert await coordinator._async_update_data() is snapshot  # noqa: SLF001

    hub.async_update_group.side_effect = SpeedportInvalidCredentialsError("bad")
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()  # noqa: SLF001

    hub.async_update_group.side_effect = SpeedportAuthenticationError("expired")
    with pytest.raises(UpdateFailed, match="session expired"):
        await coordinator._async_update_data()  # noqa: SLF001

    hub.async_update_group.side_effect = SpeedportSessionBusyError("busy")
    with pytest.raises(UpdateFailed, match="session is busy"):
        await coordinator._async_update_data()  # noqa: SLF001

    hub.async_update_group.side_effect = SpeedportConnectionError("offline")
    with pytest.raises(UpdateFailed, match="Unable to reach"):
        await coordinator._async_update_data()  # noqa: SLF001

    hub.async_update_group.side_effect = SpeedportError("invalid")
    with pytest.raises(UpdateFailed, match="Router update failed"):
        await coordinator._async_update_data()  # noqa: SLF001

    hub.async_update_group.side_effect = RuntimeError("unexpected private detail")
    with pytest.raises(RuntimeError, match="unexpected private detail"):
        await coordinator._async_update_data()  # noqa: SLF001
    assert hub.poll_group_health(PollGroup.FAST)["state"] == "failed"
    assert hub.poll_group_health(PollGroup.FAST)["last_error_class"] == "RuntimeError"


@pytest.mark.parametrize("publication", [False, True])
async def test_autonomous_poll_timer_detaches_only_private_request_context(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    publication: bool,  # noqa: FBT001 - explicit parameterized publication path
) -> None:
    """Real HA loop.call_at timers cannot inherit a completed private approval."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.NORMAL, timedelta(seconds=60)
    )
    marker = ContextVar("test_other_ha_context", default="absent")
    marker_token = marker.set("preserved")
    tasks: list[asyncio.Task] = []
    seen: list[str] = []

    def denied() -> None:
        raise PermissionError

    async def poll() -> None:
        check_private_authorization()
        seen.append(marker.get())

    def create_task(coroutine: object, **_kwargs: object) -> asyncio.Task:
        task = asyncio.create_task(coroutine)  # type: ignore[arg-type]
        tasks.append(task)
        return task

    try:
        with (
            patch.object(coordinator, "_handle_refresh_interval", side_effect=poll),
            patch.object(hass, "async_create_background_task", side_effect=create_task),
        ):
            with private_authorization(denied):
                remove = coordinator.async_add_listener(lambda: None)
                if publication:
                    coordinator.async_set_updated_data(
                        GroupSnapshot(PollGroup.NORMAL, {}, 1, datetime.now(UTC))
                    )
                cancel = coordinator._unsub_refresh  # noqa: SLF001
                assert cancel is not None
                timer = cancel.__self__  # type: ignore[attr-defined]
                with pytest.raises(PrivateAuthorizationError):
                    check_private_authorization()
            # Run the real asyncio TimerHandle in its captured scheduling context.
            timer._run()  # noqa: SLF001
            timer.cancel()
            await asyncio.gather(*tasks)
            remove()
        assert seen == ["preserved"]
    finally:
        marker.reset(marker_token)
        await coordinator.async_shutdown()


async def test_published_state_listeners_do_not_inherit_private_write_authority(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Independent entity/event tasks remain unscoped while the caller stays guarded."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.NORMAL, timedelta(seconds=60)
    )
    marker = ContextVar("test_other_listener_context", default="absent")
    marker_token = marker.set("preserved")
    tasks: list[asyncio.Task] = []
    seen: list[str] = []

    def denied() -> None:
        raise PermissionError

    async def independent_event() -> None:
        check_private_authorization()
        seen.append(marker.get())

    def listener() -> None:
        check_private_authorization()
        tasks.append(asyncio.create_task(independent_event()))

    remove = coordinator.async_add_listener(listener)
    try:
        with private_authorization(denied):
            coordinator.async_set_updated_data(
                GroupSnapshot(PollGroup.NORMAL, {}, 1, datetime.now(UTC))
            )
            with pytest.raises(PrivateAuthorizationError):
                check_private_authorization()
        await asyncio.gather(*tasks)
        assert seen == ["preserved"]
    finally:
        marker.reset(marker_token)
        remove()
        await coordinator.async_shutdown()
