"""Tests for Speedport runtime hub."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportCommandRejectedError,
    SpeedportConnectionError,
    SpeedportDecodeError,
    SpeedportError,
    SpeedportInvalidCredentialsError,
    SpeedportLoginLockedError,
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import (
    CandidateInventoryResult,
    CapabilityReport,
    DslMetrics,
    EndpointCapability,
    RouterInfo,
    RouterStatus,
    WanCounters,
    WanInterface,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_setup_and_grouped_data(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Hub discovers semantic capabilities and merges polling groups."""
    mock_speedport_client.capture_candidate_inventory = AsyncMock()
    mock_speedport_client.get_json.side_effect = lambda endpoint, **_kwargs: (
        {"use_wlan": True} if endpoint == "data/WLANBasic.json" else {"use_mesh": True}
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
    )

    await hub.async_setup()
    fast = await hub.async_update_group(PollGroup.FAST)
    normal = await hub.async_update_group(PollGroup.NORMAL)
    slow = await hub.async_update_group(PollGroup.SLOW)

    assert hub.router_identifier == "SP4R-TEST-001"
    assert hub.has_capability("internet")
    assert hub.has_capability("wan")
    assert hub.has_capability("wifi")
    assert hub.get("internet.state") is True
    assert hub.get(("wan", "interface", "alias")) == "BONDING"
    assert hub.get(("wan", "interface", "enabled")) is True
    assert hub.get("wifi.enabled") is True
    assert hub.get("mesh.enabled") is True
    assert fast.generation == 1
    assert normal.generation == 2
    assert slow.generation == 3
    assert hub.get("missing.path", "fallback") == "fallback"
    mock_speedport_client.capture_candidate_inventory.assert_not_awaited()


async def test_devicelist_families_share_one_normal_poll(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Clients and mesh topology share one authenticated DeviceList read."""
    capability_kwargs = {
        "endpoint": "data/DeviceList.json",
        "authenticated": True,
        "referer": "html/content/network/devices.html",
    }
    mock_speedport_client.setup.return_value = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "clients": EndpointCapability("clients", **capability_kwargs),
                "mesh_topology": EndpointCapability(
                    "mesh_topology", **capability_kwargs
                ),
            }
        ),
    )
    mock_speedport_client.get_json.return_value = {
        "addmdevice": [{"id": "client-1", "mdevice_mac": "AA:BB:CC:DD:EE:FF"}],
        "addmeshdevice": [
            {
                "id": "mesh-1",
                "mesh_name": "Mesh repeater",
                "mesh_downspeed": "1200000000",
            }
        ],
    }
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    await hub.async_setup()
    normal = await hub.async_update_group(PollGroup.NORMAL)
    slow = await hub.async_update_group(PollGroup.SLOW)

    mock_speedport_client.get_json.assert_awaited_once_with(
        "data/DeviceList.json",
        authenticated=True,
        referer="html/content/network/devices.html",
    )
    mock_speedport_client.observe_feature_data.assert_has_calls(
        [
            call("clients", mock_speedport_client.get_json.return_value),
            call("mesh_topology", mock_speedport_client.get_json.return_value),
        ]
    )
    mock_speedport_client.logout.assert_awaited_once()
    assert normal.data["clients"]["items"][0]["id"] == "client-1"
    assert normal.data["mesh"]["nodes"][0]["id"] == "mesh-1"
    assert slow.data["mesh"]["nodes"][0]["id"] == "mesh-1"


def test_observed_schema_is_diagnostics_only_and_copy_safe(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Observed response structure never enters state and cannot mutate its source."""
    mock_speedport_client.observed_feature_schema = MappingProxyType(
        {"wifi": (MappingProxyType({"path": "rows[].enabled", "shape": "boolean"}),)}
    )
    mock_speedport_client.observed_candidate_schema = MappingProxyType(
        {
            "wifi": (
                MappingProxyType(
                    {
                        "endpoint": "data/WLANBasic.json",
                        "authenticated": True,
                        "referer": "html/content/network/wlan_basic.html",
                        "schema": (
                            MappingProxyType(
                                {"path": "rows[].enabled", "shape": "boolean"}
                            ),
                        ),
                    }
                ),
            )
        }
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    first = hub.diagnostics()

    assert "observed_feature_schema" not in hub.data
    assert "observed_candidate_schema" not in hub.data
    assert first["observed_feature_schema"] == {
        "wifi": [{"path": "rows[].enabled", "shape": "boolean"}]
    }
    assert first["observed_candidate_schema"] == {
        "wifi": [
            {
                "endpoint": "data/WLANBasic.json",
                "authenticated": True,
                "referer": "html/content/network/wlan_basic.html",
                "schema": [{"path": "rows[].enabled", "shape": "boolean"}],
            }
        ]
    }
    first["observed_feature_schema"]["wifi"][0]["path"] = "changed"
    first["observed_candidate_schema"]["wifi"][0]["schema"][0]["path"] = "changed"
    assert hub.diagnostics()["observed_feature_schema"] == {
        "wifi": [{"path": "rows[].enabled", "shape": "boolean"}]
    }
    assert hub.diagnostics()["observed_candidate_schema"] == {
        "wifi": [
            {
                "endpoint": "data/WLANBasic.json",
                "authenticated": True,
                "referer": "html/content/network/wlan_basic.html",
                "schema": [{"path": "rows[].enabled", "shape": "boolean"}],
            }
        ]
    }


def test_management_feature_families_publish_their_normalized_roots(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Discovered endpoint aliases make their canonical read roots available."""
    feature_families = {
        "connection_privacy",
        "dect",
        "dns_rebind",
        "easy_support",
        "firmware",
        "lte",
        "mobile",
        "nas",
        "pbx",
        "phonebook",
        "port_blocking",
        "qos",
        "receiver",
        "system_services",
        "telephony",
        "usb_tethering",
        "wifi_access",
        "wifi_configuration",
        "wps",
    }
    report = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                family: EndpointCapability(
                    family,
                    f"data/{family}.json",
                    authenticated=True,
                )
                for family in feature_families
            }
        ),
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    hub._apply_capability_report(report)  # noqa: SLF001 - capability routing contract

    expected_roots = {
        "dect",
        "internet",
        "mobile",
        "pbx",
        "qos",
        "receiver",
        "security",
        "system",
        "telephony",
        "usb",
        "wifi",
    }
    assert feature_families <= hub.capabilities
    assert expected_roots <= hub.capabilities


async def test_detail_families_use_independent_exact_get_routes(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Summary evidence cannot hide safe schedule, VPN, or repeater detail."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi_schedule": EndpointCapability(
                    "wifi_schedule",
                    "data/WLANBasic.json",
                    authenticated=True,
                    referer="html/content/network/wlan_basic.html",
                ),
                "vpn_details": EndpointCapability(
                    "vpn_details",
                    "data/VPN.json",
                    authenticated=True,
                    referer="html/content/internet/vpn.html",
                ),
                "dect_repeater": EndpointCapability(
                    "dect_repeater",
                    "data/DECTRepeater.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_repeater.html",
                ),
                "usb": EndpointCapability(
                    "usb",
                    "data/NASDevice.json",
                    authenticated=True,
                    referer="html/content/network/nas_overview.html",
                ),
                "media_server": EndpointCapability(
                    "media_server",
                    "data/NASMediacenter.json",
                    authenticated=True,
                    referer="html/content/network/nas_mediacenter.html",
                ),
            }
        ),
    )

    async def feature_payload(endpoint: str, **_: object) -> dict[str, object]:
        return {
            "data/WLANBasic.json": {
                "wlan_timerule": "1",
                "wlan_dfrom": "07:30",
                "wlan_dto": "22:15",
            },
            "data/VPN.json": {
                "vpn_status": "1",
                "vpn_connected": "1",
                "addpeer": [{"connected": "1"}, {"connected": "0"}],
            },
            "data/DECTRepeater.json": {
                "addrepeater": [{"id": "1"}, {"id": "2"}],
            },
            "data/NASDevice.json": {
                "addnasdevice": [{"nas_device_name": "USB storage"}],
            },
            "data/NASMediacenter.json": {
                "use_media_server": "1",
                "addnasmediareplay": [
                    {"mediareplay_active": "1"},
                    {"mediareplay_active": "0"},
                ],
            },
        }[endpoint]

    mock_speedport_client.get_json.side_effect = feature_payload
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    await hub.async_setup()
    await hub.async_update_group(PollGroup.SLOW)

    mock_speedport_client.get_json.assert_has_awaits(
        [
            call(
                "data/WLANBasic.json",
                authenticated=True,
                referer="html/content/network/wlan_basic.html",
            ),
            call(
                "data/VPN.json",
                authenticated=True,
                referer="html/content/internet/vpn.html",
            ),
            call(
                "data/DECTRepeater.json",
                authenticated=True,
                referer="html/content/phone/phone_dect_repeater.html",
            ),
            call(
                "data/NASDevice.json",
                authenticated=True,
                referer="html/content/network/nas_overview.html",
            ),
            call(
                "data/NASMediacenter.json",
                authenticated=True,
                referer="html/content/network/nas_mediacenter.html",
            ),
        ],
        any_order=True,
    )
    assert mock_speedport_client.get_json.await_count == 5
    mock_speedport_client.logout.assert_awaited_once()
    assert {
        "wifi_schedule",
        "vpn_details",
        "dect_repeater",
        "usb",
        "media_server",
    } <= hub.capabilities
    assert {"wifi", "vpn", "dect"} <= hub.capabilities
    assert hub.get("wifi.schedule.daily_from") == "07:30"
    assert hub.get("vpn.connected_peer_count") == 1
    assert hub.get("dect.repeater_count") == 2
    assert hub.get("usb.storage_device_count") == 1
    assert hub.get("usb.media_share_count") == 2
    assert hub.get("usb.active_media_share_count") == 1


@pytest.mark.parametrize("detail_result", ["daily", "empty", "unsupported"])
async def test_detail_family_loss_preserves_healthy_base_sources(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    detail_result: str,
) -> None:
    """One missing detail source cannot clear overlapping healthy base state."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                ),
                "wifi_schedule": EndpointCapability(
                    "wifi_schedule",
                    "data/WLANBasic.json",
                    authenticated=True,
                    referer="html/content/network/wlan_basic.html",
                ),
                "vpn": EndpointCapability(
                    "vpn",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                ),
                "vpn_details": EndpointCapability(
                    "vpn_details",
                    "data/VPN.json",
                    authenticated=True,
                    referer="html/content/internet/vpn.html",
                ),
                "dect": EndpointCapability(
                    "dect",
                    "data/DECTStation.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_mobiles.html",
                ),
                "dect_repeater": EndpointCapability(
                    "dect_repeater",
                    "data/DECTRepeater.json",
                    authenticated=True,
                    referer="html/content/phone/phone_dect_repeater.html",
                ),
            }
        ),
    )
    phase = {"detail": "initial"}

    async def feature_payload(endpoint: str, **_: object) -> dict[str, object]:
        base_payloads: dict[str, dict[str, object]] = {
            "data/SecureStatus.json": {
                "use_wlan": "1",
                "wlan_time_active": "1",
                "vpn_active": "1",
                "vpn_connected": "1",
            },
            "data/DECTStation.json": {"use_dect": "1"},
        }
        if endpoint in base_payloads:
            return base_payloads[endpoint]
        if phase["detail"] == "unsupported":
            raise SpeedportUnsupportedError("detail endpoint disappeared")
        if phase["detail"] == "empty":
            return {}
        if phase["detail"] == "daily":
            if endpoint == "data/WLANBasic.json":
                return {
                    "wlan_timerule": "1",
                    "wlan_dfrom": "07:30",
                    "wlan_dto": "22:15",
                }
            return {}
        return {
            "data/WLANBasic.json": {
                "use_wlan": "0",
                "wlan_timerule": "2",
                "wlan_time_mo_from": "08:00",
                "wlan_time_mo_to": "21:00",
            },
            "data/VPN.json": {
                "enabled": "0",
                "addpeer": [{"connected": "1"}, {"connected": "0"}],
            },
            "data/DECTRepeater.json": {
                "use_dect": "0",
                "addrepeater": [{"id": "1"}, {"id": "2"}],
            },
        }[endpoint]

    mock_speedport_client.get_json.side_effect = feature_payload
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)

    assert hub.get("wifi.enabled") is True
    assert hub.get("vpn.enabled") is True
    assert hub.get("dect.enabled") is True
    assert hub.get("wifi.schedule.weekly_day_count") == 1
    assert hub.get("vpn.connected_peer_count") == 1
    assert hub.get("dect.repeater_count") == 2

    phase["detail"] = detail_result
    await hub.async_update_group(PollGroup.SLOW)

    assert hub.get("wifi.enabled") is True
    assert hub.get("wifi.schedule_enabled") is True
    assert hub.get("vpn.enabled") is True
    assert hub.get("vpn.connected") is True
    assert hub.get("dect.enabled") is True
    assert hub.get("wifi.schedule.weekly_day_count") is None
    assert hub.get("vpn.connected_peer_count") is None
    assert hub.get("dect.repeater_count") is None
    if detail_result == "daily":
        assert hub.get("wifi.schedule.daily_from") == "07:30"
        assert hub.get("wifi.schedule.daily_to") == "22:15"


async def test_rate_delta_and_counter_reset(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_interface: WanInterface,
) -> None:
    """Rates use monotonic deltas and counter reset emits no spike."""
    times = iter((100.0, 105.0, 110.0))
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
        rate_window_seconds=10,
        monotonic_time=lambda: next(times),
    )

    first = WanCounters(wan_interface, 1_000, 500, datetime.now(UTC))
    second = WanCounters(wan_interface, 6_001_000, 1_500_500, datetime.now(UTC))
    reset = WanCounters(wan_interface, 10, 5, datetime.now(UTC))

    first_data = hub._normalise_wan_counters(  # noqa: SLF001
        first, download_capacity=10_000_000, upload_capacity=4_000_000
    )
    second_data = hub._normalise_wan_counters(  # noqa: SLF001
        second, download_capacity=10_000_000, upload_capacity=4_000_000
    )
    reset_data = hub._normalise_wan_counters(  # noqa: SLF001
        reset, download_capacity=10_000_000, upload_capacity=4_000_000
    )

    assert first_data["download_rate_bps"] is None
    assert second_data["download_rate_bps"] == 9_600_000
    assert second_data["upload_rate_bps"] == 2_400_000
    assert second_data["download_utilization"] == 96
    assert second_data["upload_utilization"] == 60
    assert reset_data["download_rate_bps"] is None
    assert reset_data["upload_rate_bps"] is None


async def test_fast_wan_busy_uses_telemetry_backoff_only(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A busy ToTR64 lease backs off counters without blocking web controls."""
    now = [100.0]
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "busy"
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    await hub.async_update_group(PollGroup.FAST)
    assert hub.get("management.access.state") == "available"
    assert hub.get("wan.download_rate_bps") is None
    assert mock_speedport_client.get_wan_counters.await_count == 1
    assert mock_speedport_client.get_wan_counters.await_args.kwargs == {
        "busy_retries": 0
    }
    assert hub._protected_retry_at == 0.0  # noqa: SLF001

    mock_speedport_client.get_wan_counters.side_effect = None
    mock_speedport_client.get_wan_counters.return_value = WanCounters(
        WanInterface(index=1, alias="WAN", name="wan", status="Up"),
        2_000,
        1_000,
        datetime.now(UTC),
    )
    now[0] = 101.0
    await hub.async_update_group(PollGroup.FAST)

    assert mock_speedport_client.get_wan_counters.await_count == 1
    assert hub.get("management.access.state") == "available"
    assert hub.get("diagnostics.problem") is False

    now[0] = 106.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 2
    assert hub.get("management.access.state") == "available"

    now[0] = 107.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_status.await_count == 4
    assert mock_speedport_client.get_wan_counters.await_count == 2
    assert hub.get("wan.bytes_received") == 2_000


async def test_public_status_failure_does_not_starve_due_wan_poll(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_status: RouterStatus,
) -> None:
    """A failed public source is unavailable without starving WAN polling."""
    now = [100.0]
    mock_speedport_client.get_status.side_effect = (
        router_status,
        SpeedportConnectionError("temporary"),
        router_status,
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=5,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    await hub.async_update_group(PollGroup.FAST)
    assert hub.get("internet.state") is True
    assert mock_speedport_client.get_status.await_count == 1
    assert mock_speedport_client.get_wan_counters.await_count == 1
    assert hub.get("wan.bytes_received") == 10_000

    now[0] = 105.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_status.await_count == 2
    assert mock_speedport_client.get_wan_counters.await_count == 2
    assert hub.get("internet.state") is None
    assert hub.get("dsl.state") is None
    assert hub.get("wan.bytes_received") == 10_000
    assert hub.diagnostics()["endpoint_errors"]["status"] == (
        "SpeedportConnectionError"
    )

    now[0] = 110.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_status.await_count == 3
    assert mock_speedport_client.get_wan_counters.await_count == 3
    assert hub.get("internet.state") is True
    assert hub.get("dsl.state") is True
    assert "status" not in hub.diagnostics()["endpoint_errors"]


async def test_wan_transient_failures_preserve_totals_and_do_not_inflate_busy_retry(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_interface: WanInterface,
) -> None:
    """Transient failures retain totals and do not poison 9801 backoff."""
    now = [100.0]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=300,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    mock_speedport_client.get_wan_counters.return_value = WanCounters(
        wan_interface,
        10_000,
        5_000,
        datetime.now(UTC),
        packets_received=100,
        packets_sent=50,
    )
    await hub.async_update_group(PollGroup.FAST)
    now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001
    mock_speedport_client.get_wan_counters.return_value = WanCounters(
        wan_interface,
        20_000,
        10_000,
        datetime.now(UTC),
        packets_received=200,
        packets_sent=100,
    )
    await hub.async_update_group(PollGroup.FAST)
    assert hub.get("wan.download_rate_bps") is not None

    mock_speedport_client.get_wan_counters.side_effect = SpeedportConnectionError(
        "temporary"
    )
    for _ in range(4):
        now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001
        await hub.async_update_group(PollGroup.FAST)

    assert hub.get("wan.bytes_received") == 20_000
    assert hub.get("wan.bytes_sent") == 10_000
    assert hub.get("wan.packets_received") == 200
    assert hub.get("wan.packets_sent") == 100
    assert hub.get("wan.download_rate_bps") is None
    assert hub.get("wan.upload_rate_bps") is None

    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "busy"
    )
    now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001
    await hub.async_update_group(PollGroup.FAST)

    telemetry = hub.diagnostics()["telemetry"]["wan_counters"]
    assert telemetry["retry_in_seconds"] == 5.0
    assert hub.get("wan.bytes_received") == 20_000


async def test_wan_failure_breaks_clean_cadence_proof_streak(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Successes separated by a failed sample cannot prove a faster cadence."""
    now = [100.0]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=300,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    for _ in range(11):
        await hub.async_update_group(PollGroup.FAST)
        now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001

    assert hub._wan_counter_success_streak == 11  # noqa: SLF001
    assert hub._wan_counter_effective_interval == 5.0  # noqa: SLF001
    mock_speedport_client.get_wan_counters.side_effect = SpeedportConnectionError(
        "temporary"
    )
    await hub.async_update_group(PollGroup.FAST)
    assert hub._wan_counter_success_streak == 0  # noqa: SLF001

    mock_speedport_client.get_wan_counters.side_effect = None
    now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001
    await hub.async_update_group(PollGroup.FAST)

    assert hub._wan_counter_success_streak == 1  # noqa: SLF001
    assert hub._wan_counter_effective_interval == 5.0  # noqa: SLF001
    assert hub.wan_counter_telemetry["last_stable_interval_seconds"] is None


async def test_slow_wan_error_reschedules_from_request_completion(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A slow failed request cannot trigger another attempt on the next tick."""
    now = [100.0]

    async def delayed_error(**_kwargs: object) -> None:
        now[0] += 10.0
        raise SpeedportConnectionError("temporary")

    mock_speedport_client.get_wan_counters.side_effect = delayed_error
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=300,
        wan_counter_interval_seconds=2,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    await hub.async_update_group(PollGroup.FAST)

    assert now[0] == 110.0
    assert hub._wan_counter_next_poll_at == 112.0  # noqa: SLF001
    assert mock_speedport_client.get_wan_counters.await_count == 1

    now[0] = 111.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 1

    now[0] = 112.0
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == 2


async def test_pending_wan_counter_capability_recovers_after_busy_setup(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    wan_interface: WanInterface,
) -> None:
    """A setup-time 9801 remains exposed and recovers without a reload."""
    now = [100.0]
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        tr064=True,
        wan_counters=False,
        authenticated_json=True,
        failures=MappingProxyType(
            {"wan_counters": "SpeedportSessionBusyError: ToTR64 session busy"}
        ),
    )
    mock_speedport_client.get_wan_counters.side_effect = (
        SpeedportSessionBusyError("busy"),
        WanCounters(wan_interface, 12_000, 6_000, datetime.now(UTC)),
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    assert hub.has_capability("wan_counters")
    await hub.async_update_group(PollGroup.FAST)
    assert hub.has_capability("wan_counters")
    assert hub.get("wan.bytes_received") is None

    now[0] = 106.0
    await hub.async_update_group(PollGroup.FAST)

    assert hub.has_capability("wan_counters")
    assert hub.get("wan.bytes_received") == 12_000
    assert hub.get("wan.sampled_at") is not None
    assert hub.capability_report is not None
    assert hub.capability_report.wan_counters
    assert "wan_counters" not in hub.diagnostics()["endpoint_errors"]


@pytest.mark.parametrize(
    ("independent_wan", "expected_wan"),
    [(False, False), (True, True)],
)
async def test_pending_wan_counter_capability_is_removed_after_unsupported_probe(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    *,
    independent_wan: bool,
    expected_wan: bool,
) -> None:
    """A disproved setup probe removes only capabilities it contributed."""
    feature_endpoints = (
        MappingProxyType({"wan": EndpointCapability("wan", "data/WAN.json")})
        if independent_wan
        else MappingProxyType({})
    )
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        tr064=True,
        wan_counters=False,
        authenticated_json=True,
        feature_endpoints=feature_endpoints,
        failures=MappingProxyType(
            {"wan_counters": "SpeedportSessionBusyError: ToTR64 session busy"}
        ),
    )
    mock_speedport_client.get_wan_counters.side_effect = SpeedportUnsupportedError(
        "unsupported"
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()

    assert hub.has_capability("wan_counters")
    assert hub.has_capability("wan")
    await hub.async_update_group(PollGroup.FAST)

    assert not hub.has_capability("wan_counters")
    assert hub.has_capability("wan") is expected_wan
    assert hub.capability_report is not None
    assert "wan_counters" not in hub.capability_report.failures


async def test_repeated_wan_busy_uses_exponential_retry_without_raising_floor(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Repeated 9801 responses slow retries without rejecting a proven cadence."""
    now = [100.0]
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "busy"
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    for retry_seconds in (5.0, 10.0, 20.0, 40.0, 60.0):
        await hub.async_update_group(PollGroup.FAST)
        telemetry = hub.diagnostics()["telemetry"]["wan_counters"]
        assert telemetry["retry_in_seconds"] == retry_seconds
        assert telemetry["runtime_floor_seconds"] == 1.0
        assert hub.get("management.access.state") == "available"
        assert hub.get("diagnostics.problem") is False
        now[0] += retry_seconds

    assert mock_speedport_client.get_wan_counters.await_count == 5


async def test_wan_counter_auto_cadence_learns_independently_and_holds_after_busy(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Auto cadence learns 5→4→3→2→1 and holds after a busy response."""
    now = [100.0]
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=300,
        wan_counter_interval_seconds=0,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    for expected_interval in (4.0, 3.0, 2.0, 1.0):
        for _ in range(12):
            await hub.async_update_group(PollGroup.FAST)
            now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001
        assert hub._wan_counter_effective_interval == expected_interval  # noqa: SLF001

    assert mock_speedport_client.get_status.await_count == 1
    assert hub.diagnostics()["telemetry"]["wan_counters"]["state"] == "learning"
    confirmed_total = hub.get("wan.bytes_received")
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "busy"
    )

    await hub.async_update_group(PollGroup.FAST)

    telemetry = hub.diagnostics()["telemetry"]["wan_counters"]
    assert telemetry["effective_interval_seconds"] == 2.0
    assert telemetry["state"] == "retrying"
    assert telemetry["runtime_floor_seconds"] == 2.0
    assert telemetry["last_stable_interval_seconds"] == 2.0
    assert hub.get("wan.bytes_received") == confirmed_total
    assert hub.get("diagnostics.problem") is False

    mock_speedport_client.get_wan_counters.side_effect = None
    now[0] = hub._wan_counter_retry_at  # noqa: SLF001
    for _ in range(12):
        await hub.async_update_group(PollGroup.FAST)
        now[0] = hub._wan_counter_next_poll_at  # noqa: SLF001

    telemetry = hub.diagnostics()["telemetry"]["wan_counters"]
    assert telemetry["effective_interval_seconds"] == 2.0
    assert telemetry["state"] == "limited"
    assert "wan_counters" not in hub.diagnostics()["endpoint_errors"]


def test_wan_auto_target_is_stable_only_after_target_samples_are_proven(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Reaching the target starts a probe; clean samples prove it stable."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        wan_counter_interval_seconds=0,
        monotonic_time=lambda: 100.0,
    )
    hub._wan_counter_effective_interval = 1.0  # noqa: SLF001
    hub._wan_counter_last_stable_interval = 2.0  # noqa: SLF001

    initial = hub.diagnostics()["telemetry"]["wan_counters"]
    assert initial["state"] == "learning"
    assert initial["last_stable_interval_seconds"] is None
    for _ in range(12):
        hub._record_wan_counter_success()  # noqa: SLF001

    telemetry = hub.diagnostics()["telemetry"]["wan_counters"]
    assert telemetry["last_stable_interval_seconds"] == 1.0
    assert telemetry["state"] == "stable"


def test_wan_telemetry_accessors_return_small_immutable_snapshots(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Hot-path telemetry access avoids exporting the full diagnostic tree."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: 100.0,
    )
    hub._endpoint_errors["wan_counters"] = "SpeedportConnectionError"  # noqa: SLF001

    telemetry = hub.wan_counter_telemetry
    endpoint_errors = hub.endpoint_errors

    assert telemetry["mode"] == "auto"
    assert telemetry["effective_interval_seconds"] == 5.0
    assert "data" not in telemetry
    assert hub.has_endpoint_error("wan_counters")
    assert endpoint_errors == {"wan_counters": "SpeedportConnectionError"}
    with pytest.raises(TypeError):
        telemetry["state"] = "stable"  # type: ignore[index]
    with pytest.raises(TypeError):
        endpoint_errors["status"] = "SpeedportConnectionError"  # type: ignore[index]


def test_manual_wan_counter_target_is_decoupled_from_public_status(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An advanced manual target does not change the public status interval."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=30,
        wan_counter_interval_seconds=2,
    )

    telemetry = hub.diagnostics()["telemetry"]
    assert telemetry["public_status"]["interval_seconds"] == 30
    assert telemetry["wan_counters"]["mode"] == "manual"
    assert telemetry["wan_counters"]["target_interval_seconds"] == 2
    assert telemetry["wan_counters"]["effective_interval_seconds"] == 2


async def test_transitions_and_fallback_identity(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    router_info: RouterInfo,
) -> None:
    """Hub emits only changes after initial state and has stable fallback ID."""
    now = [100.0]
    no_serial = RouterInfo(model="Speedport", serial_number=None)
    mock_speedport_client.router_info = no_serial
    mock_speedport_client.setup.return_value = CapabilityReport(status_json=True)
    mock_speedport_client.get_status.side_effect = (
        RouterStatus(info=no_serial, internet_state="online"),
        RouterStatus(info=no_serial, internet_state="offline"),
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry-id",
        public_status_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()

    first = await hub.async_update_group(PollGroup.FAST)
    now[0] = 101.0
    second = await hub.async_update_group(PollGroup.FAST)

    assert hub.router_identifier == "entry-id"
    assert first.transitions == ()
    assert len(second.transitions) == 1
    assert second.transitions[0].path == "internet.state"
    assert second.transitions[0].previous is True
    assert second.transitions[0].current is False
    assert router_info.serial_number != hub.router_identity.serial_number


async def test_feature_failure_isolation_and_authentication(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Optional family failure does not erase another family or mask auth loss."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability("wifi", "wifi"),
                "clients": EndpointCapability("clients", "clients"),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "wifi":
            raise SpeedportConnectionError("temporary")
        return {"mdevice_mac": ["AA:BB:CC:DD:EE:FF"]}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    await hub.async_update_group(PollGroup.NORMAL)
    assert len(hub.get("clients.items")) == 1
    assert hub.get("wifi") is None
    assert hub.diagnostics()["endpoint_errors"] == {"wifi": "SpeedportConnectionError"}

    mock_speedport_client.get_json.side_effect = SpeedportInvalidCredentialsError(
        "invalid"
    )
    with pytest.raises(SpeedportInvalidCredentialsError):
        await hub.async_update_group(PollGroup.NORMAL)


async def test_protected_decode_failure_marks_management_unavailable_and_backs_off(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A failed protected session cannot leave management falsely available."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "clients": EndpointCapability("clients", "clients", authenticated=True),
                "wifi": EndpointCapability("wifi", "wifi", authenticated=True),
            }
        ),
    )
    fail_protected = False

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if fail_protected:
            raise SpeedportDecodeError("encrypted response authentication failed")
        if endpoint == "clients":
            return {"mdevice_mac": ["AA:BB:CC:DD:EE:FF"]}
        return {"use_wlan": True}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    assert hub.get("management.access.state") == "available"
    assert hub.get("wifi.enabled") is True

    fail_protected = True
    await hub.async_update_group(PollGroup.NORMAL)

    assert hub.get("management.access.state") == "unavailable"
    assert hub.get("wifi.enabled") is None
    assert hub.get("clients.items") is None
    assert hub.diagnostics()["endpoint_errors"] == {
        "clients": "SpeedportDecodeError",
        "wifi": "SpeedportDecodeError",
    }

    request_count = mock_speedport_client.get_json.await_count
    await hub.async_update_group(PollGroup.NORMAL)
    assert mock_speedport_client.get_json.await_count == request_count
    assert hub.get("management.access.state") == "unavailable"


async def test_protected_failure_restores_latest_public_status_values(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Protected loss clears only fields without a public Status fallback."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "internet": EndpointCapability(
                    "internet", "internet", authenticated=True
                ),
                "dsl": EndpointCapability("dsl", "dsl", authenticated=True),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "internet":
            return {
                "status": "online",
                "download_capacity_bps": 190_000_000,
                "upload_capacity_bps": 39_000_000,
                "public_ip_v4": "192.0.2.1",
            }
        return {
            "dsl_status": "up",
            "dsl_downstream_bps": 203_000_000,
            "dsl_upstream_bps": 41_000_000,
            "dsl_snr_downstream": 11.5,
        }

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()

    await hub.async_update_group(PollGroup.FAST)
    public_values = {
        "internet_state": hub.get("internet.state"),
        "download_capacity": hub.get("internet.download_capacity_bps"),
        "upload_capacity": hub.get("internet.upload_capacity_bps"),
        "dsl_state": hub.get("dsl.state"),
        "downstream": hub.get("dsl.downstream_bps"),
        "upstream": hub.get("dsl.upstream_bps"),
    }
    assert all(value is not None for value in public_values.values())

    await hub.async_update_group(PollGroup.NORMAL)
    assert hub.get("internet.ipv4_address") == "192.0.2.1"
    assert hub.get("dsl.snr_downstream_db") == 11.5

    mock_speedport_client.get_json.side_effect = SpeedportSessionBusyError("busy")
    await hub.async_update_group(PollGroup.NORMAL)

    assert hub.get("internet.state") == public_values["internet_state"]
    assert (
        hub.get("internet.download_capacity_bps") == public_values["download_capacity"]
    )
    assert hub.get("internet.upload_capacity_bps") == public_values["upload_capacity"]
    assert hub.get("dsl.state") == public_values["dsl_state"]
    assert hub.get("dsl.downstream_bps") == public_values["downstream"]
    assert hub.get("dsl.upstream_bps") == public_values["upstream"]
    assert hub.get("internet.ipv4_address") is None
    assert hub.get("dsl.snr_downstream_db") is None

    request_count = mock_speedport_client.get_json.await_count
    await hub.async_update_group(PollGroup.NORMAL)
    assert mock_speedport_client.get_json.await_count == request_count
    assert hub.get("internet.state") == public_values["internet_state"]
    assert hub.get("internet.download_capacity_bps") is not None
    assert hub.get("internet.upload_capacity_bps") is not None
    assert hub.get("dsl.state") == public_values["dsl_state"]
    assert hub.get("dsl.downstream_bps") is not None
    assert hub.get("dsl.upstream_bps") is not None
    assert hub.get("internet.ipv4_address") is None
    assert hub.get("dsl.snr_downstream_db") is None


async def test_public_status_failure_does_not_restore_errored_family_cache(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Two failed sources cannot revive an older overlapping family value."""
    now = [100.0]
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi",
                    "data/SecureStatus.json",
                    authenticated=True,
                    referer="html/content/overview/index.html",
                )
            }
        ),
    )
    mock_speedport_client.get_status.side_effect = (
        RouterStatus(
            info=RouterInfo(model="Speedport Smart 4R"),
            raw={"use_wlan": "1"},
        ),
        SpeedportConnectionError("public status unavailable"),
    )
    mock_speedport_client.get_json.return_value = {"use_wlan": "0"}
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        public_status_interval_seconds=1,
        monotonic_time=lambda: now[0],
    )

    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    await hub.async_update_group(PollGroup.NORMAL)
    assert hub.get("wifi.enabled") is False

    mock_speedport_client.get_json.side_effect = SpeedportSessionBusyError("busy")
    await hub.async_update_group(PollGroup.NORMAL)
    assert hub.get("wifi.enabled") is True
    assert hub.diagnostics()["endpoint_errors"]["wifi"] == ("SpeedportSessionBusyError")

    now[0] = 101.0
    await hub.async_update_group(PollGroup.FAST)

    assert hub.get("wifi.enabled") is None
    assert hub.diagnostics()["endpoint_errors"] == {
        "status": "SpeedportConnectionError",
        "wifi": "SpeedportSessionBusyError",
    }


async def test_protected_failure_invalidates_every_poll_group_immediately(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Session loss clears cached protected data outside the current poll group."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    assert hub.get("wifi.enabled") is True
    assert hub.get("nat.port_forwarding_enabled") is True
    assert hub.get("internet.state") is True

    slow_coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.SLOW, slow_coordinator)
    mock_speedport_client.get_json.side_effect = SpeedportSessionBusyError("busy")

    with patch.object(hub, "_create_management_issue") as create_issue:
        await hub.async_update_group(PollGroup.NORMAL)

    assert hub.get("management.access.state") == "blocked"
    create_issue.assert_called_once_with()
    assert hub.get("wifi.enabled") is None
    assert hub.get("nat.port_forwarding_enabled") is None
    assert hub.get("internet.state") is True
    slow_coordinator.async_set_updated_data.assert_called_once()
    propagated = slow_coordinator.async_set_updated_data.call_args.args[0]
    assert propagated.group is PollGroup.SLOW
    assert propagated.data["nat"]["port_forwarding_enabled"] is None

    slow_coordinator.reset_mock()
    await hub.async_update_group(PollGroup.NORMAL)
    slow_coordinator.async_set_updated_data.assert_not_called()


async def test_fast_wan_busy_preserves_protected_poll_groups(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A busy ToTR64 counter request degrades only live WAN telemetry."""
    now = [100.0]
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        tr064=True,
        wan_counters=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    mock_speedport_client.get_wan_counters.return_value = WanCounters(
        WanInterface(index=5, alias="BONDING", name="habond", status="Up"),
        10_000,
        5_000,
        datetime.now(UTC),
        packets_received=100,
        packets_sent=50,
        errors_received=2,
        errors_sent=1,
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    assert hub.get("wan.bytes_received") == 10_000
    assert hub.get("wan.packets_received") == 100
    normal_coordinator = MagicMock()
    slow_coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.NORMAL, normal_coordinator)
    hub.attach_coordinator(PollGroup.SLOW, slow_coordinator)
    mock_speedport_client.get_wan_counters.side_effect = SpeedportSessionBusyError(
        "busy"
    )
    now[0] = 106.0

    with patch.object(hub, "_create_management_issue") as create_issue:
        await hub.async_update_group(PollGroup.FAST)

    assert hub.get("management.access.state") == "available"
    create_issue.assert_not_called()
    assert hub.get("wan.bytes_received") == 10_000
    assert hub.get("wan.bytes_sent") == 5_000
    assert hub.get("wan.packets_received") == 100
    assert hub.get("wan.packets_sent") == 50
    assert hub.get("wan.errors_received") == 2
    assert hub.get("wan.errors_sent") == 1
    assert hub.get("wan.sampled_at") is not None
    assert hub.get("wan.download_rate_bps") is None
    assert hub.get("wan.upload_rate_bps") is None
    assert hub.get("wifi.enabled") is True
    assert hub.get("nat.port_forwarding_enabled") is True
    assert hub.get("internet.state") is True
    assert hub._protected_retry_at == 0.0  # noqa: SLF001
    normal_coordinator.async_set_updated_data.assert_not_called()
    slow_coordinator.async_set_updated_data.assert_not_called()

    counter_requests = mock_speedport_client.get_wan_counters.await_count
    await hub.async_update_group(PollGroup.FAST)
    assert mock_speedport_client.get_wan_counters.await_count == counter_requests
    assert hub.get("wan.bytes_received") == 10_000


async def test_dsl_busy_degrades_only_dsl_telemetry(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A busy ToTR64 DSL request does not block the web management session."""
    now = [100.0]
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        tr064=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    mock_speedport_client.get_dsl_metrics.return_value = DslMetrics(
        line_index=1,
        channel_index=1,
        status="Up",
        downstream_current_bps=204_413_000,
        upstream_current_bps=42_460_000,
        downstream_max_bps=230_000_000,
        upstream_max_bps=50_000_000,
        downstream_noise_margin_db=12.5,
        upstream_noise_margin_db=8.5,
        downstream_attenuation_db=4.0,
        upstream_attenuation_db=2.0,
        sampled_at=datetime.now(UTC),
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        monotonic_time=lambda: now[0],
    )
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    assert hub.get("wifi.enabled") is True
    assert hub.get("nat.port_forwarding_enabled") is True
    assert hub.get("dsl.snr_downstream_db") == 12.5

    slow_coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.SLOW, slow_coordinator)
    mock_speedport_client.get_dsl_metrics.side_effect = SpeedportSessionBusyError(
        "busy"
    )

    with patch.object(hub, "_create_management_issue") as create_issue:
        await hub.async_update_group(PollGroup.NORMAL)

    assert hub.get("management.access.state") == "available"
    create_issue.assert_not_called()
    assert hub.get("diagnostics.problem") is False
    assert hub.get("wifi.enabled") is True
    assert hub.get("nat.port_forwarding_enabled") is True
    assert hub.get("internet.state") is True
    assert hub.get("dsl.downstream_bps") == 204_413_000
    assert hub.get("dsl.snr_downstream_db") is None
    assert hub.get("dsl.attainable_downstream_bps") is None
    assert hub._protected_retry_at == 0.0  # noqa: SLF001
    slow_coordinator.async_set_updated_data.assert_not_called()

    mock_speedport_client.get_dsl_metrics.side_effect = None
    mock_speedport_client.get_dsl_metrics.return_value = DslMetrics(
        line_index=1,
        channel_index=1,
        status="Up",
        downstream_current_bps=204_413_000,
        upstream_current_bps=42_460_000,
        downstream_max_bps=231_000_000,
        upstream_max_bps=51_000_000,
        downstream_noise_margin_db=13.0,
        upstream_noise_margin_db=9.0,
        downstream_attenuation_db=4.0,
        upstream_attenuation_db=2.0,
        sampled_at=datetime.now(UTC),
    )
    now[0] = 106.0

    await hub.async_update_group(PollGroup.NORMAL)

    assert hub.has_capability("dsl_metrics")
    assert hub.get("dsl.snr_downstream_db") == 13.0
    assert "dsl_metrics" not in hub.diagnostics()["endpoint_errors"]


async def test_invalid_credentials_clear_other_poll_groups_before_reauth(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Reauthentication cannot leave another coordinator's protected cache stale."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    normal_coordinator = MagicMock()
    slow_coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.NORMAL, normal_coordinator)
    hub.attach_coordinator(PollGroup.SLOW, slow_coordinator)
    mock_speedport_client.get_json.side_effect = SpeedportInvalidCredentialsError(
        "invalid"
    )

    with pytest.raises(SpeedportInvalidCredentialsError):
        await hub.async_update_group(PollGroup.NORMAL)

    assert hub.get("management.access.state") == "unavailable"
    assert hub.get("wifi.enabled") is None
    assert hub.get("nat.port_forwarding_enabled") is None
    normal_coordinator.async_set_updated_data.assert_not_called()
    slow_coordinator.async_set_updated_data.assert_called_once()


async def test_retry_invalid_credentials_starts_reauth_once(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An explicit protected-data retry starts reauth on definitive rejection."""
    entry = MagicMock()
    mock_speedport_client.probe_capabilities.side_effect = (
        SpeedportInvalidCredentialsError("invalid")
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
    )
    await hub.async_setup()

    with (
        patch.object(
            hass.config_entries,
            "async_get_entry",
            return_value=entry,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hub.async_retry_protected_data()

    entry.async_start_reauth.assert_called_once_with(hass)
    mock_speedport_client.probe_capabilities.assert_awaited_once_with()


async def test_candidate_inventory_records_complete_counts_without_reload(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Explicit inventory publishes safe counts and preserves runtime capabilities."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
    )
    await hub.async_setup()
    report = hub.capability_report
    mock_speedport_client.capture_candidate_inventory = AsyncMock(
        return_value=CandidateInventoryResult(
            attempted=53,
            succeeded=41,
            unsupported=12,
            failed=0,
            observed=76,
        )
    )

    with patch.object(hass.config_entries, "async_schedule_reload") as reload_entry:
        await hub.async_capture_candidate_inventory()

    diagnostics = hub.diagnostics()["candidate_inventory"]
    assert diagnostics["status"] == "complete"
    assert diagnostics["attempted"] == 53
    assert diagnostics["succeeded"] == 41
    assert diagnostics["unsupported"] == 12
    assert diagnostics["failed"] == 0
    assert diagnostics["observed"] == 76
    assert diagnostics["last_attempted_at"] is not None
    assert diagnostics["last_completed_at"] is not None
    assert diagnostics["last_error"] is None
    assert hub.capability_report is report
    assert hub.get("management.access.state") == "available"
    reload_entry.assert_not_called()


async def test_candidate_inventory_marks_partial_and_retains_counts_on_abort(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Isolated failures are partial; a later critical abort keeps prior counts."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
    )
    await hub.async_setup()
    partial = CandidateInventoryResult(
        attempted=53,
        succeeded=40,
        unsupported=12,
        failed=1,
        observed=74,
    )
    mock_speedport_client.capture_candidate_inventory = AsyncMock(
        side_effect=[
            partial,
            SpeedportDecodeError("encrypted response authentication failed"),
        ]
    )

    await hub.async_capture_candidate_inventory()
    first = hub.diagnostics()["candidate_inventory"]
    assert first["status"] == "partial"
    assert first["failed"] == 1
    assert first["observed"] == 74

    with pytest.raises(HomeAssistantError):
        await hub.async_capture_candidate_inventory()

    second = hub.diagnostics()["candidate_inventory"]
    assert second["status"] == "failed"
    assert second["attempted"] == 53
    assert second["observed"] == 74
    assert second["last_completed_at"] == first["last_completed_at"]
    assert second["last_error"] == "SpeedportDecodeError"
    assert "encrypted response authentication failed" not in repr(second)
    assert hub.get("management.access.state") == "unavailable"


async def test_candidate_inventory_serializes_against_polling(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The explicit scan owns the hub operation lock until it has logged out."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    started = asyncio.Event()
    release = asyncio.Event()

    async def capture() -> CandidateInventoryResult:
        started.set()
        await release.wait()
        return CandidateInventoryResult(1, 1, 0, 0, 1)

    mock_speedport_client.capture_candidate_inventory = AsyncMock(side_effect=capture)
    mock_speedport_client.get_status.reset_mock()
    capture_task = asyncio.create_task(hub.async_capture_candidate_inventory())
    await started.wait()
    poll_task = asyncio.create_task(hub.async_update_group(PollGroup.FAST))
    await asyncio.sleep(0)

    mock_speedport_client.get_status.assert_not_awaited()
    assert not poll_task.done()

    release.set()
    await capture_task
    await poll_task
    mock_speedport_client.get_status.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("error", "expected_state", "starts_reauth"),
    [
        (SpeedportSessionBusyError("busy"), "blocked", False),
        (SpeedportInvalidCredentialsError("invalid"), "unavailable", True),
    ],
    ids=["busy", "invalid-credentials"],
)
async def test_retry_failure_invalidates_cached_protected_groups(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    error: SpeedportError,
    expected_state: str,
    starts_reauth: bool,  # noqa: FBT001
) -> None:
    """A failed explicit retry cannot leave prior protected values current."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
    )
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    coordinators = {
        PollGroup.NORMAL: MagicMock(),
        PollGroup.SLOW: MagicMock(),
    }
    for group, coordinator in coordinators.items():
        hub.attach_coordinator(group, coordinator)
    mock_speedport_client.probe_capabilities.side_effect = error
    entry = MagicMock()

    with (
        patch.object(
            hass.config_entries,
            "async_get_entry",
            return_value=entry,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await hub.async_retry_protected_data()

    assert hub.get("management.access.state") == expected_state
    assert hub.get("wifi.enabled") is None
    assert hub.get("nat.port_forwarding_enabled") is None
    for coordinator in coordinators.values():
        coordinator.async_set_updated_data.assert_called_once()
    if starts_reauth:
        entry.async_start_reauth.assert_called_once_with(hass)
    else:
        entry.async_start_reauth.assert_not_called()


async def test_setup_keeps_public_data_when_protected_session_is_unavailable(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A protected decode failure degrades management without failing setup."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=False,
        feature_endpoints=MappingProxyType(
            {"status": EndpointCapability("status", "data/Status.json")}
        ),
    )
    mock_speedport_client.last_management_error = SpeedportAuthenticationError(
        "protected decode failed"
    )
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    await hub.async_setup()

    assert hub.get("management.access.state") == "unavailable"
    assert hub.has_capability("status")


async def test_unsupported_counter_removed_and_close_idempotent(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A transient counter failure preserves the confirmed capability for retry."""
    mock_speedport_client.get_wan_counters.side_effect = SpeedportUnsupportedError
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    await hub.async_update_group(PollGroup.FAST)
    assert hub.has_capability("wan_counters")
    assert hub.get("wan.bytes_received") is None
    assert hub.diagnostics()["endpoint_errors"] == {
        "wan_counters": "SpeedportUnsupportedError"
    }
    await hub.async_close()
    await hub.async_close()
    mock_speedport_client.close.assert_awaited_once()
    with pytest.raises(SpeedportConnectionError):
        await hub.async_update_group(PollGroup.FAST)


async def test_command_gate_and_verification(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Commands require opt-in, allowlist, implementation, and verification poll."""
    disabled = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
    )
    assert not disabled.supports_command("wifi_set_enabled")
    with pytest.raises(HomeAssistantError, match="disabled") as disabled_error:
        await disabled.async_execute("wifi_set_enabled", enabled=True)
    assert disabled_error.value.translation_domain == DOMAIN
    assert disabled_error.value.translation_key == "controls_disabled"

    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    with pytest.raises(HomeAssistantError) as unsupported_error:
        await hub.async_execute("factory_reset")
    assert unsupported_error.value.translation_domain == DOMAIN
    assert unsupported_error.value.translation_key == "command_unsupported"
    with pytest.raises(HomeAssistantError) as unimplemented_error:
        await hub.async_execute("set_wifi_2_4", enabled=True)
    assert unimplemented_error.value.translation_key == "command_unsupported"

    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(return_value="ok")
    hub._async_update_group_locked = AsyncMock()  # noqa: SLF001
    normal_coordinator = MagicMock()
    hub.attach_coordinator(PollGroup.NORMAL, normal_coordinator)
    assert hub.supports_command("wifi_set_enabled")
    assert (
        await hub.async_execute(
            "wifi_set_enabled", verify_group=PollGroup.NORMAL, enabled=True
        )
        == "ok"
    )
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=True
    )
    hub._async_update_group_locked.assert_awaited_once_with(  # noqa: SLF001
        PollGroup.NORMAL
    )
    normal_coordinator.async_set_updated_data.assert_called_once()


async def test_descriptor_scaffolding_never_enables_unproven_commands(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Read capability data cannot expose a command without an exact handler gate."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    hub._capabilities = frozenset(  # noqa: SLF001 - explicit safety contract
        {
            "ddns",
            "dsl",
            "firmware",
            "mesh",
            "nat",
            "parental",
            "usb",
            "vpn",
        }
    )

    for command in (
        "ddns_update",
        "dsl_restart",
        "firmware_update",
        "mesh_optimize",
        "set_client_internet_paused",
        "set_ddns",
        "set_media_server",
        "set_parental_controls",
        "set_upnp",
        "set_vpn",
        "wireguard_restart",
    ):
        assert not hub.supports_command(command), command


async def test_write_controls_require_exact_reviewed_model_and_firmware(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A read-compatible router cannot inherit another firmware's write contract."""
    mock_speedport_client.router_info = RouterInfo(
        model="Speedport Smart 4R Typ A",
        firmware="unreviewed",
        serial_number="SP4R-TEST-001",
    )
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )

    await hub.async_setup()

    assert hub.has_capability("wifi")
    assert hub.has_capability("authenticated_json")
    assert not hub.supports_command("wifi_set_enabled")
    assert not hub.supports_command("reboot")


async def test_disruptive_command_defers_verification(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """An accepted disruptive command relies on natural coordinator recovery."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    mock_speedport_client.reboot = AsyncMock(return_value="accepted")
    hub._async_update_group_locked = AsyncMock(  # noqa: SLF001
        side_effect=SpeedportConnectionError("router restarting")
    )

    assert await hub.async_execute("reboot", verify_group=None) == "accepted"

    mock_speedport_client.reboot.assert_awaited_once_with()
    hub._async_update_group_locked.assert_not_awaited()  # noqa: SLF001
    mock_speedport_client.logout.assert_awaited_once()


async def test_command_failures_are_translated_without_retry(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Indeterminate command timeouts back off and cannot repeat immediately."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    hub._async_update_group_locked = AsyncMock()  # noqa: SLF001
    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(
        side_effect=SpeedportConnectionError("response timed out")
    )

    with pytest.raises(HomeAssistantError) as command_error:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert command_error.value.translation_domain == DOMAIN
    assert command_error.value.translation_key == "command_failed"
    assert isinstance(command_error.value.__cause__, SpeedportConnectionError)
    assert hub.get("management.access.state") == "unavailable"
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=False
    )
    with pytest.raises(HomeAssistantError):
        await hub.async_execute("wifi_set_enabled", enabled=False)
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=False
    )
    hub._async_update_group_locked.assert_not_awaited()  # noqa: SLF001
    mock_speedport_client.logout.assert_awaited_once()

    mock_speedport_client.logout.reset_mock()
    hub._set_management_access("available")  # noqa: SLF001
    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(return_value="accepted")
    hub._async_update_group_locked = AsyncMock(  # noqa: SLF001
        side_effect=SpeedportConnectionError("readback unavailable")
    )

    with pytest.raises(HomeAssistantError) as verification_error:
        await hub.async_execute("wifi_set_enabled", enabled=True)

    assert verification_error.value.translation_domain == DOMAIN
    assert verification_error.value.translation_key == "command_verification_failed"
    assert isinstance(verification_error.value.__cause__, SpeedportConnectionError)
    assert hub.get("management.access.state") == "unavailable"
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=True
    )
    with pytest.raises(HomeAssistantError):
        await hub.async_execute("wifi_set_enabled", enabled=True)
    mock_speedport_client.execute_wifi_set_enabled.assert_awaited_once_with(
        enabled=True
    )
    hub._async_update_group_locked.assert_awaited_once_with(  # noqa: SLF001
        PollGroup.NORMAL
    )
    mock_speedport_client.logout.assert_awaited_once()


async def test_command_rejection_keeps_management_available(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A negative acknowledgement does not defer the next protected poll."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()
    rejection = SpeedportCommandRejectedError("router rejected request")
    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(side_effect=rejection)

    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert failure.value.translation_key == "command_failed"
    assert failure.value.__cause__ is rejection
    assert hub.get("management.access.state") == "available"
    assert hub._protected_retry_at == 0.0  # noqa: SLF001

    mock_speedport_client.get_json.reset_mock()
    await hub.async_update_group(PollGroup.NORMAL)

    mock_speedport_client.get_json.assert_awaited_once_with(
        "data/WLANBasic.json",
        authenticated=True,
        referer=None,
    )


@pytest.mark.parametrize("failure_stage", ["command", "verification"])
@pytest.mark.parametrize(
    "case",
    [
        (SpeedportSessionBusyError("busy"), "blocked", None),
        (SpeedportLoginLockedError(retry_after=90), "locked", 90),
        (SpeedportAuthenticationError("session failed"), "unavailable", None),
        (SpeedportProtocolError("decode failed"), "unavailable", None),
    ],
    ids=["busy", "locked", "authentication", "protocol"],
)
async def test_command_failures_update_management_backoff(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
    failure_stage: str,
    case: tuple[SpeedportError, str, int | None],
) -> None:
    """Authenticated command failures update access state before translation."""
    error, expected_state, expected_retry_after = case
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()
    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(return_value="accepted")
    hub._async_update_group_locked = AsyncMock()  # noqa: SLF001
    if failure_stage == "command":
        mock_speedport_client.execute_wifi_set_enabled.side_effect = error
        expected_translation_key = "command_failed"
    else:
        hub._async_update_group_locked.side_effect = error  # noqa: SLF001
        expected_translation_key = "command_verification_failed"

    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert failure.value.translation_key == expected_translation_key
    assert failure.value.__cause__ is error
    assert hub.get("management.access.state") == expected_state
    assert hub.get("management.access.retry_after_seconds") == expected_retry_after
    assert hub._protected_retry_at > 100.0  # noqa: SLF001


async def test_command_session_failure_invalidates_every_protected_cache(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A handler-side session failure immediately clears all protected state."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        status_json=True,
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "wifi": EndpointCapability(
                    "wifi", "data/WLANBasic.json", authenticated=True
                ),
                "port_forwarding": EndpointCapability(
                    "port_forwarding",
                    "data/PortForwarding.json",
                    authenticated=True,
                ),
            }
        ),
    )

    async def get_feature(endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint == "data/WLANBasic.json":
            return {"use_wlan": True}
        return {"internet_ports_active": True}

    mock_speedport_client.get_json.side_effect = get_feature
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)
    coordinators = {group: MagicMock() for group in PollGroup}
    for group, coordinator in coordinators.items():
        hub.attach_coordinator(group, coordinator)
    handler = AsyncMock(side_effect=SpeedportSessionBusyError("busy"))
    mock_speedport_client.execute_wifi_set_enabled = handler

    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert failure.value.translation_key == "command_failed"
    assert hub.get("management.access.state") == "blocked"
    assert hub.get("wifi.enabled") is None
    assert hub.get("nat.port_forwarding_enabled") is None
    handler.assert_awaited_once_with(enabled=False)
    for coordinator in coordinators.values():
        coordinator.async_set_updated_data.assert_called_once()


async def test_command_invalid_credentials_starts_reauth_without_second_write(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """A rejected command starts reauth and subsequent presses fail before I/O."""
    entry = MagicMock()
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        entry_id="entry-id",
        controls_enabled=True,
    )
    await hub.async_setup()
    handler = AsyncMock(side_effect=SpeedportInvalidCredentialsError("invalid"))
    mock_speedport_client.execute_wifi_set_enabled = handler

    with patch.object(
        hass.config_entries,
        "async_get_entry",
        return_value=entry,
    ):
        with pytest.raises(HomeAssistantError):
            await hub.async_execute("wifi_set_enabled", enabled=False)
        with pytest.raises(HomeAssistantError):
            await hub.async_execute("wifi_set_enabled", enabled=False)

    entry.async_start_reauth.assert_called_once_with(hass)
    handler.assert_awaited_once_with(enabled=False)


async def test_command_backoff_rejects_before_handler_io(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Repeated control presses cannot bypass a protected-session backoff."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
        monotonic_time=lambda: 100.0,
    )
    await hub.async_setup()
    handler = AsyncMock(return_value="accepted")
    mock_speedport_client.execute_wifi_set_enabled = handler
    hub._mark_management_busy(SpeedportSessionBusyError("busy"))  # noqa: SLF001

    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert failure.value.translation_key == "command_failed"
    handler.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()

    hub._set_management_access("available")  # noqa: SLF001
    hub._protected_retry_at = 101.0  # noqa: SLF001

    with pytest.raises(HomeAssistantError):
        await hub.async_execute("wifi_set_enabled", enabled=False)

    handler.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()


async def test_firmware_write_block_rejects_before_handler_io(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """The firmware's global save-failure gate disables every mutation."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    handler = AsyncMock(return_value="accepted")
    mock_speedport_client.execute_wifi_set_enabled = handler
    hub._merge_data(  # noqa: SLF001 - firmware-state safety fixture
        {"system": {"settings_write_blocked": True}}
    )

    assert not hub.management_controls_available
    with pytest.raises(HomeAssistantError) as failure:
        await hub.async_execute("wifi_set_enabled", enabled=False)

    assert failure.value.translation_key == "command_failed"
    handler.assert_not_awaited()
    mock_speedport_client.logout.assert_not_awaited()

    hub._merge_data(  # noqa: SLF001 - transient Status.json failure fixture
        {"system": {"settings_write_blocked": None}}
    )
    assert not hub.management_controls_available
    with pytest.raises(HomeAssistantError):
        await hub.async_execute("wifi_set_enabled", enabled=False)
    handler.assert_not_awaited()

    hub._merge_data(  # noqa: SLF001 - explicit router readback clears latch
        {"system": {"settings_write_blocked": False}}
    )
    assert hub.management_controls_available
    assert (
        await hub.async_execute(
            "wifi_set_enabled",
            enabled=False,
            verify_group=None,
        )
        == "accepted"
    )
    handler.assert_awaited_once_with(enabled=False)


async def test_commands_remain_serialized(
    hass: HomeAssistant,
    mock_speedport_client: MagicMock,
) -> None:
    """Concurrent callers cannot overlap mutation or verification work."""
    hub = SpeedportHub(
        hass,
        mock_speedport_client,
        fallback_identifier="entry",
        controls_enabled=True,
    )
    await hub.async_setup()
    active = 0
    max_active = 0

    async def execute_wifi(*, enabled: bool) -> bool:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return enabled

    mock_speedport_client.execute_wifi_set_enabled = AsyncMock(side_effect=execute_wifi)
    hub._async_update_group_locked = AsyncMock()  # noqa: SLF001

    assert await asyncio.gather(
        hub.async_execute("wifi_set_enabled", enabled=True),
        hub.async_execute("wifi_set_enabled", enabled=False),
    ) == [True, False]

    assert max_active == 1
    assert mock_speedport_client.execute_wifi_set_enabled.await_count == 2
    assert hub._async_update_group_locked.await_count == 2  # noqa: SLF001
    assert mock_speedport_client.logout.await_count == 2


async def test_closed_hub_cannot_be_reopened(
    hass: HomeAssistant, mock_speedport_client: MagicMock
) -> None:
    """Closed session owner cannot silently reopen."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_close()
    with pytest.raises(SpeedportError, match="closed"):
        await hub.async_setup()
