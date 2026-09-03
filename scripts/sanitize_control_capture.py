"""
Convert one user-operated browser HAR into safe control-contract evidence.

The utility is deliberately offline: it accepts a HAR document on standard
input, performs no network requests, and writes only a bounded structural
roundtrip report. Raw headers, bodies, authentication material, router origin,
and subscriber values never enter the report.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.speedport_smart.api.codec import (
    CCM_TAG_LENGTH,
    DEFAULT_KEY,
    decode_payload,
    is_encrypted_payload,
)
from custom_components.speedport_smart.api.exceptions import SpeedportDecodeError

_MAX_INPUT_BYTES: Final = 32 * 1024 * 1024
_MAX_ENTRIES: Final = 256
_MAX_BODY_BYTES: Final = 2 * 1024 * 1024
_MAX_NODES: Final = 100_000
_MAX_DEPTH: Final = 32
_MAX_URL_LENGTH: Final = 4_096
_MAX_FIELDS: Final = 256
_MAX_FIELD_VALUE_LENGTH: Final = 64 * 1024
_MIN_STATE_VALUES: Final = 2
_MAX_STATE_VALUES: Final = 10
_ROUNDTRIP_POST_COUNT: Final = 2
_HTTP_SUCCESS_MIN: Final = 200
_HTTP_SUCCESS_MAX: Final = 300
_HTTP_NOT_MODIFIED: Final = 304
_LOGIN_PATH: Final = "data/Login.json"
_SAFE_CACHE_QUERY_FIELDS: Final = frozenset({"_", "_time"})
_SAFE_OPERATION = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_SAFE_FIELD = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.$:-]{0,127}(?:\[\])*$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_.\-/]+$")
_SAFE_SCALAR_FIELDS: Final = frozenset(
    {
        "ex5g_led_mode",
        "lan_privacy_policy",
        "mdevice_fix_dhcp",
        "portuw_active",
        "use_bonding",
        "use_wlan",
        "wlan_guest_active",
        "wlan_office_active",
    }
)
_SAFE_PUBLIC_STATE = re.compile(
    r"^(?:-?[0-9]|true|false|on|off|yes|no|enable|disable|enabled|disabled|"
    r"connect|disconnect|reconnect|start|stop)$",
    re.IGNORECASE,
)
_POSITIVE_ACK_VALUES: Final = frozenset({"1", "ok", "success", "true"})
_AUTH_KEY_PARTS: Final = frozenset(
    {
        "auth",
        "challenge",
        "cookie",
        "csrf",
        "httoken",
        "nonce",
        "proof",
        "session",
        "showpw",
        "token",
    }
)
_SECRET_KEY_PARTS: Final = frozenset(
    {
        "credential",
        "key",
        "passphrase",
        "password",
        "pin",
        "private",
        "preshared",
        "puk",
        "secret",
    }
)
_ADDRESS_KEY_PARTS: Final = frozenset(
    {
        "address",
        "dns",
        "gateway",
        "host",
        "ip",
        "mac",
        "network",
        "subnet",
    }
)
_PII_KEY_PARTS: Final = frozenset(
    {
        "caller",
        "email",
        "imei",
        "imsi",
        "label",
        "name",
        "number",
        "phone",
        "serial",
        "ssid",
        "title",
    }
)
_IDENTIFIER_KEYS: Final = frozenset({"fingerprint", "id", "row_id", "uid", "uuid"})
_FORBIDDEN_SELECTOR_PARTS: Final = frozenset(
    {
        "backup",
        "credential",
        "delete",
        "erase",
        "export",
        "factory",
        "firmware",
        "format",
        "import",
        "key",
        "login",
        "logout",
        "password",
        "pin",
        "private",
        "puk",
        "purge",
        "reboot",
        "remove",
        "reset",
        "restart",
        "restore",
        "secret",
        "shutdown",
        "update",
        "upload",
        "upgrade",
        "wipe",
    }
)
_SAFE_ACK_FIELDS: Final = frozenset({"ack", "result", "status", "success"})


class CaptureError(ValueError):
    """Fixed-code rejection that never includes raw capture data."""

    def __init__(self, code: str) -> None:
        """Initialize one non-sensitive fixed rejection code."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CaptureSpec:
    """Explicit allowlist for one reversible scalar operation."""

    operation: str
    post_path: str
    state_field: str
    state_values: tuple[str, ...]
    readback_path: str
    readback_field: str
    ack_field: str = "status"

    def __post_init__(self) -> None:
        """Reject unsafe or ambiguous command-line evidence selectors."""
        if not _SAFE_OPERATION.fullmatch(self.operation):
            raise CaptureError("unsafe_operation_name")
        object.__setattr__(self, "post_path", _safe_relative_path(self.post_path))
        object.__setattr__(
            self,
            "readback_path",
            _safe_relative_path(self.readback_path),
        )
        if self.post_path == _LOGIN_PATH:
            raise CaptureError("login_endpoint_cannot_be_targeted")
        for field in (self.state_field, self.readback_field, self.ack_field):
            if not _safe_field_path(field):
                raise CaptureError("unsafe_field_name")
        _validate_safe_capture_target(self)
        if not _MIN_STATE_VALUES <= len(self.state_values) <= _MAX_STATE_VALUES:
            raise CaptureError("state_allowlist_requires_two_to_ten_values")
        canonical_values = tuple(
            _canonical_scalar(value) for value in self.state_values
        )
        if len(set(canonical_values)) != len(canonical_values) or any(
            not _SAFE_PUBLIC_STATE.fullmatch(value) for value in canonical_values
        ):
            raise CaptureError("unsafe_state_allowlist")
        object.__setattr__(self, "state_values", canonical_values)


def sanitize_control_capture(
    har: Mapping[str, Any],
    spec: CaptureSpec,
) -> dict[str, Any]:
    """Return sanitized evidence for one exact apply/readback/rollback sequence."""
    _validate_structure_bounds(har)
    entries = _har_entries(har)
    origin = _single_origin(entries)
    session_key = _derive_session_key(entries)

    post_matches = [
        (index, entry)
        for index, entry in enumerate(entries)
        if _request_targets(
            entry,
            expected_origin=origin,
            method="POST",
            path=spec.post_path,
        )
    ]
    if len(post_matches) != _ROUNDTRIP_POST_COUNT:
        raise CaptureError("roundtrip_requires_exactly_two_target_posts")
    (apply_index, apply_entry), (rollback_index, rollback_entry) = post_matches
    if apply_index >= rollback_index:
        raise CaptureError("invalid_roundtrip_order")

    apply_form = _decode_request_form(apply_entry, session_key)
    rollback_form = _decode_request_form(rollback_entry, session_key)
    apply_state = _single_form_value(apply_form, spec.state_field)
    rollback_state = _single_form_value(rollback_form, spec.state_field)
    allowed = frozenset(spec.state_values)
    if apply_state not in allowed or rollback_state not in allowed:
        raise CaptureError("target_state_outside_allowlist")
    if apply_state == rollback_state:
        raise CaptureError("apply_and_rollback_states_match")

    baseline_entry = _select_readback(
        entries,
        spec,
        origin,
        start=0,
        end=apply_index,
        take_last=True,
    )
    applied_entry = _select_readback(
        entries,
        spec,
        origin,
        start=apply_index + 1,
        end=rollback_index,
        take_last=True,
    )
    restored_entry = _select_readback(
        entries,
        spec,
        origin,
        start=rollback_index + 1,
        end=len(entries),
        take_last=False,
    )

    baseline_state = _readback_state(baseline_entry, spec, session_key)
    applied_state = _readback_state(applied_entry, spec, session_key)
    restored_state = _readback_state(restored_entry, spec, session_key)
    apply_ack = _ack_evidence(apply_entry, spec, session_key)
    rollback_ack = _ack_evidence(rollback_entry, spec, session_key)

    blockers: list[str] = []
    if not apply_ack["positive"]:
        blockers.append("apply_ack_not_positive")
    if not rollback_ack["positive"]:
        blockers.append("rollback_ack_not_positive")
    if baseline_state not in allowed:
        blockers.append("baseline_readback_outside_allowlist")
    if applied_state not in allowed:
        blockers.append("applied_readback_outside_allowlist")
    if restored_state not in allowed:
        blockers.append("restored_readback_outside_allowlist")
    if baseline_state != rollback_state:
        blockers.append("rollback_request_does_not_match_baseline")
    if applied_state != apply_state:
        blockers.append("apply_readback_mismatch")
    if restored_state != baseline_state:
        blockers.append("rollback_readback_mismatch")

    field_evidence, field_blockers = _field_evidence(
        apply_form,
        rollback_form,
        state_field=spec.state_field,
        apply_state=apply_state,
        rollback_state=rollback_state,
    )
    blockers.extend(field_blockers)
    referer_apply = _referer_path(apply_entry, expected_origin=origin)
    referer_rollback = _referer_path(rollback_entry, expected_origin=origin)
    if referer_apply != referer_rollback:
        blockers.append("referer_changed_between_apply_and_rollback")
    content_type_apply = _request_content_type(apply_entry)
    content_type_rollback = _request_content_type(rollback_entry)
    if content_type_apply != content_type_rollback:
        blockers.append("content_type_changed_between_apply_and_rollback")

    unique_blockers = sorted(set(blockers))
    return {
        "format_version": 1,
        "operation": spec.operation,
        "evidence_only": True,
        "privacy": {
            "raw_values_retained": False,
            "raw_headers_retained": False,
            "raw_bodies_retained": False,
            "origin_retained": False,
            "authentication_material_retained": False,
            "subscriber_identifiers_retained": False,
        },
        "request": {
            "method": "POST",
            "path": spec.post_path,
            "referer_path": referer_apply,
            "content_type": content_type_apply,
            "fields": field_evidence,
        },
        "acknowledgement": {
            "field": spec.ack_field,
            "apply": apply_ack,
            "rollback": rollback_ack,
        },
        "readback": {
            "method": "GET",
            "path": spec.readback_path,
            "field": spec.readback_field,
            "baseline": _safe_state_output(baseline_state, allowed),
            "applied": _safe_state_output(applied_state, allowed),
            "restored": _safe_state_output(restored_state, allowed),
            "independent_gets": True,
        },
        "proof": {
            "apply_changed_state": apply_state != rollback_state,
            "apply_readback_matches": applied_state == apply_state,
            "rollback_requested_baseline": rollback_state == baseline_state,
            "rollback_restored_baseline": restored_state == baseline_state,
            "complete": not unique_blockers,
            "blockers": unique_blockers,
        },
    }


def _har_entries(har: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return a bounded ordered HAR entry list."""
    log = har.get("log")
    if not isinstance(log, Mapping):
        raise CaptureError("invalid_har_log")
    raw_entries = log.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CaptureError("invalid_har_entries")
    if len(raw_entries) > _MAX_ENTRIES:
        raise CaptureError("har_entry_limit_exceeded")
    if not all(isinstance(entry, Mapping) for entry in raw_entries):
        raise CaptureError("invalid_har_entry")
    return list(raw_entries)


def _single_origin(entries: Sequence[Mapping[str, Any]]) -> tuple[str, str, int | None]:
    """Require all captured traffic to use one origin without retaining it."""
    origins: set[tuple[str, str, int | None]] = set()
    for entry in entries:
        request = _request(entry)
        url = request.get("url")
        if not isinstance(url, str) or len(url) > _MAX_URL_LENGTH:
            raise CaptureError("invalid_request_url")
        try:
            split = urlsplit(url)
            port = split.port
        except ValueError as err:
            raise CaptureError("invalid_request_url") from err
        if (
            split.scheme not in {"http", "https"}
            or not split.hostname
            or split.username is not None
            or split.password is not None
            or split.fragment
        ):
            raise CaptureError("invalid_request_url")
        origins.add((split.scheme, split.hostname.casefold(), port))
    if len(origins) != 1:
        raise CaptureError("multiple_origins_rejected")
    return next(iter(origins))


def _request(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return one HAR request mapping."""
    request = entry.get("request")
    if not isinstance(request, Mapping):
        raise CaptureError("invalid_har_request")
    return request


def _response(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return one HAR response mapping."""
    response = entry.get("response")
    if not isinstance(response, Mapping):
        raise CaptureError("invalid_har_response")
    return response


def _request_method(entry: Mapping[str, Any]) -> str:
    """Return an uppercase HTTP method without exposing arbitrary input."""
    method = _request(entry).get("method")
    if not isinstance(method, str):
        raise CaptureError("invalid_request_method")
    normalized = method.strip().upper()
    if normalized not in {"GET", "POST"}:
        raise CaptureError("unsupported_request_method")
    return normalized


def _request_path(
    entry: Mapping[str, Any],
    *,
    expected_origin: tuple[str, str, int | None],
) -> str:
    """Return one normalized relative request path."""
    url = _request(entry).get("url")
    if not isinstance(url, str):
        raise CaptureError("invalid_request_url")
    split = urlsplit(url)
    if split.username is not None or split.password is not None or split.fragment:
        raise CaptureError("invalid_request_url")
    if (split.scheme, (split.hostname or "").casefold(), split.port) != expected_origin:
        raise CaptureError("multiple_origins_rejected")
    return _safe_relative_path(split.path)


def _request_targets(
    entry: Mapping[str, Any],
    *,
    expected_origin: tuple[str, str, int | None],
    method: str,
    path: str,
) -> bool:
    """Match one relevant endpoint and validate only its contract query."""
    if _request_method(entry) != method:
        return False
    if _request_path(entry, expected_origin=expected_origin) != path:
        return False
    url = _request(entry).get("url")
    if not isinstance(url, str):
        raise CaptureError("invalid_request_url")
    _validate_request_query(urlsplit(url).query, method=method)
    return True


def _validate_request_query(query: str, *, method: str) -> None:
    """Permit only numeric cache busters on independent GET readbacks."""
    if not query:
        return
    if method != "GET":
        raise CaptureError("target_post_query_rejected")
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=False,
            strict_parsing=True,
            max_num_fields=len(_SAFE_CACHE_QUERY_FIELDS),
        )
    except ValueError as err:
        raise CaptureError("unsafe_readback_query") from err
    if not pairs or any(
        name not in _SAFE_CACHE_QUERY_FIELDS or not value.isdecimal()
        for name, value in pairs
    ):
        raise CaptureError("unsafe_readback_query")


def _safe_relative_path(value: str) -> str:
    """Return a router-relative path without host, query, or traversal."""
    split = urlsplit(value.strip())
    if split.scheme or split.netloc or split.query or split.fragment:
        raise CaptureError("unsafe_relative_path")
    path = split.path.lstrip("/")
    if not path or ".." in PurePosixPath(path).parts or not _SAFE_PATH.fullmatch(path):
        raise CaptureError("unsafe_relative_path")
    return path


def _safe_field_path(value: str) -> bool:
    """Return whether an explicit dotted field selector is structural only."""
    return bool(value) and all(_SAFE_FIELD.fullmatch(part) for part in value.split("."))


def _validate_safe_capture_target(spec: CaptureSpec) -> None:
    """Limit v1 evidence to reversible, non-private scalar setters."""
    selectors = (
        spec.operation,
        spec.post_path,
        spec.state_field,
        spec.readback_path,
        spec.readback_field,
        spec.ack_field,
    )
    if not spec.operation.startswith("set_") or any(
        forbidden in selector.casefold()
        for selector in selectors
        for forbidden in _FORBIDDEN_SELECTOR_PARTS
    ):
        raise CaptureError("unsafe_capture_target")
    if not spec.post_path.startswith("data/") or not spec.post_path.endswith(".json"):
        raise CaptureError("unsafe_capture_target")
    if spec.state_field.casefold() not in _SAFE_SCALAR_FIELDS:
        raise CaptureError("unsafe_capture_target")
    if any(
        _selector_is_private(selector)
        for selector in (spec.state_field, spec.readback_field, spec.ack_field)
    ):
        raise CaptureError("unsafe_capture_target")
    if spec.ack_field.split(".")[-1].casefold() not in _SAFE_ACK_FIELDS:
        raise CaptureError("unsafe_capture_target")


def _selector_is_private(selector: str) -> bool:
    """Reject secret, authentication, identity, address, and PII selectors."""
    return any(
        _field_role(part.replace("[]", "")) != "opaque" for part in selector.split(".")
    )


def _safe_form_field(value: str) -> str:
    """Normalize dynamic array indices out of one submitted field name."""
    normalized = re.sub(r"\[[^\]]+\]", "[]", value.strip())
    if not _SAFE_FIELD.fullmatch(normalized):
        raise CaptureError("unsafe_submitted_field_name")
    return normalized


def _request_body(entry: Mapping[str, Any]) -> str:
    """Return a bounded request body in memory only."""
    post_data = _request(entry).get("postData")
    if not isinstance(post_data, Mapping):
        raise CaptureError("missing_request_body")
    text = post_data.get("text")
    if isinstance(text, str):
        if len(text.encode("utf-8")) > _MAX_BODY_BYTES:
            raise CaptureError("request_body_limit_exceeded")
        return text
    params = post_data.get("params")
    if not isinstance(params, list):
        raise CaptureError("missing_request_body")
    pairs: list[tuple[str, str]] = []
    for param in params:
        if not isinstance(param, Mapping):
            raise CaptureError("invalid_request_parameters")
        name = param.get("name")
        value = param.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise CaptureError("invalid_request_parameters")
        pairs.append((name, value))
    text = urlencode(pairs)
    if len(text.encode("utf-8")) > _MAX_BODY_BYTES:
        raise CaptureError("request_body_limit_exceeded")
    return text


def _response_text(entry: Mapping[str, Any]) -> str:
    """Return a bounded decoded HAR response body in memory only."""
    content = _response(entry).get("content")
    if not isinstance(content, Mapping):
        raise CaptureError("missing_response_body")
    text = content.get("text")
    if not isinstance(text, str):
        raise CaptureError("missing_response_body")
    if content.get("encoding") == "base64":
        try:
            body = base64.b64decode(text, validate=True)
        except (ValueError, binascii.Error) as err:
            raise CaptureError("invalid_base64_response") from err
        if len(body) > _MAX_BODY_BYTES:
            raise CaptureError("response_body_limit_exceeded")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as err:
            raise CaptureError("non_utf8_response") from err
    if len(text.encode("utf-8")) > _MAX_BODY_BYTES:
        raise CaptureError("response_body_limit_exceeded")
    return text


def _derive_session_key(entries: Sequence[Mapping[str, Any]]) -> bytes | None:
    """Derive the ephemeral browser session key from a captured challenge."""
    for entry in entries:
        if _request_method(entry) != "POST":
            continue
        request = _request(entry)
        url = request.get("url")
        if not isinstance(url, str) or urlsplit(url).path.lstrip("/") != _LOGIN_PATH:
            continue
        try:
            form = _decode_form_text(_request_body(entry), (DEFAULT_KEY,))
        except CaptureError:
            continue
        if form.get("getChallenge") != ["1"]:
            continue
        document = _decode_response_document(entry, (DEFAULT_KEY,))
        challenge = document.get("challenge")
        if not isinstance(challenge, str):
            raise CaptureError("invalid_login_challenge")
        try:
            key = bytes.fromhex(challenge.strip())
        except ValueError as err:
            raise CaptureError("invalid_login_challenge") from err
        if len(key) not in {16, 24, 32}:
            raise CaptureError("invalid_login_challenge")
        return key
    return None


def _decode_request_form(
    entry: Mapping[str, Any],
    session_key: bytes | None,
) -> dict[str, list[str]]:
    """Decode one target form without retaining the plaintext beyond this call."""
    keys = (session_key, DEFAULT_KEY) if session_key is not None else (DEFAULT_KEY,)
    return _decode_form_text(_request_body(entry), keys)


def _decode_form_text(
    body: str,
    keys: Sequence[bytes],
) -> dict[str, list[str]]:
    """Decode encrypted or plain URL-encoded form text into bounded fields."""
    plaintext = body.strip()
    if is_encrypted_payload(plaintext):
        decoded: str | None = None
        for key in keys:
            try:
                raw = AESCCM(key, tag_length=CCM_TAG_LENGTH).decrypt(
                    key[:8],
                    bytes.fromhex(plaintext),
                    None,
                )
                decoded = raw.decode("utf-8")
            except (InvalidTag, UnicodeDecodeError, ValueError):
                continue
            break
        if decoded is None:
            raise CaptureError("encrypted_request_needs_captured_login")
        plaintext = decoded
    try:
        pairs = parse_qsl(
            plaintext,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_FIELDS,
        )
    except ValueError as err:
        raise CaptureError("invalid_form_body") from err
    if not pairs:
        raise CaptureError("empty_form_body")
    result: dict[str, list[str]] = {}
    for raw_name, value in pairs:
        if len(value) > _MAX_FIELD_VALUE_LENGTH:
            raise CaptureError("form_value_limit_exceeded")
        name = _safe_form_field(raw_name)
        result.setdefault(name, []).append(value)
    if len(result) > _MAX_FIELDS:
        raise CaptureError("form_field_limit_exceeded")
    return result


def _decode_response_document(
    entry: Mapping[str, Any],
    keys: Sequence[bytes | None],
) -> dict[str, Any]:
    """Decode one response with explicitly supplied ephemeral keys."""
    text = _response_text(entry)
    candidates = tuple(key for key in keys if key is not None) or (DEFAULT_KEY,)
    last_error: SpeedportDecodeError | None = None
    for key in candidates:
        try:
            return decode_payload(text, key)
        except SpeedportDecodeError as err:
            last_error = err
    raise CaptureError("encrypted_response_needs_captured_login") from last_error


def _single_form_value(form: Mapping[str, list[str]], field: str) -> str:
    """Return one canonical allowlisted target field value."""
    values = form.get(field)
    if values is None or len(values) != 1:
        raise CaptureError("target_field_missing_or_duplicated")
    return _canonical_scalar(values[0])


def _canonical_scalar(value: Any) -> str:
    """Return a stable scalar spelling without serializing unknown objects."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip().casefold()
    raise CaptureError("non_scalar_state_value")


def _select_readback(
    entries: Sequence[Mapping[str, Any]],
    spec: CaptureSpec,
    origin: tuple[str, str, int | None],
    *,
    start: int,
    end: int,
    take_last: bool,
) -> Mapping[str, Any]:
    """Select one independent non-cached GET from an explicit sequence window."""
    matches = [
        entry
        for entry in entries[start:end]
        if _request_targets(
            entry,
            expected_origin=origin,
            method="GET",
            path=spec.readback_path,
        )
        and _response_is_success(entry)
        and not _response_is_cached(entry)
    ]
    if not matches:
        raise CaptureError("missing_independent_readback")
    return matches[-1] if take_last else matches[0]


def _response_is_cached(entry: Mapping[str, Any]) -> bool:
    """Reject cached or not-modified responses as independent readback proof."""
    response = _response(entry)
    status = response.get("status")
    return status == _HTTP_NOT_MODIFIED or any(
        value is True
        for value in (
            entry.get("_fromCache"),
            response.get("_fromDiskCache"),
            response.get("_servedFromCache"),
        )
    )


def _response_is_success(entry: Mapping[str, Any]) -> bool:
    """Require a real HTTP success before treating a GET as readback proof."""
    status = _response(entry).get("status")
    return (
        isinstance(status, int)
        and not isinstance(status, bool)
        and _HTTP_SUCCESS_MIN <= status < _HTTP_SUCCESS_MAX
    )


def _readback_state(
    entry: Mapping[str, Any],
    spec: CaptureSpec,
    session_key: bytes | None,
) -> str | None:
    """Extract only the explicitly allowlisted readback scalar."""
    document = _decode_response_document(entry, (session_key, DEFAULT_KEY))
    value = _mapping_path(document, spec.readback_field)
    if value is None:
        return None
    try:
        return _canonical_scalar(value)
    except CaptureError:
        return None


def _mapping_path(document: Mapping[str, Any], path: str) -> Any:
    """Resolve one explicit dotted mapping path without list inference."""
    value: Any = document
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _ack_evidence(
    entry: Mapping[str, Any],
    spec: CaptureSpec,
    session_key: bytes | None,
) -> dict[str, Any]:
    """Retain only fixed positive acknowledgement semantics and HTTP status."""
    response = _response(entry)
    status = response.get("status")
    http_status = (
        status if isinstance(status, int) and not isinstance(status, bool) else None
    )
    document = _decode_response_document(entry, (session_key, DEFAULT_KEY))
    raw_value = _mapping_path(document, spec.ack_field)
    try:
        value = _canonical_scalar(raw_value)
    except CaptureError:
        value = None
    safe_value = value if value in _POSITIVE_ACK_VALUES else None
    return {
        "http_status": http_status,
        "value": safe_value,
        "positive": (
            http_status is not None
            and _HTTP_SUCCESS_MIN <= http_status < _HTTP_SUCCESS_MAX
            and safe_value is not None
        ),
    }


def _field_evidence(
    apply: Mapping[str, list[str]],
    rollback: Mapping[str, list[str]],
    *,
    state_field: str,
    apply_state: str,
    rollback_state: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Describe a complete form using names, roles, and equality only."""
    names = sorted(set(apply) | set(rollback))
    blockers: list[str] = []
    if set(apply) != set(rollback):
        blockers.append("apply_and_rollback_field_sets_differ")
    evidence: list[dict[str, Any]] = []
    for name in names:
        role = "state" if name == state_field else _field_role(name)
        apply_values = apply.get(name)
        rollback_values = rollback.get(name)
        item: dict[str, Any] = {
            "name": name,
            "role": role,
            "occurrences": max(len(apply_values or ()), len(rollback_values or ())),
            "same_across_apply_and_rollback": apply_values == rollback_values,
        }
        if role == "state":
            item["apply"] = apply_state
            item["rollback"] = rollback_state
        elif role != "authentication" and apply_values != rollback_values:
            blockers.append(f"unexpected_changed_field:{name}")
        evidence.append(item)
    return evidence, blockers


def _field_role(name: str) -> str:
    """Classify values without retaining them or relying on regex redaction."""
    normalized = name.casefold()
    if any(part in normalized for part in _AUTH_KEY_PARTS):
        return "authentication"
    if any(part in normalized for part in _SECRET_KEY_PARTS):
        return "secret"
    if normalized in _IDENTIFIER_KEYS or any(
        part in normalized for part in _ADDRESS_KEY_PARTS
    ):
        return "identifier"
    if any(part in normalized for part in _PII_KEY_PARTS):
        return "private"
    return "opaque"


def _referer_path(
    entry: Mapping[str, Any],
    *,
    expected_origin: tuple[str, str, int | None],
) -> str | None:
    """Return only a same-origin Referer path and discard its value otherwise."""
    value = _header_value(entry, "referer")
    if value is None:
        return None
    try:
        split = urlsplit(value)
        origin = (split.scheme, (split.hostname or "").casefold(), split.port)
    except ValueError as err:
        raise CaptureError("invalid_referer") from err
    if origin != expected_origin:
        raise CaptureError("off_origin_referer_rejected")
    return _safe_relative_path(split.path)


def _request_content_type(entry: Mapping[str, Any]) -> str | None:
    """Return the structural request media type without parameters."""
    post_data = _request(entry).get("postData")
    value = post_data.get("mimeType") if isinstance(post_data, Mapping) else None
    if not isinstance(value, str):
        value = _header_value(entry, "content-type")
    if not isinstance(value, str):
        return None
    media_type = value.split(";", maxsplit=1)[0].strip().casefold()
    if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", media_type):
        raise CaptureError("invalid_content_type")
    return media_type


def _header_value(entry: Mapping[str, Any], target: str) -> str | None:
    """Read one header in memory while never serializing the header collection."""
    headers = _request(entry).get("headers")
    if not isinstance(headers, list):
        return None
    found: list[str] = []
    for header in headers:
        if not isinstance(header, Mapping):
            raise CaptureError("invalid_request_headers")
        name = header.get("name")
        value = header.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            raise CaptureError("invalid_request_headers")
        if name.strip().casefold() == target:
            found.append(value)
    if len(found) > 1:
        raise CaptureError("duplicate_structural_header")
    return found[0] if found else None


def _safe_state_output(value: str | None, allowed: frozenset[str]) -> str | None:
    """Return only an explicitly approved state code."""
    return value if value in allowed else None


def _validate_structure_bounds(value: Any) -> None:
    """Reject deeply nested or excessively large decoded HAR structures."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_NODES:
            raise CaptureError("har_node_limit_exceeded")
        if depth > _MAX_DEPTH:
            raise CaptureError("har_depth_limit_exceeded")
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _write_private_json(path: Path, document: Mapping[str, Any]) -> None:
    """Create one non-symlink private artifact without overwriting evidence."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as err:
        raise CaptureError("output_already_exists") from err
    except OSError as err:
        raise CaptureError("output_could_not_be_created") from err
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, indent=2, sort_keys=True)
            output.write("\n")
    except OSError as err:
        raise CaptureError("output_could_not_be_written") from err


def _arguments() -> argparse.Namespace:
    """Parse an explicit scalar capture contract from safe command-line data."""
    parser = argparse.ArgumentParser(
        description=(
            "Sanitize one browser-captured Speedport apply/readback/rollback HAR "
            "from standard input without making network requests."
        )
    )
    parser.add_argument("--operation", required=True)
    parser.add_argument("--post-path", required=True)
    parser.add_argument("--state-field", required=True)
    parser.add_argument(
        "--state-value",
        action="append",
        required=True,
        help="Safe bounded state code; repeat for every allowed value.",
    )
    parser.add_argument("--readback-path", required=True)
    parser.add_argument("--readback-field", required=True)
    parser.add_argument("--ack-field", default="status")
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def _load_stdin_har() -> Mapping[str, Any]:
    """Read one bounded HAR mapping from standard input."""
    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        raise CaptureError("har_input_limit_exceeded")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise CaptureError("invalid_har_json") from err
    if not isinstance(document, Mapping):
        raise CaptureError("invalid_har_root")
    return document


def main() -> None:
    """Read raw HAR once from stdin and write only sanitized evidence."""
    args = _arguments()
    try:
        document = _load_stdin_har()
        spec = CaptureSpec(
            operation=args.operation,
            post_path=args.post_path,
            state_field=args.state_field,
            state_values=tuple(args.state_value),
            readback_path=args.readback_path,
            readback_field=args.readback_field,
            ack_field=args.ack_field,
        )
        evidence = sanitize_control_capture(document, spec)
        _write_private_json(args.out, evidence)
    except CaptureError as err:
        raise SystemExit(f"Capture rejected safely: {err.code}") from err
    sys.stdout.write("Sanitized control-contract evidence written.\n")


if __name__ == "__main__":
    main()
