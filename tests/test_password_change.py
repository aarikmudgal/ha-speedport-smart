"""Pure password-change protocol and commit-proof tests; no router connections."""

# Scenario names document each parametrized proof.
# ruff: noqa: D103, S105

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.speedport_smart.admin_actions import (
    SPEEDPORT_SMART_4R_TYP_A_010152,
)
from custom_components.speedport_smart.password_change import (
    PASSWORD_CHANGE_CONFIRMATION,
    PASSWORD_CHANGE_ENDPOINT,
    PASSWORD_CHANGE_REFERER,
    PasswordChangeError,
    PasswordChangeIdentity,
    PasswordChangeRequest,
    classify_password_change_ack,
    password_change_identity,
    password_change_metadata,
)

OLD = "old-private-password"
NEW = "new-private-password"


def identity(identifier: str = "synthetic-router-id") -> PasswordChangeIdentity:
    target = SPEEDPORT_SMART_4R_TYP_A_010152
    return password_change_identity(
        model=target.model,
        firmware=target.firmware,
        router_identifier=identifier,
    )


def fields() -> dict[str, str]:
    return {"password": OLD, "new_password": NEW, "new_pw_repeat": NEW}


def request(changes: dict | None = None, **overrides: Any) -> PasswordChangeRequest:
    kwargs = {
        "identity": identity(),
        "confirmed": True,
        "confirmation_text": PASSWORD_CHANGE_CONFIRMATION,
        "recovery_ready": True,
    }
    kwargs.update(overrides)
    return PasswordChangeRequest(fields() if changes is None else changes, **kwargs)


def payload(draft: PasswordChangeRequest, **overrides: Any) -> dict[str, str]:
    kwargs = {
        "page_token": "123456",
        "current_identity": identity(),
        "router_state": "OK",
        "current_password_authenticated": True,
    }
    kwargs.update(overrides)
    return draft.take_payload(**kwargs)


def accepted_request() -> PasswordChangeRequest:
    draft = request()
    payload(draft).clear()
    assert (
        draft.record_acknowledgement({"status": "ok", "login": "success"}) == "accepted"
    )
    return draft


def proof(draft: PasswordChangeRequest, **overrides: Any) -> None:
    kwargs = {
        "response": {"login": "success"},
        "current_identity": identity(),
        "router_state": "OK",
        "old_session_released": True,
        "isolated_new_session": True,
        "fresh_challenge_requested": True,
        "new_challenge": "a1" * 16,
    }
    kwargs.update(overrides)
    draft.verify_new_login(**kwargs)


def test_exact_static_endpoint_empty_secret_fields_and_confirmation() -> None:
    assert PASSWORD_CHANGE_ENDPOINT == "data/Login.json"
    assert PASSWORD_CHANGE_REFERER == "html/content/config/change_password.html"
    metadata = password_change_metadata()
    assert metadata["execution_policy"] == "password_change"
    assert metadata["live_write_verified"] is False
    assert metadata["confirmation"] == PASSWORD_CHANGE_CONFIRMATION
    assert [
        (item["name"], item["kind"], item["minimum"], item["maximum"])
        for item in metadata["fields"]
    ] == [
        ("password", "secret", 1, 32),
        ("new_password", "secret", 8, 32),
        ("new_pw_repeat", "secret", 8, 32),
    ]
    assert all("value" not in item for item in metadata["fields"])
    assert "data/" not in repr(metadata)
    assert OLD not in repr(metadata)
    assert NEW not in repr(metadata)


@pytest.mark.parametrize(
    "overrides",
    [
        {"confirmed": False},
        {"confirmed": "true"},
        {"recovery_ready": False},
        {"recovery_ready": 1},
        {"confirmation_text": "CHANGE PASSWORD"},
    ],
)
def test_exact_typed_and_recovery_confirmation_required(overrides: dict) -> None:
    with pytest.raises(PasswordChangeError, match="confirmation_required"):
        request(**overrides)


@pytest.mark.parametrize(
    "changes", [{}, {"password": OLD}, {**fields(), "endpoint": "data/Other.json"}]
)
def test_exact_three_fields_no_generic_raw_input(changes: dict) -> None:
    with pytest.raises(PasswordChangeError):
        request(changes)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        123,
        [],
        "",
        "with space",
        "a\\b",
        "apostrophe'",
        "backtick`",
        "a\n",
        "a\x7f",
        "ä",
        "********",
        "[REDACTED]",
        "x" * 33,
    ],
)
def test_exact_alphabet_bounds_and_no_mask_replay(bad: object) -> None:
    with pytest.raises(PasswordChangeError):
        request({**fields(), "password": bad})


def test_new_password_minimum_exact_symbols_and_case_preserved() -> None:
    with pytest.raises(PasswordChangeError):
        request({**fields(), "new_password": "short12", "new_pw_repeat": "short12"})
    secret = '!"§$%&/()=*+#,;.:_-012aAZ'
    draft = request({"password": "a", "new_password": secret, "new_pw_repeat": secret})
    assert draft.current_password() == "a"
    assert payload(draft)["new_password"] == secret


def test_repeat_and_noop_check_do_not_coerce_credentials() -> None:
    with pytest.raises(PasswordChangeError, match="password_repeat_mismatch"):
        request({**fields(), "new_pw_repeat": NEW.upper()})
    with pytest.raises(PasswordChangeError, match="password_unchanged"):
        request({"password": NEW, "new_password": NEW, "new_pw_repeat": NEW})


def test_model_and_stable_identity_are_server_bound_and_private() -> None:
    target = SPEEDPORT_SMART_4R_TYP_A_010152
    assert "synthetic-router-id" not in repr(identity())
    for model, firmware, identifier in (
        ("Speedport Smart 4", target.firmware, "synthetic-private-id"),
        (target.model, "other", "synthetic-private-id"),
        (target.model, target.firmware, ""),
        (target.model, target.firmware, "private\nidentifier"),
    ):
        with pytest.raises(PasswordChangeError) as error:
            password_change_identity(
                model=model, firmware=firmware, router_identifier=identifier
            )
        assert identifier not in str(error.value) or not identifier


def test_plaintext_form_not_login_hash_and_payload_can_only_be_taken_once() -> None:
    changes = fields()
    draft = request(changes)
    changes["new_password"] = "changed-after-approval"
    assert draft.current_password() == OLD
    sent = payload(draft)
    assert sent == {
        "password": OLD,
        "new_password": NEW,
        "new_pw_repeat": NEW,
        "httoken": "123456",
    }
    assert OLD not in repr(draft)
    assert NEW not in repr(draft)
    assert not hasattr(draft, "__dict__")
    with pytest.raises(PasswordChangeError, match="stale_password_change"):
        payload(draft)
    with pytest.raises(PasswordChangeError):
        draft.current_password()
    sent.clear()


@pytest.mark.parametrize(
    "overrides",
    [
        {"page_token": None},
        {"page_token": ""},
        {"page_token": "12&token=3"},
        {"page_token": 123},
        {"current_identity": identity("replacement")},
        {"router_state": "MODEM"},
        {"current_password_authenticated": False},
        {"current_password_authenticated": 1},
    ],
)
def test_preflight_failure_produces_no_payload(overrides: dict) -> None:
    draft = request()
    with pytest.raises(PasswordChangeError, match="password_change_preflight_failed"):
        payload(draft, **overrides)
    assert draft.result(credential_persisted=False, cleanup_confirmed=True) == {
        "status": "not_started",
        "retry_safe": False,
    }


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"status": "ok", "login": "success"}, "accepted"),
        ({"status": "ok", "login": "success", "reason": "0"}, "accepted"),
        ({"status": "ok", "reason": "-1"}, "rejected"),
        ({"status": "ok", "reason": "-2"}, "rejected"),
        ({"status": "failed"}, "rejected"),
        ({"status": "ok", "login": "failed"}, "rejected"),
        ({"status": "ok", "login": "success", "reason": "-2"}, "outcome_unknown"),
        ({"status": "error", "login": "success"}, "outcome_unknown"),
        ({"status": "ok", "login": "success", "error": "bad"}, "outcome_unknown"),
        ({"status": "ok", "Login": "success"}, "outcome_unknown"),
        ({"status": "ok", "login": "success", "LOGIN": "failed"}, "outcome_unknown"),
        ({"status": ["ok", "ok"], "login": "success"}, "outcome_unknown"),
        ({"status": "ok", "login": ["success", "failed"]}, "outcome_unknown"),
        ({"status": "ok"}, "outcome_unknown"),
        ({"login": "success"}, "outcome_unknown"),
        ({}, "outcome_unknown"),
        (None, "outcome_unknown"),
    ],
)
def test_double_ack_exact_rejections_and_ambiguity(
    response: object, expected: str
) -> None:
    assert classify_password_change_ack(response) == expected


def test_ack_must_follow_payload_and_cannot_be_replaced() -> None:
    draft = request()
    with pytest.raises(PasswordChangeError):
        draft.record_acknowledgement({"status": "ok", "login": "success"})
    payload(draft).clear()
    draft.record_acknowledgement({})
    with pytest.raises(PasswordChangeError):
        draft.record_acknowledgement({"status": "ok", "login": "success"})


@pytest.mark.parametrize("response", [{}, {"status": "error"}, {"status": "ok"}])
def test_unknown_or_negative_ack_never_tries_new_password(response: dict) -> None:
    draft = request()
    payload(draft).clear()
    draft.record_acknowledgement(response)
    with pytest.raises(PasswordChangeError):
        draft.verification_password()
    with pytest.raises(PasswordChangeError):
        draft.credential_for_storage()
    assert draft.result(credential_persisted=False, cleanup_confirmed=True)[
        "status"
    ] in {
        "outcome_unknown",
        "rejected",
    }


def test_candidate_login_is_one_shot_and_storage_requires_its_proof() -> None:
    draft = accepted_request()
    with pytest.raises(PasswordChangeError):
        draft.credential_for_storage()
    with pytest.raises(PasswordChangeError):
        proof(draft)
    assert draft.verification_password() == NEW
    with pytest.raises(PasswordChangeError):
        draft.verification_password()
    proof(draft)
    assert draft.credential_for_storage() == NEW


@pytest.mark.parametrize(
    "overrides",
    [
        {"old_session_released": False},
        {"isolated_new_session": False},
        {"isolated_new_session": 1},
        {"fresh_challenge_requested": False},
        {"new_challenge": "invalid"},
        {"new_challenge": "a" * 31},
        {"current_identity": identity("replacement")},
        {"router_state": "UPDATE"},
        {"response": {"login": "ok"}},
        {"response": {"login": True}},
        {"response": {"login": "success", "status": "failed"}},
        {"response": {"login": "success", "Login": "failed"}},
        {"response": {"login": "success", "reason": "-1"}},
        {"response": {"login": "success", "login_locked": "10"}},
        {"response": {"login": "success", "login_other": "private-owner"}},
    ],
)
def test_new_login_proof_rejects_session_reuse_stale_identity_or_ambiguity(
    overrides: dict,
) -> None:
    draft = accepted_request()
    draft.verification_password()
    with pytest.raises(
        PasswordChangeError, match="password_verification_failed"
    ) as error:
        proof(draft, **deepcopy(overrides))
    assert "private-owner" not in str(error.value)
    with pytest.raises(PasswordChangeError):
        draft.credential_for_storage()


def test_new_login_challenge_need_not_have_invented_uniqueness_property() -> None:
    draft = accepted_request()
    draft.verification_password()
    proof(draft, new_challenge="a1" * 16)
    # Only a freshly requested challenge and isolated authentication exchange are
    # required. Firmware does not promise a distinct value for every session.
    assert draft.credential_for_storage() == NEW


def test_result_separates_verified_credential_persistence_and_cleanup() -> None:
    draft = accepted_request()
    assert draft.result(credential_persisted=False, cleanup_confirmed=True) == {
        "status": "outcome_unknown",
        "verification": "reauthentication_required",
        "acknowledged": True,
        "retry_safe": False,
    }
    draft.verification_password()
    proof(draft)
    assert (
        draft.result(credential_persisted=False, cleanup_confirmed=True)["verification"]
        == "credential_update_required"
    )
    partial = draft.result(credential_persisted=True, cleanup_confirmed=False)
    assert partial == {
        "status": "outcome_unknown",
        "verification": "session_cleanup_failed",
        "credential_updated": True,
        "retry_safe": False,
    }
    final = draft.result(credential_persisted=True, cleanup_confirmed=True)
    assert final == {
        "status": "verified",
        "verification": "new_credential",
        "credential_updated": True,
        "retry_safe": False,
    }
    assert OLD not in repr(final)
    assert NEW not in repr(final)


def test_cannot_claim_persisted_credential_before_verification() -> None:
    draft = accepted_request()
    with pytest.raises(PasswordChangeError):
        draft.result(credential_persisted=True, cleanup_confirmed=True)


def test_clear_releases_references_and_invalidates_all_private_operations() -> None:
    draft = accepted_request()
    draft.verification_password()
    proof(draft)
    draft.clear()
    assert draft._old is None  # noqa: SLF001 -- Prove private references were released.
    assert draft._new is None  # noqa: SLF001
    for callback in (
        draft.current_password,
        draft.verification_password,
        draft.credential_for_storage,
        lambda: payload(draft),
        lambda: draft.record_acknowledgement({}),
        lambda: draft.result(credential_persisted=True, cleanup_confirmed=True),
    ):
        with pytest.raises(PasswordChangeError, match="stale_password_change"):
            callback()
    draft.clear()
    assert repr(draft) == "<PasswordChangeRequest private>"
