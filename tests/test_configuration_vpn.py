"""Offline exact VPN toggle/deletion tests; credentials never leave local fixtures."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.configuration_targets import (
    resolve_settings_contract,
)
from custom_components.speedport_smart.configuration_vpn import (
    VPN_SETTINGS,
    extract_vpn_credentials,
    extract_vpn_rotated_credentials,
    vpn_target_contract,
    vpn_target_metadata,
    vpn_target_rows,
)

_ENABLE = vpn_target_contract("vpn_peer_enabled", "7")
_DELETE = vpn_target_contract("vpn_peer_delete", "7")
_OWNER = ("synthetic-admin", "synthetic-session")
_CREATE = VPN_SETTINGS[0]
_ROTATE = VPN_SETTINGS[1]
_PASSWORD = "SyntheticPassword123!"  # noqa: S105
_WG_CONTENT = (
    "[Interface]\nPrivateKey = synthetic-private-key\nAddress = 192.0.2.5/32\n"
    "DNS = 192.0.2.1\n[Peer]\nPublicKey = synthetic-public-key\n"
    "AllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = vpn.example.invalid:51820\n"
    "PersistentKeepalive = 25\n"
)


def _raw(mode: str = "0") -> dict[str, Any]:
    return {
        "vpn_typ": mode,
        "vpn_key": "synthetic-global-key",
        "vpn_connectivity": {"onlinestatus": "online"},
        "addvpn": [
            {
                "id": identifier,
                "vpn_name": name,
                "vpn_status": "1",
                "vpn_userip": "192.0.2.1",
                **(
                    {
                        "vpn_username": f"synthetic-user-{identifier}",
                        "vpn_password": "Synthetic-Password-123",
                        "vpn_ipsec_qrcode": "synthetic-qr-data",
                    }
                    if mode == "1"
                    else {}
                ),
            }
            for identifier, name in (("2", "First peer"), ("7", "Second peer"))
        ],
        "online_counter": "10",
    }


def _create_changes(mode: str = "0") -> dict[str, Any]:
    return {
        "vpn_name": "New peer",
        **({"vpn_password": _PASSWORD} if mode == "1" else {}),
    }


def _created(mode: str = "0") -> dict[str, Any]:
    raw = _raw(mode)
    raw["addvpn"].append(
        {
            "id": "15",
            "vpn_name": "New peer",
            "vpn_status": "1",
            "vpn_userip": "",
            **(
                {"vpn_username": "new-user", "vpn_password": _PASSWORD}
                if mode == "1"
                else {}
            ),
        }
    )
    return raw


@pytest.mark.parametrize("mode", ["0", "1"])
def test_exact_minimal_native_toggle_and_delete_payloads(mode: str) -> None:
    """No name, secret, mode or connection-state value belongs in these POSTs."""
    raw = _raw(mode)
    before = deepcopy(raw)
    assert _ENABLE.build(raw, {"vpn_status": False}) == {
        "id": "7",
        "switchStatus": True,
        "vpn_status": 0,
    }
    assert _ENABLE.build(raw, {"vpn_status": True})["vpn_status"] == 1
    assert _DELETE.build(raw, {"delete_entry": True}) == {
        "id": "7",
        "deleteEntry": "delete",
    }
    assert raw == before
    assert _ENABLE.endpoint == "data/VPN.json"
    assert _ENABLE.referer == "html/content/network/vpn.html"
    assert _ENABLE.acknowledgement == "status_ok"


def test_empty_native_shape_singleton_and_secret_free_public_metadata() -> None:
    """Actual empty mode-0 response offers no fabricated peer."""
    assert vpn_target_rows("vpn_peer_enabled", {"vpn_typ": "0", "vpn_key": ""}) == ()
    raw = _raw("1")
    raw["addvpn"] = raw["addvpn"][1]
    assert _ENABLE.read(raw) == {"vpn_status": True}
    assert vpn_target_rows("vpn_peer_enabled", raw) == (
        {"id": "7", "vpn_name": "Second peer"},
    )
    public = str(_ENABLE.read(raw)) + str(vpn_target_metadata())
    assert "Synthetic-Password" not in public
    assert "synthetic-global-key" not in public
    assert "192.0.2.1" not in public


@pytest.mark.parametrize(
    "changes",
    [
        {"vpn_status": "0"},
        {"vpn_status": 0},
        {"vpn_status": None},
        {"vpn_status": True, "id": "2"},
        {"vpn_name": "Rename"},
        {"vpn_typ": "1"},
        {"vpn_password": "SyntheticPassword123"},
        {"renewvpn": "true"},
        {"deleteEntry": "delete"},
        {"switchStatus": True},
        {"endpoint": "data/Other.json"},
        {},
    ],
)
def test_untyped_inputs_unsupported_mutations_and_wire_injection_rejected(
    changes: dict[str, object],
) -> None:
    """Only a typed boolean for this exact peer crosses the command boundary."""
    with pytest.raises(ConfigurationError):
        _ENABLE.build(_raw(), changes)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_mode",
        "unknown_mode",
        "missing_key",
        "duplicate_id",
        "missing_name",
        "invalid_name",
        "missing_flag",
        "unknown_flag",
        "bad_secret",
        "too_many",
    ],
)
def test_ambiguous_current_state_fails_closed(mutation: str) -> None:
    """Neither missing identity nor malformed current mode or credentials is guessed."""
    raw = _raw("1")
    row = raw["addvpn"][1]
    if mutation == "missing_mode":
        raw.pop("vpn_typ")
    elif mutation == "unknown_mode":
        raw["vpn_typ"] = "2"
    elif mutation == "missing_key":
        raw.pop("vpn_key")
    elif mutation == "duplicate_id":
        row["id"] = "2"
    elif mutation == "missing_name":
        row.pop("vpn_name")
    elif mutation == "invalid_name":
        row["vpn_name"] = "<bad>"
    elif mutation == "missing_flag":
        row.pop("vpn_status")
    elif mutation == "unknown_flag":
        row["vpn_status"] = "2"
    elif mutation == "bad_secret":
        row["vpn_password"] = {"unexpected": "mapping"}
    else:
        raw["addvpn"] = [{**row, "id": str(index)} for index in range(6)]
    with pytest.raises(ConfigurationError):
        _ENABLE.read(raw)


def test_revision_ignores_connection_telemetry_and_binds_credentials_privately() -> (
    None
):
    """Connection IP changes are expected; peer/key replacement invalidates grants."""
    before, changed = _raw("1"), _raw("1")
    changed["addvpn"][1]["vpn_userip"] = ""
    changed["online_counter"] = "11"
    assert _ENABLE.revision(before) == _ENABLE.revision(changed)
    changed["addvpn"][1]["vpn_password"] = "OtherSyntheticPassword123"  # noqa: S105
    assert _ENABLE.revision(before) != _ENABLE.revision(changed)
    changed = _raw("1")
    changed["vpn_key"] = "different-global-key"
    assert _ENABLE.revision(before) != _ENABLE.revision(changed)


@pytest.mark.parametrize("action", ["disable", "delete"])
@pytest.mark.parametrize("mode", ["0", "1"])
async def test_one_shot_session_requires_exact_whole_collection_readback(
    action: str, mode: str
) -> None:
    """Positive command completion is followed by independent exact state proof."""
    contract = _DELETE if action == "delete" else _ENABLE
    changes = {"delete_entry": True} if action == "delete" else {"vpn_status": False}
    before, after = _raw(mode), _raw(mode)
    if action == "delete":
        after["addvpn"].pop()
    else:
        after["addvpn"][1]["vpn_status"] = "0"
        after["addvpn"][1]["vpn_userip"] = ""
    assert contract.verifier is not None
    assert contract.verifier(before, changes, after)
    assert not contract.verifier(before, changes, before)
    collateral = deepcopy(after)
    collateral["addvpn"][0]["vpn_status"] = "0"
    assert not contract.verifier(before, changes, collateral)
    rotated = deepcopy(after)
    rotated["vpn_key"] = "unexpected-key-rotation"
    assert not contract.verifier(before, changes, rotated)
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(contract, _OWNER, read)
    assert "synthetic-global-key" not in str(initial)
    assert await session.save(
        contract,
        _OWNER,
        initial["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    ) == {"status": "verified"}
    write.assert_awaited_once()


async def test_absent_target_and_failed_readback_never_replay_write() -> None:
    """Missing target is not deletion authority; a POST echo is not persistence."""
    empty = {"vpn_typ": "0", "vpn_key": ""}
    with pytest.raises(ConfigurationError, match="stale_settings"):
        _DELETE.build(empty, {"delete_entry": True})
    read, write = (
        AsyncMock(return_value=_raw()),
        AsyncMock(return_value={"status": "ok"}),
    )
    session = ConfigurationSession()
    initial = await session.read(_ENABLE, _OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            _ENABLE,
            _OWNER,
            initial["revision"],
            {"vpn_status": False},
            confirmed=True,
            confirmation_text=_ENABLE.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


@pytest.mark.parametrize("mode", ["0", "1"])
def test_create_exact_checked_default_and_mode_specific_password(mode: str) -> None:
    """New peer is checked in native HTML; hidden WireGuard password is omitted."""
    assert _CREATE.read(_raw(mode)) == {"vpn_name": ""}
    assert _CREATE.build(_raw(mode), _create_changes(mode)) == {
        "id": "-1",
        "vpn_name": "New peer",
        "vpn_status": "1",
        **({"vpn_password": _PASSWORD} if mode == "1" else {}),
    }
    assert _CREATE.verifier is not None
    assert _CREATE.verifier(_raw(mode), _create_changes(mode), _created(mode))
    assert not _CREATE.verifier(_raw(mode), _create_changes(mode), _raw(mode))
    assert _PASSWORD not in str(_CREATE.read(_raw(mode))) + str(_CREATE.metadata())
    assert "not stored" in _CREATE.warning


@pytest.mark.parametrize(
    "password",
    [
        "shortA1!",
        "x" * 33,
        "abcdefghijklmnop",
        "abcdefghijkl1234",
        "Abcdefghijkl 12",
        "Abcdefghijkl@12",
        "Abcdefghijkl😀12",
        "************",
        123456789012,
        None,
    ],
)
def test_ipsec_password_exact_length_character_set_and_three_classes(
    password: object,
) -> None:
    """Strength failures cannot be satisfied by masked values or coercion."""
    with pytest.raises(ConfigurationError):
        _CREATE.build(_raw("1"), {"vpn_name": "New peer", "vpn_password": password})


@pytest.mark.parametrize(
    "context",
    [
        {"onlinestatus": "online"},
        {"auto_external_modem": "1", "extwan_typ": "2", "extwan_status": "1"},
        {"auto_external_modem": "1", "extwan_typ": "3", "lte_status": "10"},
        {"auto_external_modem": "1", "extwan_typ": "3", "lte_status": "11"},
    ],
)
def test_fresh_native_online_branches_allow_create(context: dict[str, str]) -> None:
    """The builder uses fresh global context without making it a staleness counter."""
    raw = _raw()
    raw["vpn_connectivity"] = context
    assert _CREATE.build(raw, _create_changes())["id"] == "-1"


@pytest.mark.parametrize(
    "mutation",
    ["missing_context", "offline", "tethering", "wrong_mode_password", "limit"],
)
def test_missing_prerequisites_and_unreviewed_branch_changes_block_create(
    mutation: str,
) -> None:
    """Unknown connectivity, capacity and inactive password fields are not guessed."""
    raw, changes = _raw(), _create_changes()
    if mutation == "missing_context":
        raw.pop("vpn_connectivity")
    elif mutation == "offline":
        raw["vpn_connectivity"] = {"onlinestatus": "offline"}
    elif mutation == "tethering":
        raw["vpn_connectivity"] = {
            "onlinestatus": "offline",
            "use_tethering": "1",
            "tethering_status": "2",
        }
    elif mutation == "wrong_mode_password":
        changes["vpn_password"] = _PASSWORD
    else:
        raw["addvpn"] = [{**raw["addvpn"][0], "id": str(index)} for index in range(5)]
    with pytest.raises(ConfigurationError):
        _CREATE.build(raw, changes)


@pytest.mark.parametrize("escaped", [False, True])
def test_wireguard_credentials_are_inert_one_time_data_bound_to_newest_id(
    *,
    escaped: bool,
) -> None:
    """Decode only data escapes and never evaluate the router's JavaScript string."""
    content = _WG_CONTENT.replace("\n", "\\n") if escaped else _WG_CONTENT
    response = {"newestID": "15", "vpn_qrcode": content}
    before, after = _raw(), _created()
    snapshots = deepcopy((before, after, response))
    credentials = extract_vpn_credentials(before, _create_changes(), response, after)
    assert credentials.peer_id == "15"
    assert credentials.mode == "0"
    assert credentials.filename == "Wireguard.conf"
    assert credentials.content == _WG_CONTENT
    assert "synthetic-private-key" not in repr(credentials)
    assert (before, after, response) == snapshots


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not a configuration",
        '[Interface]\\n";globalThis.pwned=true;//',
        _WG_CONTENT + "PostUp = echo unsafe\n",
        _WG_CONTENT + "[Peer]\nPublicKey = second-peer\n",
        _WG_CONTENT + "PublicKey = duplicate\n",
        _WG_CONTENT.replace("Endpoint = vpn.example.invalid:51820\n", ""),
        _WG_CONTENT + "\x00",
    ],
)
def test_malformed_config_and_executable_hooks_rejected(content: str) -> None:
    """Unknown fields and scripts are not promoted into a usable client download."""
    with pytest.raises(ConfigurationError):
        extract_vpn_credentials(
            _raw(),
            _create_changes(),
            {"newestID": "15", "vpn_qrcode": content},
            _created(),
        )


def test_credentials_require_exact_created_row_response_and_preserved_siblings() -> (
    None
):
    """Neither an ACK, existing peer nor unrelated newestID can release a secret."""
    for response in (
        {"status": "ok", "vpn_qrcode": _WG_CONTENT},
        {"newestID": "7", "vpn_qrcode": _WG_CONTENT},
        {"newestID": "16", "vpn_qrcode": _WG_CONTENT},
    ):
        with pytest.raises(ConfigurationError):
            extract_vpn_credentials(_raw(), _create_changes(), response, _created())
    altered = _created()
    altered["addvpn"][0]["vpn_status"] = "0"
    with pytest.raises(ConfigurationError):
        extract_vpn_credentials(
            _raw(),
            _create_changes(),
            {"newestID": "15", "vpn_qrcode": _WG_CONTENT},
            altered,
        )


def test_ipsec_secret_download_uses_verified_fields_without_revealing_repr() -> None:
    """IPsec handoff is a bounded JSON document, not a guessed import file."""
    credentials = extract_vpn_credentials(
        _raw("1"), _create_changes("1"), {"newestID": "15"}, _created("1")
    )
    assert credentials.filename == "Speedport-IPsec.json"
    assert credentials.media_type == "application/json"
    assert _PASSWORD in credentials.content
    assert _PASSWORD not in repr(credentials)


@pytest.mark.parametrize("mode", ["0", "1"])
async def test_create_session_one_post_then_independent_verified_new_peer(
    mode: str,
) -> None:
    """Response secrets are neither published by reads nor accepted as state proof."""
    before, after = _raw(mode), _created(mode)
    read = AsyncMock(side_effect=[before, before, after])
    write = AsyncMock(return_value={"newestID": "15", "vpn_qrcode": _WG_CONTENT})
    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    result = await session.save(
        _CREATE,
        _OWNER,
        initial["revision"],
        _create_changes(mode),
        confirmed=True,
        confirmation_text=_CREATE.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "secret_unverified" if mode == "1" else "verified"}
    write.assert_awaited_once()
    assert "synthetic-private-key" not in str(initial) + str(result)


def test_ipsec_rotation_exact_payload_and_independent_global_key_proof() -> None:
    """Rotate the proven global key only; derived QR changes are expected."""
    before, after = _raw("1"), _raw("1")
    after["vpn_key"] = "new-synthetic-global-key"
    for row in after["addvpn"]:
        row["vpn_ipsec_qrcode"] = "updated-synthetic-qr"
    assert _ROTATE.read(before) == {"rotate_key": False}
    assert _ROTATE.build(before, {"rotate_key": True}) == {"renewvpn": "true"}
    assert _ROTATE.verifier is not None
    assert _ROTATE.verifier(before, {"rotate_key": True}, after)
    assert not _ROTATE.verifier(before, {"rotate_key": True}, before)
    credentials = extract_vpn_rotated_credentials(
        before, {"rotate_key": True}, {"vpn_key": after["vpn_key"]}, after
    )
    assert credentials.peer_id == "all"
    assert credentials.mode == "1"
    assert credentials.filename == "Speedport-IPsec-peers.json"
    assert "new-synthetic-global-key" in credentials.content
    assert "new-synthetic-global-key" not in repr(credentials)


@pytest.mark.parametrize(
    "mutation",
    ["wireguard", "empty", "masked_key", "missing_login", "same_key", "peer_change"],
)
def test_rotation_unavailable_or_unverified_state_rejected(mutation: str) -> None:
    """Never rotate WireGuard, trust masked key evidence or overlook peer changes."""
    before, after = _raw("1"), _raw("1")
    after["vpn_key"] = "new-synthetic-global-key"
    if mutation == "wireguard":
        before["vpn_typ"] = "0"
    elif mutation == "empty":
        before.pop("addvpn")
    elif mutation == "masked_key":
        after["vpn_key"] = "********"
    elif mutation == "missing_login":
        after["addvpn"][0].pop("vpn_username")
    elif mutation == "same_key":
        after["vpn_key"] = before["vpn_key"]
    else:
        after["addvpn"][0]["vpn_status"] = "0"
    assert _ROTATE.verifier is not None
    assert not _ROTATE.verifier(before, {"rotate_key": True}, after)
    with pytest.raises(ConfigurationError):
        extract_vpn_rotated_credentials(
            before, {"rotate_key": True}, {"vpn_key": after["vpn_key"]}, after
        )


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_key_rotation_requires_typed_explicit_true(value: object) -> None:
    """A raw truthy value cannot authorize the all-client credential change."""
    with pytest.raises(ConfigurationError):
        _ROTATE.build(_raw("1"), {"rotate_key": value})


async def test_rotation_real_session_delivers_no_secret_without_opt_in_callback() -> (
    None
):
    """One global mutation, independent readback; default result contains no key."""
    before, after = _raw("1"), _raw("1")
    after["vpn_key"] = "new-synthetic-global-key"
    read = AsyncMock(side_effect=[before, before, after])
    write = AsyncMock(return_value={"vpn_key": after["vpn_key"]})
    session = ConfigurationSession()
    initial = await session.read(_ROTATE, _OWNER, read)
    result = await session.save(
        _ROTATE,
        _OWNER,
        initial["revision"],
        {"rotate_key": True},
        confirmed=True,
        confirmation_text=_ROTATE.confirmation,
        read=read,
        write=write,
    )
    assert result == {"status": "verified"}
    assert "synthetic-global-key" not in str(initial) + str(result)
    write.assert_awaited_once()


async def test_secret_callback_runs_once_only_after_independent_creation_readback() -> (
    None
):
    """Hold response secrets locally across GET retries; do not replay creation."""
    before, after = _raw(), _created()
    read = AsyncMock(side_effect=[before, before, before, after])
    response = {"newestID": "15", "vpn_qrcode": _WG_CONTENT}
    write = AsyncMock(return_value=response)
    callbacks: list[str] = []

    def verified(
        current: dict[str, Any],
        changes: dict[str, Any],
        reply: dict[str, Any],
        observed: dict[str, Any],
    ) -> dict[str, Any]:
        credentials = extract_vpn_credentials(current, changes, reply, observed)
        callbacks.append(credentials.peer_id)
        return {"status": "verified", "download": {"content": credentials.content}}

    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with patch(
        "custom_components.speedport_smart.configuration_session.asyncio.sleep",
        new=AsyncMock(),
    ):
        result = await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            _create_changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
            on_verified=verified,
        )
    assert callbacks == ["15"]
    assert result["download"]["content"] == _WG_CONTENT
    write.assert_awaited_once()
    assert read.await_count == 4
    assert "synthetic-private-key" not in str(initial)


async def test_lost_one_time_credentials_fail_without_a_second_creation() -> None:
    """A persisted peer with missing response credentials cannot be retried blindly."""
    before, after = _raw(), _created()
    read = AsyncMock(side_effect=[before, before, after])
    write = AsyncMock(return_value={"newestID": "15"})

    def verified(
        current: dict[str, Any],
        changes: dict[str, Any],
        reply: dict[str, Any],
        observed: dict[str, Any],
    ) -> dict[str, Any]:
        extract_vpn_credentials(current, changes, reply, observed)
        return {"status": "verified"}

    session = ConfigurationSession()
    initial = await session.read(_CREATE, _OWNER, read)
    with pytest.raises(ConfigurationError):
        await session.save(
            _CREATE,
            _OWNER,
            initial["revision"],
            _create_changes(),
            confirmed=True,
            confirmation_text=_CREATE.confirmation,
            read=read,
            write=write,
            on_verified=verified,
        )
    write.assert_awaited_once()


async def test_identical_peer_state_cannot_transfer_grant_to_another_target() -> None:
    """Equal values and inventory do not confer another peer's authority."""
    first = resolve_settings_contract("vpn_peer_enabled", "2")
    second = resolve_settings_contract("vpn_peer_enabled", "7")
    before, after = _raw(), _raw()
    after["addvpn"][1]["vpn_status"] = "0"
    read, write = AsyncMock(side_effect=[before, before, after]), AsyncMock()
    session = ConfigurationSession()
    initial = await session.read(first, _OWNER, read)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            second,
            _OWNER,
            initial["revision"],
            {"vpn_status": False},
            confirmed=True,
            confirmation_text=second.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()
