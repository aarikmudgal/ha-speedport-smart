"""Polling coordinators for Speedport Smart."""

from __future__ import annotations

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
        super().__init__(
            hass,
            logger=hub.logger,
            config_entry=config_entry,
            name=f"{DOMAIN}_{hub.router_identifier}_{group}",
            update_interval=interval,
            always_update=False,
        )

    @callback
    def _schedule_refresh(self) -> None:
        """Keep autonomous poll timers independent of an initiating admin request."""
        with autonomous_ha_context():
            super()._schedule_refresh()

    @callback
    def async_set_updated_data(self, data: GroupSnapshot) -> None:
        """Publish snapshots without binding entity/automation tasks to a request."""
        with autonomous_ha_context():
            super().async_set_updated_data(data)

    async def _async_update_data(self) -> GroupSnapshot:
        """Fetch one polling group."""
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
