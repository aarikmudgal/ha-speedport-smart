"""Focused safety tests for newly reviewed native controls."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.speedport_smart.api import DEFAULT_FEATURE_CANDIDATES
from custom_components.speedport_smart.api.client import _has_capability_evidence
from custom_components.speedport_smart.button import (
    BUTTON_DESCRIPTIONS,
    SpeedportCommandButton,
)
from custom_components.speedport_smart.coordinator import (
    PollGroup,
    SpeedportDataUpdateCoordinator,
)
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.models import (
    CapabilityReport,
    EndpointCapability,
)
from custom_components.speedport_smart.normalizers import normalize_feature_payload
from custom_components.speedport_smart.platform_helpers import (
    wps_in_progress,
    wps_started_or_completed,
)
from custom_components.speedport_smart.select import (
    SELECT_DESCRIPTIONS,
    SpeedportCommandSelect,
)


def _description(descriptions: tuple[Any, ...], key: str) -> Any:
    return next(description for description in descriptions if description.key == key)


def _attach_coordinators(hass: Any, hub: SpeedportHub) -> None:
    for group in PollGroup:
        hub.attach_coordinator(
            group,
            SpeedportDataUpdateCoordinator(hass, hub, group, timedelta(seconds=30)),
        )
        hub.coordinator(group).async_request_refresh = AsyncMock()
        hub.coordinator(group).last_update_success = True


def _add_feature_proofs(hub: SpeedportHub, **endpoints: str) -> None:
    """Set only exact, authenticated read proofs for control discovery."""
    report = hub._capability_report  # noqa: SLF001 - focused proof fixture
    assert report is not None
    feature_endpoints = dict(report.feature_endpoints)
    feature_endpoints.update(
        {
            family: EndpointCapability(family, endpoint, authenticated=True)
            for family, endpoint in endpoints.items()
        }
    )
    hub._apply_capability_report(  # noqa: SLF001 - focused proof fixture
        replace(
            report,
            authenticated_json=True,
            feature_endpoints=MappingProxyType(feature_endpoints),
        )
    )


@pytest.mark.parametrize(
    ("family", "endpoint", "field", "valid", "invalid"),
    [
        ("connection_privacy", "data/IPPrivacy.json", "lan_privacy_policy", "2", "3"),
        ("receiver_led", "data/LTE.json", "ex5g_led_mode", "1", "3"),
        ("wps", "data/WLANAccess.json", "use_wps", "1", "2"),
    ],
)
def test_control_discovery_requires_exact_scalar_proof(
    family: str,
    endpoint: str,
    field: str,
    valid: str,
    invalid: str,
) -> None:
    """Each control capability needs its exact endpoint and allowed scalar."""
    candidate = next(
        candidate
        for candidate in DEFAULT_FEATURE_CANDIDATES[family]
        if candidate.endpoint == endpoint
    )

    assert _has_capability_evidence({field: valid}, candidate)
    assert not _has_capability_evidence({field: invalid}, candidate)
    assert not _has_capability_evidence({f"not_{field}": valid}, candidate)


async def test_controls_require_exact_read_proofs_before_availability(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """Generic receiver or wifi data cannot replace reviewed endpoint proofs."""
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=True
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    hub._merge_data(  # noqa: SLF001 - focused control readback fixture
        {
            "internet": {"privacy_level": 1},
            "receiver": {"led_mode": 1},
            "wifi": {"wps_start_available": True},
        }
    )
    for command in ("wps", "set_internet_privacy_level", "set_receiver_led_mode"):
        assert not hub.command_decision(command).capability_supported

    _add_feature_proofs(
        hub,
        connection_privacy="data/IPPrivacy.json",
        receiver_led="data/LTE.json",
        wps="data/WLANAccess.json",
    )
    for command in ("wps", "set_internet_privacy_level", "set_receiver_led_mode"):
        assert hub.command_decision(command).capability_supported


async def test_control_polling_uses_only_gets_and_never_posts(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """Capability polling and availability state never invoke write transport."""
    mock_speedport_client.setup.return_value = CapabilityReport(
        authenticated_json=True,
        feature_endpoints=MappingProxyType(
            {
                "connection_privacy": EndpointCapability(
                    "connection_privacy",
                    "data/IPPrivacy.json",
                    authenticated=True,
                    referer="html/content/internet/con_privacy.html",
                ),
                "receiver_led": EndpointCapability(
                    "receiver_led",
                    "data/LTE.json",
                    authenticated=True,
                    referer="html/content/internet/lte_mode.html",
                ),
                "wps": EndpointCapability(
                    "wps",
                    "data/WLANAccess.json",
                    authenticated=True,
                    referer="html/content/network/wlan_wps.html",
                ),
                "wps_status": EndpointCapability(
                    "wps_status",
                    "data/WPSStatus.json",
                    authenticated=True,
                    referer="html/content/network/wlan_wps.html",
                ),
            }
        ),
    )
    mock_speedport_client.get_json.side_effect = lambda endpoint, **_kwargs: {
        "data/IPPrivacy.json": {"lan_privacy_policy": "1"},
        "data/LTE.json": {"ex5g_led_mode": "1"},
        "data/WLANAccess.json": {
            "use_wlan": "1",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_band": "1",
            "wlan_enc": "1",
            "wlan_visible": "1",
        },
        "data/WPSStatus.json": {},
    }[endpoint]
    mock_speedport_client._post_json_unlocked = AsyncMock()  # noqa: SLF001
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")

    await hub.async_setup()
    await hub.async_update_group(PollGroup.NORMAL)
    await hub.async_update_group(PollGroup.SLOW)

    mock_speedport_client._post_json_unlocked.assert_not_awaited()  # noqa: SLF001
    assert hub.get("internet.privacy_level") == 1
    assert hub.get("receiver.led_mode") == 1
    assert hub.get("wifi.wps_start_available") is True
    assert hub.get("wifi.wps_status") == "idle"


@pytest.mark.parametrize(
    "case",
    [
        (
            {
                "use_wlan": "1",
                "use_wps": "1",
                "disabled_wps": "0",
                "wlan_band": "0",
                "wlan_enc": "1",
                "wlan_visible": "1",
                "wlan_5ghz_visible": "1",
            },
            True,
            None,
        ),
        (
            {
                "use_wlan": "1",
                "use_wps": "0",
                "disabled_wps": "0",
                "wlan_band": "0",
            },
            False,
            "disabled_by_setting",
        ),
        (
            {"use_wlan": "1", "use_wps": "1", "disabled_wps": "1", "wlan_band": "0"},
            False,
            "disabled_by_firmware",
        ),
    ],
)
async def test_wps_uses_stable_access_prerequisite_and_reason(
    hass: Any,
    mock_speedport_client: MagicMock,
    case: tuple[dict[str, str], bool, str | None],
) -> None:
    """WPS availability comes from WLANAccess, not an idle transaction response."""
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=True
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_feature_proofs(
        hub,
        wps="data/WLANAccess.json",
        wps_status="data/WPSStatus.json",
    )
    payload, available, reason = case
    hub._merge_data(normalize_feature_payload("wps", payload))  # noqa: SLF001
    hub._merge_data({"wifi": {"wps_status": "idle"}})  # noqa: SLF001
    button = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    hub.async_execute = AsyncMock()

    assert button.available is available
    assert button.extra_state_attributes == (
        {} if reason is None else {"control_unavailable_reason": reason}
    )
    hub.async_execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {
                "use_wlan": "1",
                "use_wps": "1",
                "disabled_wps": "0",
                "wlan_band": "1",
                "wlan_enc": "2",
                "wlan_visible": "1",
            },
            "incompatible_encryption",
        ),
        (
            {
                "use_wlan": "1",
                "use_wps": "1",
                "disabled_wps": "0",
                "wlan_band": "1",
                "wlan_enc": "6",
                "wlan_visible": "1",
            },
            "wps_prerequisite_unavailable",
        ),
        (
            {
                "use_wlan": "1",
                "use_wps": "1",
                "disabled_wps": "0",
                "wlan_band": "1",
                "wlan_enc": "1",
                "wlan_visible": "0",
                "wlan_guest_active": "0",
                "wlan_guest_wps": "0",
                "wlan_guest_enc": "1",
            },
            "ssid_hidden",
        ),
    ],
)
def test_wps_stable_prerequisites_fail_closed(
    payload: dict[str, str], reason: str
) -> None:
    """Unsafe encryption or hidden active bands prevents WPS before commands."""
    wifi = normalize_feature_payload("wps", payload)["wifi"]

    assert wifi["wps_start_available"] is False
    assert wifi["wps_unavailable_reason"] == reason


def test_wps_guest_encryption_exception_requires_exact_guest_proof() -> None:
    """Guest override only enables WPS with all reviewed guest prerequisite values."""
    wifi = normalize_feature_payload(
        "wps",
        {
            "use_wlan": "1",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_band": "1",
            "wlan_enc": "6",
            "wlan_visible": "1",
            "wlan_guest_active": "1",
            "wlan_guest_wps": "1",
            "wlan_guest_enc": "1",
        },
    )["wifi"]

    assert wifi["wps_start_available"] is True
    assert "wps_unavailable_reason" not in wifi


def test_wps_one_visible_active_band_is_enough() -> None:
    """One visible selected main band keeps WPS available."""
    wifi = normalize_feature_payload(
        "wps",
        {
            "use_wlan": "1",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_band": "0",
            "wlan_enc": "1",
            "wlan_visible": "0",
            "wlan_5ghz_visible": "1",
        },
    )["wifi"]

    assert wifi["wps_start_available"] is True


def test_wps_guest_wep_remains_incompatible() -> None:
    """Guest WPS cannot override an effective WEP encryption mode."""
    wifi = normalize_feature_payload(
        "wps",
        {
            "use_wlan": "1",
            "use_wps": "1",
            "disabled_wps": "0",
            "wlan_band": "1",
            "wlan_enc": "6",
            "wlan_visible": "1",
            "wlan_guest_active": "1",
            "wlan_guest_wps": "1",
            "wlan_guest_enc": "2",
        },
    )["wifi"]

    assert wifi["wps_unavailable_reason"] == "incompatible_encryption"


def test_wps_idle_and_failed_statuses_do_not_claim_active_pairing() -> None:
    """Empty idle response and failed terminal state both permit another start."""
    assert normalize_feature_payload("wps_status", {}) == {
        "wifi": {"wps_status": "idle"}
    }
    assert normalize_feature_payload("wps_status", {"unexpected": "1"}) == {}
    assert normalize_feature_payload("wps_status", {"wlan_wps_state": "2"}) == {}
    assert not wps_in_progress("failed")
    assert not wps_started_or_completed("failed")


async def test_wps_requires_current_status_capability_and_readback(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """Stable WLANAccess state cannot replace the current WPSStatus readback."""
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=True
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_feature_proofs(hub, wps="data/WLANAccess.json")
    hub._merge_data(  # noqa: SLF001 - focused WPS fixture
        {"wifi": {"wps_start_available": True, "wps_status": "idle"}}
    )
    button = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    hub.async_execute = AsyncMock()

    assert not button.available
    _add_feature_proofs(hub, wps_status="data/WPSStatus.json")
    hub._endpoint_errors["wps_status"] = "SpeedportDecodeError"  # noqa: SLF001
    assert not button.available
    hub._endpoint_errors.pop("wps_status")  # noqa: SLF001
    assert button.available
    hub.async_execute.assert_not_awaited()


async def test_wps_in_progress_is_unavailable_without_executing_command(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """An active WPS lifecycle is reported clearly instead of accepting a press."""
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=True
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_feature_proofs(
        hub,
        wps="data/WLANAccess.json",
        wps_status="data/WPSStatus.json",
    )
    hub._merge_data(  # noqa: SLF001 - focused WPS fixture
        {"wifi": {"wps_start_available": True, "wps_status": "connecting"}}
    )
    button = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    hub.async_execute = AsyncMock()

    assert not button.available
    assert button.extra_state_attributes == {
        "control_unavailable_reason": "wps_in_progress"
    }
    await button.async_press()
    hub.async_execute.assert_not_awaited()


async def test_wps_requires_stable_prerequisite_readback(
    hass: Any,
    mock_speedport_client: MagicMock,
) -> None:
    """A WPSStatus lifecycle alone cannot prove WPS may be started."""
    hub = SpeedportHub(
        hass, mock_speedport_client, fallback_identifier="entry", controls_enabled=True
    )
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    _add_feature_proofs(
        hub,
        wps="data/WLANAccess.json",
        wps_status="data/WPSStatus.json",
    )
    hub._merge_data({"wifi": {"wps_status": "idle"}})  # noqa: SLF001
    button = SpeedportCommandButton(hub, _description(BUTTON_DESCRIPTIONS, "wps"))
    hub.async_execute = AsyncMock()

    assert not button.available
    assert button.extra_state_attributes == {
        "control_unavailable_reason": "wps_prerequisite_unavailable"
    }
    hub.async_execute.assert_not_awaited()


@pytest.mark.parametrize(
    "case",
    [
        (SpeedportCommandButton, "wps", {"wps_start_available": True}),
        (
            SpeedportCommandSelect,
            "internet_privacy_level_control",
            {"privacy_level": 1},
        ),
        (SpeedportCommandSelect, "receiver_led_mode_control", {"led_mode": 1}),
    ],
)
async def test_availability_reports_reason_without_executing_command(
    hass: Any,
    mock_speedport_client: MagicMock,
    case: tuple[
        type[SpeedportCommandButton | SpeedportCommandSelect], str, dict[str, Any]
    ],
) -> None:
    """Availability is a local gate: it never invokes a router command."""
    hub = SpeedportHub(hass, mock_speedport_client, fallback_identifier="entry")
    await hub.async_setup()
    _attach_coordinators(hass, hub)
    entity_type, description_key, state = case
    root = (
        "wifi"
        if description_key == "wps"
        else ("internet" if description_key.startswith("internet") else "receiver")
    )
    hub._merge_data({root: state})  # noqa: SLF001 - local state fixture
    descriptions = (
        BUTTON_DESCRIPTIONS
        if entity_type is SpeedportCommandButton
        else SELECT_DESCRIPTIONS
    )
    entity = entity_type(hub, _description(descriptions, description_key))
    hub.async_execute = AsyncMock()

    assert not entity.available
    assert entity.extra_state_attributes == {
        "control_unavailable_reason": "controls_disabled"
    }
    hub.async_execute.assert_not_awaited()
