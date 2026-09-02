"""New provider contracts reuse validation and preserve existing accounts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_provider_create import (
    PROVIDER_CREATE_SETTINGS,
)


def _raw() -> dict[str, Any]:
    return {
        "internet_connection": {"onlinestatus": "online"},
        "addipphoneprovider": [
            {
                "id": "99",
                "isp_selection": "automatic",
                "profile_version": "1",
                "addipnumber": [
                    {"ipphonenumber_id": "1", "ip_number": "+491234", "clir": "0"}
                ],
            }
        ],
    }


def _draft() -> dict[str, Any]:
    return {
        "new_number": "01235",
        "t_mail": "User@example.invalid",
        "t_phonepwd": "Synthetic-pass",
    }


def _after() -> dict[str, Any]:
    raw = deepcopy(_raw())
    raw["addipphoneprovider"].append(
        {
            "id": "2",
            "isp_selection": "0",
            "t_mail": "user@example.invalid",
            "t_phonepwd": "[REDACTED]",
            "addipnumber": [
                {"ipphonenumber_id": "7", "ip_number": "+491235", "clir": "0"}
            ],
        }
    )
    return raw


def test_new_provider_payload_is_complete_and_uses_new_sentinels() -> None:
    """New provider and number sentinels do not overwrite the automatic account."""
    contract = PROVIDER_CREATE_SETTINGS[0]
    assert contract.build(_raw(), _draft()) == {
        "id": "-1",
        "isp_selection": "0",
        "t_mail": "user@example.invalid",
        "t_phonepwd": "Synthetic-pass",
        "ip_number[21]": "+491235",
        "ipphonenumber_id[21]": "-1",
    }
    assert contract.read(_raw()) == {"new_number": "", "t_mail": ""}
    assert contract.verifier_owns_fields is True
    assert contract.confirmation == "CREATE TELEPHONE PROVIDER"
    assert contract.verifier is not None
    assert contract.verifier(_raw(), _draft(), _after())


def test_new_provider_verification_checks_identity_number_and_old_account() -> None:
    """A successful-looking account cannot hide moved numbers or sibling changes."""
    verifier = PROVIDER_CREATE_SETTINGS[0].verifier
    assert verifier is not None
    after = _after()
    after["addipphoneprovider"][1]["addipnumber"][0]["ipphonenumber_id"] = "1"
    assert not verifier(_raw(), _draft(), after)
    after = _after()
    after["addipphoneprovider"][0]["profile_version"] = "2"
    assert not verifier(_raw(), _draft(), after)
    after = _after()
    after["addipphoneprovider"][1]["t_mail"] = "wrong@example.invalid"
    assert not verifier(_raw(), _draft(), after)
    assert not verifier(_raw(), _draft(), _raw())


def test_duplicate_number_capacity_and_missing_inventory_rejected() -> None:
    """Creation needs complete inventory and both global firmware capacities."""
    contract = PROVIDER_CREATE_SETTINGS[0]
    with pytest.raises(ConfigurationError):
        contract.build(_raw(), {**_draft(), "new_number": "01234"})
    with pytest.raises(ConfigurationError):
        contract.read({"internet_connection": {"onlinestatus": "online"}})
    raw = _raw()
    raw["addipphoneprovider"] *= 10
    with pytest.raises(ConfigurationError):
        contract.read(raw)


@pytest.mark.parametrize(
    ("index", "draft", "expected"),
    [
        (1, {"new_number": "1235", "areacode": "0123"}, {"areacode": "0123"}),
        (
            2,
            {
                "new_number": "user@example.invalid",
                "other_phonename": "Account",
                "other_phoneuser": "user",
                "other_pass": "Synthetic-pass",
                "other_registrar": "sip.example.invalid",
                "other_port": "5060",
            },
            {"other_port": "5060", "other_registrar": "sip.example.invalid"},
        ),
    ],
)
def test_other_new_provider_types_reuse_reviewed_exact_fields(
    index: int, draft: dict[str, Any], expected: dict[str, str]
) -> None:
    """Each provider type uses only its actual visible firmware section."""
    contract = PROVIDER_CREATE_SETTINGS[index]
    payload = contract.build(_raw(), draft)
    assert expected.items() <= payload.items()
    assert payload["id"] == "-1"
    assert "t_mail" not in payload


def test_offline_new_provider_never_connects_internet_implicitly() -> None:
    """The page's online prerequisite blocks, it does not invoke connect commands."""
    raw = _raw()
    raw["internet_connection"]["onlinestatus"] = "notconf"
    with pytest.raises(ConfigurationError):
        PROVIDER_CREATE_SETTINGS[0].build(raw, _draft())
