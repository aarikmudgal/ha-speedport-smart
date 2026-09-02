"""Exact existing VPN peer controls with secret-safe state proof; no network I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    normalize_configuration_payload,
)
from .configuration_rule_devices import rule_id, rule_rows

if TYPE_CHECKING:
    from .configuration import SettingValues

_ENDPOINT: Final = "data/VPN.json"
_REFERER: Final = "html/content/network/vpn.html"
_COLLECTION: Final = "addvpn"
_MAX_PEERS: Final = 5
_MAX_CHARACTER: Final = 255
_FIRST_PRINTABLE: Final = 32
_MAX_PRIVATE_TEXT: Final = 16384
_NAME: Final = SettingsField("vpn_name", "Peer name", "text", minimum=1, maximum=20)
_ACTIVE: Final = boolean("vpn_status", "Enable this VPN peer")
_DELETE: Final = boolean("delete_entry", "Delete this exact VPN peer")
_ROTATE: Final = boolean("rotate_key", "Replace the shared key for every IPsec peer")
_KEY: Final = SettingsField(
    "vpn_key", "IPsec shared key", "secret", minimum=1, maximum=_MAX_PRIVATE_TEXT
)
_PRIVATE_PEER_FIELDS: Final = ("vpn_username", "vpn_password", "vpn_ipsec_qrcode")
_CREATE_NAME: Final = SettingsField("vpn_name", "New peer name", "text", maximum=20)
_PASSWORD: Final = SettingsField(
    "vpn_password",
    "New IPsec password (IPsec mode only)",
    "secret",
    minimum=12,
    maximum=32,
    description=(
        "Leave untouched for WireGuard. Existing IPsec mode requires 12-32 allowed "
        "characters and three of uppercase, lowercase, digits and special characters."
    ),
)
_PASSWORD_CHARACTERS: Final = re.compile(r'[0-9a-zA-Z!"§$%&/()=*+#,;.:_-]{12,32}')
_PASSWORD_CLASSES: Final = (r"[0-9]", r"[a-z]", r"[A-Z]", r"[!§$%&/()=*+#,;.:_-]")
_MIN_PASSWORD_CLASSES: Final = 3
_WIREGUARD_FIELDS: Final = {
    "Interface": frozenset({"PrivateKey", "Address", "DNS", "ListenPort", "MTU"}),
    "Peer": frozenset(
        {"PublicKey", "PresharedKey", "AllowedIPs", "Endpoint", "PersistentKeepalive"}
    ),
}
_WARNING: Final = (
    "Changing or deleting this VPN peer can terminate its remote connection. "
    "Use a local connection if this peer provides your current router access. "
    "Other peers and their credentials are preserved."
)


@dataclass(frozen=True, slots=True)
class VpnTargetSpec:
    """Expose only the proven existing-peer actions, never arbitrary VPN requests."""

    id: str
    title: str
    endpoint: str
    referer: str
    collection: str
    label_key: str
    fields: tuple[SettingsField, ...]


@dataclass(frozen=True, slots=True, repr=False)
class VpnCredentials:
    """One-request secret download; callers must not log, cache or persist it."""

    peer_id: str
    mode: str
    filename: str
    media_type: str
    content: str


VPN_TARGET_SPECS: Final = MappingProxyType(
    {
        "vpn_peer_enabled": VpnTargetSpec(
            "vpn_peer_enabled",
            "Enable or disable VPN peer",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "vpn_name",
            (_ACTIVE,),
        ),
        "vpn_peer_delete": VpnTargetSpec(
            "vpn_peer_delete",
            "Delete VPN peer",
            _ENDPOINT,
            _REFERER,
            _COLLECTION,
            "vpn_name",
            (_DELETE,),
        ),
    }
)


def _mode(raw: SettingValues) -> str:
    value = raw.get("vpn_typ")
    if type(value) is not str or value not in {"0", "1"}:
        raise ConfigurationError("unsupported_vpn_mode")
    return value


def _private_text(value: object) -> str:
    if type(value) is not str or len(value) > _MAX_PRIVATE_TEXT or "\x00" in value:
        raise ConfigurationError("invalid_vpn_state")
    return value


def _peers(raw: SettingValues) -> dict[str, dict[str, Any]]:
    _mode(raw)
    peers: dict[str, dict[str, Any]] = {}
    for row in rule_rows(raw.get(_COLLECTION, []), _MAX_PEERS):
        identifier = rule_id(row.get("id"))
        name = _NAME.validate(row.get("vpn_name"))
        if (
            identifier in peers
            or type(name) is not str
            or any(ord(char) > _MAX_CHARACTER or char in "<>" for char in name)
        ):
            raise ConfigurationError("ambiguous_vpn_peer")
        peers[identifier] = {
            "id": identifier,
            "vpn_name": name,
            "vpn_status": _ACTIVE.read(row),
            **{
                key: _private_text(row[key])
                for key in _PRIVATE_PEER_FIELDS
                if key in row
            },
        }
    return peers


def _snapshot(raw: SettingValues) -> dict[str, Any]:
    """Private HMAC/readback projection excludes connected IPs and other telemetry."""
    return {
        "vpn_typ": _mode(raw),
        "vpn_key": _private_text(raw.get("vpn_key")),
        _COLLECTION: _peers(raw),
    }


def _online(raw: SettingValues) -> None:
    """Match native fresh global connectivity gates and tethering-only refusal."""
    context = raw.get("vpn_connectivity")
    if not isinstance(context, Mapping):
        raise ConfigurationError("missing_vpn_connectivity")
    if context.get("onlinestatus") == "online" or (
        context.get("auto_external_modem") == "1"
        and (
            (context.get("extwan_typ") == "2" and context.get("extwan_status") == "1")
            or (
                context.get("extwan_typ") == "3"
                and context.get("lte_status") in ("10", "11")
            )
        )
    ):
        return
    raise ConfigurationError("vpn_offline")


def _create_values(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
    _online(raw)
    mode = _mode(raw)
    allowed = {"vpn_name", "vpn_password"} if mode == "1" else {"vpn_name"}
    if set(changes) != allowed:
        raise ConfigurationError("invalid_vpn_creation")
    name = _NAME.validate(changes["vpn_name"])
    if type(name) is not str or any(
        ord(char) > _MAX_CHARACTER or char in "<>" for char in name
    ):
        raise ConfigurationError("invalid_vpn_name")
    values: dict[str, Any] = {"vpn_name": name, "vpn_status": True}
    if mode == "1":
        password = _PASSWORD.validate(changes["vpn_password"])
        if (
            type(password) is not str
            or not _PASSWORD_CHARACTERS.fullmatch(password)
            or sum(bool(re.search(pattern, password)) for pattern in _PASSWORD_CLASSES)
            < _MIN_PASSWORD_CLASSES
        ):
            raise ConfigurationError("invalid_vpn_password")
        values["vpn_password"] = password
    return values


def _create_read(raw: SettingValues) -> dict[str, Any]:
    _snapshot(raw)
    _online(raw)
    return {"vpn_name": ""}


def _create_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    if len(_snapshot(raw)[_COLLECTION]) >= _MAX_PEERS:
        raise ConfigurationError("vpn_peer_limit")
    values = _create_values(raw, changes)
    return {
        "id": "-1",
        "vpn_name": values["vpn_name"],
        # V16 confirms the new peer checkbox is checked. Native add disables it,
        # but the serializer excludes disabled text inputs, not checkboxes.
        "vpn_status": "1",
        **(
            {"vpn_password": values["vpn_password"]} if "vpn_password" in values else {}
        ),
    }


def _create_valid(raw: SettingValues, payload: SettingValues) -> bool:
    try:
        changes = {"vpn_name": payload["vpn_name"]}
        if _mode(raw) == "1":
            changes["vpn_password"] = payload["vpn_password"]
        return _create_build(raw, changes) == dict(payload)
    except (ConfigurationError, KeyError, TypeError):
        return False


def _created_peer(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> dict[str, Any]:
    _create_build(before, changes)
    previous, current = _snapshot(before), _snapshot(after)
    old, new = previous[_COLLECTION], current[_COLLECTION]
    created = new.keys() - old.keys()
    if (
        previous["vpn_typ"] != current["vpn_typ"]
        or len(created) != 1
        or len(new) != len(old) + 1
        or any(new.get(key) != row for key, row in old.items())
        or (previous["vpn_key"] != current["vpn_key"] and (old or previous["vpn_key"]))
    ):
        raise ConfigurationError("vpn_creation_unverified")
    row = new[next(iter(created))]
    if any(
        row.get(key) != value for key, value in _create_values(before, changes).items()
    ):
        raise ConfigurationError("vpn_creation_unverified")
    return dict(row)


def _create_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _created_peer(before, changes, after)
    except ConfigurationError:
        return False
    return True


def _wireguard_content(value: object) -> str:
    """Decode data escapes, never JavaScript, and exclude executable wg-quick hooks."""
    content = _private_text(value)
    if "\n" not in content and "\\n" in content:
        try:
            content = json.loads('"' + content + '"')
        except (ValueError, TypeError):
            raise ConfigurationError("invalid_vpn_credentials") from None
    content = _private_text(content)
    if any(ord(char) < _FIRST_PRINTABLE and char not in "\n\r\t" for char in content):
        raise ConfigurationError("invalid_vpn_credentials")
    sections: dict[str, set[str]] = {}
    section: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section not in _WIREGUARD_FIELDS or section in sections:
                raise ConfigurationError("invalid_vpn_credentials")
            sections[section] = set()
            continue
        name, separator, data = line.partition("=")
        name = name.strip()
        if (
            section is None
            or name not in _WIREGUARD_FIELDS[section]
            or name in sections[section]
            or not separator
            or not data.strip()
        ):
            raise ConfigurationError("invalid_vpn_credentials")
        sections[section].add(name)
    if not {"PrivateKey", "Address"} <= sections.get("Interface", set()) or not {
        "PublicKey",
        "AllowedIPs",
        "Endpoint",
    } <= sections.get("Peer", set()):
        raise ConfigurationError("invalid_vpn_credentials")
    return content


def extract_vpn_credentials(
    before: SettingValues,
    changes: SettingValues,
    response: SettingValues,
    after: SettingValues,
) -> VpnCredentials:
    """Return a secret only after exact fresh creation proof and newestID binding."""
    row = _created_peer(before, changes, after)
    response = normalize_configuration_payload(response)
    if rule_id(response.get("newestID")) != row["id"]:
        raise ConfigurationError("vpn_creation_unverified")
    mode = _mode(before)
    if mode == "0":
        return VpnCredentials(
            row["id"],
            mode,
            "Wireguard.conf",
            "text/plain;charset=utf-8",
            _wireguard_content(response.get("vpn_qrcode")),
        )
    username, password, key = (
        _private_text(row.get("vpn_username")),
        _private_text(row.get("vpn_password")),
        _private_text(after.get("vpn_key")),
    )
    if not username or not password or not key:
        raise ConfigurationError("invalid_vpn_credentials")
    return VpnCredentials(
        row["id"],
        mode,
        "Speedport-IPsec.json",
        "application/json",
        json.dumps(
            {"username": username, "password": password, "pre_shared_key": key},
            ensure_ascii=True,
        ),
    )


def _rotation_state(raw: SettingValues) -> dict[str, Any]:
    state = _snapshot(raw)
    if state["vpn_typ"] != "1" or not state[_COLLECTION]:
        raise ConfigurationError("vpn_key_rotation_unavailable")
    _KEY.validate(state["vpn_key"])
    for row in state[_COLLECTION].values():
        for name in ("vpn_username", "vpn_password"):
            if not _private_text(row.get(name)):
                raise ConfigurationError("invalid_vpn_credentials")
    return state


def _rotation_read(raw: SettingValues) -> dict[str, Any]:
    _rotation_state(raw)
    return {"rotate_key": False}


def _rotation_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _rotation_state(raw)
    if changes != {"rotate_key": True}:
        raise ConfigurationError("vpn_key_rotation_confirmation_required")
    return {"renewvpn": "true"}


def _rotation_verify(
    before: SettingValues, changes: SettingValues, after: SettingValues
) -> bool:
    try:
        _rotation_build(before, changes)
        previous, current = _rotation_state(before), _rotation_state(after)
        if previous["vpn_key"] == current["vpn_key"]:
            return False
        # The native QR encodes the new global key. Only those derived QR strings
        # may change alongside the key; IDs, names, flags and login data may not.
        for state in (previous, current):
            for row in state[_COLLECTION].values():
                row.pop("vpn_ipsec_qrcode", None)
        return bool(previous[_COLLECTION] == current[_COLLECTION])
    except ConfigurationError:
        return False


def extract_vpn_rotated_credentials(
    before: SettingValues,
    changes: SettingValues,
    response: SettingValues,
    after: SettingValues,
) -> VpnCredentials:
    """Deliver the independently verified new IPsec key without logging credentials."""
    if not _rotation_verify(before, changes, after):
        raise ConfigurationError("vpn_key_rotation_unverified")
    response = normalize_configuration_payload(response)
    current = _rotation_state(after)
    if response.get("vpn_key") != current["vpn_key"]:
        raise ConfigurationError("vpn_key_rotation_unverified")
    return VpnCredentials(
        "all",
        "1",
        "Speedport-IPsec-peers.json",
        "application/json",
        json.dumps(
            {
                "pre_shared_key": current["vpn_key"],
                "peers": [
                    {
                        "id": row["id"],
                        "name": row["vpn_name"],
                        "username": row["vpn_username"],
                        "password": row["vpn_password"],
                    }
                    for row in current[_COLLECTION].values()
                ],
            },
            ensure_ascii=True,
        ),
    )


def vpn_target_rows(setting_id: str, raw: SettingValues) -> tuple[dict[str, str], ...]:
    """Return IDs and names only; never expose credentials or connected addresses."""
    if setting_id not in VPN_TARGET_SPECS:
        raise ConfigurationError("setting_unavailable")
    return tuple(
        {"id": row["id"], "vpn_name": row["vpn_name"]}
        for row in _snapshot(raw)[_COLLECTION].values()
    )


def vpn_target_metadata() -> list[dict[str, Any]]:
    """Describe reviewed controls without fabricating a current target."""
    return [
        {**vpn_target_contract(spec.id, "0").metadata(), "requires_target": True}
        for spec in VPN_TARGET_SPECS.values()
    ]


def vpn_target_contract(setting_id: str, target_id: str) -> SettingsContract:
    """Bind a minimal native toggle or deletion to an exact fresh stable peer ID."""
    spec = VPN_TARGET_SPECS.get(setting_id)
    if spec is None or type(target_id) is not str:
        raise ConfigurationError("setting_unavailable")
    target_id = rule_id(target_id)
    deleting = setting_id == "vpn_peer_delete"

    def selected(raw: SettingValues) -> dict[str, Any]:
        row = _snapshot(raw)[_COLLECTION].get(target_id)
        if row is None:
            raise ConfigurationError("stale_settings")
        return dict(row)

    def read(raw: SettingValues) -> dict[str, Any]:
        return (
            {"delete_entry": target_id not in _snapshot(raw)[_COLLECTION]}
            if deleting
            else {"vpn_status": selected(raw)["vpn_status"]}
        )

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        selected(raw)
        if deleting:
            if changes != {"delete_entry": True}:
                raise ConfigurationError("deletion_required")
            return {"id": target_id, "deleteEntry": "delete"}
        if set(changes) != {"vpn_status"}:
            raise ConfigurationError("invalid_vpn_change")
        value = _ACTIVE.validate(changes["vpn_status"])
        return {"id": target_id, "switchStatus": True, "vpn_status": 1 if value else 0}

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            expected = _snapshot(before)
            if deleting:
                expected[_COLLECTION].pop(target_id)
            else:
                expected[_COLLECTION][target_id]["vpn_status"] = changes["vpn_status"]
            return _snapshot(after) == expected
        except ConfigurationError:
            return False

    return SettingsContract(
        spec.id,
        spec.title,
        "Network",
        _ENDPOINT,
        _REFERER,
        spec.fields,
        reader=read,
        builder=build,
        payload_keys=frozenset(
            {"id", "deleteEntry"} if deleting else {"id", "switchStatus", "vpn_status"}
        ),
        verifier=verify,
        revision_values=_snapshot,
        warning=_WARNING,
        confirmation="DELETE VPN PEER" if deleting else "CHANGE VPN PEER",
    )


VPN_SETTINGS: Final = (
    SettingsContract(
        "vpn_peer_create",
        "Add VPN peer",
        "Network",
        _ENDPOINT,
        _REFERER,
        (_CREATE_NAME, _PASSWORD),
        reader=_create_read,
        builder=_create_build,
        payload_validator=_create_valid,
        verifier=_create_verify,
        verifier_owns_fields=True,
        revision_values=_snapshot,
        expected_values=lambda raw, changes: {
            "vpn_name": _create_values(raw, changes)["vpn_name"]
        },
        warning=(
            "The new peer is enabled and grants remote network access. "
            "Save its credentials immediately; WireGuard credentials are returned "
            "only once to this administrator's current session and are not stored. "
            "Closing the editor or losing the response can lose the configuration; "
            "do not retry creation automatically. No existing peer credentials or "
            "VPN mode are changed."
        ),
        confirmation="ADD VPN PEER",
    ),
    SettingsContract(
        "vpn_ipsec_key_rotate",
        "Replace the shared IPsec key",
        "Network",
        _ENDPOINT,
        _REFERER,
        (_ROTATE,),
        reader=_rotation_read,
        builder=_rotation_build,
        payload_keys=frozenset({"renewvpn"}),
        verifier=_rotation_verify,
        verifier_owns_fields=True,
        revision_values=_rotation_state,
        warning=(
            "This replaces the shared key for every IPsec peer and can terminate "
            "all remote VPN connections. Every client must receive the new key. "
            "Download the credentials now: this administrator's response is not "
            "stored, and closing the editor can lose it. Never retry automatically. "
            "WireGuard mode is not supported by this action."
        ),
        confirmation="REPLACE ALL IPSEC KEYS",
    ),
)
