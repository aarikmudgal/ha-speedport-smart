"""Shared helpers for capability-driven Speedport platforms."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from .coordinator import PollGroup, SpeedportDataUpdateCoordinator
    from .entity import SpeedportDevice
    from .hub import SpeedportHub

MISSING = object()
_MIN_PHONE_LABEL_DIGITS = 5


def supported(
    hub: SpeedportHub,
    capability: str,
    data_path: str | tuple[str | int, ...] | None,
) -> bool:
    """Return whether capability and optional value exist."""
    if not hub.has_capability(capability):
        return False
    return data_path is None or hub.get(data_path, MISSING) is not MISSING


def coordinator(hub: SpeedportHub, group: PollGroup) -> SpeedportDataUpdateCoordinator:
    """Return polling coordinator for an entity description."""
    return hub.coordinator(group)


def value[T](
    hub: SpeedportHub,
    data_path: str | tuple[str | int, ...],
    transform: Callable[[Any], T] | None = None,
) -> T | Any | None:
    """Read and optionally transform a normalized value."""
    raw = hub.get(data_path)
    if raw is None or transform is None:
        return raw
    try:
        return transform(raw)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def as_mbit_per_second(raw: Any) -> float:
    """Convert bits per second to megabits per second."""
    return round(float(raw) / 1_000_000, 3)


def as_gigabytes(raw: Any) -> float:
    """Convert byte counters to decimal gigabytes for readable totals."""
    return round(float(raw) / 1_000_000_000, 6)


def as_percent(raw: Any) -> float:
    """Clamp a percentage to valid Home Assistant range."""
    return round(max(0.0, min(100.0, float(raw))), 1)


def as_int(raw: Any) -> int:
    """Convert numeric router value to integer."""
    return int(raw)


def as_float(raw: Any) -> float:
    """Convert numeric router value to float."""
    return float(raw)


def as_bool(raw: Any) -> bool:
    """Normalize common Speedport boolean representations."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {
            "1",
            "active",
            "connected",
            "enabled",
            "on",
            "online",
            "up",
            "yes",
        }:
            return True
        if normalized in {
            "0",
            "disabled",
            "disconnected",
            "down",
            "inactive",
            "no",
            "off",
            "offline",
        }:
            return False
    message = f"Unsupported boolean value: {raw!r}"
    raise ValueError(message)


def as_datetime(raw: Any) -> datetime:
    """Normalize ISO or Unix timestamp to an aware datetime."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    parsed = datetime.fromisoformat(str(raw))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def count_items(raw: Any) -> int:
    """Count a normalized collection or accept an existing numeric count."""
    if isinstance(raw, Mapping):
        return len(raw)
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return len(raw)
    return int(raw)


def collection(
    hub: SpeedportHub, data_path: str | tuple[str | int, ...]
) -> tuple[Mapping[str, Any], ...]:
    """Return mapping items from a normalized collection."""
    raw = hub.get(data_path, ())
    items: Iterable[Any]
    if isinstance(raw, Mapping):
        items = raw.values()
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        items = raw
    else:
        return ()
    return tuple(item for item in items if isinstance(item, Mapping))


def child_collection(
    hub: SpeedportHub,
    data_paths: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    """
    Return child items from the first exposed collection or singleton path.

    A mapping with its own stable identity is a single child (used by the
    external receiver payload). Other mappings are treated as keyed
    collections, but each child still needs an identity in its own payload.
    This deliberately refuses to manufacture identities from list positions,
    IP addresses, or arbitrary mapping keys.
    """
    for data_path in data_paths:
        raw = hub.get(data_path, MISSING)
        if raw is MISSING or raw is None:
            continue
        if isinstance(raw, Mapping):
            if stable_id(raw) is not None:
                return (raw,)
            mapped_items = tuple(
                item for item in raw.values() if isinstance(item, Mapping)
            )
            if mapped_items:
                return mapped_items
            continue
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            sequence_items = tuple(item for item in raw if isinstance(item, Mapping))
            if sequence_items:
                return sequence_items
            continue
        return ()
    return ()


def child_item(
    hub: SpeedportHub,
    data_paths: tuple[str, ...],
    identifier: str,
) -> Mapping[str, Any] | None:
    """Find a child by router-provided stable identity."""
    return next(
        (
            item
            for item in child_collection(hub, data_paths)
            if stable_id(item) == identifier
        ),
        None,
    )


def stable_id(item: Mapping[str, Any]) -> str | None:
    """Return stable router-provided identity, never IP or list index."""
    for key in ("id", "uuid", "uid", "serial", "mac"):
        candidate = item.get(key)
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip().lower()
    return None


def speedport_child_device(
    family: str,
    item: Mapping[str, Any],
) -> SpeedportDevice | None:
    """Build stable, non-sensitive child-device metadata."""
    # Imported lazily so the general platform helpers stay cycle-free.
    from .entity import SpeedportDevice  # noqa: PLC0415

    identifier = stable_id(item)
    if identifier is None:
        return None

    default_names = {
        "client": "Network client",
        "dect_handset": "DECT handset",
        "ip_phone": "IP phone",
        "mesh_node": "Mesh node",
        "receiver": "5G/LTE receiver",
        "telephone_line": "Telephone line",
        "usb_device": "USB device",
    }
    candidate: Any = None
    if family != "telephone_line":
        candidate = item.get("hostname") or item.get("name") or item.get("label")
    else:
        line_label = item.get("label") or item.get("name")
        if line_label is not None and not _looks_like_phone_number(str(line_label)):
            candidate = line_label

    name = str(candidate).strip() if candidate is not None else ""
    if not name:
        name = default_names.get(family, "Speedport device")

    return SpeedportDevice(
        identifier=identifier,
        kind=family,
        name=name,
        manufacturer=(
            str(item["manufacturer"])
            if item.get("manufacturer") is not None
            else MANUFACTURER
        ),
        model=(
            str(item.get("model") or item.get("type"))
            if item.get("model") is not None or item.get("type") is not None
            else None
        ),
        sw_version=(
            str(item["firmware"]) if item.get("firmware") is not None else None
        ),
        hw_version=(
            str(item["hardware_version"])
            if item.get("hardware_version") is not None
            else None
        ),
    )


def _looks_like_phone_number(value: str) -> bool:
    """Return whether a label is predominantly a telephone number."""
    compact = "".join(character for character in value if not character.isspace())
    digits = sum(character.isdigit() for character in compact)
    return digits >= _MIN_PHONE_LABEL_DIGITS and digits * 2 >= len(compact)


def child_device_info(
    hub: SpeedportHub,
    family: str,
    item: Mapping[str, Any],
) -> DeviceInfo | None:
    """Build child device information when stable identity exists."""
    identifier = stable_id(item)
    if identifier is None:
        return None
    router_identifier = getattr(hub, "router_identifier", None)
    via_device = (
        (DOMAIN, str(router_identifier)) if router_identifier is not None else None
    )
    model = item.get("model") or item.get("type")
    manufacturer = item.get("manufacturer") or MANUFACTURER
    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{family}:{identifier}")},
        name=str(item.get("name") or item.get("hostname") or f"{family} {identifier}"),
        manufacturer=str(manufacturer),
        model=str(model) if model else None,
        sw_version=(
            str(item["firmware"]) if item.get("firmware") is not None else None
        ),
        serial_number=(str(item["serial"]) if item.get("serial") is not None else None),
    )
    if via_device is not None:
        device_info["via_device"] = via_device
    return device_info
