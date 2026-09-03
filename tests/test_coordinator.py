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
@pytest.mark.parametrize("group", [PollGroup.FAST, PollGroup.NORMAL])
async def test_autonomous_poll_timer_detaches_only_private_request_context(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    publication: bool,  # noqa: FBT001 - explicit parameterized publication path
    group: PollGroup,
) -> None:
    """Real HA loop.call_at timers cannot inherit a completed private approval."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, group, timedelta(seconds=60)
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
                        GroupSnapshot(group, {}, 1, datetime.now(UTC))
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


async def test_fast_timer_targets_actual_deadline_and_cancels_with_listener(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """No HA integer-phase early tick can replace the exact WAN deadline."""
    now = [100.3]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    hub._public_status_next_poll_at = float("inf")  # noqa: SLF001
    hub._wan_counter_next_poll_at = 101.0  # noqa: SLF001
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.FAST, timedelta(seconds=1)
    )
    with patch.object(hass.loop, "call_later") as schedule:
        remove = coordinator.async_add_listener(lambda: None)
        assert schedule.call_args.args[0] == pytest.approx(0.7)
        assert schedule.call_args.args[1] == coordinator._handle_fast_refresh  # noqa: SLF001
        handle = schedule.return_value
        remove()
        handle.cancel.assert_called_once()
    await coordinator.async_shutdown()
    with patch.object(hass.loop, "call_later") as schedule:
        coordinator._schedule_refresh()  # noqa: SLF001
        schedule.assert_not_called()


@pytest.mark.parametrize("authentication_failure", [False, True])
@pytest.mark.parametrize("previous_authentication_failure", [False, True])
async def test_publication_during_fast_read_cannot_queue_another_handler(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    authentication_failure: bool,  # noqa: FBT001 - parameterized lifecycle branch
    previous_authentication_failure: bool,  # noqa: FBT001 - retained HA exception
) -> None:
    """One FAST handler owns the request and deferred schedule through completion."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.FAST, timedelta(seconds=1)
    )
    if previous_authentication_failure:
        coordinator.last_exception = ConfigEntryAuthFailed("previous failure")
    entered, release = asyncio.Event(), asyncio.Event()
    tasks = []
    snapshot = GroupSnapshot(PollGroup.FAST, {}, 1, datetime.now(UTC))

    async def read(_group: PollGroup) -> GroupSnapshot:
        entered.set()
        await release.wait()
        if authentication_failure:
            raise SpeedportInvalidCredentialsError("synthetic")
        return snapshot

    def create_task(coroutine: object, **_kwargs: object) -> asyncio.Task:
        task = asyncio.create_task(coroutine)  # type: ignore[arg-type]
        tasks.append(task)
        return task

    hub.async_update_group = AsyncMock(side_effect=read)  # type: ignore[method-assign]
    try:
        with (
            patch.object(hass.loop, "call_later") as schedule,
            patch.object(hass, "async_create_background_task", side_effect=create_task),
        ):
            remove = coordinator.async_add_listener(lambda: None)
            coordinator._handle_fast_refresh()  # noqa: SLF001
            await entered.wait()
            for _ in range(2):
                coordinator.async_set_updated_data(snapshot)
                coordinator._handle_fast_refresh()  # noqa: SLF001
            assert len(tasks) == 1
            assert schedule.call_count == 1
            assert hub.async_update_group.await_count == 1
            release.set()
            await asyncio.gather(*tasks)
            assert schedule.call_count == (1 if authentication_failure else 2)
            remove()
    finally:
        release.set()
        await asyncio.gather(*tasks)
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


@pytest.mark.parametrize("group", [PollGroup.NORMAL, PollGroup.SLOW])
async def test_focused_publications_cannot_accumulate_background_refreshes(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    group: PollGroup,
) -> None:
    """Deferred polls share one read, despite publications or stale timer calls."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    interval = timedelta(seconds=30 if group is PollGroup.NORMAL else 300)
    coordinator = SpeedportDataUpdateCoordinator(hass, hub, group, interval)
    owner = object()
    hub.polling_priority.set_focus(owner, "administration")
    hub.async_update_group = AsyncMock(  # type: ignore[method-assign]
        wraps=hub.async_update_group
    )
    listener = MagicMock()
    remove = coordinator.async_add_listener(listener)
    tasks = [asyncio.create_task(coordinator.async_refresh())]
    try:
        await asyncio.sleep(0)
        for generation in range(3):
            published = GroupSnapshot(group, {}, generation, datetime.now(UTC))
            coordinator.async_set_updated_data(published)
            assert coordinator.data is published
            assert coordinator._unsub_refresh is None  # noqa: SLF001
            tasks.append(
                asyncio.create_task(coordinator._handle_refresh_interval())  # noqa: SLF001
            )
        await asyncio.sleep(0)
        assert listener.call_count == 3
        assert not any(task.done() for task in tasks)
        assert hub.async_update_group.await_count == 1
        assert len(hub.polling_priority._waiters) == 1  # noqa: SLF001
        mock_speedport_client.get_json.assert_not_awaited()
        hub.polling_priority.clear_focus(owner)
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        assert hub.async_update_group.await_count == 1
        mock_speedport_client.get_json.assert_awaited_once()
        assert coordinator.update_interval == interval
        assert coordinator._unsub_refresh is not None  # noqa: SLF001
    finally:
        hub.polling_priority.clear_focus(owner)
        await asyncio.gather(*tasks, return_exceptions=True)
        remove()
        await coordinator.async_shutdown()
        await hub.async_close()


@pytest.mark.parametrize("group", list(PollGroup))
async def test_cancelling_shared_waiter_keeps_original_refresh_running(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    group: PollGroup,
) -> None:
    """A second caller can stop waiting without cancelling the real operation."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(hass, hub, group, timedelta(seconds=1))
    entered, release = asyncio.Event(), asyncio.Event()
    snapshot = GroupSnapshot(group, {}, 1, datetime.now(UTC))

    async def read(_group: PollGroup) -> GroupSnapshot:
        entered.set()
        await release.wait()
        return snapshot

    hub.async_update_group = AsyncMock(side_effect=read)  # type: ignore[method-assign]
    original = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await entered.wait()
    waiter = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not original.done()
    assert hub.async_update_group.await_count == 1
    release.set()
    assert await asyncio.wait_for(original, timeout=1) is snapshot
    assert await coordinator._async_update_data() is snapshot  # noqa: SLF001
    assert hub.async_update_group.await_count == 2
    await coordinator.async_shutdown()


async def test_original_refresh_cancellation_reaches_shared_waiters_and_recovers(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The owning refresh retains its cancellation semantics and clears sharing."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.NORMAL, timedelta(seconds=30)
    )
    entered, release = asyncio.Event(), asyncio.Event()
    snapshot = GroupSnapshot(PollGroup.NORMAL, {}, 1, datetime.now(UTC))

    async def read(_group: PollGroup) -> GroupSnapshot:
        entered.set()
        await release.wait()
        return snapshot

    hub.async_update_group = AsyncMock(side_effect=read)  # type: ignore[method-assign]
    original = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await entered.wait()
    waiter = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await asyncio.sleep(0)
    original.cancel()
    for task in (original, waiter):
        with pytest.raises(asyncio.CancelledError):
            await task
    assert hub.async_update_group.await_count == 1
    release.set()
    assert await coordinator._async_update_data() is snapshot  # noqa: SLF001
    assert hub.async_update_group.await_count == 2
    await coordinator.async_shutdown()


async def test_shared_refresh_failure_is_recorded_once_and_reaches_every_waiter(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Sharing does not double-count a failed router operation or swallow errors."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    coordinator = SpeedportDataUpdateCoordinator(
        hass, hub, PollGroup.NORMAL, timedelta(seconds=30)
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def read(_group: PollGroup) -> GroupSnapshot:
        entered.set()
        await release.wait()
        raise SpeedportConnectionError("synthetic")

    hub.async_update_group = AsyncMock(side_effect=read)  # type: ignore[method-assign]
    original = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await entered.wait()
    waiter = asyncio.create_task(coordinator._async_update_data())  # noqa: SLF001
    await asyncio.sleep(0)
    release.set()
    for task in (original, waiter):
        with pytest.raises(UpdateFailed, match="Unable to reach router"):
            await task
    assert hub.async_update_group.await_count == 1
    assert hub._update_failures == 1  # noqa: SLF001
    await coordinator.async_shutdown()
