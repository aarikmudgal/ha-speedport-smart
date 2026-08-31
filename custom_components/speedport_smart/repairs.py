"""Repair flows for actionable Speedport Smart issues."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow

MANAGEMENT_SESSION_ISSUE = "management_session_blocked"
MANAGEMENT_SESSION_ISSUE_PREFIX = f"{MANAGEMENT_SESSION_ISSUE}_"

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResult


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create repair flow for a Speedport issue."""
    issue_data = data or {}
    if issue_id == MANAGEMENT_SESSION_ISSUE or issue_id.startswith(
        MANAGEMENT_SESSION_ISSUE_PREFIX
    ):
        entry_id = issue_data.get("entry_id")
        if not isinstance(entry_id, str) and issue_id.startswith(
            MANAGEMENT_SESSION_ISSUE_PREFIX
        ):
            candidate = issue_id.removeprefix(MANAGEMENT_SESSION_ISSUE_PREFIX)
            if hass.config_entries.async_get_entry(candidate) is not None:
                entry_id = candidate
        return SpeedportManagementSessionRepairFlow(
            entry_id if isinstance(entry_id, str) else None
        )

    return SpeedportRepairFlow(issue_id, issue_data)


class SpeedportManagementSessionRepairFlow(RepairsFlow):
    """Prompt for browser logout before safely retrying router access."""

    def __init__(self, entry_id: str | None) -> None:
        """Initialize the management-session repair flow."""
        self.entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Explain the required logout and schedule a retry on confirmation."""
        if user_input is None:
            return self.async_show_form(step_id="init", data_schema=vol.Schema({}))

        if self.entry_id is not None and self.hass.config_entries.async_get_entry(
            self.entry_id
        ):
            # Scheduling lets the repair flow finish before setup can recreate the
            # issue when the browser session is still active.
            self.hass.config_entries.async_schedule_reload(self.entry_id)
        return self.async_create_entry(title="", data={})


class SpeedportRepairFlow(RepairsFlow):
    """Confirm external recovery, reload entry, and clear issue."""

    def __init__(self, issue_id: str, data: dict[str, Any]) -> None:
        """Initialize repair flow."""
        self.issue_id = issue_id
        self.issue_data = data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user to complete issue-specific recovery steps."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                description_placeholders={"issue": self.issue_id.replace("_", " ")},
            )

        entry_id = self.issue_data.get("entry_id")
        if isinstance(entry_id, str) and self.hass.config_entries.async_get_entry(
            entry_id
        ):
            await self.hass.config_entries.async_reload(entry_id)
        return self.async_create_entry(title="", data={})
