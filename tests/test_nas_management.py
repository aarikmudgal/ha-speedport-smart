"""Pure NAS edit contracts preserve state and never recycle masked secrets."""

# ruff: noqa: S105, S106 - deliberately synthetic test credentials

from __future__ import annotations

import pytest

from custom_components.speedport_smart.nas_management import (
    NAS_SHARE_SUCCESS_ACK_PROVEN,
    NasShareContractError,
    NasShareEdit,
    NasShareLimits,
    NasShareReadback,
    build_nas_share_write,
    compare_nas_share_readback,
    nas_share_fingerprint,
)

# Test-only bounds; production callers must obtain their firmware's exact HTML.
LIMITS = NasShareLimits(128, 3, 32, 8, 64)


@pytest.fixture
def nas_row() -> dict[str, object]:
    """Return an exact wire row containing a password that must be ignored."""
    return {
        "sid": "share_1",
        "nas_active": "1",
        "nas_folder_name": "/Drive/Media",
        "nas_folder_nur_lesen": "0",
        "nas_secure": "0",
        "nas_user_name": "media-user",
        "nas_user_pwd": "DO-NOT-REUSE-ROUTER-SECRET",
    }


def test_preserve_and_single_use(nas_row: dict[str, object]) -> None:
    """Changing one flag preserves all other submitted state exactly."""
    write = build_nas_share_write(
        nas_row,
        expected_share_id="share_1",
        expected_fingerprint=nas_share_fingerprint(nas_row),
        edit=NasShareEdit(read_only=True),
        limits=LIMITS,
    )
    assert write.consume_payload() == {
        "sid": "share_1",
        "nas_active": 1,
        "nas_folder_name": "/Drive/Media",
        "nas_folder_nur_lesen": 1,
        "nas_secure": 0,
    }
    with pytest.raises(NasShareContractError, match="already consumed"):
        write.consume_payload()
    assert "SECRET" not in repr(write)
    assert compare_nas_share_readback(write, nas_row) is NasShareReadback.MISMATCH
    assert (
        compare_nas_share_readback(write, {**nas_row, "nas_folder_nur_lesen": "1"})
        is NasShareReadback.VERIFIED
    )


def test_disable_minimal_payload(nas_row: dict[str, object]) -> None:
    """Disabling does not require or transmit credentials or form bounds."""
    nas_row["nas_secure"] = "1"
    write = build_nas_share_write(
        nas_row,
        expected_share_id="share_1",
        expected_fingerprint=nas_share_fingerprint(nas_row),
        edit=NasShareEdit(enabled=False),
    )
    assert write.consume_payload() == {"sid": "share_1", "nas_active": 0}
    assert (
        compare_nas_share_readback(write, {"sid": "share_1", "nas_active": "0"})
        is NasShareReadback.VERIFIED
    )


def test_explicit_secret_not_cached_or_verified(nas_row: dict[str, object]) -> None:
    """Only a newly supplied credential reaches the one-shot payload."""
    edit = NasShareEdit(secure=True, password="Fresh-Password-1")
    write = build_nas_share_write(
        nas_row,
        expected_share_id="share_1",
        expected_fingerprint=nas_share_fingerprint(nas_row),
        edit=edit,
        limits=LIMITS,
    )
    assert "Fresh-Password-1" not in repr(edit)
    assert "Fresh-Password-1" not in repr(write)
    assert "nas_user_pwd" not in write.expected
    assert write.consume_payload()["nas_user_pwd"] == "Fresh-Password-1"
    assert (
        compare_nas_share_readback(write, {**nas_row, "nas_secure": "1"})
        is NasShareReadback.SECRET_UNVERIFIED
    )


@pytest.mark.parametrize("password", [None, "", "********", "[REDACTED]", "••••••••"])
def test_never_reuse_missing_or_masked_secret(
    nas_row: dict[str, object], password: str | None
) -> None:
    """Existing plaintext or masked router credentials are never forwarded."""
    nas_row["nas_secure"] = "1"
    with pytest.raises(NasShareContractError) as raised:
        build_nas_share_write(
            nas_row,
            expected_share_id="share_1",
            expected_fingerprint=nas_share_fingerprint(nas_row),
            edit=NasShareEdit(read_only=True, password=password),
            limits=LIMITS,
        )
    assert "DO-NOT-REUSE" not in str(raised.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"sid": "other"},
        {"nas_secure": "1"},
        {"nas_folder_name": "/Other"},
        {"nas_user_name": "other-user"},
    ],
)
def test_stale_target_fails(
    nas_row: dict[str, object], changes: dict[str, object]
) -> None:
    """Selection is invalidated by any preserved non-secret state change."""
    fingerprint = nas_share_fingerprint(nas_row)
    with pytest.raises(NasShareContractError, match="target changed"):
        build_nas_share_write(
            {**nas_row, **changes},
            expected_share_id="share_1",
            expected_fingerprint=fingerprint,
            edit=NasShareEdit(enabled=False),
        )


@pytest.mark.parametrize("sid", ["-1", "", None, True, " ../share", "x\n"])
def test_unsafe_or_new_identity_rejected(
    nas_row: dict[str, object], sid: object
) -> None:
    """Do not create shares or guess missing row identities."""
    with pytest.raises(NasShareContractError, match="identity"):
        nas_share_fingerprint({**nas_row, "sid": sid})


def test_conflicting_identity_and_unknown_flags(nas_row: dict[str, object]) -> None:
    """Ambiguous input cannot create a valid target fingerprint."""
    with pytest.raises(NasShareContractError, match="identities disagree"):
        nas_share_fingerprint({**nas_row, "id": "other"})
    with pytest.raises(NasShareContractError, match="incomplete"):
        nas_share_fingerprint({**nas_row, "nas_active": "maybe"})


@pytest.mark.parametrize(
    "edit",
    [
        NasShareEdit(),
        NasShareEdit(enabled=False, read_only=True),
        NasShareEdit(secure=False, password="Fresh-Password-1"),
        NasShareEdit(folder_name="\nPRIVATE"),
        NasShareEdit(secure=True, username="bad username", password="Fresh-Password-1"),
        NasShareEdit(secure=True, password="short"),
        NasShareEdit(secure=True, password="Fresh[Password]1"),
    ],
)
def test_inapplicable_or_invalid_edits_rejected(
    nas_row: dict[str, object], edit: NasShareEdit
) -> None:
    """Do not silently drop requested fields or weaken firmware validation."""
    with pytest.raises(NasShareContractError):
        build_nas_share_write(
            nas_row,
            expected_share_id="share_1",
            expected_fingerprint=nas_share_fingerprint(nas_row),
            edit=edit,
            limits=LIMITS,
        )


def test_missing_bounds_and_readback(nas_row: dict[str, object]) -> None:
    """Do not guess limits or interpret unavailable readbacks as success."""
    with pytest.raises(NasShareContractError, match="bounds"):
        build_nas_share_write(
            nas_row,
            expected_share_id="share_1",
            expected_fingerprint=nas_share_fingerprint(nas_row),
            edit=NasShareEdit(read_only=True),
        )
    write = build_nas_share_write(
        nas_row,
        expected_share_id="share_1",
        expected_fingerprint=nas_share_fingerprint(nas_row),
        edit=NasShareEdit(enabled=False),
    )
    assert compare_nas_share_readback(write, None) is NasShareReadback.UNAVAILABLE
    assert compare_nas_share_readback(write, {}) is NasShareReadback.UNAVAILABLE
    assert (
        compare_nas_share_readback(write, {"sid": "other", "nas_active": 0})
        is NasShareReadback.MISMATCH
    )
    write.discard()
    with pytest.raises(NasShareContractError, match="already consumed"):
        write.consume_payload()
    assert NAS_SHARE_SUCCESS_ACK_PROVEN is False


def test_password_does_not_change_fingerprint(nas_row: dict[str, object]) -> None:
    """Secret material never enters target identity hashes."""
    assert nas_share_fingerprint(nas_row) == nas_share_fingerprint(
        {**nas_row, "nas_user_pwd": "********"}
    )


@pytest.mark.parametrize(("minimum", "maximum"), [(0, 10), (10, 9), (True, 10)])
def test_invalid_limits_rejected(minimum: int, maximum: int) -> None:
    """Bounds are explicit positive integers with ordered endpoints."""
    with pytest.raises(NasShareContractError, match="bounds"):
        NasShareLimits(128, minimum, maximum, 8, 64)
