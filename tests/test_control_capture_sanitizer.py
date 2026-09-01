"""Tests for the offline browser-capture contract sanitizer."""

from __future__ import annotations

import json
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from custom_components.speedport_smart.api.codec import DEFAULT_KEY, encode_payload
from scripts.sanitize_control_capture import (
    CaptureError,
    CaptureSpec,
    _write_private_json,
    sanitize_control_capture,
)

_ORIGIN = "http://router.private"
_CHALLENGE = "11" * 32
_SESSION_KEY = bytes.fromhex(_CHALLENGE)
_POST_PATH = "data/LTE.json"
_READBACK_PATH = "data/LTE.json"


def _encrypted_form(fields: dict[str, str], key: bytes = _SESSION_KEY) -> str:
    """Return one synthetic encrypted browser request body."""
    return encode_payload(urlencode(fields), key)


def _encrypted_json(document: dict[str, Any], key: bytes = _SESSION_KEY) -> str:
    """Return one synthetic encrypted browser response body."""
    return encode_payload(json.dumps(document, separators=(",", ":")), key)


def _entry(
    method: str,
    path: str,
    *,
    request_body: str | None = None,
    response_body: str,
    status: int = 200,
    referer: str = "html/content/internet/lte_mode.html",
    host: str = _ORIGIN,
) -> dict[str, Any]:
    """Build one bounded synthetic HAR entry."""
    request: dict[str, Any] = {
        "method": method,
        "url": f"{host}/{path}",
        "headers": [
            {"name": "Cookie", "value": "session=private-session-cookie"},
            {"name": "X-CSRF-Token", "value": "private-csrf-token"},
            {"name": "Referer", "value": f"{host}/{referer}"},
        ],
    }
    if request_body is not None:
        request["postData"] = {
            "mimeType": "application/x-www-form-urlencoded; charset=UTF-8",
            "text": request_body,
        }
    return {
        "request": request,
        "response": {
            "status": status,
            "content": {
                "mimeType": "application/json",
                "text": response_body,
            },
        },
    }


def _private_fields(state: str, *, auth_marker: str) -> dict[str, str]:
    """Return a complete synthetic form containing every privacy class."""
    return {
        "use_bonding": state,
        "httoken": auth_marker,
        "session_id": f"private-session-{auth_marker}",
        "router_password": "correct horse battery staple",
        "wifi_key": "private-wifi-key",
        "ssid": "Family Network",
        "mdevice_mac": "AA:BB:CC:DD:EE:FF",
        "mdevice_ipv4": "10.168.10.23",
        "mdevice_name": "Aarik Phone",
        "phone_number": "+49 30 1234567",
        "contact_email": "private@example.test",
        "serial_number": "PRIVATE-SERIAL-123",
    }


def _readback(state: str) -> dict[str, Any]:
    """Return a synthetic response with unrelated private values."""
    return {
        "use_bonding": state,
        "ssid": "Family Network",
        "mdevice_mac": "AA:BB:CC:DD:EE:FF",
        "mdevice_ipv4": "10.168.10.23",
        "phone_number": "+49 30 1234567",
    }


def _complete_har() -> dict[str, Any]:
    """Return one exact baseline/apply/readback/rollback/readback sequence."""
    return {
        "log": {
            "entries": [
                _entry(
                    "POST",
                    "data/Login.json",
                    request_body=_encrypted_form(
                        {"getChallenge": "1"},
                        DEFAULT_KEY,
                    ),
                    response_body=_encrypted_json(
                        {"challenge": _CHALLENGE},
                        DEFAULT_KEY,
                    ),
                    referer="html/login/login.html",
                ),
                _entry(
                    "GET",
                    f"{_READBACK_PATH}?_time=1",
                    response_body=_encrypted_json(_readback("0")),
                ),
                _entry(
                    "POST",
                    _POST_PATH,
                    request_body=_encrypted_form(
                        _private_fields("1", auth_marker="111")
                    ),
                    response_body=_encrypted_json(
                        {
                            "status": "success",
                            "message": (
                                "Family Network AA:BB:CC:DD:EE:FF "
                                "10.168.10.23 +49 30 1234567"
                            ),
                        }
                    ),
                ),
                _entry(
                    "GET",
                    f"{_READBACK_PATH}?_time=2",
                    response_body=_encrypted_json(_readback("1")),
                ),
                _entry(
                    "POST",
                    _POST_PATH,
                    request_body=_encrypted_form(
                        _private_fields("0", auth_marker="222")
                    ),
                    response_body=_encrypted_json({"status": "success"}),
                ),
                _entry(
                    "GET",
                    f"{_READBACK_PATH}?_time=3",
                    response_body=_encrypted_json(_readback("0")),
                ),
            ]
        }
    }


def _spec() -> CaptureSpec:
    """Return the explicit public scalar allowlist used by the fixture."""
    return CaptureSpec(
        operation="set_hybrid_bonding",
        post_path=_POST_PATH,
        state_field="use_bonding",
        state_values=("0", "1"),
        readback_path=_READBACK_PATH,
        readback_field="use_bonding",
    )


def test_sanitizes_complete_encrypted_roundtrip_without_private_values() -> None:
    """Exact contract structure survives while all live values disappear."""
    har = _complete_har()
    apply_ciphertext = har["log"]["entries"][2]["request"]["postData"]["text"]

    result = sanitize_control_capture(har, _spec())

    assert result["proof"] == {
        "apply_changed_state": True,
        "apply_readback_matches": True,
        "rollback_requested_baseline": True,
        "rollback_restored_baseline": True,
        "complete": True,
        "blockers": [],
    }
    assert result["request"]["path"] == _POST_PATH
    assert result["request"]["referer_path"] == ("html/content/internet/lte_mode.html")
    assert result["acknowledgement"]["apply"] == {
        "http_status": 200,
        "value": "success",
        "positive": True,
    }
    assert result["readback"] == {
        "method": "GET",
        "path": _READBACK_PATH,
        "field": "use_bonding",
        "baseline": "0",
        "applied": "1",
        "restored": "0",
        "independent_gets": True,
    }
    fields = {field["name"]: field for field in result["request"]["fields"]}
    assert (
        fields["use_bonding"]
        | {
            "name": "use_bonding",
            "role": "state",
            "apply": "1",
            "rollback": "0",
        }
        == fields["use_bonding"]
    )
    assert fields["httoken"]["role"] == "authentication"
    assert fields["router_password"]["role"] == "secret"
    assert fields["mdevice_mac"]["role"] == "identifier"
    assert fields["ssid"]["role"] == "private"

    serialized = json.dumps(result, sort_keys=True)
    for private_value in (
        "router.private",
        "private-session-cookie",
        "private-csrf-token",
        _CHALLENGE,
        apply_ciphertext,
        "correct horse battery staple",
        "private-wifi-key",
        "Family Network",
        "AA:BB:CC:DD:EE:FF",
        "10.168.10.23",
        "Aarik Phone",
        "+49 30 1234567",
        "private@example.test",
        "PRIVATE-SERIAL-123",
    ):
        assert private_value not in serialized


def test_nonpositive_ack_is_a_sanitized_blocker() -> None:
    """A rejected response never becomes positive proof or leaks its value."""
    har = _complete_har()
    har["log"]["entries"][2]["response"]["content"]["text"] = _encrypted_json(
        {"status": "failed", "message": "private@example.test"}
    )

    result = sanitize_control_capture(har, _spec())

    assert result["proof"]["complete"] is False
    assert result["proof"]["blockers"] == ["apply_ack_not_positive"]
    assert result["acknowledgement"]["apply"] == {
        "http_status": 200,
        "value": None,
        "positive": False,
    }
    serialized = json.dumps(result)
    assert "failed" not in serialized
    assert "private@example.test" not in serialized


def test_missing_independent_readback_fails_closed() -> None:
    """A POST response can never substitute for the post-change GET."""
    har = _complete_har()
    del har["log"]["entries"][3]

    with pytest.raises(CaptureError, match="missing_independent_readback"):
        sanitize_control_capture(har, _spec())


def test_unsuccessful_readback_is_not_proof() -> None:
    """An error response containing a state-shaped body cannot prove readback."""
    har = _complete_har()
    har["log"]["entries"][3]["response"]["status"] = 500

    with pytest.raises(CaptureError, match="missing_independent_readback"):
        sanitize_control_capture(har, _spec())


def test_behavioral_query_parameters_fail_closed() -> None:
    """Only numeric GET cache busters can be omitted from structural evidence."""
    har = _complete_har()
    har["log"]["entries"][3]["request"]["url"] = (
        f"{_ORIGIN}/{_READBACK_PATH}?client=private-id"
    )

    with pytest.raises(CaptureError, match="unsafe_readback_query"):
        sanitize_control_capture(har, _spec())


def test_target_post_query_fails_closed() -> None:
    """A hidden POST action query cannot be dropped from contract evidence."""
    har = _complete_har()
    har["log"]["entries"][2]["request"]["url"] = f"{_ORIGIN}/{_POST_PATH}?action=reset"

    with pytest.raises(CaptureError, match="target_post_query_rejected"):
        sanitize_control_capture(har, _spec())


def test_unrelated_same_origin_query_does_not_change_contract() -> None:
    """Noise from the same router origin is ignored after origin validation."""
    har = _complete_har()
    har["log"]["entries"].insert(
        1,
        _entry(
            "GET",
            "assets/ui.js?v=private-build-id",
            response_body="{}",
        ),
    )

    assert sanitize_control_capture(har, _spec())["proof"]["complete"] is True


def test_multiple_origins_fail_before_contract_extraction() -> None:
    """Unrelated browser traffic cannot enter one router evidence artifact."""
    har = _complete_har()
    har["log"]["entries"][1]["request"]["url"] = (
        "https://unrelated.example/data/LTE.json"
    )

    with pytest.raises(CaptureError, match="multiple_origins_rejected"):
        sanitize_control_capture(har, _spec())


def test_private_writer_uses_mode_0600_and_never_overwrites(tmp_path: Path) -> None:
    """Sanitized evidence is private and existing evidence is immutable."""
    output = tmp_path / "sanitized.json"

    _write_private_json(output, {"safe": True})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == {"safe": True}
    with pytest.raises(CaptureError, match="output_already_exists"):
        _write_private_json(output, {"safe": False})


def test_private_writer_refuses_symlink_target(tmp_path: Path) -> None:
    """A symlink cannot redirect sanitized output into an existing file."""
    target = tmp_path / "target.json"
    target.write_text("unchanged", encoding="utf-8")
    link = tmp_path / "capture.json"
    link.symlink_to(target)

    with pytest.raises(CaptureError, match="output_already_exists"):
        _write_private_json(link, {"safe": True})

    assert target.read_text(encoding="utf-8") == "unchanged"


def test_input_fixture_is_not_mutated() -> None:
    """Sanitization never rewrites or materializes a raw capture artifact."""
    har = _complete_har()
    before = deepcopy(har)

    sanitize_control_capture(har, _spec())

    assert har == before


@pytest.mark.parametrize(
    ("operation", "post_path", "state_field", "readback_field"),
    [
        ("reboot_router", "data/Reboot.json", "use_reboot", "use_reboot"),
        (
            "set_restart_router",
            "data/LTE.json",
            "use_bonding",
            "use_bonding",
        ),
        ("set_factory_reset", "data/Reset.json", "use_reset", "use_reset"),
        ("set_firmware_update", "data/Update.json", "use_update", "use_update"),
        ("set_router_password", "data/Password.json", "use_password", "enabled"),
        ("set_wifi_key", "data/WLAN.json", "wifi_key", "wifi_key"),
        ("set_client_mac", "data/DeviceList.json", "mdevice_mac", "mdevice_mac"),
        ("set_router_name", "data/Router.json", "router_name", "router_name"),
    ],
)
def test_high_risk_or_private_capture_selectors_fail_closed(
    operation: str,
    post_path: str,
    state_field: str,
    readback_field: str,
) -> None:
    """V1 cannot prepare destructive, credential, secret, or identity captures."""
    with pytest.raises(CaptureError, match="unsafe_capture_target"):
        CaptureSpec(
            operation=operation,
            post_path=post_path,
            state_field=state_field,
            state_values=("0", "1"),
            readback_path=post_path,
            readback_field=readback_field,
        )


def test_private_ack_selector_fails_closed() -> None:
    """A safe-looking ACK leaf cannot hide under a private selector path."""
    with pytest.raises(CaptureError, match="unsafe_capture_target"):
        CaptureSpec(
            operation="set_hybrid_bonding",
            post_path=_POST_PATH,
            state_field="use_bonding",
            state_values=("0", "1"),
            readback_path=_READBACK_PATH,
            readback_field="use_bonding",
            ack_field="password.status",
        )


def test_unreviewed_scalar_shape_fails_closed() -> None:
    """A benign-looking scalar is blocked until its exact field is reviewed."""
    with pytest.raises(CaptureError, match="unsafe_capture_target"):
        CaptureSpec(
            operation="set_unreviewed_feature",
            post_path="data/Unreviewed.json",
            state_field="feature_enabled",
            state_values=("0", "1"),
            readback_path="data/Unreviewed.json",
            readback_field="feature_enabled",
        )


@pytest.mark.parametrize(
    "field",
    [
        "use_bonding",
        "lan_privacy_policy",
        "ex5g_led_mode",
        "use_wlan",
        "wlan_guest_active",
        "wlan_office_active",
        "portuw_active",
        "mdevice_fix_dhcp",
    ],
)
def test_reviewed_reversible_scalar_field_shapes_are_allowed(field: str) -> None:
    """The safety gate retains intended bounded scalar evidence targets."""
    spec = CaptureSpec(
        operation="set_reviewed_scalar",
        post_path="data/ReviewedScalar.json",
        state_field=field,
        state_values=("0", "1"),
        readback_path="data/ReviewedScalar.json",
        readback_field=field,
    )

    assert spec.state_field == field


@pytest.mark.parametrize("field", ["wlan_active", "fix_dhcp"])
def test_readback_aliases_are_not_accepted_as_post_state_fields(field: str) -> None:
    """Only exact reviewed browser form fields can define a captured write."""
    with pytest.raises(CaptureError, match="unsafe_capture_target"):
        CaptureSpec(
            operation="set_reviewed_scalar",
            post_path="data/ReviewedScalar.json",
            state_field=field,
            state_values=("0", "1"),
            readback_path="data/ReviewedScalar.json",
            readback_field=field,
        )
