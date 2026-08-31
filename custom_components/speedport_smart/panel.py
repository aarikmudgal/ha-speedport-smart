"""Bundled full-page frontend panel for Speedport Smart."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_CONTROL, POLICY_READ
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.update import UpdateEntityFeature
from homeassistant.components.websocket_api.decorators import websocket_command
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.websocket_api.connection import ActiveConnection
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .hub import SpeedportHub

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH: Final = "speedport-smart"
PANEL_COMPONENT_NAME: Final = "speedport-smart-panel"
PANEL_TITLE: Final = "Telekom Speedport Smart"
PANEL_ICON: Final = "mdi:router-network"
PANEL_SCHEMA_VERSION: Final = 2

_STATIC_URL: Final = "/speedport_smart_frontend"
_FRONTEND_DIR: Final = Path(__file__).parent / "frontend"
_FRONTEND_FILE: Final = "speedport-smart-panel.js"
_PANEL_DATA_KEY: Final = f"{DOMAIN}_frontend_panel"
_PANEL_WS_TYPE: Final = f"{DOMAIN}/panel"

_PUBLIC_STATUS_KEYS: Final = frozenset(
    {
        "dsl_connected",
        "dsl_downstream",
        "dsl_upstream",
        "internet_connected",
        "internet_uptime",
        "wan_download_capacity",
        "wan_upload_capacity",
    }
)
_WAN_COUNTER_KEYS: Final = frozenset(
    {
        "wan_bytes_received",
        "wan_bytes_sent",
        "wan_discarded_packets_received",
        "wan_discarded_packets_sent",
        "wan_download_rate",
        "wan_download_utilization",
        "wan_errors_received",
        "wan_errors_sent",
        "wan_interface",
        "wan_packets_received",
        "wan_packets_sent",
        "wan_upload_rate",
        "wan_upload_utilization",
    }
)
_TOTR64_KEYS: Final = frozenset(
    {
        "dsl_attainable_downstream",
        "dsl_attainable_upstream",
        "dsl_attenuation_downstream",
        "dsl_attenuation_upstream",
        "dsl_snr_downstream",
        "dsl_snr_upstream",
    }
)
_INTEGRATION_KEYS: Final = frozenset(
    {
        "last_successful_update",
        "management_access",
        "request_latency",
        "retry_protected_data",
        "router_problem",
        "update_failures",
    }
)
_CHILD_SECTIONS: Final = {
    "client": "clients",
    "dect_handset": "telephony",
    "ip_phone": "telephony",
    "mesh_node": "wireless",
    "receiver": "mobile",
    "telephone_line": "telephony",
    "usb_device": "system",
}
_DISRUPTIVE_CONTROL_KEYS: Final = frozenset(
    {
        "firmware",
        "optimize_mesh",
        "reboot_router",
        "reconnect_internet",
        "restart_dsl",
        "restart_vpn",
        "update_ddns",
        "wps",
    }
)


class _ChildDevicePanelData(TypedDict):
    """Permission-scoped child-device metadata exposed to the panel."""

    device_id: str
    kind: str
    name: str
    model: str | None


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register static assets, metadata API, and one global sidebar panel."""
    panel_state: dict[str, bool] = hass.data.setdefault(_PANEL_DATA_KEY, {})

    if not panel_state.get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    _STATIC_URL,
                    str(_FRONTEND_DIR),
                    cache_headers=False,
                )
            ]
        )
        panel_state["static_registered"] = True

    if not panel_state.get("websocket_registered"):
        websocket_api.async_register_command(hass, websocket_panel_info)
        panel_state["websocket_registered"] = True

    if panel_state.get("panel_owned"):
        return

    if PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        _LOGGER.warning(
            "Cannot register Speedport Smart panel: sidebar path %s is already used",
            PANEL_URL_PATH,
        )
        return

    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT_NAME,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=(f"{_STATIC_URL}/{_FRONTEND_FILE}?schema={PANEL_SCHEMA_VERSION}"),
        embed_iframe=False,
        trust_external=False,
        config={"schema_version": PANEL_SCHEMA_VERSION},
        require_admin=False,
    )
    panel_state["panel_owned"] = True


def async_unregister_panel(hass: HomeAssistant) -> None:
    """
    Remove only the panel owned by this integration.

    Static routes and WebSocket commands intentionally remain process-scoped because
    Home Assistant does not provide supported unregister APIs for them. Config-entry
    reloads should therefore leave the global panel registered.
    """
    panel_state: dict[str, bool] | None = hass.data.get(_PANEL_DATA_KEY)
    if not panel_state or not panel_state.get("panel_owned"):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    panel_state["panel_owned"] = False


@websocket_command({vol.Required("type"): _PANEL_WS_TYPE})
@callback
def websocket_panel_info(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return permission-filtered panel metadata without router I/O."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    routers = []
    for entry in sorted(
        hass.config_entries.async_entries(DOMAIN),
        key=lambda candidate: candidate.title.casefold(),
    ):
        router = _entry_panel_data(
            entry,
            connection,
            entity_registry,
            device_registry,
        )
        if router is not None:
            routers.append(router)

    connection.send_result(
        msg["id"],
        {
            "schema_version": PANEL_SCHEMA_VERSION,
            "routers": routers,
        },
    )


def _entry_panel_data(
    entry: ConfigEntry[Any],
    connection: ActiveConnection,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> dict[str, Any] | None:
    """Build one config entry's local UI model."""
    entities = []
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.disabled_by is not None or not _can_read_entity(
            connection, entity_entry.entity_id
        ):
            continue
        entities.append(
            _entity_panel_data(
                entity_entry,
                _child_device_panel_data(entity_entry, device_registry),
                connection,
            )
        )
    entities.sort(key=_entity_panel_sort_key)

    if not entities and not connection.user.is_admin:
        return None

    hub = _loaded_hub(entry)
    model: str | None = None
    capabilities: list[str] = []
    management: dict[str, Any] = {
        "state": "unavailable",
        "browser_logout_required": False,
        "retry_after_seconds": None,
        "last_successful_update": None,
    }
    access_sources = _empty_access_sources()
    capability_families: list[dict[str, str]] = []
    if hub is not None:
        model = hub.router_identity.model
        capabilities = sorted(hub.capabilities)
        management = _management_panel_data(hub)
        access_sources, capability_families = _capability_panel_data(hub)

    root_device = next(
        (
            device
            for device in dr.async_entries_for_config_entry(
                device_registry, entry.entry_id
            )
            if device.via_device_id is None
        ),
        None,
    )

    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "model": model,
        "entry_state": entry.state.value,
        "root_device_id": root_device.id if root_device is not None else None,
        "management": management,
        "access_sources": access_sources,
        "capabilities": capabilities,
        "capability_families": capability_families,
        "entities": entities,
    }


def _loaded_hub(entry: ConfigEntry[Any]) -> SpeedportHub | None:
    """Return runtime data only for a loaded entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    if runtime_data is None or not hasattr(runtime_data, "capability_report"):
        return None
    return cast("SpeedportHub", runtime_data)


def _entity_panel_data(
    entity_entry: er.RegistryEntry,
    child_device: _ChildDevicePanelData | None,
    connection: ActiveConnection,
) -> dict[str, Any]:
    """Return stable display metadata for one supported entity."""
    entity_id = entity_entry.entity_id
    entity_domain = entity_id.partition(".")[0]
    translation_key = entity_entry.translation_key or entity_id.partition(".")[2]
    child_kind = child_device["kind"] if child_device is not None else None
    supports_control = entity_domain in {"button", "switch"} or (
        entity_domain == "update"
        and bool(entity_entry.supported_features & UpdateEntityFeature.INSTALL)
    )
    is_control = supports_control and _can_control_entity(
        connection,
        entity_id,
    )
    access_source = _access_source_for_entity(
        translation_key,
        entity_domain,
        child_kind,
        is_control=supports_control,
    )
    panel_data: dict[str, Any] = {
        "entity_id": entity_id,
        "domain": entity_domain,
        "translation_key": translation_key,
        "entity_category": (
            str(entity_entry.entity_category)
            if entity_entry.entity_category is not None
            else None
        ),
        "section": (
            "controls"
            if supports_control
            else _section_for_entity(translation_key, entity_domain, child_kind)
        ),
        "access_source": access_source,
        "control": is_control,
        "mutates_router": is_control and translation_key != "retry_protected_data",
        "disruptive": translation_key in _DISRUPTIVE_CONTROL_KEYS,
    }
    if child_device is not None:
        panel_data["child_device"] = child_device
    return panel_data


def _entity_panel_sort_key(entity: dict[str, Any]) -> tuple[str, int, str, str, str]:
    """Keep router summaries first, then child entities grouped by display name."""
    child_device = entity.get("child_device")
    if isinstance(child_device, Mapping):
        child_order = 1
        child_name = str(child_device.get("name", "")).casefold()
    else:
        child_order = 0
        child_name = ""
    return (
        str(entity["section"]),
        child_order,
        child_name,
        str(entity["translation_key"]),
        str(entity["entity_id"]),
    )


def _section_for_entity(
    translation_key: str,
    entity_domain: str,
    child_kind: str | None,
) -> str:
    """Group an entity using stable semantic keys, never display names."""
    if child_kind is not None:
        return _CHILD_SECTIONS.get(child_kind, "system")
    key = translation_key.casefold()
    if entity_domain == "device_tracker" or key.startswith(
        ("client_", "connected_clients", "dhcp_", "lan_")
    ):
        return "clients"
    if key.startswith("lte_tunnel_"):
        return "mobile"
    if key.startswith("wan_"):
        return "bandwidth"
    if key.startswith(("internet_", "public_ipv")) or key == "internet_connected":
        return "connection"
    if key.startswith("dsl_") or key == "dsl_connected":
        return "dsl"
    if key.startswith(("hybrid_", "mobile_", "lte_", "5g_")):
        return "mobile"
    if key.startswith(("wifi_", "guest_wifi", "office_wifi", "mesh_", "wps")):
        return "wireless"
    if key.startswith(("port_forward", "nat_", "upnp_")):
        return "clients"
    if key.startswith(
        (
            "telephone_",
            "telephony_",
            "active_call",
            "missed_call",
            "last_call",
            "ip_phone",
            "dect_",
            "phonebook",
        )
    ):
        return "telephony"
    if key in {
        "last_successful_update",
        "management_access",
        "request_latency",
        "router_problem",
        "update_failures",
    }:
        return "management"
    return "system"


def _access_source_for_entity(
    translation_key: str,
    entity_domain: str,
    child_kind: str | None,
    *,
    is_control: bool,
) -> str:
    """Classify whether an entity survives a competing browser session."""
    key = translation_key.casefold()
    if key in _INTEGRATION_KEYS:
        return "integration"
    if is_control:
        return "router_control"
    if child_kind is not None or entity_domain == "device_tracker":
        return "protected_json"
    if key in _PUBLIC_STATUS_KEYS:
        return "public_status"
    if key in _WAN_COUNTER_KEYS:
        return "wan_counters"
    if key in _TOTR64_KEYS:
        return "totr64"
    return "protected_json"


def _child_device_panel_data(
    entity_entry: er.RegistryEntry,
    device_registry: dr.DeviceRegistry,
) -> _ChildDevicePanelData | None:
    """Return safe registry metadata only for an integration child device."""
    if entity_entry.device_id is None:
        return None
    device = device_registry.async_get(entity_entry.device_id)
    if device is None or device.via_device_id is None:
        return None
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        _router, separator, child = identifier.partition(":")
        if not separator:
            continue
        kind, separator, _identifier = child.partition(":")
        if separator and kind:
            return {
                "device_id": device.id,
                "kind": kind,
                "name": str(device.name_by_user or device.name or kind),
                "model": str(device.model) if device.model is not None else None,
            }
    return None


def _can_read_entity(connection: ActiveConnection, entity_id: str) -> bool:
    """Respect the connected Home Assistant user's entity permissions."""
    user = connection.user
    permissions = user.permissions
    return permissions.access_all_entities(POLICY_READ) or permissions.check_entity(
        entity_id, POLICY_READ
    )


def _can_control_entity(connection: ActiveConnection, entity_id: str) -> bool:
    """Return whether the connected Home Assistant user may control an entity."""
    user = connection.user
    permissions = user.permissions
    return permissions.access_all_entities(POLICY_CONTROL) or permissions.check_entity(
        entity_id, POLICY_CONTROL
    )


def _management_panel_data(hub: SpeedportHub) -> dict[str, Any]:
    """Return actionable management state without owner or credential data."""
    value: object = hub.get("management.access", {})
    if not isinstance(value, Mapping):
        return {
            "state": "unavailable",
            "browser_logout_required": False,
            "retry_after_seconds": None,
            "last_successful_update": None,
        }
    return {
        "state": value.get("state", "unknown"),
        "browser_logout_required": bool(value.get("browser_logout_required", False)),
        "retry_after_seconds": value.get("retry_after_seconds"),
        "last_successful_update": value.get("last_successful_update"),
    }


def _empty_access_sources() -> list[dict[str, Any]]:
    """Return stable unavailable source cards for an unloaded entry."""
    return [
        {
            "id": "public_status",
            "label": "Browser-independent status",
            "supported": False,
            "available": False,
        },
        {
            "id": "protected_json",
            "label": "Protected router data",
            "supported": False,
            "available": False,
        },
        {
            "id": "totr64",
            "label": "TR-064 line data",
            "supported": False,
            "available": False,
        },
        {
            "id": "wan_counters",
            "label": "Live WAN counters",
            "supported": False,
            "available": False,
        },
    ]


def _capability_panel_data(
    hub: SpeedportHub,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Group proven capability families by their non-mutating access source."""
    report = hub.capability_report
    if report is None:
        return _empty_access_sources(), []

    diagnostics = hub.diagnostics()
    endpoint_errors = diagnostics.get("endpoint_errors", {})
    polling = diagnostics.get("polling", {})
    fast_available = _poll_group_available(polling, "fast")
    normal_available = _poll_group_available(polling, "normal")
    management: Any = hub.get("management.access", {})
    management_available = (
        isinstance(management, Mapping) and management.get("state") == "available"
    )
    public_supported = hub.has_capability("status")
    protected_supported = hub.has_capability("authenticated_json")
    totr64_supported = hub.has_capability("dsl_metrics")
    wan_supported = hub.has_capability("wan_counters")
    access_sources = [
        {
            "id": "public_status",
            "label": "Browser-independent status",
            "supported": public_supported,
            "available": public_supported and fast_available,
        },
        {
            "id": "protected_json",
            "label": "Protected router data",
            "supported": protected_supported,
            "available": (
                protected_supported and management_available and normal_available
            ),
        },
        {
            "id": "totr64",
            "label": "TR-064 line data",
            "supported": totr64_supported,
            "available": (
                totr64_supported
                and normal_available
                and "dsl_metrics" not in endpoint_errors
            ),
        },
        {
            "id": "wan_counters",
            "label": "Live WAN counters",
            "supported": wan_supported,
            "available": (
                wan_supported
                and fast_available
                and "wan_counters" not in endpoint_errors
            ),
        },
    ]
    families = []
    for name, capability in sorted(report.feature_endpoints.items()):
        if capability.endpoint == "data/Status.json":
            source = "public_status"
        elif capability.authenticated:
            source = "protected_json"
        else:
            source = "public_json"
        families.append({"name": str(name), "source": source})
    return access_sources, families


def _poll_group_available(polling: object, group: str) -> bool:
    """Return current coordinator health from the UI-safe diagnostic snapshot."""
    if not isinstance(polling, Mapping):
        return False
    group_state = polling.get(group)
    return isinstance(group_state, Mapping) and group_state.get("available") is True
