import { keepDialogFocus } from "./accessibility.js?schema=7";
import {
  controlConfirmationPhrase,
  controlConfirmationPolicyMatches,
  isSupportedSelectControl,
  isSupportedTextControl,
  managementControlAvailable,
  selectControlOptions,
  selectControlServiceCall,
  switchControlServiceCall,
  textControlConstraints,
  textControlServiceCall,
  typedConfirmationMatches,
  validateTextControlValue,
} from "./controls.js?schema=7";
import {
  aggregateAvailability,
  entityDisplayName,
  entityAvailability,
} from "./entity-state.js?schema=7";
import {
  captureRenderState,
  restoreDetailsState,
  restoreFocusState,
} from "./render-state.js?schema=7";
import {
  formatPanelDurationSeconds,
  panelTranslate,
  resolvePanelLanguage,
} from "./translations.js?schema=7";

const API_TYPE = "speedport_smart/panel";
const PANEL_SCHEMA_VERSION = 7;
const METADATA_REFRESH_INTERVAL_MS = 10_000;
const HERO_KEYS = new Set(["wan_download_rate", "wan_upload_rate"]);
const WAN_CUMULATIVE_KEYS = new Set([
  "wan_bytes_received",
  "wan_bytes_sent",
  "wan_discarded_packets_received",
  "wan_discarded_packets_sent",
  "wan_errors_received",
  "wan_errors_sent",
  "wan_packets_received",
  "wan_packets_sent",
]);
const WAN_RATE_KEYS = new Set(["wan_download_rate", "wan_upload_rate"]);
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
    titleKey: "section.connection.title",
    subtitleKey: "section.connection.subtitle",
    icon: "mdi:web",
  },
  bandwidth: {
    titleKey: "section.bandwidth.title",
    subtitleKey: "section.bandwidth.subtitle",
    icon: "mdi:speedometer",
  },
  dsl: {
    titleKey: "section.dsl.title",
    subtitleKey: "section.dsl.subtitle",
    icon: "mdi:transmission-tower",
  },
  mobile: {
    titleKey: "section.mobile.title",
    subtitleKey: "section.mobile.subtitle",
    icon: "mdi:signal-cellular-3",
  },
  wireless: {
    titleKey: "section.wireless.title",
    subtitleKey: "section.wireless.subtitle",
    icon: "mdi:wifi",
  },
  clients: {
    titleKey: "section.clients.title",
    subtitleKey: "section.clients.subtitle",
    icon: "mdi:lan",
  },
  telephony: {
    titleKey: "section.telephony.title",
    subtitleKey: "section.telephony.subtitle",
    icon: "mdi:phone",
  },
  system: {
    titleKey: "section.system.title",
    subtitleKey: "section.system.subtitle",
    icon: "mdi:router-network",
  },
  management: {
    titleKey: "section.management.title",
    subtitleKey: "section.management.subtitle",
    icon: "mdi:shield-check-outline",
  },
  controls: {
    titleKey: "section.controls.title",
    subtitleKey: "section.controls.subtitle",
    icon: "mdi:gesture-tap-button",
  },
};
const ACCESS_SOURCE_ORDER = [
  "public_status",
  "public_json",
  "integration",
  "protected_json",
  "totr64",
  "wan_counters",
  "router_control",
];
const ACCESS_SOURCE_INFO = {
  public_status: {
    titleKey: "source.public_status.title",
    shortKey: "source.public_status.short",
    descriptionKey: "source.public_status.description",
    icon: "mdi:shield-check-outline",
  },
  public_json: {
    titleKey: "source.public_json.title",
    shortKey: "source.public_json.short",
    descriptionKey: "source.public_json.description",
    icon: "mdi:file-document-outline",
  },
  protected_json: {
    titleKey: "source.protected_json.title",
    shortKey: "source.protected_json.short",
    descriptionKey: "source.protected_json.description",
    icon: "mdi:account-lock-outline",
  },
  totr64: {
    titleKey: "source.totr64.title",
    shortKey: "source.totr64.short",
    descriptionKey: "source.totr64.description",
    icon: "mdi:lan-connect",
  },
  wan_counters: {
    titleKey: "source.wan_counters.title",
    shortKey: "source.wan_counters.short",
    descriptionKey: "source.wan_counters.description",
    icon: "mdi:speedometer",
  },
  integration: {
    titleKey: "source.integration.title",
    shortKey: "source.integration.short",
    descriptionKey: "source.integration.description",
    icon: "mdi:home-assistant",
  },
  router_control: {
    titleKey: "source.router_control.title",
    shortKey: "source.router_control.short",
    descriptionKey: "source.router_control.description",
    icon: "mdi:gesture-tap-button",
  },
};
const CHILD_KIND_INFO = {
  client: { labelKey: "child.client", icon: "mdi:devices" },
  dect_handset: { labelKey: "child.dect_handset", icon: "mdi:phone-wireless" },
  ip_phone: { labelKey: "child.ip_phone", icon: "mdi:deskphone" },
  mesh_node: { labelKey: "child.mesh_node", icon: "mdi:access-point-network" },
  receiver: { labelKey: "child.receiver", icon: "mdi:access-point-network" },
  telephone_line: { labelKey: "child.telephone_line", icon: "mdi:phone-in-talk" },
  usb_device: { labelKey: "child.usb_device", icon: "mdi:usb" },
};

const DECIMAL_DATA_FACTORS = {
  B: 1,
  kB: 1_000,
  MB: 1_000_000,
  GB: 1_000_000_000,
  TB: 1_000_000_000_000,
};
const CAPABILITY_GROUP_INFO = {
  connection_internet: { titleKey: "group.connection_internet", icon: "mdi:web-check" },
  connection_addressing: { titleKey: "group.connection_addressing", icon: "mdi:ip-network-outline" },
  connection_privacy: { titleKey: "group.connection_privacy", icon: "mdi:shield-account-outline" },
  bandwidth_capacity: { titleKey: "group.bandwidth_capacity", icon: "mdi:gauge" },
  bandwidth_totals: { titleKey: "group.bandwidth_totals", icon: "mdi:database-arrow-up-outline" },
  bandwidth_packets: { titleKey: "group.bandwidth_packets", icon: "mdi:package-variant-closed" },
  bandwidth_errors: { titleKey: "group.bandwidth_errors", icon: "mdi:alert-circle-outline" },
  bandwidth_interface: { titleKey: "group.bandwidth_interface", icon: "mdi:ethernet" },
  bandwidth_polling: { titleKey: "group.bandwidth_polling", icon: "mdi:timer-sync-outline" },
  bandwidth_live: { titleKey: "group.bandwidth_live", icon: "mdi:swap-vertical-bold" },
  dsl_status: { titleKey: "group.dsl_status", icon: "mdi:connection" },
  dsl_sync: { titleKey: "group.dsl_sync", icon: "mdi:transmission-tower" },
  dsl_attainable: { titleKey: "group.dsl_attainable", icon: "mdi:speedometer" },
  dsl_quality: { titleKey: "group.dsl_quality", icon: "mdi:sine-wave" },
  dsl_errors: { titleKey: "group.dsl_errors", icon: "mdi:alert-outline" },
  mobile_connection: { titleKey: "group.mobile_connection", icon: "mdi:signal-cellular-3" },
  mobile_radio: { titleKey: "group.mobile_radio", icon: "mdi:radio-tower" },
  mobile_signal: { titleKey: "group.mobile_signal", icon: "mdi:signal" },
  mobile_tunnel: { titleKey: "group.mobile_tunnel", icon: "mdi:swap-vertical" },
  mobile_receivers: { titleKey: "group.mobile_receivers", icon: "mdi:access-point-network" },
  mobile_receiver_status: { titleKey: "group.mobile_receiver_status", icon: "mdi:access-point-network" },
  mobile_receiver_firmware: { titleKey: "group.mobile_receiver_firmware", icon: "mdi:update" },
  wireless_2_4: { titleKey: "group.wireless_2_4", icon: "mdi:wifi" },
  wireless_5: { titleKey: "group.wireless_5", icon: "mdi:wifi" },
  wireless_guest: { titleKey: "group.wireless_guest", icon: "mdi:wifi-star" },
  wireless_office: { titleKey: "group.wireless_office", icon: "mdi:wifi-cog" },
  wireless_mesh: { titleKey: "group.wireless_mesh", icon: "mdi:access-point-network" },
  wireless_mesh_nodes: { titleKey: "group.wireless_mesh_nodes", icon: "mdi:access-point-network" },
  wireless_radios: { titleKey: "group.wireless_radios", icon: "mdi:radio-tower" },
  wireless_access: { titleKey: "group.wireless_access", icon: "mdi:account-lock-outline" },
  wireless_wps: { titleKey: "group.wireless_wps", icon: "mdi:wifi-plus" },
  wireless_schedule: { titleKey: "group.wireless_schedule", icon: "mdi:calendar-clock" },
  wireless_general: { titleKey: "group.wireless_general", icon: "mdi:wifi-cog" },
  clients_overview: { titleKey: "group.clients_overview", icon: "mdi:devices" },
  clients_devices: { titleKey: "group.clients_devices", icon: "mdi:laptop" },
  clients_lan: { titleKey: "group.clients_lan", icon: "mdi:ethernet" },
  clients_dhcp: { titleKey: "group.clients_dhcp", icon: "mdi:ip-network" },
  clients_forwarding: { titleKey: "group.clients_forwarding", icon: "mdi:router-network" },
  clients_upnp: { titleKey: "group.clients_upnp", icon: "mdi:lan-connect" },
  telephony_registration: { titleKey: "group.telephony_registration", icon: "mdi:phone-check" },
  telephony_calls: { titleKey: "group.telephony_calls", icon: "mdi:phone-in-talk" },
  telephony_lines: { titleKey: "group.telephony_lines", icon: "mdi:phone-classic" },
  telephony_dect: { titleKey: "group.telephony_dect", icon: "mdi:phone-wireless" },
  telephony_pbx: { titleKey: "group.telephony_pbx", icon: "mdi:phone-switch" },
  telephony_voip: { titleKey: "group.telephony_voip", icon: "mdi:phone-lock" },
  telephony_ip: { titleKey: "group.telephony_ip", icon: "mdi:deskphone" },
  telephony_phonebooks: { titleKey: "group.telephony_phonebooks", icon: "mdi:book-open-page-variant" },
  system_health: { titleKey: "group.system_health", icon: "mdi:chip" },
  system_firmware: { titleKey: "group.system_firmware", icon: "mdi:update" },
  system_security: { titleKey: "group.system_security", icon: "mdi:shield-lock-outline" },
  system_security_dns: { titleKey: "group.system_security_dns", icon: "mdi:dns-outline" },
  system_security_port_block: { titleKey: "group.system_security_port_block", icon: "mdi:shield-lock-outline" },
  system_security_qos: { titleKey: "group.system_security_qos", icon: "mdi:priority-high" },
  system_ddns: { titleKey: "group.system_ddns", icon: "mdi:dns-outline" },
  system_vpn: { titleKey: "group.system_vpn", icon: "mdi:vpn" },
  system_parental: { titleKey: "group.system_parental", icon: "mdi:account-child-outline" },
  system_usb: { titleKey: "group.system_usb", icon: "mdi:usb" },
  system_usb_tethering: { titleKey: "group.system_usb_tethering", icon: "mdi:usb-port" },
  system_nas: { titleKey: "group.system_nas", icon: "mdi:nas" },
  system_support: { titleKey: "group.system_support", icon: "mdi:lifebuoy" },
  system_services: { titleKey: "group.system_services", icon: "mdi:cog-outline" },
  management_session: { titleKey: "group.management_session", icon: "mdi:account-lock-outline" },
  management_health: { titleKey: "group.management_health", icon: "mdi:home-assistant" },
  controls_wireless: { titleKey: "group.controls_wireless", icon: "mdi:wifi-cog" },
  controls_internet: { titleKey: "group.controls_internet", icon: "mdi:web-sync" },
  controls_mobile: { titleKey: "group.controls_mobile", icon: "mdi:signal-5g" },
  controls_mesh: { titleKey: "group.controls_mesh", icon: "mdi:access-point-network" },
  controls_clients: { titleKey: "group.controls_clients", icon: "mdi:account-lock-outline" },
  controls_forwarding: { titleKey: "group.controls_forwarding", icon: "mdi:router-network" },
  controls_ddns: { titleKey: "group.controls_ddns", icon: "mdi:dns-outline" },
  controls_vpn: { titleKey: "group.controls_vpn", icon: "mdi:vpn" },
  controls_parental: { titleKey: "group.controls_parental", icon: "mdi:account-child-outline" },
  controls_media: { titleKey: "group.controls_media", icon: "mdi:multimedia" },
  controls_system: { titleKey: "group.controls_system", icon: "mdi:power-cycle" },
  controls_session: { titleKey: "group.controls_session", icon: "mdi:account-sync-outline" },
};
const CAPABILITY_GROUP_ORDER = {
  connection: ["connection_internet", "connection_addressing", "connection_privacy"],
  bandwidth: ["bandwidth_capacity", "bandwidth_totals", "bandwidth_packets", "bandwidth_errors", "bandwidth_interface", "bandwidth_polling", "bandwidth_live"],
  dsl: ["dsl_status", "dsl_sync", "dsl_attainable", "dsl_quality", "dsl_errors"],
  mobile: ["mobile_connection", "mobile_radio", "mobile_signal", "mobile_tunnel", "mobile_receiver_status", "mobile_receiver_firmware", "mobile_receivers"],
  wireless: ["wireless_2_4", "wireless_5", "wireless_guest", "wireless_office", "wireless_radios", "wireless_access", "wireless_wps", "wireless_schedule", "wireless_mesh", "wireless_mesh_nodes", "wireless_general"],
  clients: ["clients_overview", "clients_devices", "clients_lan", "clients_dhcp", "clients_forwarding", "clients_upnp"],
  telephony: ["telephony_registration", "telephony_calls", "telephony_lines", "telephony_dect", "telephony_pbx", "telephony_voip", "telephony_ip", "telephony_phonebooks"],
  system: ["system_health", "system_firmware", "system_support", "system_security", "system_security_dns", "system_security_port_block", "system_security_qos", "system_ddns", "system_vpn", "system_parental", "system_usb", "system_usb_tethering", "system_nas", "system_services"],
  management: ["management_session", "management_health"],
  controls: ["controls_session", "controls_wireless", "controls_internet", "controls_mobile", "controls_mesh", "controls_clients", "controls_forwarding", "controls_ddns", "controls_vpn", "controls_parental", "controls_media", "controls_system"],
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

export function capabilityGroupFor(meta) {
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
  if (meta.capability_group && CAPABILITY_GROUP_INFO[meta.capability_group]) {
    return meta.capability_group;
  }

  if (section === "connection") {
    if (key.startsWith("public_ipv") || key === "internet_ip_stack") {
      return "connection_addressing";
    }
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
    if (key.startsWith("wan_interface") || key === "wan_mtu") {
      return "bandwidth_interface";
    }
    if (
      key.startsWith("wan_polling") ||
      key === "wan_fastest_proven_interval" ||
      key === "wan_last_sample"
    ) {
      return "bandwidth_polling";
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
    if (
      key.startsWith("lte_tunnel") ||
      (key.startsWith("hybrid_") && key.endsWith("_tunnel"))
    ) {
      return "mobile_tunnel";
    }
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
    if (key.startsWith("wifi_wps")) return "wireless_wps";
    if (key === "wifi_mac_filter_enabled") return "wireless_access";
    if (key.startsWith("wifi_schedule")) return "wireless_schedule";
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
    if (key.startsWith("pbx_")) return "telephony_pbx";
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
    if (key.startsWith("usb") || key.startsWith("media_server")) {
      return "system_usb";
    }
    return "system_services";
  }
  if (section === "management") {
    return key === "management_access"
      ? "management_session"
      : "management_health";
  }
  if (section === "controls") {
    if (key === "retry_protected_data") return "controls_session";
    if (
      [
        "hybrid_bonding",
        "internet_privacy_level_control",
        "reconnect_internet",
        "restart_dsl",
      ].includes(key)
    ) {
      return "controls_internet";
    }
    if (key === "receiver_led_mode_control") return "controls_mobile";
    if (["wifi", "guest_wifi", "office_wifi", "wps"].includes(key)) {
      return "controls_wireless";
    }
    if (key === "optimize_mesh") return "controls_mesh";
    if (
      ["client_fixed_dhcp", "client_internet_access", "client_name"].includes(
        key,
      )
    ) {
      return "controls_clients";
    }
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
    titleKey: groupId.endsWith("_devices")
      ? "group.other_devices"
      : "group.other",
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
  if (meta.domain === "select") return "mdi:form-dropdown";
  if (meta.domain === "button") return "mdi:gesture-tap-button";
  if (meta.domain === "binary_sensor") return "mdi:checkbox-marked-circle-outline";
  if (meta.domain === "device_tracker") return "mdi:devices";
  if (meta.domain === "update") return "mdi:update";
  if (meta.domain === "text" && meta.translation_key === "client_name") {
    return "mdi:rename-box";
  }
  return SECTION_INFO[meta.section]?.icon || "mdi:gauge";
}

export function internetConnectionPresentation(state) {
  if (!state || ["unavailable", "unknown"].includes(state.state)) {
    return {
      className: "unavailable",
      labelKey: "hero.connection_unavailable",
    };
  }
  if (state.state === "on") {
    return { className: "online", labelKey: "hero.connected" };
  }
  return { className: "offline", labelKey: "hero.disconnected" };
}

export function liveWanSourceFromEntityStates(source, entities, states) {
  if (source?.id !== "wan_counters") return source;
  const live = { ...source };
  const stateFor = (translationKey) => {
    const entity = entities?.find(
      (candidate) => candidate.translation_key === translationKey,
    );
    return entity ? states?.[entity.entity_id] : undefined;
  };
  const usableState = (entityState) =>
    entityState && !["unavailable", "unknown"].includes(entityState.state)
      ? entityState.state
      : undefined;
  const positiveNumberState = (entityState) => {
    const numeric = Number(usableState(entityState));
    return Number.isFinite(numeric) && numeric > 0 ? numeric : undefined;
  };

  const mode = usableState(stateFor("wan_polling_mode"));
  if (["auto", "manual"].includes(mode)) live.mode = mode;

  const schedulerEntityState = stateFor("wan_polling_state");
  const schedulerState = usableState(schedulerEntityState);
  if (["learning", "stable", "retrying", "limited"].includes(schedulerState)) {
    live.state = schedulerState;
    live.retrying = schedulerState === "retrying";
  } else if (schedulerEntityState) {
    live.available = false;
    live.retrying = false;
  }
  const schedulerAttributes = schedulerEntityState?.attributes || {};
  if (typeof schedulerAttributes.source_available === "boolean") {
    live.available =
      source.polling_available !== false &&
      schedulerAttributes.source_available;
  }
  const retryInSeconds = Number(schedulerAttributes.retry_in_seconds);
  if (Number.isFinite(retryInSeconds) && retryInSeconds >= 0) {
    live.retry_in_seconds = retryInSeconds;
  }

  const interval = positiveNumberState(stateFor("wan_polling_interval"));
  if (interval !== undefined) live.effective_interval_seconds = interval;
  const fastest = positiveNumberState(
    stateFor("wan_fastest_proven_interval"),
  );
  if (fastest !== undefined) live.last_stable_interval_seconds = fastest;
  const lastSample = usableState(stateFor("wan_last_sample"));
  if (lastSample !== undefined) live.last_sampled_at = lastSample;
  return live;
}

export function wanTelemetryPresentation(
  meta,
  state,
  source,
  nowMilliseconds = Date.now(),
) {
  const isWanSource = source?.id === "wan_counters";
  const retrying =
    isWanSource && (source.retrying === true || source.state === "retrying");
  const degraded =
    isWanSource &&
    source?.supported !== false &&
    (retrying || source?.available === false);
  const interval = Number(source?.effective_interval_seconds);
  const effectiveIntervalSeconds =
    isWanSource && Number.isFinite(interval) && interval > 0
      ? interval
      : undefined;
  const sampledAtMilliseconds = Date.parse(source?.last_sampled_at || "");
  const stableInterval = Number(source?.last_stable_interval_seconds);
  const fastestProvenIntervalSeconds =
    isWanSource &&
    Number.isFinite(sampledAtMilliseconds) &&
    Number.isFinite(stableInterval) &&
    stableInterval > 0
      ? stableInterval
      : undefined;
  const mode =
    isWanSource && ["auto", "manual"].includes(source?.mode)
      ? source.mode
      : undefined;
  const schedulerState =
    isWanSource &&
    ["learning", "stable", "retrying", "limited"].includes(source?.state)
      ? source.state
      : undefined;
  const sampleAgeSeconds =
    isWanSource && Number.isFinite(sampledAtMilliseconds)
      ? Math.max(0, Math.floor((nowMilliseconds - sampledAtMilliseconds) / 1_000))
      : undefined;
  const retryIn = Number(source?.retry_in_seconds);
  const retryInSeconds =
    retrying && Number.isFinite(retryIn) && retryIn > 0 ? retryIn : undefined;
  const availability = entityAvailability(meta, state);
  const rateStatusKey = WAN_RATE_KEYS.has(meta?.translation_key)
    ? availability === "available"
      ? "status.recent_rate"
      : retrying
        ? "status.rate_retrying"
        : degraded
          ? "status.rate_unavailable"
          : "status.rate_warming"
    : undefined;
  return {
    degraded,
    effectiveIntervalSeconds,
    fastestProvenIntervalSeconds,
    lastConfirmed:
      degraded &&
      availability === "available" &&
      WAN_CUMULATIVE_KEYS.has(meta?.translation_key),
    mode,
    rateStatusKey,
    retrying,
    retryInSeconds,
    sampleAgeSeconds,
    schedulerState,
  };
}

export class SpeedportSmartPanel extends HTMLElement {
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
    this._noticeKind = "status";
    this._focusAfterRenderEntityId = undefined;
    this._refreshTimer = undefined;
    this._renderFrame = undefined;
    this.shadowRoot.addEventListener("click", (event) => this._handleClick(event));
    this.shadowRoot.addEventListener("input", (event) => this._handleInput(event));
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
      this._refreshTimer = window.setInterval(
        () => this._loadMetadata(),
        METADATA_REFRESH_INTERVAL_MS,
      );
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
    if (this._pendingAction) return false;
    if (
      !previous ||
      !this._metadata ||
      previous.language !== next.language ||
      previous.locale !== next.locale
    ) {
      return true;
    }
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
      this._loadError = "error.metadata_unavailable";
    } finally {
      this._loading = false;
      if (!this._pendingAction) this._render();
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
    const router = this._currentRouter();
    const managementMeta = router?.entities?.find(
      (entity) => entity.translation_key === "management_access",
    );
    const managementState = this._state(managementMeta);
    const controlsAvailable =
      managementState?.attributes?.controls_available ??
      router?.management?.controls_available;
    const managementStateValue =
      managementState?.state || router?.management?.state;
    return (
      this._isUnavailable(state) ||
      !managementControlAvailable(
        meta,
        managementStateValue,
        controlsAvailable,
      ) ||
      (meta?.domain === "text" && state?.state === "unknown") ||
      (meta?.domain === "select" && !isSupportedSelectControl(meta, state)) ||
      (meta?.domain === "switch" && !["on", "off"].includes(state?.state)) ||
      (meta?.domain === "update" && state?.state !== "on")
    );
  }

  _friendlyName(meta, state) {
    return entityDisplayName(
      meta,
      state,
      this._translatedEntityName(meta),
      humanize(meta?.translation_key || meta?.entity_id),
    );
  }

  _translatedEntityName(meta) {
    const key = `component.speedport_smart.entity.${meta.domain}.${meta.translation_key}.name`;
    return this._hass?.localize?.(key) || undefined;
  }

  _translatedSelectOption(meta, option) {
    if (!meta?.translation_key) return humanize(option);
    const key = `component.speedport_smart.entity.select.${meta.translation_key}.state.${option}`;
    return this._hass?.localize?.(key) || humanize(option);
  }

  _locale() {
    return (
      this._hass?.locale?.language ||
      this._hass?.language ||
      globalThis.navigator?.language ||
      "en"
    );
  }

  _language() {
    return resolvePanelLanguage(this._hass, globalThis.navigator?.language);
  }

  _t(key, replacements = {}) {
    return panelTranslate(this._language(), key, replacements);
  }

  _managementStateLabel(state) {
    const key = `management.state.${state}`;
    const translated = this._t(key);
    return translated === key ? humanize(state) : translated;
  }

  _entryStateLabel(state) {
    const key = `entry_state.${state}`;
    const translated = this._t(key);
    return translated === key ? humanize(state) : translated;
  }

  _capabilityName(name) {
    const key = `capability.${name}`;
    const translated = this._t(key);
    return translated === key ? humanize(name) : translated;
  }

  _formatState(state) {
    if (!state || state.state === "unavailable") {
      return this._t("status.unavailable");
    }
    if (state.state === "unknown") return this._t("status.unknown");
    const attributes = state.attributes || {};
    if (
      attributes.device_class === "duration" &&
      attributes.unit_of_measurement === "s"
    ) {
      const duration = formatPanelDurationSeconds(
        state.state,
        this._locale(),
        this._language(),
      );
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
      this._noticeKind = "status";
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
      this._closeConfirmation();
      return;
    }
    if (target.dataset.confirmAction !== undefined) {
      this._runPendingAction();
    }
  }

  _handleKeyDown(event) {
    if (!this._pendingAction) return;
    if (event.key === "Escape" && !this._actionBusy) {
      event.preventDefault();
      this._closeConfirmation();
      return;
    }
    if (
      event.key === "Enter" &&
      (event.target?.dataset?.textDraft !== undefined ||
        event.target?.dataset?.confirmDraft !== undefined) &&
      !this._actionBusy
    ) {
      event.preventDefault();
      this._runPendingAction();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = this.shadowRoot.querySelector(".confirm-dialog");
    keepDialogFocus(event, dialog, this.shadowRoot.activeElement);
  }

  _handleInput(event) {
    const pending = this._pendingAction;
    const target = event.target;
    if (!pending || !target?.dataset) {
      return;
    }
    if (pending.kind === "select" && target.dataset.selectDraft !== undefined) {
      if (pending.options?.includes(target.value)) pending.value = target.value;
      return;
    }
    if (pending.kind === "text" && target.dataset.textDraft !== undefined) {
      pending.value = target.value;
      pending.errorKey = undefined;
      target.removeAttribute("aria-invalid");
      const error = this.shadowRoot.querySelector("[data-text-error]");
      if (error) error.textContent = "";
      return;
    }
    if (target.dataset.confirmDraft !== undefined) {
      pending.confirmationDraft = target.value;
      pending.confirmationError = false;
      const matches = typedConfirmationMatches(
        pending.confirmationPhrase,
        pending.confirmationDraft,
      );
      target.removeAttribute("aria-invalid");
      const button = this.shadowRoot.querySelector("[data-confirm-action]");
      if (button) button.disabled = this._actionBusy || !matches;
      const error = this.shadowRoot.querySelector("[data-confirm-error]");
      if (error) error.textContent = "";
    }
  }

  _closeConfirmation() {
    this._focusAfterRenderEntityId = this._pendingAction?.entityId;
    this._pendingAction = undefined;
    this._render();
  }

  _prepareAction(entityId) {
    const meta = this._entityMetadata(entityId);
    const state = this._state(meta);
    if (!meta?.control || this._isControlUnavailable(meta, state)) {
      this._notice =
        meta?.domain === "update" && state?.state !== "on"
          ? this._t("notice.firmware_current")
          : this._t("notice.control_unavailable");
      this._noticeKind = "status";
      this._render();
      return;
    }

    const label = this._friendlyName(meta, state);
    let actionLabel = this._t("action.run_action");
    let message = this._t("confirm.default");
    let kind = "action";
    let value;
    let constraints;
    let options;
    let observedState;
    if (isSupportedTextControl(meta)) {
      kind = "text";
      value = typeof state.state === "string" ? state.state : "";
      observedState = state.state;
      constraints = textControlConstraints(state);
      actionLabel = this._t("action.save_name");
      message = this._t("confirm.text");
    } else if (isSupportedSelectControl(meta, state)) {
      kind = "select";
      value = state.state;
      observedState = state.state;
      options = [...selectControlOptions(meta, state)];
      actionLabel = this._t("action.apply_setting");
      message = this._t(
        meta.risk === "sensitive"
          ? "confirm.sensitive_select"
          : meta.disruptive
            ? "confirm.disruptive_select"
            : "confirm.select",
        { label },
      );
    } else if (
      meta.domain === "button" &&
      meta.translation_key === "retry_protected_data"
    ) {
      actionLabel = this._t("action.retry_protected");
      message = this._t("confirm.retry");
    } else if (meta.domain === "switch") {
      observedState = state.state;
      actionLabel = this._t(
        state.state === "on" ? "action.turn_off" : "action.turn_on",
      );
      message = this._t(
        meta.risk === "lockout"
          ? "confirm.lockout_switch"
          : meta.risk === "sensitive"
            ? "confirm.sensitive_switch"
          : meta.disruptive
            ? "confirm.disruptive_switch"
            : "confirm.switch",
        { label },
      );
    } else if (meta.domain === "update") {
      actionLabel = this._t("action.install_update");
      message = this._t("confirm.update");
    } else if (meta.disruptive) {
      message = this._t("confirm.disruptive");
    } else if (meta.risk === "sensitive") {
      message = this._t("confirm.sensitive");
    }

    const confirmationPhrase = controlConfirmationPhrase(meta, observedState);
    if (meta.confirmation === "typed" && !confirmationPhrase) {
      this._notice = this._t("notice.control_unavailable");
      this._noticeKind = "status";
      this._render();
      return;
    }

    this._pendingAction = {
      entityId,
      label,
      actionLabel,
      message,
      disruptive: Boolean(meta.disruptive || meta.domain === "update"),
      kind,
      value,
      constraints,
      options,
      observedState,
      confirmationPhrase,
      confirmationDraft: "",
      confirmationPolicy: meta.confirmation,
      risk: meta.risk,
      confirmationError: false,
      errorKey: undefined,
    };
    if (["select", "text"].includes(kind) && this._renderFrame) {
      window.cancelAnimationFrame(this._renderFrame);
      this._renderFrame = undefined;
    }
    this._notice = "";
    this._noticeKind = "status";
    this._render();
  }

  async _runPendingAction() {
    if (!this._pendingAction || this._actionBusy || !this._hass) return;
    const pending = this._pendingAction;
    const meta = this._entityMetadata(pending.entityId);
    const state = this._state(meta);
    if (!meta?.control || this._isControlUnavailable(meta, state)) {
      this._pendingAction = undefined;
      this._focusAfterRenderEntityId = pending.entityId;
      this._notice = this._t("notice.control_changed");
      this._noticeKind = "status";
      this._render();
      return;
    }

    if (
      !controlConfirmationPolicyMatches(
        meta,
        state.state,
        pending.confirmationPolicy,
        pending.risk,
        pending.confirmationPhrase,
      )
    ) {
      this._pendingAction = undefined;
      this._focusAfterRenderEntityId = pending.entityId;
      this._notice = this._t("notice.control_changed");
      this._noticeKind = "status";
      this._render();
      return;
    }

    if (
      pending.confirmationPhrase &&
      !typedConfirmationMatches(
        pending.confirmationPhrase,
        pending.confirmationDraft,
      )
    ) {
      pending.confirmationError = true;
      this._render();
      return;
    }

    let serviceCall;
    if (pending.kind === "text") {
      const constraints = textControlConstraints(state);
      const errorKey = validateTextControlValue(pending.value, constraints);
      if (errorKey) {
        pending.constraints = constraints;
        pending.errorKey = errorKey;
        this._render();
        return;
      }
      serviceCall = textControlServiceCall(
        meta,
        pending.value,
        pending.observedState,
        state.state,
      );
      if (!serviceCall) {
        this._pendingAction = undefined;
        this._focusAfterRenderEntityId = pending.entityId;
        this._notice = this._t("notice.control_changed");
        this._noticeKind = "status";
        this._render();
        return;
      }
    } else if (pending.kind === "select") {
      serviceCall = selectControlServiceCall(
        meta,
        pending.value,
        pending.observedState,
        state,
      );
      if (!serviceCall) {
        this._pendingAction = undefined;
        this._focusAfterRenderEntityId = pending.entityId;
        this._notice = this._t("notice.control_changed");
        this._noticeKind = "status";
        this._render();
        return;
      }
    } else if (meta.domain === "switch") {
      serviceCall = switchControlServiceCall(
        meta,
        pending.observedState,
        state.state,
      );
      if (!serviceCall) {
        this._pendingAction = undefined;
        this._focusAfterRenderEntityId = pending.entityId;
        this._notice = this._t("notice.control_changed");
        this._noticeKind = "status";
        this._render();
        return;
      }
    }

    this._actionBusy = true;
    this._render();
    try {
      if (serviceCall) {
        await this._hass.callService(
          serviceCall.domain,
          serviceCall.service,
          serviceCall.data,
        );
      } else if (meta.domain === "button") {
        await this._hass.callService("button", "press", {
          entity_id: meta.entity_id,
        });
      } else if (meta.domain === "update") {
        await this._hass.callService("update", "install", {
          entity_id: meta.entity_id,
        });
      } else {
        throw new Error(this._t("error.unsupported_control"));
      }
      this._notice = this._t("notice.action_success", {
        action: pending.actionLabel,
      });
      this._noticeKind = "status";
      this._pendingAction = undefined;
      this._focusAfterRenderEntityId = pending.entityId;
    } catch (_error) {
      this._notice = this._t("error.action_failed");
      this._noticeKind = "alert";
      this._pendingAction = undefined;
      this._focusAfterRenderEntityId = pending.entityId;
    } finally {
      this._actionBusy = false;
      this._render();
    }
  }

  _wanTelemetryDetails(source) {
    const presentation = wanTelemetryPresentation(
      undefined,
      undefined,
      source,
    );
    const details = [];
    if (presentation.mode) {
      details.push(this._t(`status.polling_mode_${presentation.mode}`));
    }
    if (
      presentation.schedulerState &&
      presentation.schedulerState !== "retrying"
    ) {
      details.push(
        this._t(`status.polling_state_${presentation.schedulerState}`),
      );
    }
    if (presentation.effectiveIntervalSeconds !== undefined) {
      const duration = formatPanelDurationSeconds(
        presentation.effectiveIntervalSeconds,
        this._locale(),
        this._language(),
      );
      if (duration !== undefined) {
        details.push(this._t("status.sample_interval", { duration }));
      }
    }
    if (presentation.fastestProvenIntervalSeconds !== undefined) {
      const duration = formatPanelDurationSeconds(
        presentation.fastestProvenIntervalSeconds,
        this._locale(),
        this._language(),
      );
      if (duration !== undefined) {
        details.push(this._t("status.fastest_proven", { duration }));
      }
    }
    if (presentation.retryInSeconds !== undefined) {
      const duration = formatPanelDurationSeconds(
        presentation.retryInSeconds,
        this._locale(),
        this._language(),
      );
      if (duration !== undefined) {
        details.push(this._t("status.retry_in", { duration }));
      }
    }
    if (presentation.sampleAgeSeconds !== undefined) {
      const duration = formatPanelDurationSeconds(
        presentation.sampleAgeSeconds,
        this._locale(),
        this._language(),
      );
      if (duration !== undefined) {
        details.push(
          this._t(
            presentation.degraded
              ? "status.last_confirmed_ago"
              : "status.last_sample_ago",
            { duration },
          ),
        );
      }
    }
    return details.join(" · ");
  }

  _renderSource(source) {
    const unsupported = source.supported === false;
    const telemetry = wanTelemetryPresentation(undefined, undefined, source);
    const retrying = !unsupported && telemetry.retrying;
    const status = unsupported
      ? "unsupported"
      : retrying
        ? "retrying"
        : source.available
          ? "available"
          : "unavailable";
    const statusLabel = unsupported
      ? this._t("status.not_detected")
      : retrying
        ? this._t("status.telemetry_retrying")
        : source.available
          ? this._t("status.ready_now")
          : this._t("status.temporarily_unavailable");
    const sourceInfo =
      ACCESS_SOURCE_INFO[source.id] || ACCESS_SOURCE_INFO.protected_json;
    const details =
      source.id === "wan_counters" ? this._wanTelemetryDetails(source) : "";
    return `
      <div class="source ${status}">
        <span class="source-dot" aria-hidden="true"></span>
        <span>${escapeHtml(this._t(sourceInfo.titleKey))}</span>
        <strong>${escapeHtml(statusLabel)}</strong>
        ${details ? `<small class="source-detail">${escapeHtml(details)}</small>` : ""}
      </div>
    `;
  }

  _renderManagement(router) {
    const managementMeta = router.entities.find(
      (entity) => entity.translation_key === "management_access",
    );
    const managementState = this._state(managementMeta);
    if (!managementMeta && !router.management) return "";
    const state =
      managementState?.state || router.management?.state || "unavailable";
    const attributes = managementState?.attributes || {};
    const logoutRequired =
      attributes.browser_logout_required ??
      router.management?.browser_logout_required ??
      false;
    const owner = attributes.owner_ip_address;
    const stateLabel = this._managementStateLabel(state);

    if (logoutRequired || ["blocked", "other_session"].includes(state)) {
      return `
        <aside class="management-alert warning">
          <ha-icon icon="mdi:account-lock" aria-hidden="true"></ha-icon>
          <div>
            <strong>${escapeHtml(this._t("management.browser.title"))}</strong>
            <p>
              ${escapeHtml(this._t("management.browser.body"))}
              ${owner ? escapeHtml(this._t("management.browser.owner", { owner })) : ""}
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
          <ha-icon icon="mdi:timer-lock-outline" aria-hidden="true"></ha-icon>
          <div>
            <strong>${escapeHtml(this._t("management.locked.title"))}</strong>
            <p>
              ${escapeHtml(this._t("management.locked.body"))}
              ${
                retryAfter != null
                  ? escapeHtml(
                      this._t("management.locked.remaining", {
                        duration:
                          formatPanelDurationSeconds(
                            retryAfter,
                            this._locale(),
                            this._language(),
                          ) ||
                          `${retryAfter} ${this._t("duration.second")}`,
                      }),
                    )
                  : ""
              }
            </p>
          </div>
          <span class="state-pill">${escapeHtml(stateLabel)}</span>
        </aside>
      `;
    }
    const healthy = state === "available";
    return `
      <aside class="management-alert ${healthy ? "good" : "caution"}">
        <ha-icon icon="${healthy ? "mdi:shield-check-outline" : "mdi:shield-alert-outline"}" aria-hidden="true"></ha-icon>
        <div>
          <strong>${escapeHtml(this._t("management.access.title", { state: stateLabel }))}</strong>
          <p>${escapeHtml(this._t("management.access.body"))}</p>
        </div>
        <span class="state-pill">${escapeHtml(stateLabel)}</span>
      </aside>
    `;
  }

  _childEntityName(meta, state) {
    if (meta.domain === "device_tracker") return this._t("label.presence");
    const friendlyName = this._friendlyName(meta, state);
    const deviceName = meta.child_device?.name;
    if (!deviceName) return friendlyName;
    if (friendlyName === deviceName) {
      return this._translatedEntityName(meta);
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

    const groupTitle = this._t(
      capabilityGroupInfo(groupId, meta.section).titleKey,
    );
    if (label.toLowerCase() === groupTitle.toLowerCase()) {
      return this._t("label.status");
    }
    if (label.toLowerCase().startsWith(`${groupTitle.toLowerCase()} `)) {
      return label.slice(groupTitle.length + 1);
    }

    const semanticPrefixes = {
      connection: [this._capabilityName("internet")],
      bandwidth: ["WAN"],
      dsl: ["DSL"],
      mobile: [this._capabilityName("mobile")],
      system: [this._capabilityName("system")],
    };
    for (const prefix of semanticPrefixes[meta.section] || []) {
      if (label.toLowerCase() === prefix.toLowerCase()) {
        return this._t("label.status");
      }
      if (label.toLowerCase().startsWith(`${prefix.toLowerCase()} `)) {
        return label.slice(prefix.length + 1);
      }
    }
    return label;
  }

  _renderEntity(
    meta,
    {
      capabilityGroup = undefined,
      child = false,
      hero = false,
      sourceState = undefined,
    } = {},
  ) {
    const state = this._state(meta);
    const stateClass = entityAvailability(meta, state);
    const unavailable = stateClass !== "available";
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
        ? this._t("status.ready")
        : this._formatState(state);
    const icon = iconFor(meta, state);
    const sourceInfo =
      ACCESS_SOURCE_INFO[meta.access_source] || ACCESS_SOURCE_INFO.protected_json;
    const wanPresentation = wanTelemetryPresentation(meta, state, sourceState);
    const wanDetails =
      meta.access_source === "wan_counters"
        ? this._wanTelemetryDetails(sourceState)
        : "";

    if (hero) {
      const rateStatusKey =
        wanPresentation.rateStatusKey ||
        (unavailable ? "status.waiting_sample" : "status.recent_rate");
      return `
        <button class="hero-metric ${stateClass}" data-more-info="${escapeHtml(meta.entity_id)}">
          <div class="hero-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(icon)}"></ha-icon></div>
          <div>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(displayState)}</strong>
            <small>${escapeHtml(this._t(sourceInfo.shortKey))} · ${escapeHtml(this._t(rateStatusKey))}</small>
          </div>
        </button>
      `;
    }

    const actionLabel =
      meta.domain === "button" &&
      meta.translation_key === "retry_protected_data"
        ? this._t("action.retry")
        : isSupportedTextControl(meta)
          ? this._t("action.edit")
        : meta.domain === "select"
          ? this._t("action.change_setting")
        : meta.domain === "switch"
          ? state?.state === "on"
            ? this._t("action.turn_off")
            : this._t("action.turn_on")
          : meta.domain === "update"
            ? this._t("action.install")
            : this._t("action.run");
    const control = meta.control
      ? `
        <button
          class="entity-action ${meta.disruptive ? "disruptive" : ""}"
          data-control="${escapeHtml(meta.entity_id)}"
          aria-label="${escapeHtml(this._t("action.for_entity", { action: actionLabel, entity: label }))}"
          ${controlUnavailable ? "disabled" : ""}
        >
          ${escapeHtml(actionLabel)}
        </button>
      `
      : "";

    const sourceBadge = wanPresentation.lastConfirmed
      ? wanDetails || this._t("status.last_confirmed")
      : this._t(sourceInfo.shortKey);
    const availabilityTitle = wanPresentation.lastConfirmed
      ? sourceBadge
      : this._t(
          stateClass === "available"
            ? "status.available"
            : stateClass === "unknown"
              ? "status.unknown"
              : "status.unavailable",
        );

    return `
      <article class="entity-card ${child ? "child-entity-card" : ""} ${stateClass} ${wanPresentation.lastConfirmed ? "last-confirmed" : ""} ${meta.control ? "control-card" : ""}">
        <button class="entity-main" data-more-info="${escapeHtml(meta.entity_id)}">
          <span class="entity-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(icon)}"></ha-icon></span>
          <span class="entity-copy">
            <span class="entity-name">${escapeHtml(label)}</span>
            <strong class="entity-state">${escapeHtml(displayState)}</strong>
            <span class="source-badge" title="${escapeHtml(this._t(sourceInfo.descriptionKey))}">
              ${escapeHtml(sourceBadge)}
            </span>
          </span>
          <span class="availability-dot" aria-hidden="true" title="${escapeHtml(availabilityTitle)}"></span>
        </button>
        ${control}
      </article>
    `;
  }

  _renderChildDevice(entities) {
    const child = entities[0]?.child_device;
    if (!child) return "";
    const kindInfo = CHILD_KIND_INFO[child.kind] || {
      labelKey: undefined,
      icon: "mdi:devices",
    };
    const kindLabel = kindInfo.labelKey
      ? this._t(kindInfo.labelKey)
      : humanize(child.kind);
    const details = child.model
      ? `${kindLabel} · ${child.model}`
      : kindLabel;
    const stateClass = aggregateAvailability(
      entities.map((entity) => entityAvailability(entity, this._state(entity))),
    );
    return `
      <section class="child-device-card ${stateClass}" data-child-device="${escapeHtml(child.device_id)}">
        <header class="child-device-heading">
          <span class="child-device-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(kindInfo.icon)}"></ha-icon></span>
          <span class="child-device-copy">
            <strong>${escapeHtml(child.name)}</strong>
            <small>${escapeHtml(details)}</small>
          </span>
          <span class="child-device-count" title="${escapeHtml(this._t(entities.length === 1 ? "count.entity" : "count.entities", { count: entities.length }))}">${entities.length}</span>
        </header>
        <div class="child-device-entities">
          ${entities.map((entity) => this._renderEntity(entity, { child: true })).join("")}
        </div>
      </section>
    `;
  }

  _renderCapabilityGroup(sectionId, sourceId, groupId, entities, sourceState) {
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
            this._renderEntity(entity, {
              capabilityGroup: groupId,
              sourceState,
            }),
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
    const countLabel = this._t(
      entities.length === 1 ? "count.entity" : "count.entities",
      { count: entities.length },
    );
    return `
      <section class="entity-capability-block ${childGroups.size ? "device-capability-block" : ""}" aria-labelledby="${escapeHtml(headingId)}">
        <header class="entity-capability-heading">
          <span class="entity-capability-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(info.icon)}"></ha-icon></span>
          <h3 id="${escapeHtml(headingId)}">${escapeHtml(this._t(info.titleKey))}</h3>
          <span class="entity-capability-count" aria-label="${escapeHtml(countLabel)}">${entities.length}</span>
        </header>
        ${rootGrid}
        ${childGrid}
      </section>
    `;
  }

  _renderSection(sectionId, entities, router, liveSourceStates = undefined) {
    const info = SECTION_INFO[sectionId];
    if (!info || entities.length === 0) return "";
    const sourceStates =
      liveSourceStates ||
      Object.fromEntries(
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
        const sourceRetrying =
          sourceId === "wan_counters" && sourceState?.retrying === true;
        const statusClass = sourceState
          ? sourceState.supported === false
            ? "unsupported"
            : sourceRetrying
              ? "retrying"
              : sourceState.available
                ? "available"
                : "unavailable"
          : "local";
        const statusText = sourceState
          ? sourceState.supported === false
            ? this._t("status.not_detected")
            : sourceRetrying
              ? this._t("status.telemetry_retrying")
              : sourceState.available
                ? this._t("status.available_now")
                : this._t("status.temporarily_unavailable")
          : sourceId === "router_control"
            ? this._t("status.confirmation_only")
            : this._t("status.available_locally");
        const sourceDetails =
          sourceId === "wan_counters"
            ? this._wanTelemetryDetails(sourceState)
            : "";
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
              this._t(
                capabilityGroupInfo(left, sectionId).titleKey,
              ).localeCompare(
                this._t(capabilityGroupInfo(right, sectionId).titleKey),
                this._locale(),
              ),
          )
          .map(([groupId, groupEntities]) =>
            this._renderCapabilityGroup(
              sectionId,
              sourceId,
              groupId,
              groupEntities,
              sourceState,
            ),
          )
          .join("");
        const capabilityGrid = capabilityBlocks
          ? `<div class="entity-capability-grid">${capabilityBlocks}</div>`
          : "";
        const sourceGroupClass =
          capabilityGroups.size >= 3
            ? "entity-source-group source-group-wide"
            : "entity-source-group";
        return `
          <div class="${sourceGroupClass}">
            <header class="entity-source-heading ${statusClass}">
              <span class="entity-source-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(sourceInfo.icon)}"></ha-icon></span>
              <div>
                <strong>${escapeHtml(this._t(sourceInfo.titleKey))}</strong>
                <p>${escapeHtml(this._t(sourceInfo.descriptionKey))}</p>
                ${sourceDetails ? `<small class="entity-source-detail">${escapeHtml(sourceDetails)}</small>` : ""}
              </div>
              <span class="entity-source-status"><i aria-hidden="true"></i>${escapeHtml(statusText)}</span>
            </header>
            ${capabilityGrid}
          </div>
        `;
      })
      .join("");
    return `
      <section class="dashboard-section section-${escapeHtml(sectionId)}">
        <header class="section-heading">
          <span class="section-icon" aria-hidden="true"><ha-icon icon="${info.icon}"></ha-icon></span>
          <div>
            <h2>${escapeHtml(this._t(info.titleKey))}</h2>
            <p>${escapeHtml(this._t(info.subtitleKey))}</p>
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
      public_status: "capabilities.public_status",
      public_json: "capabilities.public_json",
      protected_json: "capabilities.protected_json",
    };
    const groups = Object.entries(bySource)
      .map(
        ([source, names]) => `
          <div class="capability-group">
            <strong>${escapeHtml(sourceNames[source] ? this._t(sourceNames[source]) : humanize(source))}</strong>
            <div class="capability-chips">
              ${names
                .map((name) => `<span>${escapeHtml(this._capabilityName(name))}</span>`)
                .join("")}
            </div>
          </div>
        `,
      )
      .join("");
    return `
      <details class="capability-details">
        <summary>
          <span>${escapeHtml(this._t("capabilities.title"))}</span>
          <small>${escapeHtml(this._t("capabilities.active_signals", { count: router.capabilities?.length || 0 }))}</small>
        </summary>
        <div class="capability-content">
          ${groups || `<p>${escapeHtml(this._t("capabilities.empty"))}</p>`}
        </div>
      </details>
    `;
  }

  _renderConfirmation() {
    const pending = this._pendingAction;
    if (!pending) return "";
    const riskClass = pending.disruptive
      ? "danger"
      : pending.risk === "sensitive"
        ? "caution"
        : "";
    const riskIcon = pending.disruptive
      ? "mdi:alert-outline"
      : pending.risk === "sensitive"
        ? "mdi:shield-alert-outline"
        : "mdi:shield-check-outline";
    const textEditor = pending.kind === "text";
    const selectEditor = pending.kind === "select";
    const constraints = pending.constraints || {};
    const textError = pending.errorKey ? this._t(pending.errorKey) : "";
    const describedByIds = ["speedport-confirm-description"];
    if (textEditor) describedByIds.push("speedport-text-error");
    if (pending.confirmationPhrase) {
      describedByIds.push("speedport-confirm-phrase", "speedport-confirm-error");
    }
    const describedBy = describedByIds.join(" ");
    let editor = "";
    if (textEditor) {
      editor = `
          <label class="confirm-field" for="speedport-text-value">
            <span>${escapeHtml(this._t("label.new_device_name"))}</span>
            <input
              id="speedport-text-value"
              data-text-draft
              type="text"
              value="${escapeHtml(pending.value)}"
              ${constraints.min !== undefined ? `minlength="${constraints.min}"` : ""}
              ${constraints.max !== undefined ? `maxlength="${constraints.max}"` : ""}
              ${pending.errorKey ? 'aria-invalid="true"' : ""}
              aria-describedby="speedport-text-error"
              autocomplete="off"
              spellcheck="false"
              ${this._actionBusy ? "disabled" : ""}
            >
          </label>
          <p id="speedport-text-error" class="confirm-error" data-text-error role="alert">${escapeHtml(textError)}</p>
        `;
    } else if (selectEditor) {
      const meta = this._entityMetadata(pending.entityId);
      const selectOptions = (pending.options || [])
        .map(
          (option) => `
            <option value="${escapeHtml(option)}" ${option === pending.value ? "selected" : ""}>
              ${escapeHtml(this._translatedSelectOption(meta, option))}
            </option>
          `,
        )
        .join("");
      editor = `
        <label class="confirm-field" for="speedport-select-value">
          <span>${escapeHtml(this._t("label.setting_value"))}</span>
          <select
            id="speedport-select-value"
            data-select-draft
            aria-describedby="speedport-confirm-description"
            ${this._actionBusy ? "disabled" : ""}
          >
            ${selectOptions}
          </select>
        </label>
      `;
    }
    const confirmationMatches = typedConfirmationMatches(
      pending.confirmationPhrase,
      pending.confirmationDraft,
    );
    const confirmationEditor = pending.confirmationPhrase
      ? `
        <p id="speedport-confirm-phrase">${escapeHtml(
          this._t("confirm.type_phrase", {
            phrase: pending.confirmationPhrase,
          }),
        )}</p>
        <label class="confirm-field" for="speedport-confirm-value">
          <span>${escapeHtml(this._t("label.confirmation_phrase"))}</span>
          <input
            id="speedport-confirm-value"
            data-confirm-draft
            type="text"
            value="${escapeHtml(pending.confirmationDraft)}"
            ${pending.confirmationError ? 'aria-invalid="true"' : ""}
            aria-describedby="speedport-confirm-phrase speedport-confirm-error"
            autocomplete="off"
            autocapitalize="characters"
            spellcheck="false"
            ${this._actionBusy ? "disabled" : ""}
          >
        </label>
        <p id="speedport-confirm-error" class="confirm-error" data-confirm-error role="alert">${
          pending.confirmationError
            ? escapeHtml(this._t("error.confirmation_phrase"))
            : ""
        }</p>
      `
      : "";
    return `
      <div class="modal-backdrop" role="presentation">
        <section
          class="confirm-dialog ${riskClass}"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="speedport-confirm-title"
          aria-describedby="${describedBy}"
          aria-busy="${this._actionBusy ? "true" : "false"}"
          tabindex="-1"
        >
          <span class="confirm-icon" aria-hidden="true">
            <ha-icon icon="${riskIcon}"></ha-icon>
          </span>
          <h2 id="speedport-confirm-title">${escapeHtml(pending.label)}</h2>
          <p id="speedport-confirm-description">${escapeHtml(pending.message)}</p>
          ${editor}
          ${confirmationEditor}
          <div class="confirm-actions">
            <button class="secondary" data-cancel-action ${this._actionBusy ? "disabled" : ""}>
              ${escapeHtml(this._t("action.cancel"))}
            </button>
            <button class="primary" data-confirm-action ${
              this._actionBusy ||
              (pending.confirmationPhrase && !confirmationMatches)
                ? "disabled"
                : ""
            }>
              ${this._actionBusy ? escapeHtml(this._t("action.working")) : escapeHtml(pending.actionLabel)}
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
          <div class="brand-mark" aria-hidden="true"><span></span><span></span><span></span></div>
          <h1>Telekom Speedport Smart</h1>
          <p>${escapeHtml(this._t("empty.description"))}</p>
          <button class="primary" data-refresh>${escapeHtml(this._t("action.refresh"))}</button>
        </section>
      </main>
    `;
  }

  _render() {
    if (!this.shadowRoot) return;
    const renderState = captureRenderState(this.shadowRoot);
    const routers = this._metadata?.routers || [];
    const router = this._currentRouter();
    if (!this._hass || this._loading && !this._metadata) {
      this.shadowRoot.innerHTML = `${this._styles()}
        <main class="shell loading-shell" role="status" aria-live="polite">
          <div class="loading-mark" aria-hidden="true"><span></span><span></span><span></span></div>
          <p>${escapeHtml(this._t("loading.dashboard"))}</p>
        </main>`;
      return;
    }
    if (this._loadError && !this._metadata) {
      this.shadowRoot.innerHTML = `${this._styles()}
        <main class="shell empty-shell">
          <section class="empty-card error-card" role="alert">
            <ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>
            <h1>${escapeHtml(this._t("error.dashboard_unavailable"))}</h1>
            <p>${escapeHtml(this._t(this._loadError))}</p>
            <button class="primary" data-refresh>${escapeHtml(this._t("action.try_again"))}</button>
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
    const accessSourceStates = Object.fromEntries(
      (router.access_sources || []).map((source) => [source.id, source]),
    );
    if (accessSourceStates.wan_counters) {
      accessSourceStates.wan_counters = liveWanSourceFromEntityStates(
        accessSourceStates.wan_counters,
        router.entities,
        this._hass?.states,
      );
    }
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
    const connectionPresentation = internetConnectionPresentation(internetState);
    const connectionLabel = this._t(connectionPresentation.labelKey);

    const routerTabs =
      routers.length > 1
        ? `
          <nav class="router-tabs" aria-label="${escapeHtml(this._t("router_tabs.label"))}">
            ${routers
              .map(
                (item) => `
                  <button
                    data-router="${escapeHtml(item.entry_id)}"
                    class="${item.entry_id === router.entry_id ? "active" : ""}"
                    ${item.entry_id === router.entry_id ? 'aria-current="page"' : ""}
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
      this._renderSection(
        section,
        sectionEntities[section] || [],
        router,
        accessSourceStates,
      ),
    ).join("");
    const notice = this._notice
      ? `<div class="notice" role="${this._noticeKind}" aria-live="${this._noticeKind === "alert" ? "assertive" : "polite"}"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._notice)}</div>`
      : "";

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <main class="shell" ${this._pendingAction ? 'inert aria-hidden="true"' : ""}>
        <header class="hero">
          <div class="hero-copy">
            <div class="eyebrow">
              <span class="telekom-dots" aria-hidden="true"><i></i><i></i><i></i></span>
              ${escapeHtml(this._t("hero.eyebrow"))}
            </div>
            <h1>${escapeHtml(router.title)}</h1>
            ${router.model ? `<p>${escapeHtml(router.model)}</p>` : ""}
            <div class="hero-status">
              <span class="online-dot ${connectionPresentation.className}" aria-hidden="true"></span>
              ${escapeHtml(connectionLabel)}
              <span class="divider" aria-hidden="true"></span>
              <span class="integration-status">${escapeHtml(this._t("hero.integration", { state: this._entryStateLabel(router.entry_state) }))}</span>
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
              <span class="kicker">${escapeHtml(this._t("access.kicker"))}</span>
              <h2>${escapeHtml(this._t("access.title"))}</h2>
            </div>
            <button class="icon-button" data-refresh title="${escapeHtml(this._t("action.refresh_metadata"))}" aria-label="${escapeHtml(this._t("action.refresh_metadata"))}">
              <ha-icon icon="mdi:refresh" aria-hidden="true"></ha-icon>
            </button>
          </header>
          <div class="source-grid">
            ${(router.access_sources || [])
              .map((source) =>
                this._renderSource(accessSourceStates[source.id] || source),
              )
              .join("")}
          </div>
          ${this._renderCapabilities(router)}
        </section>

        ${
          heroEntities.length
            ? `<section class="hero-metrics">${heroEntities
                .map((entity) =>
                  this._renderEntity(entity, {
                    hero: true,
                    sourceState: accessSourceStates[entity.access_source],
                  }),
                )
                .join("")}</section>`
            : ""
        }

        <div class="sections">${sections}</div>

        <footer>
          <span>Telekom Speedport Smart</span>
          <span>${escapeHtml(this._t("footer.local"))}</span>
        </footer>
      </main>
      ${this._renderConfirmation()}
    `;
    restoreDetailsState(this.shadowRoot, renderState);
    if (this._pendingAction) {
      window.requestAnimationFrame(() => {
        const dialog = this.shadowRoot.querySelector(".confirm-dialog");
        const editor = this.shadowRoot.querySelector(
          "[data-text-draft]:not([disabled]), [data-select-draft]:not([disabled]), [data-confirm-draft]:not([disabled])",
        );
        const cancel = this.shadowRoot.querySelector(
          "[data-cancel-action]:not([disabled])",
        );
        (editor || cancel || dialog)?.focus();
      });
    } else if (this._focusAfterRenderEntityId) {
      const entityId = this._focusAfterRenderEntityId;
      this._focusAfterRenderEntityId = undefined;
      window.requestAnimationFrame(() => {
        restoreFocusState(this.shadowRoot, {
          focus: { kind: "data", key: "control", value: entityId },
        });
      });
    } else if (renderState.focus) {
      window.requestAnimationFrame(() => {
        restoreFocusState(this.shadowRoot, renderState);
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
        .online-dot.unavailable { background: var(--sp-muted); }
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
          min-height: 44px;
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
          width: 44px;
          height: 44px;
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
        .source-detail {
          grid-column: 2;
          color: var(--sp-muted);
          font-size: 10px;
          line-height: 1.35;
        }
        .source.available .source-dot { background: var(--sp-success); box-shadow: none; }
        .source.unavailable .source-dot { box-shadow: none; }
        .source.retrying {
          border: 1px solid color-mix(in srgb, var(--sp-warning) 35%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-warning) 8%, var(--sp-surface-soft));
        }
        .source.retrying .source-dot { background: var(--sp-warning); box-shadow: none; }
        .source.unsupported .source-dot { background: var(--sp-muted); box-shadow: none; opacity: .55; }
        .source.unsupported { opacity: .7; }
        .capability-details {
          margin-top: 14px;
          border-top: 1px solid var(--sp-border);
        }
        .capability-details summary {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          min-height: 44px;
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
          width: 100%;
          padding: clamp(20px, 3vw, 30px);
          overflow: hidden;
          border: 1px solid var(--sp-border);
          border-radius: 22px;
          background:
            linear-gradient(135deg, color-mix(in srgb, var(--sp-magenta) 11%, transparent), transparent 58%),
            var(--sp-surface);
          box-shadow: 0 12px 34px rgba(0,0,0,.055);
          color: inherit;
          text-align: left;
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
        .sections { display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; }
        .dashboard-section { grid-column: 1 / -1; min-width: 0; width: 100%; }
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
        .entity-source-groups {
          display: flex;
          flex-wrap: wrap;
          align-items: start;
          gap: 20px;
        }
        .entity-source-group {
          flex: 1 1 min(100%, 400px);
          min-width: 0;
        }
        .entity-source-group.source-group-wide { flex-basis: 100%; }
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
        .entity-source-heading.retrying {
          background: color-mix(in srgb, var(--sp-warning) 12%, var(--sp-surface-soft));
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
        .entity-source-heading.retrying .entity-source-status i { background: var(--sp-warning); }
        .entity-source-heading.unsupported .entity-source-status i { background: var(--sp-muted); }
        .entity-source-detail {
          display: block;
          margin-top: 4px;
          color: var(--sp-muted);
          font-size: 10px;
          line-height: 1.35;
        }
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
        .child-device-card.unknown { opacity: .82; }
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
        .entity-card.unknown { opacity: .78; }
        .entity-card.last-confirmed {
          border-color: color-mix(in srgb, var(--sp-warning) 45%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-warning) 8%, var(--sp-surface-soft));
        }
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
        .entity-card.available > .entity-main .availability-dot {
          background: var(--sp-success);
        }
        .entity-card.last-confirmed > .entity-main .availability-dot {
          background: var(--sp-warning);
        }
        .entity-card.last-confirmed .source-badge { color: var(--sp-warning); }
        .entity-card.unknown > .entity-main .availability-dot {
          background: var(--sp-muted);
        }
        .entity-action {
          width: calc(100% - 24px);
          min-height: 44px;
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
        button:focus-visible, summary:focus-visible, input:focus-visible, select:focus-visible {
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
          min-height: 44px;
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
        .confirm-dialog.caution .confirm-icon { color: var(--sp-warning); background: color-mix(in srgb, var(--sp-warning) 10%, var(--sp-surface)); }
        .confirm-dialog.danger .confirm-icon { color: var(--sp-error); background: color-mix(in srgb, var(--sp-error) 10%, var(--sp-surface)); }
        .confirm-dialog h2 { margin: 18px 0 8px; }
        .confirm-dialog p { color: var(--sp-muted); line-height: 1.55; }
        .confirm-field {
          display: grid;
          gap: 7px;
          margin-top: 18px;
          color: var(--sp-muted);
          font-size: 12px;
          font-weight: 700;
        }
        .confirm-field input,
        .confirm-field select {
          width: 100%;
          min-height: 46px;
          padding: 10px 12px;
          color: var(--sp-text);
          border: 1px solid var(--sp-border);
          border-radius: 11px;
          background: var(--sp-surface-soft);
          font: inherit;
        }
        .confirm-field select { appearance: auto; }
        .confirm-field input[aria-invalid="true"] {
          border-color: var(--sp-error);
        }
        .confirm-error {
          min-height: 20px;
          margin: 6px 0 0;
          color: var(--sp-error) !important;
          font-size: 12px;
        }
        .confirm-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }
        :host([narrow]) .sections { grid-template-columns: 1fr; }
        :host([narrow]) .dashboard-section { grid-column: auto; }
        :host([narrow]) .entity-source-group { flex-basis: 100%; }
        :host([narrow]) .entity-capability-grid { grid-template-columns: 1fr; }
        @media (max-width: 900px) {
          .sections { grid-template-columns: 1fr; }
          .dashboard-section { grid-column: auto; }
          .entity-source-group { flex-basis: 100%; }
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
