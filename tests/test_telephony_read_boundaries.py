"""Focused privacy boundaries for telephony payload normalization."""

from __future__ import annotations

from custom_components.speedport_smart.normalizers import normalize_feature_payload


def test_call_groups_expose_only_missed_count_and_latest_timestamp() -> None:
    """Call records collapse to one count and timestamp without identities."""
    normalized = normalize_feature_payload(
        "telephony",
        {
            "addmissedcalls": [
                {
                    "timestamp": "2026-09-01T09:00:00+00:00",
                    "name": "Private missed caller",
                    "number": "+49 30 111111",
                },
                {
                    "timestamp": "2026-09-01T11:00:00+00:00",
                    "name": "Another private caller",
                    "number": "+49 30 222222",
                },
            ],
            "adddialedcalls": [
                {
                    "timestamp": "2026-09-01T12:00:00+00:00",
                    "name": "Private dialed contact",
                    "number": "+49 30 333333",
                }
            ],
            "addtakencalls": [
                {
                    "timestamp": "2026-09-01T10:00:00+00:00",
                    "name": "Private answered caller",
                    "number": "+49 30 444444",
                }
            ],
        },
    )

    assert normalized == {
        "telephony": {
            "missed_call_count": 2,
            "last_call": {"timestamp": "2026-09-01T12:00:00+00:00"},
        }
    }


def test_analog_payload_remains_absent_without_exact_handler() -> None:
    """Analog settings cannot leak through generic payload normalization."""
    assert (
        normalize_feature_payload(
            "analog",
            {
                "use_analog": "1",
                "analog_name": "Private analog socket",
                "phone_number": "+49 30 555555",
            },
        )
        == {}
    )


def test_dect_private_and_unproven_settings_remain_absent() -> None:
    """PIN, transmit power, and Full Eco need exact reviewed contracts."""
    normalized = normalize_feature_payload(
        "dect",
        {
            "use_dect": "1",
            "dect_pin": "1234",
            "dect_transmit_power": "reduced",
            "dect_full_eco": "1",
        },
    )

    assert normalized == {"dect": {"enabled": True}}
