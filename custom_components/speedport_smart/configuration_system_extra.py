"""Reviewed email, EasySupport and router-display configuration forms."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    SettingValues,
    boolean,
    choice,
)

_MAX_DEPENDENCY_NUMBER: Final = 99_999_999
_EXTERNAL_5G_TYPE: Final = 3
_TETHERING_ONLINE: Final = 2
_MIN_PROVISIONING_LENGTH: Final = 2
_MAX_PROVISIONING_LENGTH: Final = 32
_MAX_DISPLAY_RULES: Final = 64
_MAX_RULE_NAME: Final = 20
_FIRST_PRINTABLE: Final = 32
_DELETE_CHARACTER: Final = 127
_MAX_EMAIL_TEXT: Final = 255
_EMAIL_DOMAINS: Final = (("0", "@t-online.de"), ("1", "@magenta.de"))
_EMAIL_EVENT_LABELS: Final = (
    ("email_ev1", "Router firmware available"),
    ("email_ev2", "Router firmware installed"),
    ("email_ev4", "Internet IP address changed"),
    ("email_ev5", "Incoming calls"),
    ("email_ev6", "Daily status report"),
    ("email_ev7", "Security events"),
    ("email_ev8", "VPN login and logout"),
    ("email_ev9", "Mesh firmware available"),
    ("email_ev10", "Mesh firmware installed"),
    ("email_ev11", "Switch between fixed and mobile internet"),
    ("email_ev12", "Daily call report"),
    ("email_ev13", "VPN connection created"),
    ("email_ev14", "SIM status (mobile receiver only)"),
    ("email_ev15", "Mobile receiver connection lost"),
)
_EMAIL_MOBILE_EVENTS: Final = frozenset({"email_ev14", "email_ev15"})
_EMAIL_SELECTS: Final = ("email_provider", "email_t_domain", "email_port")
_EMAIL_FIELDS: Final = (
    boolean("email_active", "Enable email notifications"),
    choice("email_provider", "Email provider", (("0", "Telekom"), ("1", "Other"))),
    SettingsField(
        "email_t_username", "Telekom mailbox name", "text", maximum=_MAX_EMAIL_TEXT
    ),
    choice("email_t_domain", "Telekom email domain", _EMAIL_DOMAINS),
    SettingsField(
        "email_t_password",
        "New Telekom email password",
        "secret",
        minimum=1,
        maximum=_MAX_EMAIL_TEXT,
    ),
    SettingsField(
        "email_other_username",
        "Other-provider username",
        "text",
        maximum=_MAX_EMAIL_TEXT,
    ),
    SettingsField(
        "email_other_password",
        "New other-provider email password",
        "secret",
        minimum=1,
        maximum=_MAX_EMAIL_TEXT,
    ),
    SettingsField("email_smtp", "SMTP server", "text", maximum=_MAX_EMAIL_TEXT),
    choice("email_port", "SMTP port", (("25", "25"), ("465", "465"), ("587", "587"))),
    boolean("samerecip", "Use the sender address as recipient"),
    SettingsField(
        "email_sendto", "Separate recipient address", "text", maximum=_MAX_EMAIL_TEXT
    ),
    *(boolean(name, label) for name, label in _EMAIL_EVENT_LABELS),
    choice(
        "email_ev5_type",
        "Which incoming calls",
        (("0", "Missed calls"), ("1", "All incoming calls")),
    ),
)
_EMAIL_ACCOUNT_FIELDS: Final = frozenset(
    field.name
    for field in _EMAIL_FIELDS
    if not field.name.startswith("email_ev") and field.name != "email_active"
)

_SUPPORT_FIELDS: Final = (
    boolean("easy_support_deactive", "Disable EasySupport"),
    boolean("autofw_deactive", "Disable automatic firmware updates"),
)
_SUPPORT_DEPENDENCIES: Final = (
    "inet_isp",
    "other_dt",
    "onlinestatus",
    "auto_external_modem",
    "extwan_typ",
    "use_tethering",
    "tethering_status",
    "provis_inet",
    "bngnumbers",
)
_DISPLAY: Final = SettingsField(
    "disptime",
    "Rule controlled by the router display",
    "enum",
    dynamic_choices=True,
    description=(
        "Select an existing parental-control rule, or No rule. "
        "The selected rule and complete rule inventory are checked again before saving."
    ),
)


def _flag(raw: SettingValues, name: str) -> bool:
    value = boolean(name, name).read(raw)
    if type(value) is not bool:
        raise ConfigurationError("settings_unavailable")
    return value


def _number(raw: SettingValues, name: str) -> int:
    value = raw.get(name)
    if type(value) is str and re.fullmatch(r"[0-9]{1,8}", value):
        return int(value)
    if type(value) is int and 0 <= value <= _MAX_DEPENDENCY_NUMBER:
        return value
    raise ConfigurationError("settings_unavailable")


def _support_read(raw: SettingValues) -> dict[str, Any]:
    return {field.name: field.read(raw) for field in _SUPPORT_FIELDS}


def _support_context(raw: SettingValues) -> tuple[bool, bool]:
    """Apply the firmware's provider, connectivity and BNG routing conditions."""
    provider = _number(raw, "inet_isp")
    other_telekom = _flag(raw, "other_dt")
    external = _flag(raw, "auto_external_modem")
    ext_type = _number(raw, "extwan_typ")
    tethering = _flag(raw, "use_tethering")
    tethering_status = _number(raw, "tethering_status")
    online = raw.get("onlinestatus")
    if not isinstance(online, str) or not online:
        raise ConfigurationError("settings_unavailable")
    if provider not in {0, 99} and not other_telekom:
        raise ConfigurationError("easysupport_provider_unavailable")
    if online != "online" and (
        (external and ext_type == _EXTERNAL_5G_TYPE)
        or (tethering and tethering_status == _TETHERING_ONLINE)
    ):
        raise ConfigurationError("easysupport_connection_unavailable")
    provisioning = raw.get("provis_inet")
    if (
        not isinstance(provisioning, str)
        or not _MIN_PROVISIONING_LENGTH <= len(provisioning) <= _MAX_PROVISIONING_LENGTH
    ):
        raise ConfigurationError("settings_unavailable")
    return provisioning[1] == "4", _number(raw, "bngnumbers") != 0


def _support_build(
    raw: SettingValues, changes: SettingValues, *, route: str
) -> dict[str, str | int | bool]:
    """Match one actual checkbox callback, including its coupled second flag."""
    before = _support_read(raw)
    configured, profile = _support_context(raw)
    changed = {key: value for key, value in changes.items() if before[key] != value}
    if not changed:
        key = next(iter(changes))
        return {key: "1" if before[key] else "0"}
    for primary, selected in changed.items():
        payload: dict[str, str | int | bool] = {primary: "1" if selected else "0"}
        selected_route = "standard"
        if primary == "easy_support_deactive":
            if selected:
                if profile:
                    selected_route = "bng_deactivation"
            else:
                if configured:
                    selected_route = "bng_activation"
                if configured or before["autofw_deactive"]:
                    payload["autofw_deactive"] = "0"
        elif selected and not before["easy_support_deactive"]:
            payload["easy_support_deactive"] = "1"
            if profile:
                selected_route = "bng_deactivation"
        after = {**before, **{key: value == "1" for key, value in payload.items()}}
        if all(after[key] == value for key, value in changes.items()):
            if selected_route != route:
                raise ConfigurationError("easysupport_branch_unavailable")
            return payload
    raise ConfigurationError("easysupport_incompatible_changes")


def _standard_support(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    return _support_build(raw, changes, route="standard")


def _activate_bng(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    return _support_build(raw, changes, route="bng_activation")


def _deactivate_bng(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    return _support_build(raw, changes, route="bng_deactivation")


def _rule_id(value: object) -> str:
    if type(value) is int and value >= 0:
        value = str(value)
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value) is None
    ):
        raise ConfigurationError("display_rule_unavailable")
    return value


def oled_rule_choices(raw: SettingValues) -> tuple[tuple[str, str], ...]:
    """Return current administrator-only choices after full inventory validation."""
    source = raw.get("addtime")
    if isinstance(source, Mapping):
        rows = [source] if source else []
    elif isinstance(source, list):
        rows = source
    else:
        raise ConfigurationError("display_rule_unavailable")
    if len(rows) > _MAX_DISPLAY_RULES or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ConfigurationError("display_rule_unavailable")
    choices = [("0", "No rule")]
    seen = {"0"}
    for row in rows:
        rule_id = _rule_id(row.get("id"))
        name = row.get("timerule_name")
        if (
            rule_id in seen
            or not isinstance(name, str)
            or not 1 <= len(name) <= _MAX_RULE_NAME
            or any(
                ord(char) < _FIRST_PRINTABLE or ord(char) == _DELETE_CHARACTER
                for char in name
            )
        ):
            raise ConfigurationError("display_rule_unavailable")
        seen.add(rule_id)
        choices.append((rule_id, name))
    return tuple(choices)


def _display_read(raw: SettingValues) -> dict[str, str]:
    selected = _rule_id(raw.get("disptime"))
    if selected not in {key for key, _label in oled_rule_choices(raw)}:
        raise ConfigurationError("display_rule_unavailable")
    return {"disptime": selected}


def _display_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    _display_read(raw)
    selected = _rule_id(changes.get("disptime", raw.get("disptime")))
    if selected not in {key for key, _label in oled_rule_choices(raw)}:
        raise ConfigurationError("display_rule_unavailable")
    return {"disptime": selected}


def _display_choices(raw: SettingValues) -> Mapping[str, tuple[tuple[str, str], ...]]:
    return {"disptime": oled_rule_choices(raw)}


def _sender(values: SettingValues) -> str:
    if values["email_provider"] == "0":
        username = str(values["email_t_username"])
        return (
            username + dict(_EMAIL_DOMAINS)[values["email_t_domain"]]
            if username
            else ""
        )
    return str(values["email_other_username"])


def _email_read(raw: SettingValues) -> dict[str, Any]:
    """Read the complete non-secret form and derive the UI-only recipient checkbox."""
    source = dict(raw)
    _flag(raw, "use_lte")
    # These two fields have an observed explicit empty sentinel. Their static
    # checkboxes have no value attribute; jsonvariables.js parseOption therefore
    # renders empty as unchecked, including with an enabled mobile receiver.
    # Do not broaden this to missing fields or any other malformed flag.
    for name in _EMAIL_MOBILE_EVENTS:
        if source.get(name) == "":
            source[name] = "0"
    values = {
        field.name: field.read(source)
        for field in _EMAIL_FIELDS
        if field.kind != "secret" and field.name != "samerecip"
    }
    values["samerecip"] = _sender(values).lower() == str(values["email_sendto"]).lower()
    return values


def _email_account_payload(
    before: SettingValues, values: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Simulate opening the account editor without replaying a masked password."""
    telekom = values["email_provider"] == "0"
    username = "email_t_username" if telekom else "email_other_username"
    password = "email_t_password" if telekom else "email_other_password"
    hidden = (
        {"email_other_username", "email_other_password", "email_smtp", "email_port"}
        if telekom
        else {"email_t_username", "email_t_password", "email_t_domain"}
    )
    if any(name in changes and changes[name] != before.get(name) for name in hidden):
        raise ConfigurationError("email_inactive_fields")
    if password not in changes:
        raise ConfigurationError("email_password_required")
    if not values[username] or (not telekom and not values["email_smtp"]):
        raise ConfigurationError("email_account_required")
    recipient = _sender(values) if values["samerecip"] else values["email_sendto"]
    if (
        not isinstance(recipient, str)
        or not 1 <= len(recipient) <= _MAX_EMAIL_TEXT
        or re.fullmatch(r".+@.+\..+", recipient) is None
    ):
        raise ConfigurationError("email_recipient_required")
    # The firmware overwrites the recipient from the sender when this checkbox
    # is visible. Do not silently discard an explicitly edited separate address.
    if values["samerecip"] and (
        "email_sendto" in changes
        and changes["email_sendto"] != before["email_sendto"]
        and changes["email_sendto"] != recipient
    ):
        raise ConfigurationError("email_recipient_conflict")
    payload: dict[str, str | int | bool] = {
        username: values[username],
        password: changes[password],
        "email_sendto": recipient,
    }
    if not telekom:
        payload["email_smtp"] = values["email_smtp"]
    if values["samerecip"]:
        payload["samerecip"] = "1"
    return payload


def _email_build(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Mirror visibility, always-submitted selects and dependent event controls."""
    before = _email_read(raw)
    mobile = _flag(raw, "use_lte")
    values = {**before, **changes}
    changed = {name for name in changes if changes[name] != before.get(name)}
    payload: dict[str, str | int | bool] = {
        "email_active": "1" if values["email_active"] else "0",
        **{name: values[name] for name in _EMAIL_SELECTS},
    }
    if not values["email_active"]:
        if changed - {"email_active"}:
            raise ConfigurationError("email_inactive_fields")
        return payload
    if not mobile and changed & _EMAIL_MOBILE_EVENTS:
        raise ConfigurationError("email_inactive_fields")
    if not values["email_ev5"] and "email_ev5_type" in changed:
        raise ConfigurationError("email_inactive_fields")
    if values["email_ev6"] and "email_ev12" in changed:
        raise ConfigurationError("email_daily_report_dependency")
    events = [
        name
        for name, _label in _EMAIL_EVENT_LABELS
        if mobile or name not in _EMAIL_MOBILE_EVENTS
    ]
    if not any(values[name] for name in events):
        raise ConfigurationError("email_event_required")
    payload.update({name: "1" if values[name] else "0" for name in events})
    if values["email_ev5"]:
        payload["email_ev5_type"] = values["email_ev5_type"]
    if changed & _EMAIL_ACCOUNT_FIELDS or not before["email_sendto"]:
        payload.update(_email_account_payload(before, values, changes))
    return payload


def _email_expected(raw: SettingValues, changes: SettingValues) -> dict[str, Any]:
    # samerecip is derived from the saved addresses, never a backend state claim.
    return _email_read({**raw, **_email_build(raw, changes)})


SYSTEM_EXTRA_SETTINGS: tuple[SettingsContract, ...] = (
    SettingsContract(
        "system_email_notifications",
        "Email notifications",
        "System",
        "data/EMailNotify.json",
        "html/content/config/notify.html",
        _EMAIL_FIELDS,
        reader=_email_read,
        builder=_email_build,
        expected_values=_email_expected,
        revision_fields=("use_lte",),
        warning=(
            "Notifications can include private network and call information sent "
            "to the selected mailbox. Account or recipient edits require a freshly "
            "entered password for the selected provider; saved passwords are never "
            "shown or resubmitted. Event-only changes preserve the saved account. "
            "Daily status reports lock the separate daily-call checkbox. Mobile "
            "events require a mobile receiver. Readback verifies settings, not "
            "password correctness or email delivery."
        ),
        confirmation="SAVE EMAIL NOTIFICATIONS",
        payload_keys=frozenset(field.name for field in _EMAIL_FIELDS),
    ),
    SettingsContract(
        "system_easysupport",
        "EasySupport and automatic updates (standard)",
        "System",
        "data/Modules.json",
        "html/content/config/easy_support.html",
        _SUPPORT_FIELDS,
        read_endpoint="data/EasySupport.json",
        reader=_support_read,
        builder=_standard_support,
        acknowledgement="readback",
        revision_fields=_SUPPORT_DEPENDENCIES,
        warning=(
            "Disabling automatic firmware updates also disables EasySupport when "
            "it is active. Enabling EasySupport also enables automatic updates. "
            "BNG provisioning can require one of the separate BNG branches; this "
            "standard editor rejects those branches before sending."
        ),
        confirmation="CHANGE EASYSUPPORT",
        payload_keys=frozenset(field.name for field in _SUPPORT_FIELDS),
    ),
    SettingsContract(
        "system_easysupport_bng_activation",
        "Enable EasySupport for BNG provisioning",
        "System",
        "data/EasySupport.json",
        "html/content/config/easy_support.html",
        _SUPPORT_FIELDS,
        reader=_support_read,
        builder=_activate_bng,
        acknowledgement="readback",
        readback_policy="reconnect_required",
        revision_fields=_SUPPORT_DEPENDENCIES,
        warning=(
            "This exact BNG activation path enables EasySupport and automatic "
            "firmware updates, then restarts the router. It is accepted only when "
            "the fresh provisioning state requires this branch. Reconnect and "
            "inspect the state afterward; callback completion does not prove "
            "acceptance."
        ),
        confirmation="ENABLE BNG EASYSUPPORT",
        payload_keys=frozenset(field.name for field in _SUPPORT_FIELDS),
    ),
    SettingsContract(
        "system_easysupport_bng_deactivation",
        "Disable EasySupport with a BNG profile",
        "System",
        "data/EasySupport.json",
        "html/content/config/easy_support.html",
        _SUPPORT_FIELDS,
        reader=_support_read,
        builder=_deactivate_bng,
        acknowledgement="readback",
        revision_fields=_SUPPORT_DEPENDENCIES,
        warning=(
            "This BNG-profile branch disables EasySupport, and also disables "
            "automatic firmware updates if that checkbox is selected. It is "
            "accepted only for the exact current BNG state; both resulting flags "
            "must be read back independently."
        ),
        confirmation="DISABLE BNG EASYSUPPORT",
        payload_keys=frozenset(field.name for field in _SUPPORT_FIELDS),
    ),
    SettingsContract(
        "system_oled_display_rule",
        "Parental-control rule on the router display",
        "System",
        "data/OLEDtimerule.json",
        "html/content/internet/chd_timerules.html",
        (_DISPLAY,),
        read_endpoint="data/TimeRules.json",
        reader=_display_read,
        builder=_display_build,
        field_choices=_display_choices,
        revision_fields=("addtime",),
        warning=(
            "This selects which existing parental-control rule the router's "
            "display button can switch. It does not change a display timeout or "
            "edit the rule. Use 0 to remove the display assignment."
        ),
        confirmation="CHANGE DISPLAY RULE",
        payload_keys=frozenset({"disptime"}),
    ),
)
