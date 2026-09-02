"""Closed resolution of scalar editors and existing, explicitly selected rows."""

from dataclasses import replace
from typing import Any

from .configuration import ConfigurationError, SettingsContract, settings_contracts
from .configuration_media import (
    MEDIA_TARGET_SPECS,
    media_target_contract,
    media_target_metadata,
    media_target_rows,
)
from .configuration_mesh import (
    MESH_TARGET_SPECS,
    mesh_target_contract,
    mesh_target_metadata,
    mesh_target_rows,
)
from .configuration_network_rules import (
    NETWORK_RULE_TARGET_SPECS,
    network_rule_target_contract,
    network_rule_target_metadata,
    network_rule_target_rows,
)
from .configuration_parental import (
    PARENTAL_TARGET_SPECS,
    parental_target_contract,
    parental_target_metadata,
    parental_target_rows,
)
from .configuration_phone_assignments import (
    ASSIGNMENT_TARGET_SPECS,
    assignment_target_contract,
    assignment_target_metadata,
    assignment_target_rows,
)
from .configuration_phone_numbers import (
    NUMBER_TARGET_SPECS,
    number_target_contract,
    number_target_metadata,
    number_target_rows,
)
from .configuration_phone_providers import (
    PROVIDER_TARGET_SPECS,
    provider_target_contract,
    provider_target_metadata,
    provider_target_rows,
)
from .configuration_phone_targets import (
    PHONE_TARGET_SPECS,
    phone_target_contract,
    phone_target_metadata,
    phone_target_rows,
)
from .configuration_phonebook import (
    PHONEBOOK_SETTING_ID,
    phonebook_contact_metadata,
    phonebook_contact_settings,
)
from .configuration_phonebook_accounts import (
    PHONEBOOK_ACCOUNT_TARGET_SPECS,
    phonebook_account_contract,
    phonebook_account_metadata,
    phonebook_account_targets,
)
from .configuration_phonebook_assignment import (
    PHONEBOOK_ASSIGN_TARGET_SPECS,
    phonebook_assignment_contract,
    phonebook_assignment_metadata,
    phonebook_assignment_rows,
)
from .configuration_phonebook_lifecycle import (
    PHONEBOOK_CREATE_SETTING_ID,
    phonebook_create_metadata,
    phonebook_create_settings,
)
from .configuration_phonebook_link import (
    PHONEBOOK_LINK_TARGET_SPECS,
    phonebook_link_contract,
    phonebook_link_metadata,
    phonebook_link_rows,
)
from .configuration_port_blocking import (
    PORT_BLOCKING_TARGET_SPECS,
    port_blocking_target_contract,
    port_blocking_target_metadata,
    port_blocking_target_rows,
)
from .configuration_powerline import (
    POWERLINE_TARGET_SPECS,
    powerline_target_contract,
    powerline_target_metadata,
    powerline_target_rows,
)
from .configuration_routing_exceptions import (
    ROUTING_EXCEPTION_TARGET_SPECS,
    routing_exception_target_contract,
    routing_exception_target_metadata,
    routing_exception_target_rows,
)
from .configuration_storage import (
    NAS_SHARE_SETTING_ID,
    nas_share_settings,
    nas_share_settings_metadata,
)
from .configuration_vpn import (
    VPN_TARGET_SPECS,
    vpn_target_contract,
    vpn_target_metadata,
    vpn_target_rows,
)
from .storage_lifecycle import (
    STORAGE_TARGET_SPECS,
    storage_target_contract,
    storage_target_metadata,
    storage_target_rows,
)


def target_settings_ids() -> frozenset[str]:
    """Return only reviewed target-bound editor IDs."""
    return frozenset(
        (
            NAS_SHARE_SETTING_ID,
            *PHONE_TARGET_SPECS,
            *ASSIGNMENT_TARGET_SPECS,
            *PROVIDER_TARGET_SPECS,
            *NETWORK_RULE_TARGET_SPECS,
            *MEDIA_TARGET_SPECS,
            *MESH_TARGET_SPECS,
            *PORT_BLOCKING_TARGET_SPECS,
            *STORAGE_TARGET_SPECS,
            *PARENTAL_TARGET_SPECS,
            *NUMBER_TARGET_SPECS,
            *VPN_TARGET_SPECS,
            *PHONEBOOK_ASSIGN_TARGET_SPECS,
            *PHONEBOOK_ACCOUNT_TARGET_SPECS,
            *PHONEBOOK_LINK_TARGET_SPECS,
            *POWERLINE_TARGET_SPECS,
            *ROUTING_EXCEPTION_TARGET_SPECS,
            PHONEBOOK_SETTING_ID,
            PHONEBOOK_CREATE_SETTING_ID,
        )
    )


def target_settings_metadata() -> list[dict[str, Any]]:
    """Describe existing-row editors without choosing an invented target."""
    metadata = [
        nas_share_settings_metadata(),
        *phone_target_metadata(),
        *assignment_target_metadata(),
        *provider_target_metadata(),
        *network_rule_target_metadata(),
        *media_target_metadata(),
        *mesh_target_metadata(),
        *port_blocking_target_metadata(),
        *storage_target_metadata(),
        *parental_target_metadata(),
        *number_target_metadata(),
        *vpn_target_metadata(),
        *phonebook_assignment_metadata(),
        *phonebook_account_metadata(),
        *phonebook_link_metadata(),
        *powerline_target_metadata(),
        *routing_exception_target_metadata(),
        phonebook_contact_metadata(),
        phonebook_create_metadata(),
    ]
    for item in metadata:
        item["target_limit"] = target_settings_limit(item["id"])
    return metadata


def target_settings_limit(setting_id: str) -> int:
    """Bound each reviewed inventory without truncating valid nested targets."""
    if setting_id in {"port_forward_range_edit", "port_forward_range_delete"}:
        return 2048
    if setting_id == PHONEBOOK_SETTING_ID:
        return 5000
    return 64


def target_settings_read_pairs() -> frozenset[tuple[str, str]]:
    """Keep page tokens scoped to exact reviewed target reads."""
    return frozenset(
        (source[0], source[1])
        for setting_id in target_settings_ids()
        if (source := target_settings_source(setting_id)) is not None
    ) | frozenset(
        {
            ("data/InternetConnection.json", "html/content/phone/phone_internet.html"),
            ("data/PhoneOnlbuch.json", "html/content/phone/phone_book_assign.html"),
        }
    )


def target_settings_source(setting_id: str) -> tuple[str, str, str, str] | None:
    """Return a fixed endpoint, referer, label field and title for a reviewed family."""
    for specs in (
        PHONE_TARGET_SPECS,
        ASSIGNMENT_TARGET_SPECS,
        PROVIDER_TARGET_SPECS,
        NETWORK_RULE_TARGET_SPECS,
        MEDIA_TARGET_SPECS,
        MESH_TARGET_SPECS,
        PORT_BLOCKING_TARGET_SPECS,
        STORAGE_TARGET_SPECS,
        PARENTAL_TARGET_SPECS,
        NUMBER_TARGET_SPECS,
        VPN_TARGET_SPECS,
        PHONEBOOK_ASSIGN_TARGET_SPECS,
        PHONEBOOK_ACCOUNT_TARGET_SPECS,
        PHONEBOOK_LINK_TARGET_SPECS,
        POWERLINE_TARGET_SPECS,
        ROUTING_EXCEPTION_TARGET_SPECS,
    ):
        spec = specs.get(setting_id)
        if spec is not None:
            return (
                getattr(spec, "read_endpoint", spec.endpoint),
                getattr(spec, "read_referer", None) or spec.referer,
                spec.label_key,
                spec.title,
            )
    return None


def target_settings_rows(
    setting_id: str, raw: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Resolve only an explicitly reviewed collection parser."""
    if setting_id in PHONE_TARGET_SPECS:
        return phone_target_rows(setting_id, raw)
    if setting_id in PARENTAL_TARGET_SPECS:
        return parental_target_rows(setting_id, raw)
    if setting_id in NUMBER_TARGET_SPECS:
        return number_target_rows(setting_id, raw)
    if setting_id in VPN_TARGET_SPECS:
        return vpn_target_rows(setting_id, raw)
    if setting_id in PHONEBOOK_ASSIGN_TARGET_SPECS:
        return phonebook_assignment_rows(setting_id, raw)
    if setting_id in PHONEBOOK_ACCOUNT_TARGET_SPECS:
        return phonebook_account_targets(setting_id, raw)
    if setting_id in PHONEBOOK_LINK_TARGET_SPECS:
        return phonebook_link_rows(setting_id, raw)
    if setting_id in POWERLINE_TARGET_SPECS:
        return powerline_target_rows(setting_id, raw)
    if setting_id in ROUTING_EXCEPTION_TARGET_SPECS:
        return routing_exception_target_rows(setting_id, raw)
    if setting_id in MEDIA_TARGET_SPECS:
        return media_target_rows(setting_id, raw)
    if setting_id in MESH_TARGET_SPECS:
        return mesh_target_rows(setting_id, raw)
    if setting_id in PORT_BLOCKING_TARGET_SPECS:
        return port_blocking_target_rows(setting_id, raw)
    if setting_id in STORAGE_TARGET_SPECS:
        return storage_target_rows(setting_id, raw)
    if setting_id in ASSIGNMENT_TARGET_SPECS:
        return assignment_target_rows(setting_id, raw)
    if setting_id in PROVIDER_TARGET_SPECS:
        return provider_target_rows(setting_id, raw)
    if setting_id in NETWORK_RULE_TARGET_SPECS:
        return network_rule_target_rows(setting_id, raw)
    raise ConfigurationError("setting_unavailable")


def resolve_settings_contract(
    setting_id: str, target_id: str | None = None
) -> SettingsContract:
    """Bind the exact target to every grant, even when rows share equal values."""
    contract = _resolve_settings_contract(setting_id, target_id)
    return (
        replace(contract, target_scope=target_id) if target_id is not None else contract
    )


def _resolve_settings_contract(
    setting_id: str, target_id: str | None = None
) -> SettingsContract:
    if setting_id in PHONEBOOK_LINK_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return phonebook_link_contract(setting_id, target_id)
    if setting_id in ROUTING_EXCEPTION_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return routing_exception_target_contract(setting_id, target_id)
    if setting_id in PHONEBOOK_ACCOUNT_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return phonebook_account_contract(setting_id, target_id)
    if setting_id in POWERLINE_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return powerline_target_contract(setting_id, target_id)
    """Resolve a static form; a target never selects an endpoint or payload key."""
    if setting_id in PHONEBOOK_ASSIGN_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return phonebook_assignment_contract(setting_id, target_id)
    if setting_id in PARENTAL_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return parental_target_contract(setting_id, target_id)
    if setting_id in NUMBER_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return number_target_contract(setting_id, target_id)
    if setting_id in VPN_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return vpn_target_contract(setting_id, target_id)
    if setting_id in STORAGE_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return storage_target_contract(setting_id, target_id)
    if setting_id in MEDIA_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return media_target_contract(setting_id, target_id)
    if setting_id in MESH_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return mesh_target_contract(setting_id, target_id)
    if setting_id in PORT_BLOCKING_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return port_blocking_target_contract(setting_id, target_id)
    if setting_id in {PHONEBOOK_SETTING_ID, PHONEBOOK_CREATE_SETTING_ID}:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return (
            phonebook_contact_settings(target_id)
            if setting_id == PHONEBOOK_SETTING_ID
            else phonebook_create_settings(target_id)
        )
    if setting_id == NAS_SHARE_SETTING_ID:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return nas_share_settings(target_id)
    if setting_id in PHONE_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return phone_target_contract(setting_id, target_id)
    if setting_id in ASSIGNMENT_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return assignment_target_contract(setting_id, target_id)
    if setting_id in PROVIDER_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return provider_target_contract(setting_id, target_id)
    if setting_id in NETWORK_RULE_TARGET_SPECS:
        if target_id is None:
            raise ConfigurationError("settings_target_required")
        return network_rule_target_contract(setting_id, target_id)
    if target_id is not None:
        raise ConfigurationError("invalid_settings_target")
    contract = settings_contracts().get(setting_id)
    if contract is None:
        raise ConfigurationError("setting_unavailable")
    return contract
