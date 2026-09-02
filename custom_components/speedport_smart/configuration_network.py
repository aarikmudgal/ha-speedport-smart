"""Reviewed network form schemas and pure, conditional payload builders."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from .configuration import (
    ConfigurationError,
    SettingsContract,
    SettingsField,
    boolean,
    choice,
)
from .lan_management import (
    LAN_MUTATION_FIELDS,
    LanManagementValidationError,
    LanSnapshot,
    build_lan_ipv4_command,
    parse_lan_snapshot,
)

if TYPE_CHECKING:
    from .configuration import SettingValues

_NETWORK: Final = "html/content/network/"
_ASCII_MIN: Final = 32
_ASCII_MAX: Final = 126
_DIRECTION_SELECTABLE_CHANNELS: Final = range(5, 10)
_DHCP_FIELDS: Final = (
    boolean("lan_use_dhcp", "DHCP server"),
    SettingsField("lan_dhcp_from", "First address suffix", "integer", maximum=255),
    SettingsField("lan_dhcp_to", "Last address suffix", "integer", maximum=255),
    choice(
        "lan_dhcp_validtime",
        "Lease duration",
        (
            ("0", "30 minutes"),
            ("1", "1 hour"),
            ("2", "2 hours"),
            ("3", "6 hours"),
            ("4", "1 day"),
            ("5", "2 days"),
            ("6", "4 days"),
            ("7", "1 week"),
            ("8", "2 weeks"),
            ("9", "3 weeks"),
        ),
    ),
)
_FIVE_GHZ_CHANNELS: Final = {
    "0": (0, 36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112),
    "1": (0, 36, 44, 52, 60, 100, 108),
    "2": (0, 36, 52, 100),
    "3": (0, 36),
}


def _enum_options(*values: str) -> tuple[tuple[str, str], ...]:
    """Keep firmware mode IDs explicit where labels are not captured."""
    return tuple((value, f"Firmware mode {value}") for value in values)


_RADIO_FIELDS: Final = (
    choice(
        "wlan_band",
        "Active bands",
        (("0", "Both bands"), ("1", "2.4 GHz only"), ("2", "5 GHz only")),
    ),
    choice(
        "wlan_power", "Transmit power", (("0", "Full"), ("1", "Medium"), ("2", "Low"))
    ),
    choice("wlan_mode", "2.4 GHz mode", _enum_options("0", "2", "3")),
    choice("wlan_speed", "2.4 GHz bandwidth", (("0", "20 MHz"), ("1", "40 MHz"))),
    choice(
        "wlan_channel",
        "2.4 GHz channel",
        (("0", "Automatic"), *((str(value), str(value)) for value in range(1, 14))),
    ),
    choice(
        "wlan_channel_dir",
        "2.4 GHz extension channel",
        (("2", "Automatic"), ("0", "Above"), ("1", "Below")),
    ),
    choice("wlan_5ghz_mode", "5 GHz mode", _enum_options("0", "1", "2")),
    choice(
        "wlan_5ghz_speed",
        "5 GHz bandwidth",
        (("0", "20 MHz"), ("1", "40 MHz"), ("2", "80 MHz"), ("3", "160 MHz")),
    ),
    choice(
        "wlan_5ghz_channel",
        "5 GHz primary channel",
        (
            ("0", "Automatic"),
            *((str(value), str(value)) for value in _FIVE_GHZ_CHANNELS["0"] if value),
        ),
    ),
)
_IDENTITY_FIELDS: Final = (
    SettingsField("wlan_ssid", "2.4 GHz network name", "text", minimum=1, maximum=32),
    boolean("wlan_visible", "Broadcast 2.4 GHz network name"),
    SettingsField(
        "wlan_5ghz_ssid", "5 GHz network name", "text", minimum=1, maximum=32
    ),
    boolean("wlan_5ghz_visible", "Broadcast 5 GHz network name"),
    choice(
        "wlan_enc",
        "Encryption",
        (("6", "WPA3"), ("5", "WPA2/WPA3"), ("4", "WPA2"), ("0", "Unencrypted")),
    ),
    boolean("wlan_pmf", "Protected management frames (WPA2 only)"),
    SettingsField(
        "wlan_wpa_key",
        "Wi-Fi password",
        "secret",
        minimum=8,
        maximum=63,
        description="Unchanged passwords require an unmasked current router key.",
    ),
    boolean("wlan_display_key", "Display password on router"),
)
_DDNS_FIELDS: Final = (
    boolean("use_dyndns", "Dynamic DNS enabled"),
    choice(
        "dyndns_provider",
        "Provider",
        (
            ("", "Not configured — select a provider"),
            ("0", "Firmware provider 0"),
            ("1", "Firmware provider 1"),
            ("2", "Firmware provider 2"),
            ("3", "Firmware provider 3"),
            ("4", "Custom"),
        ),
    ),
    SettingsField("dyndns_domain", "Domain", "text", maximum=253),
    SettingsField("dyndns_user", "User name", "text", maximum=256),
    SettingsField("dyndns_password", "Password", "secret", minimum=1, maximum=256),
    SettingsField("dyndns_updsrv", "Custom update hostname", "text", maximum=253),
    choice(
        "dyndns_updprot",
        "Custom transport",
        (("", "Not configured — select transport"), ("0", "HTTP"), ("1", "HTTPS")),
    ),
    SettingsField(
        "dyndns_updport",
        "Custom port",
        "integer",
        maximum=65535,
        description=(
            "0 means not configured; an enabled custom provider requires 1-65535."
        ),
    ),
    SettingsField(
        "dyndns_update_path",
        "Custom update path and query",
        "secret",
        minimum=1,
        maximum=2048,
        read_key="dyndns_updurl",
        description=(
            "Optional replacement beginning with /. Existing path and "
            "embedded credentials remain private."
        ),
    ),
)
_DDNS_WORD: Final = re.compile(r"[A-Za-z0-9_\-.@]*")
_DDNS_HOST: Final = re.compile(
    r"(?=.{1,253}\Z)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
)
_SECRET_MASK: Final = re.compile(r"[*•●]+")
_WEEKDAYS: Final = (
    ("mo", "Monday"),
    ("di", "Tuesday"),
    ("mi", "Wednesday"),
    ("do", "Thursday"),
    ("fr", "Friday"),
    ("sa", "Saturday"),
    ("so", "Sunday"),
)
_SCHEDULE_FIELDS: Final = (
    choice(
        "wlan_timerule",
        "Schedule mode",
        (("0", "No schedule"), ("1", "Daily"), ("2", "Weekly")),
    ),
    SettingsField("wlan_dfrom", "Daily start", "text", maximum=5, description="HH:MM"),
    SettingsField(
        "wlan_dto",
        "Daily end",
        "text",
        maximum=5,
        description="HH:MM; 24:00 is allowed",
    ),
    boolean("wlan_fdis", "Force disconnect at scheduled end"),
    *(
        SettingsField(
            f"wlan_time_{day}_{suffix}",
            f"{label} {caption}",
            "text",
            maximum=5,
            description="HH:MM; 24:00 is allowed for end times",
        )
        for day, label in _WEEKDAYS
        for suffix, caption in (("from", "start"), ("to", "end"))
    ),
)
_CLOCK: Final = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_END_OF_DAY: Final = 24 * 60


def _value(
    field: SettingsField, raw: SettingValues, changes: SettingValues
) -> str | int | bool:
    """Validate either an explicit change or its exact current wire value."""
    value = (
        field.validate(changes[field.name])
        if field.name in changes
        else field.read(raw)
    )
    if isinstance(value, list):
        raise ConfigurationError("invalid_contract_field")
    return value


def _wire(values: dict[str, str | int | bool]) -> dict[str, str | int | bool]:
    """Use the template engine's numeric checkbox representation."""
    return {
        key: ("1" if value else "0") if type(value) is bool else value
        for key, value in values.items()
    }


def _build_dhcp(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Preserve visible DHCP form values and validate its suffix-based pool."""
    values = {field.name: _value(field, raw, changes) for field in _DHCP_FIELDS}
    if values["lan_use_dhcp"] is False:
        if {"lan_dhcp_from", "lan_dhcp_to"} & changes.keys():
            raise ConfigurationError("inactive_settings_field")
        # Text inputs disappear with the disabled branch; select stays serialized.
        return _wire(
            {key: values[key] for key in ("lan_use_dhcp", "lan_dhcp_validtime")}
        )
    octet = SettingsField("octet", "Address suffix", "integer", maximum=255)
    ipv4 = ".".join(
        str(octet.read({"octet": raw.get(f"lan_ipv4_{index}")}))
        for index in range(1, 5)
    )
    mask = "255." + ".".join(
        str(octet.read({"octet": raw.get(f"lan_mask_{index}")}))
        for index in range(2, 5)
    )
    try:
        # This reuses geometry checks only; these placeholder IPv6 values are
        # never serialized by the DHCP contract.
        LanSnapshot(
            ipv4,
            mask,
            0,
            "",
            0,
            0,
            int(values["lan_dhcp_from"]),
            int(values["lan_dhcp_to"]),
        )
    except LanManagementValidationError:
        raise ConfigurationError("invalid_dhcp_range") from None
    return _wire(values)


def _build_radio(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Apply the captured channel-direction and bandwidth compatibility rules."""
    values = {field.name: _value(field, raw, changes) for field in _RADIO_FIELDS}
    channel = int(values["wlan_channel"])
    forced_direction = (
        "2"
        if channel == 0
        else None
        if channel in _DIRECTION_SELECTABLE_CHANNELS
        else "0"
        if channel < _DIRECTION_SELECTABLE_CHANNELS.start
        else "1"
    )
    if forced_direction is not None:
        if (
            "wlan_channel_dir" in changes
            and values["wlan_channel_dir"] != forced_direction
        ):
            raise ConfigurationError("invalid_channel_direction")
        values["wlan_channel_dir"] = forced_direction
    if values["wlan_5ghz_mode"] == "0" and values["wlan_5ghz_speed"] in {"2", "3"}:
        if "wlan_5ghz_speed" in changes:
            raise ConfigurationError("invalid_channel_bandwidth")
        values["wlan_5ghz_speed"] = "1"
    bandwidth = str(values["wlan_5ghz_speed"])
    if int(values["wlan_5ghz_channel"]) not in _FIVE_GHZ_CHANNELS[bandwidth]:
        if "wlan_5ghz_channel" in changes:
            raise ConfigurationError("invalid_channel_bandwidth")
        values["wlan_5ghz_channel"] = "0"
    return _wire(values)


def _ascii(value: object) -> str:
    """Require the firmware's printable ASCII SSID/password alphabet."""
    if type(value) is not str or not all(
        _ASCII_MIN <= ord(char) <= _ASCII_MAX for char in value
    ):
        raise ConfigurationError("invalid_wifi_text")
    return value


def _build_identity(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Serialize only the active encryption branch; never replay a masked key."""
    fields = {field.name: field for field in _IDENTITY_FIELDS}
    common = (
        "wlan_ssid",
        "wlan_visible",
        "wlan_5ghz_ssid",
        "wlan_5ghz_visible",
        "wlan_enc",
    )
    values = {name: _value(fields[name], raw, changes) for name in common}
    for name in ("wlan_ssid", "wlan_5ghz_ssid"):
        ssid = _ascii(values[name])
        if ssid.casefold() == "telekom":
            raise ConfigurationError("reserved_wifi_name")
        if name in changes:
            for other in ("wlan_guest_ssid", "wlan_office_ssid"):
                current = raw.get(other)
                if type(current) is not str:
                    raise ConfigurationError("incomplete_wifi_identity")
                if current.casefold() == ssid.casefold():
                    raise ConfigurationError("duplicate_wifi_name")
    encryption = values["wlan_enc"]
    if encryption == "4":
        values["wlan_pmf"] = _value(fields["wlan_pmf"], raw, changes)
    elif "wlan_pmf" in changes:
        raise ConfigurationError("inactive_settings_field")
    if encryption != "0":
        values["wlan_wpa_key"] = _ascii(_value(fields["wlan_wpa_key"], raw, changes))
        values["wlan_display_key"] = _value(fields["wlan_display_key"], raw, changes)
        if {
            "wlan_ssid",
            "wlan_5ghz_ssid",
            "wlan_wpa_key",
        } & changes.keys() and "wlan_display_key" not in changes:
            values["wlan_display_key"] = False
    elif {"wlan_wpa_key", "wlan_display_key"} & changes.keys():
        raise ConfigurationError("inactive_settings_field")
    return _wire(values)


def _read_lan(raw: SettingValues) -> dict[str, str]:
    """Expose only the two reviewed LAN IPv4 edits, not preserved private state."""
    try:
        snapshot = parse_lan_snapshot(raw)
    except LanManagementValidationError:
        raise ConfigurationError("incomplete_lan_snapshot") from None
    return {"ipv4_address": snapshot.ipv4_address, "subnet_mask": snapshot.subnet_mask}


def _build_lan(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Adapt the strict standalone eleven-field LAN command without router I/O."""
    try:
        snapshot = parse_lan_snapshot(raw)
        command = build_lan_ipv4_command(
            snapshot,
            ipv4_address=changes.get("ipv4_address", snapshot.ipv4_address),
            subnet_mask=changes.get("subnet_mask", snapshot.subnet_mask),
        )
    except LanManagementValidationError:
        raise ConfigurationError("invalid_lan_settings") from None
    return dict(command.payload)


def _read_ddns(raw: SettingValues) -> dict[str, str | int | bool]:
    """Expose inactive empty state without inventing values for a future write."""
    enabled = _value(_DDNS_FIELDS[0], raw, {})
    provider = raw.get("dyndns_provider")
    known_provider = str(provider) in {"0", "1", "2", "3", "4"}
    if enabled and not known_provider:
        raise ConfigurationError("unknown_ddns_provider")
    result: dict[str, str | int | bool] = {"use_dyndns": enabled}
    for field in _DDNS_FIELDS[1:]:
        if field.kind == "secret":
            continue
        try:
            result[field.name] = _value(field, raw, {})
        except ConfigurationError:
            custom = field.name.startswith("dyndns_upd")
            if enabled and (not custom or str(provider) == "4"):
                raise
            # These presentation sentinels never feed the payload builder.
            result[field.name] = 0 if field.kind == "integer" else ""
    return result


def _build_ddns(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Preserve the private update path and model standard/custom visibility."""
    fields = {field.name: field for field in _DDNS_FIELDS}
    # Selects stay serialized even when their containing branch is hidden.
    values = {
        name: _value(fields[name], raw, changes)
        for name in (
            "use_dyndns",
            "dyndns_provider",
            "dyndns_updprot",
        )
    }
    provider = values["dyndns_provider"]
    if not provider or values["dyndns_updprot"] not in {"0", "1"}:
        raise ConfigurationError("incomplete_ddns_settings")
    if values["use_dyndns"] is False:
        if set(changes) - {"use_dyndns"}:
            raise ConfigurationError("inactive_settings_field")
        # Custom-provider preaction also adds its preserved host/path while off.
        if provider == "4":
            values.update(_ddns_custom_location(raw, changes, fields))
        return _wire(values)
    if provider != raw.get("dyndns_provider"):
        required = {"dyndns_domain", "dyndns_user", "dyndns_password"}
        if provider == "4":
            required |= {"dyndns_updsrv", "dyndns_update_path"}
        if not required <= changes.keys():
            # Never transfer an existing credential to a newly selected provider.
            raise ConfigurationError("new_provider_requires_credentials")
    for name in ("dyndns_domain", "dyndns_user"):
        value = _value(fields[name], raw, changes)
        if (
            type(value) is not str
            or not _DDNS_WORD.fullmatch(value)
            or (provider != "4" and not value)
        ):
            raise ConfigurationError("invalid_ddns_identity")
        values[name] = value
    if (
        provider == "4"
        and "dyndns_password" not in changes
        and raw.get("dyndns_password") == ""
    ):
        values["dyndns_password"] = ""
    else:
        values["dyndns_password"] = _value(fields["dyndns_password"], raw, changes)
    if provider == "4":
        values.update(_ddns_custom_location(raw, changes, fields))
        values["dyndns_updport"] = _value(fields["dyndns_updport"], raw, changes)
        if "dyndns_updprot" in changes and "dyndns_updport" not in changes:
            values["dyndns_updport"] = 80 if values["dyndns_updprot"] == "0" else 443
        if values["dyndns_updport"] == 0:
            raise ConfigurationError("incomplete_ddns_settings")
        if not values["dyndns_updsrv"] and any(
            not values[name]
            for name in (
                "dyndns_domain",
                "dyndns_user",
                "dyndns_password",
            )
        ):
            raise ConfigurationError("incomplete_ddns_identity")
    elif {
        "dyndns_updsrv",
        "dyndns_update_path",
        "dyndns_updport",
    } & changes.keys():
        raise ConfigurationError("inactive_settings_field")
    return _wire(values)


def _ddns_custom_location(
    raw: SettingValues, changes: SettingValues, fields: dict[str, SettingsField]
) -> dict[str, str | int | bool]:
    """Keep host/path separate so an unchanged path can never be erased."""
    host = _value(fields["dyndns_updsrv"], raw, changes)
    if type(host) is not str or (
        host
        and (
            not _DDNS_HOST.fullmatch(host)
            or any(
                not re.fullmatch(
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label
                )
                for label in host.split(".")
            )
        )
    ):
        raise ConfigurationError("invalid_ddns_host")
    if "dyndns_updsrv" in changes and host != raw.get("dyndns_updsrv"):
        required = {"dyndns_update_path"}
        if raw.get("dyndns_password"):
            required.add("dyndns_password")
        if not required <= changes.keys():
            raise ConfigurationError("new_server_requires_credentials")
    path: object
    if "dyndns_update_path" in changes:
        path = fields["dyndns_update_path"].validate(changes["dyndns_update_path"])
    else:
        path = raw.get("dyndns_updurl")
    if (
        type(path) is not str
        or len(path) > fields["dyndns_update_path"].maximum
        or (path and not path.startswith("/"))
        or not path.isascii()
        or (path and not path.isprintable())
        or _SECRET_MASK.fullmatch(path.lstrip("/"))
        or path.startswith("//")
        or "#" in path
        or (not host and path)
    ):
        raise ConfigurationError("invalid_ddns_update_path")
    return {"dyndns_updsrv": host, "dyndns_updurl": path}


def _clock_minutes(value: object, *, end: bool) -> int:
    """Validate exact firmware time bounds, including end-of-day notation."""
    if type(value) is not str:
        raise ConfigurationError("invalid_schedule_time")
    if end and value == "24:00":
        return _END_OF_DAY
    if not _CLOCK.fullmatch(value):
        raise ConfigurationError("invalid_schedule_time")
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _build_schedule(
    raw: SettingValues, changes: SettingValues
) -> dict[str, str | int | bool]:
    """Emit only the active radio branch; hidden weekday-use flags never post."""
    fields = {field.name: field for field in _SCHEDULE_FIELDS}
    mode = _value(fields["wlan_timerule"], raw, changes)
    names = {"wlan_timerule"}
    if mode == "1":
        names |= {"wlan_dfrom", "wlan_dto", "wlan_fdis"}
    elif mode == "2":
        names |= {
            f"wlan_time_{day}_{suffix}"
            for day, _ in _WEEKDAYS
            for suffix in ("from", "to")
        }
        names.add("wlan_fdis")
    if not changes.keys() <= names:
        raise ConfigurationError("inactive_settings_field")
    values = {name: _value(fields[name], raw, changes) for name in names}
    if mode == "1":
        _clock_minutes(values["wlan_dfrom"], end=False)
        _clock_minutes(values["wlan_dto"], end=True)
    elif mode == "2":
        spans = [
            (
                _clock_minutes(values[f"wlan_time_{day}_from"], end=False),
                _clock_minutes(values[f"wlan_time_{day}_to"], end=True),
            )
            for day, _ in _WEEKDAYS
        ]
        for index, (start, finish) in enumerate(spans):
            next_start = spans[(index + 1) % len(spans)][0]
            if start > finish > next_start:
                raise ConfigurationError("overlapping_wifi_schedule")
    return _wire(values)


NETWORK_SETTINGS: Final = (
    SettingsContract(
        "lan_ipv4",
        "LAN IPv4 address and subnet",
        "Network",
        "data/LAN.json",
        _NETWORK + "lan.html",
        (
            SettingsField(
                "ipv4_address", "Router IPv4 address", "text", minimum=7, maximum=15
            ),
            SettingsField("subnet_mask", "Subnet mask", "text", minimum=7, maximum=15),
        ),
        builder=_build_lan,
        reader=_read_lan,
        payload_keys=frozenset(LAN_MUTATION_FIELDS),
        warning=(
            "This can disconnect Home Assistant and all LAN clients. "
            "Reconnection to the new router address may be required."
        ),
        confirmation="CHANGE LAN ADDRESS",
        readback_policy="reconnect_required",
        revision_fields=(*LAN_MUTATION_FIELDS, "lan_dhcp_from", "lan_dhcp_to"),
    ),
    SettingsContract(
        "dhcp",
        "DHCP server and address pool",
        "Network",
        "data/LAN.json",
        _NETWORK + "dhcp.html",
        _DHCP_FIELDS,
        builder=_build_dhcp,
        warning=(
            "Changing DHCP may disconnect clients. The pool uses the router's "
            "first three address octets."
        ),
        confirmation="CHANGE DHCP",
        revision_fields=tuple(f"lan_ipv4_{index}" for index in range(1, 5))
        + tuple(f"lan_mask_{index}" for index in range(2, 5)),
    ),
    SettingsContract(
        "wifi_radio",
        "Wi-Fi radio and channels",
        "Wi-Fi",
        "data/WLANBasic.json",
        _NETWORK + "wlan_sendset.html",
        _RADIO_FIELDS,
        builder=_build_radio,
        warning=(
            "Changing bands, radio modes or channels interrupts Wi-Fi. "
            "DFS channels may take time to become usable."
        ),
        confirmation="CHANGE WIFI",
    ),
    SettingsContract(
        "wifi_identity",
        "Wi-Fi names and security",
        "Wi-Fi",
        "data/WLANBasicAss.json",
        _NETWORK + "wlan_name_enc.html",
        _IDENTITY_FIELDS,
        builder=_build_identity,
        warning=(
            "Name, encryption or password changes disconnect Wi-Fi clients. "
            "Unencrypted networks provide no Wi-Fi confidentiality."
        ),
        confirmation="CHANGE WIFI",
        revision_fields=(
            "wlan_guest_ssid",
            "wlan_office_ssid",
            "wlan_pmf",
            "wlan_display_key",
        ),
    ),
    SettingsContract(
        "dynamic_dns",
        "Dynamic DNS",
        "Internet",
        "data/DynDNS.json",
        "html/content/internet/dyn_dns.html",
        _DDNS_FIELDS,
        builder=_build_ddns,
        reader=_read_ddns,
        payload_keys=frozenset(
            {field.name for field in _DDNS_FIELDS if field.name != "dyndns_update_path"}
            | {"dyndns_updurl"}
        ),
        warning=(
            "Provider changes require explicit credentials. Custom update "
            "paths can contain secrets and are never displayed."
        ),
        confirmation="CHANGE DYNAMIC DNS",
        revision_fields=(*(field.name for field in _DDNS_FIELDS), "dyndns_updurl"),
    ),
    SettingsContract(
        "wifi_schedule",
        "Wi-Fi schedule",
        "Wi-Fi",
        "data/WLANBasic.json",
        _NETWORK + "wlan_basic.html",
        _SCHEDULE_FIELDS,
        builder=_build_schedule,
        warning=(
            "Scheduling or forced disconnect can interrupt the "
            "Home Assistant connection."
        ),
        confirmation="CHANGE WIFI SCHEDULE",
        revision_fields=tuple(f"wlan_time_{day}_use" for day, _ in _WEEKDAYS),
    ),
)
