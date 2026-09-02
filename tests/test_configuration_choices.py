"""Offline proof for dynamic choices, indexed payloads and whole-list readback."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.speedport_smart.configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
)
from custom_components.speedport_smart.configuration_session import ConfigurationSession


def contract() -> SettingsContract:
    """Use synthetic rows; no router transport is involved."""
    return SettingsContract(
        "members",
        "Members",
        "Network",
        "data/Example.json",
        "html/content/network/example.html",
        (SettingsField("members", "Members", "identifiers", dynamic_choices=True),),
        field_choices=lambda raw: {"members": tuple(raw["inventory"])},
        builder=lambda _raw, changes: {
            f"member[{i}]": key for i, key in enumerate(changes["members"])
        },
        payload_validator=lambda _raw, payload: set(payload) == {"member[0]"},
        revision_fields=("inventory", "other"),
    )


RAW = {
    "members": ["a"],
    "inventory": (("a", "First"), ("b", "Second")),
    "other": "unchanged",
}
OWNER = ("admin", "session")


def test_dynamic_choices_are_typed_and_revision_bound() -> None:
    """Both the selected IDs and their inventory participate in the revision."""
    spec = contract()
    assert spec.read(RAW) == {"members": ["a"]}
    assert spec.choices(RAW) == {
        "members": [{"value": "a", "label": "First"}, {"value": "b", "label": "Second"}]
    }
    assert spec.revision(RAW) != spec.revision(
        {**RAW, "inventory": (("a", "Renamed"), ("b", "Second"))}
    )
    assert spec.build(RAW, {"members": ["b"]}) == {"member[0]": "b"}


@pytest.mark.parametrize(
    "value", [["unknown"], ["a", "a"], "a", [1], ["x&data=1"], ["a"] * 257]
)
def test_unreviewed_identifiers_fail_closed(value: object) -> None:
    """Unknown, repeated or malformed IDs cannot reach a builder."""
    with pytest.raises(ConfigurationError):
        contract().build(RAW, {"members": value})


@pytest.mark.parametrize(
    "choices", [(("a", "A"), ("a", "B")), (("x&y", "A"),), (("a", "bad\nlabel"),)]
)
def test_ambiguous_or_unsafe_dynamic_options_rejected(choices: object) -> None:
    """Dynamic labels and identifiers remain bounded and unambiguous."""
    with pytest.raises(ConfigurationError):
        contract().read({**RAW, "inventory": choices})


def test_indexed_builder_cannot_bypass_payload_policy() -> None:
    """A reviewed builder still needs exact wire-key and primitive-value proof."""
    spec = replace(contract(), builder=lambda _raw, _changes: {"unreviewed": "1"})
    with pytest.raises(ConfigurationError, match="invalid_contract_payload"):
        spec.build(RAW, {"members": ["a"]})
    spec = replace(contract(), builder=lambda _raw, _changes: {"member[0]": ["a"]})
    with pytest.raises(ConfigurationError, match="invalid_contract_payload"):
        spec.build(RAW, {"members": ["a"]})


async def test_whole_inventory_change_rejects_stale_selection() -> None:
    """Changes outside the selected row invalidate its stale editor."""
    spec = contract()
    session = ConfigurationSession()
    read = AsyncMock(
        side_effect=[RAW, {**RAW, "inventory": (("a", "First"), ("c", "Third"))}]
    )
    write = AsyncMock()
    loaded = await session.read(spec, OWNER, read)
    assert "choices" in loaded
    with pytest.raises(ConfigurationError, match="stale_settings"):
        await session.save(
            spec,
            OWNER,
            loaded["revision"],
            {"members": ["b"]},
            confirmed=True,
            confirmation_text=spec.confirmation,
            read=read,
            write=write,
        )
    write.assert_not_awaited()


async def test_target_readback_does_not_hide_damage_to_other_rows() -> None:
    """Matching the target alone does not verify a whole-list submission."""
    spec = replace(
        contract(),
        verifier=lambda before, _changes, after: after["other"] == before["other"],
    )
    session = ConfigurationSession()
    read = AsyncMock(
        side_effect=[RAW, RAW] + [{**RAW, "members": ["b"], "other": "changed"}] * 4
    )
    write = AsyncMock()
    loaded = await session.read(spec, OWNER, read)
    with (
        patch(
            "custom_components.speedport_smart.configuration_session.asyncio.sleep",
            new=AsyncMock(),
        ),
        pytest.raises(ConfigurationError, match="action_verification_failed"),
    ):
        await session.save(
            spec,
            OWNER,
            loaded["revision"],
            {"members": ["b"]},
            confirmed=True,
            confirmation_text=spec.confirmation,
            read=read,
            write=write,
        )
    write.assert_awaited_once()


def test_identifier_order_is_canonical() -> None:
    """Selection order has no effect on readback and never mutates caller data."""
    field = SettingsField("ids", "IDs", "identifiers", dynamic_choices=True)
    original = ["b", "a"]
    assert field.validate(original) == ["a", "b"]
    assert original == ["b", "a"]
