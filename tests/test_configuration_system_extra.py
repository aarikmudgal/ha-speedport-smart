"""Offline contract proof for email, EasySupport and OLED rule selection."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_system_extra import (
    SYSTEM_EXTRA_SETTINGS,
    oled_rule_choices,
)

_CONTRACTS = {item.id: item for item in SYSTEM_EXTRA_SETTINGS}
_SUPPORT = {
    "easy_support_deactive": "0",
    "autofw_deactive": "0",
    "inet_isp": "0",
    "other_dt": "0",
    "onlinestatus": "online",
    "auto_external_modem": "0",
    "extwan_typ": "0",
    "use_tethering": "0",
    "tethering_status": "0",
    "provis_inet": "00",
    "bngnumbers": "0",
}
_RULES = {
    "disptime": "0",
    "addtime": [
        {"id": "1", "timerule_name": "Homework"},
        {"id": "2", "timerule_name": "Bedtime"},
    ],
}
_EMAIL = {
    "email_active": "1",
    "email_provider": "0",
    "email_t_username": "sample",
    "email_t_domain": "0",
    "email_t_password": "********",
    "email_other_username": "other@example.invalid",
    "email_other_password": "********",
    "email_smtp": "smtp.example.invalid",
    "email_port": "587",
    "email_sendto": "sample@t-online.de",
    "email_ev5_type": "0",
    "use_lte": "0",
    **{
        f"email_ev{number}": "0"
        for number in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)
    },
    "email_ev1": "1",
}


@pytest.mark.parametrize(
    ("raw", "changes", "expected"),
    [
        ({}, {"easy_support_deactive": True}, {"easy_support_deactive": "1"}),
        (
            {"easy_support_deactive": "1", "autofw_deactive": "1"},
            {"easy_support_deactive": False},
            {"easy_support_deactive": "0", "autofw_deactive": "0"},
        ),
        (
            {},
            {"autofw_deactive": True},
            {"autofw_deactive": "1", "easy_support_deactive": "1"},
        ),
        (
            {"easy_support_deactive": "1", "autofw_deactive": "1"},
            {"autofw_deactive": False},
            {"autofw_deactive": "0"},
        ),
        (
            {
                "easy_support_deactive": "1",
                "autofw_deactive": "1",
                "provis_inet": "04",
                "bngnumbers": "1",
            },
            {"autofw_deactive": False},
            {"autofw_deactive": "0"},
        ),
        (
            {"easy_support_deactive": "1", "autofw_deactive": "1"},
            {"easy_support_deactive": False, "autofw_deactive": False},
            {"easy_support_deactive": "0", "autofw_deactive": "0"},
        ),
    ],
)
def test_standard_support_mirrors_coupled_checkbox_payloads(
    raw: dict[str, Any], changes: dict[str, bool], expected: dict[str, str]
) -> None:
    """Preserve untouched flags and include only the firmware's derived changes."""
    contract = _CONTRACTS["system_easysupport"]
    assert contract.endpoint == "data/Modules.json"
    assert contract.read_endpoint == "data/EasySupport.json"
    assert contract.build({**_SUPPORT, **raw, "PRIVATE": "value"}, changes) == expected


def test_bng_activation_is_a_distinct_reconnect_unknown_contract() -> None:
    """BNG activation cannot be silently sent to the ordinary Modules path."""
    raw = {
        **_SUPPORT,
        "easy_support_deactive": "1",
        "autofw_deactive": "1",
        "provis_inet": "04",
    }
    changes = {"easy_support_deactive": False}
    with pytest.raises(ConfigurationError, match="branch_unavailable"):
        _CONTRACTS["system_easysupport"].build(raw, changes)
    contract = _CONTRACTS["system_easysupport_bng_activation"]
    assert contract.endpoint == "data/EasySupport.json"
    assert contract.build(raw, changes) == {
        "easy_support_deactive": "0",
        "autofw_deactive": "0",
    }
    assert contract.acknowledgement == "readback"
    assert contract.readback_policy == "reconnect_required"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"easy_support_deactive": True}, {"easy_support_deactive": "1"}),
        (
            {"autofw_deactive": True},
            {"autofw_deactive": "1", "easy_support_deactive": "1"},
        ),
    ],
)
def test_bng_profile_deactivation_selects_exact_endpoint(
    changes: dict[str, bool], expected: dict[str, str]
) -> None:
    """Profile presence routes coupled deactivation through EasySupport.json."""
    raw = {**_SUPPORT, "bngnumbers": "1"}
    with pytest.raises(ConfigurationError, match="branch_unavailable"):
        _CONTRACTS["system_easysupport"].build(raw, changes)
    contract = _CONTRACTS["system_easysupport_bng_deactivation"]
    assert contract.build(raw, changes) == expected
    assert contract.readback_policy == "exact"


@pytest.mark.parametrize(
    "key",
    [
        "inet_isp",
        "other_dt",
        "onlinestatus",
        "auto_external_modem",
        "extwan_typ",
        "use_tethering",
        "tethering_status",
        "provis_inet",
        "bngnumbers",
    ],
)
def test_support_requires_all_current_dynamic_route_dependencies(key: str) -> None:
    """Missing branch selectors never default to a less restrictive route."""
    raw = dict(_SUPPORT)
    del raw[key]
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_easysupport"].build(raw, {"easy_support_deactive": True})


@pytest.mark.parametrize(
    "changes",
    [
        {"easy_support_deactive": False, "autofw_deactive": True},
        {"easy_support_deactive": "1"},
        {"inet_isp": "0"},
        {},
    ],
)
def test_support_rejects_incompatible_or_unreviewed_changes(
    changes: dict[str, Any],
) -> None:
    """No invented independent combination bypasses the firmware coupling."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_easysupport"].build(_SUPPORT, changes)


@pytest.mark.parametrize(
    "raw",
    [
        {"inet_isp": "7"},
        {"onlinestatus": "offline", "auto_external_modem": "1", "extwan_typ": "3"},
        {"onlinestatus": "offline", "use_tethering": "1", "tethering_status": "2"},
    ],
)
def test_support_respects_provider_and_alternate_wan_restrictions(
    raw: dict[str, Any],
) -> None:
    """Provider and connectivity conditions reject hidden firmware controls."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_easysupport"].build(
            {**_SUPPORT, **raw}, {"easy_support_deactive": True}
        )


def test_support_dependencies_are_private_and_revision_bound() -> None:
    """Only the two flags appear in the editor, while all routing facts are bound."""
    contract = _CONTRACTS["system_easysupport"]
    before = {**_SUPPORT, "provis_inet": "PRIVATE"}
    assert "PRIVATE" not in repr(contract.read(before))
    assert contract.revision(before) != contract.revision(_SUPPORT)
    assert "bngnumbers" not in repr(contract.metadata())


def test_display_rule_has_distinct_post_and_full_read_source() -> None:
    """OLED controls rule assignment, not an invented timeout or TimeRules mutation."""
    contract = _CONTRACTS["system_oled_display_rule"]
    assert contract.endpoint == "data/OLEDtimerule.json"
    assert contract.read_endpoint == "data/TimeRules.json"
    assert contract.referer == "html/content/internet/chd_timerules.html"
    assert contract.build(_RULES, {"disptime": "2"}) == {"disptime": "2"}
    assert contract.build({**_RULES, "disptime": "1"}, {"disptime": "0"}) == {
        "disptime": "0"
    }
    assert oled_rule_choices(_RULES) == (
        ("0", "No rule"),
        ("1", "Homework"),
        ("2", "Bedtime"),
    )
    assert contract.fields[0].kind == "enum"
    assert contract.fields[0].dynamic_choices is True
    assert contract.choices(_RULES) == {
        "disptime": [
            {"value": "0", "label": "No rule"},
            {"value": "1", "label": "Homework"},
            {"value": "2", "label": "Bedtime"},
        ]
    }


@pytest.mark.parametrize(
    "source",
    [
        None,
        [None],
        [{"id": "0", "timerule_name": "Bad"}],
        [{"id": "1", "timerule_name": "One"}, {"id": "1", "timerule_name": "Other"}],
        [{"id": "1"}],
        [{"id": "1", "timerule_name": "bad\nname"}],
        [{"id": "1", "timerule_name": "One"}] * 65,
    ],
)
def test_display_requires_complete_unambiguous_existing_rule_inventory(
    source: object,
) -> None:
    """Incomplete, duplicate and oversized rule inventories fail closed."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_oled_display_rule"].build(
            {"disptime": "0", "addtime": source}, {"disptime": "1"}
        )


@pytest.mark.parametrize("value", ["3", "../data", "1;reset", "", 1, True])
def test_display_rejects_unknown_or_untyped_rule_ids(value: object) -> None:
    """Only existing string IDs and the explicit zero sentinel are accepted."""
    with pytest.raises(ConfigurationError):
        _CONTRACTS["system_oled_display_rule"].build(_RULES, {"disptime": value})


def test_display_inventory_change_invalidates_revision_without_exposing_rules() -> None:
    """Fresh rule names and membership are bound to the administrator review."""
    contract = _CONTRACTS["system_oled_display_rule"]
    changed = {**_RULES, "addtime": [{"id": "1", "timerule_name": "PRIVATE"}]}
    assert contract.read(changed) == {"disptime": "0"}
    assert contract.revision(changed) != contract.revision(_RULES)
    assert "PRIVATE" not in repr(contract.metadata())


def test_email_event_edit_preserves_hidden_account_and_full_visible_form() -> None:
    """Event-only edits never resend account text, passwords or unknown fields."""
    contract = _CONTRACTS["system_email_notifications"]
    assert contract.endpoint == "data/EMailNotify.json"
    assert contract.referer == "html/content/config/notify.html"
    payload = contract.build({**_EMAIL, "unreviewed": "PRIVATE"}, {"email_ev2": True})
    assert set(payload) == {
        "email_active",
        "email_provider",
        "email_t_domain",
        "email_port",
        *(f"email_ev{number}" for number in (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)),
    }
    assert payload["email_ev1"] == payload["email_ev2"] == "1"
    assert payload["email_port"] == "587"
    assert "sample" not in repr(payload)
    assert "********" not in repr(payload)
    assert "PRIVATE" not in repr(payload)


def test_email_explicit_empty_mobile_sentinels_follow_checkbox_parser() -> None:
    """Only the observed empty fields map to unchecked, never missing values."""
    contract = _CONTRACTS["system_email_notifications"]
    raw = {**_EMAIL, "email_ev14": "", "email_ev15": ""}
    assert contract.read(raw)["email_ev14"] is False
    assert contract.read(raw)["email_ev15"] is False
    assert "email_ev14" not in contract.build(raw, {"email_ev2": True})
    active = {**raw, "use_lte": "1"}
    assert contract.read(active)["email_ev14"] is False
    assert contract.build(active, {"email_ev2": True})["email_ev14"] == "0"
    assert contract.build(active, {"email_ev14": True})["email_ev14"] == "1"
    for mobile in (None, "", "unknown"):
        with pytest.raises(ConfigurationError):
            contract.read({**raw, "use_lte": mobile})
    with pytest.raises(ConfigurationError):
        contract.read({**raw, "email_ev14": None})


@pytest.mark.parametrize("domain", ["0", "1"])
def test_email_telekom_account_uses_exact_domain_and_fresh_password(
    domain: str,
) -> None:
    """The selected domain text derives the recipient; stored masks are not sent."""
    contract = _CONTRACTS["system_email_notifications"]
    changes = {
        "email_t_username": "new-sample",
        "email_t_domain": domain,
        "email_t_password": "new=email-password",
    }
    payload = contract.build(_EMAIL, changes)
    assert payload["email_t_password"] == "new=email-password"  # noqa: S105
    assert payload["email_sendto"] == (
        "new-sample@t-online.de" if domain == "0" else "new-sample@magenta.de"
    )
    assert payload["samerecip"] == "1"
    assert "email_other_username" not in payload
    assert "email_other_password" not in payload
    assert "email_smtp" not in payload
    assert contract.expected_values is not None
    expected = contract.expected_values(_EMAIL, changes)
    assert expected["samerecip"] is True
    assert expected["email_sendto"] == payload["email_sendto"]
    assert "password" not in repr(expected)


def test_email_other_account_with_separate_recipient_omits_hidden_checkbox() -> None:
    """Provider switching keeps hidden selects but only submits visible credentials."""
    changes = {
        "email_provider": "1",
        "email_other_password": "fresh-password",
        "samerecip": False,
        "email_sendto": "receiver@example.invalid",
        "email_port": "465",
    }
    contract = _CONTRACTS["system_email_notifications"]
    payload = contract.build(_EMAIL, changes)
    assert payload["email_other_username"] == "other@example.invalid"
    assert payload["email_other_password"] == "fresh-password"  # noqa: S105
    assert payload["email_smtp"] == "smtp.example.invalid"
    assert payload["email_sendto"] == "receiver@example.invalid"
    assert payload["email_t_domain"] == "0"
    assert "email_t_username" not in payload
    assert "email_t_password" not in payload
    assert "samerecip" not in payload
    assert contract.expected_values is not None
    assert contract.expected_values(_EMAIL, changes)["samerecip"] is False


def test_email_recipient_checkbox_is_derived_not_a_backend_claim() -> None:
    """Case-insensitive equality is exactly the firmware's initial checkbox state."""
    contract = _CONTRACTS["system_email_notifications"]
    values = contract.read(
        {**_EMAIL, "email_sendto": "SAMPLE@T-ONLINE.DE", "samerecip": "0"}
    )
    assert values["samerecip"] is True
    assert "email_t_password" not in values
    assert "email_other_password" not in values
    changes = {"samerecip": False, "email_t_password": "fresh-password"}
    assert contract.expected_values is not None
    assert contract.expected_values(_EMAIL, changes)["samerecip"] is True


@pytest.mark.parametrize("key", list(_EMAIL.keys()))
def test_email_requires_complete_nonsecret_form_and_visibility_dependency(
    key: str,
) -> None:
    """A missing current field cannot be replaced with a convenient default."""
    contract = _CONTRACTS["system_email_notifications"]
    raw = dict(_EMAIL)
    del raw[key]
    if key in {"email_t_password", "email_other_password"}:
        assert contract.build(raw, {"email_ev2": True})["email_ev2"] == "1"
    else:
        with pytest.raises(ConfigurationError):
            contract.build(raw, {"email_ev2": True})


@pytest.mark.parametrize(
    ("raw", "changes", "code"),
    [
        ({}, {"email_t_username": "changed"}, "email_password_required"),
        ({}, {"samerecip": False}, "email_password_required"),
        ({}, {"email_t_password": "********"}, "invalid_settings"),
        ({}, {"email_t_password": "<redacted>"}, "invalid_settings"),
        ({}, {"email_other_password": "fresh"}, "email_inactive_fields"),
        ({}, {"email_port": "25"}, "email_inactive_fields"),
        ({}, {"email_ev1": False}, "email_event_required"),
        ({}, {"email_ev14": True}, "email_inactive_fields"),
        ({}, {"email_ev5_type": "1"}, "email_inactive_fields"),
        ({"email_ev6": "1"}, {"email_ev12": True}, "email_daily_report_dependency"),
        ({}, {"email_active": False, "email_ev2": True}, "email_inactive_fields"),
        ({}, {"email_provider": "2"}, "invalid_settings"),
        ({}, {"email_t_domain": "2"}, "invalid_settings"),
        ({}, {"email_port": "2525"}, "invalid_settings"),
        ({}, {"email_ev2": "1"}, "invalid_settings"),
        ({}, {"email_ev3": True}, "invalid_settings"),
        ({}, {"delete": "true"}, "invalid_settings"),
        (
            {},
            {"email_t_password": "fresh", "email_sendto": "other@example.invalid"},
            "email_recipient_conflict",
        ),
        (
            {},
            {"email_t_password": "fresh", "samerecip": False, "email_sendto": "bad"},
            "email_recipient_required",
        ),
        (
            {},
            {"email_t_password": "fresh", "email_t_username": ""},
            "email_account_required",
        ),
        (
            {},
            {"email_t_password": "fresh", "email_t_username": "a" * 255},
            "email_recipient_required",
        ),
        ({}, {"email_t_password": "bad\npassword"}, "invalid_settings"),
    ],
)
def test_email_rejects_unproven_or_conflicting_form_changes(
    raw: dict[str, Any], changes: dict[str, Any], code: str
) -> None:
    """Conditional fields and secret placeholders fail before any transport call."""
    with pytest.raises(ConfigurationError, match=code):
        _CONTRACTS["system_email_notifications"].build({**_EMAIL, **raw}, changes)


def test_email_disable_only_submits_active_and_always_serialized_selects() -> None:
    """Hidden checkbox/text/radio controls stay unchanged when notifications stop."""
    contract = _CONTRACTS["system_email_notifications"]
    assert contract.build(_EMAIL, {"email_active": False}) == {
        "email_active": "0",
        "email_provider": "0",
        "email_t_domain": "0",
        "email_port": "587",
    }
    assert contract.expected_values is not None
    expected = contract.expected_values(_EMAIL, {"email_active": False})
    assert expected["email_ev1"] is True
    assert expected["email_active"] is False


def test_email_dependent_visible_controls_and_initial_setup() -> None:
    """Call type and mobile events appear only when their parent controls allow it."""
    contract = _CONTRACTS["system_email_notifications"]
    payload = contract.build(
        {**_EMAIL, "use_lte": "1", "email_ev6": "1", "email_ev12": "1"},
        {"email_ev5": True, "email_ev5_type": "1", "email_ev14": True},
    )
    assert payload["email_ev5_type"] == "1"
    assert payload["email_ev14"] == "1"
    assert payload["email_ev15"] == "0"
    assert payload["email_ev12"] == "1"
    raw = {**_EMAIL, "email_sendto": "", "email_t_username": ""}
    with pytest.raises(ConfigurationError, match="email_password_required"):
        contract.build(raw, {"email_ev2": True})
    payload = contract.build(
        raw,
        {
            "email_t_username": "initial",
            "email_t_password": "fresh-password",
        },
    )
    assert payload["email_sendto"] == "initial@t-online.de"


def test_email_metadata_never_contains_current_addresses_or_secrets() -> None:
    """Private values stay in the explicit editor, not static dashboard metadata."""
    contract = _CONTRACTS["system_email_notifications"]
    assert len(contract.fields) == 26
    assert "sample" not in repr(contract.metadata())
    assert "smtp.example.invalid" not in repr(contract.metadata())
    assert "********" not in repr(contract.metadata())
    assert contract.revision(_EMAIL) != contract.revision({**_EMAIL, "use_lte": "1"})
    assert contract.revision(_EMAIL) != contract.revision(
        {**_EMAIL, "email_t_password": "changed"}
    )
