"""Tests for the offline Speedport custom-form contract sanitizer."""

from __future__ import annotations

import json

import pytest

from scripts.sanitize_form_contract import (
    FormContractError,
    classify_field_name,
    sanitize_form_contracts,
)


def _field_map(result: dict[str, object], form_index: int = 0) -> dict[str, object]:
    forms = result["forms"]
    assert isinstance(forms, list)
    form = forms[form_index]
    assert isinstance(form, dict)
    fields = form["fields"]
    assert isinstance(fields, list)
    return {str(field["name"]): field for field in fields}


def test_extracts_only_action_and_value_free_field_contract() -> None:
    """Action and types survive while live values, options, and labels disappear."""
    html = """
    <div class="panel form-internal other">
      <address>
        <span class="form-action"> ../../data/NASFolder.json </span>
        <span class="form-destination">private-destination.html</span>
      </address>
      <input name="profile_name" type="text" value="Alice's private share">
      <input name="nas_user_pwd" type="password" value="correct horse battery">
      <input name="enabled" type="checkbox" value="private-current-value" checked>
      <input name="choice" type="radio" value="manual" checked>
      <input name="choice" type="radio" value="auto">
      <select name="mode">
        <option value="0">Disabled private label</option>
        <option value="1" selected>Enabled private label</option>
        <option value="https://secret.example/token">Unsafe option</option>
      </select>
      <textarea name="notes">private free text</textarea>
      <button type="submit" name="action" value="save">Save private text</button>
    </div>
    """

    result = sanitize_form_contracts(html)

    assert result["format"] == 1
    assert result["summary"] == {"forms": 1, "fields": 6, "sensitive_fields": 1}
    assert result["safety"] == {
        "action_paths_only": True,
        "field_values_retained": False,
        "human_text_retained": False,
        "option_values_retained": False,
        "secret_values_retained": False,
    }
    form = result["forms"][0]
    assert form["action"] == "data/NASFolder.json"
    assert form["blockers"] == []
    fields = _field_map(result)
    assert fields["choice"] == {
        "name": "choice",
        "types": ["radio"],
        "classification": "opaque",
        "options": [],
        "options_incomplete": True,
    }
    assert fields["enabled"]["options"] == []
    assert fields["enabled"]["options_incomplete"] is True
    assert fields["mode"]["options"] == []
    assert fields["mode"]["options_incomplete"] is True
    assert fields["nas_user_pwd"] == {
        "name": "nas_user_pwd",
        "types": ["password"],
        "classification": "secret",
        "options": [],
        "options_incomplete": False,
    }
    assert fields["notes"]["types"] == ["textarea"]
    assert "action" not in fields

    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "Alice's private share",
        "correct horse battery",
        "private-current-value",
        "Disabled private label",
        "Enabled private label",
        "private free text",
        "private-destination.html",
        "secret.example",
        "Save private text",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("name", "input_type", "expected"),
    [
        ("nas_user_pwd", "text", "secret"),
        ("routerPassword", "text", "secret"),
        ("dyndns_othpassword", "text", "secret"),
        ("wlan-psk", "text", "secret"),
        ("ordinary", "password", "secret"),
        ("csrf_token", "hidden", "authentication"),
        ("device_id", "select-one", "identifier"),
        ("guest_ssid", "text", "private"),
        ("monkey_mode", "select-one", "opaque"),
    ],
)
def test_classifies_sensitive_names_by_exact_tokens(
    name: str,
    input_type: str,
    expected: str,
) -> None:
    """`pwd` and camel-case secrets are caught without substring false positives."""
    assert classify_field_name(name, input_type=input_type) == expected


def test_private_and_secret_selectors_never_retain_option_codes() -> None:
    """Option codes are omitted when a field can carry identity or secret data."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal">
          <span class="form-action">data/Example.json</span>
          <select name="device_id">
            <option value="household-device-1">Private device</option>
          </select>
          <select name="vpn_password">
            <option value="private-secret">Secret choice</option>
          </select>
        </div>
        """
    )

    fields = _field_map(result)
    assert fields["device_id"]["classification"] == "identifier"
    assert fields["device_id"]["options"] == []
    assert fields["device_id"]["options_incomplete"] is True
    assert fields["vpn_password"]["classification"] == "secret"
    assert fields["vpn_password"]["options"] == []
    assert fields["vpn_password"]["options_incomplete"] is True
    serialized = json.dumps(result)
    assert "household-device-1" not in serialized
    assert "private-secret" not in serialized


def test_opaque_selector_never_retains_private_option_value() -> None:
    """A generic field name cannot make an arbitrary option value share-safe."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal">
          <span class="form-action">data/Example.json</span>
          <select name="mode">
            <option value="MyPrivateSSID">Private network</option>
          </select>
        </div>
        """
    )

    field = _field_map(result)["mode"]
    assert field["classification"] == "opaque"
    assert field["options"] == []
    assert field["options_incomplete"] is True
    assert "MyPrivateSSID" not in json.dumps(result)


def test_checkbox_never_invents_or_retains_submission_codes() -> None:
    """Checkbox HTML alone proves neither a binary code nor its unchecked value."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal">
          <span class="form-action">data/Example.json</span>
          <input name="enabled" type="checkbox" value="yes">
        </div>
        """
    )

    field = _field_map(result)["enabled"]
    assert field["options"] == []
    assert field["options_incomplete"] is True
    assert "yes" not in json.dumps(result)


def test_duplicate_secret_type_keeps_value_free_field_contract() -> None:
    """Conflicting duplicate controls remain value-free after secret discovery."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal">
          <span class="form-action">data/Example.json</span>
          <select name="mode"><option value="1">One</option></select>
          <input name="mode" type="password" value="private-secret">
        </div>
        """
    )

    field = _field_map(result)["mode"]
    assert field["types"] == ["password", "select-one"]
    assert field["classification"] == "secret"
    assert field["options"] == []
    assert field["options_incomplete"] is True
    assert "private-secret" not in json.dumps(result)


def test_multiple_forms_are_scoped_deduplicated_and_sorted() -> None:
    """Fields outside custom forms are ignored and repeated controls are merged."""
    result = sanitize_form_contracts(
        """
        <input name="outside" value="must-not-appear">
        <div class="form-internal">
          <span class="form-action">../../data/Zed.json</span>
          <input name="state" type="radio" value="1">
          <input name="state" type="radio" value="0">
        </div>
        <div class="form-internal">
          <span class="form-action">data/Alpha.json</span>
          <input name="state" type="hidden" value="private">
        </div>
        """
    )

    assert [form["action"] for form in result["forms"]] == [
        "data/Alpha.json",
        "data/Zed.json",
    ]
    assert "outside" not in json.dumps(result)
    fields = _field_map(result, 1)
    assert fields["state"]["types"] == ["radio"]
    assert fields["state"]["options"] == []
    assert fields["state"]["options_incomplete"] is True


def test_missing_conflicting_and_unsafe_actions_fail_closed_without_echo() -> None:
    """Unsafe action text becomes fixed blockers and never enters output."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal"><input name="state"></div>
        <div class="form-internal">
          <span class="form-action">data/First.json</span>
          <span class="form-action">data/Second.json</span>
        </div>
        <div class="form-internal">
          <span class="form-action">https://router.invalid/data/Secret.json?token=raw</span>
        </div>
        """
    )

    blockers = [form["blockers"] for form in result["forms"]]
    assert ["missing_action"] in blockers
    assert ["conflicting_actions"] in blockers
    assert ["missing_action", "unsafe_action_omitted"] in blockers
    serialized = json.dumps(result)
    assert "router.invalid" not in serialized
    assert "token=raw" not in serialized


@pytest.mark.parametrize(
    ("html", "code"),
    [
        (
            '<div class="form-internal"><div class="form-internal"></div></div>',
            "nested_form_internal",
        ),
        (
            '<div class="form-internal"><input name="bad name"></div>',
            "unsafe_form_field_name",
        ),
        (
            '<div class="form-internal"><input name="field">',
            "unterminated_form_internal",
        ),
    ],
)
def test_rejects_ambiguous_html_with_fixed_error_codes(html: str, code: str) -> None:
    """Malformed contracts fail with value-free codes."""
    with pytest.raises(FormContractError, match=f"^{code}$") as error:
        sanitize_form_contracts(html)
    assert error.value.code == code


def test_rejects_oversized_html_before_parsing() -> None:
    """Bounded input prevents an offline evidence file from exhausting memory."""
    html = "x" * (8 * 1024 * 1024 + 1)
    with pytest.raises(FormContractError, match=r"^html_input_limit_exceeded$"):
        sanitize_form_contracts(html)


def test_ignores_current_values_for_every_supported_control_type() -> None:
    """No supported control type can copy its current value into evidence."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal">
          <span class="form-action">data/Types.json</span>
          <input name="text_field" value="TEXT_PRIVATE">
          <input name="hidden_field" type="hidden" value="HIDDEN_PRIVATE">
          <input name="number_field" type="number" value="987654321">
          <input name="file_field" type="file" value="FILE_PRIVATE">
          <textarea name="text_area">TEXTAREA_PRIVATE</textarea>
          <select name="state">
            <option value="1" selected>SELECT_PRIVATE</option>
          </select>
        </div>
        """
    )

    serialized = json.dumps(result)
    for forbidden in (
        "TEXT_PRIVATE",
        "HIDDEN_PRIVATE",
        "987654321",
        "FILE_PRIVATE",
        "TEXTAREA_PRIVATE",
        "SELECT_PRIVATE",
    ):
        assert forbidden not in serialized


def test_self_closing_structural_tags_do_not_leak_parser_state() -> None:
    """Self-closing custom containers and selects close their local context."""
    result = sanitize_form_contracts(
        """
        <div class="form-internal" />
        <div class="form-internal">
          <span class="form-action">data/Safe.json</span>
          <select name="first" />
          <option value="private-outside-select">Ignored</option>
          <input name="second" type="text" value="private">
        </div>
        """
    )

    assert result["summary"]["forms"] == 2
    safe_form = next(form for form in result["forms"] if form["action"])
    fields = {field["name"]: field for field in safe_form["fields"]}
    assert fields["first"]["options"] == []
    assert fields["second"]["types"] == ["text"]
    assert "private-outside-select" not in json.dumps(result)
