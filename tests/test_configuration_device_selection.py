"""Synthetic compound-aware selection tests; never contact or change a router."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_device_selection import (
    DEVICE_SELECTION_SETTINGS,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

if TYPE_CHECKING:
    from custom_components.speedport_smart.configuration import SettingsContract

_WIFI, _QOS = DEVICE_SELECTION_SETTINGS
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw(family: str = "wlan") -> dict[str, object]:
    """Make hidden inventory and compound flags intentionally differ."""
    container: dict[str, object] = {
        "id": "1",
        "sid": [
            {"sid": "sid-c", "mdevice_name": "0"},
            {"sid": "sid-b", "mdevice_name": "0"},
            {"sid": "sid-a", "mdevice_name": "1"},
        ],
    }
    if family == "wlan":
        container["wlan_allow_all"] = "1"
    return {
        f"{family}_add": container,
        f"{family}_addmdevice": [
            {
                "sid": "sid-a",
                "mdevice_name": "Administrator",
                "mdevice_mac": "02:00:00:00:00:01",
            },
            {
                "sid": "sid-b",
                "mdevice_name": "Device B",
                "mdevice_mac": "02:00:00:00:00:02",
            },
            {
                "sid": "sid-c",
                "mdevice_name": "Device C",
                "mdevice_mac": "02:00:00:00:00:03",
            },
        ],
        "loginedSid": "sid-a",
        "private_unrelated": "NOT-FOR-PAYLOAD",
    }


def _after(
    raw: dict[str, object],
    selected: list[str],
    *,
    mode: str | None = None,
    family: str = "wlan",
) -> dict[str, object]:
    result = deepcopy(raw)
    container = result[f"{family}_add"]
    assert isinstance(container, dict)
    assert isinstance(container["sid"], list)
    for binding in container["sid"]:
        binding["mdevice_name"] = "1" if binding["sid"] in selected else "0"
    if mode is not None:
        container["wlan_allow_all"] = mode
    return result


def test_wifi_reader_uses_compound_flags_not_available_sid_inventory() -> None:
    """Read true checked state and expose only bounded device identity labels."""
    raw = _raw()
    assert _WIFI.read(raw) == {"wlan_allow_all": "1", "allowed_devices": ["sid-a"]}
    assert _WIFI.choices(raw) == {
        "allowed_devices": [
            {"value": "sid-a", "label": "Administrator (sid-a)"},
            {"value": "sid-b", "label": "Device B (sid-b)"},
            {"value": "sid-c", "label": "Device C (sid-c)"},
        ]
    }
    assert "02:00:00" not in str(_WIFI.read(raw))
    assert "02:00:00" not in str(_WIFI.choices(raw))
    assert "Administrator" not in str(_WIFI.metadata())


def test_wifi_restricted_payload_exact_indexed_keys_and_sid_identity() -> None:
    """Match the complete native payload, not labels or list positions as IDs."""
    assert _WIFI.build(_raw(), {"allowed_devices": ["sid-c", "sid-a"]}) == {
        "wlan_allow_all": "1",
        "sid[11]": "sid-a",
        "mdevice_name[11]": "1",
        "sid[21]": "sid-b",
        "mdevice_name[21]": "0",
        "sid[31]": "sid-c",
        "mdevice_name[31]": "1",
    }
    assert _WIFI.endpoint == "data/WLANAccess.json"
    assert _WIFI.referer == "html/content/network/wlan_access.html"
    assert _WIFI.acknowledgement == "status_ok"


def test_wifi_allow_all_keeps_hidden_sids_but_omits_hidden_checkboxes() -> None:
    """Preserve dormant membership without posting invisible checkbox fields."""
    raw = _raw()
    assert _WIFI.build(raw, {"wlan_allow_all": "0"}) == {
        "wlan_allow_all": "0",
        "sid[11]": "sid-a",
        "sid[21]": "sid-b",
        "sid[31]": "sid-c",
    }
    assert _WIFI.verifier is not None
    assert _WIFI.verifier(
        raw, {"wlan_allow_all": "0"}, _after(raw, ["sid-a"], mode="0")
    )
    assert not _WIFI.verifier(raw, {"wlan_allow_all": "0"}, _after(raw, [], mode="0"))


def test_wifi_can_enable_restriction_with_explicit_admin_selection() -> None:
    """Allow the supported transition from unrestricted to selected devices."""
    raw = _after(_raw(), [], mode="0")
    payload = _WIFI.build(raw, {"wlan_allow_all": "1", "allowed_devices": ["sid-a"]})
    assert payload["wlan_allow_all"] == "1"
    assert payload["mdevice_name[11]"] == "1"


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_devices": []},
        {"allowed_devices": ["sid-b"]},
        {"allowed_devices": ["unknown"]},
        {"allowed_devices": ["sid-a", "sid-a"]},
        {"allowed_devices": "sid-a"},
        {"allowed_devices": ("sid-a",)},
        {"allowed_devices": [1]},
        {"allowed_devices": ["sid-a", "bad\nidentifier"]},
        {"allowed_devices": ["sid-a", "id/segment"]},
        {"wlan_allow_all": "0", "allowed_devices": ["sid-a"]},
        {"wlan_allow_all": True},
        {"wlan_allow_all": "2"},
        {"sid[11]": "sid-b"},
        {"id": "2"},
        {"selectall": True},
        {"endpoint": "data/QOS.json"},
        {},
    ],
)
def test_wifi_rejects_lockout_unknown_targets_and_wire_injection(
    changes: dict[str, object],
) -> None:
    """Reject malformed selections, self-lockout and arbitrary wire fields."""
    with pytest.raises(ConfigurationError):
        _WIFI.build(_raw(), changes)


@pytest.mark.parametrize("login", [None, "", "unknown", "sid-b"])
def test_wifi_restrict_requires_known_included_administrator(login: object) -> None:
    """Require a known current administrator SID in the resulting allowlist."""
    with pytest.raises(ConfigurationError, match="administrator_wifi_lockout"):
        _WIFI.build(
            {**_raw(), "loginedSid": login}, {"allowed_devices": ["sid-a", "sid-c"]}
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy_sid_list",
        "missing_binding",
        "duplicate_binding",
        "unknown_binding",
        "missing_flag",
        "boolean_flag",
        "bad_flag",
        "extra_binding_field",
        "duplicate_device",
        "missing_device_sid",
        "bad_device_sid",
        "bad_device_name",
        "missing_inventory",
        "empty_inventory",
        "mixed_inventory",
        "wrong_form_id",
        "missing_form",
        "extra_form",
        "mixed_bindings",
    ],
)
def test_incomplete_or_ambiguous_state_fails_closed(mutation: str) -> None:
    """Reject lost compound flags, duplicate targets and incomplete snapshots."""
    raw = _raw()
    container = raw["wlan_add"]
    inventory = raw["wlan_addmdevice"]
    assert isinstance(container, dict)
    assert isinstance(inventory, list)
    bindings = container["sid"]
    assert isinstance(bindings, list)
    if mutation == "legacy_sid_list":
        container["sid"] = ["sid-a", "sid-b", "sid-c"]
    elif mutation == "missing_binding":
        bindings.pop()
    elif mutation == "duplicate_binding":
        bindings[0] = dict(bindings[1])
    elif mutation == "unknown_binding":
        bindings[0]["sid"] = "unknown"
    elif mutation == "missing_flag":
        bindings[0].pop("mdevice_name")
    elif mutation == "boolean_flag":
        bindings[0]["mdevice_name"] = True
    elif mutation == "bad_flag":
        bindings[0]["mdevice_name"] = "2"
    elif mutation == "extra_binding_field":
        bindings[0]["arbitrary"] = "0"
    elif mutation == "duplicate_device":
        inventory[0] = dict(inventory[1])
    elif mutation == "missing_device_sid":
        inventory[0].pop("sid")
    elif mutation == "bad_device_sid":
        inventory[0]["sid"] = "../invalid"
    elif mutation == "bad_device_name":
        inventory[0]["mdevice_name"] = "bad\nname"
    elif mutation == "missing_inventory":
        raw.pop("wlan_addmdevice")
    elif mutation == "empty_inventory":
        raw["wlan_addmdevice"] = []
    elif mutation == "mixed_inventory":
        inventory[0] = "sid-a"
    elif mutation == "wrong_form_id":
        container["id"] = "2"
    elif mutation == "missing_form":
        raw.pop("wlan_add")
    elif mutation == "extra_form":
        raw["wlan_add"] = [container, container]
    else:
        bindings[0] = "sid-a"
    with pytest.raises(ConfigurationError):
        _WIFI.read(raw)
    with pytest.raises(ConfigurationError):
        _WIFI.build(raw, {"wlan_allow_all": "0"})


def test_singleton_normalized_templates_are_supported() -> None:
    """Handle the codec's single-record representation without guessing selection."""
    raw = {
        "wlan_add": {
            "id": "1",
            "wlan_allow_all": "1",
            "sid": {"sid": "sid-a", "mdevice_name": "1"},
        },
        "wlan_addmdevice": {
            "sid": "sid-a",
            "mdevice_name": "",
            "mdevice_mac": "02:00:00:00:00:01",
        },
        "loginedSid": "sid-a",
    }
    assert _WIFI.read(raw)["allowed_devices"] == ["sid-a"]
    assert _WIFI.choices(raw)["allowed_devices"] == [
        {"value": "sid-a", "label": "sid-a"}
    ]


def test_duplicate_names_have_distinct_bounded_identity_labels() -> None:
    """Keep exact SIDs visible when hostnames repeat or need shortening."""
    raw = _raw()
    inventory = raw["wlan_addmdevice"]
    assert isinstance(inventory, list)
    for row in inventory:
        row["mdevice_name"] = "X" * 256
    options = _WIFI.choices(raw)["allowed_devices"]
    assert len({option["label"] for option in options}) == 3
    assert all(len(option["label"]) == 256 for option in options)


def test_inventory_exceeding_firmware_maximum_is_rejected() -> None:
    """Reject oversized inventories before generating indexed fields."""
    raw = _raw()
    raw["wlan_addmdevice"] = [
        {"sid": f"s{index}", "mdevice_name": "Device"} for index in range(254)
    ]
    with pytest.raises(ConfigurationError):
        _WIFI.read(raw)


def test_qos_exact_payload_and_empty_or_two_selected() -> None:
    """Allow zero to two priority devices with every SID/checkbox pair present."""
    raw = _raw("qos")
    assert _QOS.read(raw) == {"prioritized_devices": ["sid-a"]}
    payload = _QOS.build(raw, {"prioritized_devices": ["sid-b", "sid-c"]})
    assert payload == {
        "sid[11]": "sid-a",
        "mdevice_name[11]": "0",
        "sid[21]": "sid-b",
        "mdevice_name[21]": "1",
        "sid[31]": "sid-c",
        "mdevice_name[31]": "1",
    }
    empty = _QOS.build(raw, {"prioritized_devices": []})
    assert all(
        value == "0" for name, value in empty.items() if name.startswith("mdevice_name")
    )
    assert "use_priovoip" not in payload
    assert _QOS.endpoint == "data/QOS.json"
    assert _QOS.referer == "html/content/network/qos.html"


def test_qos_rejects_more_than_two_or_unknown_devices() -> None:
    """Enforce the native two-device limit and exact current identity choices."""
    for selected in (["sid-a", "sid-b", "sid-c"], ["unknown"]):
        with pytest.raises(ConfigurationError):
            _QOS.build(_raw("qos"), {"prioritized_devices": selected})
    with pytest.raises(ConfigurationError):
        _QOS.read(_after(_raw("qos"), ["sid-a", "sid-b", "sid-c"], family="qos"))


@pytest.mark.parametrize(
    "mutation", ["extra", "missing", "sid_swap", "wrong_flag", "wrong_suffix"]
)
def test_payload_validator_rejects_incomplete_or_misdirected_wires(
    mutation: str,
) -> None:
    """Reject missing keys, substituted IDs and unreviewed index suffixes."""
    raw = _raw()
    payload = _WIFI.build(raw, {"allowed_devices": ["sid-a", "sid-b"]})
    if mutation == "extra":
        payload["id"] = "1"
    elif mutation == "missing":
        payload.pop("sid[21]")
    elif mutation == "sid_swap":
        payload["sid[11]"] = "sid-b"
    elif mutation == "wrong_flag":
        payload["mdevice_name[21]"] = "2"
    else:
        payload["sid[2]"] = payload.pop("sid[21]")
    assert _WIFI.payload_validator is not None
    assert not _WIFI.payload_validator(raw, payload)


def test_verifier_requires_membership_and_full_inventory_identity() -> None:
    """Check current identities and the complete requested selection independently."""
    raw = _raw()
    changes = {"allowed_devices": ["sid-a", "sid-b"]}
    after = _after(raw, changes["allowed_devices"])
    assert _WIFI.verifier is not None
    assert _WIFI.verifier(raw, changes, after)
    assert not _WIFI.verifier(raw, changes, raw)
    after["wlan_addmdevice"][1]["mdevice_name"] = "Reused target"  # type: ignore[index]
    assert not _WIFI.verifier(raw, changes, after)
    qos_raw = _raw("qos")
    assert _QOS.verifier is not None
    assert _QOS.verifier(
        qos_raw,
        {"prioritized_devices": ["sid-c"]},
        _after(qos_raw, ["sid-c"], family="qos"),
    )


async def test_session_requires_fresh_revision_one_write_and_exact_readback() -> None:
    """Exercise the real grant boundary with one synthetic write and fresh read."""
    before = _raw()
    after = _after(before, ["sid-a", "sid-b"])
    read = AsyncMock(side_effect=[before, before, after])
    write = AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_WIFI, _OWNER, read)
    result = await session.save(
        _WIFI,
        _OWNER,
        initial["revision"],
        {"allowed_devices": ["sid-b", "sid-a"]},
        confirmed=True,
        confirmation_text=_WIFI.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    write.assert_awaited_once()
    assert "PRIVATE-MAC" not in str(initial)


async def test_device_reorder_invalidates_draft_before_any_write() -> None:
    """Bind row-order context so a changed inventory invalidates authorization."""
    before = _raw()
    changed = deepcopy(before)
    changed["wlan_addmdevice"].reverse()  # type: ignore[union-attr]
    read = AsyncMock(side_effect=[before, changed])
    write = AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_WIFI, _OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            _WIFI,
            _OWNER,
            initial["revision"],
            {"allowed_devices": ["sid-a", "sid-b"]},
            confirmed=True,
            confirmation_text=_WIFI.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


@pytest.mark.parametrize(("contract", "family"), [(_WIFI, "wlan"), (_QOS, "qos")])
def test_revision_ignores_telemetry_but_binds_full_private_identity(
    contract: SettingsContract, family: str
) -> None:
    """Bind identity, not counters, without returning private MACs to the UI."""
    raw = _raw(family)
    changed = deepcopy(raw)
    changed[f"{family}_addmdevice"][0].update(
        mdevice_rssi="-72", mdevice_downspeed="900", mdevice_connected="0"
    )
    assert contract.revision(raw) == contract.revision(changed)
    changed[f"{family}_addmdevice"][0]["mdevice_mac"] = "02:00:00:00:00:09"
    assert contract.revision(raw) != contract.revision(changed)
    assert "02:00:00" not in str(contract.read(raw))
    assert "02:00:00" not in str(contract.choices(raw))


def test_readback_rejects_sid_reused_with_different_mac() -> None:
    """An identical label and SID cannot hide replacement of the physical target."""
    before = _raw()
    after = _after(before, ["sid-a", "sid-b"])
    after["wlan_addmdevice"][1]["mdevice_mac"] = "02:00:00:00:00:09"
    assert _WIFI.verifier is not None
    assert not _WIFI.verifier(before, {"allowed_devices": ["sid-a", "sid-b"]}, after)


@pytest.mark.parametrize(("contract", "family"), [(_WIFI, "wlan"), (_QOS, "qos")])
def test_hyphen_mac_notation_has_identical_private_identity(
    contract: SettingsContract, family: str
) -> None:
    """Native inventories can spell the same MAC with either consistent delimiter."""
    raw, native = _raw(family), _raw(family)
    for row in native[f"{family}_addmdevice"]:
        row["mdevice_mac"] = row["mdevice_mac"].replace(":", "-").upper()
    assert contract.read(native) == contract.read(raw)
    assert contract.revision(native) == contract.revision(raw)


@pytest.mark.parametrize(
    "mac", [None, "", "bad", 1, "02:00:00:00:00:01\n", "02-00:00-00-00-01"]
)
def test_missing_or_malformed_mac_identity_fails_closed(mac: object) -> None:
    """Never authorize a target when its stable identity is absent."""
    raw = _raw()
    raw["wlan_addmdevice"][0]["mdevice_mac"] = mac
    with pytest.raises(ConfigurationError):
        _WIFI.read(raw)


async def test_no_ack_echo_shortcut_or_write_retry_when_readback_is_unchanged() -> None:
    """An ACK echo cannot replace fresh observed membership or authorize replay."""
    before = _raw()
    read = AsyncMock(return_value=before)
    write = AsyncMock(
        return_value={"status": "ok", "allowed_devices": ["sid-a", "sid-b"]}
    )
    session = ConfigurationSession()
    initial = await session.read(_WIFI, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            _WIFI,
            _OWNER,
            initial["revision"],
            {"allowed_devices": ["sid-a", "sid-b"]},
            confirmed=True,
            confirmation_text=_WIFI.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()
