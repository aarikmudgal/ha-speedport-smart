"""Tests for grouped Speedport coordinators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

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
