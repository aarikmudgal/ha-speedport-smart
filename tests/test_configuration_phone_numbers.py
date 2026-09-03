"""One-number creation preserves provider accounts and every existing number."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_phone_numbers import (
    normalize_new_phone_number,
    number_target_contract,
    number_target_metadata,
    number_target_rows,
)

_SETTING = "telephony_number_create_telekom"


def _raw() -> dict[str, Any]:
    return {
        "internet_connection": {"onlinestatus": "online"},
        "addipphoneprovider": [
            {
                "id": "99",
                "isp_selection": "automatic",
                "profile_version": "1",
                "addipnumber": [
                    {"ipphonenumber_id": "1", "ip_number": "+490000001", "clir": "0"}
                ],
            },
            {
                "id": "2",
                "isp_selection": "0",
                "t_mail": "KeepCase@example.invalid",
                "t_phonepwd": "",
                "addipnumber": [
                    {
                        "ipphonenumber_id": "4",
                        "ip_number": "+490000004",
                        "clir": "1",
                        "reject_on_busy": "0",
                        "number_status": "ok",
                    }
                ],
            },
        ],
    }


def test_number_create_payload_preserves_accounts_and_existing_numbers() -> None:
    """The new nested row uses the same ordinal contract with one explicit sentinel."""
    contract = number_target_contract(_SETTING, "2")
    payload = contract.build(_raw(), {"new_number": "0 123/009"})
    assert payload == {
        "id": "2",
        "isp_selection": "0",
        "t_mail": "KeepCase@example.invalid",
        "t_phonepwd": "",
        "ip_number[21]": "+490000004",
        "ipphonenumber_id[21]": "4",
        "ip_number[22]": "+49123009",
        "ipphonenumber_id[22]": "-1",
    }
    metadata = number_target_metadata()[0]
    assert metadata.pop("requires_target") is True
    assert metadata == contract.metadata()
    assert "t_phonepwd" not in contract.read(_raw())


@pytest.mark.parametrize(
    ("value", "provider", "expected"),
    [
        ("0049 (00) 00-9", "0", "+4900009"),
        ("0123", "0", "+49123"),
        ("phone@example.invalid", "1", "phone@example.invalid"),
        ("012 / 3", "89", "012 / 3"),
    ],
)
def test_exact_provider_number_normalization(
    value: str, provider: str, expected: str
) -> None:
    """Only Telekom numbers receive the firmware's country-prefix conversion."""
    assert normalize_new_phone_number(value, provider) == expected


@pytest.mark.parametrize("value", ["", "123", "+44123", "<script>", "x" * 33, True])
def test_invalid_telekom_numbers_rejected(value: Any) -> None:
    """Invalid or unsupported international forms do not reach a payload."""
    with pytest.raises(ConfigurationError):
        number_target_contract(_SETTING, "2").build(_raw(), {"new_number": value})


def test_duplicate_aliases_and_router_global_capacity_rejected() -> None:
    """Duplicates across providers and national/international aliases are rejected."""
    contract = number_target_contract(_SETTING, "2")
    duplicate = _raw()
    duplicate["addipphoneprovider"][0]["addipnumber"][0]["ip_number"] = "+491234"
    with pytest.raises(ConfigurationError):
        contract.build(duplicate, {"new_number": "01234"})
    raw = _raw()
    raw["addipphoneprovider"][0]["addipnumber"] = [
        {"ipphonenumber_id": str(index), "ip_number": f"+49000{index}"}
        for index in range(9)
    ]
    with pytest.raises(ConfigurationError, match="settings_capacity_reached"):
        number_target_rows(_SETTING, raw)


def test_verifier_requires_one_new_identity_and_preserved_automatic_siblings() -> None:
    """A matching name alone cannot prove creation or account preservation."""
    contract = number_target_contract(_SETTING, "2")
    before = _raw()
    after = deepcopy(before)
    after["addipphoneprovider"][1]["addipnumber"].append(
        {"ipphonenumber_id": "7", "ip_number": "+490000009", "clir": "0"}
    )
    assert contract.verifier is not None
    assert contract.verifier(before, {"new_number": "+490000009"}, after)
    after["addipphoneprovider"][0]["profile_version"] = "2"
    assert not contract.verifier(before, {"new_number": "+490000009"}, after)


def test_reused_id_wrong_number_or_changed_existing_options_cannot_verify() -> None:
    """New-row proof and existing number options are checked independently."""
    contract = number_target_contract(_SETTING, "2")
    before = _raw()
    assert contract.verifier is not None
    assert not contract.verifier(before, {"new_number": "+490000009"}, before)
    after = deepcopy(before)
    after["addipphoneprovider"][1]["addipnumber"].append(
        {"ipphonenumber_id": "7", "ip_number": "+490000009"}
    )
    after["addipphoneprovider"][1]["addipnumber"][0]["clir"] = "0"
    assert not contract.verifier(before, {"new_number": "+490000009"}, after)


def test_masked_credential_requires_reentry_and_offline_state_does_not_connect() -> (
    None
):
    """A new-number write never invents credentials or starts an Internet session."""
    raw = _raw()
    raw["addipphoneprovider"][1]["t_phonepwd"] = "[REDACTED]"
    with pytest.raises(ConfigurationError):
        number_target_contract(_SETTING, "2").build(raw, {"new_number": "+490000009"})
    raw = _raw()
    raw["internet_connection"]["onlinestatus"] = "offline"
    with pytest.raises(ConfigurationError):
        number_target_contract(_SETTING, "2").build(raw, {"new_number": "+490000009"})
