"""Tests for targeted Speedport entity-registry migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.migration import (
    async_remove_retired_global_nas_entities,
    async_remove_retired_router_control_entities,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def test_remove_only_exact_retired_global_nas_entities(hass: HomeAssistant) -> None:
    """Retire exact router-global NAS entities without touching lookalikes."""
    entry = MockConfigEntry(domain=DOMAIN)
    other_entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)
    registry = er.async_get(hass)

    retired = [
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            f"router_{key}",
            config_entry=entry,
            translation_key=key,
        )
        for key in ("nas_enabled", "nas_secure", "nas_read_only")
    ]
    preserved = [
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            "router_other_suffix",
            config_entry=entry,
            translation_key="nas_enabled",
        ),
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            "different_nas_enabled",
            config_entry=entry,
            translation_key="other_key",
        ),
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            "router_nas_secure",
            config_entry=entry,
            translation_key="nas_secure",
        ),
        registry.async_get_or_create(
            "binary_sensor",
            "other_platform",
            "router_nas_read_only",
            config_entry=entry,
            translation_key="nas_read_only",
        ),
        registry.async_get_or_create(
            "binary_sensor",
            DOMAIN,
            "other_router_nas_enabled",
            config_entry=other_entry,
            translation_key="nas_enabled",
        ),
    ]

    assert async_remove_retired_global_nas_entities(hass, entry.entry_id) == 3
    assert all(registry.async_get(item.entity_id) is None for item in retired)
    assert all(registry.async_get(item.entity_id) is not None for item in preserved)
    assert async_remove_retired_global_nas_entities(hass, entry.entry_id) == 0


def test_remove_only_exact_retired_router_controls(hass: HomeAssistant) -> None:
    """Retire exact router controls without touching registry lookalikes."""
    entry = MockConfigEntry(domain=DOMAIN)
    other_entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    retired_keys = {
        "button": ("restart_dsl", "update_ddns", "restart_vpn", "optimize_mesh"),
        "switch": ("upnp", "ddns", "vpn", "parental_controls", "media_server"),
    }

    retired = [
        registry.async_get_or_create(
            domain,
            DOMAIN,
            f"router_{key}",
            config_entry=entry,
            translation_key=key,
        )
        for domain, keys in retired_keys.items()
        for key in keys
    ]
    preserved = [
        registry.async_get_or_create(
            "button",
            DOMAIN,
            "router_restart_dsl_lookalike",
            config_entry=entry,
            translation_key="restart_dsl",
        ),
        registry.async_get_or_create(
            "button",
            DOMAIN,
            "router_other_update_ddns",
            config_entry=entry,
            translation_key="other_key",
        ),
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            "router_restart_vpn",
            config_entry=entry,
            translation_key="restart_vpn",
        ),
        registry.async_get_or_create(
            "switch",
            "other_platform",
            "router_parental_controls",
            config_entry=entry,
            translation_key="parental_controls",
        ),
        registry.async_get_or_create(
            "switch",
            DOMAIN,
            "other_router_media_server",
            config_entry=other_entry,
            translation_key="media_server",
        ),
    ]

    assert async_remove_retired_router_control_entities(hass, entry.entry_id) == 9
    assert all(registry.async_get(item.entity_id) is None for item in retired)
    assert all(registry.async_get(item.entity_id) is not None for item in preserved)
    assert async_remove_retired_router_control_entities(hass, entry.entry_id) == 0
