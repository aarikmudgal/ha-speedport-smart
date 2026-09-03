"""Configuration-only compound decoding leaves all existing telemetry unchanged."""

import json

import pytest

from custom_components.speedport_smart.api.codec import decode_payload, encode_payload
from custom_components.speedport_smart.api.exceptions import SpeedportDecodeError


def document(children: object = None) -> str:
    """Construct only synthetic firmware-format records."""
    return json.dumps(
        [
            {
                "varid": "wlan_add",
                "vartype": "template",
                "varvalue": [
                    {
                        "varid": "sid",
                        "vartype": "compound",
                        "varvalue": "first",
                        "compounds": children
                        if children is not None
                        else [
                            {
                                "varid": "mdevice_name",
                                "vartype": "option",
                                "varvalue": "1",
                            }
                        ],
                    },
                    {
                        "varid": "sid",
                        "vartype": "compound",
                        "varvalue": "second",
                        "compounds": [
                            {
                                "varid": "mdevice_name",
                                "vartype": "option",
                                "varvalue": "0",
                            }
                        ],
                    },
                ],
            }
        ]
    )


@pytest.mark.parametrize("encrypted", [False, True])
def test_compound_pairs_survive_only_when_explicitly_requested(
    *, encrypted: bool
) -> None:
    """Legacy telemetry output is identical with plaintext or encrypted input."""
    payload = encode_payload(document()) if encrypted else document()
    assert decode_payload(payload) == {"wlan_add": {"sid": ["first", "second"]}}
    assert decode_payload(payload, preserve_compounds=True) == {
        "wlan_add": {
            "sid": [
                {"sid": "first", "mdevice_name": "1"},
                {"sid": "second", "mdevice_name": "0"},
            ]
        }
    }


@pytest.mark.parametrize(
    "children", [[], {}, [{"varid": "sid", "varvalue": "collision"}]]
)
def test_missing_or_colliding_compounds_do_not_invent_selections(
    children: object,
) -> None:
    """No selection is guessed when firmware bindings are malformed."""
    with pytest.raises(SpeedportDecodeError):
        decode_payload(document(children), preserve_compounds=True)
