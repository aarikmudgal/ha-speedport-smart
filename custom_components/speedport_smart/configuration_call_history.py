"""
Private call-history adapters for the reviewed one-shot settings boundary.

These functions never contact the router, retain histories or publish them to
entities. The read/export helpers belong only in the existing administrator-only
private-query response; the clear editor exposes no call-record fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from .call_history import (
    CALL_HISTORY_READ_ENDPOINT,
    CALL_HISTORY_SPECS,
    call_history_clear_payload,
    call_history_spec,
    export_call_history_csv,
    read_call_history,
    verify_call_history_clear,
)
from .configuration import ConfigurationError, SettingsContract, boolean

if TYPE_CHECKING:
    from .configuration import SettingValues

_CLEAR: Final = boolean("clear_history", "Permanently clear this call list")


def call_history_read_source(category: str) -> tuple[str, str]:
    """Resolve an exact private GET pair from a closed category selector."""
    spec = call_history_spec(category)
    return CALL_HISTORY_READ_ENDPOINT, spec.referer


def call_history_private_read(raw: SettingValues, category: str) -> dict[str, Any]:
    """Project a fresh bounded list only for its requesting administrator."""
    return read_call_history(raw, category)


def call_history_private_export(raw: SettingValues, category: str) -> dict[str, Any]:
    """Return a local formula-safe CSV through the existing ephemeral download seam."""
    spec = call_history_spec(category)
    return {
        "category": spec.id,
        "private_download": {
            "filename": f"Speedport-{spec.id}-calls.csv",
            "media_type": "text/csv;charset=utf-8",
            "content": export_call_history_csv(raw, spec.id),
        },
    }


def _contract(category: str) -> SettingsContract:
    spec = call_history_spec(category)

    def read(raw: SettingValues) -> dict[str, Any]:
        return {"clear_history": read_call_history(raw, category)["total"] == 0}

    def build(
        raw: SettingValues, changes: SettingValues
    ) -> dict[str, str | int | bool]:
        if changes != {"clear_history": True}:
            raise ConfigurationError("call_history_clear_confirmation_required")
        return dict(call_history_clear_payload(raw, category))

    def revision(raw: SettingValues) -> dict[str, Any]:
        # Complete observed records participate only in the session HMAC. Calls
        # arriving before save invalidate the destructive draft, even when its
        # public checkbox remains false. Never retain records in a grant.
        read_call_history(raw, category)
        return {
            name: read_call_history(raw, name)
            for name, other in CALL_HISTORY_SPECS.items()
            if other.collection in raw
        }

    def verify(
        before: SettingValues, changes: SettingValues, after: SettingValues
    ) -> bool:
        try:
            build(before, changes)
            return verify_call_history_clear(before, after, category)
        except ConfigurationError:
            return False

    return SettingsContract(
        f"call_history_clear_{category}",
        f"Clear {spec.title.lower()}",
        "Telephony",
        spec.clear_endpoint,
        spec.referer,
        (_CLEAR,),
        read_endpoint=CALL_HISTORY_READ_ENDPOINT,
        reader=read,
        builder=build,
        revision_values=revision,
        verifier=verify,
        acknowledgement="readback",
        payload_keys=frozenset({"action_clearlist"}),
        confirmation=f"CLEAR {spec.id.upper()} CALLS",
        warning=(
            f"Permanently deletes only the router's {spec.title.lower()} history. "
            "Export this private list first if needed. The clear is sent once. "
            "An absent list or a new call after clearing leaves the result "
            "uncertain; inspect the router before trying again."
        ),
    )


CALL_HISTORY_SETTINGS: Final = tuple(
    _contract(category) for category in CALL_HISTORY_SPECS
)
