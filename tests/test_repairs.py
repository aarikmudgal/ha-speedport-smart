"""Tests for Speedport Smart repair flows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.repairs import async_create_fix_flow

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_repair_reload(hass: HomeAssistant) -> None:
    """Confirmed repair reloads its matching config entry."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    issue_id = "session_busy"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue_id,
    )
    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {"issue": "session busy"}

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ) as reload_entry:
        result = await flow.async_step_init({})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_repair_without_entry(hass: HomeAssistant) -> None:
    """Repair can acknowledge an issue whose config entry no longer exists."""
    flow = await async_create_fix_flow(
        hass, "unsupported_firmware", {"entry_id": "missing"}
    )
    flow.hass = hass
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload_entry:
        result = await flow.async_step_init({})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    reload_entry.assert_not_awaited()
