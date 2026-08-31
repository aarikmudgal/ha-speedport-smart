"""Tests for Speedport Smart configuration flows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
)

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportConnectionError,
    SpeedportInvalidCredentialsError,
    SpeedportSessionBusyError,
)
from custom_components.speedport_smart.config_flow import (
    CannotConnectError,
    InvalidAuthError,
    RouterBusyError,
    ValidationResult,
    async_validate_input,
)
from custom_components.speedport_smart.const import (
    CONF_ENABLE_CONTROLS,
    CONF_FAST_INTERVAL,
    CONF_HOST,
    CONF_NORMAL_INTERVAL,
    CONF_SLOW_INTERVAL,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.speedport_smart.models import RouterInfo

USER_INPUT = {
    CONF_HOST: "speedport.ip",
    CONF_PASSWORD: "router-password",
    CONF_USE_HTTPS: False,
    CONF_VERIFY_SSL: False,
}


@pytest.fixture(autouse=True)
def mock_dashboard_dependencies(hass: HomeAssistant) -> None:
    """Keep flow tests independent from the separately packaged HA frontend."""
    mock_integration(hass, MockModule("frontend"))
    mock_integration(hass, MockModule("panel_custom"))


async def test_user_flow_success_and_duplicate(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """User flow validates router, persists normalized data, and rejects duplicate."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with (
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speedport Smart 4R Typ A"
    assert result["data"] == USER_INPUT

    with patch(
        "custom_components.speedport_smart.config_flow.async_validate_input",
        AsyncMock(return_value=validation),
    ):
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (InvalidAuthError, "invalid_auth"),
        (RouterBusyError, "router_busy"),
        (CannotConnectError, "cannot_connect"),
        (RuntimeError, "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    exception: type[Exception],
    error: str,
) -> None:
    """Validation errors remain actionable in form."""
    with patch(
        "custom_components.speedport_smart.config_flow.async_validate_input",
        AsyncMock(side_effect=exception),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_reauth_and_reconfigure(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Credentials and connection settings update through supported lifecycle flows."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Old title",
        data=USER_INPUT,
        unique_id="sp4r-test-001",
    )
    entry.add_to_hass(hass)
    validation = ValidationResult("New title", "sp4r-test-001", router_info)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["step_id"] == "reconfigure"
    changed = {**USER_INPUT, CONF_HOST: "192.168.2.1"}
    with (
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], changed
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.2.1"
    assert entry.title == "New title"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Options flow stores polling intervals and explicit control opt-in."""
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    options = {
        CONF_ENABLE_CONTROLS: True,
        CONF_FAST_INTERVAL: 5,
        CONF_NORMAL_INTERVAL: 30,
        CONF_SLOW_INTERVAL: 300,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == options


@pytest.mark.parametrize(
    ("protocol_error", "flow_error"),
    [
        (SpeedportInvalidCredentialsError("bad"), InvalidAuthError),
        (SpeedportAuthenticationError("expired"), CannotConnectError),
        (SpeedportSessionBusyError("busy"), RouterBusyError),
        (SpeedportConnectionError("offline"), CannotConnectError),
    ],
)
async def test_validate_input_maps_protocol_errors(
    hass: HomeAssistant,
    protocol_error: Exception,
    flow_error: type[Exception],
) -> None:
    """Connection probe closes temporary client and maps protocol failures."""
    client = MagicMock()
    client.setup = AsyncMock(side_effect=protocol_error)
    client.close = AsyncMock()
    with (
        patch(
            "custom_components.speedport_smart.config_flow.SpeedportClient",
            return_value=client,
        ),
        pytest.raises(flow_error),
    ):
        await async_validate_input(hass, USER_INPUT, session=MagicMock())
    client.close.assert_awaited_once()


async def test_validate_input_fallback_title(
    hass: HomeAssistant,
) -> None:
    """Host provides identity fallback when router omits serial and model."""
    client = MagicMock()
    client.router_info = None
    client.setup = AsyncMock()
    client.close = AsyncMock()
    with patch(
        "custom_components.speedport_smart.config_flow.SpeedportClient",
        return_value=client,
    ):
        result = await async_validate_input(
            hass,
            USER_INPUT,
            session=MagicMock(),
        )
    assert result.unique_id == "speedport.ip"
    assert result.title == "Telekom Speedport Smart (speedport.ip)"
    client.close.assert_awaited_once()
