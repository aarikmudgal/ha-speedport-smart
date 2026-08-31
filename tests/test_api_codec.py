"""Tests for Speedport AES-CCM JSON codec."""

from __future__ import annotations

import pytest

from custom_components.speedport_smart.api.codec import (
    decode_payload,
    encode_payload,
    normalize_document,
)
from custom_components.speedport_smart.api.exceptions import SpeedportDecodeError

_KNOWN_ENCRYPTED_STATUS = (
    "99ce1cfb8bbfe9ee5a6e44f68c3c43db45d6d49b52d3681b8fde6c3eb9f325da"
    "ca4c5055651c975e4e95bb44f5524cd3b195ac290c221f9ff50510313ca2e30311"
)


def test_decode_known_aes_ccm_payload() -> None:
    """Decode independently generated protocol vector."""
    assert decode_payload(_KNOWN_ENCRYPTED_STATUS) == {"dsl_link_status": "online"}


def test_encode_known_aes_ccm_payload() -> None:
    """Encode using fixed key, nonce, and 16-byte CCM tag."""
    plain = '[{"varid":"dsl_link_status","varvalue":"online"}]'
    assert encode_payload(plain) == _KNOWN_ENCRYPTED_STATUS


def test_decode_plain_json_and_empty_list() -> None:
    """Plain legacy-compatible JSON and empty endpoint remain supported."""
    assert decode_payload('{"status":"ok"}') == {"status": "ok"}
    assert decode_payload("[]") == {}


def test_normalize_nested_and_repeated_varids() -> None:
    """Repeated records survive normalization as list."""
    document = [
        {
            "varid": "device",
            "varvalue": [
                {"varid": "mac", "varvalue": "AA:BB"},
                {"varid": "online", "varvalue": "1"},
            ],
        },
        {
            "varid": "device",
            "varvalue": [
                {"varid": "mac", "varvalue": "CC:DD"},
                {"varid": "online", "varvalue": "0"},
            ],
        },
    ]
    assert normalize_document(document) == {
        "device": [
            {"mac": "AA:BB", "online": "1"},
            {"mac": "CC:DD", "online": "0"},
        ]
    }


def test_reject_tampered_ciphertext() -> None:
    """CCM authentication failure never falls through as raw data."""
    tampered = _KNOWN_ENCRYPTED_STATUS[:-2] + "00"
    with pytest.raises(SpeedportDecodeError):
        decode_payload(tampered)


@pytest.mark.parametrize("payload", ["not json", "123", "null", "[1, 2]"])
def test_reject_unsupported_documents(payload: str) -> None:
    """Only object or varid-list documents enter normalized state."""
    with pytest.raises(SpeedportDecodeError):
        decode_payload(payload)
