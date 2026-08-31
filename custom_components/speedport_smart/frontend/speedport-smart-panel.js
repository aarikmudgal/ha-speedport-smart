const API_TYPE = "speedport_smart/panel";
const PANEL_SCHEMA_VERSION = 2;
const HERO_KEYS = new Set(["wan_download_rate", "wan_upload_rate"]);
const SECTION_ORDER = [
  "connection",
  "bandwidth",
  "dsl",
  "mobile",
  "wireless",
  "clients",
  "telephony",
  "system",
  "management",
  "controls",
];
const SECTION_INFO = {
  connection: {
    title: "Connection",
    subtitle: "Internet state, capacity, and addressing",
    icon: "mdi:web",
  },
  bandwidth: {
    title: "Live bandwidth",
    subtitle: "Aggregate WAN use and traffic counters",
    icon: "mdi:speedometer",
  },
  dsl: {
    title: "DSL line",
    subtitle: "Synchronization and line quality",
    icon: "mdi:transmission-tower",
  },
  mobile: {
    title: "Hybrid & mobile",
    subtitle: "Bonding, LTE, and 5G radio status",
    icon: "mdi:signal-cellular-3",
  },
  wireless: {
    title: "Wi-Fi & Mesh",
    subtitle: "Radios, channels, guests, and topology",
    icon: "mdi:wifi",
  },
  clients: {
    title: "Network & clients",
    subtitle: "Connected devices, LAN, DHCP, and mappings",
    icon: "mdi:lan",
  },
  telephony: {
    title: "Telephony",
    subtitle: "Calls, numbers, handsets, and registration",
    icon: "mdi:phone",
  },
  system: {
    title: "Router services",
    subtitle: "System, security, VPN, USB, and firmware",
    icon: "mdi:router-network",
  },
  management: {
    title: "Management & diagnostics",
    subtitle: "Session ownership and integration health",
    icon: "mdi:shield-check-outline",
  },
  controls: {
    title: "Controls",
    subtitle: "Actions run only after your confirmation",
    icon: "mdi:gesture-tap-button",
  },
};
const ACCESS_SOURCE_ORDER = [
  "public_status",
  "integration",
  "protected_json",
  "totr64",
  "wan_counters",
  "router_control",
];
const ACCESS_SOURCE_INFO = {
  public_status: {
    title: "Browser-independent",
    short: "Always-on local status",
    description: "Remains readable while the Speedport web interface is open.",
    icon: "mdi:shield-check-outline",
  },
  protected_json: {
    title: "Protected router session",
    short: "Protected session",
    description: "Needs the integration to own management access; log out of the router GUI if unavailable.",
    icon: "mdi:account-lock-outline",
  },
  totr64: {
    title: "TR-064 session data",
    short: "TR-064 session",
    description: "Optional line metrics that may pause while another router management session is active.",
    icon: "mdi:lan-connect",
  },
  wan_counters: {
    title: "Live WAN counters",
    short: "Live WAN session",
    description: "Real traffic counters and derived rates; a free management session is required.",
    icon: "mdi:speedometer",
  },
  integration: {
    title: "Integration health",
    short: "Home Assistant",
    description: "Generated locally by the integration and independent of router GUI ownership.",
    icon: "mdi:home-assistant",
  },
  router_control: {
    title: "Explicit router actions",
    short: "Confirmation required",
    description: "Changes router state only after you explicitly confirm the action.",
    icon: "mdi:gesture-tap-button",
  },
};
const CHILD_KIND_INFO = {
  client: { label: "Network device", icon: "mdi:devices" },
  dect_handset: { label: "DECT handset", icon: "mdi:phone-wireless" },
  ip_phone: { label: "IP phone", icon: "mdi:deskphone" },
  mesh_node: { label: "Mesh node", icon: "mdi:access-point-network" },
  receiver: { label: "Mobile receiver", icon: "mdi:access-point-network" },
  telephone_line: { label: "Telephone line", icon: "mdi:phone-in-talk" },
  usb_device: { label: "USB device", icon: "mdi:usb" },
};

const DECIMAL_DATA_FACTORS = {
  B: 1,
  kB: 1_000,
  MB: 1_000_000,
  GB: 1_000_000_000,
  TB: 1_000_000_000_000,
};
const CAPABILITY_GROUP_INFO = {
  connection_internet: { title: "Internet status", icon: "mdi:web-check" },
  connection_addressing: { title: "Public addressing", icon: "mdi:ip-network-outline" },
  bandwidth_capacity: { title: "Capacity & utilization", icon: "mdi:gauge" },
  bandwidth_totals: { title: "Data totals", icon: "mdi:database-arrow-up-outline" },
  bandwidth_packets: { title: "Packets", icon: "mdi:package-variant-closed" },
  bandwidth_errors: { title: "Errors & discards", icon: "mdi:alert-circle-outline" },
  bandwidth_interface: { title: "WAN interface", icon: "mdi:ethernet" },
  bandwidth_live: { title: "Live rate", icon: "mdi:swap-vertical-bold" },
  dsl_status: { title: "Status & profile", icon: "mdi:connection" },
  dsl_sync: { title: "Current sync", icon: "mdi:transmission-tower" },
  dsl_attainable: { title: "Attainable rate", icon: "mdi:speedometer" },
  dsl_quality: { title: "Line quality", icon: "mdi:sine-wave" },
  dsl_errors: { title: "Error counters", icon: "mdi:alert-outline" },
  mobile_connection: { title: "Connectivity", icon: "mdi:signal-cellular-3" },
  mobile_radio: { title: "Radio", icon: "mdi:radio-tower" },
  mobile_signal: { title: "Signal quality", icon: "mdi:signal" },
  mobile_tunnel: { title: "Hybrid tunnel traffic", icon: "mdi:swap-vertical" },
  mobile_receivers: { title: "Mobile receivers", icon: "mdi:access-point-network" },
  wireless_2_4: { title: "2.4 GHz Wi-Fi", icon: "mdi:wifi" },
  wireless_5: { title: "5 GHz Wi-Fi", icon: "mdi:wifi" },
  wireless_guest: { title: "Guest Wi-Fi", icon: "mdi:wifi-star" },
  wireless_office: { title: "Office Wi-Fi", icon: "mdi:wifi-cog" },
  wireless_mesh: { title: "Mesh overview", icon: "mdi:access-point-network" },
  wireless_mesh_nodes: { title: "Mesh nodes", icon: "mdi:access-point-network" },
  wireless_general: { title: "General Wi-Fi", icon: "mdi:wifi-cog" },
  clients_overview: { title: "Network overview", icon: "mdi:devices" },
  clients_devices: { title: "Network devices", icon: "mdi:laptop" },
  clients_lan: { title: "LAN ports", icon: "mdi:ethernet" },
  clients_dhcp: { title: "DHCP", icon: "mdi:ip-network" },
  clients_forwarding: { title: "Port forwarding", icon: "mdi:router-network" },
  clients_upnp: { title: "UPnP", icon: "mdi:lan-connect" },
  telephony_registration: { title: "Registration", icon: "mdi:phone-check" },
  telephony_calls: { title: "Calls", icon: "mdi:phone-in-talk" },
  telephony_lines: { title: "Telephone lines", icon: "mdi:phone-classic" },
  telephony_dect: { title: "DECT", icon: "mdi:phone-wireless" },
  telephony_ip: { title: "IP phones", icon: "mdi:deskphone" },
  telephony_phonebooks: { title: "Phonebooks", icon: "mdi:book-open-page-variant" },
  system_health: { title: "System health", icon: "mdi:chip" },
  system_firmware: { title: "Firmware", icon: "mdi:update" },
  system_security: { title: "Security", icon: "mdi:shield-lock-outline" },
  system_ddns: { title: "Dynamic DNS", icon: "mdi:dns-outline" },
  system_vpn: { title: "VPN", icon: "mdi:vpn" },
  system_parental: { title: "Parental controls", icon: "mdi:account-child-outline" },
  system_usb: { title: "USB & storage", icon: "mdi:usb" },
  system_services: { title: "Router services", icon: "mdi:cog-outline" },
  management_session: { title: "Router session", icon: "mdi:account-lock-outline" },
  management_health: { title: "Integration health", icon: "mdi:home-assistant" },
  controls_wireless: { title: "Wi-Fi", icon: "mdi:wifi-cog" },
  controls_internet: { title: "Internet & DSL", icon: "mdi:web-sync" },
  controls_mesh: { title: "Mesh", icon: "mdi:access-point-network" },
  controls_clients: { title: "Client access", icon: "mdi:account-lock-outline" },
  controls_forwarding: { title: "Port forwarding & UPnP", icon: "mdi:router-network" },
  controls_ddns: { title: "Dynamic DNS", icon: "mdi:dns-outline" },
  controls_vpn: { title: "VPN", icon: "mdi:vpn" },
  controls_parental: { title: "Parental controls", icon: "mdi:account-child-outline" },
  controls_media: { title: "Media server", icon: "mdi:multimedia" },
  controls_system: { title: "Router & firmware", icon: "mdi:power-cycle" },
  controls_session: { title: "Session recovery", icon: "mdi:account-sync-outline" },
};
const CAPABILITY_GROUP_ORDER = {
  connection: ["connection_internet", "connection_addressing"],
  bandwidth: ["bandwidth_capacity", "bandwidth_totals", "bandwidth_packets", "bandwidth_errors", "bandwidth_interface", "bandwidth_live"],
  dsl: ["dsl_status", "dsl_sync", "dsl_attainable", "dsl_quality", "dsl_errors"],
  mobile: ["mobile_connection", "mobile_radio", "mobile_signal", "mobile_tunnel", "mobile_receivers"],
  wireless: ["wireless_2_4", "wireless_5", "wireless_guest", "wireless_office", "wireless_mesh", "wireless_mesh_nodes", "wireless_general"],
  clients: ["clients_overview", "clients_devices", "clients_lan", "clients_dhcp", "clients_forwarding", "clients_upnp"],
  telephony: ["telephony_registration", "telephony_calls", "telephony_lines", "telephony_dect", "telephony_ip", "telephony_phonebooks"],
  system: ["system_health", "system_firmware", "system_security", "system_ddns", "system_vpn", "system_parental", "system_usb", "system_services"],
  management: ["management_session", "management_health"],
  controls: ["controls_session", "controls_wireless", "controls_internet", "controls_mesh", "controls_clients", "controls_forwarding", "controls_ddns", "controls_vpn", "controls_parental", "controls_media", "controls_system"],
};

const ESCAPE_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ESCAPE_MAP[character]);
}

function humanize(value) {
  return String(value ?? "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDurationSeconds(value, locale) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return undefined;
  let remaining = Math.floor(numeric);
  if (remaining === 0) return "0 s";

  const formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
  const units = [
    ["d", 86_400],
    ["h", 3_600],
    ["min", 60],
    ["s", 1],
  ];
  const parts = [];
  for (const [label, seconds] of units) {
    const amount = Math.floor(remaining / seconds);
    remaining %= seconds;
    if (amount > 0) parts.push(`${formatter.format(amount)} ${label}`);
    if (parts.length === 2) break;
  }
  return parts.join(" ");
}

function formatTransferredData(state, locale) {
  const attributes = state?.attributes || {};
  if (
    attributes.device_class !== "data_size" ||
    attributes.state_class !== "total_increasing"
  ) {
    return undefined;
  }
  const factor = DECIMAL_DATA_FACTORS[attributes.unit_of_measurement];
  const numeric = Number(state.state);
  if (!factor || !Number.isFinite(numeric) || numeric < 0) return undefined;

  const bytes = numeric * factor;
  const [unit, divisor] =
    bytes < DECIMAL_DATA_FACTORS.GB
      ? ["MB", DECIMAL_DATA_FACTORS.MB]
      : bytes < DECIMAL_DATA_FACTORS.TB
        ? ["GB", DECIMAL_DATA_FACTORS.GB]
        : ["TB", DECIMAL_DATA_FACTORS.TB];
  const displayValue = bytes / divisor;
  if (bytes > 0 && displayValue < 0.01) return `<0.01 ${unit}`;
  const formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  return `${formatter.format(displayValue)} ${unit}`;
}

function capabilityGroupFor(meta) {
  const section = SECTION_INFO[meta.section] ? meta.section : "system";
  const key = String(meta.translation_key || "").toLowerCase();
  const childKind = meta.child_device?.kind;
  if (childKind === "client") {
    return section === "controls" ? "controls_clients" : "clients_devices";
  }
  if (childKind === "mesh_node") return "wireless_mesh_nodes";
  if (childKind === "receiver") return "mobile_receivers";
  if (childKind === "telephone_line") return "telephony_lines";
  if (childKind === "dect_handset") return "telephony_dect";
  if (childKind === "ip_phone") return "telephony_ip";
  if (childKind === "usb_device") return "system_usb";
  if (childKind) return `${section}_other_devices`;

  if (section === "connection") {
    if (key.startsWith("public_ipv")) return "connection_addressing";
    return "connection_internet";
  }
  if (section === "bandwidth") {
    if (key.startsWith("wan_bytes") || key.startsWith("lte_tunnel_bytes")) {
      return "bandwidth_totals";
    }
    if (key.startsWith("wan_packets")) return "bandwidth_packets";
    if (key.startsWith("wan_errors") || key.startsWith("wan_discarded")) {
      return "bandwidth_errors";
    }
    if (key === "wan_interface" || key === "wan_mtu") {
      return "bandwidth_interface";
    }
    if (key === "wan_download_rate" || key === "wan_upload_rate") {
      return "bandwidth_live";
    }
    return "bandwidth_capacity";
  }
  if (section === "dsl") {
    if (key.startsWith("dsl_attainable")) return "dsl_attainable";
    if (key.startsWith("dsl_snr") || key.startsWith("dsl_attenuation")) {
      return "dsl_quality";
    }
    if (
      key.startsWith("dsl_crc") ||
      key.startsWith("dsl_fec") ||
      key === "dsl_error_seconds"
    ) {
      return "dsl_errors";
    }
    if (key === "dsl_downstream" || key === "dsl_upstream") return "dsl_sync";
    return "dsl_status";
  }
  if (section === "mobile") {
    if (key.startsWith("lte_tunnel")) return "mobile_tunnel";
    if (
      key.startsWith("mobile_rsrp") ||
      key.startsWith("mobile_rsrq") ||
      key.startsWith("mobile_sinr") ||
      key.startsWith("mobile_rssi")
    ) {
      return "mobile_signal";
    }
    if (
      key.startsWith("mobile_band") ||
      key.startsWith("mobile_frequency") ||
      key.startsWith("mobile_cell_id")
    ) {
      return "mobile_radio";
    }
    return "mobile_connection";
  }
  if (section === "wireless") {
    if (key.startsWith("wifi_2_4")) return "wireless_2_4";
    if (key.startsWith("wifi_5")) return "wireless_5";
    if (key.startsWith("guest_wifi") || key.startsWith("wifi_guest")) {
      return "wireless_guest";
    }
    if (key.startsWith("office_wifi")) return "wireless_office";
    if (key.startsWith("mesh_")) return "wireless_mesh";
    return "wireless_general";
  }
  if (section === "clients") {
    if (meta.domain === "device_tracker") return "clients_devices";
    if (key.startsWith("dhcp_")) return "clients_dhcp";
    if (key.startsWith("port_forward") || key.startsWith("nat_")) {
      return "clients_forwarding";
    }
    if (key.startsWith("upnp_")) return "clients_upnp";
    if (key.startsWith("lan_")) return "clients_lan";
    return "clients_overview";
  }
  if (section === "telephony") {
    if (
      key === "active_call" ||
      key.startsWith("missed_call") ||
      key === "last_call"
    ) {
      return "telephony_calls";
    }
    if (key.startsWith("dect_") || key.startsWith("phonebook")) {
      return key.startsWith("phonebook")
        ? "telephony_phonebooks"
        : "telephony_dect";
    }
    if (key.startsWith("ip_phone")) return "telephony_ip";
    return "telephony_registration";
  }
  if (section === "system") {
    if (key.startsWith("system_")) return "system_health";
    if (key.startsWith("firmware")) return "system_firmware";
    if (
      key.startsWith("firewall") ||
      key.startsWith("dns_rebind") ||
      key === "remote_management"
    ) {
      return "system_security";
    }
    if (key.startsWith("ddns")) return "system_ddns";
    if (key.startsWith("vpn")) return "system_vpn";
    if (key.startsWith("parental")) return "system_parental";
    if (key.startsWith("usb") || key === "media_server") return "system_usb";
    return "system_services";
  }
  if (section === "management") {
    return key === "management_access"
      ? "management_session"
      : "management_health";
  }
  if (section === "controls") {
    if (key === "retry_protected_data") return "controls_session";
    if (["wifi", "guest_wifi", "office_wifi", "wps"].includes(key)) {
      return "controls_wireless";
    }
    if (["reconnect_internet", "restart_dsl"].includes(key)) {
      return "controls_internet";
    }
    if (key === "optimize_mesh") return "controls_mesh";
    if (key === "client_internet_access") return "controls_clients";
    if (key === "port_forward_rule" || key === "upnp") {
      return "controls_forwarding";
    }
    if (key === "ddns" || key === "update_ddns") return "controls_ddns";
    if (key === "vpn" || key === "restart_vpn") return "controls_vpn";
    if (key === "parental_controls") return "controls_parental";
    if (key === "media_server") return "controls_media";
    if (key === "reboot_router" || key === "firmware") {
      return "controls_system";
    }
  }
  return `${section}_other`;
}

function capabilityGroupInfo(groupId, sectionId) {
  return CAPABILITY_GROUP_INFO[groupId] || {
    title: groupId.endsWith("_devices") ? "Other devices" : "Other",
    icon: SECTION_INFO[sectionId]?.icon || "mdi:dots-horizontal-circle-outline",
  };
}

function capabilityGroupRank(sectionId, groupId) {
  const order = CAPABILITY_GROUP_ORDER[sectionId] || [];
  const rank = order.indexOf(groupId);
  return rank === -1 ? order.length : rank;
}

function iconFor(meta, state) {
  if (state?.attributes?.icon) return state.attributes.icon;
  if (meta.domain === "switch") return "mdi:toggle-switch";
  if (meta.domain === "button") return "mdi:gesture-tap-button";
  if (meta.domain === "binary_sensor") return "mdi:checkbox-marked-circle-outline";
  if (meta.domain === "device_tracker") return "mdi:devices";
  if (meta.domain === "update") return "mdi:update";
  return SECTION_INFO[meta.section]?.icon || "mdi:gauge";
}

class SpeedportSmartPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this._panel = undefined;
    this._narrow = false;
    this._metadata = undefined;
    this._selectedEntry = undefined;
    this._loading = false;
    this._loadError = "";
    this._pendingAction = undefined;
    this._actionBusy = false;
    this._notice = "";
    this._refreshTimer = undefined;
    this._renderFrame = undefined;
    this.shadowRoot.addEventListener("click", (event) => this._handleClick(event));
    this.shadowRoot.addEventListener("keydown", (event) => this._handleKeyDown(event));
  }

  set hass(value) {
    const previous = this._hass;
    const firstAssignment = !previous;
    const shouldRender = this._shouldRenderForHass(previous, value);
    this._hass = value;
    if (firstAssignment) this._loadMetadata();
    if (shouldRender) this._scheduleRender();
  }

  set panel(value) {
    this._panel = value;
  }

  set narrow(value) {
    this._narrow = Boolean(value);
    this.toggleAttribute("narrow", this._narrow);
  }

  set route(value) {
    this._route = value;
  }

  connectedCallback() {
    if (this._hass && !this._metadata) this._loadMetadata();
    if (!this._refreshTimer) {
      this._refreshTimer = window.setInterval(() => this._loadMetadata(), 60000);
    }
    this._render();
  }

  disconnectedCallback() {
    if (this._refreshTimer) window.clearInterval(this._refreshTimer);
    this._refreshTimer = undefined;
    if (this._renderFrame) window.cancelAnimationFrame(this._renderFrame);
    this._renderFrame = undefined;
  }

  _shouldRenderForHass(previous, next) {
    if (!previous || !this._metadata || previous.locale !== next.locale) return true;
    return this._metadata.routers.some((router) =>
      router.entities.some(
        (entity) =>
          previous.states?.[entity.entity_id] !== next.states?.[entity.entity_id],
      ),
    );
  }

  _scheduleRender() {
    if (this._renderFrame) return;
    this._renderFrame = window.requestAnimationFrame(() => {
      this._renderFrame = undefined;
      this._render();
    });
  }

  async _loadMetadata() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._loadError = "";
    try {
      const metadata = await this._hass.connection.sendMessagePromise({
        type: API_TYPE,
      });
      if (
        metadata?.schema_version !== PANEL_SCHEMA_VERSION ||
        !Array.isArray(metadata?.routers)
      ) {
        throw new Error("Unsupported dashboard metadata");
      }
      this._metadata = metadata;
      const entryIds = new Set(metadata.routers.map((router) => router.entry_id));
      if (!this._selectedEntry || !entryIds.has(this._selectedEntry)) {
        this._selectedEntry = metadata.routers[0]?.entry_id;
      }
    } catch (_error) {
      this._loadError =
        "Dashboard metadata is unavailable. Reload Home Assistant after updating the integration.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  _currentRouter() {
    const routers = this._metadata?.routers || [];
    return (
      routers.find((router) => router.entry_id === this._selectedEntry) ||
      routers[0]
    );
  }

  _entityMetadata(entityId) {
    return this._currentRouter()?.entities?.find(
      (entity) => entity.entity_id === entityId,
    );
  }

  _state(meta) {
    return meta ? this._hass?.states?.[meta.entity_id] : undefined;
  }

  _isUnavailable(state) {
    return !state || state.state === "unavailable";
  }

  _isControlUnavailable(meta, state) {
    return (
      this._isUnavailable(state) ||
      (meta?.domain === "update" && state?.state !== "on")
    );
  }

  _friendlyName(meta, state) {
    return (
      state?.attributes?.friendly_name ||
      humanize(meta.translation_key || meta.entity_id)
    );
  }

  _locale() {
    return this._hass?.locale?.language || navigator.language || "en";
  }

  _formatState(state) {
    if (!state) return "Unavailable";
    if (state.state === "unavailable") return "Unavailable";
    if (state.state === "unknown") return "Unknown";
    const attributes = state.attributes || {};
    if (
      attributes.device_class === "duration" &&
      attributes.unit_of_measurement === "s"
    ) {
      const duration = formatDurationSeconds(state.state, this._locale());
      if (duration !== undefined) return duration;
    }
    const transferredData = formatTransferredData(state, this._locale());
    if (transferredData !== undefined) return transferredData;
    try {
      if (typeof this._hass?.formatEntityState === "function") {
        return this._hass.formatEntityState(state);
      }
    } catch (_error) {
      // Fall through to the raw Home Assistant state.
    }
    const unit = state.attributes?.unit_of_measurement;
    return unit ? `${state.state} ${unit}` : state.state;
  }

  _handleClick(event) {
    const target = event.target.closest(
      "button, [data-more-info]",
    );
    if (!target) return;

    if (target.dataset.router) {
      this._selectedEntry = target.dataset.router;
      this._pendingAction = undefined;
      this._notice = "";
      this._render();
      return;
    }
    if (target.dataset.refresh !== undefined) {
      this._loadMetadata();
      return;
    }
    if (target.dataset.moreInfo) {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: target.dataset.moreInfo },
          bubbles: true,
          composed: true,
        }),
      );
      return;
    }
    if (target.dataset.control) {
      this._prepareAction(target.dataset.control);
      return;
    }
    if (target.dataset.cancelAction !== undefined) {
      this._pendingAction = undefined;
      this._render();
      return;
    }
    if (target.dataset.confirmAction !== undefined) {
      this._runPendingAction();
    }
  }

  _handleKeyDown(event) {
    if (!this._pendingAction || this._actionBusy) return;
    if (event.key === "Escape") {
      event.preventDefault();
      this._pendingAction = undefined;
      this._render();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = this.shadowRoot.querySelector(".confirm-dialog");
    const focusable = [...(dialog?.querySelectorAll("button:not([disabled])") || [])];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && this.shadowRoot.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && this.shadowRoot.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  _prepareAction(entityId) {
    const meta = this._entityMetadata(entityId);
    const state = this._state(meta);
    if (!meta || this._isControlUnavailable(meta, state)) {
      this._notice =
        meta?.domain === "update" && state?.state !== "on"
          ? "The router firmware is already up to date."
          : "This control is currently unavailable.";
      this._render();
      return;
    }

    const label = this._friendlyName(meta, state);
    let actionLabel = "Run action";
    let message =
      "This action changes router state. It will run once only after confirmation.";
    if (meta.translation_key === "retry_protected_data") {
      actionLabel = "Retry protected data";
      message =
        "First use Logout in the Speedport web interface. Closing the browser tab may retain its session. This retry reads capabilities and does not change router settings.";
    } else if (meta.domain === "switch") {
      actionLabel = state.state === "on" ? "Turn off" : "Turn on";
      message = `Confirm changing ${label}. Nothing is changed automatically.`;
    } else if (meta.domain === "update") {
      actionLabel = "Install update";
      message =
        "Installing firmware can interrupt network access and restart the router. Continue only when you are ready.";
    } else if (meta.disruptive) {
      message =
        "This action can interrupt network service. It will run once only after confirmation.";
    }

    this._pendingAction = {
      entityId,
      label,
      actionLabel,
      message,
      disruptive: Boolean(meta.disruptive || meta.domain === "update"),
    };
    this._notice = "";
    this._render();
  }

  async _runPendingAction() {
    if (!this._pendingAction || this._actionBusy || !this._hass) return;
    const pending = this._pendingAction;
    const meta = this._entityMetadata(pending.entityId);
    const state = this._state(meta);
    if (!meta || this._isControlUnavailable(meta, state)) {
      this._pendingAction = undefined;
      this._notice = "The control became unavailable before it could run.";
      this._render();
      return;
    }

    this._actionBusy = true;
    this._render();
    try {
      if (meta.domain === "button") {
        await this._hass.callService("button", "press", {
          entity_id: meta.entity_id,
        });
      } else if (meta.domain === "switch") {
        await this._hass.callService(
          "switch",
          state.state === "on" ? "turn_off" : "turn_on",
          { entity_id: meta.entity_id },
        );
      } else if (meta.domain === "update") {
        await this._hass.callService("update", "install", {
          entity_id: meta.entity_id,
        });
      } else {
        throw new Error("Unsupported control domain");
      }
      this._notice = `${pending.actionLabel} requested successfully.`;
      this._pendingAction = undefined;
    } catch (_error) {
      this._notice = "Action failed. Check Home Assistant logs for details.";
    } finally {
      this._actionBusy = false;
      this._render();
    }
  }

  _renderSource(source) {
    const unsupported = source.supported === false;
    const status = unsupported
      ? "unsupported"
      : source.available
        ? "available"
        : "unavailable";
    const statusLabel = unsupported
      ? "Not detected"
      : source.available
        ? "Ready now"
        : "Temporarily unavailable";
    return `
      <div class="source ${status}">
        <span class="source-dot"></span>
        <span>${escapeHtml(source.label)}</span>
        <strong>${escapeHtml(statusLabel)}</strong>
      </div>
    `;
  }

  _renderManagement(router) {
    const managementMeta = router.entities.find(
      (entity) => entity.translation_key === "management_access",
    );
    const managementState = this._state(managementMeta);
    const state =
      managementState?.state || router.management?.state || "unavailable";
    const attributes = managementState?.attributes || {};
    const logoutRequired =
      attributes.browser_logout_required ??
      router.management?.browser_logout_required ??
      false;
    const owner = attributes.owner_ip_address;
    const stateLabel = humanize(state);

    if (logoutRequired || ["blocked", "other_session"].includes(state)) {
      return `
        <aside class="management-alert warning">
          <ha-icon icon="mdi:account-lock"></ha-icon>
          <div>
            <strong>Browser session owns management access</strong>
            <p>
              In the Speedport web interface, use <b>Logout</b> before retrying.
              Closing the tab or window may leave the session active.
              ${owner ? `Current owner: ${escapeHtml(owner)}.` : ""}
            </p>
          </div>
          <span class="state-pill">${escapeHtml(stateLabel)}</span>
        </aside>
      `;
    }
    if (state === "locked") {
      const retryAfter =
        attributes.retry_after_seconds ??
        router.management?.retry_after_seconds;
      return `
        <aside class="management-alert caution">
          <ha-icon icon="mdi:timer-lock-outline"></ha-icon>
          <div>
            <strong>Router login is temporarily locked</strong>
            <p>
              Wait for the router cooldown before retrying protected data.
              ${
                retryAfter != null
                  ? `About ${escapeHtml(
                      formatDurationSeconds(retryAfter, this._locale()) ||
                        `${retryAfter} s`,
                    )} remain.`
                  : ""
              }
            </p>
          </div>
          <span class="state-pill">${escapeHtml(stateLabel)}</span>
        </aside>
      `;
    }
    return `
      <aside class="management-alert good">
        <ha-icon icon="mdi:shield-check-outline"></ha-icon>
        <div>
          <strong>Management access ${escapeHtml(stateLabel.toLowerCase())}</strong>
          <p>Public and protected data are grouped below by proven capability.</p>
        </div>
        <span class="state-pill">${escapeHtml(stateLabel)}</span>
      </aside>
    `;
  }

  _childEntityName(meta, state) {
    if (meta.domain === "device_tracker") return "Presence";
    const friendlyName = this._friendlyName(meta, state);
    const deviceName = meta.child_device?.name;
    if (!deviceName) return friendlyName;
    if (friendlyName === deviceName) {
      return humanize(meta.translation_key || meta.domain);
    }
    const prefix = `${deviceName} `;
    return friendlyName.startsWith(prefix)
      ? friendlyName.slice(prefix.length)
      : friendlyName;
  }

  _capabilityEntityName(meta, state, groupId) {
    let label = this._friendlyName(meta, state);
    const router = this._currentRouter();
    for (const prefix of [router?.title, router?.model]) {
      if (prefix && label.startsWith(`${prefix} `)) {
        label = label.slice(prefix.length + 1);
        break;
      }
    }

    const groupTitle = capabilityGroupInfo(groupId, meta.section).title;
    if (label.toLowerCase() === groupTitle.toLowerCase()) return "Status";
    if (label.toLowerCase().startsWith(`${groupTitle.toLowerCase()} `)) {
      return label.slice(groupTitle.length + 1);
    }

    const semanticPrefixes = {
      connection: ["Internet"],
      bandwidth: ["WAN"],
      dsl: ["DSL"],
      mobile: ["Mobile"],
      system: ["System"],
    };
    for (const prefix of semanticPrefixes[meta.section] || []) {
      if (label.toLowerCase() === prefix.toLowerCase()) return "Status";
      if (label.toLowerCase().startsWith(`${prefix.toLowerCase()} `)) {
        return label.slice(prefix.length + 1);
      }
    }
    return label;
  }

  _renderEntity(meta, { capabilityGroup = undefined, child = false, hero = false } = {}) {
    const state = this._state(meta);
    const unavailable = this._isUnavailable(state);
    const controlUnavailable = meta.control
      ? this._isControlUnavailable(meta, state)
      : false;
    const label = child
      ? this._childEntityName(meta, state)
      : capabilityGroup
        ? this._capabilityEntityName(meta, state, capabilityGroup)
        : this._friendlyName(meta, state);
    const displayState =
      meta.domain === "button" && state?.state === "unknown"
        ? "Ready"
        : this._formatState(state);
    const icon = iconFor(meta, state);
    const stateClass = unavailable ? "unavailable" : "available";
    const sourceInfo =
      ACCESS_SOURCE_INFO[meta.access_source] || ACCESS_SOURCE_INFO.protected_json;

    if (hero) {
      return `
        <article class="hero-metric ${stateClass}" data-more-info="${escapeHtml(meta.entity_id)}">
          <div class="hero-icon"><ha-icon icon="${escapeHtml(icon)}"></ha-icon></div>
          <div>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(displayState)}</strong>
            <small>${escapeHtml(sourceInfo.short)} · ${unavailable ? "waiting for a fresh sample" : "recent aggregate WAN rate"}</small>
          </div>
        </article>
      `;
    }

    const actionLabel =
      meta.translation_key === "retry_protected_data"
        ? "Retry"
        : meta.domain === "switch"
          ? state?.state === "on"
            ? "Turn off"
            : "Turn on"
          : meta.domain === "update"
            ? "Install"
            : "Run";
    const control = meta.control
      ? `
        <button
          class="entity-action ${meta.disruptive ? "disruptive" : ""}"
          data-control="${escapeHtml(meta.entity_id)}"
          ${controlUnavailable ? "disabled" : ""}
        >
          ${escapeHtml(actionLabel)}
        </button>
      `
      : "";

    return `
      <article class="entity-card ${child ? "child-entity-card" : ""} ${stateClass} ${meta.control ? "control-card" : ""}">
        <button class="entity-main" data-more-info="${escapeHtml(meta.entity_id)}">
          <span class="entity-icon"><ha-icon icon="${escapeHtml(icon)}"></ha-icon></span>
          <span class="entity-copy">
            <span class="entity-name">${escapeHtml(label)}</span>
            <strong class="entity-state">${escapeHtml(displayState)}</strong>
            <span class="source-badge" title="${escapeHtml(sourceInfo.description)}">
              ${escapeHtml(sourceInfo.short)}
            </span>
          </span>
          <span class="availability-dot" title="${unavailable ? "Unavailable" : "Available"}"></span>
        </button>
        ${control}
      </article>
    `;
  }

  _renderChildDevice(entities) {
    const child = entities[0]?.child_device;
    if (!child) return "";
    const kindInfo = CHILD_KIND_INFO[child.kind] || {
      label: humanize(child.kind),
      icon: "mdi:devices",
    };
    const details = child.model
      ? `${kindInfo.label} · ${child.model}`
      : kindInfo.label;
    const unavailable = entities.every((entity) =>
      this._isUnavailable(this._state(entity)),
    );
    return `
      <section class="child-device-card ${unavailable ? "unavailable" : "available"}" data-child-device="${escapeHtml(child.device_id)}">
        <header class="child-device-heading">
          <span class="child-device-icon"><ha-icon icon="${escapeHtml(kindInfo.icon)}"></ha-icon></span>
          <span class="child-device-copy">
            <strong>${escapeHtml(child.name)}</strong>
            <small>${escapeHtml(details)}</small>
          </span>
          <span class="child-device-count" title="${entities.length} entities">${entities.length}</span>
        </header>
        <div class="child-device-entities">
          ${entities.map((entity) => this._renderEntity(entity, { child: true })).join("")}
        </div>
      </section>
    `;
  }

  _renderCapabilityGroup(sectionId, sourceId, groupId, entities) {
    const info = capabilityGroupInfo(groupId, sectionId);
    const rootEntities = entities.filter((entity) => !entity.child_device);
    const childGroups = new Map();
    for (const entity of entities) {
      const child = entity.child_device;
      if (!child) continue;
      if (!childGroups.has(child.device_id)) childGroups.set(child.device_id, []);
      childGroups.get(child.device_id).push(entity);
    }
    const rootGrid = rootEntities.length
      ? `<div class="entity-grid capability-entity-grid">${rootEntities
          .map((entity) =>
            this._renderEntity(entity, { capabilityGroup: groupId }),
          )
          .join("")}</div>`
      : "";
    const childGrid = childGroups.size
      ? `<div class="child-device-grid">${[...childGroups.values()]
          .map((group) => this._renderChildDevice(group))
          .join("")}</div>`
      : "";
    const headingId = `speedport-group-${sectionId}-${sourceId}-${groupId}`.replace(
      /[^a-z0-9_-]/gi,
      "-",
    );
    const countLabel = `${entities.length} ${entities.length === 1 ? "entity" : "entities"}`;
    return `
      <section class="entity-capability-block ${childGroups.size ? "device-capability-block" : ""}" aria-labelledby="${escapeHtml(headingId)}">
        <header class="entity-capability-heading">
          <span class="entity-capability-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(info.icon)}"></ha-icon></span>
          <h3 id="${escapeHtml(headingId)}">${escapeHtml(info.title)}</h3>
          <span class="entity-capability-count" aria-label="${escapeHtml(countLabel)}">${entities.length}</span>
        </header>
        ${rootGrid}
        ${childGrid}
      </section>
    `;
  }

  _renderSection(sectionId, entities, router) {
    const info = SECTION_INFO[sectionId];
    if (!info || entities.length === 0) return "";
    const sourceStates = Object.fromEntries(
      (router.access_sources || []).map((source) => [source.id, source]),
    );
    const groups = new Map();
    for (const entity of entities) {
      const source = entity.access_source || "protected_json";
      if (!groups.has(source)) groups.set(source, []);
      groups.get(source).push(entity);
    }
    const sourceRank = (sourceId) => {
      const rank = ACCESS_SOURCE_ORDER.indexOf(sourceId);
      return rank === -1 ? ACCESS_SOURCE_ORDER.length : rank;
    };
    const orderedGroups = [...groups.entries()].sort(
      ([left], [right]) => sourceRank(left) - sourceRank(right),
    );
    const sourceGroups = orderedGroups
      .map(([sourceId, sourceEntities]) => {
        const sourceInfo =
          ACCESS_SOURCE_INFO[sourceId] || ACCESS_SOURCE_INFO.protected_json;
        const sourceState = sourceStates[sourceId];
        const statusClass = sourceState
          ? sourceState.supported === false
            ? "unsupported"
            : sourceState.available
              ? "available"
              : "unavailable"
          : "local";
        const statusText = sourceState
          ? sourceState.supported === false
            ? "Not detected"
            : sourceState.available
              ? "Available now"
              : "Temporarily unavailable"
          : sourceId === "router_control"
            ? "Runs only on confirmation"
            : "Available locally";
        const capabilityGroups = new Map();
        for (const entity of sourceEntities) {
          const groupId = capabilityGroupFor(entity);
          if (!capabilityGroups.has(groupId)) {
            capabilityGroups.set(groupId, []);
          }
          capabilityGroups.get(groupId).push(entity);
        }
        const capabilityBlocks = [...capabilityGroups.entries()]
          .sort(
            ([left], [right]) =>
              capabilityGroupRank(sectionId, left) -
                capabilityGroupRank(sectionId, right) ||
              capabilityGroupInfo(left, sectionId).title.localeCompare(
                capabilityGroupInfo(right, sectionId).title,
              ),
          )
          .map(([groupId, groupEntities]) =>
            this._renderCapabilityGroup(
              sectionId,
              sourceId,
              groupId,
              groupEntities,
            ),
          )
          .join("");
        const capabilityGrid = capabilityBlocks
          ? `<div class="entity-capability-grid">${capabilityBlocks}</div>`
          : "";
        return `
          <div class="entity-source-group">
            <header class="entity-source-heading ${statusClass}">
              <span class="entity-source-icon"><ha-icon icon="${escapeHtml(sourceInfo.icon)}"></ha-icon></span>
              <div>
                <strong>${escapeHtml(sourceInfo.title)}</strong>
                <p>${escapeHtml(sourceInfo.description)}</p>
              </div>
              <span class="entity-source-status"><i></i>${escapeHtml(statusText)}</span>
            </header>
            ${capabilityGrid}
          </div>
        `;
      })
      .join("");
    return `
      <section class="dashboard-section section-${escapeHtml(sectionId)}">
        <header class="section-heading">
          <span class="section-icon"><ha-icon icon="${info.icon}"></ha-icon></span>
          <div>
            <h2>${escapeHtml(info.title)}</h2>
            <p>${escapeHtml(info.subtitle)}</p>
          </div>
          <span class="section-count">${entities.length}</span>
        </header>
        <div class="entity-source-groups">${sourceGroups}</div>
      </section>
    `;
  }

  _renderCapabilities(router) {
    const bySource = {};
    for (const family of router.capability_families || []) {
      if (!bySource[family.source]) bySource[family.source] = [];
      bySource[family.source].push(family.name);
    }
    const sourceNames = {
      public_status: "Public status",
      public_json: "Public router data",
      protected_json: "Protected router data",
    };
    const groups = Object.entries(bySource)
      .map(
        ([source, names]) => `
          <div class="capability-group">
            <strong>${escapeHtml(sourceNames[source] || humanize(source))}</strong>
            <div class="capability-chips">
              ${names
                .map((name) => `<span>${escapeHtml(humanize(name))}</span>`)
                .join("")}
            </div>
          </div>
        `,
      )
      .join("");
    return `
      <details class="capability-details">
        <summary>
          <span>Discovered capabilities</span>
          <small>${router.capabilities?.length || 0} active signals</small>
        </summary>
        <div class="capability-content">
          ${groups || "<p>No capability metadata is available yet.</p>"}
        </div>
      </details>
    `;
  }

  _renderConfirmation() {
    const pending = this._pendingAction;
    if (!pending) return "";
    return `
      <div class="modal-backdrop" role="presentation">
        <section
          class="confirm-dialog ${pending.disruptive ? "danger" : ""}"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="speedport-confirm-title"
        >
          <span class="confirm-icon">
            <ha-icon icon="${pending.disruptive ? "mdi:alert-outline" : "mdi:shield-check-outline"}"></ha-icon>
          </span>
          <h2 id="speedport-confirm-title">${escapeHtml(pending.label)}</h2>
          <p>${escapeHtml(pending.message)}</p>
          <div class="confirm-actions">
            <button class="secondary" data-cancel-action ${this._actionBusy ? "disabled" : ""}>
              Cancel
            </button>
            <button class="primary" data-confirm-action ${this._actionBusy ? "disabled" : ""}>
              ${this._actionBusy ? "Working…" : escapeHtml(pending.actionLabel)}
            </button>
          </div>
        </section>
      </div>
    `;
  }

  _renderEmpty() {
    return `
      <main class="shell empty-shell">
        <section class="empty-card">
          <div class="brand-mark"><span></span><span></span><span></span></div>
          <h1>Telekom Speedport Smart</h1>
          <p>
            No readable Speedport entries are loaded for this Home Assistant user.
            Add the integration or check entity permissions, then refresh.
          </p>
          <button class="primary" data-refresh>Refresh dashboard</button>
        </section>
      </main>
    `;
  }

  _render() {
    if (!this.shadowRoot) return;
    const routers = this._metadata?.routers || [];
    const router = this._currentRouter();
    if (!this._hass || this._loading && !this._metadata) {
      this.shadowRoot.innerHTML = `${this._styles()}
        <main class="shell loading-shell">
          <div class="loading-mark"><span></span><span></span><span></span></div>
          <p>Building your Speedport dashboard…</p>
        </main>`;
      return;
    }
    if (this._loadError && !this._metadata) {
      this.shadowRoot.innerHTML = `${this._styles()}
        <main class="shell empty-shell">
          <section class="empty-card error-card">
            <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
            <h1>Dashboard unavailable</h1>
            <p>${escapeHtml(this._loadError)}</p>
            <button class="primary" data-refresh>Try again</button>
          </section>
        </main>`;
      return;
    }
    if (!router) {
      this.shadowRoot.innerHTML = `${this._styles()}${this._renderEmpty()}`;
      return;
    }

    const heroEntities = router.entities.filter((entity) =>
      HERO_KEYS.has(entity.translation_key),
    );
    const sectionEntities = {};
    for (const entity of router.entities) {
      if (HERO_KEYS.has(entity.translation_key)) continue;
      const section = SECTION_INFO[entity.section] ? entity.section : "system";
      if (!sectionEntities[section]) sectionEntities[section] = [];
      sectionEntities[section].push(entity);
    }
    const internetMeta = router.entities.find(
      (entity) => entity.translation_key === "internet_connected",
    );
    const internetState = this._state(internetMeta);
    const online = internetState?.state === "on";
    const connectionLabel = this._isUnavailable(internetState)
      ? "Connection state unavailable"
      : online
        ? "Internet connected"
        : "Internet disconnected";

    const routerTabs =
      routers.length > 1
        ? `
          <nav class="router-tabs" aria-label="Speedport routers">
            ${routers
              .map(
                (item) => `
                  <button
                    data-router="${escapeHtml(item.entry_id)}"
                    class="${item.entry_id === router.entry_id ? "active" : ""}"
                  >
                    ${escapeHtml(item.title)}
                  </button>
                `,
              )
              .join("")}
          </nav>
        `
        : "";

    const sections = SECTION_ORDER.map((section) =>
      this._renderSection(section, sectionEntities[section] || [], router),
    ).join("");
    const notice = this._notice
      ? `<div class="notice"><ha-icon icon="mdi:information-outline"></ha-icon>${escapeHtml(this._notice)}</div>`
      : "";

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <main class="shell">
        <header class="hero">
          <div class="hero-copy">
            <div class="eyebrow">
              <span class="telekom-dots"><i></i><i></i><i></i></span>
              Telekom home network
            </div>
            <h1>${escapeHtml(router.title)}</h1>
            <p>${escapeHtml(router.model || "Telekom Speedport Smart")}</p>
            <div class="hero-status">
              <span class="online-dot ${online ? "online" : ""}"></span>
              ${escapeHtml(connectionLabel)}
              <span class="divider"></span>
              <span class="integration-status">Integration ${escapeHtml(humanize(router.entry_state))}</span>
            </div>
          </div>
          <div class="router-visual" aria-hidden="true">
            <div class="router-body">
              <span class="router-logo">T</span>
              <div class="router-leds"><i></i><i></i><i></i><i></i></div>
            </div>
            <div class="signal-wave wave-one"></div>
            <div class="signal-wave wave-two"></div>
          </div>
        </header>

        ${routerTabs}
        ${notice}
        ${this._renderManagement(router)}

        <section class="access-overview">
          <header>
            <div>
              <span class="kicker">Access behavior</span>
              <h2>What remains available during a router GUI session</h2>
            </div>
            <button class="icon-button" data-refresh title="Refresh dashboard metadata">
              <ha-icon icon="mdi:refresh"></ha-icon>
            </button>
          </header>
          <div class="source-grid">
            ${(router.access_sources || [])
              .map((source) => this._renderSource(source))
              .join("")}
          </div>
          ${this._renderCapabilities(router)}
        </section>

        ${
          heroEntities.length
            ? `<section class="hero-metrics">${heroEntities
                .map((entity) => this._renderEntity(entity, { hero: true }))
                .join("")}</section>`
            : ""
        }

        <div class="sections">${sections}</div>

        <footer>
          <span>Telekom Speedport Smart</span>
          <span>Local polling · No Telekom cloud account</span>
        </footer>
      </main>
      ${this._renderConfirmation()}
    `;
    if (this._pendingAction) {
      window.requestAnimationFrame(() => {
        this.shadowRoot.querySelector("[data-cancel-action]")?.focus();
      });
    }
  }

  _styles() {
    return `
      <style>
        :host {
          --sp-magenta: var(--speedport-smart-accent-color, #e20074);
          --sp-magenta-deep: var(--speedport-smart-accent-deep-color, #b4005c);
          --sp-surface: var(--ha-card-background, var(--card-background-color, #ffffff));
          --sp-surface-soft: var(--secondary-background-color, #f4f4f6);
          --sp-text: var(--primary-text-color, #202124);
          --sp-muted: var(--secondary-text-color, #6f7277);
          --sp-border: var(--divider-color, rgba(127, 127, 127, 0.2));
          --sp-success: var(--success-color, #20a464);
          --sp-warning: var(--warning-color, #e58b18);
          --sp-error: var(--error-color, #db3b4b);
          display: block;
          min-height: 100%;
          color: var(--sp-text);
          background:
            radial-gradient(circle at 8% 0%, color-mix(in srgb, var(--sp-magenta) 10%, transparent), transparent 34rem),
            var(--primary-background-color, #f6f7f9);
          font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
        }
        * { box-sizing: border-box; }
        button { font: inherit; }
        .shell {
          width: min(100%, 1540px);
          margin: 0 auto;
          padding: clamp(16px, 3vw, 42px);
        }
        .hero {
          position: relative;
          min-height: 260px;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 32px;
          padding: clamp(28px, 5vw, 64px);
          color: white;
          border-radius: 30px;
          background:
            linear-gradient(118deg, rgba(105, 0, 53, 0.28), transparent 60%),
            linear-gradient(135deg, var(--sp-magenta), var(--sp-magenta-deep));
          box-shadow: 0 24px 70px color-mix(in srgb, var(--sp-magenta) 30%, transparent);
        }
        .hero::before {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          background-image: radial-gradient(rgba(255,255,255,.19) 1px, transparent 1px);
          background-size: 17px 17px;
          mask-image: linear-gradient(90deg, transparent 25%, black);
        }
        .hero-copy { position: relative; z-index: 2; }
        .eyebrow {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 18px;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: .12em;
          text-transform: uppercase;
          opacity: .86;
        }
        .telekom-dots { display: flex; align-items: flex-end; gap: 3px; }
        .telekom-dots i {
          width: 4px;
          height: 4px;
          border-radius: 1px;
          background: white;
        }
        .telekom-dots i:nth-child(2) { height: 12px; }
        .hero h1 {
          max-width: 760px;
          margin: 0;
          font-size: clamp(34px, 6vw, 68px);
          line-height: .98;
          letter-spacing: -.045em;
        }
        .hero-copy > p {
          margin: 14px 0 24px;
          font-size: clamp(16px, 2vw, 22px);
          opacity: .84;
        }
        .hero-status {
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 9px;
          font-size: 13px;
          font-weight: 600;
        }
        .online-dot, .source-dot, .availability-dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: var(--sp-error);
          box-shadow: 0 0 0 4px rgba(255,255,255,.14);
        }
        .online-dot.online { background: #75f0ad; }
        .divider { width: 1px; height: 16px; background: rgba(255,255,255,.35); }
        .router-visual {
          position: relative;
          z-index: 1;
          width: min(34vw, 330px);
          min-width: 230px;
          aspect-ratio: 1.4;
        }
        .router-body {
          position: absolute;
          right: 2%;
          bottom: 5%;
          width: 72%;
          height: 80%;
          border: 2px solid rgba(255,255,255,.62);
          border-radius: 20px 20px 26px 26px;
          background: linear-gradient(145deg, rgba(255,255,255,.28), rgba(255,255,255,.08));
          box-shadow: inset 0 1px 0 rgba(255,255,255,.42), 0 24px 50px rgba(65,0,30,.28);
          backdrop-filter: blur(12px);
          transform: perspective(800px) rotateY(-8deg);
        }
        .router-body::after {
          content: "";
          position: absolute;
          left: 12%;
          right: 12%;
          bottom: -7px;
          height: 8px;
          border-radius: 0 0 12px 12px;
          background: rgba(255,255,255,.5);
        }
        .router-logo {
          position: absolute;
          top: 18%;
          left: 16%;
          display: grid;
          place-items: center;
          width: 44px;
          height: 44px;
          border: 2px solid rgba(255,255,255,.7);
          border-radius: 12px;
          font-size: 24px;
          font-weight: 900;
        }
        .router-leds {
          position: absolute;
          left: 18%;
          right: 18%;
          bottom: 16%;
          display: flex;
          justify-content: space-between;
        }
        .router-leds i {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #7df4b3;
          box-shadow: 0 0 12px #7df4b3;
        }
        .signal-wave {
          position: absolute;
          border: 2px solid rgba(255,255,255,.36);
          border-left-color: transparent;
          border-bottom-color: transparent;
          border-radius: 50%;
          transform: rotate(-45deg);
        }
        .wave-one { width: 70px; height: 70px; top: 6%; right: 0; }
        .wave-two { width: 110px; height: 110px; top: -4%; right: -10%; }
        .router-tabs {
          display: flex;
          gap: 8px;
          overflow-x: auto;
          padding: 18px 2px 6px;
          scrollbar-width: none;
        }
        .router-tabs button {
          flex: none;
          padding: 10px 16px;
          color: var(--sp-muted);
          border: 1px solid var(--sp-border);
          border-radius: 999px;
          background: var(--sp-surface);
          cursor: pointer;
        }
        .router-tabs button.active {
          color: white;
          border-color: var(--sp-magenta);
          background: var(--sp-magenta);
        }
        .notice {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: 18px;
          padding: 13px 16px;
          border: 1px solid color-mix(in srgb, var(--sp-magenta) 32%, var(--sp-border));
          border-radius: 14px;
          background: color-mix(in srgb, var(--sp-magenta) 8%, var(--sp-surface));
        }
        .management-alert {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          gap: 16px;
          margin-top: 22px;
          padding: 18px 20px;
          border: 1px solid var(--sp-border);
          border-radius: 18px;
          background: var(--sp-surface);
          box-shadow: 0 8px 28px rgba(0,0,0,.05);
        }
        .management-alert > ha-icon { --mdc-icon-size: 28px; }
        .management-alert strong { display: block; margin-bottom: 4px; }
        .management-alert p { margin: 0; color: var(--sp-muted); line-height: 1.45; }
        .management-alert.warning {
          border-color: color-mix(in srgb, var(--sp-error) 48%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-error) 7%, var(--sp-surface));
        }
        .management-alert.caution {
          border-color: color-mix(in srgb, var(--sp-warning) 48%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-warning) 7%, var(--sp-surface));
        }
        .management-alert.good > ha-icon { color: var(--sp-success); }
        .state-pill {
          padding: 7px 11px;
          border-radius: 999px;
          color: var(--sp-muted);
          background: var(--sp-surface-soft);
          font-size: 12px;
          font-weight: 700;
        }
        .access-overview, .dashboard-section {
          margin-top: 24px;
          padding: clamp(18px, 3vw, 28px);
          border: 1px solid var(--sp-border);
          border-radius: 22px;
          background: var(--sp-surface);
          box-shadow: 0 10px 32px rgba(0,0,0,.045);
        }
        .access-overview > header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 18px;
        }
        .kicker {
          color: var(--sp-magenta);
          font-size: 11px;
          font-weight: 800;
          letter-spacing: .1em;
          text-transform: uppercase;
        }
        .access-overview h2 { margin: 4px 0 0; font-size: 22px; }
        .icon-button {
          display: grid;
          place-items: center;
          width: 42px;
          height: 42px;
          color: var(--sp-magenta);
          border: 1px solid var(--sp-border);
          border-radius: 12px;
          background: transparent;
          cursor: pointer;
        }
        .source-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
        }
        .source {
          display: grid;
          grid-template-columns: auto 1fr;
          align-items: center;
          gap: 7px 9px;
          min-width: 0;
          padding: 13px;
          border-radius: 14px;
          background: var(--sp-surface-soft);
        }
        .source span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .source strong { grid-column: 2; color: var(--sp-muted); font-size: 11px; }
        .source.available .source-dot { background: var(--sp-success); box-shadow: none; }
        .source.unavailable .source-dot { box-shadow: none; }
        .source.unsupported .source-dot { background: var(--sp-muted); box-shadow: none; opacity: .55; }
        .source.unsupported { opacity: .7; }
        .capability-details {
          margin-top: 14px;
          border-top: 1px solid var(--sp-border);
        }
        .capability-details summary {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 16px 2px 2px;
          cursor: pointer;
          font-weight: 700;
        }
        .capability-details summary small { color: var(--sp-muted); font-weight: 500; }
        .capability-content {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 14px;
          padding-top: 16px;
        }
        .capability-group > strong { font-size: 12px; color: var(--sp-muted); }
        .capability-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
        .capability-chips span {
          padding: 6px 9px;
          border: 1px solid var(--sp-border);
          border-radius: 999px;
          font-size: 11px;
        }
        .hero-metrics {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 16px;
          margin-top: 24px;
        }
        .hero-metric {
          display: flex;
          align-items: center;
          gap: 18px;
          min-width: 0;
          padding: clamp(20px, 3vw, 30px);
          overflow: hidden;
          border: 1px solid var(--sp-border);
          border-radius: 22px;
          background:
            linear-gradient(135deg, color-mix(in srgb, var(--sp-magenta) 11%, transparent), transparent 58%),
            var(--sp-surface);
          box-shadow: 0 12px 34px rgba(0,0,0,.055);
          cursor: pointer;
        }
        .hero-icon {
          display: grid;
          flex: none;
          place-items: center;
          width: 58px;
          height: 58px;
          color: white;
          border-radius: 17px;
          background: var(--sp-magenta);
          box-shadow: 0 12px 24px color-mix(in srgb, var(--sp-magenta) 28%, transparent);
        }
        .hero-icon ha-icon { --mdc-icon-size: 31px; }
        .hero-metric > div:last-child { min-width: 0; }
        .hero-metric span, .hero-metric small { display: block; color: var(--sp-muted); }
        .hero-metric strong {
          display: block;
          margin: 3px 0 4px;
          overflow: hidden;
          font-size: clamp(27px, 4vw, 43px);
          line-height: 1.1;
          letter-spacing: -.035em;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .hero-metric.unavailable { opacity: .72; }
        .sections { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
        .dashboard-section { min-width: 0; }
        .section-bandwidth, .section-clients, .section-controls { grid-column: 1 / -1; }
        .section-heading {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          gap: 13px;
          margin-bottom: 18px;
        }
        .section-icon, .entity-icon {
          display: grid;
          place-items: center;
          flex: none;
          color: var(--sp-magenta);
          background: color-mix(in srgb, var(--sp-magenta) 10%, var(--sp-surface));
        }
        .section-icon { width: 42px; height: 42px; border-radius: 13px; }
        .section-heading h2 { margin: 0; font-size: 19px; }
        .section-heading p { margin: 3px 0 0; color: var(--sp-muted); font-size: 12px; }
        .section-count {
          min-width: 28px;
          padding: 5px 8px;
          border-radius: 999px;
          color: var(--sp-muted);
          background: var(--sp-surface-soft);
          text-align: center;
          font-size: 11px;
          font-weight: 700;
        }
        .entity-source-groups { display: grid; gap: 20px; }
        .entity-source-group { min-width: 0; }
        .entity-source-heading {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          gap: 10px;
          margin: 0 1px 10px;
          padding: 9px 10px;
          border-radius: 12px;
          background: color-mix(in srgb, var(--sp-success) 6%, var(--sp-surface-soft));
        }
        .entity-source-heading.unavailable {
          background: color-mix(in srgb, var(--sp-warning) 8%, var(--sp-surface-soft));
        }
        .entity-source-heading.unsupported { opacity: .68; }
        .entity-source-icon {
          display: grid;
          place-items: center;
          width: 30px;
          height: 30px;
          color: var(--sp-magenta);
        }
        .entity-source-icon ha-icon { --mdc-icon-size: 20px; }
        .entity-source-heading strong { display: block; font-size: 12px; }
        .entity-source-heading p {
          margin: 2px 0 0;
          color: var(--sp-muted);
          font-size: 10px;
          line-height: 1.35;
        }
        .entity-source-status {
          display: flex;
          align-items: center;
          gap: 6px;
          color: var(--sp-muted);
          font-size: 10px;
          font-weight: 700;
          white-space: nowrap;
        }
        .entity-source-status i {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--sp-success);
        }
        .entity-source-heading.unavailable .entity-source-status i { background: var(--sp-warning); }
        .entity-source-heading.unsupported .entity-source-status i { background: var(--sp-muted); }
        .entity-capability-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
          align-items: start;
          gap: 10px;
        }
        .entity-capability-block {
          min-width: 0;
          padding: 10px;
          border: 1px solid var(--sp-border);
          border-radius: 15px;
          background: color-mix(in srgb, var(--sp-surface-soft) 78%, transparent);
        }
        .entity-capability-block.device-capability-block { grid-column: 1 / -1; }
        .entity-capability-heading {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: center;
          gap: 8px;
          margin-bottom: 9px;
          padding: 0 2px;
        }
        .entity-capability-icon {
          display: grid;
          place-items: center;
          width: 28px;
          height: 28px;
          color: var(--sp-magenta);
          border-radius: 9px;
          background: color-mix(in srgb, var(--sp-magenta) 8%, var(--sp-surface));
        }
        .entity-capability-icon ha-icon { --mdc-icon-size: 17px; }
        .entity-capability-heading h3 {
          margin: 0;
          overflow: hidden;
          font-size: 12px;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .entity-capability-count {
          min-width: 22px;
          padding: 3px 6px;
          color: var(--sp-muted);
          border-radius: 999px;
          background: var(--sp-surface);
          font-size: 9px;
          font-weight: 700;
          text-align: center;
        }
        .capability-entity-grid { grid-template-columns: 1fr; gap: 7px; }
        .entity-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 230px), 1fr));
          gap: 10px;
        }
        .entity-grid + .child-device-grid { margin-top: 12px; }
        .child-device-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 270px), 1fr));
          align-items: start;
          gap: 12px;
        }
        .child-device-card {
          min-width: 0;
          padding: 12px;
          border: 1px solid color-mix(in srgb, var(--sp-magenta) 16%, var(--sp-border));
          border-radius: 17px;
          background: color-mix(in srgb, var(--sp-magenta) 3%, var(--sp-surface-soft));
        }
        .child-device-card.unavailable { opacity: .68; }
        .child-device-heading {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: center;
          gap: 10px;
          margin-bottom: 10px;
          padding: 0 2px;
        }
        .child-device-icon {
          display: grid;
          place-items: center;
          width: 34px;
          height: 34px;
          color: var(--sp-magenta);
          border-radius: 11px;
          background: color-mix(in srgb, var(--sp-magenta) 9%, var(--sp-surface));
        }
        .child-device-icon ha-icon { --mdc-icon-size: 19px; }
        .child-device-copy { min-width: 0; }
        .child-device-copy strong,
        .child-device-copy small {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .child-device-copy strong { font-size: 13px; }
        .child-device-copy small {
          margin-top: 2px;
          color: var(--sp-muted);
          font-size: 9px;
        }
        .child-device-count {
          min-width: 24px;
          padding: 4px 7px;
          color: var(--sp-muted);
          border: 1px solid var(--sp-border);
          border-radius: 999px;
          background: var(--sp-surface);
          font-size: 9px;
          font-weight: 700;
          text-align: center;
        }
        .child-device-entities { display: grid; gap: 7px; }
        .entity-card {
          min-width: 0;
          overflow: hidden;
          border: 1px solid var(--sp-border);
          border-radius: 15px;
          background: var(--sp-surface-soft);
        }
        .entity-card.unavailable { opacity: .62; }
        .child-entity-card {
          border-radius: 11px;
          background: var(--sp-surface);
        }
        .entity-main {
          display: grid;
          grid-template-columns: auto 1fr auto;
          align-items: center;
          gap: 11px;
          width: 100%;
          min-width: 0;
          padding: 13px;
          color: inherit;
          border: 0;
          background: transparent;
          text-align: left;
          cursor: pointer;
        }
        .entity-icon { width: 36px; height: 36px; border-radius: 11px; }
        .entity-icon ha-icon { --mdc-icon-size: 21px; }
        .entity-copy { min-width: 0; }
        .entity-name, .entity-state {
          display: block;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .entity-name { color: var(--sp-muted); font-size: 11px; }
        .entity-state { margin-top: 3px; font-size: 15px; }
        .source-badge {
          display: block;
          margin-top: 4px;
          overflow: hidden;
          color: var(--sp-muted);
          font-size: 9px;
          font-weight: 600;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .child-entity-card .entity-main {
          gap: 9px;
          padding: 9px 10px;
        }
        .child-entity-card .entity-icon {
          width: 30px;
          height: 30px;
          border-radius: 9px;
        }
        .child-entity-card .entity-icon ha-icon { --mdc-icon-size: 18px; }
        .child-entity-card .entity-copy {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: center;
          gap: 8px;
        }
        .child-entity-card .entity-name { font-size: 10px; }
        .child-entity-card .entity-state { margin-top: 0; font-size: 12px; }
        .child-entity-card .source-badge { display: none; }
        .child-entity-card .entity-action {
          width: calc(100% - 20px);
          margin: 0 10px 9px;
          padding: 7px 10px;
          font-size: 10px;
        }
        .availability-dot { width: 7px; height: 7px; box-shadow: none; }
        .available .availability-dot { background: var(--sp-success); }
        .entity-action {
          width: calc(100% - 24px);
          margin: 0 12px 12px;
          padding: 9px 12px;
          color: var(--sp-magenta);
          border: 1px solid color-mix(in srgb, var(--sp-magenta) 35%, var(--sp-border));
          border-radius: 10px;
          background: color-mix(in srgb, var(--sp-magenta) 7%, var(--sp-surface));
          font-size: 12px;
          font-weight: 700;
          cursor: pointer;
        }
        .entity-action.disruptive { color: var(--sp-error); border-color: color-mix(in srgb, var(--sp-error) 35%, var(--sp-border)); }
        button:disabled { cursor: not-allowed; opacity: .48; }
        button:focus-visible, summary:focus-visible {
          outline: 2px solid var(--sp-magenta);
          outline-offset: 2px;
        }
        footer {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 28px 4px 8px;
          color: var(--sp-muted);
          font-size: 11px;
        }
        .loading-shell, .empty-shell {
          min-height: calc(100vh - 64px);
          display: grid;
          place-items: center;
        }
        .loading-shell { align-content: center; color: var(--sp-muted); }
        .loading-mark, .brand-mark {
          display: flex;
          align-items: flex-end;
          gap: 7px;
          height: 54px;
        }
        .loading-mark span, .brand-mark span {
          width: 13px;
          height: 13px;
          border-radius: 3px;
          background: var(--sp-magenta);
          animation: speedport-pulse 1.1s ease-in-out infinite;
        }
        .loading-mark span:nth-child(2), .brand-mark span:nth-child(2) { height: 42px; animation-delay: .12s; }
        .loading-mark span:nth-child(3), .brand-mark span:nth-child(3) { animation-delay: .24s; }
        .brand-mark span { animation: none; }
        @keyframes speedport-pulse { 50% { transform: translateY(-8px); opacity: .55; } }
        .empty-card {
          width: min(100%, 520px);
          padding: clamp(28px, 6vw, 52px);
          border: 1px solid var(--sp-border);
          border-radius: 24px;
          background: var(--sp-surface);
          box-shadow: 0 20px 60px rgba(0,0,0,.08);
          text-align: center;
        }
        .empty-card .brand-mark { justify-content: center; }
        .empty-card > ha-icon { color: var(--sp-error); --mdc-icon-size: 44px; }
        .empty-card h1 { margin: 20px 0 8px; }
        .empty-card p { color: var(--sp-muted); line-height: 1.55; }
        .primary, .secondary {
          padding: 11px 17px;
          border-radius: 11px;
          font-weight: 700;
          cursor: pointer;
        }
        .primary { color: white; border: 1px solid var(--sp-magenta); background: var(--sp-magenta); }
        .secondary { color: var(--sp-text); border: 1px solid var(--sp-border); background: transparent; }
        .modal-backdrop {
          position: fixed;
          z-index: 1000;
          inset: 0;
          display: grid;
          place-items: center;
          padding: 18px;
          background: rgba(8, 8, 12, .58);
          backdrop-filter: blur(7px);
        }
        .confirm-dialog {
          width: min(100%, 460px);
          padding: 28px;
          color: var(--sp-text);
          border: 1px solid var(--sp-border);
          border-radius: 22px;
          background: var(--sp-surface);
          box-shadow: 0 28px 90px rgba(0,0,0,.35);
        }
        .confirm-icon {
          display: grid;
          place-items: center;
          width: 52px;
          height: 52px;
          color: var(--sp-magenta);
          border-radius: 16px;
          background: color-mix(in srgb, var(--sp-magenta) 10%, var(--sp-surface));
        }
        .confirm-dialog.danger .confirm-icon { color: var(--sp-error); background: color-mix(in srgb, var(--sp-error) 10%, var(--sp-surface)); }
        .confirm-dialog h2 { margin: 18px 0 8px; }
        .confirm-dialog p { color: var(--sp-muted); line-height: 1.55; }
        .confirm-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
        :host([narrow]) .sections { grid-template-columns: 1fr; }
        :host([narrow]) .dashboard-section { grid-column: auto; }
        :host([narrow]) .entity-capability-grid { grid-template-columns: 1fr; }
        @media (max-width: 900px) {
          .sections { grid-template-columns: 1fr; }
          .dashboard-section { grid-column: auto; }
          .source-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 680px) {
          .shell { padding: 12px; }
          .hero { min-height: 235px; padding: 26px 22px; border-radius: 22px; }
          .router-visual { position: absolute; right: -76px; bottom: -18px; opacity: .4; }
          .hero-copy { max-width: 88%; }
          .hero h1 { font-size: clamp(32px, 11vw, 48px); }
          .hero-metrics { grid-template-columns: 1fr; }
          .management-alert { grid-template-columns: auto 1fr; }
          .management-alert .state-pill { grid-column: 2; justify-self: start; }
          .access-overview, .dashboard-section { margin-top: 14px; padding: 16px; border-radius: 17px; }
          .section-heading p { display: none; }
          .entity-source-heading { grid-template-columns: auto 1fr; }
          .entity-source-status { grid-column: 2; justify-self: start; }
          .entity-capability-grid { grid-template-columns: 1fr; }
          footer { flex-direction: column; }
        }
        @media (max-width: 430px) {
          .source-grid { grid-template-columns: 1fr; }
          .entity-grid { grid-template-columns: 1fr; }
          .child-device-grid { grid-template-columns: 1fr; }
          .hero-status .divider, .hero-status .divider + * { display: none; }
          .confirm-dialog { padding: 22px; }
          .confirm-actions { flex-direction: column-reverse; }
          .confirm-actions button { width: 100%; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { animation: none !important; scroll-behavior: auto !important; }
        }
      </style>
    `;
  }
}

if (!customElements.get("speedport-smart-panel")) {
  customElements.define("speedport-smart-panel", SpeedportSmartPanel);
}
