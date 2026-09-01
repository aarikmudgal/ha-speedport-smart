"""Focused tests for serialized Speedport protocol client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Self
from unittest.mock import AsyncMock, MagicMock, call, patch
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.speedport_smart.api import (
    DEFAULT_FEATURE_CANDIDATES,
    DEFAULT_KEY,
    EndpointCapability,
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportCommandRejectedError,
    encode_payload,
)
from custom_components.speedport_smart.api.exceptions import (
    SpeedportProtocolError,
    SpeedportSessionBusyError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.models import (
    RouterInfo,
    RouterStatus,
    WanInterface,
)
from custom_components.speedport_smart.normalizers import normalize_feature_payload


@dataclass(slots=True)
class _FakeResponse:
    owner: _FakeSession
    body: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0

    async def __aenter__(self) -> Self:
        self.owner.active += 1
        self.owner.max_active = max(self.owner.max_active, self.owner.active)
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.owner.active -= 1

    async def text(self, *, errors: str) -> str:
        assert errors == "replace"
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.body


class _FakeSession:
    def __init__(self) -> None:
        self.responses: list[_FakeResponse] = []
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.active = 0
        self.max_active = 0

    def add(
        self,
        body: str,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0,
    ) -> None:
        self.responses.append(_FakeResponse(self, body, status, headers or {}, delay))

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def _decode_form(payload: str, key: bytes | str) -> dict[str, str]:
    """Decode one encrypted router form body for protocol assertions."""
    key_bytes = bytes.fromhex(key) if isinstance(key, str) else key
    plaintext = AESCCM(key_bytes, tag_length=16).decrypt(
        key_bytes[:8], bytes.fromhex(payload), None
    )
    return {
        name: values[-1]
        for name, values in parse_qs(plaintext.decode(), keep_blank_values=True).items()
    }


def _managed_device_row(**overrides: str) -> dict[str, str]:
    """Return one complete sanitized ManagedDevice firmware row."""
    row = {
        "mdevice_mac": "AA:BB:CC:DD:EE:FF",
        "mdevice_use_dhcp": "1",
        "mdevice_use_rule": "0",
        "mdevice_originalip": "192.0.2.10",
        "mdevice_ipv4": "192.0.2.10",
        "mdevice_reservedip": "10",
        "mdevice_type": "unknown",
        "mdevice_wifi": "1",
        "mdevice_connected": "1",
        "mdevice_slave": "0",
        "mdevice_downspeed": "1000",
        "mdevice_upspeed": "100",
        "mdevice_rssi": "-50",
        "mdevice_hasui": "0",
        "id": "row-1",
        "mdevice_name": "Phone",
        "mdevice_fix_dhcp": "0",
    }
    row.update(overrides)
    return row


def _port_forward_rule(**overrides: str) -> dict[str, str]:
    """Return one forwarding rule with stable non-active semantics."""
    row = {
        "id": "rule-1",
        "portuw_name": "HTTPS",
        "portuw_active": "1",
        "portuw_protocol": "TCP",
        "portuw_target": "192.0.2.10",
        "portuw_public_port": "443",
        "portuw_private_port": "443",
    }
    row.update(overrides)
    return row


def _port_forward_fingerprint(row: dict[str, str]) -> str:
    """Return normalized internal identity proof for one raw rule."""
    rule = normalize_feature_payload("nat", {"addportuw": [row]})["nat"][
        "port_forward_rules"
    ][0]
    fingerprint = rule.get("_identity_fingerprint")
    assert isinstance(fingerprint, str)
    return fingerprint


def _soap_response(*parameters: tuple[str, str, str]) -> str:
    values = "".join(
        "<cwmp:ParameterValueStruct>"
        f"<cwmp:Name>{name}</cwmp:Name>"
        f'<cwmp:Value xsi:type="xsd:{data_type}">{value}</cwmp:Value>'
        "</cwmp:ParameterValueStruct>"
        for name, value, data_type in parameters
    )
    return (
        '<soap-env:Envelope xmlns:soap-env="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
        "<soap-env:Body><cwmp:GetParameterValuesResponse>"
        f"<cwmp:ParameterList>{values}</cwmp:ParameterList>"
        "</cwmp:GetParameterValuesResponse></soap-env:Body></soap-env:Envelope>"
    )


def _busy_fault() -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0"><s:Body><s:Fault>'
        "<faultcode>Client</faultcode><faultstring>CWMP fault</faultstring>"
        "<detail><cwmp:Fault><FaultCode>9801</FaultCode>"
        "<FaultString>Session busy</FaultString></cwmp:Fault></detail>"
        "</s:Fault></s:Body></s:Envelope>"
    )


def _unsupported_parameter_fault() -> str:
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:cwmp="urn:dslforum-org:cwmp-1-0"><s:Body><s:Fault>'
        "<faultcode>Client</faultcode><faultstring>CWMP fault</faultstring>"
        "<detail><cwmp:Fault><FaultCode>9005</FaultCode>"
        "<FaultString>Invalid Parameter Name</FaultString>"
        "</cwmp:Fault></detail></s:Fault></s:Body></s:Envelope>"
    )


@pytest.mark.asyncio
async def test_all_router_requests_are_serialized() -> None:
    """Concurrent poll groups never overlap router requests."""
    session = _FakeSession()
    body = encode_payload('{"online_status":"online"}')
    session.add(body, delay=0.01)
    session.add(body, delay=0.01)
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    first, second = await asyncio.gather(client.get_status(), client.get_status())

    assert first.internet_state == "online"
    assert second.internet_state == "online"
    assert session.max_active == 1


def test_client_has_no_public_arbitrary_json_write_boundary() -> None:
    """Callers can mutate only through exact reviewed client methods."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]

    assert not hasattr(client, "post_json")


@pytest.mark.asyncio
async def test_feature_read_records_value_free_schema_without_extra_request() -> None:
    """One successful feature GET records only its already-returned structure."""
    session = _FakeSession()
    session.add(
        encode_payload(
            '{"wlan_active":"private-value","rows":['
            '{"enabled":true,"channel":11}],"empty":[],"matrix":[[true]]}'
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]
    client._selected_endpoints["wifi"] = EndpointCapability(  # noqa: SLF001
        "wifi",
        "data/WLANBasic.json",
        referer="html/content/network/wlan_basic.html",
    )

    result = await client.get_feature_data("wifi")

    assert result == {
        "wlan_active": "private-value",
        "rows": [{"enabled": True, "channel": 11}],
        "empty": [],
        "matrix": [[True]],
    }
    assert len(session.requests) == 1
    assert session.responses == []
    assert {
        (descriptor["path"], descriptor["shape"])
        for descriptor in client.observed_feature_schema["wifi"]
    } == {
        ("wlan_active", "string"),
        ("rows", "array"),
        ("rows[]", "object"),
        ("rows[].enabled", "boolean"),
        ("rows[].channel", "integer"),
        ("empty", "array"),
        ("matrix", "array"),
        ("matrix[]", "array"),
        ("matrix[][]", "boolean"),
    }
    rendered = repr(client.observed_feature_schema)
    assert "speedport.ip" not in rendered
    assert "data/WLANBasic.json" not in rendered
    assert "html/content/network/wlan_basic.html" not in rendered


def test_observed_schema_rejects_identifiers_values_and_is_immutable() -> None:
    """PII-like names and all scalar values stay outside immutable snapshots."""
    session = _FakeSession()
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]
    client._selected_endpoints["wifi"] = EndpointCapability(  # noqa: SLF001
        "wifi", "data/WLANBasic.json"
    )
    client.observe_feature_data(
        "wifi",
        {
            "wlan_active": "private-credential-value",
            "rows": [
                {
                    "state": True,
                    "item[37]": None,
                    "aa:bb:cc:dd:ee:ff": "mac-key",
                    "aa_bb_cc_dd_ee_ff": "separated-mac-key",
                    "aabbccddeeff": "compact-mac-key",
                    "192.0.2.12": "ip-key",
                    "host_192_0_2_12": "embedded-ip-key",
                    "private@example.test": "email-key",
                    "row_1": "short-row-id",
                    "device_aabbccdd": "hex-device-id",
                    "row_123456789": "long-number-key",
                    "source_row_id": "row-id-field",
                    "auth_token": "credential-field",
                    "endpoint": "data/private.json",
                    "router_password": "password-field",
                    "raw_payload": "raw-field",
                    "aarik": "opaque-user-label",
                    "livingroom": "opaque-device-label",
                    "living_room": "underscore-device-label",
                    "wifi_alice": "prefixed-user-label",
                    "MixedCase": "dynamic-label",
                    "user-label": "dynamic-label",
                }
            ],
            "values": ["one", "two", "three"],
        },
    )

    snapshot = client.observed_feature_schema
    rendered = repr(snapshot)
    paths = {descriptor["path"] for descriptor in snapshot["wifi"]}

    assert "wlan_active" in paths
    assert "rows[].state" in paths
    assert "rows[].item[]" in paths
    assert "values[]" in paths
    for forbidden in (
        "private-credential-value",
        "aa:bb:cc:dd:ee:ff",
        "aa_bb_cc_dd_ee_ff",
        "aabbccddeeff",
        "192.0.2.12",
        "host_192_0_2_12",
        "private@example.test",
        "row_1",
        "device_aabbccdd",
        "123456789",
        "source_row_id",
        "auth_token",
        "endpoint",
        "router_password",
        "raw_payload",
        "data/private.json",
        "aarik",
        "livingroom",
        "living_room",
        "wifi_alice",
        "MixedCase",
        "user-label",
        "one",
        "two",
        "three",
        "[37]",
    ):
        assert forbidden not in rendered
    assert session.requests == []

    with pytest.raises(TypeError):
        snapshot["wifi"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot["wifi"][0]["path"] = "changed"  # type: ignore[index]

    client.observe_feature_data("wifi", {"wlan_visible": False})
    assert "wlan_visible" not in {descriptor["path"] for descriptor in snapshot["wifi"]}
    assert "wlan_visible" in {
        descriptor["path"] for descriptor in client.observed_feature_schema["wifi"]
    }


def test_policy_schema_records_only_fixed_value_free_contract_names() -> None:
    """DNS/QoS structure is discoverable without domains or client identity."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    client._selected_endpoints["dns_rebind"] = EndpointCapability(  # noqa: SLF001
        "dns_rebind", "data/DNSExcept.json"
    )
    client._selected_endpoints["qos"] = EndpointCapability(  # noqa: SLF001
        "qos", "data/QOS.json"
    )

    client.observe_feature_data(
        "dns_rebind",
        {"adddnsexcept": [{"hostname": "private-service.example"}]},
    )
    client.observe_feature_data(
        "qos",
        {
            "qos_pc[1]": "1",
            "hostname": "private-client",
            "mac": "aa:bb:cc:dd:ee:ff",
        },
    )

    dns_paths = {
        descriptor["path"]
        for descriptor in client.observed_feature_schema["dns_rebind"]
    }
    qos_paths = {
        descriptor["path"] for descriptor in client.observed_feature_schema["qos"]
    }
    assert dns_paths == {"adddnsexcept", "adddnsexcept[]"}
    assert qos_paths == {"qos_pc[]"}
    rendered = repr(client.observed_feature_schema)
    for private_value in (
        "private-service.example",
        "private-client",
        "aa:bb:cc:dd:ee:ff",
        "hostname",
        "mac",
    ):
        assert private_value not in rendered


def test_telephony_schema_keeps_only_safe_inventory_shapes() -> None:
    """Repeater membership and counts are visible without telephony identity."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    client._selected_endpoints["dect"] = EndpointCapability(  # noqa: SLF001
        "dect", "data/DECTStation.json"
    )

    client.observe_feature_data(
        "dect",
        {
            "addrepeater": [{"id": "private-repeater-id", "name": "Private"}],
            "num_entries": 42,
            "dect_pin": "1234",
            "phone_number": "+49 30 123456",
        },
    )

    assert {
        descriptor["path"] for descriptor in client.observed_feature_schema["dect"]
    } == {"addrepeater", "addrepeater[]", "num_entries"}
    rendered = repr(client.observed_feature_schema)
    for forbidden in (
        "private-repeater-id",
        "Private",
        "dect_pin",
        "phone_number",
        "+49 30 123456",
    ):
        assert forbidden not in rendered


def test_observed_schema_inventory_is_strictly_bounded() -> None:
    """Depth, field count, array samples and key length have hard limits."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    client._selected_endpoints["wifi"] = EndpointCapability(  # noqa: SLF001
        "wifi", "data/WLANBasic.json"
    )
    deep: dict[str, Any] = {}
    cursor = deep
    for _index in range(10):
        child: dict[str, Any] = {}
        cursor["rows"] = child
        cursor = child
    sampled_fields = (
        "active",
        "available",
        "bond",
        "call",
        "channel",
        "connected",
        "count",
        "enabled",
        "energy",
    )
    client.observe_feature_data(
        "wifi",
        {
            "deep": deep,
            "rows": [{field: True} for field in sampled_fields],
            "wide": {field: index for index, field in enumerate(sampled_fields)},
            f"field_{'x' * 65}": True,
        },
    )

    fields = client.observed_feature_schema["wifi"]
    paths = {descriptor["path"] for descriptor in fields}

    assert len(fields) <= 128
    assert all(path.count(".") + path.count("[]") + 1 <= 6 for path in paths)
    assert "rows[].enabled" in paths
    assert "rows[].energy" not in paths
    assert not any("x" * 65 in path for path in paths)

    client._selected_endpoints["mesh"] = EndpointCapability(  # noqa: SLF001
        "mesh", "data/Mesh.json"
    )
    client.observe_feature_data(
        "mesh",
        {
            **{f"unsafe-label-{index}": True for index in range(300)},
            "late_field": True,
        },
    )
    assert client.observed_feature_schema["mesh"] == ()


def test_all_default_probe_candidate_metadata_is_privacy_safe() -> None:
    """Every built-in candidate can be named without host or response data."""
    session = _FakeSession()
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    for family, candidates in DEFAULT_FEATURE_CANDIDATES.items():
        for candidate in candidates:
            client._observe_candidate_data(family, candidate, {})  # noqa: SLF001

    snapshot = client.observed_candidate_schema
    assert set(snapshot) == set(DEFAULT_FEATURE_CANDIDATES)
    for family, candidates in DEFAULT_FEATURE_CANDIDATES.items():
        assert {
            (
                candidate["endpoint"],
                candidate["authenticated"],
                candidate["referer"],
            )
            for candidate in snapshot[family]
        } == {
            (candidate.endpoint, candidate.authenticated, candidate.referer)
            for candidate in candidates
        }
        assert all(candidate["schema"] == () for candidate in snapshot[family])

    assert "speedport.ip" not in repr(snapshot)
    assert session.requests == []


def test_observed_candidate_schema_metadata_is_strictly_bounded() -> None:
    """Candidate diagnostics cap entries globally and within each family."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]

    for family_index in range(24):
        family = f"candidate_{family_index}"
        for endpoint_index in range(10):
            candidate = EndpointCapability(
                family,
                f"data/Candidate{family_index}_{endpoint_index}.json",
                authenticated=True,
                referer="html/content/config/energy.html",
            )
            client._observe_candidate_data(  # noqa: SLF001
                family,
                candidate,
                {"energy": True},
            )

    snapshot = client.observed_candidate_schema
    assert sum(len(candidates) for candidates in snapshot.values()) == 128
    assert all(len(candidates) <= 8 for candidates in snapshot.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "base_kwargs"),
    [
        ("execute_wifi_set_enabled", {}),
        ("set_guest_wifi", {}),
        ("set_office_wifi", {}),
        (
            "set_client_fixed_dhcp",
            {
                "source_kind": "addmdevice",
                "row_id": "row-1",
                "stable_mac": "AA:BB:CC:DD:EE:FF",
            },
        ),
        (
            "set_port_forward_rule",
            {
                "rule_id": "rule-1",
                "expected_name": "HTTPS",
                "expected_fingerprint": "a" * 64,
            },
        ),
    ],
)
@pytest.mark.parametrize("invalid_enabled", [0, 1, "false", None])
async def test_boolean_controls_reject_non_booleans_before_router_io(
    method: str,
    base_kwargs: dict[str, object],
    invalid_enabled: object,
) -> None:
    """Integers, strings, and null cannot cross a Boolean write boundary."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    get_json = AsyncMock()
    post_json = AsyncMock()

    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportProtocolError),
    ):
        await getattr(client, method)(
            **base_kwargs,
            enabled=invalid_enabled,
        )

    get_json.assert_not_awaited()
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        {
            "method": "set_internet_privacy_level",
            "kwargs": {"level": 2},
            "endpoint": "data/IPPrivacy.json",
            "referer": "html/content/internet/con_privacy.html",
            "field": "lan_privacy_policy",
            "current_value": "0",
            "desired_value": "2",
        },
        {
            "method": "set_receiver_led_mode",
            "kwargs": {"mode": 1},
            "endpoint": "data/LTE.json",
            "referer": "html/content/internet/lte_mode.html",
            "field": "ex5g_led_mode",
            "current_value": "2",
            "desired_value": "1",
        },
        {
            "method": "set_hybrid_bonding",
            "kwargs": {"enabled": True},
            "endpoint": "data/LTE.json",
            "referer": "html/content/internet/lte_mode.html",
            "field": "use_bonding",
            "current_value": "0",
            "desired_value": "1",
        },
    ],
)
async def test_guarded_scalar_control_fresh_reads_then_posts_exact_field(
    case: dict[str, Any],
) -> None:
    """Each scalar control uses one authenticated read and one exact write."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    timeline = AsyncMock()
    get_json = AsyncMock(
        return_value={
            case["field"]: case["current_value"],
            "unrelated_read_only_field": "kept",
        }
    )
    post_json = AsyncMock(return_value={"status": "ok"})
    timeline.attach_mock(get_json, "get")
    timeline.attach_mock(post_json, "post")

    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        result = await getattr(client, case["method"])(**case["kwargs"])

    assert result == {"status": "ok"}
    assert timeline.mock_calls == [
        call.get(case["endpoint"], authenticated=True, referer=case["referer"]),
        call.post(
            case["endpoint"],
            {case["field"]: case["desired_value"]},
            authenticated=True,
            referer=case["referer"],
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs", "field", "current_value"),
    [
        (
            "set_internet_privacy_level",
            {"level": 1},
            "lan_privacy_policy",
            "1",
        ),
        ("set_receiver_led_mode", {"mode": 2}, "ex5g_led_mode", "2"),
        ("set_hybrid_bonding", {"enabled": False}, "use_bonding", "0"),
    ],
)
async def test_guarded_scalar_control_noops_after_fresh_matching_state(
    method: str,
    kwargs: dict[str, object],
    field: str,
    current_value: str,
) -> None:
    """A fresh matching scalar state never produces a POST."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    post_json = AsyncMock()
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={field: current_value}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        result = await getattr(client, method)(**kwargs)

    assert result == {"status": "unchanged"}
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("set_internet_privacy_level", {"level": True}),
        ("set_internet_privacy_level", {"level": 0.0}),
        ("set_internet_privacy_level", {"level": "0"}),
        ("set_internet_privacy_level", {"level": None}),
        ("set_internet_privacy_level", {"level": -1}),
        ("set_internet_privacy_level", {"level": 3}),
        ("set_receiver_led_mode", {"mode": False}),
        ("set_receiver_led_mode", {"mode": "1"}),
        ("set_receiver_led_mode", {"mode": -1}),
        ("set_receiver_led_mode", {"mode": 3}),
        ("set_hybrid_bonding", {"enabled": 0}),
        ("set_hybrid_bonding", {"enabled": 1}),
        ("set_hybrid_bonding", {"enabled": "1"}),
        ("set_hybrid_bonding", {"enabled": None}),
    ],
)
async def test_guarded_scalar_control_rejects_invalid_requested_state_before_read(
    method: str,
    kwargs: dict[str, object],
) -> None:
    """Wrong types, bool-as-int, and out-of-range values fail before I/O."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    get_json = AsyncMock()
    post_json = AsyncMock()
    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportProtocolError),
    ):
        await getattr(client, method)(**kwargs)

    get_json.assert_not_awaited()
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "readback",
    [
        {},
        {"LAN_PRIVACY_POLICY": "0"},
        {"lan_privacy_policy": "0", "LAN_PRIVACY_POLICY": "0"},
        {"lan_privacy_policy": 0},
        {"lan_privacy_policy": False},
        {"lan_privacy_policy": ["0"]},
        {"lan_privacy_policy": None},
        {"lan_privacy_policy": "3"},
        {"lan_privacy_policy": "enabled"},
        {"group": {"lan_privacy_policy": "0"}},
    ],
    ids=[
        "missing",
        "wrong-case",
        "ambiguous",
        "integer",
        "boolean",
        "sequence",
        "null",
        "out-of-range",
        "unexpected",
        "nested",
    ],
)
async def test_guarded_scalar_control_rejects_unsafe_fresh_state_before_post(
    readback: dict[str, object],
) -> None:
    """Missing, ambiguous, or non-allowlisted current state blocks mutation."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    post_json = AsyncMock()
    with (
        patch.object(client, "_get_json_unlocked", AsyncMock(return_value=readback)),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.set_internet_privacy_level(1)

    post_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_guarded_scalar_control_rejected_ack_is_not_retried() -> None:
    """A negative application acknowledgement fails after exactly one POST."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    get_json = AsyncMock(return_value={"ex5g_led_mode": "0"})
    post_json = AsyncMock(return_value={"status": "denied"})
    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportCommandRejectedError),
    ):
        await client.set_receiver_led_mode(2)

    get_json.assert_awaited_once()
    post_json.assert_awaited_once_with(
        "data/LTE.json",
        {"ex5g_led_mode": "2"},
        authenticated=True,
        referer="html/content/internet/lte_mode.html",
    )


@pytest.mark.asyncio
async def test_managed_client_rename_fresh_reads_and_preserves_full_row() -> None:
    """Rename changes one field after a fresh exact-kind row read."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    row = _managed_device_row()
    timeline = AsyncMock()
    get_json = AsyncMock(return_value={"addmdevice": [row]})
    post_json = AsyncMock(return_value={"status": "ok"})
    timeline.attach_mock(get_json, "get")
    timeline.attach_mock(post_json, "post")

    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        result = await client.rename_client(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="aa-bb-cc-dd-ee-ff",
            name="Living-Room",
        )

    assert result == {"status": "ok"}
    expected = {**row, "mdevice_name": "Living-Room"}
    assert timeline.mock_calls == [
        call.get(
            "data/DeviceList.json",
            authenticated=True,
            referer="html/content/network/devices.html",
        ),
        call.post(
            "data/ManagedDevice.json",
            expected,
            authenticated=True,
            referer="html/content/network/devices.html",
        ),
    ]


@pytest.mark.asyncio
async def test_port_forward_toggle_fresh_reads_identity_before_write() -> None:
    """A rule toggle reads the exact rule and state under the client lock first."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    timeline = AsyncMock()
    rule = _port_forward_rule()
    get_json = AsyncMock(return_value={"addportuw": [rule]})
    post_json = AsyncMock(return_value={"status": "ok"})
    timeline.attach_mock(get_json, "get")
    timeline.attach_mock(post_json, "post")

    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        result = await client.set_port_forward_rule(
            rule_id="rule-1",
            enabled=False,
            expected_name="HTTPS",
            expected_fingerprint=_port_forward_fingerprint(rule),
        )

    assert result == {"status": "ok"}
    assert timeline.mock_calls == [
        call.get(
            "data/PortuwMain.json",
            authenticated=True,
            referer="html/content/internet/portforwarding.html",
        ),
        call.post(
            "data/PortuwMain.json",
            {"id": "rule-1", "portuw_active": "0"},
            authenticated=True,
            referer="html/content/internet/portforwarding.html",
        ),
    ]


@pytest.mark.asyncio
async def test_port_forward_toggle_noops_after_fresh_matching_state() -> None:
    """A fresh rule already at the desired state never produces a POST."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    post_json = AsyncMock()
    rule = _port_forward_rule(portuw_active="0")
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addportuw": [rule]}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        result = await client.set_port_forward_rule(
            rule_id="rule-1",
            enabled=False,
            expected_name="HTTPS",
            expected_fingerprint=_port_forward_fingerprint(rule),
        )

    assert result == {"status": "unchanged"}
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fresh_rules",
    [
        [],
        [_port_forward_rule(portuw_name="Reused")],
        [_port_forward_rule(portuw_target="192.0.2.99")],
        [
            _port_forward_rule(),
            _port_forward_rule(portuw_active="0"),
        ],
    ],
    ids=["deleted", "renamed", "retargeted", "duplicated"],
)
async def test_port_forward_toggle_rejects_deleted_or_reused_identity(
    fresh_rules: list[dict[str, str]],
) -> None:
    """A cached rule ID cannot target a deleted, reused, or ambiguous rule."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    post_json = AsyncMock()
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addportuw": fresh_rules}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.set_port_forward_rule(
            rule_id="rule-1",
            enabled=False,
            expected_name="HTTPS",
            expected_fingerprint=_port_forward_fingerprint(_port_forward_rule()),
        )

    post_json.assert_not_awaited()


def test_port_forward_fingerprint_tracks_semantics_not_active_state() -> None:
    """Normalized rules expose a proof only when stable semantics discriminate."""
    baseline = _port_forward_rule()
    fingerprint = _port_forward_fingerprint(baseline)

    assert (
        _port_forward_fingerprint(_port_forward_rule(portuw_active="0")) == fingerprint
    )
    assert (
        _port_forward_fingerprint(_port_forward_rule(portuw_private_port="8443"))
        != fingerprint
    )

    minimal = normalize_feature_payload(
        "nat",
        {"addportuw": [{"id": "rule-1", "portuw_name": "HTTPS", "portuw_active": "1"}]},
    )["nat"]["port_forward_rules"][0]
    assert "_identity_fingerprint" not in minimal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_kind", "endpoint", "removed_fields"),
    [
        ("addmdevice", "data/ManagedDevice.json", frozenset()),
        (
            "addmlandevice",
            "data/ManagedLANDevice.json",
            frozenset({"mdevice_wifi", "mdevice_upspeed", "mdevice_rssi"}),
        ),
        ("addmwlandevice", "data/ManagedWLAN2Device.json", frozenset()),
        ("addmwlan5device", "data/ManagedWLAN5Device.json", frozenset()),
    ],
)
async def test_managed_client_source_kind_selects_exact_firmware_form(
    source_kind: str,
    endpoint: str,
    removed_fields: frozenset[str],
) -> None:
    """Every proven template kind routes only to its matching save endpoint."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    row = {
        key: value
        for key, value in _managed_device_row().items()
        if key not in removed_fields
    }
    post_json = AsyncMock(return_value={"status": "ok"})
    stable_mac = None if "mdevice_mac" in removed_fields else row["mdevice_mac"]
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={source_kind: [row]}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        await client.rename_client(
            source_kind=source_kind,
            row_id="row-1",
            stable_mac=stable_mac,
            name="Router-Client",
        )

    post_json.assert_awaited_once()
    assert post_json.await_args.args[0] == endpoint
    assert post_json.await_args.args[1] == {**row, "mdevice_name": "Router-Client"}


@pytest.mark.asyncio
async def test_priority_managed_client_row_is_read_only() -> None:
    """Priority rows remain visible but cannot reach a mutation endpoint."""
    row = _managed_device_row()
    row.pop("mdevice_mac")
    normalized = normalize_feature_payload("clients", {"addmpriodevice": [row]})[
        "clients"
    ]["items"][0]
    assert normalized["source_kind"] == "addmpriodevice"
    assert normalized["source_row_id"] == "row-1"
    assert "managed_form_supported" not in normalized

    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    get_json = AsyncMock()
    post_json = AsyncMock()
    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.rename_client(
            source_kind="addmpriodevice",
            row_id="row-1",
            stable_mac=None,
            name="Router-Client",
        )

    get_json.assert_not_awaited()
    post_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_managed_client_rejects_fresh_row_with_missing_mac() -> None:
    """A reused row ID without its stable MAC cannot reach a mutation request."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    row = _managed_device_row(mdevice_mac="")
    post_json = AsyncMock()
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addmdevice": [row]}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.rename_client(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            name="Router-Client",
        )

    post_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_managed_client_selects_exact_parallel_column_row() -> None:
    """Parallel firmware columns are aligned and matched by ID plus MAC."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    first = _managed_device_row()
    second = _managed_device_row(
        id="row-2",
        mdevice_mac="11:22:33:44:55:66",
        mdevice_name="Tablet",
        mdevice_ipv4="192.0.2.11",
    )
    columns = {key: [first[key], second[key]] for key in first}
    post_json = AsyncMock(return_value={"status": "ok"})
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addmdevice": columns}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        await client.rename_client(
            source_kind="addmdevice",
            row_id="row-2",
            stable_mac="11:22:33:44:55:66",
            name="Kitchen-Tablet",
        )

    assert post_json.await_args.args[1] == {
        **second,
        "mdevice_name": "Kitchen-Tablet",
    }


@pytest.mark.asyncio
async def test_fixed_dhcp_changes_only_flag_and_keeps_address_metadata() -> None:
    """Toggle preserves every current row value, including all address fields."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    row = _managed_device_row()
    get_json = AsyncMock(return_value={"addmdevice": [row]})
    post_json = AsyncMock(return_value={"status": "ok"})

    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        await client.set_client_fixed_dhcp(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            enabled=True,
        )

    submitted = post_json.await_args.args[1]
    assert submitted == {**row, "mdevice_fix_dhcp": "1"}
    assert submitted["mdevice_originalip"] == row["mdevice_originalip"]
    assert submitted["mdevice_ipv4"] == row["mdevice_ipv4"]
    assert submitted["mdevice_reservedip"] == row["mdevice_reservedip"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [_managed_device_row(), _managed_device_row()],
        [_managed_device_row(mdevice_use_rule="1")],
        [_managed_device_row(mdevice_use_rule="2")],
        [_managed_device_row(mdevice_use_rule="unknown")],
        [_managed_device_row(mdevice_use_dhcp="unknown")],
        [_managed_device_row(mdevice_fix_dhcp="unknown")],
        [_managed_device_row(mdevice_ipv4="not-an-ip")],
        [_managed_device_row(mdevice_unproven="value")],
    ],
)
async def test_fixed_dhcp_rejects_ambiguous_or_unproven_rows(
    rows: list[dict[str, str]],
) -> None:
    """Unsafe fresh rows fail before any authenticated mutation is submitted."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    post_json = AsyncMock()
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addmdevice": rows}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportUnsupportedError),
    ):
        await client.set_client_fixed_dhcp(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            enabled=True,
        )
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["reconnect", "reboot", "wps"])
@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "error"},
        {"status": "denied"},
        {"status": False},
        {"status": 0},
    ],
)
async def test_commands_reject_missing_or_negative_acknowledgements(
    command: str,
    response: dict[str, object],
) -> None:
    """Enabled buttons never report success for an application-level rejection."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    with (
        patch.object(client, "_post_json_unlocked", AsyncMock(return_value=response)),
        pytest.raises(SpeedportCommandRejectedError),
    ):
        await getattr(client, command)()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["unsafe name", "unsafe_name", "Grüße", "", "x" * 29],
)
async def test_managed_client_rejects_invalid_name_before_read_or_write(
    name: str,
) -> None:
    """Direct callers cannot bypass the firmware's conservative name contract."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    get_json = AsyncMock()
    post_json = AsyncMock()
    with (
        patch.object(client, "_get_json_unlocked", get_json),
        patch.object(client, "_post_json_unlocked", post_json),
        pytest.raises(SpeedportProtocolError),
    ):
        await client.rename_client(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            name=name,
        )
    get_json.assert_not_awaited()
    post_json.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["-Phone", "Phone-", "-"])
async def test_managed_client_accepts_full_firmware_name_contract(name: str) -> None:
    """Firmware-supported leading and trailing hyphens remain valid."""
    client = SpeedportClient(_FakeSession(), "speedport.ip")  # type: ignore[arg-type]
    row = _managed_device_row()
    post_json = AsyncMock(return_value={"status": "ok"})
    with (
        patch.object(
            client,
            "_get_json_unlocked",
            AsyncMock(return_value={"addmdevice": [row]}),
        ),
        patch.object(client, "_post_json_unlocked", post_json),
    ):
        await client.rename_client(
            source_kind="addmdevice",
            row_id="row-1",
            stable_mac="AA:BB:CC:DD:EE:FF",
            name=name,
        )

    assert post_json.await_args.args[1] == {**row, "mdevice_name": name}


def test_client_normalizer_exposes_only_safe_management_metadata() -> None:
    """Normalized clients retain source identity and safe control state only."""
    row = _managed_device_row()
    normalized = normalize_feature_payload("clients", {"addmdevice": [row]})

    item = normalized["clients"]["items"][0]
    assert item["source_kind"] == "addmdevice"
    assert item["source_row_id"] == "row-1"
    assert item["managed_form_supported"] is True
    assert item["fixed_dhcp"] is False
    assert item["uses_dhcp"] is True
    assert item["uses_rule"] == 0
    assert "mdevice_reservedip" not in item
    assert "mdevice_originalip" not in item

    ambiguous = normalize_feature_payload(
        "clients",
        {
            "addmdevice": [row],
            "addmlandevice": [
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"mdevice_wifi", "mdevice_upspeed", "mdevice_rssi"}
                }
            ],
        },
    )["clients"]["items"][0]
    assert "source_kind" not in ambiguous
    assert "source_row_id" not in ambiguous
    assert "managed_form_supported" not in ambiguous
    assert "fixed_dhcp" not in ambiguous

    incomplete = _managed_device_row()
    incomplete.pop("mdevice_reservedip")
    incomplete_item = normalize_feature_payload(
        "clients", {"addmdevice": [incomplete]}
    )["clients"]["items"][0]
    assert "managed_form_supported" not in incomplete_item


def test_telephone_line_never_uses_a_phone_number_as_registry_identity() -> None:
    """Phone-like row IDs are dropped while a separate opaque UUID is accepted."""
    unsafe = normalize_feature_payload(
        "telephony",
        {"addnumber": [{"id": "+49 30 123456", "registered": "1"}]},
    )
    assert "numbers" not in unsafe["telephony"]
    assert unsafe["telephony"]["registered_number_count"] == 1

    safe = normalize_feature_payload(
        "telephony",
        {
            "addnumber": [
                {
                    "id": "+49 30 123456",
                    "uuid": "line-a2f0c7",
                    "registered": "1",
                }
            ]
        },
    )
    assert safe["telephony"]["numbers"][0]["id"] == "line-a2f0c7"


@pytest.mark.asyncio
async def test_busy_fault_retries_with_same_serial_owner() -> None:
    """9801 SOAP fault retries without escaping request lock."""
    session = _FakeSession()
    session.add(_busy_fault(), status=500)
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "5", "unsignedInt"))
    )
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=1,
    )

    values = await client.get_parameter_values(("Device.IP.InterfaceNumberOfEntries",))

    assert values["Device.IP.InterfaceNumberOfEntries"].value == 5
    assert len(session.requests) == 2
    assert all(
        request[1] == "http://speedport.ip:5438/" for request in session.requests
    )


@pytest.mark.asyncio
async def test_runtime_wan_read_can_surface_first_busy_fault() -> None:
    """Adaptive polling observes the first 9801 instead of an internal retry burst."""
    session = _FakeSession()
    session.add(_busy_fault(), status=500)
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=4,
    )
    client._wan_interface = WanInterface(  # noqa: SLF001
        index=5,
        alias="BONDING",
        name="habond",
        status="Up",
    )

    with pytest.raises(SpeedportSessionBusyError):
        await client.get_wan_counters(busy_retries=0)

    assert len(session.requests) == 1


@pytest.mark.asyncio
async def test_runtime_wan_read_surfaces_busy_during_cold_interface_count() -> None:
    """A cold-cache count probe exposes its first 9801 to the scheduler."""
    session = _FakeSession()
    session.add(_busy_fault(), status=500)
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=4,
    )

    with pytest.raises(SpeedportSessionBusyError):
        await client.get_wan_counters(busy_retries=0)

    assert len(session.requests) == 1


@pytest.mark.asyncio
async def test_runtime_wan_read_surfaces_busy_during_cold_interface_details() -> None:
    """A cold-cache detail probe exposes its first 9801 to the scheduler."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(_busy_fault(), status=500)
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=4,
    )

    with pytest.raises(SpeedportSessionBusyError):
        await client.get_wan_counters(busy_retries=0)

    assert len(session.requests) == 2


@pytest.mark.asyncio
async def test_wan_read_uses_default_busy_retry_policy_when_omitted() -> None:
    """WAN callers retain constructor retry behavior unless they override it."""
    session = _FakeSession()
    session.add(_busy_fault(), status=500)
    session.add(
        _soap_response(
            ("Device.IP.Interface.5.Stats.BytesReceived", "1100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "950", "unsignedLong"),
        )
    )
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        busy_backoff=0,
        max_busy_retries=1,
    )
    client._wan_interface = WanInterface(  # noqa: SLF001
        index=5,
        alias="BONDING",
        name="habond",
        status="Up",
    )

    counters = await client.get_wan_counters()

    assert counters.bytes_received == 1100
    assert counters.bytes_sent == 950
    assert len(session.requests) == 2


@pytest.mark.asyncio
async def test_dynamic_interface_discovery_selects_bonding() -> None:
    """Interface count drives enumeration and Hybrid aggregate selection."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "5", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.4.Alias", "TUNNEL_LTE", "string"),
            ("Device.IP.Interface.4.Name", "lte0", "string"),
            ("Device.IP.Interface.4.Status", "Up", "string"),
            ("Device.IP.Interface.4.Stats.BytesReceived", "400", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.BytesSent", "300", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.PacketsReceived", "40", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.PacketsSent", "30", "unsignedLong"),
            ("Device.IP.Interface.4.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.4.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.4.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.4.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
            ("Device.IP.Interface.5.Alias", "BONDING", "string"),
            ("Device.IP.Interface.5.Name", "habond", "string"),
            ("Device.IP.Interface.5.Status", "Up", "string"),
            ("Device.IP.Interface.5.Stats.BytesReceived", "1000", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "900", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "90", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "2", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "3", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "4",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "5",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.5.Stats.BytesReceived", "1100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "950", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "110", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "95", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "3", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "4", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "5",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "6",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.5.Stats.BytesReceived", "1200", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.BytesSent", "1000", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsReceived", "120", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.PacketsSent", "100", "unsignedLong"),
            ("Device.IP.Interface.5.Stats.ErrorsReceived", "4", "unsignedInt"),
            ("Device.IP.Interface.5.Stats.ErrorsSent", "5", "unsignedInt"),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsReceived",
                "6",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.5.Stats.DiscardPacketsSent",
                "7",
                "unsignedInt",
            ),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    counters = await client.get_wan_counters()

    assert counters.interface.alias == "BONDING"
    assert counters.bytes_received == 1_100
    assert counters.bytes_sent == 950
    assert counters.packets_received == 110
    assert counters.packets_sent == 95
    assert counters.errors_received == 3
    assert counters.errors_sent == 4
    assert counters.discard_packets_received == 5
    assert counters.discard_packets_sent == 6
    second_request_body = session.requests[1][2]["data"]
    assert "Device.IP.Interface.5.Stats.BytesReceived" in second_request_body
    assert "Device.IP.Interface.5.Stats.PacketsReceived" not in second_request_body
    counter_request_body = session.requests[2][2]["data"]
    assert "Device.IP.Interface.5.Stats.PacketsReceived" in counter_request_body
    assert "Device.IP.Interface.5.Stats.DiscardPacketsSent" in counter_request_body

    next_counters = await client.get_wan_counters()

    assert next_counters.bytes_received == 1_200
    assert next_counters.packets_received == 120
    assert next_counters.errors_sent == 5
    assert next_counters.discard_packets_sent == 7
    assert len(session.requests) == 4
    assert "InterfaceNumberOfEntries" not in session.requests[3][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[3][2]["data"]
    assert "Stats.DiscardPacketsSent" in session.requests[3][2]["data"]


@pytest.mark.asyncio
async def test_discovery_falls_back_when_optional_counters_fault() -> None:
    """Unsupported optional counters cannot hide usable WAN byte counters."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
        )
    )
    session.add(_unsupported_parameter_fault(), status=500)
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    counters = await client.get_wan_counters()

    assert counters.bytes_received == 100
    assert counters.bytes_sent == 50
    assert counters.packets_received is None
    assert len(session.requests) == 4
    assert "Stats.PacketsReceived" not in session.requests[1][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[2][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[3][2]["data"]
    assert "Stats.BytesReceived" in session.requests[3][2]["data"]


@pytest.mark.asyncio
async def test_cached_counter_poll_remembers_optional_counter_fault() -> None:
    """Fast poll retries bytes together, then skips unsupported optional names."""
    session = _FakeSession()
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "100", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "50", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsSent", "5", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.1.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "110", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "55", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsReceived", "11", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.PacketsSent", "6", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.ErrorsReceived", "1", "unsignedInt"),
            ("Device.IP.Interface.1.Stats.ErrorsSent", "2", "unsignedInt"),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsReceived",
                "3",
                "unsignedInt",
            ),
            (
                "Device.IP.Interface.1.Stats.DiscardPacketsSent",
                "4",
                "unsignedInt",
            ),
        )
    )
    session.add(_unsupported_parameter_fault(), status=500)
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "120", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "60", "unsignedLong"),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "140", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "70", "unsignedLong"),
        )
    )
    client = SpeedportClient(session, "speedport.ip")  # type: ignore[arg-type]

    first = await client.get_wan_counters()
    second = await client.get_wan_counters()
    third = await client.get_wan_counters()

    assert first.packets_received == 11
    assert second.bytes_received == 120
    assert second.packets_received is None
    assert third.bytes_received == 140
    assert len(session.requests) == 6
    assert "Stats.PacketsReceived" in session.requests[2][2]["data"]
    assert "Stats.PacketsReceived" in session.requests[3][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[4][2]["data"]
    assert "Stats.PacketsReceived" not in session.requests[5][2]["data"]
    assert session.requests[5][2]["data"].count("<xsd:string>") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proof_response_key", "protected_response_key"),
    [("default", "challenge"), ("challenge", "default")],
)
async def test_modern_login_and_authenticated_decode(
    proof_response_key: str, protected_response_key: str
) -> None:
    """One challenge-framed proof opens a session with response-key fallback."""
    session = _FakeSession()
    challenge = "00" * 32
    challenge_key = bytes.fromhex(challenge)
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(
        encode_payload(
            '{"login":"success"}',
            challenge if proof_response_key == "challenge" else DEFAULT_KEY,
        )
    )
    session.add(
        encode_payload(
            '{"secure":"value"}',
            challenge if protected_response_key == "challenge" else DEFAULT_KEY,
        )
    )
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    result = await client.get_json("data/SecureStatus.json", authenticated=True)

    assert result == {"secure": "value"}
    assert client.is_authenticated
    login_posts = [
        request
        for request in session.requests
        if request[0] == "POST" and request[1].endswith("/data/Login.json")
    ]
    assert len(login_posts) == 2
    challenge_request, proof_request = login_posts
    assert challenge_request[0] == "POST"
    assert proof_request[0] == "POST"
    assert _decode_form(challenge_request[2]["data"], DEFAULT_KEY) == {
        "getChallenge": "1"
    }
    proof_form = _decode_form(proof_request[2]["data"], challenge_key)
    assert proof_form["showpw"] == "0"
    assert len(proof_form["password"]) == 64
    proof_plaintext = (
        AESCCM(challenge_key, tag_length=16)
        .decrypt(challenge_key[:8], bytes.fromhex(proof_request[2]["data"]), None)
        .decode()
    )
    assert proof_plaintext.startswith("showpw=0&password=")
    assert "Referer" not in challenge_request[2]["headers"]
    assert "Referer" not in proof_request[2]["headers"]


@pytest.mark.asyncio
async def test_authenticated_decode_failure_is_released_on_close() -> None:
    """Losing protected decode state retains only enough ownership to log out."""
    session = _FakeSession()
    challenge = "22" * 32
    unknown_key = "33" * 32
    session.add(encode_payload('{"device_name":"Speedport Smart 4"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"success"}'))
    session.add(encode_payload('{"secure":"value"}', unknown_key))
    session.add("<script>var _httoken = 123456;</script>")
    session.add(encode_payload('{"status":"ok"}', challenge))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    with pytest.raises(SpeedportAuthenticationError):
        await client.get_json("data/SecureStatus.json", authenticated=True)
    assert not client.is_authenticated

    await client.close()

    logout_request = session.requests[-1]
    assert logout_request[0] == "POST"
    assert logout_request[1].endswith("/data/Login.json")
    assert _decode_form(logout_request[2]["data"], challenge) == {
        "httoken": "123456",
        "logout": "byby",
    }


@pytest.mark.asyncio
async def test_ambiguous_proof_response_is_released_on_close() -> None:
    """A submitted proof retains tentative ownership until cleanup is attempted."""
    session = _FakeSession()
    challenge = "44" * 32
    unknown_key = "55" * 32
    session.add(encode_payload('{"device_name":"Speedport Smart 4"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"success"}', unknown_key))
    session.add("<script>var _httoken = 654321;</script>")
    session.add(encode_payload('{"status":"ok"}', challenge))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    with pytest.raises(SpeedportProtocolError):
        await client.login()

    await client.close()

    logout_request = session.requests[-1]
    assert logout_request[0] == "POST"
    assert _decode_form(logout_request[2]["data"], challenge) == {
        "httoken": "654321",
        "logout": "byby",
    }


@pytest.mark.asyncio
async def test_rejected_login_raises_typed_error() -> None:
    """Wrong password cannot degrade into empty feature data."""
    session = _FakeSession()
    challenge = "11" * 32
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"failed"}'))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="wrong",  # noqa: S106
    )

    with pytest.raises(SpeedportAuthenticationError):
        await client.get_json("data/SecureStatus.json", authenticated=True)

    assert not client.is_authenticated
    await client.close()
    assert len(session.requests) == 3


@pytest.mark.asyncio
async def test_close_without_proof_never_sends_blind_logout() -> None:
    """A client that never submitted proof has no authority to end a session."""
    session = _FakeSession()
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    await client.close()

    assert session.requests == []


@pytest.mark.asyncio
async def test_rejected_owned_logout_never_falls_back_to_public_key() -> None:
    """Cleanup retries remain bound to the router-issued session key."""
    session = _FakeSession()
    challenge = "66" * 32
    challenge_key = bytes.fromhex(challenge)
    session.add(encode_payload('{"device_name":"Speedport Smart 4"}'))
    session.add(encode_payload(f'{{"challenge":"{challenge}"}}'))
    session.add(encode_payload('{"login":"success"}', challenge_key))
    session.add("<script>var _httoken = 123456;</script>")
    session.add(encode_payload('{"status":"failed"}', challenge_key))
    session.add(encode_payload('{"status":"failed"}', challenge_key))
    session.add(encode_payload('{"status":"ok"}', DEFAULT_KEY))
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        password="router-password",  # noqa: S106
    )

    await client.login()
    cleanup_start = len(session.requests)
    await client.close()

    cleanup_posts = [
        request
        for request in session.requests[cleanup_start:]
        if request[0] == "POST" and request[1].endswith("/data/Login.json")
    ]
    assert len(cleanup_posts) == 2
    assert all(
        _decode_form(request[2]["data"], challenge_key)["logout"] == "byby"
        for request in cleanup_posts
    )


@pytest.mark.parametrize(
    ("family", "endpoint", "referer"),
    [
        (
            "wifi_configuration",
            "data/WLANBasicAss.json",
            "html/content/network/wlan_name_enc.html",
        ),
        (
            "wifi_schedule",
            "data/WLANBasic.json",
            "html/content/network/wlan_basic.html",
        ),
        ("lan", "data/LAN.json", "html/content/network/lan.html"),
        (
            "clients",
            "data/DeviceList.json",
            "html/content/network/devices.html",
        ),
        (
            "ip",
            "data/IPData.json",
            "html/content/internet/con_ipdata.html",
        ),
        (
            "connection_privacy",
            "data/IPPrivacy.json",
            "html/content/internet/con_privacy.html",
        ),
        ("system", "data/Router.json", "html/content/index.html"),
        (
            "ip_phones",
            "data/IPPhoneHandler.json",
            "html/content/phone/phone_internet.html",
        ),
        (
            "wifi_access",
            "data/WLANAccess.json",
            "html/content/network/wlan_access.html",
        ),
        (
            "wifi_environment",
            "data/WLANEnviron.json",
            "html/content/network/wlan_environ.html",
        ),
        (
            "port_forwarding",
            "data/PortuwMain.json",
            "html/content/internet/portforwarding.html",
        ),
        ("mobile", "data/LTE.json", "html/content/internet/lte_mode.html"),
        ("lte", "data/LTE.json", "html/content/internet/lte_mode.html"),
        ("5g", "data/LTE.json", "html/content/internet/lte_mode.html"),
        ("receiver", "data/LTE.json", "html/content/internet/lte_mode.html"),
        (
            "mesh",
            "data/SecureStatus.json",
            "html/content/overview/index.html",
        ),
        (
            "mesh_firmware",
            "data/FirmwareUpdateMesh.json",
            "html/content/config/check_for_updates_mesh.html",
        ),
        (
            "mesh_update",
            "data/FwCheckForUpdateMesh.json",
            "html/content/overview/index.html",
        ),
        (
            "mesh_reboot_status",
            "data/RebootMesh.json",
            "html/content/config/problem_handling_mesh.html",
        ),
        ("dhcp", "data/LAN.json", "html/content/network/dhcp.html"),
        (
            "nat",
            "data/PortuwMain.json",
            "html/content/internet/portforwarding.html",
        ),
        (
            "port_blocking",
            "data/ExtendedRules.json",
            "html/content/internet/portblocking.html",
        ),
        (
            "ddns",
            "data/DynDNS.json",
            "html/content/internet/dyn_dns.html",
        ),
        ("pbx", "data/IPPBX.json", "html/content/phone/phone_ippbx.html"),
        (
            "dect",
            "data/DECTStation.json",
            "html/content/phone/phone_dect_mobiles.html",
        ),
        (
            "dect_settings",
            "data/DECTSettings.json",
            "html/content/config/problem_handling_dect.html",
        ),
        (
            "dect_repeater",
            "data/DECTRepeater.json",
            "html/content/phone/phone_dect_repeater.html",
        ),
        (
            "vpn_details",
            "data/VPN.json",
            "html/content/internet/vpn.html",
        ),
        (
            "analog",
            "data/PhonePlugs.json",
            "html/content/phone/phone_analog.html",
        ),
        (
            "phonebook",
            "data/PhoneBook.json",
            "html/content/phone/phone_book.html",
        ),
        (
            "dns_rebind",
            "data/DNSExcept.json",
            "html/content/network/dns_rebind.html",
        ),
        ("qos", "data/QOS.json", "html/content/network/qos.html"),
        (
            "usb",
            "data/NASDevice.json",
            "html/content/network/nas_overview.html",
        ),
        (
            "media_server",
            "data/NASMediacenter.json",
            "html/content/network/nas_mediacenter.html",
        ),
        (
            "usb_tethering",
            "data/INetTeth.json",
            "html/content/internet/usb_tethering.html",
        ),
        (
            "nas",
            "data/NASDevice.json",
            "html/content/network/nas_overview.html",
        ),
        (
            "easy_support",
            "data/EasySupport.json",
            "html/content/config/easy_support.html",
        ),
        (
            "system_services",
            "data/ActiveServices.json",
            "html/content/config/system_services.html",
        ),
        ("energy", "data/Energy.json", "html/content/config/energy.html"),
        (
            "firmware",
            "data/FirmwareUpdate.json",
            "html/content/config/check_for_updates.html",
        ),
    ],
)
def test_speedport_smart_4r_candidates_prefer_proven_firmware_routes(
    family: str, endpoint: str, referer: str
) -> None:
    """Live read-only discovery routes are tried before firmware aliases."""
    candidate = DEFAULT_FEATURE_CANDIDATES[family][0]

    assert candidate.endpoint == endpoint
    assert candidate.referer == referer
    assert candidate.authenticated is True


@pytest.mark.parametrize(
    ("family", "endpoint"),
    [
        ("wifi_configuration", "data/WLANSettings.json"),
        ("clients", "data/HomeNetwork.json"),
        ("mobile", "data/WebnWalk.json"),
        ("lte", "data/WebnWalk.json"),
        ("5g", "data/WebnWalk.json"),
        ("mesh", "data/Mesh.json"),
        ("nat", "data/Portforwarding.json"),
        ("ddns", "data/DDNS.json"),
        ("vpn", "data/WireGuard.json"),
        ("vpn", "data/Wireguard.json"),
        ("vpn_details", "data/WireGuard.json"),
        ("vpn_details", "data/Wireguard.json"),
        ("pbx", "data/PhoneSettings.json"),
        ("dect", "data/PhoneSettings.json"),
        ("usb", "data/NASMediacenter.json"),
        ("firmware", "data/Update.json"),
    ],
)
def test_documented_cross_firmware_aliases_are_never_primary(
    family: str, endpoint: str
) -> None:
    """Documented aliases remain fallback-only after target-firmware discovery."""
    endpoints = tuple(
        candidate.endpoint for candidate in DEFAULT_FEATURE_CANDIDATES[family]
    )

    assert endpoint in endpoints[1:]


def test_detail_endpoint_families_poll_beyond_summary_evidence() -> None:
    """A confirmed summary endpoint cannot shadow independent detail reads."""
    assert DEFAULT_FEATURE_CANDIDATES["wifi"][0].endpoint == "data/SecureStatus.json"
    assert (
        DEFAULT_FEATURE_CANDIDATES["wifi_schedule"][0].endpoint == "data/WLANBasic.json"
    )
    assert DEFAULT_FEATURE_CANDIDATES["vpn"][0].endpoint == "data/SecureStatus.json"
    assert DEFAULT_FEATURE_CANDIDATES["vpn_details"][0].endpoint == "data/VPN.json"
    assert (
        DEFAULT_FEATURE_CANDIDATES["mesh_topology"][0].endpoint
        == "data/DeviceList.json"
    )
    assert DEFAULT_FEATURE_CANDIDATES["dect"][0].endpoint == "data/DECTStation.json"
    assert DEFAULT_FEATURE_CANDIDATES["dect_status"][0].endpoint == "data/DECTInfo.json"
    assert (
        DEFAULT_FEATURE_CANDIDATES["dect_repeater"][0].endpoint
        == "data/DECTRepeater.json"
    )
    assert DEFAULT_FEATURE_CANDIDATES["usb"][0].endpoint == "data/NASDevice.json"
    assert (
        DEFAULT_FEATURE_CANDIDATES["media_server"][0].endpoint
        == "data/NASMediacenter.json"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("detail_result", ["success", "empty", "unsupported"])
async def test_probe_keeps_summary_and_independent_detail_families(
    detail_result: str,
) -> None:
    """Capability probing evaluates detail evidence after summary confirmation."""
    overview = "html/content/overview/index.html"
    candidates = {
        "wifi": (
            EndpointCapability(
                "wifi",
                "data/SecureStatus.json",
                authenticated=True,
                referer=overview,
                evidence_keys=("wlan_active",),
            ),
        ),
        "wifi_schedule": (
            EndpointCapability(
                "wifi_schedule",
                "data/WLANBasic.json",
                authenticated=True,
                referer="html/content/network/wlan_basic.html",
                evidence_keys=("wlan_timerule",),
            ),
        ),
        "vpn": (
            EndpointCapability(
                "vpn",
                "data/SecureStatus.json",
                authenticated=True,
                referer=overview,
                evidence_keys=("vpn_active",),
            ),
        ),
        "vpn_details": (
            EndpointCapability(
                "vpn_details",
                "data/VPN.json",
                authenticated=True,
                referer="html/content/internet/vpn.html",
                evidence_keys=("addpeer",),
            ),
        ),
        "dect": (
            EndpointCapability(
                "dect",
                "data/DECTStation.json",
                authenticated=True,
                referer="html/content/phone/phone_dect_mobiles.html",
                evidence_keys=("use_dect",),
            ),
        ),
        "dect_repeater": (
            EndpointCapability(
                "dect_repeater",
                "data/DECTRepeater.json",
                authenticated=True,
                referer="html/content/phone/phone_dect_repeater.html",
                evidence_keys=("addrepeater",),
            ),
        ),
        "usb": (
            EndpointCapability(
                "usb",
                "data/NASDevice.json",
                authenticated=True,
                referer="html/content/network/nas_overview.html",
                evidence_keys=("addnasdevice",),
            ),
        ),
        "media_server": (
            EndpointCapability(
                "media_server",
                "data/NASMediacenter.json",
                authenticated=True,
                referer="html/content/network/nas_mediacenter.html",
                evidence_keys=("addnasmediareplay",),
            ),
        ),
    }
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates=candidates,
    )
    client._last_status = RouterStatus(  # noqa: SLF001 - non-network probe fixture
        info=RouterInfo(model="Speedport Smart 4R")
    )

    async def feature_payload(endpoint: str, **_: object) -> dict[str, object]:
        base_payloads: dict[str, dict[str, object]] = {
            "data/SecureStatus.json": {
                "wlan_active": "1",
                "vpn_active": "1",
            },
            "data/DECTStation.json": {"use_dect": "1"},
            "data/NASDevice.json": {"addnasdevice": [{"id": "usb-1"}]},
        }
        if endpoint in base_payloads:
            return base_payloads[endpoint]
        if detail_result == "unsupported":
            raise SpeedportUnsupportedError("detail endpoint unavailable")
        if detail_result == "empty":
            return {}
        return {
            "data/WLANBasic.json": {"wlan_timerule": "1"},
            "data/VPN.json": {"addpeer": [{"connected": "1"}]},
            "data/DECTRepeater.json": {"addrepeater": [{"id": "1"}]},
            "data/NASMediacenter.json": {
                "addnasmediareplay": [{"mediareplay_active": "1"}]
            },
        }[endpoint]

    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(client, "get_json", AsyncMock(side_effect=feature_payload)) as get,
    ):
        report = await client.probe_capabilities()

    summary_families = {"status", "wifi", "vpn", "dect", "usb"}
    detail_families = {
        "wifi_schedule",
        "vpn_details",
        "dect_repeater",
        "media_server",
    }
    assert summary_families <= set(report.feature_endpoints)
    if detail_result == "success":
        assert detail_families <= set(report.feature_endpoints)
    else:
        assert detail_families.isdisjoint(report.feature_endpoints)
        assert detail_families <= set(report.failures)
    assert report.authenticated_json is True
    assert get.await_count == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("family", "payload"),
    [
        ("wifi_schedule", {"wlan_time_active": "1"}),
        ("dect_repeater", {"use_dect": "1"}),
        ("media_server", {"use_usb": "1"}),
    ],
)
async def test_probe_rejects_detail_evidence_the_normalizer_does_not_consume(
    family: str,
    payload: dict[str, object],
) -> None:
    """Detail capability evidence must prove at least one owned output field."""
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates={family: (DEFAULT_FEATURE_CANDIDATES[family][0],)},
    )
    client._last_status = RouterStatus(  # noqa: SLF001 - non-network probe fixture
        info=RouterInfo(model="Speedport Smart 4R")
    )

    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(client, "get_json", AsyncMock(return_value=payload)),
    ):
        report = await client.probe_capabilities()

    assert family not in report.feature_endpoints
    assert family in report.failures


@pytest.mark.asyncio
async def test_probe_records_only_safe_successful_candidate_schemas() -> None:
    """Probe diagnostics retain successful structures, never values or failures."""
    candidates = {
        "energy": (
            EndpointCapability(
                "energy",
                "data/EnergyPreview.json",
                authenticated=True,
                referer="html/content/config/energy.html",
                evidence_keys=("power",),
            ),
            EndpointCapability(
                "energy",
                "data/Energy.json",
                authenticated=True,
                referer="html/content/config/energy.html",
                evidence_keys=("energy",),
            ),
            EndpointCapability(
                "energy",
                "data/EnergyUnused.json",
                authenticated=True,
                referer="html/content/config/energy.html",
                evidence_keys=("energy",),
            ),
        ),
        "logs": (
            EndpointCapability(
                "logs",
                "data/SystemMessages.json",
                authenticated=True,
                referer="html/content/config/system_messages.html",
                evidence_keys=("message",),
            ),
        ),
        "unsafe_metadata": (
            EndpointCapability(
                "unsafe_metadata",
                "data/aabbccddeeff.json",
                authenticated=True,
                referer="html/content/config/energy.html",
                evidence_keys=("energy",),
            ),
        ),
    }
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates=candidates,
    )
    client._last_status = RouterStatus(  # noqa: SLF001 - non-network probe fixture
        info=RouterInfo(model="Speedport Smart 4R")
    )

    async def feature_payload(endpoint: str, **_: object) -> dict[str, object]:
        if endpoint == "data/EnergyPreview.json":
            return {
                "status": "private-value",
                "rows": [
                    {
                        "enabled": True,
                        "hostname": "private-client",
                        "aa:bb:cc:dd:ee:ff": "private-mac-key",
                    }
                ],
                "router_password": "private-password",
            }
        if endpoint == "data/Energy.json":
            return {
                "energy": {"enabled": True, "id": "private-identifier"},
                "serial_number": "private-serial",
            }
        if endpoint == "data/SystemMessages.json":
            raise SpeedportUnsupportedError("endpoint unavailable")
        if endpoint == "data/aabbccddeeff.json":
            return {"energy": True}
        raise AssertionError(f"Unexpected candidate read: {endpoint}")

    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(client, "get_json", AsyncMock(side_effect=feature_payload)) as get,
    ):
        report = await client.probe_capabilities()

    snapshot = client.observed_candidate_schema
    assert "energy" in report.feature_endpoints
    assert "logs" in report.failures
    assert tuple(snapshot) == ("energy",)
    assert get.await_count == 4
    assert "data/EnergyUnused.json" not in {
        call_args.args[0] for call_args in get.await_args_list
    }
    assert [candidate["endpoint"] for candidate in snapshot["energy"]] == [
        "data/EnergyPreview.json",
        "data/Energy.json",
    ]
    assert snapshot["energy"][0]["referer"] == "html/content/config/energy.html"
    assert snapshot["energy"][0]["authenticated"] is True
    assert {
        (descriptor["path"], descriptor["shape"])
        for descriptor in snapshot["energy"][0]["schema"]  # type: ignore[union-attr]
    } == {
        ("status", "string"),
        ("rows", "array"),
        ("rows[]", "object"),
        ("rows[].enabled", "boolean"),
    }
    assert {
        (descriptor["path"], descriptor["shape"])
        for descriptor in snapshot["energy"][1]["schema"]  # type: ignore[union-attr]
    } == {
        ("energy", "object"),
        ("energy.enabled", "boolean"),
    }
    rendered = repr(snapshot)
    for forbidden in (
        "private-value",
        "private-client",
        "private-mac-key",
        "private-password",
        "private-identifier",
        "private-serial",
        "hostname",
        "router_password",
        "serial_number",
        "aa:bb:cc:dd:ee:ff",
        "data/SystemMessages.json",
        "data/EnergyUnused.json",
        "data/aabbccddeeff.json",
    ):
        assert forbidden not in rendered

    with pytest.raises(TypeError):
        snapshot["energy"][0]["endpoint"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot["energy"][0]["schema"][0]["path"] = "changed"  # type: ignore[index]


@pytest.mark.asyncio
async def test_probe_replaces_candidate_schema_snapshot() -> None:
    """A repeated probe must not retain fields absent from the latest response."""
    candidate = EndpointCapability(
        "energy",
        "data/Energy.json",
        authenticated=True,
        referer="html/content/config/energy.html",
        evidence_keys=("energy",),
    )
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates={"energy": (candidate,)},
    )
    client._last_status = RouterStatus(  # noqa: SLF001 - non-network probe fixture
        info=RouterInfo(model="Speedport Smart 4R")
    )
    client._observe_candidate_data(  # noqa: SLF001 - seed the previous probe
        "energy",
        candidate,
        {"energy": {"enabled": True}},
    )
    first = client.observed_candidate_schema

    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(
            client,
            "get_json",
            AsyncMock(return_value={"energy": {"available": True}}),
        ),
    ):
        await client.probe_capabilities()
        second = client.observed_candidate_schema

    assert {
        descriptor["path"]
        for descriptor in first["energy"][0]["schema"]  # type: ignore[union-attr]
    } == {"energy", "energy.enabled"}
    assert {
        descriptor["path"]
        for descriptor in second["energy"][0]["schema"]  # type: ignore[union-attr]
    } == {"energy", "energy.available"}


@pytest.mark.asyncio
async def test_probe_receiver_accepts_exact_flat_status_evidence() -> None:
    """Receiver fields cannot normalize into a capability-hidden data root."""
    referer = "html/content/internet/lte_mode.html"
    candidates = {
        family: (
            EndpointCapability(
                family,
                "data/LTE.json",
                authenticated=True,
                referer=referer,
                evidence_keys=DEFAULT_FEATURE_CANDIDATES[family][0].evidence_keys,
            ),
        )
        for family in ("mobile", "receiver")
    }
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates=candidates,
    )
    client._last_status = RouterStatus(  # noqa: SLF001 - non-network probe fixture
        info=RouterInfo(model="Speedport Smart 4R")
    )
    payload = {
        "auto_external_modem": "1",
        "extwan_typ": "3",
        "use_lte": "1",
        "auto_update": "1",
    }

    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(client, "get_json", AsyncMock(return_value=payload)) as get,
    ):
        report = await client.probe_capabilities()

    assert {"mobile", "receiver"} <= set(report.feature_endpoints)
    assert get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint_body", "expected_families"),
    [
        ("{}", ("status",)),
        ('{"internet_state":"online"}', ("status", "internet")),
    ],
)
async def test_capability_requires_matching_nonempty_data(
    endpoint_body: str, expected_families: tuple[str, ...]
) -> None:
    """Reachable empty or unrelated endpoints never create entities."""
    session = _FakeSession()
    session.add(encode_payload('{"device_name":"Speedport Smart 4R"}'))
    session.add(
        _soap_response(("Device.IP.InterfaceNumberOfEntries", "1", "unsignedInt"))
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Alias", "WAN", "string"),
            ("Device.IP.Interface.1.Status", "Up", "string"),
            ("Device.IP.Interface.1.Stats.BytesReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "5", "unsignedLong"),
        )
    )
    session.add(
        _soap_response(
            ("Device.IP.Interface.1.Stats.BytesReceived", "10", "unsignedLong"),
            ("Device.IP.Interface.1.Stats.BytesSent", "5", "unsignedLong"),
        )
    )
    session.add(endpoint_body)
    client = SpeedportClient(  # type: ignore[arg-type]
        session,
        "speedport.ip",
        endpoint_candidates={
            "internet": (
                EndpointCapability(
                    "internet",
                    "data/Test.json",
                    evidence_keys=("internet",),
                ),
            )
        },
    )
    await client.get_status()

    report = await client.probe_capabilities()

    assert tuple(report.feature_endpoints) == expected_families


@pytest.mark.asyncio
async def test_protected_decode_failure_keeps_public_report() -> None:
    """A protected response failure never discards a usable public report."""
    client = SpeedportClient(  # type: ignore[arg-type]
        _FakeSession(),
        "speedport.ip",
        password="router-password",  # noqa: S106
        endpoint_candidates={
            "wifi": (
                EndpointCapability(
                    "wifi",
                    "data/WLAN.json",
                    authenticated=True,
                    evidence_keys=("wifi",),
                ),
            )
        },
    )
    client._last_status = MagicMock()  # noqa: SLF001 - probe fixture
    with (
        patch.object(client, "logout", AsyncMock()),
        patch.object(
            client, "get_wan_counters", AsyncMock(side_effect=SpeedportUnsupportedError)
        ),
        patch.object(client, "login", AsyncMock()),
        patch.object(
            client,
            "get_json",
            AsyncMock(
                side_effect=SpeedportAuthenticationError("protected decode failed")
            ),
        ),
    ):
        report = await client.probe_capabilities(allow_protected_degraded=True)

    assert report.status_json is True
    assert report.authenticated_json is False
    assert "status" in report.feature_endpoints
    assert "wifi" not in report.feature_endpoints
    assert "authentication" in report.failures
    assert isinstance(client.last_management_error, SpeedportAuthenticationError)
