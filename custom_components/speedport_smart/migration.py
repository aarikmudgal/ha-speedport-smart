"""Targeted entity-registry migrations for Speedport Smart."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from homeassistant.const import CONF_UNIT_OF_MEASUREMENT, UnitOfInformation
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_RETIRED_ROUTER_EVENT_SUFFIX: Final = "_router_event"
_WAN_TOTAL_KEYS: Final = frozenset({"wan_bytes_received", "wan_bytes_sent"})
_SENSOR_OPTIONS_DOMAIN: Final = "sensor"
_SENSOR_PRIVATE_OPTIONS_DOMAIN: Final = "sensor.private"
_SUGGESTED_UNIT_KEY: Final = "suggested_unit_of_measurement"


@callback
def async_remove_retired_router_event_entities(
    hass: HomeAssistant,
    config_entry_id: str,
) -> int:
    """Remove only retired router-event entities for one config entry."""
    registry = er.async_get(hass)
    retired_entries = (
        entry
        for entry in er.async_entries_for_config_entry(registry, config_entry_id)
        if entry.domain == "event"
        and entry.platform == DOMAIN
        and entry.unique_id.endswith(_RETIRED_ROUTER_EVENT_SUFFIX)
    )
    removed = 0
    for entry in retired_entries:
        registry.async_remove(entry.entity_id)
        removed += 1
    return removed


@callback
def async_migrate_wan_totals_to_gigabytes(
    hass: HomeAssistant,
    config_entry_id: str,
) -> int:
    """Move legacy byte counters to GB while respecting explicit user choices."""
    registry = er.async_get(hass)
    migrated = 0
    for entry in er.async_entries_for_config_entry(registry, config_entry_id):
        if (
            entry.domain != _SENSOR_OPTIONS_DOMAIN
            or entry.platform != DOMAIN
            or entry.translation_key not in _WAN_TOTAL_KEYS
        ):
            continue

        user_options = entry.options.get(_SENSOR_OPTIONS_DOMAIN)
        if user_options is not None and CONF_UNIT_OF_MEASUREMENT in user_options:
            continue

        changed = False
        updated_entry = entry
        private_options = entry.options.get(_SENSOR_PRIVATE_OPTIONS_DOMAIN)
        if (
            private_options is not None
            and private_options.get(_SUGGESTED_UNIT_KEY) == UnitOfInformation.BYTES
        ):
            retained_private_options = dict(private_options)
            retained_private_options.pop(_SUGGESTED_UNIT_KEY)
            updated_entry = registry.async_update_entity_options(
                entry.entity_id,
                _SENSOR_PRIVATE_OPTIONS_DOMAIN,
                retained_private_options or None,
            )
            changed = True
        if updated_entry.unit_of_measurement == UnitOfInformation.BYTES:
            registry.async_update_entity(
                updated_entry.entity_id,
                unit_of_measurement=UnitOfInformation.GIGABYTES,
            )
            changed = True
        if changed:
            migrated += 1
    return migrated
