"""Hub-owned two-stage online account linking, with no automatic second write."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState

from .configuration import ConfigurationError
from .configuration_phonebook_accounts import (
    PHONEBOOK_ACCOUNTS_ENDPOINT,
    PHONEBOOK_ACCOUNTS_REFERER,
    phonebook_account_rows,
)
from .const import DOMAIN
from .phonebook_link import online_phonebook_link_stage

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .configuration import SettingsContract
    from .hub import SpeedportHub


def _require_current_requester(hub: SpeedportHub, requester: tuple[str, str]) -> str:
    """Recheck live HA identity after reads and before each mutation."""
    entry_id = hub._entry_id  # noqa: SLF001
    if entry_id is None:
        raise ConfigurationError("stale_settings")
    entry = hub.hass.config_entries.async_get_entry(entry_id)
    token = hub.hass.auth.async_get_refresh_token(requester[1])
    if (
        hub._closed  # noqa: SLF001
        or entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
        or entry.runtime_data is not hub
        or token is None
        or token.user.id != requester[0]
        or not token.user.is_admin
        or not token.user.is_active
    ):
        raise ConfigurationError("administrator_required")
    return entry_id


async def begin_online_phonebook_link(  # noqa: PLR0917
    hub: SpeedportHub,
    contract: SettingsContract,
    target_id: str,
    requester: tuple[str, str],
    revision: str,
    changes: Mapping[str, Any],
    *,
    confirmed: bool,
    confirmation_text: str,
) -> dict[str, Any]:
    """Consume a settings approval, send one credential form, issue step-two grant."""
    raw, _, owned = await hub._configuration_session.consume(  # noqa: SLF001
        contract,
        requester,
        revision,
        changes,
        confirmed=confirmed,
        confirmation_text=confirmation_text,
        read=lambda: hub.client.read_configuration(contract.id, target_id),
    )
    try:
        entry_id = _require_current_requester(hub, requester)
        # Validate before any mutation and never infer a second write from this ACK.
        payload = contract.build(raw, owned)
        payload.clear()
        try:
            response = await hub.client.save_configuration(
                contract.id, raw, owned, target_id
            )
        finally:
            hub._configuration_session.clear()  # noqa: SLF001
            hub.online_phonebook_session.clear()
        stage = online_phonebook_link_stage(
            raw,
            target_id,
            username=owned["onlbuch_bname"],
            domain=owned.get("onlbuch_domain", "0"),
            response=response,
        )
        pending = hub.online_phonebook_session.issue(
            stage,
            requester=requester,
            entry_id=entry_id,
            local_inventory=raw["local_inventory"],
        )
        return {
            "status": "pending_confirmation",
            **pending,
            "target_id": target_id,
            "phonebook_id": int(stage.book_number),
        }
    finally:
        owned.clear()


async def finish_online_phonebook_link(
    hub: SpeedportHub,
    *,
    requester: tuple[str, str],
    pending_link: str,
    target_id: str,
    phonebook_id: int,
    confirmed: bool,
    confirmation_text: str,
    merge_existing: bool,
) -> dict[str, Any]:
    """Consume exact continuation permission before one explicit merge/replace POST."""
    entry_id = _require_current_requester(hub, requester)
    if hub.online_phonebook_session.context(
        pending_link,
        requester=requester,
        entry_id=entry_id,
    ) != (target_id, phonebook_id):
        raise ConfigurationError("stale_settings")
    inventory = await hub.client._phonebook_transfer_inventory(phonebook_id)  # noqa: SLF001
    rows = phonebook_account_rows(inventory["books"])
    if not any(
        row["id"] == target_id and row["onlbuch_nr"] == str(phonebook_id)
        for row in rows
    ):
        raise ConfigurationError("stale_settings")
    payload = hub.online_phonebook_session.consume(
        pending_link,
        requester=requester,
        entry_id=entry_id,
        confirmed=confirmed,
        confirmation_text=confirmation_text,
        merge_existing=merge_existing,
        fresh_book=inventory["books"],
        fresh_local_inventory=inventory["content"],
    )
    if payload["id"] != target_id:
        raise ConfigurationError("stale_settings")
    _require_current_requester(hub, requester)
    try:
        await hub.client._post_ephemeral_action(  # noqa: SLF001
            PHONEBOOK_ACCOUNTS_ENDPOINT,
            payload,
            referer=PHONEBOOK_ACCOUNTS_REFERER,
            require_status_ok=True,
        )
    finally:
        payload.clear()
        hub.invalidate_file_transfer_state()
    # Account linkage ACK does not prove asynchronous cloud synchronization or
    # deduplication. Do not manufacture a count-based success from that response.
    return {"status": "outcome_unknown", "verification": "manual_required"}
