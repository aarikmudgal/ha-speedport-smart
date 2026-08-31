"""AES-CCM and JSON codec used by Speedport Smart 4 web API."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .exceptions import SpeedportDecodeError

DEFAULT_KEY_HEX = "cdc0cac1280b516e674f0057e4929bca84447cca8425007e33a88a5cf598a190"
DEFAULT_KEY = bytes.fromhex(DEFAULT_KEY_HEX)
CCM_TAG_LENGTH = 16
_HEX_PAYLOAD = re.compile(r"^[0-9a-fA-F]+$")


def decode_payload(payload: str, key: bytes | str = DEFAULT_KEY) -> dict[str, Any]:
    """Decode encrypted hex or plain Speedport JSON into mapping."""
    text = payload.strip()
    if not text or text == "[]":
        return {}

    if _looks_encrypted(text):
        key_bytes = _coerce_key(key)
        try:
            ciphertext_and_tag = bytes.fromhex(text)
            if len(ciphertext_and_tag) <= CCM_TAG_LENGTH:
                msg = "Encrypted response is shorter than authentication tag"
                raise SpeedportDecodeError(msg)
            plaintext = AESCCM(key_bytes, tag_length=CCM_TAG_LENGTH).decrypt(
                key_bytes[:8], ciphertext_and_tag, None
            )
            text = plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            msg = "Speedport AES-CCM response authentication failed"
            raise SpeedportDecodeError(msg) from exc

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = "Speedport response is neither encrypted nor valid JSON"
        raise SpeedportDecodeError(msg) from exc
    return normalize_document(document)


def encode_payload(payload: str, key: bytes | str = DEFAULT_KEY) -> str:
    """Encode form payload using router AES-CCM framing."""
    key_bytes = _coerce_key(key)
    encrypted = AESCCM(key_bytes, tag_length=CCM_TAG_LENGTH).encrypt(
        key_bytes[:8], payload.encode(), None
    )
    return encrypted.hex()


def normalize_document(document: object) -> dict[str, Any]:
    """Normalize Speedport varid/varvalue documents without losing duplicates."""
    if isinstance(document, Mapping):
        return {str(key): value for key, value in document.items()}
    if isinstance(document, list):
        return _flatten_items(document)
    msg = f"Unsupported JSON root type: {type(document).__name__}"
    raise SpeedportDecodeError(msg)


def is_encrypted_payload(payload: str) -> bool:
    """Return whether payload uses Speedport hex AES-CCM framing."""
    return _looks_encrypted(payload.strip())


def _looks_encrypted(text: str) -> bool:
    return (
        len(text) > CCM_TAG_LENGTH * 2
        and len(text) % 2 == 0
        and bool(_HEX_PAYLOAD.fullmatch(text))
    )


def _coerce_key(key: bytes | str) -> bytes:
    if isinstance(key, str):
        try:
            key = bytes.fromhex(key)
        except ValueError as exc:
            msg = "Speedport encryption key is not valid hexadecimal"
            raise SpeedportDecodeError(msg) from exc
    if len(key) not in {16, 24, 32}:
        msg = "Speedport AES key must contain 16, 24, or 32 bytes"
        raise SpeedportDecodeError(msg)
    return key


def _flatten_items(items: list[object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if not isinstance(item, Mapping) or "varid" not in item:
            continue
        key = str(item["varid"])
        value = _normalize_value(item.get("varvalue"))
        if key not in result:
            result[key] = value
            continue
        previous = result[key]
        if isinstance(previous, list):
            previous.append(value)
        else:
            result[key] = [previous, value]
    if items and not result:
        msg = "Speedport JSON list contains no varid records"
        raise SpeedportDecodeError(msg)
    return result


def _normalize_value(value: object) -> object:
    if isinstance(value, list):
        if any(isinstance(item, Mapping) and "varid" in item for item in value):
            return _flatten_items(value)
        return [_normalize_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    return value
