"""Offline proof of exact, conditional telephony forms and secret boundaries."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_telephony import (
    TELEPHONY_SETTINGS,
    normalize_dect_station_payload,
)

_CONTRACTS = {contract.id: contract for contract in TELEPHONY_SETTINGS}


def _dect() -> dict[str, object]:
    """Synthetic DECT state with a private test-only PIN."""
    return {
        "use_dect": "1",
        "use_smarthome": "0",
        "dect_pin": "012345",
        "dect_halb": "0",
        "dect_eco": "1",
        "addrepeater": [],
    }


def _vosip() -> dict[str, object]:
    """Synthetic provider and WAN prerequisite facts."""
    return {
        "phone_vosip_policy": "0",
        "addipphoneprovider": [{"id": "provider-1", "isp_selection": "0"}],
        "auto_external_modem": "0",
    }


def test_six_contracts_keep_existing_phone_basics_separate() -> None:
    """New contracts do not replace the three root-owned Phone settings."""
    assert len(_CONTRACTS) == 6
    assert not {
        "telephony_hd_voice",
        "telephony_dial_delay",
        "telephony_status_audio",
    } & (_CONTRACTS.keys())
    assert all(
        not contract.metadata()["live_write_verified"]
        for contract in TELEPHONY_SETTINGS
    )


def test_dect_module_ownership_and_endpoint() -> None:
    """Only the exact Modules flag is sent when Smart Home does not own DECT."""
    contract = _CONTRACTS["telephony_dect_enabled"]
    assert contract.endpoint == "data/Modules.json"
    assert contract.read_endpoint == "data/DECTStation.json"
    assert contract.read(_dect()) == {"use_dect": True}
    assert contract.build(_dect(), {"use_dect": False}) == {"use_dect": "0"}
    for raw in [{"use_dect": "1"}, {**_dect(), "use_smarthome": "1"}]:
        with pytest.raises(ConfigurationError):
            contract.build(raw, {"use_dect": False})


def test_dect_full_form_preserves_private_pin_without_exposing_it() -> None:
    """PIN is retained only in the one-shot payload, never editor read values."""
    contract = _CONTRACTS["telephony_dect_settings"]
    assert contract.endpoint == "data/DECTSettings.json"
    assert contract.read(_dect()) == {"dect_halb": "0", "dect_eco": "1"}
    assert contract.build(_dect(), {"dect_halb": "1"}) == {
        "dect_pin": "012345",
        "dect_halb": "1",
        "dect_eco": "1",
    }
    assert "012345" not in repr(contract)
    assert "012345" not in str(contract.metadata())


@pytest.mark.parametrize(
    "pin", ["", "123", "123456789", "123a", "\uff11\uff12\uff13\uff14", "****", None]
)
def test_dect_rejects_invalid_preserved_pin_without_echo(pin: object) -> None:
    """A missing/masked PIN cannot be silently resent or replaced."""
    contract = _CONTRACTS["telephony_dect_settings"]
    with pytest.raises(ConfigurationError) as raised:
        contract.build({**_dect(), "dect_pin": pin}, {"dect_eco": "0"})
    assert str(raised.value) in {"invalid_settings", "dect_pin_unavailable_or_invalid"}


def test_dect_explicit_pin_replaces_mask_with_full_form_preserved() -> None:
    """Explicit valid input can be used when the router masks the existing PIN."""
    assert _CONTRACTS["telephony_dect_settings"].build(
        {**_dect(), "dect_pin": "****"}, {"dect_pin": "0000"}
    ) == {"dect_pin": "0000", "dect_halb": "0", "dect_eco": "1"}


def test_dect_repeaters_hide_radio_fields_but_allow_pin_change() -> None:
    """Do not send radio fields hidden by firmware for a registered repeater."""
    contract = _CONTRACTS["telephony_dect_settings"]
    raw = {**_dect(), "addrepeater": [{"id": "rp1"}]}
    assert contract.build(raw, {"dect_pin": "0123"}) == {"dect_pin": "0123"}
    for field in ("dect_eco", "dect_halb"):
        with pytest.raises(ConfigurationError, match="blocked_by_repeater"):
            contract.build(raw, {field: "0"})
    for missing in [None, {}, ["not-a-row"]]:
        with pytest.raises(ConfigurationError, match="repeater_state"):
            contract.build({**_dect(), "addrepeater": missing}, {"dect_pin": "0123"})


def test_dect_absent_template_zero_only_for_complete_authenticated_station() -> None:
    """Real firmware omits absent templates; partial payloads remain unknown."""
    raw = {**_dect(), "router_state": "OK", "loginstate": "1"}
    del raw["addrepeater"]
    normalized = normalize_dect_station_payload(raw, authenticated=True)
    assert normalized["addrepeater"] == []
    assert "addrepeater" not in raw
    assert (
        _CONTRACTS["telephony_dect_settings"].build(normalized, {"dect_eco": "0"})[
            "dect_eco"
        ]
        == "0"
    )
    assert "addrepeater" not in normalize_dect_station_payload(raw, authenticated=False)
    for key in (
        "router_state",
        "loginstate",
        "dect_pin",
        "use_dect",
        "use_smarthome",
        "dect_halb",
        "dect_eco",
    ):
        partial = {name: value for name, value in raw.items() if name != key}
        assert "addrepeater" not in normalize_dect_station_payload(
            partial, authenticated=True
        )
    for explicit in (None, {}, ["bad"]):
        assert (
            normalize_dect_station_payload(
                {**raw, "addrepeater": explicit}, authenticated=True
            )["addrepeater"]
            == explicit
        )


def test_dect_singleton_repeater_mapping_keeps_radio_fields_blocked() -> None:
    """One existing row is not mistaken for zero repeaters."""
    raw = {**_dect(), "addrepeater": {"id": "rp1"}}
    contract = _CONTRACTS["telephony_dect_settings"]
    with pytest.raises(ConfigurationError, match="blocked_by_repeater"):
        contract.build(raw, {"dect_eco": "0"})
    assert contract.build(raw, {"dect_pin": "4567"}) == {"dect_pin": "4567"}


def test_vosip_read_and_write_have_distinct_endpoints() -> None:
    """The page reads PhoneLineset but submits its policy to Phone.json."""
    contract = _CONTRACTS["telephony_voice_encryption"]
    assert contract.endpoint == "data/Phone.json"
    assert contract.read_endpoint == "data/PhoneLineset.json"
    assert contract.read(_vosip()) == {"phone_vosip_policy": "0"}
    assert contract.build(_vosip(), {"phone_vosip_policy": "1"}) == {
        "phone_vosip_policy": "1"
    }


def test_vosip_singleton_provider_mapping_preserves_revision_shape() -> None:
    """One proven codec row is accepted without globally flattening collections."""
    contract = _CONTRACTS["telephony_voice_encryption"]
    row = {"id": "provider-1", "isp_selection": "0"}
    raw = {**_vosip(), "addipphoneprovider": row}
    assert contract.read(raw) == {"phone_vosip_policy": "0"}
    assert contract.build(raw, {"phone_vosip_policy": "1"}) == {
        "phone_vosip_policy": "1"
    }
    assert contract.revision(raw)["dependencies"]["addipphoneprovider"] is row
    assert raw["addipphoneprovider"] is row


@pytest.mark.parametrize(
    "provider", [{}, {"isp_selection": []}, {"isp_selection": "x"}]
)
def test_vosip_singleton_provider_mapping_is_still_strict(provider: object) -> None:
    """A mapping wrapper alone does not prove a configured Telekom provider."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["telephony_voice_encryption"].read(
            {**_vosip(), "addipphoneprovider": provider}
        )


@pytest.mark.parametrize(
    "prerequisites",
    [
        {"addipphoneprovider": []},
        {"addipphoneprovider": [{}]},
        {"addipphoneprovider": ["bad"]},
        {"addipphoneprovider": [{"isp_selection": "1"}]},
        {"auto_external_modem": None},
        {"auto_external_modem": "1", "extwan_typ": None},
        {"auto_external_modem": "1", "extwan_typ": "3", "lte_status": None},
    ],
)
def test_vosip_fails_when_prerequisites_are_unproven(
    prerequisites: dict[str, object],
) -> None:
    """Unknown provider/modem facts do not become permissive defaults."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["telephony_voice_encryption"].build(
            {**_vosip(), **prerequisites}, {"phone_vosip_policy": "2"}
        )


@pytest.mark.parametrize("lte_status", ["10", "11"])
def test_external_5g_cannot_enter_level_two(lte_status: str) -> None:
    """Existing level two may remain; entering it during active 5G is forbidden."""
    contract = _CONTRACTS["telephony_voice_encryption"]
    raw = {
        **_vosip(),
        "auto_external_modem": "1",
        "extwan_typ": "3",
        "lte_status": lte_status,
    }
    with pytest.raises(ConfigurationError, match="level_two"):
        contract.build(raw, {"phone_vosip_policy": "2"})
    assert contract.build(raw, {"phone_vosip_policy": "1"}) == {
        "phone_vosip_policy": "1"
    }
    assert contract.build(
        {**raw, "phone_vosip_policy": "2"}, {"phone_vosip_policy": "2"}
    ) == {"phone_vosip_policy": "2"}


@pytest.mark.parametrize(
    ("setting", "field", "read_endpoint"),
    [
        ("telephony_ip_pbx_enabled", "use_ippbx", "data/IPPBX.json"),
        ("telephony_automatic_speed_dial", "use_speeddial", "data/PhoneLineset.json"),
    ],
)
def test_exact_module_flags(setting: str, field: str, read_endpoint: str) -> None:
    """Module flags cannot smuggle another feature or raw endpoint into a write."""
    contract = _CONTRACTS[setting]
    assert contract.endpoint == "data/Modules.json"
    assert contract.read_endpoint == read_endpoint
    assert contract.build({field: "1"}, {field: False}) == {field: "0"}
    for changes in [{field: "0"}, {field: False, "use_usb": False}]:
        with pytest.raises(ConfigurationError):
            contract.build({field: "1"}, changes)


def test_phonebook_interval_exact_three_enums() -> None:
    """Synchronisation interval is not an arbitrary numeric duration."""
    contract = _CONTRACTS["telephony_phonebook_update_interval"]
    assert contract.build({"phonebook_int": "1"}, {"phonebook_int": "3"}) == {
        "phonebook_int": "3"
    }
    assert contract.fields[0].choices == (
        ("1", "15 minutes"),
        ("2", "30 minutes"),
        ("3", "60 minutes"),
    )
    for value in ("0", "4", 1, True):
        with pytest.raises(ConfigurationError):
            contract.build({"phonebook_int": "1"}, {"phonebook_int": value})
