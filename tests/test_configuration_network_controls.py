"""Synthetic native network controls; no router access or mutation during tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_network_controls import (
    NETWORK_CONTROL_SETTINGS,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession

_TETHER, _ACTIVATE, _BOND, _LED, _DELETE = NETWORK_CONTROL_SETTINGS
_OWNER = ("synthetic-admin", "synthetic-session")


def _raw() -> dict[str, Any]:
    return {
        "use_usb": "1",
        "use_lte": "0",
        "auto_external_modem": "0",
        "extwan_typ": "0",
        "hybrid_tunnel": "0",
        "use_tethering": "1",
        "tethering_status": "1",
        "neededTime": "100",
        "easy_support_deactive": "1",
        "use_bonding": "0",
        "ex5g_serial_number": "synthetic-receiver-serial",
        "ex5g_model_name": "synthetic-receiver-model",
        "ex5g_uptime": "100",
        "ex5g_led_mode": "0",
        "use_dyndns": "1",
        "dyndns_provider": "4",
        "dyndns_domain": "example.invalid",
        "dyndns_user": "synthetic-user",
        "dyndns_password": "synthetic-password",
        "dyndns_updsrv": "update.example.invalid",
        "dyndns_updurl": "/update?token=synthetic-secret",
        "dyndns_updprot": "1",
        "dyndns_updport": "443",
    }


def test_exact_native_endpoints_and_minimal_payloads() -> None:
    """Tethering module enable and forced activation have different native endpoints."""
    raw = _raw()
    assert _TETHER.endpoint == "data/Modules.json"
    assert _TETHER.read_endpoint == "data/INetTeth.json"
    assert _TETHER.build(raw, {"use_tethering": False}) == {"use_tethering": "0"}
    assert _ACTIVATE.endpoint == "data/INetTeth.json"
    assert _ACTIVATE.build(raw, {"activate_tethering": True}) == {
        "activate_teth": "true"
    }
    assert _BOND.build(raw, {"use_bonding": True}) == {"use_bonding": "1"}
    assert _LED.build(raw, {"ex5g_led_mode": "2"}) == {"ex5g_led_mode": "2"}
    assert _DELETE.build(raw, {"delete_provider": True}) == {"delprov": "true"}
    assert all(
        contract.acknowledgement == "readback" for contract in NETWORK_CONTROL_SETTINGS
    )


@pytest.mark.parametrize(
    ("contract", "changes"),
    [
        (_TETHER, {"use_tethering": "0"}),
        (_ACTIVATE, {"activate_tethering": 1}),
        (_BOND, {"use_bonding": 1}),
        (_LED, {"ex5g_led_mode": "3"}),
        (_DELETE, {"delete_provider": "true"}),
        (_ACTIVATE, {"rescan": True}),
        (_DELETE, {"refresh": True}),
        (_TETHER, {"endpoint": "data/INetTeth.json"}),
        (_LED, {"ex5g_serial_number": "different"}),
    ],
)
def test_closed_typed_fields_reject_coercion_and_invented_operations(
    contract: Any, changes: dict[str, object]
) -> None:
    """No caller-defined path, raw payload field, rescan POST or DDNS refresh."""
    with pytest.raises(ConfigurationError):
        contract.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation", ["usb_off", "receiver_path", "hybrid", "missing_mode", "bad_mode"]
)
def test_tethering_native_physical_and_mode_prerequisites(mutation: str) -> None:
    """Require usable USB and preserve native exclusion of active 5G/hybrid paths."""
    raw = _raw()
    if mutation == "usb_off":
        raw["use_usb"] = "0"
    elif mutation == "receiver_path":
        raw.update(auto_external_modem="1", extwan_typ="3")
    elif mutation == "hybrid":
        raw.update(use_lte="1", hybrid_tunnel="1")
    elif mutation == "missing_mode":
        raw.pop("auto_external_modem")
    else:
        raw.update(auto_external_modem="1", extwan_typ=[])
    with pytest.raises(ConfigurationError):
        _TETHER.build(raw, {"use_tethering": True})


def test_force_activation_requires_enabled_tethering_and_detected_device() -> None:
    """Never claim a disconnected USB device became the active Internet path."""
    for key in ("use_tethering", "tethering_status"):
        raw = _raw()
        raw[key] = "0"
        with pytest.raises(ConfigurationError):
            _ACTIVATE.build(raw, {"activate_tethering": True})
    raw = _raw()
    raw["tethering_status"] = "2"
    assert _ACTIVATE.read(raw) == {"activate_tethering": False}


def test_fresh_private_context_fallback_and_counter_independent_revisions() -> None:
    """Root can merge fixed prerequisite fields without publishing them in reads."""
    before, current = _raw(), _raw()
    fields = ("use_usb", "use_lte", "auto_external_modem", "extwan_typ")
    current["network_prerequisites"] = {name: current.pop(name) for name in fields}
    assert _TETHER.read(current) == _TETHER.read(before)
    assert _TETHER.revision(current) == _TETHER.revision(before)
    before["neededTime"] = "99"
    before["ex5g_uptime"] = "101"
    assert _TETHER.revision(current) == _TETHER.revision(before)
    assert _LED.revision(current) == _LED.revision(before)


def test_receiver_controls_require_exact_identity_and_manual_bonding_authority() -> (
    None
):
    """No missing hardware identity or EasySupport-managed bonding is overridden."""
    raw = _raw()
    raw["easy_support_deactive"] = "0"
    with pytest.raises(ConfigurationError, match="bonding_managed"):
        _BOND.build(raw, {"use_bonding": True})
    raw = _raw()
    raw["ex5g_serial_number"] = ""
    with pytest.raises(ConfigurationError):
        _LED.build(raw, {"ex5g_led_mode": "1"})


def test_ddns_erasure_requires_all_credentials_and_custom_path_removed() -> None:
    """Disabled alone is not deletion; retained login or custom URL fails proof."""
    before, after = _raw(), _raw()
    after.update(
        use_dyndns="0",
        dyndns_domain="",
        dyndns_user="",
        dyndns_password="",
        dyndns_updsrv="",
        dyndns_updurl=None,
        dyndns_updprot="0",
        dyndns_updport="80",
    )
    assert _DELETE.verifier is not None
    assert _DELETE.verifier(before, {"delete_provider": True}, after)
    for name in (
        "dyndns_domain",
        "dyndns_user",
        "dyndns_password",
        "dyndns_updsrv",
        "dyndns_updurl",
    ):
        retained = deepcopy(after)
        retained[name] = before[name]
        assert not _DELETE.verifier(before, {"delete_provider": True}, retained)
    assert "synthetic-password" not in str(_DELETE.read(before)) + str(
        _DELETE.metadata()
    )


@pytest.mark.parametrize(
    ("contract", "changes"),
    [
        (_TETHER, {"use_tethering": False}),
        (_ACTIVATE, {"activate_tethering": True}),
        (_BOND, {"use_bonding": True}),
    ],
)
async def test_switching_network_paths_reports_reconnect_required_not_verified(
    contract: Any, changes: dict[str, object]
) -> None:
    """Native callbacks prove no ACK or route; report an uncertain outcome."""
    raw = _raw()
    read, write = AsyncMock(return_value=raw), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "outcome_unknown", "verification": "reconnect_required"}
    write.assert_awaited_once()
    assert read.await_count == 2


async def test_receiver_led_exact_readback_rejects_receiver_replacement() -> None:
    """A different physical receiver cannot satisfy the original grant or readback."""
    before, after = _raw(), _raw()
    after["ex5g_led_mode"] = "1"
    assert _LED.verifier is not None
    assert _LED.verifier(before, {"ex5g_led_mode": "1"}, after)
    replaced = deepcopy(after)
    replaced["ex5g_serial_number"] = "different-receiver"
    assert not _LED.verifier(before, {"ex5g_led_mode": "1"}, replaced)
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_LED, _OWNER, read)
    assert await session.save(
        _LED,
        _OWNER,
        initial["revision"],
        {"ex5g_led_mode": "1"},
        confirmed=True,
        confirmation_text=_LED.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()


@pytest.mark.parametrize(
    ("wire", "code"),
    [("On", "0"), ("Timer", "1"), ("Off", "2"), ("0", "0"), ("1", "1"), ("2", "2")],
)
def test_receiver_led_proven_read_aliases_preserve_numeric_contract(
    wire: str, code: str
) -> None:
    """Native symbolic reads and decimal reads produce the same private revision."""
    raw = {**_raw(), "ex5g_led_mode": wire}
    numeric = {**raw, "ex5g_led_mode": code}
    assert _LED.read(raw) == {"ex5g_led_mode": code}
    assert _LED.revision(raw) == _LED.revision(numeric)
    for target in ("0", "1", "2"):
        assert _LED.build(raw, {"ex5g_led_mode": target}) == {"ex5g_led_mode": target}
    assert raw["ex5g_led_mode"] == wire


@pytest.mark.parametrize(
    "value", ["on", "timer", "off", "Always", "3", "Timer1", 1.0, True, None, ["Timer"]]
)
def test_receiver_led_unproven_read_aliases_remain_rejected(value: Any) -> None:
    """Case variants and coercions cannot widen the exact firmware evidence."""
    raw = {**_raw(), "ex5g_led_mode": value}
    with pytest.raises(ConfigurationError):
        _LED.read(raw)
    assert _LED.verifier is not None
    assert not _LED.verifier(_raw(), {"ex5g_led_mode": "1"}, raw)


@pytest.mark.parametrize("alias", ["On", "Timer", "Off"])
def test_receiver_led_symbolic_names_are_read_only_aliases(alias: str) -> None:
    """Callers still submit only the existing numeric enum values."""
    with pytest.raises(ConfigurationError):
        _LED.build(_raw(), {"ex5g_led_mode": alias})


@pytest.mark.parametrize(("after_wire", "target"), [("Timer", "1"), ("Off", "2")])
async def test_receiver_led_symbolic_preflight_and_readback_save_once(
    after_wire: str, target: str
) -> None:
    """A symbolic readback can prove a numeric write without changing identity rules."""
    before = {**_raw(), "ex5g_led_mode": "On"}
    after = {**before, "ex5g_led_mode": after_wire}
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_LED, _OWNER, read)
    assert initial["values"] == {"ex5g_led_mode": "0"}
    assert await session.save(
        _LED,
        _OWNER,
        initial["revision"],
        {"ex5g_led_mode": target},
        confirmed=True,
        confirmation_text=_LED.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()
    assert read.await_count == 3
    assert _LED.verifier is not None
    assert not _LED.verifier(
        before,
        {"ex5g_led_mode": target},
        {**after, "ex5g_serial_number": "replacement"},
    )


async def test_connected_tether_device_is_not_proof_of_active_route_or_noop() -> None:
    """An explicit switch still runs once when the USB link reports connected."""
    raw = _raw()
    raw.update(tethering_status="2", onlinestatus="online")
    read, write = AsyncMock(return_value=raw), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(_ACTIVATE, _OWNER, read)
    assert initial["values"] == {"activate_tethering": False}
    assert await session.save(
        _ACTIVATE,
        _OWNER,
        initial["revision"],
        {"activate_tethering": True},
        confirmed=True,
        confirmation_text=_ACTIVATE.confirmation,
        read=read,
        write=write,
    ) == {"status": "outcome_unknown", "verification": "reconnect_required"}
    write.assert_awaited_once()
