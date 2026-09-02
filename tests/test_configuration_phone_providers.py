"""Existing provider credential editor contracts using synthetic offline fixtures."""

# ruff: noqa: S105 - synthetic credentials only

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phone_providers import (
    provider_target_contract,
    provider_target_metadata,
    provider_target_rows,
)


def _raw(provider: str = "0") -> dict[str, Any]:
    return {
        "internet_connection": {"onlinestatus": "online"},
        "addipphoneprovider": {
            "id": "2",
            "isp_selection": provider,
            "t_mail": "account@example.invalid",
            "t_phonepwd": "Example-secret1",
            "areacode": "030",
            "other_phonename": "Example SIP",
            "other_phoneuser": "sip-user",
            "other_pass": "Other-secret1",
            "other_registrar": "sip.example.invalid",
            "other_port": "5060",
            "addipnumber": [
                {
                    "ipphonenumber_id": "0",
                    "ip_number": "+4900000001",
                    "number_status": "ok",
                },
                {
                    "ipphonenumber_id": "5",
                    "ip_number": "+4900000002",
                    "number_status": "inactive",
                },
            ],
        },
    }


def test_static_provider_metadata_and_primary_read_endpoint() -> None:
    """Use the page JSONSource, not IPPhone.json's delete shortcut."""
    for metadata in provider_target_metadata():
        assert metadata.pop("requires_target") is True
        contract = provider_target_contract(metadata["id"], "2")
        assert metadata == contract.metadata()
        assert contract.read_endpoint == "data/IPPhoneHandler.json"


def test_telekom_form_preserves_numbers_and_excludes_other_provider_fields() -> None:
    """An existing provider form retains every real number and private credential."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    raw = _raw()
    before = deepcopy(raw)
    assert contract.read(raw) == {"t_mail": "account@example.invalid"}
    assert contract.build(raw, {"t_mail": "new@example.invalid"}) == {
        "id": "2",
        "isp_selection": "0",
        "t_mail": "new@example.invalid",
        "t_phonepwd": "Example-secret1",
        "ip_number[11]": "+4900000001",
        "ipphonenumber_id[11]": "0",
        "ip_number[12]": "+4900000002",
        "ipphonenumber_id[12]": "5",
    }
    assert raw == before
    assert (
        contract.build(raw, {"t_mail": "NEW@Example.invalid"})["t_mail"]
        == "new@example.invalid"
    )
    assert contract.expected_values is not None
    assert contract.expected_values(raw, {"t_mail": "NEW@Example.invalid"}) == {
        "t_mail": "new@example.invalid"
    }


def test_other_and_regio_forms_have_only_their_visible_credentials() -> None:
    """Provider type cannot be switched by a client-supplied field or target."""
    raw = _raw("1")
    other = provider_target_contract("telephony_provider_other", "2")
    payload = other.build(raw, {"other_phoneuser": "new-user"})
    assert payload["other_pass"] == "Other-secret1"
    assert not {"t_mail", "t_phonepwd", "areacode", "show_t_mail"} & payload.keys()
    regio = provider_target_contract("telephony_provider_regio", "2")
    payload = regio.build(_raw("89"), {"areacode": "040"})
    assert set(payload) == {
        "id",
        "isp_selection",
        "areacode",
        "ip_number[11]",
        "ipphonenumber_id[11]",
        "ip_number[12]",
        "ipphonenumber_id[12]",
    }


def test_automatic_provider_never_has_writable_target() -> None:
    """Firmware hides provider 99's editor; do not bypass that restriction."""
    raw = _raw()
    raw["addipphoneprovider"]["id"] = "99"
    assert provider_target_rows("telephony_provider_telekom", raw) == ()
    with pytest.raises(ConfigurationError):
        provider_target_contract("telephony_provider_telekom", "99")


@pytest.mark.parametrize(
    "changes",
    [
        {"isp_selection": "1"},
        {"id": "7"},
        {"ip_number[11]": "000"},
        {"show_t_mail": "new@example.invalid"},
        {"t_mail": "not-an-email"},
        {"t_phonepwd": "********"},
        {"t_phonepwd": "[REDACTED]"},
    ],
)
def test_extra_fields_and_invalid_credentials_are_rejected(
    changes: dict[str, Any],
) -> None:
    """Credential forms cannot become unrestricted telephone-number writes."""
    with pytest.raises(ConfigurationError):
        provider_target_contract("telephony_provider_telekom", "2").build(
            _raw(), changes
        )


def test_mask_or_missing_secret_cannot_be_reused_as_password() -> None:
    """Only an explicit existing blank is preserved; unknown and masks fail closed."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    raw = _raw()
    for value in (None, "********", "[REDACTED]"):
        raw["addipphoneprovider"]["t_phonepwd"] = value
        with pytest.raises(ConfigurationError):
            contract.build(raw, {"t_mail": "new@example.invalid"})
        assert (
            contract.build(raw, {"t_phonepwd": "Fresh-secret1"})["t_phonepwd"]
            == "Fresh-secret1"
        )
    raw["addipphoneprovider"]["t_phonepwd"] = ""
    assert contract.build(raw, {"t_mail": "new@example.invalid"})["t_phonepwd"] == ""
    assert "t_phonepwd" not in contract.read(raw)


@pytest.mark.parametrize(
    "connection",
    [
        None,
        {},
        {"onlinestatus": "offline"},
        {
            "onlinestatus": "notconf",
            "auto_external_modem": "1",
            "extwan_typ": "3",
            "lte_status": "10",
        },
    ],
)
def test_no_online_proof_prevents_submission(connection: object) -> None:
    """Saving numbers requires the firmware's InternetConnection prerequisite."""
    raw = _raw()
    raw["internet_connection"] = connection
    with pytest.raises(ConfigurationError):
        provider_target_contract("telephony_provider_telekom", "2").build(
            raw, {"t_mail": "new@example.invalid"}
        )


def test_all_number_rows_and_sibling_credentials_checked_on_readback() -> None:
    """Changed credentials cannot hide number deletion or collateral provider edits."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    before = _raw()
    after = deepcopy(before)
    after["addipphoneprovider"]["t_mail"] = "new@example.invalid"
    assert contract.verifier is not None
    assert contract.verifier(before, {"t_mail": "new@example.invalid"}, after)
    after["addipphoneprovider"]["addipnumber"].pop()
    assert not contract.verifier(before, {"t_mail": "new@example.invalid"}, after)


def test_provider_type_mismatch_and_incomplete_numbers_fail_closed() -> None:
    """Missing nested rows cannot be treated as an empty number list."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    with pytest.raises(ConfigurationError):
        contract.read(_raw("1"))
    raw = _raw()
    raw["addipphoneprovider"].pop("addipnumber")
    with pytest.raises(ConfigurationError):
        contract.build(raw, {"t_mail": "new@example.invalid"})


def test_automatic_sibling_preserved_without_editable_form_assumptions() -> None:
    """A stable automatic profile is not rejected for lacking manual form fields."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    before = _raw()
    before["addipphoneprovider"] = [
        {"id": "99", "isp_selection": "automatic", "profile_version": "1"},
        before["addipphoneprovider"],
    ]
    after = deepcopy(before)
    after["addipphoneprovider"][1]["t_mail"] = "new@example.invalid"
    assert contract.verifier is not None
    assert contract.verifier(before, {"t_mail": "new@example.invalid"}, after)
    after["addipphoneprovider"][0]["profile_version"] = "2"
    assert not contract.verifier(before, {"t_mail": "new@example.invalid"}, after)


def test_registration_status_can_change_but_stable_number_options_cannot() -> None:
    """Registration outcomes are volatile; number options remain preservation checks."""
    contract = provider_target_contract("telephony_provider_telekom", "2")
    before = _raw()
    before["addipphoneprovider"]["addipnumber"][0].update(clir="0", errnr="7")
    after = deepcopy(before)
    after["addipphoneprovider"]["t_phonepwd"] = "Fresh-secret1"
    after["addipphoneprovider"]["addipnumber"][0].update(number_status="ok", errnr="0")
    assert contract.verifier is not None
    assert contract.verifier(before, {"t_phonepwd": "Fresh-secret1"}, after)
    after["addipphoneprovider"]["addipnumber"][0]["clir"] = "1"
    assert not contract.verifier(before, {"t_phonepwd": "Fresh-secret1"}, after)
