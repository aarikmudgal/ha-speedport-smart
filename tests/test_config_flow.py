"""Tests for Speedport Smart configuration flows."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
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
    async_probe_discovered_router,
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
    CONF_WAN_INTERVAL,
    DOMAIN,
)
from custom_components.speedport_smart.models import RouterInfo

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

USER_INPUT = {
    CONF_HOST: "speedport.ip",
    CONF_PASSWORD: "router-password",
    CONF_USE_HTTPS: False,
    CONF_VERIFY_SSL: False,
}
DISCOVERY_INPUT = {
    CONF_PASSWORD: "router-password",
    CONF_USE_HTTPS: False,
    CONF_VERIFY_SSL: False,
}


def _dhcp_info(
    *, ip: str = "192.168.2.1", macaddress: str = "AA:BB:CC:DD:EE:FF"
) -> SimpleNamespace:
    """Return minimal DHCP discovery data."""
    return SimpleNamespace(ip=ip, hostname="speedport", macaddress=macaddress)


def _ssdp_info(
    *,
    location: str = "http://192.168.2.1:49000/rootDesc.xml",
    udn: str | None = "uuid:speedport-test",
    usn: str = "uuid:speedport-test::upnp:rootdevice",
) -> SimpleNamespace:
    """Return minimal SSDP discovery data."""
    return SimpleNamespace(
        ssdp_location=location,
        ssdp_udn=udn,
        ssdp_usn=usn,
        upnp={},
    )


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
    ("source", "discovery_info"),
    [
        (config_entries.SOURCE_DHCP, _dhcp_info()),
        (config_entries.SOURCE_SSDP, _ssdp_info()),
    ],
)
async def test_discovery_confirms_supported_smart_after_read_only_validation(
    hass: HomeAssistant,
    router_info: RouterInfo,
    source: str,
    discovery_info: SimpleNamespace,
) -> None:
    """Public identity precedes confirmation and full read-only validation."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(return_value=validation),
        ) as probe,
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ) as validate,
        patch(
            "custom_components.speedport_smart.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source},
            data=discovery_info,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "confirm"
        assert result["description_placeholders"] == {CONF_HOST: "192.168.2.1"}
        probe.assert_awaited_once_with(hass, "192.168.2.1")
        validate.assert_not_awaited()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], DISCOVERY_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Speedport Smart 4R Typ A"
    assert result["data"] == {**DISCOVERY_INPUT, CONF_HOST: "192.168.2.1"}
    assert result["result"].unique_id == "sp4r-test-001"
    validate.assert_awaited_once_with(
        hass, {**DISCOVERY_INPUT, CONF_HOST: "192.168.2.1"}
    )


@pytest.mark.parametrize(
    "router_info",
    [
        None,
        RouterInfo(model="Speedport", serial_number="generic-speedport"),
        RouterInfo(model="Speedport Pro Plus", serial_number="speedport-pro"),
        RouterInfo(model="Speedport Smart 3", serial_number="smart-3"),
        RouterInfo(model="Speedport Smart 4 Plus", serial_number="smart-4-plus"),
        RouterInfo(model="Speedport Smart 4 R Typ A", serial_number="ssdp-spelling"),
        RouterInfo(model="Speedport Smart 4R Typ B", serial_number="smart-4r-b"),
        RouterInfo(model="Speedport Smart 4R Typ A", serial_number=None),
        RouterInfo(model=None, serial_number="malformed-model"),  # type: ignore[arg-type]
    ],
)
async def test_discovery_rejects_unproven_or_unrelated_router_models(
    hass: HomeAssistant, router_info: RouterInfo | None
) -> None:
    """Public identity rejects adjacent or malformed models before prompting."""
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(
                return_value=ValidationResult("Candidate", "candidate", router_info)
            ),
        ),
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(),
        ) as validate,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"
    validate.assert_not_awaited()


async def test_discovery_deduplicates_normalized_ipv4_host(
    hass: HomeAssistant,
) -> None:
    """Equivalent IPv4 text is rejected before any router validation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**USER_INPUT, CONF_HOST: " 192.168.2.1. "},
        unique_id="existing-router",
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(),
        ) as probe,
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(),
        ) as validate,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(ip=" 192.168.2.1 "),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_awaited()
    validate.assert_not_awaited()


async def test_discovery_deduplicates_serial_without_updating_existing_entry(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Untrusted discovery cannot relocate a configured serial to another host."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            **USER_INPUT,
            CONF_HOST: "192.168.2.254",
            CONF_PASSWORD: "existing-password",
            CONF_USE_HTTPS: True,
            CONF_VERIFY_SSL: True,
        },
        unique_id="sp4r-test-001",
    )
    entry.add_to_hass(hass)
    original_data = dict(entry.data)
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(
                return_value=ValidationResult(
                    "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
                )
            ),
        ),
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(),
        ) as validate,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == original_data
    validate.assert_not_awaited()


async def test_discovery_confirmation_does_not_update_entry_created_during_flow(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """A concurrent entry wins without discovery changing its connection data."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ),
    ):
        discovery = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                **USER_INPUT,
                CONF_HOST: "192.168.2.254",
                CONF_PASSWORD: "existing-password",
                CONF_USE_HTTPS: True,
                CONF_VERIFY_SSL: True,
            },
            unique_id="sp4r-test-001",
        )
        entry.add_to_hass(hass)
        original_data = dict(entry.data)
        result = await hass.config_entries.flow.async_configure(
            discovery["flow_id"], DISCOVERY_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data == original_data


async def test_dhcp_and_ssdp_hints_for_same_host_share_one_flow(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Concurrent same-host protocol hints share one public identity probe."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with patch(
        "custom_components.speedport_smart.config_flow.async_probe_discovered_router",
        AsyncMock(return_value=validation),
    ) as probe:
        first = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
        assert first["type"] is FlowResultType.FORM
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_SSDP},
            data=_ssdp_info(),
        )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_in_progress"
    probe.assert_awaited_once_with(hass, "192.168.2.1")


async def test_different_hosts_with_same_public_serial_share_one_flow(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Stable public serial closes the cross-protocol changed-host race."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    probes_started = 0
    both_probes_started = asyncio.Event()
    release_probes = asyncio.Event()

    async def _probe(_hass: HomeAssistant, _host: str) -> ValidationResult:
        nonlocal probes_started
        probes_started += 1
        if probes_started == 2:
            both_probes_started.set()
        await release_probes.wait()
        return validation

    with patch(
        "custom_components.speedport_smart.config_flow.async_probe_discovered_router",
        AsyncMock(side_effect=_probe),
    ) as probe:
        dhcp_task = asyncio.create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_DHCP},
                data=_dhcp_info(),
            )
        )
        ssdp_task = asyncio.create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_SSDP},
                data=_ssdp_info(location="http://192.168.2.2/rootDesc.xml"),
            )
        )
        await both_probes_started.wait()
        release_probes.set()
        results = await asyncio.gather(dhcp_task, ssdp_task)

    forms = [result for result in results if result["type"] is FlowResultType.FORM]
    aborts = [result for result in results if result["type"] is FlowResultType.ABORT]
    assert len(forms) == 1
    assert len(aborts) == 1
    assert aborts[0]["reason"] == "already_in_progress"
    assert probe.await_count == 2


@pytest.mark.parametrize(
    ("validated_model", "validated_serial"),
    [
        ("Speedport Smart 4 Plus", "SP4R-TEST-001"),
        ("Speedport Smart 4R Typ A", "OTHER-SERIAL"),
    ],
)
async def test_discovery_rejects_identity_change_after_password_validation(
    hass: HomeAssistant,
    router_info: RouterInfo,
    validated_model: str,
    validated_serial: str,
) -> None:
    """Confirmation cannot switch model or serial after public preflight."""
    discovery = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    validated_info = RouterInfo(
        model=validated_model,
        firmware=router_info.firmware,
        serial_number=validated_serial,
    )
    validated = ValidationResult(
        validated_model, validated_serial.casefold(), validated_info
    )
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(return_value=discovery),
        ),
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validated),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], DISCOVERY_INPUT
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_manual_flow_wins_over_pending_discovery(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Manual setup can finish while same-serial discovery awaits confirmation."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with (
        patch(
            "custom_components.speedport_smart.config_flow."
            "async_probe_discovered_router",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.config_flow.async_validate_input",
            AsyncMock(return_value=validation),
        ),
        patch(
            "custom_components.speedport_smart.async_setup_entry",
            AsyncMock(return_value=True),
        ),
    ):
        discovery = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
        assert discovery["type"] is FlowResultType.FORM
        manual = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
        await hass.async_block_till_done()
    assert manual["type"] is FlowResultType.CREATE_ENTRY
    assert manual["result"].unique_id == "sp4r-test-001"


async def test_concurrent_manual_flows_still_deduplicate(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Manual priority handling does not permit two manual entries."""
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
        first = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        second = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        first = await hass.config_entries.flow.async_configure(
            first["flow_id"], USER_INPUT
        )
        second = await hass.config_entries.flow.async_configure(
            second["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()
    assert first["type"] is FlowResultType.CREATE_ENTRY
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_ssdp_https_location_does_not_select_management_https(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """SSDP transport metadata supplies only host; confirmation defaults to HTTP."""
    validation = ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    with patch(
        "custom_components.speedport_smart.config_flow.async_probe_discovered_router",
        AsyncMock(return_value=validation),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_SSDP},
            data=_ssdp_info(location="https://192.168.2.1/rootDesc.xml"),
        )
    values = result["data_schema"]({CONF_PASSWORD: "router-password"})
    assert values[CONF_USE_HTTPS] is False
    assert values[CONF_VERIFY_SSL] is False


async def test_public_discovery_probe_reads_status_without_password(
    hass: HomeAssistant, router_info: RouterInfo
) -> None:
    """Preflight uses only unauthenticated public status and closes its client."""
    client = MagicMock()
    client.get_status = AsyncMock(return_value=SimpleNamespace(info=router_info))
    client.setup = AsyncMock()
    client.close = AsyncMock()
    session = MagicMock()
    with patch(
        "custom_components.speedport_smart.config_flow.SpeedportClient",
        return_value=client,
    ) as client_factory:
        result = await async_probe_discovered_router(
            hass, "192.168.2.1", session=session
        )
    assert result == ValidationResult(
        "Speedport Smart 4R Typ A", "sp4r-test-001", router_info
    )
    client_factory.assert_called_once_with(
        session,
        "192.168.2.1",
        password=None,
        use_https=False,
        verify_ssl=False,
        tr064_http_port=5438,
        tr064_https_port=8443,
        owns_session=False,
    )
    client.get_status.assert_awaited_once_with()
    client.setup.assert_not_awaited()
    client.close.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (CannotConnectError(), "cannot_connect"),
        (RuntimeError(), "unknown"),
    ],
)
async def test_discovery_probe_failures_abort_with_translated_reason(
    hass: HomeAssistant, error: Exception, reason: str
) -> None:
    """Background preflight failures abort instead of opening a broken form."""
    with patch(
        "custom_components.speedport_smart.config_flow.async_probe_discovered_router",
        AsyncMock(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=_dhcp_info(),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.parametrize(
    "relative_path",
    ["strings.json", "translations/en.json", "translations/de.json"],
)
def test_discovery_probe_abort_reasons_are_translated(relative_path: str) -> None:
    """Every shipped backend locale covers preflight abort reasons."""
    component = Path(__file__).parents[1] / "custom_components" / "speedport_smart"
    document = json.loads((component / relative_path).read_text(encoding="utf-8"))
    abort = document["config"]["abort"]
    assert abort["cannot_connect"]
    assert abort["unknown"]


def test_manifest_uses_only_captured_narrow_discovery_hints() -> None:
    """Manifest matchers stay pinned to the captured Smart 4R advertisement."""
    component = Path(__file__).parents[1] / "custom_components" / "speedport_smart"
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dhcp"] == [{"hostname": "speedport*"}]
    assert manifest["ssdp"] == [
        {
            "deviceType": "urn:schemas-upnp-org:device:WLANAccessPointDevice:1",
            "manufacturer": "Deutsche Telekom AG",
            "modelName": "Speedport Smart 4 R Typ A",
        }
    ]


@pytest.mark.parametrize(
    ("source", "discovery_info"),
    [
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="fe80::1")),
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="8.8.8.8")),
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="127.0.0.1")),
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="169.254.1.1")),
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="224.0.0.1")),
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="0.0.0.0")),  # noqa: S104
        (config_entries.SOURCE_DHCP, _dhcp_info(ip="240.0.0.1")),
        (config_entries.SOURCE_SSDP, _ssdp_info(location="not-a-url")),
        (config_entries.SOURCE_SSDP, _ssdp_info(location="http://[bad")),
        (
            config_entries.SOURCE_SSDP,
            _ssdp_info(location="ftp://192.168.2.1/rootDesc.xml"),
        ),
    ],
)
async def test_discovery_rejects_nonlocal_or_malformed_network_hints(
    hass: HomeAssistant, source: str, discovery_info: SimpleNamespace
) -> None:
    """Only usable private-unicast IPv4 discovery locations reach a probe."""
    with patch(
        "custom_components.speedport_smart.config_flow.async_probe_discovered_router",
        AsyncMock(),
    ) as probe:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source},
            data=discovery_info,
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_discovery_info"
    probe.assert_not_awaited()


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
        CONF_WAN_INTERVAL: 0,
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
