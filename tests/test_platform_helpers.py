"""Tests for platform data normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.speedport_smart.const import DOMAIN
from custom_components.speedport_smart.platform_helpers import (
    as_bool,
    as_datetime,
    as_float,
    as_int,
    as_mbit_per_second,
    as_percent,
    child_device_info,
    collection,
    count_items,
    speedport_child_device,
    stable_id,
    supported,
    value,
)


class FakeHub:
    """Small nested-data hub double."""

    router_identifier = "router-1"

    def __init__(self) -> None:
        """Initialize representative nested data."""
        self.capabilities = {"wifi", "clients"}
        self.data: dict[str, Any] = {
            "wifi": {"channel": 11},
            "clients": {
                "items": [
                    {"id": "one", "name": "Phone"},
                    {"name": "No stable ID"},
                ]
            },
        }

    def has_capability(self, capability: str) -> bool:
        """Return declared capability."""
        return capability in self.capabilities

    def get(self, path: str, default: Any = None) -> Any:
        """Read dotted path."""
        current: Any = self.data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current


def test_supported_and_value_transform() -> None:
    """Capability and path both gate entity creation."""
    hub = FakeHub()
    assert supported(hub, "wifi", "wifi.channel")
    assert supported(hub, ("dsl", "wifi"), "wifi.channel")
    assert supported(hub, "wifi", None)
    assert not supported(hub, "dsl", "wifi.channel")
    assert not supported(hub, ("dsl", "mesh"), "wifi.channel")
    assert not supported(hub, "wifi", "wifi.missing")
    assert value(hub, "wifi.channel", as_int) == 11
    assert value(hub, "wifi.channel") == 11
    assert value(hub, "wifi.missing", as_int) is None
    assert value(hub, "wifi.channel", lambda _: 1 / 0) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (1, True),
        (0.0, False),
        ("connected", True),
        ("UP", True),
        ("disabled", False),
        ("off", False),
    ],
)
def test_boolean_normalization(raw: Any, expected: object) -> None:
    """Router boolean spellings normalize consistently."""
    assert as_bool(raw) is expected


def test_invalid_boolean_is_rejected() -> None:
    """Ambiguous state cannot silently become true."""
    with pytest.raises(ValueError, match="Unsupported boolean"):
        as_bool("maybe")


def test_numeric_and_time_transforms() -> None:
    """Platform units remain native Home Assistant values."""
    assert as_mbit_per_second(123_456_789) == 123.457
    assert as_percent(-1) == 0
    assert as_percent(150) == 100
    assert as_percent(12.34) == 12.3
    assert as_int("4") == 4
    assert as_float("4.5") == 4.5
    now = datetime.now(UTC)
    assert as_datetime(now) is now
    naive = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
    assert as_datetime(naive).tzinfo is UTC
    assert as_datetime(0) == datetime(1970, 1, 1, tzinfo=UTC)
    assert as_datetime("2026-01-01T00:00:00Z").tzinfo is not None


def test_collection_counts_and_stable_identity() -> None:
    """Collections accept maps/lists but identities reject IP-only objects."""
    hub = FakeHub()
    assert len(collection(hub, "clients.items")) == 2
    hub.data["clients"]["items"] = {"one": {"uuid": "ABC"}}
    assert stable_id(collection(hub, "clients.items")[0]) == "abc"
    hub.data["clients"]["items"] = "invalid"
    assert collection(hub, "clients.items") == ()
    assert stable_id({"ip": "192.0.2.10"}) is None
    assert stable_id({"serial": " SER-1 "}) == "ser-1"
    assert count_items([1, 2]) == 2
    assert count_items({"one": 1}) == 1
    assert count_items("3") == 3


def test_child_device_requires_stable_identity() -> None:
    """Child devices link to router only with a stable router-provided ID."""
    hub = FakeHub()
    assert child_device_info(hub, "client", {"ip": "192.0.2.3"}) is None
    info = child_device_info(
        hub,
        "mesh",
        {
            "serial": "node-1",
            "name": "Living room",
            "model": "Speed Home WLAN",
            "firmware": "1.2.3",
        },
    )
    assert info is not None
    assert info["identifiers"] == {(DOMAIN, "mesh:node-1")}
    assert info["via_device"] == (DOMAIN, "router-1")
    assert info["name"] == "Living room"


def test_telephone_line_child_rejects_phone_number_identity() -> None:
    """Defense in depth keeps subscriber numbers out of device identifiers."""
    assert (
        speedport_child_device(
            "telephone_line",
            {"id": "+49 30 123456", "registered": True},
        )
        is None
    )


def test_dect_repeater_child_uses_safe_default_name() -> None:
    """An exact repeater row creates a stable child without a private label."""
    device = speedport_child_device(
        "dect_repeater",
        {"id": "repeater-1", "registered": True},
    )

    assert device is not None
    assert device.identifier == "repeater-1"
    assert device.name == "DECT repeater"


def test_collection_rejects_scalar_root() -> None:
    """Non-collection payload yields no child entities."""
    hub = SimpleNamespace(get=lambda *_: 5)
    assert collection(hub, "clients.items") == ()
