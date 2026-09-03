"""Polling coordinators for Speedport Smart."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportSessionBusyError,
)
from .const import DOMAIN
from .private_authorization import autonomous_ha_context

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime, timedelta

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub, StateTransition


class PollGroup(StrEnum):
    """Router polling groups."""

    FAST = "fast"
    NORMAL = "normal"
    SLOW = "slow"


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    """One successful polling-group snapshot."""

    group: PollGroup
    data: Mapping[str, Any]
    generation: int
    updated_at: datetime
    transitions: tuple[StateTransition, ...] = ()


class SpeedportDataUpdateCoordinator(DataUpdateCoordinator[GroupSnapshot]):
    """Update one router data group without coupling platform entities to I/O."""

    def __init__(
        self,
        hass: HomeAssistant,
        hub: SpeedportHub,
        group: PollGroup,
        interval: timedelta,
        *,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize coordinator."""
        self.hub = hub
        self.group = group
        self._fast_refresh_running = False
        self._fast_refresh_reschedule_requested = False
        self._update_future: asyncio.Future[GroupSnapshot] | None = None
        super().__init__(
            hass,
            logger=hub.logger,
            config_entry=config_entry,
            name=f"{DOMAIN}_{hub.router_identifier}_{group}",
            update_interval=interval,
            always_update=False,
        )
        if group is PollGroup.FAST:
            hub.align_fast_poll_clock()

    @callback
    def _schedule_refresh(self) -> None:
        """Keep autonomous poll timers independent of an initiating admin request."""
        with autonomous_ha_context():
            if self._update_future is not None:
                self._async_unsub_refresh()
                return
            if self.group is PollGroup.FAST:
                if (
                    self.update_interval is None
                    or self._shutdown_requested
                    or (self.config_entry and self.config_entry.pref_disable_polling)
                ):
                    return
                self._async_unsub_refresh()
                if self._fast_refresh_running:
                    self._fast_refresh_reschedule_requested = True
                    return
                delay = self.hub.fast_poll_delay(self.update_interval.total_seconds())
                self._unsub_refresh = self.hass.loop.call_later(
                    max(delay, 0.001), self._handle_fast_refresh
                ).cancel
                return
            super()._schedule_refresh()

    @callback
    def _handle_fast_refresh(self) -> None:
        """Delegate each exact-deadline tick to HA's serialized lifecycle handler."""
        self._unsub_refresh = None
        if (
            self._fast_refresh_running
            or self._shutdown_requested
            or self.hass.is_stopping
        ):
            return
        self._fast_refresh_running = True
        self._fast_refresh_reschedule_requested = False
        if self.config_entry:
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_fast_refresh(),
                name=f"{self.name} - refresh",
                eager_start=True,
            )
        else:
            self.hass.async_create_background_task(
                self._async_fast_refresh(),
                name=f"{self.name} - refresh",
                eager_start=True,
            )

    async def _async_fast_refresh(self) -> None:
        """Drop busy timer slots and schedule at most once after completion."""
        try:
            await self._handle_refresh_interval()
        finally:
            self._fast_refresh_running = False
            reschedule = self._fast_refresh_reschedule_requested
            self._fast_refresh_reschedule_requested = False
            if (
                reschedule
                and self._listeners
                and not self._shutdown_requested
                and not self.hass.is_stopping
                and (
                    self.last_update_success
                    or not isinstance(self.last_exception, ConfigEntryAuthFailed)
                )
            ):
                self._schedule_refresh()

    @callback
    def async_set_updated_data(self, data: GroupSnapshot) -> None:
        """Publish snapshots without binding entity/automation tasks to a request."""
        with autonomous_ha_context():
            super().async_set_updated_data(data)

    async def _async_update_data(self) -> GroupSnapshot:
        """Share one in-flight group read, including time deferred by focus."""
        if self._update_future is not None:
            return await asyncio.shield(self._update_future)
        update_future = self._update_future = self.hass.loop.create_future()
        try:
            result = await self._async_fetch_data()
        except BaseException as err:
            if isinstance(err, asyncio.CancelledError):
                update_future.cancel()
            else:
                update_future.set_exception(err)
                # The owning caller receives this error directly, even without
                # a second waiter to retrieve the shared future's exception.
                update_future.exception()
            raise
        else:
            update_future.set_result(result)
            return result
        finally:
            self._update_future = None

    async def _async_fetch_data(self) -> GroupSnapshot:
        """Fetch one polling group and record its actual outcome once."""
        try:
            return await self.hub.async_update_group(self.group)
        except SpeedportInvalidCredentialsError as err:
            self.hub.record_update_failure(self.group, err)
            raise ConfigEntryAuthFailed from err
        except SpeedportAuthenticationError as err:
            self.hub.record_update_failure(self.group, err)
            message = "Router authentication session expired"
            raise UpdateFailed(message) from err
        except SpeedportSessionBusyError as err:
            self.hub.record_update_failure(self.group, err)
            message = "Router session is busy"
            raise UpdateFailed(message) from err
        except SpeedportConnectionError as err:
            self.hub.record_update_failure(self.group, err)
            message = f"Unable to reach router: {err}"
            raise UpdateFailed(message) from err
        except SpeedportError as err:
            self.hub.record_update_failure(self.group, err)
            message = f"Router update failed: {err}"
            raise UpdateFailed(message) from err
        except Exception as err:
            self.hub.record_update_failure(self.group, err)
            raise
