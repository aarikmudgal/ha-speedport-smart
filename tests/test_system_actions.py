"""Static-protocol fixtures for one-shot system requests; no router calls."""

# Scenario names document each parametrized proof.
# ruff: noqa: D103

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_configuration_mesh import mesh_node, mesh_raw

from custom_components.speedport_smart.api import SpeedportClient
from custom_components.speedport_smart.api.exceptions import (
    SpeedportCommandRejectedError,
    SpeedportMutationOutcomeUnknownError,
)
from custom_components.speedport_smart.configuration import ConfigurationError
from custom_components.speedport_smart.configuration_session import ConfigurationSession
from custom_components.speedport_smart.system_actions import (
    SYSTEM_ACTION_SETTINGS,
    merge_system_action_offer,
    system_action_extra_read,
    validate_smarthome_response,
)

CONTRACTS = {contract.id: contract for contract in SYSTEM_ACTION_SETTINGS}
OWNER = ("admin", "refresh-token")
ROUTER = "system_router_firmware_online"
MESH = "system_mesh_firmware_online"
ACTIVATE = "network_smarthome_activate"
DEACTIVATE = "network_smarthome_deactivate"
RECEIVER = "internet_receiver_firmware_update"
RESET = "internet_receiver_factory_esim_restore"


def router_base() -> dict:
    return {
        "router_state": "OK",
        "onlinestatus": "online",
        "inet_isp": "0",
        "autofw_deactive": "0",
        "firmware_version": "1.0",
        "extwan_typ": "1",
        "lte_status": "0",
        "use_tethering": "0",
        "tethering_status": "0",
    }


def router_offer() -> dict:
    return {
        "status": "ok",
        "fwupd_avail": "1",
        "fwupd_version": "2.0",
        "newFwImageURL": "https://firmware.example.test/private-offer.bin",
        "newFwDigest": "synthetic-private-digest",
    }


def mesh_base() -> dict:
    return {**router_base(), **mesh_raw(mesh_node())}


def mesh_offer(base: dict) -> dict:
    return {"status": "ok", "addmeshdevice": deepcopy(base["addmeshdevice"])}


def smart_home(*, active: str = "0", state: str = "0") -> dict:
    return {
        **router_base(),
        "use_smarthome": active,
        "smarthome_state_check": state,
        "acode_locked": "0",
        "acode_2": "9999",
        "acode_3": "8888",
        "acode_4": "7777",
    }


def receiver() -> dict:
    return {
        **router_base(),
        "auto_external_modem": "1",
        "extwan_typ": "3",
        "ex5g_model_name": "Synthetic receiver",
        "ex5g_serial_number": "private-serial",
        "ex5g_eid": "private-eid",
        "ex5g_fw_version": "1.0",
        "ex5g_fwupd_avail": "1",
        "ex5g_fwupd_version": "2.0",
    }


def approvals() -> dict:
    return {"execute": True, "physical_access": True}


def test_eight_action_contracts_not_synthetic_state_controls() -> None:
    assert len(CONTRACTS) == 8
    for contract in CONTRACTS.values():
        metadata = contract.metadata()
        assert metadata["fields"][0]["name"] == "execute"
        assert "not a reported" in metadata["fields"][0]["description"]
        assert metadata["live_write_verified"] is False
        assert "data/" not in repr(metadata)


def test_router_offer_uses_exact_fixed_endpoints_and_private_fresh_values() -> None:
    contract = CONTRACTS[ROUTER]
    base, offer = router_base(), router_offer()
    assert system_action_extra_read(ROUTER, base) == (
        "data/FwCheckForUpdate.json",
        "html/content/config/check_for_updates.html",
    )
    raw = merge_system_action_offer(ROUTER, base, offer)
    assert contract.read(raw) == {"execute": False, "physical_access": False}
    assert contract.build(raw, approvals()) == {
        "fwAutoUpdateImageUrl": offer["newFwImageURL"],
        "fwAutoUpdateImageDigest": offer["newFwDigest"],
    }
    assert contract.acknowledgement == "result_ok"
    assert contract.readback_policy == "reconnect_required"
    assert "private" not in repr(contract.read(raw))
    assert "synthetic-private" not in repr(contract)
    assert contract.revision(raw)["context"]["offer"]["digest"] == offer["newFwDigest"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fwupd_avail", "0"),
        ("status", "wait"),
        ("status", ["ok", "failed"]),
        ("fwupd_version", "1.0"),
        ("newFwImageURL", "file:///tmp/firmware"),
        ("newFwImageURL", "https://name:password@example.test/a"),
        ("newFwImageURL", "https://example.test:broken/a"),
        ("newFwImageURL", "https://example.test/a#fragment"),
        ("newFwImageURL", "https://example.test/a\n"),
        ("newFwDigest", ""),
    ],
)
def test_router_bad_offer_rejected_before_send(key: str, value: object) -> None:
    offer = {**router_offer(), key: value}
    with pytest.raises(ConfigurationError):
        merge_system_action_offer(ROUTER, router_base(), offer)


@pytest.mark.parametrize("value", ["1", "89"])
def test_managed_provider_automatic_updates_block_manual_check(value: str) -> None:
    base = {**router_base(), "inet_isp": value}
    with pytest.raises(ConfigurationError, match="managed_automatically"):
        system_action_extra_read(ROUTER, base)
    base["autofw_deactive"] = "1"
    assert system_action_extra_read(ROUTER, base) is not None


def test_offline_blocks_check_but_exact_mobile_or_tethering_paths_work() -> None:
    base = {**router_base(), "onlinestatus": "offline"}
    with pytest.raises(ConfigurationError, match="offline"):
        system_action_extra_read(ROUTER, base)
    assert system_action_extra_read(
        ROUTER, {**base, "extwan_typ": "3", "lte_status": "10"}
    )
    assert system_action_extra_read(
        ROUTER, {**base, "use_tethering": "1", "tethering_status": "2"}
    )


def test_offer_must_be_composed_by_closed_helper_not_arbitrary_namespace() -> None:
    with pytest.raises(ConfigurationError):
        merge_system_action_offer("other", router_base(), router_offer())
    raw = merge_system_action_offer(ROUTER, router_base(), router_offer())
    with pytest.raises(ConfigurationError):
        merge_system_action_offer(ROUTER, raw, router_offer())
    with pytest.raises(ConfigurationError):
        CONTRACTS[ROUTER].build(router_base(), approvals())


def test_mesh_counts_include_connected_local_nodes_but_offer_is_router_managed() -> (
    None
):
    first, local, offline = (
        mesh_node("1"),
        mesh_node("2"),
        mesh_node("3", connected="0"),
    )
    local.update(mesh_device_type="2", mesh_upd_local="1")
    base = {**router_base(), **mesh_raw(first, local, offline)}
    assert system_action_extra_read(MESH, base) == (
        "data/FwCheckForUpdateMesh.json?shw_num=1&shwl_num=1",
        "html/content/config/check_for_updates_mesh.html",
    )
    raw = merge_system_action_offer(MESH, base, mesh_offer(base))
    payload = CONTRACTS[MESH].build(raw, approvals())
    assert payload == {
        "MeshAutoUpdateImageUrl": first["newFwImageURL"],
        "MeshAutoUpdateImageDigest": first["newFwDigest"],
    }
    assert "mesh_serial" not in payload


def test_mesh_first_nonlocal_offer_matches_static_selector() -> None:
    first, second = mesh_node("1"), mesh_node("2")
    first["mesh_upd_avail"] = "0"
    second["newFwImageURL"] = "https://firmware.example.test/second.bin"
    base = {**router_base(), **mesh_raw(first, second)}
    raw = merge_system_action_offer(MESH, base, mesh_offer(base))
    assert (
        CONTRACTS[MESH].build(raw, approvals())["MeshAutoUpdateImageUrl"]
        == first["newFwImageURL"]
    )


@pytest.mark.parametrize(
    "change", ["missing", "replaced", "offline", "router_state", "local", "type"]
)
def test_mesh_partial_or_changed_offer_inventory_rejected(change: str) -> None:
    base = mesh_base()
    offer = mesh_offer(base)
    if change == "missing":
        offer["addmeshdevice"] = []
    elif change == "replaced":
        offer["addmeshdevice"][0]["mesh_serial"] = "replacement"
    elif change == "offline":
        offer["addmeshdevice"][0]["mesh_connected"] = "0"
    elif change == "local":
        offer["addmeshdevice"][0]["mesh_upd_local"] = "1"
    elif change == "type":
        offer["addmeshdevice"][0]["mesh_device_type"] = "2"
    else:
        offer["router_state"] = "REBOOT"
    with pytest.raises(ConfigurationError):
        merge_system_action_offer(MESH, base, offer)


def test_mesh_local_only_no_connected_and_no_updates_rejected() -> None:
    for updates in (
        {"mesh_upd_local": "1"},
        {"mesh_connected": "0"},
        {"mesh_upd_avail": "0"},
    ):
        base = mesh_base()
        base["addmeshdevice"][0].update(updates)
        with pytest.raises(ConfigurationError):
            merge_system_action_offer(MESH, base, mesh_offer(base))


@pytest.mark.parametrize("setting_id", [ROUTER, MESH, RECEIVER])
def test_firmware_requires_explicit_physical_recovery_attestation(
    setting_id: str,
) -> None:
    if setting_id == ROUTER:
        raw = merge_system_action_offer(ROUTER, router_base(), router_offer())
    elif setting_id == MESH:
        base = mesh_base()
        raw = merge_system_action_offer(MESH, base, mesh_offer(base))
    else:
        raw = receiver()
    with pytest.raises(ConfigurationError, match="confirmation_required"):
        CONTRACTS[setting_id].build(raw, {"execute": True})


def test_mesh_maintenance_uses_only_known_read_source_and_global_fixed_payload() -> (
    None
):
    for action, key in (
        ("system_mesh_restart", "reboot_device"),
        ("system_mesh_reset", "reset_device"),
    ):
        contract = CONTRACTS[action]
        assert contract.endpoint == "data/RebootMesh.json"
        assert contract.read_endpoint == "data/DeviceList.json"
        assert contract.read_referer == "html/content/network/devices.html"
        assert contract.referer == "html/content/config/problem_handling_mesh.html"
        changes = (
            {"execute": True}
            if action.endswith("restart")
            else {
                **approvals(),
                "backup_saved": True,
            }
        )
        assert contract.build(mesh_base(), changes) == {key: "true"}
        assert contract.acknowledgement == "readback"
        assert contract.readback_policy == "reconnect_required"
        with pytest.raises(ConfigurationError):
            contract.build(mesh_raw(), changes)


def test_smarthome_code_has_exact_three_secret_blocks_and_no_hidden_prefix() -> None:
    contract = CONTRACTS[ACTIVATE]
    raw = smart_home()
    assert contract.read(raw) == {"execute": False}
    changes = {"execute": True, "acode_2": "1234", "acode_3": "5678", "acode_4": "9012"}
    assert contract.build(raw, changes) == {
        key: value for key, value in changes.items() if key != "execute"
    }
    assert "9999" not in repr(contract.read(raw))
    assert "9999" not in repr(contract.metadata())
    assert all(field.kind == "secret" for field in contract.fields[1:])
    for key, value in (
        ("acode_2", "\uff11\uff12\uff13\uff14"),
        ("acode_3", "123"),
        ("acode_4", "abcd"),
    ):
        with pytest.raises(ConfigurationError):
            contract.build(raw, {**changes, key: value})
    with pytest.raises(ConfigurationError):
        contract.build(raw, {**changes, "acode_1": "1234"})


@pytest.mark.parametrize(
    "changes",
    [{"acode_locked": "4"}, {"smarthome_state_check": "1"}, {"use_smarthome": "1"}],
)
def test_smarthome_preflight_blocks_lock_progress_or_already_active(
    changes: dict,
) -> None:
    with pytest.raises(ConfigurationError):
        CONTRACTS[ACTIVATE].read({**smart_home(), **changes})


def test_missing_smarthome_lock_matches_static_getvar_false_branch() -> None:
    raw = smart_home()
    del raw["acode_locked"]
    assert CONTRACTS[ACTIVATE].read(raw) == {"execute": False}
    raw["acode_locked"] = ["0", "30"]
    with pytest.raises(ConfigurationError):
        CONTRACTS[ACTIVATE].read(raw)


@pytest.mark.parametrize("value", ["codewrong", "codeused"])
def test_smarthome_explicit_rejection_is_not_generic_success(value: str) -> None:
    with pytest.raises(SpeedportCommandRejectedError):
        validate_smarthome_response({"status": "ok", "smarthome_reg": value})


@pytest.mark.parametrize(
    "response",
    [
        {"smarthome_reg": ["accepted", "codewrong"]},
        {"SmartHome_Reg": "codewrong"},
        {"smarthome_reg": "accepted", "SMARTHOME_REG": "codewrong"},
        {"smarthome_reg": {}},
        {"smarthome_reg": False},
    ],
)
def test_smarthome_ambiguous_response_stays_unknown(response: dict) -> None:
    with pytest.raises(SpeedportMutationOutcomeUnknownError):
        validate_smarthome_response(response)


def test_smarthome_independent_verifiers_do_not_reapply_preflight() -> None:
    activate, deactivate = CONTRACTS[ACTIVATE], CONTRACTS[DEACTIVATE]
    assert activate.verifier({}, {}, smart_home(active="1", state="2"))
    assert not activate.verifier({}, {}, smart_home(active="1", state="1"))
    assert not activate.verifier({}, {}, smart_home(active="0", state="2"))
    assert deactivate.verifier({}, {}, smart_home(active="0", state="0"))
    assert not deactivate.verifier({}, {}, smart_home(active="1", state="2"))
    assert deactivate.build(smart_home(active="1", state="2"), {"execute": True}) == {
        "deact_shome": "true"
    }


def test_receiver_exact_update_and_restore_enums_private_identity_binding() -> None:
    raw = receiver()
    assert CONTRACTS[RECEIVER].build(raw, approvals()) == {"auto_update": "true"}
    contract = CONTRACTS[RESET]
    assert contract.read(raw) == {
        "execute": False,
        "physical_access": False,
        "reset_esim": False,
        "esim_recovery_ready": False,
    }
    assert contract.build(raw, approvals()) == {"restore": "0"}
    assert contract.build(
        raw, {**approvals(), "reset_esim": True, "esim_recovery_ready": True}
    ) == {"restore": "1"}
    assert contract.revision(raw)["context"]["serial"] == "private-serial"
    assert "private-serial" not in repr(contract.read(raw))
    with pytest.raises(ConfigurationError):
        contract.build(raw, {**approvals(), "reset_esim": True})
    with pytest.raises(ConfigurationError):
        contract.build(
            {**raw, "ex5g_eid": "not supported"},
            {
                **approvals(),
                "reset_esim": True,
                "esim_recovery_ready": True,
            },
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"auto_external_modem": "0"},
        {"extwan_typ": "2"},
        {"ex5g_serial_number": ""},
        {"ex5g_fwupd_avail": "0"},
        {"ex5g_fwupd_version": "1.0"},
    ],
)
def test_receiver_fresh_prerequisites_reject_unsupported_or_no_offer(
    changes: dict,
) -> None:
    with pytest.raises(ConfigurationError):
        CONTRACTS[RECEIVER].read({**receiver(), **changes})


async def test_changed_firmware_offer_consumes_revision_without_sending() -> None:
    contract = CONTRACTS[ROUTER]
    before = merge_system_action_offer(ROUTER, router_base(), router_offer())
    after = merge_system_action_offer(
        ROUTER, router_base(), {**router_offer(), "newFwDigest": "changed"}
    )
    session = ConfigurationSession()
    read, write = AsyncMock(side_effect=[before, after]), AsyncMock()
    review = await session.read(contract, OWNER, read)
    assert "private" not in repr(review)
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            contract,
            OWNER,
            review["revision"],
            approvals(),
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


@pytest.mark.parametrize("action", [ROUTER, "system_mesh_reset", RECEIVER, RESET])
async def test_async_actions_send_once_never_claim_verified(action: str) -> None:
    raw = (
        merge_system_action_offer(ROUTER, router_base(), router_offer())
        if action == ROUTER
        else (mesh_base() if action == "system_mesh_reset" else receiver())
    )
    changes = (
        {**approvals(), "backup_saved": True}
        if action == "system_mesh_reset"
        else approvals()
    )
    contract = CONTRACTS[action]
    session = ConfigurationSession()
    read, write = AsyncMock(return_value=raw), AsyncMock(return_value={"result": "ok"})
    review = await session.read(contract, OWNER, read)
    result = await session.save(
        contract,
        OWNER,
        review["revision"],
        changes,
        confirmed=True,
        confirmation_text=contract.confirmation,
        read=read,
        write=write,
    )
    assert result["status"] == (
        "outcome_unknown" if action == "system_mesh_reset" else "reconnect_required"
    )
    assert read.await_count == 2
    write.assert_awaited_once()


async def test_smarthome_activation_bounded_readback_never_retries_code() -> None:
    contract = CONTRACTS[ACTIVATE]
    session = ConfigurationSession()
    raw = smart_home()
    progress = smart_home(active="1", state="1")
    read = AsyncMock(side_effect=[raw, raw, progress, progress, progress, progress])
    write = AsyncMock(return_value={"status": "ok"})
    review = await session.read(contract, OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            contract,
            OWNER,
            review["revision"],
            {
                "execute": True,
                "acode_2": "1234",
                "acode_3": "5678",
                "acode_4": "9012",
            },
            confirmed=True,
            confirmation_text=contract.confirmation,
            read=read,
            write=write,
        )
    assert read.await_count == 6
    write.assert_awaited_once()


@pytest.mark.parametrize(
    ("action", "responses", "code"),
    [
        *(
            (
                action,
                [{**router_base(), "mesh_exist": "0"}],
                "system_mesh_unavailable",
            )
            for action in ("system_mesh_restart", "system_mesh_reset", MESH)
        ),
        *(
            (action, [router_base()], "incomplete_mesh_inventory")
            for action in ("system_mesh_restart", "system_mesh_reset", MESH)
        ),
        (
            MESH,
            [{**router_base(), **mesh_raw({**mesh_node(), "mesh_upd_local": "1"})}],
            "system_mesh_local_update_only",
        ),
        *(
            (
                ROUTER,
                [{**router_base(), "inet_isp": provider}],
                "system_firmware_managed_automatically",
            )
            for provider in ("1", "89")
        ),
        *(
            (
                ROUTER,
                [router_base(), {**router_offer(), **offer_change}],
                "system_firmware_offer_unavailable",
            )
            for offer_change in (
                {"fwupd_avail": "0"},
                {"fwupd_version": "1.0"},
                {"status": "failed"},
            )
        ),
        *(
            (
                RECEIVER,
                [{**receiver(), **offer_change}],
                "system_firmware_offer_unavailable",
            )
            for offer_change in (
                {"ex5g_fwupd_avail": "0"},
                {"ex5g_fwupd_version": "1.0"},
            )
        ),
    ],
)
async def test_unavailable_maintenance_read_has_exact_reason_no_grant_or_write(
    action: str, responses: list[dict], code: str
) -> None:
    """Missing offers/targets stay disabled; malformed inventory is not empty."""
    client = SpeedportClient(MagicMock(), "router.invalid")
    session = ConfigurationSession()
    contract = CONTRACTS[action]

    async def read() -> dict:
        return await client.read_configuration(action)

    with (
        patch.object(client, "get_json", AsyncMock(side_effect=responses)) as get,
        patch.object(client, "_post_json_unlocked", AsyncMock()) as post,
        pytest.raises(ConfigurationError) as error,
    ):
        await session.read(contract, OWNER, read)

    assert error.value.code == code
    assert session._grants == {}  # noqa: SLF001 - failed reads must mint no grant
    assert get.await_count == len(responses)
    first = get.await_args_list[0]
    assert first.args == (contract.read_endpoint or contract.endpoint,)
    assert first.kwargs["authenticated"] is True
    assert first.kwargs["referer"] == (contract.read_referer or contract.referer)
    if len(responses) == 2:
        get.assert_awaited_with(
            "data/FwCheckForUpdate.json",
            authenticated=True,
            referer="html/content/config/check_for_updates.html",
            preserve_compounds=True,
        )
    post.assert_not_awaited()
