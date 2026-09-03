import { requestPrivateApi } from "./private-api.js?schema=31";
import { renderDashboardOverview, DASHBOARD_OVERVIEW_STYLES } from "./dashboard-overview.js?schema=31";
import { createTrafficHistoryController, renderTrafficHistory, bindTrafficHistory, refreshTrafficHistoryContent, TRAFFIC_HISTORY_STYLES, LIVE_TRAFFIC_CLOCK_SKEW_MS } from "./traffic-history.js?schema=31";
import {
  NATIVE_ADMIN_TABS, resolveAdminPage, adminPageSettings, adminPageFeatures, adminPageSettingSections,
} from "./admin-navigation.js?schema=31";
import { keepDialogFocus } from "./accessibility.js?schema=31";
import {
  createCallHistoryViewController, renderCallHistoryView, bindCallHistoryView,
} from "./call-history-view.js?schema=31";
import {
  createFileTransferEditorController, renderFileTransferEditor, bindFileTransferEditor,
} from "./file-transfer-editor.js?schema=31";
import {
  createMaintenanceEditorController, renderMaintenanceEditor, bindMaintenanceEditor,
} from "./maintenance-editor.js?schema=31";
import {
  createConfigurationEditorController,
  renderConfigurationEditor,
  bindConfigurationEditor,
} from "./configuration-editor.js?schema=31";
import {
  controlConfirmationPhrase,
  controlConfirmationPolicyMatches,
  controlUnavailableReason,
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
} from "./controls.js?schema=31";
import {
  aggregateAvailability,
  entityDisplayName,
  entityAvailability,
} from "./entity-state.js?schema=31";
import {
  captureRenderState,
  restoreDetailsState,
  restoreFocusState,
} from "./render-state.js?schema=31";
import {
  formatPanelDurationSeconds,
  panelTranslate,
  resolvePanelLanguage,
} from "./translations.js?schema=31";

const API_TYPE = "speedport_smart/panel";
const ADMIN_READ_API_TYPE = `${API_TYPE}/admin_read`;
const ADMIN_READ_SCHEMA_VERSION = 2;
const ADMIN_PRIVATE_QUERY_SCHEMA_VERSION = 1;
const ADMIN_PRIVATE_QUERY_API_TYPES = Object.freeze({
  ip_information: `${API_TYPE}/ip_information`,
  ip_pbx_refresh: `${API_TYPE}/ip_pbx_refresh`,
  phonebook_search: `${API_TYPE}/phonebook_search`,
  phonebook_contact: `${API_TYPE}/phonebook_contact`,
});
const ADMIN_PRIVATE_QUERY_IDENTIFIER = /^[A-Za-z0-9_-]{1,32}$/;
const ADMIN_PRIVATE_QUERY_PREFIX = /^[A-Za-z]?$/;
const ADMIN_PRIVATE_QUERY_PHONE_NUMBER = /^\+?[0-9/\-*# ]*$/;
const ADMIN_PRIVATE_QUERY_BIRTHDAY = /^\d{2}\.\d{2}\.\d{4}$/;
const ADMIN_PRIVATE_QUERY_MAX_ROWS = 256;
const ADMIN_PRIVATE_QUERY_MAX_TEXT_LENGTH = 256;
const ADMIN_PRIVATE_QUERY_PBX_STATUSES = Object.freeze([
  "disconnected",
  "registered",
  "locked",
]);
const ADMIN_ACTION_SCHEMA_VERSION = 1;
const ADMIN_ACTION_MAX_DECT_TARGETS = 16;
const ADMIN_ACTION_MAX_VOIP_TARGETS = 32;
const ADMIN_ACTION_TOKEN = /^[a-f0-9]{32}$/;
const ADMIN_ACTION_MAX_HANDSET_NAME_LENGTH = 64;
const ADMIN_ACTION_VOIP_NUMBER_SUFFIX = /^[0-9]{4}$/;
const ADMIN_ACTION_UNAVAILABLE_REASONS = new Set([
  "controls_disabled",
  "unsupported_firmware",
  "capability_not_proven",
  "implementation_unavailable",
  "management_unavailable",
]);
export const ADMIN_ACTION_INFO = Object.freeze({
  dect_handset_enroll: Object.freeze({
    apiType: `${API_TYPE}/action/dect_handset_enroll`,
    featureId: "telephony_dect_handset_enrollment",
    icon: "mdi:phone-plus-outline",
    confirmation: "confirm",
    typedConfirmation: null,
    prerequisite: null,
    targetQuery: null,
    targetTokenTtlSeconds: null,
    risk: "sensitive",
  }),
  dect_repeater_enroll: Object.freeze({
    apiType: `${API_TYPE}/action/dect_repeater_enroll`,
    featureId: "telephony_dect_repeater_enrollment",
    icon: "mdi:access-point-plus",
    confirmation: "confirm",
    typedConfirmation: null,
    prerequisite: "dect_repeater_requirements",
    targetQuery: null,
    targetTokenTtlSeconds: null,
    risk: "sensitive",
  }),
  dect_handset_set_paging: Object.freeze({
    apiType: `${API_TYPE}/action/dect_handset_set_paging`,
    featureId: "telephony_dect_handset_paging",
    icon: "mdi:bell-ring-outline",
    confirmation: "confirm",
    typedConfirmation: null,
    prerequisite: null,
    targetQuery: "dect_handset_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 16,
    risk: "sensitive",
  }),
  voip_line_set_active: Object.freeze({
    apiType: `${API_TYPE}/action/voip_line_set_active`,
    featureId: "telephony_number_activation",
    icon: "mdi:phone-check-outline",
    confirmation: "confirm",
    typedConfirmation: null,
    prerequisite: null,
    targetQuery: "voip_line_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "disruptive",
  }),
  dect_handset_disconnect: Object.freeze({
    apiType: `${API_TYPE}/action/dect_handset_disconnect`,
    featureId: "telephony_dect_handset_disconnect",
    icon: "mdi:phone-remove-outline",
    confirmation: "typed",
    typedConfirmation: "DISCONNECT DECT HANDSET",
    prerequisite: null,
    targetQuery: "dect_handset_disconnect_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 16,
    risk: "destructive",
  }),
  dect_repeater_disconnect: Object.freeze({
    apiType: `${API_TYPE}/action/dect_repeater_disconnect`,
    featureId: "telephony_dect_repeater_disconnect",
    icon: "mdi:access-point-remove",
    confirmation: "typed",
    typedConfirmation: "DISCONNECT DECT REPEATER",
    prerequisite: null,
    targetQuery: "dect_repeater_disconnect_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 16,
    risk: "destructive",
  }),
  voip_provider_delete: Object.freeze({
    apiType: `${API_TYPE}/action/voip_provider_delete`,
    featureId: "telephony_provider_delete",
    icon: "mdi:account-remove-outline",
    confirmation: "typed",
    typedConfirmation: "DELETE VOIP PROVIDER",
    prerequisite: null,
    targetQuery: "voip_provider_delete_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "destructive",
  }),
  voip_line_delete: Object.freeze({
    apiType: `${API_TYPE}/action/voip_line_delete`,
    featureId: "telephony_number_delete",
    icon: "mdi:phone-minus-outline",
    confirmation: "typed",
    typedConfirmation: "DELETE VOIP NUMBER",
    prerequisite: null,
    targetQuery: "voip_line_delete_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "destructive",
  }),
  ip_pbx_client_delete: Object.freeze({
    apiType: `${API_TYPE}/action/ip_pbx_client_delete`,
    featureId: "telephony_ip_pbx_client_delete",
    icon: "mdi:account-minus-outline",
    confirmation: "typed",
    typedConfirmation: "DELETE IP PBX CLIENT",
    prerequisite: null,
    targetQuery: "ip_pbx_client_delete_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "destructive",
  }),
  phonebook_entry_delete: Object.freeze({
    apiType: `${API_TYPE}/action/phonebook_entry_delete`,
    featureId: "telephony_phonebook_entry_delete",
    icon: "mdi:book-remove-outline",
    confirmation: "typed",
    typedConfirmation: "DELETE PHONEBOOK ENTRY",
    prerequisite: null,
    targetQuery: "phonebook_entry_delete_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "destructive",
  }),
  nas_share_delete: Object.freeze({
    apiType: `${API_TYPE}/action/nas_share_delete`,
    featureId: "storage_nas_share_delete",
    icon: "mdi:folder-remove-outline",
    confirmation: "typed",
    typedConfirmation: "DELETE NAS SHARE",
    prerequisite: null,
    targetQuery: "nas_share_delete_targets",
    targetTokenTtlSeconds: 60,
    maxTargets: 32,
    risk: "destructive",
  }),
});
const DESTRUCTIVE_ADMIN_ACTION_IDS = Object.freeze(
  Object.keys(ADMIN_ACTION_INFO).filter(
    (actionId) => ADMIN_ACTION_INFO[actionId].risk === "destructive",
  ),
);
const ADMIN_ACTION_BY_FEATURE_ID = new Map(
  Object.entries(ADMIN_ACTION_INFO).map(([actionId, info]) => [
    info.featureId,
    actionId,
  ]),
);
const ADMIN_ACTION_PBX_TARGET_STATUSES = new Set([
  "disconnected",
  "registered",
  "locked",
]);
const DECT_HANDSET_TARGETS_API_TYPE = `${API_TYPE}/action/dect_handset_targets`;
const VOIP_LINE_TARGETS_API_TYPE = `${API_TYPE}/action/voip_line_targets`;
const PANEL_SCHEMA_VERSION = 31;
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
const DASHBOARD_SECTION_ORDER = [
  "connection",
  "bandwidth",
  "dsl",
  "mobile",
  "wireless",
  "clients",
  "telephony",
  "system",
  "management",
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
  dect_repeater: { labelKey: "child.dect_repeater", icon: "mdi:access-point" },
  ip_phone: { labelKey: "child.ip_phone", icon: "mdi:deskphone" },
  mesh_node: { labelKey: "child.mesh_node", icon: "mdi:access-point-network" },
  powerline_node: { labelKey: "child.powerline_node", icon: "mdi:power-plug" },
  receiver: { labelKey: "child.receiver", icon: "mdi:access-point-network" },
  telephone_line: { labelKey: "child.telephone_line", icon: "mdi:phone-in-talk" },
  usb_device: { labelKey: "child.usb_device", icon: "mdi:usb" },
};

const ADMIN_COMMON_DEVICE_FIELDS = [
  "name",
  "hostname",
  "manufacturer",
  "model",
  "firmware",
  "hardware_version",
  "serial",
  "mac",
];
const ADMIN_TRAFFIC_FIELDS = [
  "link_speed_bps",
  "download_rate_bps",
  "upload_rate_bps",
  "download_link_speed_bps",
  "upload_link_speed_bps",
  "bytes_received",
  "bytes_sent",
];
export const ADMIN_READ_SECTION_ORDER = Object.freeze([
  "clients",
  "mesh_nodes",
  "port_forward_rules",
  "port_block_rules",
  "dns_rebind_exceptions",
  "qos_prioritized_clients",
  "vpn_peers",
  "telephony_providers",
  "telephone_lines",
  "dect_handsets",
  "dect_repeaters",
  "ip_phones",
  "pbx_clients",
  "usb_devices",
  "receivers",
  "storage_devices",
  "nas_shares",
  "powerline_nodes",
  "internet_status_technical",
  "status_technical",
  "lan_ipv6_technical",
  "ddns_identity",
  "wifi_2_4_identity",
  "wifi_5_identity",
  "wifi_guest_identity",
  "wifi_office_identity",
]);
const ADMIN_READ_SECTION_INFO = Object.freeze({
  clients: {
    titleKey: "admin.section.clients",
    icon: "mdi:devices",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "ipv4",
      "configured_reserved_ipv4",
      "reserved_ipv4",
      "ipv6",
      "ipv6_ula",
      "ipv6_gua",
      "connected",
      "medium",
      "wifi_generation",
      "wifi_standard",
      "has_web_ui",
      "web_ui_port",
      "web_ui_scheme",
      "signal_dbm",
      ...ADMIN_TRAFFIC_FIELDS,
      "access_point",
      "mesh_node",
      "band",
      "channel",
      "last_seen",
      "parental_profile",
      "internet_paused",
      "internet_access_allowed",
      "fixed_dhcp",
      "uses_dhcp",
      "uses_rule",
    ],
  },
  mesh_nodes: {
    titleKey: "admin.section.mesh_nodes",
    icon: "mdi:access-point-network",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "connected",
      "parent",
      "device_type",
      "medium",
      "ipv4",
      "wifi_2_4_mac",
      "wifi_5_mac",
      "wifi_enabled",
      ...ADMIN_TRAFFIC_FIELDS,
      "signal_dbm",
      "band",
      "channel",
      "client_count",
      "role",
      "backhaul",
      "uptime_seconds",
      "linked_lan_port_count",
      "lan_port_1_speed_bps",
      "lan_port_2_speed_bps",
    ],
  },
  port_forward_rules: {
    titleKey: "admin.section.port_forward_rules",
    icon: "mdi:router-network",
    fields: ["name", "active", "target", "tcp_mappings", "udp_mappings"],
  },
  port_block_rules: {
    titleKey: "admin.section.port_block_rules",
    icon: "mdi:shield-lock-outline",
    fields: ["rule_group", "id", "active", "tcp_ports", "udp_ports"],
  },
  dns_rebind_exceptions: {
    titleKey: "admin.section.dns_rebind_exceptions",
    icon: "mdi:dns-outline",
    fields: ["domain"],
  },
  qos_prioritized_clients: {
    titleKey: "admin.section.qos_prioritized_clients",
    icon: "mdi:priority-high",
    fields: ["slot", "prioritized"],
  },
  ddns_identity: {
    titleKey: "admin.section.ddns_identity",
    icon: "mdi:dns-outline",
    fields: ["domain", "update_server"],
  },
  vpn_peers: {
    titleKey: "admin.section.vpn_peers",
    icon: "mdi:vpn",
    fields: ["id", "name", "enabled", "connected", "last_handshake"],
  },
  telephony_providers: {
    titleKey: "admin.section.telephony_providers",
    icon: "mdi:phone-cog",
    fields: ["id", "provider_code"],
  },
  telephone_lines: {
    titleKey: "admin.section.telephone_lines",
    icon: "mdi:phone-classic",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "registered",
      "enabled",
      "active_call",
      "call_state",
      "id",
      "status",
      "provider_code",
      "provider_id",
      "error_code",
    ],
  },
  dect_handsets: {
    titleKey: "admin.section.dect_handsets",
    icon: "mdi:phone-wireless",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "connected",
      "registered",
      "active_call",
      "charging",
      "battery_percent",
      "signal_dbm",
      "signal_percent",
      "call_state",
      "paging",
    ],
  },
  dect_repeaters: {
    titleKey: "admin.section.dect_repeaters",
    icon: "mdi:access-point-network",
    fields: ["id", "registered"],
  },
  ip_phones: {
    titleKey: "admin.section.ip_phones",
    icon: "mdi:deskphone",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "connected",
      "registered",
      "active_call",
      "call_state",
    ],
  },
  pbx_clients: {
    titleKey: "admin.section.pbx_clients",
    icon: "mdi:phone-switch",
    fields: ["id", "status", "name", "ipv4", "mac"],
  },
  usb_devices: {
    titleKey: "admin.section.usb_devices",
    icon: "mdi:usb",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "connected",
      "mounted",
      "total_bytes",
      "used_bytes",
      "free_bytes",
      "usage_percent",
      "temperature_celsius",
      "media_type",
    ],
  },
  receivers: {
    titleKey: "admin.section.receivers",
    icon: "mdi:access-point-network",
    fields: [
      ...ADMIN_COMMON_DEVICE_FIELDS,
      "connected",
      ...ADMIN_TRAFFIC_FIELDS,
      "network_type",
      "operator",
      "rsrp_dbm",
      "rsrq_db",
      "sinr_db",
      "rssi_dbm",
      "band",
      "frequency_mhz",
      "cell_id",
      "temperature_celsius",
    ],
  },
  storage_devices: {
    titleKey: "admin.section.storage_devices",
    icon: "mdi:harddisk",
    fields: [
      "name",
      "serial",
      "storage_type",
      "connection",
      "total_bytes",
      "used_bytes",
      "free_bytes",
    ],
  },
  nas_shares: {
    titleKey: "admin.section.nas_shares",
    icon: "mdi:folder-network",
    fields: ["id", "name", "enabled", "read_only", "secure"],
  },
  powerline_nodes: {
    titleKey: "admin.section.powerline_nodes",
    icon: "mdi:power-plug-outline",
    fields: [
      "id",
      "name",
      "parent",
      "manufacturer",
      "mac",
      "firmware",
      "mode",
      "download_link_speed_bps",
      "upload_link_speed_bps",
    ],
  },
  internet_status_technical: {
    titleKey: "admin.section.internet_status_technical",
    icon: "mdi:web-alert",
    source: "public_status",
    fields: ["failure_reason"],
  },
  status_technical: {
    titleKey: "admin.section.status_technical",
    icon: "mdi:identifier",
    source: "public_status",
    fields: ["domain_name"],
  },
  lan_ipv6_technical: {
    titleKey: "admin.section.lan_ipv6_technical",
    icon: "mdi:ip-network-outline",
    fields: ["ipv6_pext_flag", "ipv6_arec_flag"],
  },
  wifi_2_4_identity: {
    titleKey: "admin.section.wifi_2_4_identity",
    icon: "mdi:wifi",
    fields: ["ssid"],
  },
  wifi_5_identity: {
    titleKey: "admin.section.wifi_5_identity",
    icon: "mdi:wifi",
    fields: ["ssid"],
  },
  wifi_guest_identity: {
    titleKey: "admin.section.wifi_guest_identity",
    icon: "mdi:wifi-star",
    fields: ["ssid"],
  },
  wifi_office_identity: {
    titleKey: "admin.section.wifi_office_identity",
    icon: "mdi:wifi-lock",
    fields: ["ssid"],
  },
});
export const ADMIN_READ_SECTION_FIELDS = Object.freeze(
  Object.fromEntries(
    ADMIN_READ_SECTION_ORDER.map((sectionId) => [
      sectionId,
      Object.freeze([...ADMIN_READ_SECTION_INFO[sectionId].fields]),
    ]),
  ),
);
export const ADMIN_READ_SECTION_SOURCES = Object.freeze(
  Object.fromEntries(
    ADMIN_READ_SECTION_ORDER.map((sectionId) => [
      sectionId,
      ADMIN_READ_SECTION_INFO[sectionId].source || "protected_json",
    ]),
  ),
);
export const ADMIN_READ_FIELD_KEYS = Object.freeze([
  ...new Set(
    ADMIN_READ_SECTION_ORDER.flatMap(
      (sectionId) => ADMIN_READ_SECTION_INFO[sectionId].fields,
    ),
  ),
]);
const MAX_ADMIN_READ_ROWS = 256;
const MAX_ADMIN_READ_TEXT_LENGTH = 256;
export const ADMIN_READ_CLOSED_ENUM_VALUES = Object.freeze({
  failure_reason: Object.freeze(["dsl", "net", "router", "user"]),
});
const ADMIN_READ_CLOSED_ENUMS = Object.freeze({
  failure_reason: new Set(ADMIN_READ_CLOSED_ENUM_VALUES.failure_reason),
});
const ADMIN_RISK_ORDER = Object.freeze([
  "normal",
  "sensitive",
  "disruptive",
  "lockout",
  "destructive",
]);

function fixedAdminSubsection({
  id,
  icon,
  entityGroups = [],
  controls = [],
  readSections = [],
  features = [],
}) {
  return Object.freeze({
    id,
    titleKey: `admin.subsection.${id}`,
    icon,
    entityGroups: Object.freeze(entityGroups),
    controls: Object.freeze(controls),
    features: Object.freeze(features),
    readSections: Object.freeze(
      readSections.map(({ id: sectionId, capabilities = [] }) =>
        Object.freeze({
          id: sectionId,
          capabilities: Object.freeze(capabilities),
        }),
      ),
    ),
  });
}

function fixedAdminFeature(
  id,
  {
    contract = "blocked",
    controls = [],
    entityGroups = [],
    readSections = [],
    queries = [],
    adminActions = [],
    adminActionReplacesBlocked = false,
    capabilities = [],
    risk,
    blockedReasonKey,
  } = {},
) {
  if (risk !== undefined && !ADMIN_RISK_ORDER.includes(risk)) {
    throw new Error(`Unknown Administration feature risk: ${risk}`);
  }
  return Object.freeze({
    id,
    titleKey: `admin.feature.${id}`,
    contract,
    controls: Object.freeze(controls),
    entityGroups: Object.freeze(entityGroups),
    readSections: Object.freeze(readSections),
    queries: Object.freeze(queries),
    adminActions: Object.freeze(adminActions),
    adminActionReplacesBlocked,
    capabilities: Object.freeze(capabilities),
    risk,
    destructive: risk === "destructive",
    blockedReasonKey,
  });
}

function fixedAdminArea(id, icon, subsections) {
  return Object.freeze({
    id,
    titleKey: `admin.area.${id}`,
    icon,
    subsections: Object.freeze(subsections),
  });
}

/**
 * Fixed, reviewed Administration information architecture.
 *
 * Entries contain semantic Home Assistant keys only. They never contain router
 * endpoints, methods, request fields, or payload templates. An entity absent
 * from this manifest cannot appear as an Administration control.
 */
export const ADMIN_IA = Object.freeze([
  fixedAdminArea("internet", "mdi:web", [
    fixedAdminSubsection({
      id: "internet_connection",
      icon: "mdi:web-check",
      entityGroups: [
        "connection_internet",
        "connection_addressing",
        "connection_privacy",
      ],
      controls: [
        "button:reconnect_internet",
        "select:internet_privacy_level_control",
      ],
      readSections: [
        { id: "internet_status_technical", capabilities: ["internet"] },
      ],
      features: [
        fixedAdminFeature("internet_reconnect", {
          contract: "reviewed",
          controls: ["button:reconnect_internet"],
          entityGroups: ["connection_internet", "connection_addressing"],
          capabilities: ["internet"],
        }),
        fixedAdminFeature("internet_provider_configuration", {
          entityGroups: ["connection_internet", "bandwidth_interface"],
          capabilities: ["internet"],
        }),
        fixedAdminFeature("internet_connection_diagnostics", {
          contract: "read_only",
          entityGroups: ["connection_internet"],
          readSections: ["internet_status_technical"],
          capabilities: ["internet"],
        }),
        fixedAdminFeature("internet_ip_information", {
          contract: "read_only",
          queries: ["ip_information"],
          entityGroups: ["connection_addressing"],
          capabilities: ["internet"],
        }),
        fixedAdminFeature("internet_dns_servers", {
          capabilities: ["internet", "dns"],
        }),
        fixedAdminFeature("internet_privacy", {
          contract: "reviewed",
          controls: ["select:internet_privacy_level_control"],
          entityGroups: ["connection_privacy"],
          capabilities: ["connection_privacy"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "internet_mobile",
      icon: "mdi:signal-5g",
      entityGroups: [
        "mobile_connection",
        "mobile_radio",
        "mobile_signal",
        "mobile_receiver_status",
        "mobile_receiver_firmware",
        "mobile_receivers",
        "system_usb_tethering",
      ],
      controls: [
        "switch:hybrid_bonding",
        "select:receiver_led_mode_control",
      ],
      readSections: [{ id: "receivers", capabilities: ["receiver"] }],
      features: [
        fixedAdminFeature("internet_usb_tethering", {
          entityGroups: ["system_usb_tethering"],
          capabilities: ["usb_tethering"],
        }),
        fixedAdminFeature("internet_hybrid_bonding", {
          contract: "reviewed",
          controls: ["switch:hybrid_bonding"],
          entityGroups: ["mobile_connection", "mobile_tunnel"],
          capabilities: ["hybrid"],
        }),
        fixedAdminFeature("internet_receiver_led", {
          contract: "reviewed",
          controls: ["select:receiver_led_mode_control"],
          entityGroups: ["mobile_receiver_status"],
          capabilities: ["receiver_led"],
        }),
        fixedAdminFeature("internet_receiver_mode", {
          entityGroups: [
            "mobile_connection",
            "mobile_radio",
            "mobile_signal",
            "mobile_receiver_status",
            "mobile_receivers",
          ],
          readSections: ["receivers"],
          capabilities: ["receiver", "mobile"],
        }),
        fixedAdminFeature("internet_receiver_routing_exceptions", {
          capabilities: ["receiver", "mobile"],
        }),
        fixedAdminFeature("internet_receiver_firmware_update", {
          entityGroups: ["mobile_receiver_firmware"],
          capabilities: ["receiver"],
          risk: "disruptive",
        }),
        fixedAdminFeature("internet_receiver_factory_esim_restore", {
          capabilities: ["receiver"],
          risk: "destructive",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "internet_parental",
      icon: "mdi:account-child-outline",
      entityGroups: ["system_parental"],
      features: [
        fixedAdminFeature("internet_parental_controls", {
          entityGroups: ["system_parental"],
          capabilities: ["parental"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "internet_forwarding",
      icon: "mdi:router-network",
      entityGroups: [
        "clients_forwarding",
        "clients_upnp",
        "system_security_port_block",
      ],
      controls: ["switch:port_forward_rule"],
      readSections: [
        { id: "port_forward_rules", capabilities: ["nat"] },
        { id: "port_block_rules", capabilities: ["port_blocking"] },
      ],
      features: [
        fixedAdminFeature("internet_port_forward_toggle", {
          contract: "reviewed",
          controls: ["switch:port_forward_rule"],
          entityGroups: ["clients_forwarding"],
          readSections: ["port_forward_rules"],
          capabilities: ["nat"],
        }),
        fixedAdminFeature("internet_port_forward_editor", {
          entityGroups: ["clients_forwarding"],
          readSections: ["port_forward_rules"],
          capabilities: ["nat"],
        }),
        fixedAdminFeature("internet_port_blocking", {
          entityGroups: ["system_security_port_block"],
          readSections: ["port_block_rules"],
          capabilities: ["port_blocking"],
        }),
        fixedAdminFeature("internet_upnp", {
          entityGroups: ["clients_upnp"],
          capabilities: ["upnp"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "internet_ddns",
      icon: "mdi:dns-outline",
      entityGroups: ["system_ddns"],
      readSections: [{ id: "ddns_identity", capabilities: ["ddns"] }],
      features: [
        fixedAdminFeature("internet_ddns_management", {
          entityGroups: ["system_ddns"],
          readSections: ["ddns_identity"],
          capabilities: ["ddns"],
        }),
        fixedAdminFeature("internet_ddns_configuration_delete", {
          capabilities: ["ddns"],
          risk: "destructive",
        }),
      ],
    }),
  ]),
  fixedAdminArea("telephony", "mdi:phone", [
    fixedAdminSubsection({
      id: "telephony_numbers",
      icon: "mdi:phone-classic",
      entityGroups: [
        "telephony_registration",
        "telephony_lines",
        "telephony_voip",
        "telephony_call_encryption",
        "telephony_hd_voice",
      ],
      readSections: [
        { id: "telephony_providers", capabilities: ["telephony"] },
        { id: "telephone_lines", capabilities: ["telephony"] },
      ],
      features: [
        fixedAdminFeature("telephony_provider_registration", {
          entityGroups: ["telephony_registration", "telephony_lines"],
          readSections: ["telephony_providers", "telephone_lines"],
          capabilities: ["telephony"],
          risk: "sensitive",
        }),
        fixedAdminFeature("telephony_provider_delete", {
          adminActions: ["voip_provider_delete"],
          adminActionReplacesBlocked: true,
          capabilities: ["telephony"],
          risk: "destructive",
        }),
        fixedAdminFeature("telephony_number_delete", {
          adminActions: ["voip_line_delete"],
          adminActionReplacesBlocked: true,
          capabilities: ["telephony"],
          risk: "destructive",
        }),
        fixedAdminFeature("telephony_number_activation", {
          contract: "reviewed",
          adminActions: ["voip_line_set_active"],
          capabilities: ["telephony"],
          risk: "disruptive",
        }),
        fixedAdminFeature("telephony_number_assignment", {
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_number_use", {
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_call_encryption", {
          entityGroups: ["telephony_call_encryption"],
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_hd_voice", {
          entityGroups: ["telephony_hd_voice"],
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_dialing_delay", {
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_status_messages", {
          capabilities: ["telephony"],
        }),
        fixedAdminFeature("telephony_automatic_speed_dial", {
          capabilities: ["telephony"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "telephony_analog",
      icon: "mdi:phone-outline",
      features: [
        fixedAdminFeature("telephony_analog_socket_name", {
          capabilities: ["telephony", "analog"],
        }),
        fixedAdminFeature("telephony_analog_number_assignment", {
          capabilities: ["telephony", "analog"],
        }),
        fixedAdminFeature("telephony_analog_device_type", {
          capabilities: ["telephony", "analog"],
        }),
        fixedAdminFeature("telephony_analog_call_waiting", {
          capabilities: ["telephony", "analog"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "telephony_dect",
      icon: "mdi:phone-wireless",
      entityGroups: [
        "telephony_dect",
        "telephony_dect_base",
        "telephony_dect_scan",
        "telephony_dect_paging",
        "telephony_dect_handsets",
        "telephony_dect_repeaters",
      ],
      readSections: [
        { id: "dect_handsets", capabilities: ["dect"] },
        { id: "dect_repeaters", capabilities: ["dect"] },
      ],
      features: [
        fixedAdminFeature("telephony_dect_base", {
          entityGroups: ["telephony_dect_base"],
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_base_pin", {
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_transmit_power", {
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_full_eco", {
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_handset_enrollment", {
          contract: "reviewed",
          adminActions: ["dect_handset_enroll"],
          entityGroups: ["telephony_dect_scan"],
          capabilities: ["dect"],
          risk: "sensitive",
        }),
        fixedAdminFeature("telephony_dect_handset_configuration", {
          entityGroups: ["telephony_dect_handsets"],
          readSections: ["dect_handsets"],
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_handset_call_waiting", {
          capabilities: ["dect"],
        }),
        fixedAdminFeature("telephony_dect_handset_disconnect", {
          adminActions: ["dect_handset_disconnect"],
          adminActionReplacesBlocked: true,
          entityGroups: ["telephony_dect_handsets"],
          readSections: ["dect_handsets"],
          capabilities: ["dect"],
          risk: "destructive",
          blockedReasonKey:
            "admin.feature.blocked_reason.dect_handset_disconnect",
        }),
        fixedAdminFeature("telephony_dect_handset_paging", {
          contract: "reviewed",
          adminActions: ["dect_handset_set_paging"],
          entityGroups: ["telephony_dect_paging"],
          capabilities: ["dect"],
          risk: "sensitive",
        }),
        fixedAdminFeature("telephony_dect_repeater_enrollment", {
          contract: "reviewed",
          adminActions: ["dect_repeater_enroll"],
          entityGroups: ["telephony_dect_repeaters"],
          readSections: ["dect_repeaters"],
          capabilities: ["dect"],
          risk: "sensitive",
        }),
        fixedAdminFeature("telephony_dect_repeater_disconnect", {
          adminActions: ["dect_repeater_disconnect"],
          adminActionReplacesBlocked: true,
          entityGroups: ["telephony_dect_repeaters"],
          readSections: ["dect_repeaters"],
          capabilities: ["dect"],
          risk: "destructive",
          blockedReasonKey:
            "admin.feature.blocked_reason.dect_repeater_disconnect",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "telephony_pbx",
      icon: "mdi:phone-switch",
      entityGroups: ["telephony_pbx", "telephony_ip"],
      readSections: [
        { id: "ip_phones", capabilities: ["pbx"] },
        { id: "pbx_clients", capabilities: ["pbx"] },
      ],
      features: [
        fixedAdminFeature("telephony_ip_pbx", {
          entityGroups: ["telephony_pbx"],
          readSections: ["pbx_clients"],
          queries: ["ip_pbx_refresh"],
          capabilities: ["pbx"],
        }),
        fixedAdminFeature("telephony_ip_phone_enrollment", {
          entityGroups: ["telephony_ip"],
          readSections: ["ip_phones"],
          capabilities: ["pbx"],
        }),
        fixedAdminFeature("telephony_ip_phone_configuration", {
          entityGroups: ["telephony_ip"],
          capabilities: ["pbx"],
        }),
        fixedAdminFeature("telephony_ip_phone_disconnect", {
          entityGroups: ["telephony_ip"],
          capabilities: ["pbx"],
          risk: "destructive",
        }),
        fixedAdminFeature("telephony_ip_pbx_client_delete", {
          adminActions: ["ip_pbx_client_delete"],
          adminActionReplacesBlocked: true,
          capabilities: ["pbx"],
          risk: "destructive",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "telephony_calls",
      icon: "mdi:phone-in-talk",
      entityGroups: ["telephony_calls"],
      features: [
        fixedAdminFeature("telephony_call_lists", {
          entityGroups: ["telephony_calls"],
          capabilities: ["telephony", "calls"],
        }),
        fixedAdminFeature("telephony_keypad_functions", {
          contract: "unsupported",
          capabilities: ["telephony"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "telephony_phonebooks",
      icon: "mdi:book-open-page-variant",
      entityGroups: ["telephony_phonebooks"],
      features: [
        fixedAdminFeature("telephony_phonebook_management", {
          entityGroups: ["telephony_phonebooks"],
          queries: ["phonebook_search"],
          capabilities: ["telephony", "phonebook"],
        }),
        fixedAdminFeature("telephony_phonebook_entry_delete", {
          adminActions: ["phonebook_entry_delete"],
          adminActionReplacesBlocked: true,
          capabilities: ["telephony", "phonebook"],
          risk: "destructive",
        }),
      ],
    }),
  ]),
  fixedAdminArea("network", "mdi:lan", [
    fixedAdminSubsection({
      id: "network_devices",
      icon: "mdi:devices",
      entityGroups: ["clients_devices"],
      controls: ["text:client_name", "switch:client_fixed_dhcp"],
      readSections: [{ id: "clients", capabilities: ["clients"] }],
      features: [
        fixedAdminFeature("network_client_rename", {
          contract: "reviewed",
          controls: ["text:client_name"],
          capabilities: ["clients"],
        }),
        fixedAdminFeature("network_client_fixed_dhcp", {
          contract: "reviewed",
          controls: ["switch:client_fixed_dhcp"],
          capabilities: ["clients"],
        }),
        fixedAdminFeature("network_client_inventory", {
          contract: "read_only",
          entityGroups: ["clients_devices"],
          readSections: ["clients"],
          capabilities: ["clients"],
        }),
        fixedAdminFeature("network_client_manual_add", {
          entityGroups: ["clients_devices"],
          capabilities: ["clients"],
        }),
        fixedAdminFeature("network_client_delete", {
          entityGroups: ["clients_devices"],
          capabilities: ["clients"],
          risk: "destructive",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_mesh",
      icon: "mdi:access-point-network",
      entityGroups: ["wireless_mesh", "wireless_mesh_nodes"],
      readSections: [
        { id: "mesh_nodes", capabilities: ["mesh"] },
        { id: "powerline_nodes", capabilities: ["powerline"] },
      ],
      features: [
        fixedAdminFeature("network_mesh_management", {
          entityGroups: ["wireless_mesh", "wireless_mesh_nodes"],
          readSections: ["mesh_nodes"],
          capabilities: ["mesh"],
        }),
        fixedAdminFeature("network_mesh_node_rename"),
        fixedAdminFeature("network_mesh_identify", {
          capabilities: ["mesh"],
          risk: "disruptive",
        }),
        fixedAdminFeature("network_mesh_node_delete", {
          capabilities: ["mesh"],
          risk: "destructive",
        }),
        fixedAdminFeature("network_powerline_management", {
          readSections: ["powerline_nodes"],
          capabilities: ["powerline"],
        }),
        fixedAdminFeature("network_powerline_node_rename"),
      ],
    }),
    fixedAdminSubsection({
      id: "network_wifi",
      icon: "mdi:wifi-cog",
      entityGroups: [
        "wireless_2_4",
        "wireless_5",
        "wireless_radios",
        "wireless_schedule",
        "wireless_general",
      ],
      controls: ["switch:wifi"],
      readSections: [
        { id: "wifi_2_4_identity", capabilities: ["wifi"] },
        { id: "wifi_5_identity", capabilities: ["wifi"] },
      ],
      features: [
        fixedAdminFeature("network_wifi_main", {
          contract: "reviewed",
          controls: ["switch:wifi"],
          entityGroups: ["wireless_2_4", "wireless_5", "wireless_general"],
          capabilities: ["wifi"],
        }),
        fixedAdminFeature("network_wifi_radio_settings", {
          entityGroups: ["wireless_2_4", "wireless_5", "wireless_radios"],
          readSections: ["wifi_2_4_identity", "wifi_5_identity"],
          capabilities: ["wifi"],
        }),
        fixedAdminFeature("network_wifi_schedule", {
          entityGroups: ["wireless_schedule"],
          capabilities: ["wifi"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_wifi_access",
      icon: "mdi:wifi-lock",
      entityGroups: [
        "wireless_guest",
        "wireless_office",
        "wireless_access",
        "wireless_wps",
      ],
      controls: [
        "switch:guest_wifi",
        "switch:office_wifi",
        "button:wps",
      ],
      readSections: [
        { id: "wifi_guest_identity", capabilities: ["wifi"] },
        { id: "wifi_office_identity", capabilities: ["wifi"] },
      ],
      features: [
        fixedAdminFeature("network_wifi_guest", {
          contract: "reviewed",
          controls: ["switch:guest_wifi"],
          entityGroups: ["wireless_guest"],
          capabilities: ["wifi", "guest_wifi"],
        }),
        fixedAdminFeature("network_wifi_office", {
          contract: "reviewed",
          controls: ["switch:office_wifi"],
          entityGroups: ["wireless_office"],
          capabilities: ["wifi", "office_wifi"],
        }),
        fixedAdminFeature("network_wifi_wps_start", {
          contract: "reviewed",
          controls: ["button:wps"],
          entityGroups: ["wireless_wps"],
          capabilities: ["wifi", "wps"],
        }),
        fixedAdminFeature("network_wifi_wps_enablement", {
          entityGroups: ["wireless_wps"],
          capabilities: ["wifi", "wps"],
        }),
        fixedAdminFeature("network_wifi_wps_pin_mode", {
          capabilities: ["wifi", "wps"],
        }),
        fixedAdminFeature("network_wifi_identity_security", {
          entityGroups: ["wireless_guest", "wireless_office"],
          readSections: [
            "wifi_guest_identity",
            "wifi_office_identity",
          ],
          capabilities: ["wifi"],
        }),
        fixedAdminFeature("network_wifi_guest_access_pass", {
          capabilities: ["wifi", "guest_wifi"],
          blockedReasonKey:
            "admin.feature.blocked_reason.wifi_guest_access_pass",
        }),
        fixedAdminFeature("network_wifi_allowlist", {
          entityGroups: ["wireless_access"],
          capabilities: ["wifi"],
        }),
        fixedAdminFeature("network_wifi_environment_scan", {
          capabilities: ["wifi"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_lan",
      icon: "mdi:ip-network",
      entityGroups: ["clients_lan", "clients_dhcp"],
      readSections: [
        { id: "lan_ipv6_technical", capabilities: ["lan"] },
      ],
      features: [
        fixedAdminFeature("network_lan_identity", {
          contract: "read_only",
          entityGroups: ["clients_lan"],
          readSections: ["lan_ipv6_technical"],
          capabilities: ["lan"],
        }),
        fixedAdminFeature("network_lan_dhcp", {
          entityGroups: ["clients_lan", "clients_dhcp"],
          capabilities: ["lan", "clients"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_protection",
      icon: "mdi:shield-lock-outline",
      entityGroups: ["system_security_dns", "system_security_qos"],
      readSections: [
        { id: "dns_rebind_exceptions", capabilities: ["dns_rebind"] },
        { id: "qos_prioritized_clients", capabilities: ["qos"] },
      ],
      features: [
        fixedAdminFeature("network_traffic_prioritization", {
          entityGroups: ["system_security_qos"],
          readSections: ["qos_prioritized_clients"],
          capabilities: ["qos"],
        }),
        fixedAdminFeature("network_dns_rebind", {
          entityGroups: ["system_security_dns"],
          readSections: ["dns_rebind_exceptions"],
          capabilities: ["dns_rebind"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_vpn",
      icon: "mdi:vpn",
      entityGroups: ["system_vpn"],
      readSections: [{ id: "vpn_peers", capabilities: ["vpn"] }],
      features: [
        fixedAdminFeature("network_vpn_management", {
          entityGroups: ["system_vpn"],
          readSections: ["vpn_peers"],
          capabilities: ["vpn"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_storage",
      icon: "mdi:nas",
      entityGroups: ["system_usb", "system_nas"],
      readSections: [
        { id: "usb_devices", capabilities: ["usb"] },
        { id: "storage_devices", capabilities: ["usb"] },
        { id: "nas_shares", capabilities: ["usb"] },
      ],
      features: [
        fixedAdminFeature("network_usb_printer_media", {
          entityGroups: ["system_usb"],
          readSections: ["usb_devices", "storage_devices"],
          capabilities: ["usb"],
        }),
        fixedAdminFeature("network_usb_safe_remove", {
          capabilities: ["usb"],
          risk: "disruptive",
        }),
        fixedAdminFeature("network_nas_shares", {
          entityGroups: ["system_nas", "system_usb"],
          readSections: ["nas_shares", "storage_devices"],
          capabilities: ["usb", "nas"],
        }),
        fixedAdminFeature("storage_nas_share_delete", {
          adminActions: ["nas_share_delete"],
          adminActionReplacesBlocked: true,
          capabilities: ["usb", "nas"],
          risk: "destructive",
        }),
        fixedAdminFeature("network_media_folders", {
          entityGroups: ["system_nas", "system_usb"],
          capabilities: ["usb", "nas", "media_server"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "network_smarthome",
      icon: "mdi:home-automation",
      entityGroups: ["network_smarthome"],
      features: [
        fixedAdminFeature("network_smarthome_activation", {
          entityGroups: ["network_smarthome"],
          capabilities: ["smarthome", "system"],
        }),
      ],
    }),
  ]),
  fixedAdminArea("system", "mdi:router-network", [
    fixedAdminSubsection({
      id: "system_setup",
      icon: "mdi:progress-wrench",
      entityGroups: ["system_health", "system_security"],
      features: [
        fixedAdminFeature("system_initial_setup", {
          entityGroups: ["system_health", "system_security"],
          capabilities: ["system"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "system_maintenance",
      icon: "mdi:power-cycle",
      controls: ["button:reboot_router"],
      features: [
        fixedAdminFeature("system_reboot", {
          contract: "reviewed",
          controls: ["button:reboot_router"],
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_configuration_backup", {
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_configuration_restore", {
          capabilities: ["system"],
          risk: "destructive",
        }),
        fixedAdminFeature("system_factory_reset", {
          capabilities: ["system"],
          risk: "destructive",
        }),
        fixedAdminFeature("system_dect_reset", {
          entityGroups: ["telephony_dect"],
          capabilities: ["dect"],
          risk: "destructive",
        }),
        fixedAdminFeature("system_mesh_restart", {
          entityGroups: ["wireless_mesh", "wireless_mesh_nodes"],
          readSections: ["mesh_nodes"],
          capabilities: ["mesh"],
          risk: "disruptive",
        }),
        fixedAdminFeature("system_mesh_reset", {
          entityGroups: ["wireless_mesh", "wireless_mesh_nodes"],
          readSections: ["mesh_nodes"],
          capabilities: ["mesh"],
          risk: "destructive",
        }),
        fixedAdminFeature("system_dsl_modem_mode", {
          entityGroups: ["dsl_status", "connection_internet"],
          capabilities: ["dsl"],
          risk: "lockout",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "system_firmware",
      icon: "mdi:update",
      entityGroups: ["system_firmware"],
      features: [
        fixedAdminFeature("system_router_firmware", {
          entityGroups: ["system_firmware"],
          capabilities: ["firmware"],
          risk: "disruptive",
        }),
        fixedAdminFeature("system_mesh_firmware", {
          entityGroups: ["wireless_mesh_nodes"],
          readSections: ["mesh_nodes"],
          capabilities: ["firmware", "mesh"],
          risk: "disruptive",
        }),
        fixedAdminFeature("system_web_ui_version", {
          capabilities: ["system"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "system_security",
      icon: "mdi:shield-lock-outline",
      entityGroups: ["system_security"],
      features: [
        fixedAdminFeature("system_router_password", {
          entityGroups: ["system_security"],
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_router_pass", {
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_https_access", {
          entityGroups: ["system_security"],
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_firewall", {
          contract: "read_only",
          entityGroups: ["system_security"],
          capabilities: ["firewall"],
        }),
        fixedAdminFeature("system_email_notifications", {
          capabilities: ["system", "email_notifications"],
        }),
        fixedAdminFeature("system_safe_mail_allowlist", {
          contract: "unsupported",
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "system_information",
      icon: "mdi:information-outline",
      entityGroups: [
        "system_health",
        "system_services",
        "system_lan_ports",
        "system_local_display",
      ],
      readSections: [{ id: "status_technical", capabilities: ["system"] }],
      features: [
        fixedAdminFeature("system_front_led_schedule", {
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_lan_port_status", {
          contract: "read_only",
          entityGroups: ["system_lan_ports"],
          capabilities: ["lan", "system"],
        }),
        fixedAdminFeature("system_energy_settings", {
          entityGroups: ["wireless_general", "wireless_radios"],
          capabilities: ["system", "wifi"],
        }),
        fixedAdminFeature("system_information_services", {
          contract: "read_only",
          entityGroups: ["system_health", "system_services"],
          readSections: ["status_technical"],
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_messages", {
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_external_modem", {
          entityGroups: [
            "connection_internet",
            "mobile_receiver_status",
            "clients_lan",
          ],
          capabilities: ["receiver", "lan"],
          risk: "lockout",
        }),
        fixedAdminFeature("system_local_display_settings", {
          entityGroups: ["system_local_display"],
          capabilities: ["system"],
        }),
        fixedAdminFeature("system_physical_front_panel_actions", {
          contract: "unsupported",
          capabilities: ["system"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "system_support",
      icon: "mdi:lifebuoy",
      entityGroups: [
        "system_support",
        "system_easysupport",
        "system_easysupport_firmware",
        "system_remote_support",
      ],
      features: [
        fixedAdminFeature("system_easysupport_automatic_setup", {
          entityGroups: ["system_easysupport"],
          capabilities: ["system", "easysupport"],
        }),
        fixedAdminFeature("system_easysupport_automatic_firmware", {
          entityGroups: ["system_easysupport_firmware"],
          capabilities: ["system", "easysupport"],
        }),
        fixedAdminFeature("system_easysupport_wifi_backup", {
          capabilities: ["system", "easysupport"],
        }),
        fixedAdminFeature("system_easysupport_remote_support", {
          entityGroups: ["system_remote_support"],
          capabilities: ["system", "easysupport"],
        }),
        fixedAdminFeature("system_device_manager", {
          contract: "unsupported",
          entityGroups: ["system_easysupport"],
          capabilities: ["easysupport"],
        }),
      ],
    }),
  ]),
  fixedAdminArea("home_assistant", "mdi:home-assistant", [
    fixedAdminSubsection({
      id: "home_assistant_session",
      icon: "mdi:account-sync-outline",
      entityGroups: ["management_session"],
      controls: ["button:retry_protected_data"],
      features: [
        fixedAdminFeature("home_assistant_session_recovery", {
          contract: "reviewed",
          controls: ["button:retry_protected_data"],
          entityGroups: ["management_session"],
          capabilities: ["management"],
        }),
      ],
    }),
    fixedAdminSubsection({
      id: "home_assistant_diagnostics",
      icon: "mdi:database-search-outline",
      entityGroups: ["controls_diagnostics", "management_health"],
      controls: ["button:capture_read_only_inventory"],
      features: [
        fixedAdminFeature("home_assistant_capability_inventory", {
          contract: "read_only",
          controls: ["button:capture_read_only_inventory"],
          entityGroups: ["controls_diagnostics"],
          capabilities: ["management"],
        }),
      ],
    }),
  ]),
]);

// Some catalog features include more than one independently reviewed form.
// Partial links expose the working editor without claiming complete parity.
export const SETTINGS_FEATURE_LINKS = Object.freeze({
  internet_parental_controls: { ids: ["parental_profile_create", "parental_profile_edit", "parental_profile_delete"], complete: true },
  network_vpn_management: { ids: ["vpn_peer_create", "vpn_peer_enabled", "vpn_peer_delete", "vpn_ipsec_key_rotate"], complete: true },
  network_usb_safe_remove: { ids: ["storage_usb_safe_remove"], complete: true },
  network_smarthome_activation: { ids: ["network_smarthome_activate", "network_smarthome_deactivate"], complete: true },
  system_router_firmware: { ids: ["system_router_firmware_online"], complete: true },
  system_router_password: { ids: ["system_router_password_change"], complete: true },
  system_mesh_firmware: { ids: ["system_mesh_firmware_online"], complete: true },
  system_mesh_restart: { ids: ["system_mesh_restart"], complete: true },
  system_mesh_reset: { ids: ["system_mesh_reset"], complete: true },
  internet_receiver_firmware_update: { ids: ["internet_receiver_firmware_update"], complete: true },
  internet_receiver_factory_esim_restore: { ids: ["internet_receiver_factory_esim_restore"], complete: true },
  internet_port_blocking: { ids: ["port_blocking_create", "port_blocking_edit", "port_blocking_delete"], complete: true },
  network_media_folders: { ids: ["storage_media_folder", "storage_media_folder_delete", "storage_media_folder_create", "storage_media_reindex"], complete: true },
  network_mesh_node_rename: { ids: ["network_mesh_node_rename"], complete: true },
  network_mesh_node_delete: { ids: ["network_mesh_node_delete"], complete: true },
  network_mesh_identify: { ids: ["network_mesh_identify_start", "network_mesh_identify_stop"], complete: true },
  internet_port_forward_editor: { ids: ["port_forward_create", "port_forward_edit", "port_forward_delete", "port_forward_range_create", "port_forward_range_edit", "port_forward_range_delete"], complete: true },
  telephony_provider_registration: { ids: ["telephony_provider_telekom", "telephony_provider_regio", "telephony_provider_other", "telephony_provider_create_telekom", "telephony_provider_create_regio", "telephony_provider_create_other", "telephony_number_create_telekom", "telephony_number_create_regio", "telephony_number_create_other"], complete: true },
  telephony_number_assignment: { ids: ["telephony_incoming_assignment", "telephony_outgoing_assignment"], complete: true },
  network_dns_rebind: { ids: ["dns_rebind_protection", "dns_exception_create", "dns_exception_edit", "dns_exception_delete"], complete: true },
  telephony_hd_voice: { ids: ["telephony_hd_voice"], complete: true },
  telephony_dialing_delay: { ids: ["telephony_dial_delay"], complete: true },
  telephony_status_messages: { ids: ["telephony_status_audio"], complete: true },
  telephony_call_encryption: { ids: ["telephony_voice_encryption"], complete: true },
  telephony_automatic_speed_dial: { ids: ["telephony_automatic_speed_dial", "telephony_number_memory_clear"], complete: true },
  telephony_dect_base: { ids: ["telephony_dect_enabled"], complete: true },
  telephony_dect_base_pin: { ids: ["telephony_dect_settings"], complete: true },
  telephony_dect_transmit_power: { ids: ["telephony_dect_settings"], complete: true },
  telephony_dect_full_eco: { ids: ["telephony_dect_settings"], complete: true },
  telephony_ip_pbx: { ids: ["telephony_ip_pbx_enabled"], complete: false },
  telephony_ip_phone_configuration: { ids: ["telephony_ip_phone"], complete: true },
  telephony_ip_phone_enrollment: { ids: ["telephony_ip_phone_create"], complete: true },
  telephony_phonebook_management: { ids: ["telephony_phonebook_update_interval", "telephony_phonebook_contact", "telephony_phonebook_create", "telephony_handset_phonebook", "telephony_phonebook_rename", "telephony_phonebook_delete", "telephony_phonebook_disconnect", "telephony_phonebook_account_create", "telephony_phonebook_link"], complete: true },
  telephony_call_lists: { ids: ["call_history_clear_dialed", "call_history_clear_missed", "call_history_clear_taken"], complete: true },
  network_powerline_node_rename: { ids: ["powerline_rename"], complete: true },
  internet_usb_tethering: { ids: ["usb_tethering_enabled", "usb_tethering_activate"], complete: true },
  internet_hybrid_bonding: { ids: ["receiver_bonding"], complete: true },
  internet_receiver_led: { ids: ["receiver_led_mode"], complete: true },
  internet_receiver_routing_exceptions: { ids: ["routing_exception_enabled", "routing_exception_delete"], complete: false },
  telephony_number_use: { ids: ["telephony_line_options"], complete: true },
  telephony_analog_socket_name: { ids: ["telephony_analog_socket"], complete: true },
  telephony_analog_number_assignment: { ids: ["telephony_analog_socket"], complete: true },
  telephony_analog_device_type: { ids: ["telephony_analog_socket"], complete: true },
  telephony_analog_call_waiting: { ids: ["telephony_analog_socket"], complete: true },
  telephony_dect_handset_configuration: { ids: ["telephony_dect_handset"], complete: true },
  telephony_dect_handset_call_waiting: { ids: ["telephony_dect_handset"], complete: true },
  network_wifi_radio_settings: { ids: ["wifi_radio"], complete: true },
  network_wifi_schedule: { ids: ["wifi_schedule"], complete: true },
  network_wifi_identity_security: { ids: ["wifi_identity", "wifi_guest_settings", "wifi_office_settings"], complete: true },
  network_wifi_allowlist: { ids: ["wifi_access"], complete: true },
  network_traffic_prioritization: { ids: ["qos_devices", "qos_voice_priority"], complete: true },
  network_wifi_guest: { ids: ["wifi_guest_settings"], complete: true },
  network_wifi_office: { ids: ["wifi_office_settings"], complete: true },
  network_lan_identity: { ids: ["lan_ipv4"], complete: false },
  network_lan_dhcp: { ids: ["dhcp"], complete: true },
  network_nas_shares: { ids: ["storage_nas_share", "storage_nas_share_create", "nas_workgroup"], complete: true },
  internet_ddns_management: { ids: ["dynamic_dns", "dynamic_dns_delete"], complete: true },
  internet_provider_configuration: { ids: ["internet_connection"], complete: true },
  internet_dns_servers: { ids: ["internet_connection"], complete: true },
  system_front_led_schedule: { ids: ["system_led_schedule"], complete: true },
  system_energy_settings: { ids: ["system_energy"], complete: true },
  system_https_access: { ids: ["system_https"], complete: true },
  system_external_modem: { ids: ["system_external_modem"], complete: true },
  system_messages: { ids: ["system_extended_logging", "system_log_filter"], complete: false },
  system_easysupport_wifi_backup: { ids: ["system_cloud_backup"], complete: true },
  system_easysupport_automatic_setup: { ids: ["system_easysupport", "system_easysupport_bng_activation", "system_easysupport_bng_deactivation"], complete: true },
  system_easysupport_automatic_firmware: { ids: ["system_easysupport"], complete: true },
  system_email_notifications: { ids: ["system_email_notifications"], complete: true },
  system_local_display_settings: { ids: ["system_oled_display_rule", "wifi_identity", "wifi_guest_settings"], complete: true },
});
const MAINTENANCE_FEATURE_LINKS = Object.freeze({
  system_factory_reset: "system_factory_reset",
  system_dect_reset: "system_dect_reset",
  system_dsl_modem_mode: "system_dsl_modem_mode",
  system_messages: "system_log_clear",
});
const FILE_TRANSFER_FEATURE_LINKS = Object.freeze({
  system_configuration_backup: "system_backup_download",
  system_configuration_restore: "system_backup_restore",
  system_router_firmware: "system_firmware_upload",
  system_mesh_firmware: "system_mesh_firmware_upload",
  system_messages: "system_log_download",
  system_router_pass: "system_router_pass_download",
  telephony_phonebook_management: Array.from({length: 6}, (_, book) => [
    `phonebook_export_${book}`, `phonebook_import_${book}`,
  ]).flat(),
});

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
  telephony_dect_base: { titleKey: "group.telephony_dect_base", icon: "mdi:phone-wireless" },
  telephony_dect_scan: { titleKey: "group.telephony_dect_scan", icon: "mdi:access-point-plus" },
  telephony_dect_paging: { titleKey: "group.telephony_dect_paging", icon: "mdi:phone-ring" },
  telephony_dect_handsets: { titleKey: "group.telephony_dect_handsets", icon: "mdi:cellphone" },
  telephony_dect_repeaters: { titleKey: "group.telephony_dect_repeaters", icon: "mdi:access-point" },
  telephony_pbx: { titleKey: "group.telephony_pbx", icon: "mdi:phone-switch" },
  telephony_voip: { titleKey: "group.telephony_voip", icon: "mdi:phone-lock" },
  telephony_call_encryption: { titleKey: "group.telephony_call_encryption", icon: "mdi:phone-lock" },
  telephony_hd_voice: { titleKey: "group.telephony_hd_voice", icon: "mdi:waveform" },
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
  system_easysupport: { titleKey: "group.system_easysupport", icon: "mdi:lifebuoy" },
  system_easysupport_firmware: { titleKey: "group.system_easysupport_firmware", icon: "mdi:update" },
  system_remote_support: { titleKey: "group.system_remote_support", icon: "mdi:remote-desktop" },
  system_lan_ports: { titleKey: "group.system_lan_ports", icon: "mdi:ethernet" },
  system_local_display: { titleKey: "group.system_local_display", icon: "mdi:monitor" },
  system_services: { titleKey: "group.system_services", icon: "mdi:cog-outline" },
  network_smarthome: { titleKey: "group.network_smarthome", icon: "mdi:home-automation" },
  management_session: { titleKey: "group.management_session", icon: "mdi:account-lock-outline" },
  management_health: { titleKey: "group.management_health", icon: "mdi:home-assistant" },
  controls_wireless: { titleKey: "group.controls_wireless", icon: "mdi:wifi-cog" },
  controls_internet: { titleKey: "group.controls_internet", icon: "mdi:web-sync" },
  controls_mobile: { titleKey: "group.controls_mobile", icon: "mdi:signal-5g" },
  controls_clients: { titleKey: "group.controls_clients", icon: "mdi:account-lock-outline" },
  controls_forwarding: { titleKey: "group.controls_forwarding", icon: "mdi:router-network" },
  controls_system: { titleKey: "group.controls_system", icon: "mdi:power-cycle" },
  controls_session: { titleKey: "group.controls_session", icon: "mdi:account-sync-outline" },
  controls_diagnostics: { titleKey: "group.controls_diagnostics", icon: "mdi:database-search-outline" },
};
const CAPABILITY_GROUP_ORDER = {
  connection: ["connection_internet", "connection_addressing", "connection_privacy"],
  bandwidth: ["bandwidth_capacity", "bandwidth_totals", "bandwidth_packets", "bandwidth_errors", "bandwidth_interface", "bandwidth_polling", "bandwidth_live"],
  dsl: ["dsl_status", "dsl_sync", "dsl_attainable", "dsl_quality", "dsl_errors"],
  mobile: ["mobile_connection", "mobile_radio", "mobile_signal", "mobile_tunnel", "mobile_receiver_status", "mobile_receiver_firmware", "mobile_receivers"],
  wireless: ["wireless_2_4", "wireless_5", "wireless_guest", "wireless_office", "wireless_radios", "wireless_access", "wireless_wps", "wireless_schedule", "wireless_mesh", "wireless_mesh_nodes", "wireless_general"],
  clients: ["clients_overview", "clients_devices", "clients_lan", "clients_dhcp", "system_lan_ports", "clients_forwarding", "clients_upnp"],
  telephony: ["telephony_registration", "telephony_calls", "telephony_lines", "telephony_dect", "telephony_dect_base", "telephony_dect_scan", "telephony_dect_paging", "telephony_dect_handsets", "telephony_dect_repeaters", "telephony_pbx", "telephony_voip", "telephony_call_encryption", "telephony_hd_voice", "telephony_ip", "telephony_phonebooks"],
  system: ["system_health", "system_firmware", "system_support", "system_easysupport", "system_easysupport_firmware", "system_remote_support", "system_security", "system_security_dns", "system_security_port_block", "system_security_qos", "system_ddns", "system_vpn", "system_parental", "system_usb", "system_usb_tethering", "system_nas", "system_services", "system_local_display"],
  management: ["management_session", "management_health"],
  controls: ["controls_session", "controls_diagnostics", "controls_wireless", "controls_internet", "controls_mobile", "controls_clients", "controls_forwarding", "controls_system"],
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

function isSemanticControl(meta) {
  return meta?.control_supported === true || meta?.control === true;
}

export function splitPanelEntities(entities) {
  const reporting = [];
  const controls = [];
  for (const entity of Array.isArray(entities) ? entities : []) {
    if (entity?.section === "controls") controls.push(entity);
    else reporting.push(entity);
  }
  return { controls, reporting };
}

export function normalizeAdminReadPayload(payload, entryId) {
  if (
    payload?.schema_version !== ADMIN_READ_SCHEMA_VERSION ||
    payload?.entry_id !== entryId ||
    !Array.isArray(payload?.sections) ||
    payload.sections.length > ADMIN_READ_SECTION_ORDER.length
  ) {
    return undefined;
  }

  const seen = new Set();
  const sections = [];
  for (const section of payload.sections) {
    const sectionId = section?.id;
    const info = ADMIN_READ_SECTION_INFO[sectionId];
    const expectedSource = info?.source || "protected_json";
    if (
      typeof sectionId !== "string" ||
      !Object.hasOwn(ADMIN_READ_SECTION_INFO, sectionId) ||
      seen.has(sectionId) ||
      section.source !== expectedSource ||
      !Array.isArray(section.rows) ||
      typeof section.truncated !== "boolean"
    ) {
      return undefined;
    }
    seen.add(sectionId);

    const rows = [];
    for (const rawRow of section.rows.slice(0, MAX_ADMIN_READ_ROWS)) {
      if (!rawRow || typeof rawRow !== "object" || Array.isArray(rawRow)) {
        continue;
      }
      const row = {};
      for (const field of info.fields) {
        if (!Object.hasOwn(rawRow, field)) continue;
        const value = rawRow[field];
        const allowedValues = ADMIN_READ_CLOSED_ENUMS[field];
        if (allowedValues && !allowedValues.has(value)) continue;
        if (typeof value === "string") {
          row[field] = value.slice(0, MAX_ADMIN_READ_TEXT_LENGTH);
        } else if (
          typeof value === "boolean" ||
          (typeof value === "number" && Number.isFinite(value))
        ) {
          row[field] = value;
        }
      }
      if (Object.keys(row).length) rows.push(row);
    }
    sections.push({
      id: sectionId,
      rows,
      source: expectedSource,
      truncated: section.truncated || section.rows.length > MAX_ADMIN_READ_ROWS,
    });
  }

  sections.sort(
    (left, right) =>
      ADMIN_READ_SECTION_ORDER.indexOf(left.id) -
      ADMIN_READ_SECTION_ORDER.indexOf(right.id),
  );
  return {
    schema_version: ADMIN_READ_SCHEMA_VERSION,
    entry_id: entryId,
    sections,
  };
}

function hasExactKeys(value, expected) {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join("\u0000") === [...expected].sort().join("\u0000")
  );
}

function adminActionToken(value) {
  return typeof value === "string" && ADMIN_ACTION_TOKEN.test(value)
    ? value
    : undefined;
}

/** Normalize only the closed administrator-action advertisements understood here. */
export function normalizeAdminActionMetadata(value) {
  const actions = new Map();
  if (!Array.isArray(value) || value.length > Object.keys(ADMIN_ACTION_INFO).length) {
    return actions;
  }
  for (const raw of value) {
    const info = Object.hasOwn(ADMIN_ACTION_INFO, raw?.id)
      ? ADMIN_ACTION_INFO[raw.id]
      : undefined;
    const reasonValid =
      raw?.available === true
        ? raw.unavailable_reason === null
        : ADMIN_ACTION_UNAVAILABLE_REASONS.has(raw?.unavailable_reason);
    if (
      !info ||
      actions.has(raw.id) ||
      raw.feature_id !== info.featureId ||
      typeof raw.supported !== "boolean" ||
      typeof raw.available !== "boolean" ||
      (raw.available && !raw.supported) ||
      raw.risk !== info.risk ||
      raw.confirmation !== info.confirmation ||
      raw.typed_confirmation !== info.typedConfirmation ||
      (raw.confirmation === "confirm"
        ? raw.typed_confirmation !== null
        : typeof raw.typed_confirmation !== "string" ||
          raw.typed_confirmation.length < 8 ||
          raw.typed_confirmation.length > 64 ||
          !/^[\x20-\x7E]+$/.test(raw.typed_confirmation)) ||
      raw.prerequisite !== info.prerequisite ||
      raw.prerequisite_confirmation_required !==
        (info.prerequisite !== null) ||
      raw.target_query !== info.targetQuery ||
      raw.target_token_ttl_seconds !== info.targetTokenTtlSeconds ||
      !reasonValid
    ) {
      continue;
    }
    actions.set(
      raw.id,
      Object.freeze({
        id: raw.id,
        feature_id: raw.feature_id,
        supported: raw.supported,
        available: raw.available,
        unavailable_reason: raw.unavailable_reason,
        risk: raw.risk,
        confirmation: raw.confirmation,
        typed_confirmation: raw.typed_confirmation,
        prerequisite: raw.prerequisite,
        prerequisite_confirmation_required:
          raw.prerequisite_confirmation_required,
        target_query: raw.target_query,
        target_token_ttl_seconds: raw.target_token_ttl_seconds,
      }),
    );
  }
  return actions;
}

/** Build one exact, fixed WebSocket action request. */
export function adminActionRequest(
  actionId,
  entryId,
  parameters = {},
  confirmationText,
) {
  const info = Object.hasOwn(ADMIN_ACTION_INFO, actionId)
    ? ADMIN_ACTION_INFO[actionId]
    : undefined;
  if (
    !info ||
    typeof entryId !== "string" ||
    entryId.length === 0 ||
    entryId.length > 64
  ) {
    return undefined;
  }
  let typedConfirmation = {};
  if (info.confirmation === "typed") {
    if (
      typeof confirmationText !== "string" ||
      confirmationText !== info.typedConfirmation ||
      confirmationText.length < 8 ||
      confirmationText.length > 64 ||
      !/^[\x20-\x7E]+$/.test(confirmationText)
    ) {
      return undefined;
    }
    typedConfirmation = { confirmation_text: confirmationText };
  } else if (confirmationText !== undefined) {
    return undefined;
  }
  const base = {
    type: info.apiType,
    entry_id: entryId,
    confirmed: true,
    ...typedConfirmation,
  };
  if (actionId === "dect_handset_enroll" && hasExactKeys(parameters, [])) {
    return base;
  }
  if (
    actionId === "dect_repeater_enroll" &&
    hasExactKeys(parameters, [
      "pin_is_default",
      "full_power_enabled",
      "full_eco_disabled",
    ]) &&
    parameters.pin_is_default === true &&
    parameters.full_power_enabled === true &&
    parameters.full_eco_disabled === true
  ) {
    return {
      ...base,
      pin_is_default: true,
      full_power_enabled: true,
      full_eco_disabled: true,
    };
  }
  if (
    actionId === "dect_handset_set_paging" &&
    hasExactKeys(parameters, ["target_token", "enabled"]) &&
    adminActionToken(parameters.target_token) &&
    typeof parameters.enabled === "boolean"
  ) {
    return {
      ...base,
      target_token: parameters.target_token,
      enabled: parameters.enabled,
    };
  }
  if (
    actionId === "voip_line_set_active" &&
    hasExactKeys(parameters, ["target_token", "active"]) &&
    adminActionToken(parameters.target_token) &&
    typeof parameters.active === "boolean"
  ) {
    return {
      ...base,
      target_token: parameters.target_token,
      active: parameters.active,
    };
  }
  if (
    info.risk === "destructive" &&
    info.targetQuery &&
    hasExactKeys(parameters, ["target_token"]) &&
    adminActionToken(parameters.target_token)
  ) {
    return {
      ...base,
      target_token: parameters.target_token,
    };
  }
  return undefined;
}

/** Verify an action acknowledgement without retaining router response data. */
export function normalizeAdminActionResult(payload, actionId, expectedActive) {
  if (
    payload?.schema_version !== ADMIN_ACTION_SCHEMA_VERSION ||
    payload?.action !== actionId
  ) {
    return false;
  }
  if (
    actionId === "dect_handset_enroll" ||
    actionId === "dect_repeater_enroll"
  ) {
    return (
      payload?.result?.status === "verified" &&
      payload.result.lifecycle === "scan_active"
    );
  }
  if (ADMIN_ACTION_INFO[actionId]?.risk === "destructive") {
    return (
      ["verified", "unchanged"].includes(payload?.result?.status) &&
      payload.result.deleted === true
    );
  }
  return (
    ["dect_handset_set_paging", "voip_line_set_active"].includes(actionId) &&
    ["verified", "unchanged"].includes(payload?.result?.status) &&
    typeof expectedActive === "boolean" &&
    payload.result.active === expectedActive
  );
}

/** Normalize the bounded, ephemeral DECT paging target query. */
export function normalizeDectHandsetTargets(payload) {
  if (
    payload?.schema_version !== ADMIN_ACTION_SCHEMA_VERSION ||
    payload?.query !== "dect_handset_targets" ||
    !Array.isArray(payload?.result?.targets) ||
    typeof payload?.result?.truncated !== "boolean"
  ) {
    return undefined;
  }
  const seen = new Set();
  const targets = [];
  for (const raw of payload.result.targets.slice(0, ADMIN_ACTION_MAX_DECT_TARGETS)) {
    const targetToken = adminActionToken(raw?.target_token);
    const reference = adminPrivateQueryIdentifier(raw?.reference);
    if (
      !targetToken ||
      !reference ||
      seen.has(targetToken) ||
      typeof raw?.paging !== "boolean"
    ) {
      continue;
    }
    seen.add(targetToken);
    const target = {
      target_token: targetToken,
      reference,
      paging: raw.paging,
    };
    if (
      typeof raw.name === "string" &&
      raw.name.length > 0 &&
      raw.name.length <= ADMIN_ACTION_MAX_HANDSET_NAME_LENGTH &&
      raw.name === raw.name.trim() &&
      !/[\p{C}\p{Zl}\p{Zp}]/u.test(raw.name)
    ) {
      target.name = raw.name;
    }
    targets.push(target);
  }
  return {
    targets,
    truncated:
      payload.result.truncated ||
      payload.result.targets.length > ADMIN_ACTION_MAX_DECT_TARGETS,
  };
}

/** Normalize action-safe VoIP target tokens without joining broad cached rows. */
export function normalizeVoipLineTargets(payload) {
  if (
    payload?.schema_version !== ADMIN_ACTION_SCHEMA_VERSION ||
    payload?.query !== "voip_line_targets" ||
    !Array.isArray(payload?.result?.targets) ||
    typeof payload?.result?.truncated !== "boolean"
  ) {
    return undefined;
  }
  const seen = new Set();
  const targets = [];
  for (const raw of payload.result.targets.slice(0, ADMIN_ACTION_MAX_VOIP_TARGETS)) {
    const targetToken = adminActionToken(raw?.target_token);
    const reference = adminPrivateQueryIdentifier(raw?.reference);
    if (
      !targetToken ||
      !reference ||
      seen.has(targetToken) ||
      typeof raw?.active !== "boolean"
    ) {
      continue;
    }
    seen.add(targetToken);
    const target = { target_token: targetToken, reference, active: raw.active };
    if (
      typeof raw.number_suffix === "string" &&
      ADMIN_ACTION_VOIP_NUMBER_SUFFIX.test(raw.number_suffix)
    ) {
      target.number_suffix = raw.number_suffix;
    }
    targets.push(target);
  }
  return {
    targets,
    truncated:
      payload.result.truncated ||
      payload.result.targets.length > ADMIN_ACTION_MAX_VOIP_TARGETS,
  };
}

/** Normalize one destructive action's bounded, one-use target handshake. */
export function normalizeDestructiveAdminActionTargets(payload, actionId) {
  const info = Object.hasOwn(ADMIN_ACTION_INFO, actionId)
    ? ADMIN_ACTION_INFO[actionId]
    : undefined;
  if (
    info?.risk !== "destructive" ||
    payload?.schema_version !== ADMIN_ACTION_SCHEMA_VERSION ||
    payload?.query !== info.targetQuery ||
    !Array.isArray(payload?.result?.targets) ||
    typeof payload?.result?.truncated !== "boolean"
  ) {
    return undefined;
  }
  const seen = new Set();
  const targets = [];
  for (const raw of payload.result.targets.slice(0, info.maxTargets)) {
    const targetToken = adminActionToken(raw?.target_token);
    const reference = adminPrivateQueryIdentifier(raw?.reference);
    if (!targetToken || !reference || seen.has(targetToken)) continue;
    seen.add(targetToken);
    const target = { target_token: targetToken, reference };
    if (
      ["dect_handset_disconnect", "ip_pbx_client_delete", "nas_share_delete"].includes(
        actionId,
      )
    ) {
      const name = adminPrivateQueryText(raw.name, 64);
      if (name !== undefined) target.name = name;
    } else if (actionId === "voip_provider_delete") {
      if (
        Number.isInteger(raw.provider_code) &&
        raw.provider_code >= 0 &&
        raw.provider_code <= 9_999
      ) {
        target.provider_code = raw.provider_code;
      }
    } else if (actionId === "voip_line_delete") {
      if (typeof raw.active === "boolean") target.active = raw.active;
      if (
        typeof raw.number_suffix === "string" &&
        ADMIN_ACTION_VOIP_NUMBER_SUFFIX.test(raw.number_suffix)
      ) {
        target.number_suffix = raw.number_suffix;
      }
    } else if (actionId === "phonebook_entry_delete") {
      const displayName = adminPrivateQueryText(raw.display_name, 64);
      if (displayName !== undefined) target.display_name = displayName;
    }
    if (
      actionId === "ip_pbx_client_delete" &&
      ADMIN_ACTION_PBX_TARGET_STATUSES.has(raw.status)
    ) {
      target.status = raw.status;
    }
    targets.push(target);
  }
  return {
    targets,
    truncated:
      payload.result.truncated || payload.result.targets.length > info.maxTargets,
  };
}

function emptyAdminActionTargetState() {
  return {
    errorKey: "",
    loaded: false,
    loading: false,
    request: 0,
    expiresAt: 0,
    generation: undefined,
    result: undefined,
  };
}

function emptyAdminActionState() {
  return {
    handsetTargets: emptyAdminActionTargetState(),
    voipLineTargets: emptyAdminActionTargetState(),
    destructiveTargets: Object.fromEntries(
      DESTRUCTIVE_ADMIN_ACTION_IDS.map((actionId) => [
        actionId,
        emptyAdminActionTargetState(),
      ]),
    ),
    phonebookId: 0,
  };
}

function adminPrivateQueryText(value, maxLength = ADMIN_PRIVATE_QUERY_MAX_TEXT_LENGTH) {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > maxLength ||
    value !== value.trim() ||
    /[\p{C}\p{Zl}\p{Zp}]/u.test(value)
  ) {
    return undefined;
  }
  return value;
}

function adminPrivateQueryIdentifier(value) {
  return typeof value === "string" &&
    ADMIN_PRIVATE_QUERY_IDENTIFIER.test(value)
    ? value
    : undefined;
}

function adminPrivateQueryPhoneNumber(value) {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= 64 &&
    value === value.trim() &&
    ADMIN_PRIVATE_QUERY_PHONE_NUMBER.test(value)
    ? value
    : undefined;
}

function adminPrivateQueryIpv4(value) {
  if (typeof value !== "string") return undefined;
  const parts = value.split(".");
  if (
    parts.length !== 4 ||
    parts.some((part) => {
      const numeric = Number(part);
      return (
        !/^\d{1,3}$/.test(part) ||
        !Number.isInteger(numeric) ||
        numeric < 0 ||
        numeric > 255 ||
        String(numeric) !== part
      );
    })
  ) {
    return undefined;
  }
  return value;
}

function adminPrivateQueryMac(value) {
  return typeof value === "string" &&
    /^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(value)
    ? value
    : undefined;
}

function adminPrivateQueryPhonebookId(value) {
  return Number.isInteger(value) && value >= 0 && value <= 5
    ? value
    : undefined;
}

/** Return a translated validation key for one exact backend query contract. */
export function adminPrivateQueryInputError(query, input) {
  if (query === "ip_pbx_refresh") {
    return adminPrivateQueryIdentifier(input?.clientId) === undefined
      ? "admin.query.error.identifier"
      : undefined;
  }
  if (query === "phonebook_search") {
    if (adminPrivateQueryPhonebookId(input?.phonebookId) === undefined) {
      return "admin.query.error.phonebook";
    }
    return typeof input?.prefix !== "string" ||
      !ADMIN_PRIVATE_QUERY_PREFIX.test(input.prefix)
      ? "admin.query.error.prefix"
      : undefined;
  }
  if (query === "phonebook_contact") {
    if (adminPrivateQueryPhonebookId(input?.phonebookId) === undefined) {
      return "admin.query.error.phonebook";
    }
    return adminPrivateQueryIdentifier(input?.contactId) === undefined
      ? "admin.query.error.identifier"
      : undefined;
  }
  return "admin.query.error.unavailable";
}

function normalizeAdminPrivatePbxResult(result, expected) {
  const clientId = adminPrivateQueryIdentifier(result?.client_id);
  const statusCode = result?.status_code;
  if (
    clientId === undefined ||
    clientId !== expected?.clientId ||
    !Number.isInteger(statusCode) ||
    statusCode < 0 ||
    statusCode >= ADMIN_PRIVATE_QUERY_PBX_STATUSES.length ||
    result?.status !== ADMIN_PRIVATE_QUERY_PBX_STATUSES[statusCode]
  ) {
    return undefined;
  }
  const normalized = {
    client_id: clientId,
    status: result.status,
    status_code: statusCode,
  };
  const name = adminPrivateQueryText(result.name);
  const ipv4 = adminPrivateQueryIpv4(result.ipv4);
  const mac = adminPrivateQueryMac(result.mac);
  if (name !== undefined) normalized.name = name;
  if (ipv4 !== undefined) normalized.ipv4 = ipv4;
  if (mac !== undefined) normalized.mac = mac;
  return normalized;
}

function normalizeAdminPrivateSearchResult(result, expected) {
  const phonebookId = adminPrivateQueryPhonebookId(result?.phonebook_id);
  const prefix = result?.prefix;
  if (
    phonebookId === undefined ||
    phonebookId !== expected?.phonebookId ||
    typeof prefix !== "string" ||
    !ADMIN_PRIVATE_QUERY_PREFIX.test(prefix) ||
    prefix !== expected?.prefix ||
    !Array.isArray(result?.entries) ||
    typeof result?.truncated !== "boolean"
  ) {
    return undefined;
  }
  const entries = [];
  for (const rawEntry of result.entries.slice(0, ADMIN_PRIVATE_QUERY_MAX_ROWS)) {
    if (!rawEntry || typeof rawEntry !== "object" || Array.isArray(rawEntry)) {
      continue;
    }
    const contactId = adminPrivateQueryIdentifier(rawEntry.contact_id);
    if (contactId === undefined) continue;
    const entry = { contact_id: contactId };
    const lastName = adminPrivateQueryText(rawEntry.last_name);
    const firstName = adminPrivateQueryText(rawEntry.first_name);
    const number = adminPrivateQueryPhoneNumber(rawEntry.number);
    if (lastName !== undefined) entry.last_name = lastName;
    if (firstName !== undefined) entry.first_name = firstName;
    if (number !== undefined) entry.number = number;
    entries.push(entry);
  }
  const normalized = {
    phonebook_id: phonebookId,
    prefix,
    entries,
    truncated:
      result.truncated || result.entries.length > ADMIN_PRIVATE_QUERY_MAX_ROWS,
  };
  if (
    Number.isInteger(result.total) &&
    result.total >= 0 &&
    result.total <= 1000
  ) {
    normalized.total = result.total;
  }
  if (
    Number.isInteger(result.free_entries) &&
    result.free_entries >= 0 &&
    result.free_entries <= 1000
  ) {
    normalized.free_entries = result.free_entries;
  }
  return normalized;
}

function normalizeAdminPrivateContactResult(result, expected) {
  const phonebookId = adminPrivateQueryPhonebookId(result?.phonebook_id);
  const contactId = adminPrivateQueryIdentifier(result?.contact_id);
  if (
    phonebookId === undefined ||
    phonebookId !== expected?.phonebookId ||
    contactId === undefined ||
    contactId !== expected?.contactId ||
    !result?.contact ||
    typeof result.contact !== "object" ||
    Array.isArray(result.contact)
  ) {
    return undefined;
  }
  const fieldLimits = {
    last_name: 256,
    first_name: 256,
    private_number: 64,
    work_number: 64,
    mobile_number: 64,
    secondary_mobile_number: 64,
    street: 256,
    postal_code: 32,
    city: 256,
    birthday: 10,
  };
  const phoneFields = new Set([
    "private_number",
    "work_number",
    "mobile_number",
    "secondary_mobile_number",
  ]);
  const contact = {};
  for (const [field, maxLength] of Object.entries(fieldLimits)) {
    let value;
    if (phoneFields.has(field)) {
      value = adminPrivateQueryPhoneNumber(result.contact[field]);
    } else if (field === "birthday") {
      value =
        typeof result.contact[field] === "string" &&
        ADMIN_PRIVATE_QUERY_BIRTHDAY.test(result.contact[field])
          ? result.contact[field]
          : undefined;
    } else {
      value = adminPrivateQueryText(result.contact[field], maxLength);
    }
    if (value !== undefined) contact[field] = value;
  }
  if (Object.keys(contact).length === 0) return undefined;
  return { phonebook_id: phonebookId, contact_id: contactId, contact };
}

/** Allowlist one ephemeral private-query response before it reaches the DOM. */
const ADMIN_IP_INFORMATION_FIELDS = Object.freeze({
  ipv4: Object.freeze(["address", "gateway", "dns_primary", "dns_secondary"]),
  ipv6: Object.freeze(["delegated_prefix", "lan_prefix", "address", "gateway", "dns_primary", "dns_secondary"]),
});

function normalizeAdminIpInformation(result) {
  if (Object.keys(result).length !== 2 || !Object.hasOwn(result, "ipv4") || !Object.hasOwn(result, "ipv6")) return undefined;
  const normalized = {};
  for (const [family, fields] of Object.entries(ADMIN_IP_INFORMATION_FIELDS)) {
    const values = result[family];
    if (!values || typeof values !== "object" || Array.isArray(values) ||
        Object.keys(values).some((field) => !fields.includes(field))) return undefined;
    normalized[family] = {};
    for (const [field, value] of Object.entries(values)) {
      if (typeof value !== "string" || value.length > 128 || value !== value.trim() || /[\s%]/.test(value)) return undefined;
      if (family === "ipv4") {
        if (!adminPrivateQueryIpv4(value)) return undefined;
      } else {
        const parts = value.split("/");
        if (field.endsWith("prefix")) {
          if (parts.length > 2 || parts.length === 2 && (!/^(?:0|[1-9][0-9]{0,2})$/.test(parts[1]) || Number(parts[1]) > 128)) return undefined;
        } else if (parts.length !== 1) return undefined;
        if (!/^[0-9a-f:.]+$/i.test(parts[0]) || !parts[0].includes(":")) return undefined;
        try { new URL(`http://[${parts[0]}]/`); } catch { return undefined; }
      }
      normalized[family][field] = value;
    }
  }
  return normalized;
}

export function normalizeAdminPrivateQueryPayload(payload, query, expected) {
  if (
    payload?.schema_version !== ADMIN_PRIVATE_QUERY_SCHEMA_VERSION ||
    payload?.query !== query ||
    !payload?.result ||
    typeof payload.result !== "object" ||
    Array.isArray(payload.result)
  ) {
    return undefined;
  }
  if (query === "ip_information") return normalizeAdminIpInformation(payload.result);
  if (query === "ip_pbx_refresh") {
    return normalizeAdminPrivatePbxResult(payload.result, expected);
  }
  if (query === "phonebook_search") {
    return normalizeAdminPrivateSearchResult(payload.result, expected);
  }
  if (query === "phonebook_contact") {
    return normalizeAdminPrivateContactResult(payload.result, expected);
  }
  return undefined;
}

function emptyAdminPrivateQueryState() {
  return {
    ip: {errorKey: "", loading: false, attempted: false, result: undefined},
    pbx: {
      clientId: "",
      errorKey: "",
      loading: false,
      request: 0,
      result: undefined,
    },
    phonebook: {
      contactErrorKey: "",
      contactLoading: false,
      contactRequest: 0,
      contactResult: undefined,
      phonebookId: 0,
      prefix: "",
      searchErrorKey: "",
      searchLoading: false,
      searchRequest: 0,
      searchResult: undefined,
    },
  };
}

function formatAdminReadBytes(value, locale) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return String(value);
  const units = ["B", "kB", "MB", "GB", "TB"];
  let display = numeric;
  let unitIndex = 0;
  while (display >= 1_000 && unitIndex < units.length - 1) {
    display /= 1_000;
    unitIndex += 1;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(display)} ${units[unitIndex]}`;
}

export function formatAdminReadValue(field, value, locale, language) {
  if (typeof value === "boolean") {
    return panelTranslate(
      language,
      value ? "admin.value.yes" : "admin.value.no",
    );
  }
  if (typeof value === "number") {
    const formatter = new Intl.NumberFormat(locale, {
      maximumFractionDigits: 2,
    });
    if (field.includes("bytes")) return formatAdminReadBytes(value, locale);
    if (field.endsWith("_bps")) {
      return `${formatter.format(value / 1_000_000)} Mbit/s`;
    }
    if (field.endsWith("_percent") || field === "usage_percent") {
      return `${formatter.format(value)} %`;
    }
    if (field.endsWith("_seconds")) {
      return (
        formatPanelDurationSeconds(value, locale, language) ||
        `${formatter.format(value)} s`
      );
    }
    if (field.endsWith("_celsius")) return `${formatter.format(value)} °C`;
    if (field.endsWith("_dbm")) return `${formatter.format(value)} dBm`;
    if (field.endsWith("_db")) return `${formatter.format(value)} dB`;
    if (field.endsWith("_mhz")) return `${formatter.format(value)} MHz`;
    return formatter.format(value);
  }
  if (
    typeof value === "string" &&
    ["last_seen", "last_handshake"].includes(field)
  ) {
    const timestamp = Date.parse(value);
    if (Number.isFinite(timestamp)) {
      return new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(timestamp);
    }
  }
  return String(value ?? "");
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
  if (childKind === "powerline_node") return "clients_lan";
  if (childKind === "receiver") return "mobile_receivers";
  if (childKind === "telephone_line") return "telephony_lines";
  if (childKind === "dect_handset") return "telephony_dect_handsets";
  if (childKind === "dect_repeater") return "telephony_dect_repeaters";
  if (childKind === "ip_phone") return "telephony_ip";
  if (childKind === "usb_device") return "system_usb";
  if (childKind) return `${section}_other_devices`;
  if (key.startsWith("lan_port_")) return "system_lan_ports";
  if (key === "guest_wifi_display_key_enabled") {
    return "system_local_display";
  }
  if (key === "easy_support_enabled") return "system_easysupport";
  if (key === "firmware_automatic_updates") {
    return "system_easysupport_firmware";
  }
  // Keep the legacy entity key, but classify its actual br_active meaning.
  if (key === "remote_support_active") return "system_support";
  if (key === "telephony_voip_policy") {
    return "telephony_call_encryption";
  }
  if (key === "telephony_hd_voice_active") return "telephony_hd_voice";
  if (key === "dect_enabled") return "telephony_dect_base";
  if (key === "dect_scan_active") return "telephony_dect_scan";
  if (key === "dect_paging_active" || key === "dect_paging_handsets") {
    return "telephony_dect_paging";
  }
  if (key === "dect_handsets") return "telephony_dect_handsets";
  if (key === "dect_repeaters") return "telephony_dect_repeaters";
  // Telekom places SmartHome under Network. Keep the exact linked-state entity
  // there without moving unrelated router-service diagnostics with it.
  if (key === "smarthome_linked") return "network_smarthome";
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
      key === "dsl_error_seconds" ||
      key === "dsl_error_code"
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
      key.startsWith("mobile_rssi") ||
      key === "mobile_nr_signal" ||
      key === "mobile_lte_signal"
    ) {
      return "mobile_signal";
    }
    if (
      key.startsWith("mobile_band") ||
      key.startsWith("mobile_frequency") ||
      key.startsWith("mobile_cell_id") ||
      key === "mobile_nr_band" ||
      key === "mobile_lte_band"
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
    if (key.startsWith("office_wifi") || key.startsWith("wifi_office")) {
      return "wireless_office";
    }
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
    if (key === "phonebook_entries") return "telephony_phonebooks";
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
      key === "remote_management" ||
      key === "router_https_enabled"
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
    if (key === "capture_read_only_inventory") return "controls_diagnostics";
    if (
      [
        "hybrid_bonding",
        "internet_privacy_level_control",
        "reconnect_internet",
      ].includes(key)
    ) {
      return "controls_internet";
    }
    if (key === "receiver_led_mode_control") return "controls_mobile";
    if (["wifi", "guest_wifi", "office_wifi", "wps"].includes(key)) {
      return "controls_wireless";
    }
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
    if (key === "reboot_router" || key === "firmware") {
      return "controls_system";
    }
  }
  return `${section}_other`;
}

/**
 * Canonical render owners for entity groups intentionally shared by subsections.
 * Any new duplicate group must be reviewed and added here before module startup.
 */
export const ADMIN_SHARED_ENTITY_GROUP_OWNERS = Object.freeze({
  system_health: Object.freeze({
    areaId: "system",
    subsectionId: "system_information",
  }),
  system_security: Object.freeze({
    areaId: "system",
    subsectionId: "system_security",
  }),
});

/** Build deterministic subsection owners and reject unreviewed duplicates. */
export function buildAdminEntityGroupPlacements(
  areas,
  sharedOwners = ADMIN_SHARED_ENTITY_GROUP_OWNERS,
) {
  const claims = new Map();
  for (const area of areas) {
    for (const subsection of area.subsections) {
      const placement = Object.freeze({
        areaId: area.id,
        subsectionId: subsection.id,
      });
      for (const group of subsection.entityGroups) {
        if (!claims.has(group)) claims.set(group, []);
        claims.get(group).push(placement);
      }
    }
  }

  for (const group of Object.keys(sharedOwners)) {
    const candidates = claims.get(group);
    if (!candidates) {
      throw new Error(
        `Administration entity-group owner references unknown group: ${group}`,
      );
    }
    if (candidates.length < 2) {
      throw new Error(
        `Administration entity-group owner is redundant for unshared group: ${group}`,
      );
    }
  }

  const placements = new Map();
  for (const [group, candidates] of claims) {
    if (candidates.length === 1) {
      placements.set(group, candidates[0]);
      continue;
    }
    if (!Object.hasOwn(sharedOwners, group)) {
      throw new Error(
        `Administration entity group has no explicit shared owner: ${group}`,
      );
    }
    const expected = sharedOwners[group];
    const owner = candidates.find(
      (candidate) =>
        candidate.areaId === expected.areaId &&
        candidate.subsectionId === expected.subsectionId,
    );
    if (!owner) {
      throw new Error(
        `Administration entity-group owner is not a declared placement: ${group}`,
      );
    }
    placements.set(group, owner);
  }
  return placements;
}

const ADMIN_CONTROL_FEATURE = new Map();
const ADMIN_ENTITY_GROUP_PLACEMENT = buildAdminEntityGroupPlacements(ADMIN_IA);
const ADMIN_FEATURE_PLACEMENT = new Map();
const ADMIN_FEATURE_ENTITY_GROUPS = new Set();
const ADMIN_READ_SECTION_OWNER = new Map();
for (const area of ADMIN_IA) {
  for (const subsection of area.subsections) {
    const placement = Object.freeze({
      areaId: area.id,
      subsectionId: subsection.id,
    });
    for (const feature of subsection.features) {
      ADMIN_FEATURE_PLACEMENT.set(feature.id, placement);
      for (const control of feature.controls) {
        ADMIN_CONTROL_FEATURE.set(control, feature.id);
      }
      for (const group of feature.entityGroups) {
        ADMIN_FEATURE_ENTITY_GROUPS.add(group);
      }
      for (const readSection of feature.readSections) {
        // A cached collection may support several related capabilities. Render it
        // once under the first feature that claims it in the reviewed manifest;
        // later features still use it as status evidence without duplicating data.
        if (!ADMIN_READ_SECTION_OWNER.has(readSection)) {
          ADMIN_READ_SECTION_OWNER.set(readSection, feature.id);
        }
      }
    }
  }
}

function adminFeatureForControl(meta) {
  if (!isSemanticControl(meta)) return undefined;
  if (
    typeof meta.management_feature === "string" &&
    meta.management_feature.length > 0
  ) {
    return ADMIN_FEATURE_PLACEMENT.has(meta.management_feature)
      ? meta.management_feature
      : undefined;
  }
  return ADMIN_CONTROL_FEATURE.get(
    `${String(meta.domain || "")}:${String(meta.translation_key || "")}`,
  );
}

/** Return the reviewed Administration placement for an entity, if any. */
export function adminPlacementFor(meta) {
  if (!meta) return undefined;
  if (isSemanticControl(meta)) {
    const featureId = adminFeatureForControl(meta);
    return featureId ? ADMIN_FEATURE_PLACEMENT.get(featureId) : undefined;
  }
  if (meta.child_device?.kind === "powerline_node") {
    return { areaId: "network", subsectionId: "network_mesh" };
  }
  return ADMIN_ENTITY_GROUP_PLACEMENT.get(capabilityGroupFor(meta));
}

function administrationEntityStateChanged(meta, previousState, nextState) {
  if (adminPlacementFor(meta) !== undefined) {
    return previousState !== nextState;
  }
  if (!ADMIN_FEATURE_ENTITY_GROUPS.has(capabilityGroupFor(meta))) {
    return false;
  }
  return (
    entityAvailability(meta, previousState) !==
    entityAvailability(meta, nextState)
  );
}

/** Return the exact highest backend-supplied risk represented by controls. */
export function highestAdminRisk(entities) {
  let highest;
  let highestRank = -1;
  for (const entity of entities || []) {
    if (!isSemanticControl(entity)) continue;
    const rank = ADMIN_RISK_ORDER.indexOf(entity.risk);
    if (rank > highestRank) {
      highest = entity.risk;
      highestRank = rank;
    }
  }
  return highest;
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

function iconFromRange(value, range) {
  const thresholds = Object.entries(range)
    .map(([threshold, icon]) => ({ icon, value: Number(threshold) }))
    .filter(({ value: threshold }) => Number.isFinite(threshold))
    .sort((left, right) => left.value - right.value);
  if (thresholds.length === 0 || value < thresholds[0].value) return undefined;
  let selectedThreshold = thresholds[0];
  for (const threshold of thresholds) {
    if (value < threshold.value) break;
    selectedThreshold = threshold;
  }
  return selectedThreshold.icon;
}

function translatedIconFor(stateValue, translations) {
  if (!translations) return undefined;
  if (stateValue && translations.state?.[stateValue]) {
    return translations.state[stateValue];
  }
  if (
    stateValue !== undefined &&
    translations.range &&
    Number.isFinite(Number(stateValue))
  ) {
    return (
      iconFromRange(Number(stateValue), translations.range) ??
      translations.default
    );
  }
  return translations.default;
}

export function iconFor(
  meta,
  state,
  platformIcons = undefined,
  componentIcons = undefined,
  entityRegistryEntries = undefined,
) {
  const registryIcon = entityRegistryEntries?.[meta.entity_id]?.icon;
  if (registryIcon) return registryIcon;
  if (state?.attributes?.icon) return state.attributes.icon;
  const translated = platformIcons?.[meta.domain]?.[meta.translation_key];
  const translatedIcon = translatedIconFor(state?.state, translated);
  if (translatedIcon) return translatedIcon;
  const domainIcons = componentIcons?.[meta.domain];
  const componentTranslated =
    domainIcons?.[state?.attributes?.device_class] || domainIcons?._;
  const componentIcon = translatedIconFor(state?.state, componentTranslated);
  if (componentIcon) return componentIcon;
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
  if (["learning", "stable", "cooldown", "retrying", "limited"].includes(schedulerState)) {
    live.state = schedulerState;
    live.retrying = ["cooldown", "retrying"].includes(schedulerState);
  } else if (schedulerEntityState) {
    live.available = false;
    live.retrying = false;
  }
  const schedulerAttributes = schedulerEntityState?.attributes || {};
  if (typeof schedulerAttributes.source_available === "boolean") {
    const schedulerAt = typeof schedulerEntityState?.last_updated === "string" ? Date.parse(schedulerEntityState.last_updated) : NaN;
    const checkedAt = typeof source.availability_checked_at === "string" ? Date.parse(source.availability_checked_at) : NaN;
    const now = Date.now();
    const interval = Number(source.effective_interval_seconds);
    const freshness = Math.min(300000, Math.max(30000, (Number.isFinite(interval) && interval > 0 ? interval : 10) * 4000));
    // A server-side metadata snapshot can precede an HA recovery update.
    // Compare server timestamps, not the browser's receipt time or a cached
    // last-success clock. Older, missing or stale evidence cannot undo failure.
    const newerHealthyScheduler = ["learning", "stable"].includes(schedulerState) &&
      Number.isFinite(schedulerAt) && Number.isFinite(checkedAt) && schedulerAt > checkedAt &&
      checkedAt <= now + LIVE_TRAFFIC_CLOCK_SKEW_MS && schedulerAt <= now + LIVE_TRAFFIC_CLOCK_SKEW_MS &&
      now - schedulerAt <= freshness;
    live.available =
      source.supported !== false && ["learning", "stable", "limited"].includes(schedulerState) &&
      ((source.polling_available !== false && source.available !== false) || newerHealthyScheduler) &&
      schedulerAttributes.source_available;
  }
  if (Object.hasOwn(schedulerAttributes, "observed_interval_seconds")) {
    const observed = schedulerAttributes.observed_interval_seconds;
    if (typeof observed === "number" && Number.isFinite(observed) && observed > 0) live.observed_interval_seconds = observed;
    else delete live.observed_interval_seconds;
  }
  for (const key of ["rate_window_seconds", "rate_sample_span_seconds"]) {
    if (!Object.hasOwn(schedulerAttributes, key)) continue;
    const seconds = schedulerAttributes[key];
    if (typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0) live[key] = seconds;
    else delete live[key];
  }
  if (live.available === false || live.supported === false || live.retrying === true ||
      !["learning", "stable"].includes(live.state)) {
    delete live.observed_interval_seconds;
    delete live.rate_sample_span_seconds;
  }
  const retryInSeconds = schedulerAttributes.retry_in_seconds;
  if (typeof retryInSeconds === "number" && Number.isFinite(retryInSeconds) && retryInSeconds >= 0) {
    live.retry_in_seconds = retryInSeconds;
  } else if (Object.hasOwn(schedulerAttributes, "retry_in_seconds")) {
    delete live.retry_in_seconds;
  }
  for (const [key, minimum, maximum] of [["success_streak", 0, 5], ["success_samples_required", 5, 5], ["cooldown_seconds", 60, 60]]) {
    if (!Object.hasOwn(schedulerAttributes, key)) continue;
    const value = schedulerAttributes[key];
    if (Number.isSafeInteger(value) && value >= minimum && value <= maximum) live[key] = value;
    else delete live[key];
  }

  const interval = positiveNumberState(stateFor("wan_polling_interval"));
  if (interval !== undefined) live.effective_interval_seconds = interval;
  const fastest = positiveNumberState(
    stateFor("wan_fastest_proven_interval"),
  );
  if (fastest !== undefined) live.last_stable_interval_seconds = fastest;
  const lastSample = usableState(stateFor("wan_last_sample"));
  if (live.last_sampled_at === undefined && lastSample !== undefined) {
    live.last_sampled_at = lastSample;
  }
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
    isWanSource && (source.retrying === true || ["cooldown", "retrying"].includes(source.state));
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
    ["learning", "stable", "cooldown", "retrying", "limited"].includes(source?.state)
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
    ? isWanSource && source.state === "cooldown"
      ? "status.rate_cooldown"
      : availability === "available"
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
    this._platformIcons = undefined;
    this._componentIcons = undefined;
    this._platformIconsLoading = false;
    this._selectedEntry = undefined;
    this._activeView = "dashboard";
    this._trafficHistory = createTrafficHistoryController({
      request: (message) => this._hass.connection.sendMessagePromise(message),
      onChange: () => {
        if (this.isConnected && this._activeView === "dashboard") this._scheduleRender();
      },
    });
    this._adminTab = "overview";
    this._adminPage = undefined;
    this._adminPageEpoch = 0;
    this._adminMenuOpen = false;
    this._privateRequestQueue = Promise.resolve();
    this._privateReadReadyAt = {read: 0, targets: 0, callHistory: 0};
    this._privateReadNow = () => Date.now();
    this._privateReadWait = (delay) => new Promise((resolve) => setTimeout(resolve, delay));
    this._settingsEditors = new Map();
    this._adminRecoverySelections = new Map();
    this._adminSessionInvalidationPending = undefined;
    this._adminPageRecoveryPending = undefined;
    this._settingsHost = undefined;
    this._settingsBinding = undefined;
    this._settingsEditor = this._newConfigurationEditor();
    this._maintenanceHost = undefined;
    this._maintenanceBinding = undefined;
    this._maintenanceEditor = createMaintenanceEditorController({
      request: (message) => {
        if (this._hass?.user?.is_admin !== true || message.entry_id !== this._currentRouter()?.entry_id) {
          return Promise.reject(new Error("administrator_required"));
        }
        return this._requestPrivate(message);
      },
      onChange: () => { this._flushAdminSessionInvalidation(); this._renderMaintenanceEditor(); },
    });
    this._fileTransferHost = undefined;
    this._fileTransferBinding = undefined;
    this._fileTransferEditor = createFileTransferEditorController({
      request: (path, options) => {
        const entryId = this._currentRouter()?.entry_id;
        if (this._hass?.user?.is_admin !== true || !entryId ||
            !path.startsWith(`/api/speedport_smart/file_transfer/${encodeURIComponent(entryId)}/`)) {
          return Promise.reject(new Error("administrator_required"));
        }
        return this._hass.fetchWithAuth(path, options);
      },
      download: async (blob, filename) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url; link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
      onChange: () => { this._flushAdminSessionInvalidation(); this._renderFileTransferEditor(); },
    });
    this._adminRead = undefined;
    this._callHistoryHost = undefined;
    this._callHistoryBinding = undefined;
    this._callHistoryView = createCallHistoryViewController({
      request: (message) => {
        if (this._hass?.user?.is_admin !== true || this._activeView !== "administration" ||
            message.entry_id !== this._currentRouter()?.entry_id) {
          return Promise.reject(new Error("administrator_required"));
        }
        return this._requestPrivate(message);
      },
      onChange: () => this._renderCallHistoryEditor(),
    });
    this._adminReadEntry = undefined;
    this._adminReadLoading = false;
    this._adminReadError = "";
    this._adminReadRequest = 0;
    this._adminReadRefreshPending = undefined;
    this._adminPrivateQueries = emptyAdminPrivateQueryState();
    this._adminPrivateQueryEpoch = 0;
    this._focusAfterPrivateQuery = undefined;
    this._adminActionState = emptyAdminActionState();
    this._adminActionEpoch = 0;
    this._adminActionNow = () => Date.now();
    this._focusAfterAdminAction = undefined;
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
    this.shadowRoot.addEventListener("submit", (event) => this._handleSubmit(event));
    this.shadowRoot.addEventListener("focusout", (event) => {
      if (event.target?.matches?.("[data-traffic-window]") && this._trafficWindowRenderPending) {
        this._trafficWindowRenderPending = false;
        this._scheduleRender();
      }
    });
    this.shadowRoot.addEventListener("toggle", (event) => this._handleToggle(event), true);
  }

  set hass(value) {
    const previous = this._hass;
    const firstAssignment = !previous;
    const currentRouter = this._currentRouter();
    const userContextChanged = Boolean(
      previous &&
        (previous.user?.id !== value.user?.id ||
          previous.user?.is_admin !== value.user?.is_admin),
    );
    const managementAvailabilityChanged = Boolean(
      previous &&
        currentRouter &&
        this._adminManagementAvailable(previous, currentRouter) !==
          this._adminManagementAvailable(value, currentRouter),
    );
    const shouldRender = this._shouldRenderForHass(previous, value);
    this._hass = value;
    if (userContextChanged) {
      this._clearAdminRead();
      if (
        this._activeView === "administration" &&
        value.user?.is_admin === true
      ) {
        const router = this._currentRouter();
        if (router?.entry_state === "loaded") {
          this._loadAdminReadAndPage(router.entry_id);
        }
      }
    } else if (managementAvailabilityChanged) {
      this._clearAdminActionState();
      this._invalidateAdminPageSession();
    }
    if (firstAssignment) {
      this._loadPlatformIcons();
      this._loadMetadata();
    }
    if (shouldRender) {
      this._syncTrafficHistory();
      this._scheduleRender();
    }
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
    if (this._hass && (!this._platformIcons || !this._componentIcons)) {
      this._loadPlatformIcons();
    }
    if (
      this._activeView === "administration" &&
      this._hass?.user?.is_admin === true &&
      !this._adminRead
    ) {
      const entryId = this._currentRouter()?.entry_id;
      if (entryId) this._loadAdminReadAndPage(entryId);
    }
    if (!this._refreshTimer) {
      this._refreshTimer = window.setInterval(
        () => this._loadMetadata(),
        METADATA_REFRESH_INTERVAL_MS,
      );
    }
    this._syncTrafficHistory();
    this._render();
  }

  disconnectedCallback() {
    if (this._refreshTimer) window.clearInterval(this._refreshTimer);
    this._refreshTimer = undefined;
    if (this._renderFrame) window.cancelAnimationFrame(this._renderFrame);
    this._renderFrame = undefined;
    this._clearAdminRead();
    this._trafficHistory.dispose();
    this._clearTrafficBinding();
    this.shadowRoot.innerHTML = "";
  }

  _shouldRenderForHass(previous, next) {
    if (
      !previous ||
      !this._metadata ||
      previous.user?.id !== next.user?.id ||
      previous.user?.is_admin !== next.user?.is_admin ||
      previous.language !== next.language ||
      previous.locale !== next.locale
    ) {
      return true;
    }
    if (this._pendingAction) return false;
    const administrationActive = this._activeView === "administration";
    return this._metadata.routers.some((router) =>
      router.entities.some(
        (entity) => {
          if (
            previous.entities?.[entity.entity_id]?.icon !==
            next.entities?.[entity.entity_id]?.icon
          ) {
            return true;
          }
          const previousState = previous.states?.[entity.entity_id];
          const nextState = next.states?.[entity.entity_id];
          return administrationActive
            ? administrationEntityStateChanged(
                entity,
                previousState,
                nextState,
              )
            : previousState !== nextState;
        },
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

  async _loadPlatformIcons() {
    if (
      !this._hass ||
      this._platformIconsLoading ||
      (this._platformIcons && this._componentIcons)
    ) {
      return;
    }
    this._platformIconsLoading = true;
    try {
      const requests = [];
      if (!this._platformIcons) {
        requests.push(
          this._hass.connection
            .sendMessagePromise({
              type: "frontend/get_icons",
              category: "entity",
              integration: "speedport_smart",
            })
            .then((result) => {
              const icons = result?.resources?.speedport_smart;
              this._platformIcons =
                icons && typeof icons === "object" && !Array.isArray(icons)
                  ? icons
                  : {};
            }),
        );
      }
      if (!this._componentIcons) {
        requests.push(
          this._hass.connection
            .sendMessagePromise({
              type: "frontend/get_icons",
              category: "entity_component",
            })
            .then((result) => {
              const icons = result?.resources;
              this._componentIcons =
                icons && typeof icons === "object" && !Array.isArray(icons)
                  ? icons
                  : {};
            }),
        );
      }
      await Promise.allSettled(requests);
    } finally {
      this._platformIconsLoading = false;
      if (!this._pendingAction) this._render();
    }
  }

  async _loadMetadata() {
    if (!this._hass || this._loading) return;
    if (!this._platformIcons || !this._componentIcons) {
      this._loadPlatformIcons();
    }
    this._loading = true;
    const recoveringMetadata = Boolean(this._loadError);
    this._loadError = "";
    try {
      const previousRouter = this._currentRouter();
      const previousPageSettings = new Set(adminPageSettings(
        this._currentAdminPage().page, previousRouter?.settings || [], SETTINGS_FEATURE_LINKS,
      ).filter((setting) => setting.supported && setting.available).map((setting) => setting.id));
      const previousActionGeneration = this._adminActionGeneration(previousRouter);
      const previousManagementAvailable = this._adminManagementAvailable(
        this._hass,
        previousRouter,
      );
      const metadata = await this._hass.connection.sendMessagePromise({
        type: API_TYPE,
      });
      if (
        metadata?.schema_version !== PANEL_SCHEMA_VERSION ||
        !Array.isArray(metadata?.routers)
      ) {
        throw new Error("Unsupported dashboard metadata");
      }
      const previousEntry = this._selectedEntry;
      this._metadata = metadata;
      const entryIds = new Set(metadata.routers.map((router) => router.entry_id));
      if (!this._selectedEntry || !entryIds.has(this._selectedEntry)) {
        this._selectedEntry = metadata.routers[0]?.entry_id;
      }
      const selectedRouter = metadata.routers.find(
        (candidate) => candidate.entry_id === this._selectedEntry,
      );
      const selectionChanged = previousEntry !== this._selectedEntry;
      const selectedEntryLoaded = selectedRouter?.entry_state === "loaded";
      const actionSessionChanged = Boolean(
        previousRouter &&
          selectedRouter &&
          previousRouter.entry_id === selectedRouter.entry_id &&
          (previousActionGeneration !==
            this._adminActionGeneration(selectedRouter) ||
            previousManagementAvailable !==
              this._adminManagementAvailable(this._hass, selectedRouter)),
      );
      if (selectionChanged || !selectedEntryLoaded) {
        this._clearAdminRead();
      } else if (actionSessionChanged) {
        this._clearAdminActionState();
        this._invalidateAdminPageSession();
      }
      if (
        selectedEntryLoaded &&
        (selectionChanged || previousRouter?.entry_state !== "loaded" || recoveringMetadata) &&
        this._activeView === "administration" &&
        this._hass?.user?.is_admin === true &&
        this._selectedEntry
      ) {
        this._loadAdminReadAndPage(this._selectedEntry);
      } else if (!actionSessionChanged && selectedEntryLoaded &&
          adminPageSettingSections(this._currentAdminPage().page, selectedRouter.settings || [], SETTINGS_FEATURE_LINKS).inline
            .some((setting) => setting.supported && setting.available && !previousPageSettings.has(setting.id) &&
              !this._settingsEditors.has(setting.id))) {
        // Add only newly available page sections; keep existing revisions and
        // drafts, including failed editors awaiting an explicit Refresh.
        this._queueAdminPageRecovery({allowExisting: true});
      }
    } catch (_error) {
      this._clearAdminRead();
      this._loadError = "error.metadata_unavailable";
    } finally {
      this._loading = false;
      this._syncTrafficHistory();
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

  _syncTrafficHistory() {
    const router = this._currentRouter();
    const userId = this._hass?.user?.id;
    if (!this.isConnected || this._activeView !== "dashboard" || !router || router.entry_state !== "loaded" || !userId ||
        typeof this._hass?.connection?.sendMessagePromise !== "function") {
      this._trafficHistory.dispose();
      this._clearTrafficBinding();
      return;
    }
    const entities = Object.fromEntries(["download", "upload"].map((direction) => [direction,
      router.entities?.find((meta) => meta.domain === "sensor" && !meta.disabled_by && !meta.disabled &&
        !meta.child_device && !meta.control && !meta.control_supported && /^sensor\.[a-z0-9_]+$/.test(meta.entity_id) &&
        meta.translation_key === `wan_${direction}_rate`)?.entity_id ?? null,
    ]));
    const scope = JSON.stringify([router.entry_id, userId, entities.download, entities.upload]);
    if (this._trafficScope !== scope) {
      this._clearTrafficBinding();
      this._trafficScope = scope;
    }
    const source = liveWanSourceFromEntityStates(
      router.access_sources?.find((item) => item.id === "wan_counters"), router.entities, this._hass.states,
    );
    const sampleMeta = router.entities?.find((meta) => meta.translation_key === "wan_last_sample");
    // The diagnostic sensor is minute-rounded. Prefer the newest real sample
    // from either source, never a render-time heartbeat. HA can be slightly
    // ahead of the browser; preserve the actual clock within a bounded margin.
    const now = Date.now();
    const observationTimes = [source?.last_sampled_at,
      sampleMeta ? this._hass.states?.[sampleMeta.entity_id]?.state : undefined]
      .map((value) => typeof value === "string" ? Date.parse(value) : NaN)
      .filter((time) => Number.isFinite(time) && time <= now + LIVE_TRAFFIC_CLOCK_SKEW_MS);
    const sampledAt = observationTimes.length ? Math.max(...observationTimes) : undefined;
    this._trafficHistory.open({entryId: router.entry_id, userId, entities, states: this._hass.states,
      stale: source?.available === false || source?.retrying === true || source?.state === "cooldown" || source?.supported === false,
      staleAfterMs: Math.max(30000, (Number(source?.effective_interval_seconds) || 10) * 4000), sampledAt,
    });
  }

  _clearTrafficBinding() {
    this._trafficWindowRenderPending = false;
    this._trafficBinding?.();
    this._trafficBinding = undefined;
    this._trafficScope = undefined;
    if (this._trafficHost) this._trafficHost.innerHTML = "";
    this._trafficHost = undefined;
  }

  _canShowAdministration(router = this._currentRouter()) {
    return (
      this._hass?.user?.is_admin === true ||
      splitPanelEntities(router?.entities).controls.length > 0
    );
  }

  _adminManagementAvailable(hass, router = this._currentRouter()) {
    const managementMeta = router?.entities?.find(
      (entity) => entity.translation_key === "management_access",
    );
    const entityState = managementMeta
      ? hass?.states?.[managementMeta.entity_id]?.state
      : undefined;
    return (
      router?.management?.controls_available === true &&
      (entityState || router?.management?.state) === "available"
    );
  }

  _adminActionGeneration(router = this._currentRouter()) {
    const generation = router?.management?.generation;
    return Number.isSafeInteger(generation) && generation >= 0
      ? generation
      : undefined;
  }

  _clearAdminRead() {
    this._adminPageEpoch += 1;
    this._adminRecoverySelection = undefined;
    this._adminRecoverySelections.clear();
    this._clearSettingsEditor();
    this._invalidateAdminReadSnapshot();
    this._clearAdminPrivateQueries();
    this._clearAdminActionState();
  }

  _invalidateAdminReadSnapshot() {
    this._adminReadRequest += 1;
    this._adminRead = undefined;
    this._adminReadEntry = undefined;
    this._adminReadLoading = false;
    this._adminReadError = "";
    this._adminReadRefreshPending = undefined;
  }

  _clearAdminPrivateQueries() {
    this._adminPrivateQueryEpoch += 1;
    this._adminPrivateQueries = emptyAdminPrivateQueryState();
    this._focusAfterPrivateQuery = undefined;
  }

  _clearAdminActionState() {
    this._adminActionEpoch += 1;
    this._adminActionState = emptyAdminActionState();
    this._focusAfterAdminAction = undefined;
    if (this._pendingAction?.source === "admin_action") {
      this._pendingAction = undefined;
      this._actionBusy = false;
    }
  }

  _requestPrivate(message) {
    if (this._hass?.user?.is_admin !== true || this._activeView !== "administration" ||
        message?.entry_id !== this._currentRouter()?.entry_id) {
      return Promise.reject(new Error("administrator_required"));
    }
    const epoch = this._adminPageEpoch;
    const userId = this._hass.user?.id;
    const current = () => {
      if ((message.type !== ADMIN_READ_API_TYPE && epoch !== this._adminPageEpoch) || this._hass?.user?.id !== userId ||
          this._hass?.user?.is_admin !== true || this._activeView !== "administration" ||
          this.isConnected === false ||
          message.entry_id !== this._currentRouter()?.entry_id) throw new Error("administrator_required");
    };
    const run = this._privateRequestQueue.then(async () => {
      current();
      const paced = message.type === "speedport_smart/panel/settings/read" ? "read" :
        message.type === "speedport_smart/panel/settings/targets" ? "targets" :
          message.type === "speedport_smart/panel/call_history" ? "callHistory" :
            message.type === "speedport_smart/panel/ip_information" ? "read" : null;
      if (paced) {
        const delay = this._privateReadReadyAt[paced] - this._privateReadNow();
        if (delay > 0) await this._privateReadWait(delay);
        current();
        if (this._configurationSaving() || this._actionBusy || this._maintenanceEditor.snapshot()?.busy ||
            this._fileTransferEditor.snapshot()?.busy) throw new Error("action_busy");
      }
      try {
        return await requestPrivateApi(this._hass, message);
      } finally {
        if (paced) this._privateReadReadyAt[paced] = this._privateReadNow() + 1000;
      }
    });
    // The queue retains completion only, never a private response/credential.
    this._privateRequestQueue = run.then(() => undefined, () => undefined);
    return run;
  }

  async _loadAdminRead(entryId, { force = false } = {}) {
    if (
      this._hass?.user?.is_admin !== true ||
      !entryId ||
      this._currentRouter()?.entry_id !== entryId ||
      (!force && this._adminReadEntry === entryId && this._adminRead)
    ) {
      return;
    }
    if (this._adminReadLoading) {
      if (force) this._adminReadRefreshPending = entryId;
      return;
    }

    const request = ++this._adminReadRequest;
    if (this._adminReadRefreshPending === entryId) {
      this._adminReadRefreshPending = undefined;
    }
    this._adminReadLoading = true;
    this._adminReadError = "";
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: ADMIN_READ_API_TYPE,
        entry_id: entryId,
      });
      if (
        request !== this._adminReadRequest ||
        this._currentRouter()?.entry_id !== entryId
      ) {
        return;
      }
      const normalized = normalizeAdminReadPayload(payload, entryId);
      if (!normalized) throw new Error("Unsupported administrator data");
      this._adminRead = normalized;
      this._adminReadEntry = entryId;
    } catch (_error) {
      if (
        request === this._adminReadRequest &&
        this._currentRouter()?.entry_id === entryId
      ) {
        this._adminReadError = "error.admin_read_unavailable";
      }
    } finally {
      let refreshPending = false;
      if (request === this._adminReadRequest) {
        this._adminReadLoading = false;
        refreshPending = this._adminReadRefreshPending === entryId;
        this._adminReadRefreshPending = undefined;
        if (!this._pendingAction) this._render();
      }
      if (
        refreshPending &&
        this._activeView === "administration" &&
        this._hass?.user?.is_admin === true &&
        this._currentRouter()?.entry_id === entryId
      ) {
        await this._loadAdminRead(entryId, { force: true });
      }
    }
  }

  _selectRouter(entryId) {
    if (!entryId || entryId === this._selectedEntry) return;
    if (!this._canLeaveAdminPage()) return;
    this._clearAdminRead();
    this._selectedEntry = entryId;
    this._syncTrafficHistory();
    this._pendingAction = undefined;
    this._notice = "";
    this._noticeKind = "status";
    if (
      this._activeView === "administration" &&
      this._hass?.user?.is_admin === true
    ) {
      this._loadAdminReadAndPage(entryId);
    } else {
      this._render();
    }
  }

  _selectView(view) {
    if (
      !["dashboard", "administration"].includes(view) ||
      (view === "administration" && !this._canShowAdministration())
    ) {
      return;
    }
    if (view !== this._activeView && !this._canLeaveAdminPage()) return;
    const previousView = this._activeView;
    this._activeView = view;
    this._syncTrafficHistory();
    this._notice = "";
    if (view !== "administration") {
      this._adminPageEpoch += 1;
      this._adminRecoverySelection = undefined;
      this._adminRecoverySelections.clear();
      this._clearSettingsEditor();
      this._clearAdminPrivateQueries();
      this._clearAdminActionState();
    }
    // Switch the visible panel immediately. A cached administrator snapshot must
    // never make `_loadAdminRead` short-circuit before the selected tab renders.
    this._render();
    if (view === "administration" && this._hass?.user?.is_admin === true) {
      const entryId = this._currentRouter()?.entry_id;
      if (entryId) {
        const cachedForEntry =
          this._adminReadEntry === entryId && Boolean(this._adminRead);
        if (previousView !== "administration") {
          this._loadAdminReadAndPage(entryId, {force: cachedForEntry});
        } else {
          this._loadAdminRead(entryId);
        }
      }
    }
  }

  _currentAdminPage() {
    return resolveAdminPage(this._adminTab, this._adminPage);
  }

  async _loadAdminReadAndPage(entryId, options) {
    if (this.isConnected === false) return;
    const epoch = this._adminPageEpoch;
    const userId = this._hass?.user?.id;
    try {
      await this._loadAdminRead(entryId, options);
      if (this.isConnected !== false && epoch === this._adminPageEpoch && userId === this._hass?.user?.id &&
          this._activeView === "administration" && this._hass?.user?.is_admin === true &&
          this._currentRouter()?.entry_id === entryId) await this._loadAdminPage();
    } catch {
      // Render a bounded fallback; never leak a private response or retry a write.
      if (this._currentRouter()?.entry_id === entryId && this._hass?.user?.id === userId) {
        this._notice = "Settings could not be loaded. Use Refresh to try reading them again.";
        this._render();
      }
    }
  }

  _queueAdminPageRecovery({allowExisting = false} = {}) {
    const epoch = this._adminPageEpoch;
    const entryId = this._currentRouter()?.entry_id;
    const userId = this._hass?.user?.id;
    if (this.isConnected === false || this._adminRecoveryEpoch === epoch || !this._adminManagementAvailable(this._hass) ||
        this._activeView !== "administration" || this._hass?.user?.is_admin !== true) return;
    const busy = () => this._configurationSaving() || this._actionBusy ||
      this._maintenanceEditor.snapshot()?.busy || this._fileTransferEditor.snapshot()?.busy;
    const defer = () => { this._adminPageRecoveryPending = {epoch, entryId, userId, allowExisting}; };
    // A new sibling becoming available must not advance the page epoch while a
    // write owns it. Retain only scope identifiers; drain after its outcome.
    if (busy()) { defer(); return; }
    this._adminRecoveryEpoch = epoch;
    // Coalesce session notifications, then recheck identity/page/access before
    // reading. Normal telemetry renders never trigger router configuration I/O.
    Promise.resolve().then(() => {
      if (this.isConnected === false || epoch !== this._adminPageEpoch || entryId !== this._currentRouter()?.entry_id ||
          userId !== this._hass?.user?.id || this._hass?.user?.is_admin !== true ||
          this._activeView !== "administration" || this._currentRouter()?.entry_state !== "loaded" ||
          !this._adminManagementAvailable(this._hass) || !allowExisting && this._configurationViews().length) return;
      if (busy()) { this._adminRecoveryEpoch = undefined; defer(); return; }
      if (this._maintenanceEditor.snapshot() || this._fileTransferEditor.snapshot()) return;
      return this._loadAdminPage();
    }).catch(() => {
      if (entryId === this._currentRouter()?.entry_id && userId === this._hass?.user?.id &&
          this._activeView === "administration") {
        this._notice = "Settings could not be loaded. Use Refresh to try reading them again.";
        this._render();
      }
    });
  }

  _flushAdminSessionInvalidation() {
    if (this._configurationSaving() || this._maintenanceEditor?.snapshot()?.busy ||
        this._fileTransferEditor?.snapshot()?.busy || this._actionBusy) return;
    const pending = this._adminSessionInvalidationPending;
    if (pending) {
      this._adminSessionInvalidationPending = undefined;
      this._invalidateAdminPageSession({preserve: pending});
      return;
    }
    const recovery = this._adminPageRecoveryPending;
    this._adminPageRecoveryPending = undefined;
    if (recovery && recovery.epoch === this._adminPageEpoch &&
        recovery.entryId === this._currentRouter()?.entry_id && recovery.userId === this._hass?.user?.id) {
      this._queueAdminPageRecovery({allowExisting: recovery.allowExisting});
    }
  }

  _invalidateAdminPageSession({preserve = new Set()} = {}) {
    // Never erase the outcome of a dispatched write. Idle private snapshots and
    // credentials belong to the old session; reload the visible page on recovery.
    if (this._configurationSaving() || this._maintenanceEditor?.snapshot()?.busy ||
        this._fileTransferEditor?.snapshot()?.busy || this._actionBusy) {
      const pending = this._adminSessionInvalidationPending ||= new Set();
      for (const editor of new Set([this._settingsEditor, ...[...this._settingsEditors.values()].map((record) => record.editor)])) {
        if (editor?.snapshot()?.isSaving) pending.add(editor);
      }
      if (this._maintenanceEditor?.snapshot()?.busy) pending.add(this._maintenanceEditor);
      if (this._fileTransferEditor?.snapshot()?.busy) pending.add(this._fileTransferEditor);
      return;
    }
    for (const selection of this._configurationViews()) {
      if ([...preserve].some((editor) => editor.snapshot()?.setting?.id === selection.setting.id)) continue;
      const pending = this._adminRecoverySelections.get(selection.setting.id) || this._adminRecoverySelection;
      const pageId = this._currentAdminPage().page.id;
      const recovery = {pageId,
        settingId: selection.setting.id, targetId: selection.targetId ??
          (pending?.pageId === pageId && pending.settingId === selection.setting.id ? pending.targetId : null)};
      this._adminRecoverySelections.set(selection.setting.id, recovery);
      if (selection.setting.id === this._settingsEditor.snapshot()?.setting.id) this._adminRecoverySelection = recovery;
      if (selection.isDirty) this._notice = "The router management session changed. Unsaved changes were discarded; current settings will load when access returns.";
    }
    this._adminPageEpoch += 1;
    this._clearSettingsEditor({preserve});
    this._clearAdminPrivateQueries();
    this._queueAdminPageRecovery({allowExisting: preserve.size > 0});
  }

  _canLeaveAdminPage() {
    if (this._actionBusy || this._configurationSaving() ||
        this._maintenanceEditor?.snapshot()?.busy || this._fileTransferEditor?.snapshot()?.busy) {
      this._notice = "Wait for the current router request to finish before leaving this page.";
      this._render();
      return false;
    }
    if (this._configurationViews().some((state) => state.isDirty || state.link || state.downloadAvailable) ||
        this._fileTransferEditor?.snapshot()?.filename) {
      return globalThis.confirm?.("Leave this page? Unsaved changes and temporary private data will be discarded.") !== false;
    }
    return true;
  }

  async _selectAdminPage(tabId, pageId) {
    if (this._activeView !== "administration" || !this._canLeaveAdminPage()) return;
    const {tab, page} = resolveAdminPage(tabId, pageId);
    const current = this._currentAdminPage();
    this._adminMenuOpen = false;
    if (current.tab.id === tab.id && current.page.id === page.id) {
      this._render();
      if (!this._configurationViews().length) await this._loadAdminPage();
      return;
    }
    this._adminPageEpoch += 1;
    this._adminRecoverySelection = undefined;
    this._adminRecoverySelections.clear();
    this._clearSettingsEditor();
    this._clearAdminPrivateQueries();
    this._clearAdminActionState();
    this._pendingAction = undefined;
    this._adminTab = tab.id;
    this._adminPage = page.id;
    this._notice = "";
    this._render();
    await this._loadAdminPage();
  }

  async _openAdminSetting(settingId, {targetId, recovering = false, inline = false, retry = false} = {}) {
    const router = this._currentRouter();
    const setting = router?.settings?.find((item) => item.id === settingId);
    if (this._activeView !== "administration" || this._hass?.user?.is_admin !== true ||
        this.isConnected === false || !setting?.supported || !setting.available ||
        this._configurationSaving() || this._actionBusy || this._maintenanceEditor.snapshot()?.busy ||
        this._fileTransferEditor.snapshot()?.busy) return;
    const existing = this._settingsEditors.get(settingId);
    if (existing?.error && retry) {
      existing.binding?.(); existing.editor.dispose();
      this._settingsEditors.delete(settingId);
    }
    if (existing && !(existing.error && retry)) {
      if (!inline) this._settingsEditor = existing.editor;
      if (targetId != null && targetId !== existing.editor.snapshot()?.targetId) await existing.editor.selectTarget(targetId);
      existing.host?.scrollIntoView?.({block: "nearest"});
      return;
    }
    const editor = this._newConfigurationEditor();
    this._settingsEditors.set(settingId, {editor, inline, host: undefined, binding: undefined});
    if (!inline || !this._settingsEditor.snapshot() ||
        recovering && this._adminRecoverySelection?.settingId === settingId) this._settingsEditor = editor;
    if (!recovering) {
      this._adminRecoverySelections.delete(settingId);
      if (this._adminRecoverySelection?.settingId === settingId) this._adminRecoverySelection = undefined;
    }
    this._render();
    try {
      await editor.open({entryId: router.entry_id, setting, autoLoad: true, targetId});
    } catch (error) {
      const record = this._settingsEditors.get(settingId);
      if (record?.editor === editor) record.error = true;
      throw error;
    }
    this._render();
  }

  _loadAdminPage() {
    if (this._adminPageLoad?.epoch === this._adminPageEpoch) return this._adminPageLoad.promise;
    const task = {epoch: this._adminPageEpoch + 1, promise: null};
    this._adminPageLoad = task;
    task.promise = this._loadAdminPageSections().finally(() => {
      if (this._adminPageLoad === task) this._adminPageLoad = undefined;
    });
    return task.promise;
  }

  async _loadAdminPageSections() {
    const router = this._currentRouter();
    if (this.isConnected === false || this._activeView !== "administration" || this._hass?.user?.is_admin !== true || !router) return;
    const epoch = ++this._adminPageEpoch;
    const {page} = this._currentAdminPage();
    const current = () => epoch === this._adminPageEpoch && this._activeView === "administration" &&
      this._currentRouter()?.entry_id === router.entry_id && this.isConnected !== false &&
      this._hass?.user?.is_admin === true && this._currentRouter()?.entry_state === "loaded";
    const settings = adminPageSettings(page, router.settings || [], SETTINGS_FEATURE_LINKS);
    const {inline} = adminPageSettingSections(page, router.settings || [], SETTINGS_FEATURE_LINKS);
    const jobs = [...inline];
    for (const setting of settings) {
      if (this._adminRecoverySelections.get(setting.id)?.pageId === page.id && !jobs.some((item) => item.id === setting.id)) jobs.push(setting);
    }
    for (const setting of jobs) {
      if (!current()) return;
      if (!setting.supported || !setting.available || this._settingsEditors.has(setting.id)) continue;
      const resume = this._adminRecoverySelections.get(setting.id);
      try {
        await this._openAdminSetting(setting.id, {targetId: resume?.targetId,
          recovering: Boolean(resume), inline: inline.some((item) => item.id === setting.id)});
      } catch {
        if (current()) {
          this._notice = "Settings could not be loaded. Use Refresh to try reading them again.";
          this._render();
        }
      }
      if (!current()) return;
      const loaded = this._settingsEditors.get(setting.id)?.editor.snapshot();
      if (this._adminRecoverySelections.get(setting.id) === resume && loaded?.loaded &&
          (resume?.targetId == null || loaded.targetId === resume.targetId)) {
        this._adminRecoverySelections.delete(setting.id);
        if (this._adminRecoverySelection === resume) this._adminRecoverySelection = undefined;
      }
    }
    if (!current()) return;
    if (page.id === "internet_ip_information" && !this._adminPrivateQueries.ip.attempted) {
      await this._runIpInformationQuery();
      if (!current()) return;
    }
    // Read inventories only after page entry; never from telemetry rendering.
    for (const feature of adminPageFeatures(page, ADMIN_IA)) {
      for (const actionId of feature.adminActions) {
        if (!current()) return;
        if (actionId === "dect_handset_set_paging") await this._loadDectHandsetTargets();
        else if (actionId === "voip_line_set_active") await this._loadVoipLineTargets();
        else if (ADMIN_ACTION_INFO[actionId]?.risk === "destructive") {
          await this._loadDestructiveAdminActionTargets(actionId);
        }
      }
    }
    const category = this._adminCallHistoryCategory();
    const history = this._callHistoryView.snapshot();
    if (category && current() && (history?.entryId !== router.entry_id || history.category !== category)) {
      this._callHistoryView.open({entryId: router.entry_id, category});
      await this._callHistoryView.load();
    }
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

  _controlUnavailableReason(meta, state) {
    const router = this._currentRouter();
    const managementMeta = router?.entities?.find(
      (entity) => entity.translation_key === "management_access",
    );
    const managementState = this._state(managementMeta);
    return controlUnavailableReason(
      meta,
      state,
      managementState?.state || router?.management?.state,
      managementState?.attributes?.controls_available ??
        router?.management?.controls_available,
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

    if (target.dataset.adminTab) {
      return this._selectAdminPage(target.dataset.adminTab);
    }
    if (target.dataset.adminPage) {
      return this._selectAdminPage(this._adminTab, target.dataset.adminPage);
    }
    if (target.dataset.adminMenu !== undefined) {
      this._adminMenuOpen = !this._adminMenuOpen;
      this._render();
      return;
    }
    if (target.dataset.loadAdminPage !== undefined) {
      this._loadAdminPage();
      return;
    }
    if (target.dataset.retrySetting) {
      return this._openAdminSetting(target.dataset.retrySetting, {retry: true, inline: true}).catch(() => {
        this._notice = "Settings could not be loaded. Use Refresh to try reading them again.";
        this._render();
      });
    }

    if (target.dataset.openTransfer) {
      const router = this._currentRouter();
      const action = router?.file_transfers?.find((item) => item.id === target.dataset.openTransfer);
      if (this._activeView === "administration" && this._hass?.user?.is_admin === true &&
          action?.supported && action.available && this._canLeaveAdminPage()) {
        this._adminPageEpoch += 1;
        this._adminRecoverySelection = undefined;
        this._adminRecoverySelections.clear();
        this._clearSettingsEditor();
        this._fileTransferEditor.open({entryId: router.entry_id, action});
        this._fileTransferHost?.scrollIntoView?.({block: "nearest", behavior: "smooth"});
      }
      return;
    }

    if (target.dataset.openMaintenance) {
      const router = this._currentRouter();
      const action = router?.admin_actions?.find((item) =>
        item.id === target.dataset.openMaintenance && item.execution_policy === "maintenance");
      if (this._activeView === "administration" && this._hass?.user?.is_admin === true &&
          action?.supported && action.available && this._canLeaveAdminPage()) {
        this._adminPageEpoch += 1;
        this._adminRecoverySelection = undefined;
        this._adminRecoverySelections.clear();
        this._clearSettingsEditor();
        this._maintenanceEditor.open({entryId: router.entry_id, action});
        this._maintenanceHost?.scrollIntoView?.({block: "nearest", behavior: "smooth"});
      }
      return;
    }

    if (target.dataset.openSetting) {
      const router = this._currentRouter();
      const setting = router?.settings?.find((item) => item.id === target.dataset.openSetting);
      if (this._hass?.user?.is_admin === true && setting?.supported && setting.available) {
        return this._openAdminSetting(setting.id);
      }
      return;
    }
    if (target.dataset.openCallHistory) {
      const router = this._currentRouter();
      if (this._hass?.user?.is_admin === true && this._activeView === "administration" &&
          router?.entry_state === "loaded") {
        this._callHistoryView.open({entryId: router.entry_id, category: this._adminCallHistoryCategory() || "taken"});
        this._callHistoryHost?.scrollIntoView?.({block: "nearest", behavior: "smooth"});
      }
      return;
    }

    if (target.dataset.adminQueryClear) {
      this._clearAdminPrivateQueryResult(target.dataset.adminQueryClear);
      return;
    }
    if (target.dataset.refreshIpInformation !== undefined) {
      return this._runIpInformationQuery();
    }
    if (target.dataset.phonebookContact) {
      this._runPhonebookContactQuery(target.dataset.phonebookContact);
      return;
    }

    if (target.dataset.router) {
      this._selectRouter(target.dataset.router);
      return;
    }
    if (target.dataset.view) {
      this._selectView(target.dataset.view);
      return;
    }
    if (target.dataset.adminRefresh !== undefined) {
      const entryId = this._currentRouter()?.entry_id;
      if (entryId && this._hass?.user?.is_admin === true) {
        this._loadAdminRead(entryId, { force: true });
      }
      return;
    }
    if (target.dataset.adminActionTargetsRefresh !== undefined) {
      this._loadDectHandsetTargets({ force: true });
      return;
    }
    if (target.dataset.adminActionLinesRefresh !== undefined) {
      this._loadVoipLineTargets({ force: true });
      return;
    }
    if (target.dataset.adminDestructiveTargetsRefresh) {
      this._loadDestructiveAdminActionTargets(
        target.dataset.adminDestructiveTargetsRefresh,
        { force: true },
      );
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
    if (target.dataset.adminAction) {
      this._prepareAdminAction(
        target.dataset.adminAction,
        target.dataset.adminTargetToken,
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
    if (this._handleAdminPrivateQueryInput(event)) return;
    const target = event.target;
    if (!target?.dataset) {
      return;
    }
    if (target.dataset.adminActionPhonebookId !== undefined) {
      const phonebookId = Number(target.value);
      if (Number.isInteger(phonebookId) && phonebookId >= 0 && phonebookId <= 5) {
        this._adminActionState.phonebookId = phonebookId;
        this._resetDestructiveActionTargets("phonebook_entry_delete");
        this._loadDestructiveAdminActionTargets("phonebook_entry_delete");
      }
      return;
    }
    const pending = this._pendingAction;
    if (!pending) return;
    if (
      pending.source === "admin_action" &&
      target.dataset.repeaterPrerequisite !== undefined
    ) {
      const prerequisite = target.dataset.repeaterPrerequisite;
      if (
        ![
          "pinIsDefault",
          "fullPowerEnabled",
          "fullEcoDisabled",
        ].includes(prerequisite)
      ) {
        return;
      }
      pending[prerequisite] = target.checked === true;
      const button = this.shadowRoot.querySelector("[data-confirm-action]");
      if (button) {
        button.disabled =
          this._actionBusy ||
          !pending.pinIsDefault ||
          !pending.fullPowerEnabled ||
          !pending.fullEcoDisabled;
      }
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

  _handleToggle(event) {
    const target = event.target;
    if (target?.open !== true) return;
    const actionId = ADMIN_ACTION_BY_FEATURE_ID.get(target.dataset?.adminFeature);
    if (actionId === "dect_handset_set_paging") {
      this._loadDectHandsetTargets();
    } else if (actionId === "voip_line_set_active") {
      this._loadVoipLineTargets();
    } else if (ADMIN_ACTION_INFO[actionId]?.risk === "destructive") {
      this._loadDestructiveAdminActionTargets(actionId);
    }
  }

  _handleSubmit(event) {
    const form = event.target?.closest?.("[data-admin-query-form]");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.adminQueryForm === "ip_pbx_refresh") {
      this._runIpPbxQuery();
    } else if (form.dataset.adminQueryForm === "phonebook_search") {
      this._runPhonebookSearchQuery();
    }
  }

  _handleAdminPrivateQueryInput(event) {
    const input = event.target;
    const field = input?.dataset?.adminQueryInput;
    if (!field) return false;
    if (field === "pbx-client-id") {
      this._adminPrivateQueries.pbx.clientId = String(input.value ?? "").slice(
        0,
        33,
      );
      this._adminPrivateQueries.pbx.errorKey = "";
    } else if (field === "phonebook-id") {
      const value = Number(input.value);
      this._adminPrivateQueries.phonebook.phonebookId =
        adminPrivateQueryPhonebookId(value) ?? -1;
      this._adminPrivateQueries.phonebook.searchErrorKey = "";
    } else if (field === "phonebook-prefix") {
      this._adminPrivateQueries.phonebook.prefix = String(
        input.value ?? "",
      ).slice(0, 2);
      this._adminPrivateQueries.phonebook.searchErrorKey = "";
    } else {
      return false;
    }
    input.removeAttribute?.("aria-invalid");
    const error = this.shadowRoot.querySelector?.(
      `[data-admin-query-input-error="${field}"]`,
    );
    if (error) error.textContent = "";
    return true;
  }

  _adminPrivateQueryCapabilityObserved(query) {
    const router = this._currentRouter();
    if (query === "ip_information") return router?.entry_state === "loaded";
    const capabilities = new Set([
      ...(router?.capabilities || []).map((capability) =>
        String(capability).toLowerCase(),
      ),
      ...(router?.capability_families || []).map((family) =>
        String(family?.name || "").toLowerCase(),
      ),
    ]);
    const requiredCapability =
      query === "ip_pbx_refresh"
        ? "pbx_clients"
        : ["phonebook_search", "phonebook_contact"].includes(query)
          ? "phonebook"
          : undefined;
    return (
      requiredCapability !== undefined &&
      capabilities.has(requiredCapability)
    );
  }

  _adminPrivateQueryAvailable(query) {
    const router = this._currentRouter();
    const protectedSource = router?.access_sources?.find(
      (source) => source.id === "protected_json",
    );
    return (
      this._adminPrivateQueryCapabilityObserved(query) &&
      this._activeView === "administration" &&
      this._hass?.user?.is_admin === true &&
      router?.entry_state === "loaded" &&
      router?.management?.state === "available" &&
      protectedSource?.supported !== false &&
      protectedSource?.available !== false
    );
  }

  _adminPrivateQueryErrorKey(error) {
    return error?.code === "rate_limited"
      ? "admin.query.error.rate_limited"
      : "admin.query.error.unavailable";
  }

  _adminPrivateQueryContextIsCurrent(entryId, epoch) {
    return (
      epoch === this._adminPrivateQueryEpoch &&
      this._activeView === "administration" &&
      this._hass?.user?.is_admin === true &&
      this._currentRouter()?.entry_id === entryId
    );
  }

  async _runIpInformationQuery() {
    const state = this._adminPrivateQueries.ip;
    if (state.loading || this._currentAdminPage().page.id !== "internet_ip_information" ||
        !this._adminPrivateQueryAvailable("ip_information") || this.isConnected === false) return;
    const entryId = this._currentRouter().entry_id;
    const epoch = this._adminPrivateQueryEpoch, pageEpoch = this._adminPageEpoch;
    const userId = this._hass.user.id;
    const current = () => this._adminPrivateQueryContextIsCurrent(entryId, epoch) &&
      this._adminPageEpoch === pageEpoch && this._hass?.user?.id === userId &&
      this.isConnected !== false && this._currentRouter()?.entry_state === "loaded" &&
      this._currentAdminPage().page.id === "internet_ip_information";
    state.attempted = true; state.loading = true; state.errorKey = ""; state.result = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({type: ADMIN_PRIVATE_QUERY_API_TYPES.ip_information, entry_id: entryId});
      if (!current()) return;
      const result = normalizeAdminPrivateQueryPayload(payload, "ip_information");
      if (!result) throw new Error("invalid_response");
      state.result = result;
    } catch (error) {
      if (current()) state.errorKey = this._adminPrivateQueryErrorKey(error);
    } finally {
      if (current()) {state.loading = false; this._render();}
    }
  }

  async _runIpPbxQuery() {
    const state = this._adminPrivateQueries.pbx;
    if (state.loading) return;
    const expected = { clientId: state.clientId };
    const inputError = adminPrivateQueryInputError("ip_pbx_refresh", expected);
    if (inputError || !this._adminPrivateQueryAvailable("ip_pbx_refresh")) {
      state.errorKey = inputError || "admin.query.error.unavailable";
      state.result = undefined;
      this._render();
      return;
    }
    const entryId = this._currentRouter().entry_id;
    const epoch = this._adminPrivateQueryEpoch;
    const request = ++state.request;
    state.errorKey = "";
    state.loading = true;
    state.result = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: ADMIN_PRIVATE_QUERY_API_TYPES.ip_pbx_refresh,
        entry_id: entryId,
        client_id: expected.clientId,
      });
      if (
        !this._adminPrivateQueryContextIsCurrent(entryId, epoch) ||
        request !== this._adminPrivateQueries.pbx.request
      ) {
        return;
      }
      const result = normalizeAdminPrivateQueryPayload(
        payload,
        "ip_pbx_refresh",
        expected,
      );
      if (!result) throw new Error("Unsupported private query response");
      state.result = result;
      this._focusAfterPrivateQuery = "ip_pbx_refresh";
    } catch (error) {
      if (this._adminPrivateQueryContextIsCurrent(entryId, epoch)) {
        state.errorKey = this._adminPrivateQueryErrorKey(error);
      }
    } finally {
      if (
        this._adminPrivateQueryContextIsCurrent(entryId, epoch) &&
        request === this._adminPrivateQueries.pbx.request
      ) {
        state.loading = false;
        this._render();
      }
    }
  }

  async _runPhonebookSearchQuery() {
    const state = this._adminPrivateQueries.phonebook;
    if (state.searchLoading) return;
    const expected = {
      phonebookId: state.phonebookId,
      prefix: state.prefix,
    };
    const inputError = adminPrivateQueryInputError("phonebook_search", expected);
    if (inputError || !this._adminPrivateQueryAvailable("phonebook_search")) {
      state.searchErrorKey = inputError || "admin.query.error.unavailable";
      state.searchResult = undefined;
      state.contactResult = undefined;
      this._render();
      return;
    }
    const entryId = this._currentRouter().entry_id;
    const epoch = this._adminPrivateQueryEpoch;
    const request = ++state.searchRequest;
    state.contactRequest += 1;
    state.searchErrorKey = "";
    state.searchLoading = true;
    state.searchResult = undefined;
    state.contactErrorKey = "";
    state.contactLoading = false;
    state.contactResult = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: ADMIN_PRIVATE_QUERY_API_TYPES.phonebook_search,
        entry_id: entryId,
        phonebook_id: expected.phonebookId,
        prefix: expected.prefix,
      });
      if (
        !this._adminPrivateQueryContextIsCurrent(entryId, epoch) ||
        request !== this._adminPrivateQueries.phonebook.searchRequest
      ) {
        return;
      }
      const result = normalizeAdminPrivateQueryPayload(
        payload,
        "phonebook_search",
        expected,
      );
      if (!result) throw new Error("Unsupported private query response");
      state.searchResult = result;
      this._focusAfterPrivateQuery = "phonebook_search";
    } catch (error) {
      if (this._adminPrivateQueryContextIsCurrent(entryId, epoch)) {
        state.searchErrorKey = this._adminPrivateQueryErrorKey(error);
      }
    } finally {
      if (
        this._adminPrivateQueryContextIsCurrent(entryId, epoch) &&
        request === this._adminPrivateQueries.phonebook.searchRequest
      ) {
        state.searchLoading = false;
        this._render();
      }
    }
  }

  async _runPhonebookContactQuery(contactId) {
    const state = this._adminPrivateQueries.phonebook;
    const searchResult = state.searchResult;
    if (
      state.contactLoading ||
      !searchResult?.entries?.some((entry) => entry.contact_id === contactId)
    ) {
      return;
    }
    const expected = {
      phonebookId: searchResult.phonebook_id,
      contactId,
    };
    const inputError = adminPrivateQueryInputError("phonebook_contact", expected);
    if (inputError || !this._adminPrivateQueryAvailable("phonebook_contact")) {
      state.contactErrorKey = inputError || "admin.query.error.unavailable";
      state.contactResult = undefined;
      this._render();
      return;
    }
    const entryId = this._currentRouter().entry_id;
    const epoch = this._adminPrivateQueryEpoch;
    const request = ++state.contactRequest;
    state.contactErrorKey = "";
    state.contactLoading = true;
    state.contactResult = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: ADMIN_PRIVATE_QUERY_API_TYPES.phonebook_contact,
        entry_id: entryId,
        phonebook_id: expected.phonebookId,
        contact_id: expected.contactId,
      });
      if (
        !this._adminPrivateQueryContextIsCurrent(entryId, epoch) ||
        request !== this._adminPrivateQueries.phonebook.contactRequest
      ) {
        return;
      }
      const result = normalizeAdminPrivateQueryPayload(
        payload,
        "phonebook_contact",
        expected,
      );
      if (!result) throw new Error("Unsupported private query response");
      state.contactResult = result;
      this._focusAfterPrivateQuery = "phonebook_contact";
    } catch (error) {
      if (this._adminPrivateQueryContextIsCurrent(entryId, epoch)) {
        state.contactErrorKey = this._adminPrivateQueryErrorKey(error);
      }
    } finally {
      if (
        this._adminPrivateQueryContextIsCurrent(entryId, epoch) &&
        request === this._adminPrivateQueries.phonebook.contactRequest
      ) {
        state.contactLoading = false;
        this._render();
      }
    }
  }

  _clearAdminPrivateQueryResult(scope) {
    if (scope === "ip_pbx_refresh") {
      const state = this._adminPrivateQueries.pbx;
      state.request += 1;
      state.errorKey = "";
      state.loading = false;
      state.result = undefined;
    } else if (scope === "phonebook_contact") {
      const state = this._adminPrivateQueries.phonebook;
      state.contactRequest += 1;
      state.contactErrorKey = "";
      state.contactLoading = false;
      state.contactResult = undefined;
    } else if (scope === "phonebook_search") {
      const state = this._adminPrivateQueries.phonebook;
      state.searchRequest += 1;
      state.contactRequest += 1;
      state.searchErrorKey = "";
      state.searchLoading = false;
      state.searchResult = undefined;
      state.contactErrorKey = "";
      state.contactLoading = false;
      state.contactResult = undefined;
    } else {
      return;
    }
    this._focusAfterPrivateQuery = undefined;
    this._render();
  }

  _adminActionDescriptor(actionId) {
    if (this._hass?.user?.is_admin !== true) return undefined;
    return normalizeAdminActionMetadata(this._currentRouter()?.admin_actions).get(
      actionId,
    );
  }

  _adminActionContextIsCurrent(entryId, epoch, generation) {
    const currentGeneration = this._adminActionGeneration();
    return (
      epoch === this._adminActionEpoch &&
      this._activeView === "administration" &&
      this._hass?.user?.is_admin === true &&
      this._currentRouter()?.entry_id === entryId &&
      this._currentRouter()?.entry_state === "loaded" &&
      this._adminManagementAvailable(this._hass) &&
      currentGeneration !== undefined &&
      (generation === undefined || generation === currentGeneration)
    );
  }

  _adminActionErrorKey(error) {
    const code = error?.code;
    return [
      "action_unavailable",
      "confirmation_required",
      "action_busy",
      "action_rate_limited",
      "action_rejected",
      "action_failed",
      "action_outcome_unknown",
      "action_verification_failed",
    ].includes(code)
      ? `admin.action.error.${code}`
      : "admin.action.error.action_failed";
  }

  _adminActionUnavailableKey(reason) {
    return ADMIN_ACTION_UNAVAILABLE_REASONS.has(reason)
      ? `admin.action.unavailable.${reason}`
      : "admin.action.error.action_unavailable";
  }

  _resetAdminActionTargets(key) {
    const previousRequest = this._adminActionState[key]?.request || 0;
    const replacement = emptyAdminActionState()[key];
    replacement.request = previousRequest + 1;
    this._adminActionState[key] = replacement;
  }

  _currentAdminActionTargets(key) {
    const state = this._adminActionState[key];
    if (
      state?.result &&
      (state.generation !== this._adminActionGeneration() ||
        state.expiresAt <= this._adminActionNow())
    ) {
      this._resetAdminActionTargets(key);
      return this._adminActionState[key];
    }
    return state;
  }

  _resetDestructiveActionTargets(actionId) {
    const current = this._adminActionState.destructiveTargets[actionId];
    if (!current) return;
    const replacement = emptyAdminActionTargetState();
    replacement.request = current.request + 1;
    this._adminActionState.destructiveTargets[actionId] = replacement;
  }

  _currentDestructiveActionTargets(actionId) {
    const state = this._adminActionState.destructiveTargets[actionId];
    if (
      state?.result &&
      (state.generation !== this._adminActionGeneration() ||
        state.expiresAt <= this._adminActionNow())
    ) {
      this._resetDestructiveActionTargets(actionId);
      return this._adminActionState.destructiveTargets[actionId];
    }
    return state;
  }

  async _loadDectHandsetTargets({ force = false } = {}) {
    const actionId = "dect_handset_set_paging";
    const descriptor = this._adminActionDescriptor(actionId);
    const state = this._currentAdminActionTargets("handsetTargets");
    const entryId = this._currentRouter()?.entry_id;
    const generation = this._adminActionGeneration();
    if (
      !descriptor?.supported ||
      !descriptor.available ||
      !this._adminActionContextIsCurrent(entryId, this._adminActionEpoch) ||
      state.loading ||
      (!force && state.loaded)
    ) {
      return;
    }

    const epoch = this._adminActionEpoch;
    const request = ++state.request;
    state.errorKey = "";
    state.loading = true;
    if (force) state.result = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: DECT_HANDSET_TARGETS_API_TYPE,
        entry_id: entryId,
      });
      if (
        !this._adminActionContextIsCurrent(entryId, epoch, generation) ||
        request !== this._adminActionState.handsetTargets.request
      ) {
        return;
      }
      const result = normalizeDectHandsetTargets(payload);
      if (!result) throw new Error("Unsupported DECT handset targets");
      state.result = result;
      state.loaded = true;
      state.generation = generation;
      state.expiresAt =
        this._adminActionNow() + descriptor.target_token_ttl_seconds * 1_000;
    } catch (error) {
      if (this._adminActionContextIsCurrent(entryId, epoch, generation)) {
        state.errorKey =
          error?.code === "rate_limited"
            ? "admin.action.error.action_rate_limited"
            : "admin.action.targets_unavailable";
      }
    } finally {
      if (
        this._adminActionContextIsCurrent(entryId, epoch, generation) &&
        request === this._adminActionState.handsetTargets.request
      ) {
        state.loading = false;
        this._render();
      }
    }
  }

  async _loadVoipLineTargets({ force = false } = {}) {
    const actionId = "voip_line_set_active";
    const descriptor = this._adminActionDescriptor(actionId);
    const state = this._currentAdminActionTargets("voipLineTargets");
    const entryId = this._currentRouter()?.entry_id;
    const generation = this._adminActionGeneration();
    if (
      !descriptor?.supported ||
      !descriptor.available ||
      !this._adminActionContextIsCurrent(entryId, this._adminActionEpoch) ||
      state.loading ||
      (!force && state.loaded)
    ) {
      return;
    }

    const epoch = this._adminActionEpoch;
    const request = ++state.request;
    state.errorKey = "";
    state.loading = true;
    if (force) state.result = undefined;
    this._render();
    try {
      const payload = await this._requestPrivate({
        type: VOIP_LINE_TARGETS_API_TYPE,
        entry_id: entryId,
      });
      if (
        !this._adminActionContextIsCurrent(entryId, epoch, generation) ||
        request !== this._adminActionState.voipLineTargets.request
      ) {
        return;
      }
      const result = normalizeVoipLineTargets(payload);
      if (!result) throw new Error("Unsupported VoIP line targets");
      state.result = result;
      state.loaded = true;
      state.generation = generation;
      state.expiresAt =
        this._adminActionNow() + descriptor.target_token_ttl_seconds * 1_000;
    } catch (error) {
      if (this._adminActionContextIsCurrent(entryId, epoch, generation)) {
        state.errorKey =
          error?.code === "rate_limited"
            ? "admin.action.error.action_rate_limited"
            : "admin.action.targets_unavailable";
      }
    } finally {
      if (
        this._adminActionContextIsCurrent(entryId, epoch, generation) &&
        request === this._adminActionState.voipLineTargets.request
      ) {
        state.loading = false;
        this._render();
      }
    }
  }

  async _loadDestructiveAdminActionTargets(
    actionId,
    { force = false } = {},
  ) {
    const info = Object.hasOwn(ADMIN_ACTION_INFO, actionId)
      ? ADMIN_ACTION_INFO[actionId]
      : undefined;
    const descriptor = this._adminActionDescriptor(actionId);
    const state = this._currentDestructiveActionTargets(actionId);
    const entryId = this._currentRouter()?.entry_id;
    const generation = this._adminActionGeneration();
    if (
      info?.risk !== "destructive" ||
      !state ||
      !descriptor?.supported ||
      !descriptor.available ||
      !this._adminActionContextIsCurrent(entryId, this._adminActionEpoch) ||
      state.loading ||
      (!force && state.loaded)
    ) {
      return;
    }

    const epoch = this._adminActionEpoch;
    const request = ++state.request;
    state.errorKey = "";
    state.loading = true;
    if (force) state.result = undefined;
    this._render();
    const message = {
      type: `${API_TYPE}/action/${info.targetQuery}`,
      entry_id: entryId,
    };
    if (actionId === "phonebook_entry_delete") {
      message.phonebook_id = this._adminActionState.phonebookId;
    }
    try {
      const payload = await this._requestPrivate(message);
      if (
        !this._adminActionContextIsCurrent(entryId, epoch, generation) ||
        request !==
          this._adminActionState.destructiveTargets[actionId]?.request
      ) {
        return;
      }
      const result = normalizeDestructiveAdminActionTargets(payload, actionId);
      if (!result) throw new Error("Unsupported destructive action targets");
      state.result = result;
      state.loaded = true;
      state.generation = generation;
      state.expiresAt =
        this._adminActionNow() + descriptor.target_token_ttl_seconds * 1_000;
    } catch (error) {
      if (this._adminActionContextIsCurrent(entryId, epoch, generation)) {
        state.errorKey =
          error?.code === "rate_limited"
            ? "admin.action.error.action_rate_limited"
            : "admin.action.targets_unavailable";
      }
    } finally {
      if (
        this._adminActionContextIsCurrent(entryId, epoch, generation) &&
        request ===
          this._adminActionState.destructiveTargets[actionId]?.request
      ) {
        state.loading = false;
        this._render();
      }
    }
  }

  _adminActionTarget(actionId, targetToken) {
    if (actionId === "dect_handset_set_paging") {
      return this._currentAdminActionTargets(
        "handsetTargets",
      ).result?.targets.find(
        (target) => target.target_token === targetToken,
      );
    }
    if (actionId === "voip_line_set_active") {
      return this._currentAdminActionTargets(
        "voipLineTargets",
      ).result?.targets.find(
        (target) => target.target_token === targetToken,
      );
    }
    if (ADMIN_ACTION_INFO[actionId]?.risk === "destructive") {
      return this._currentDestructiveActionTargets(
        actionId,
      )?.result?.targets.find(
        (target) => target.target_token === targetToken,
      );
    }
    return undefined;
  }

  _prepareAdminAction(actionId, targetToken) {
    const info = Object.hasOwn(ADMIN_ACTION_INFO, actionId)
      ? ADMIN_ACTION_INFO[actionId]
      : undefined;
    const descriptor = this._adminActionDescriptor(actionId);
    const entryId = this._currentRouter()?.entry_id;
    if (
      !info ||
      !descriptor?.available ||
      !this._adminActionContextIsCurrent(entryId, this._adminActionEpoch)
    ) {
      this._notice = this._t(
        this._adminActionUnavailableKey(descriptor?.unavailable_reason),
      );
      this._noticeKind = "status";
      this._render();
      return;
    }

    let target;
    let observedActive;
    let expectedActive;
    if (info.targetQuery) {
      target = this._adminActionTarget(actionId, targetToken);
      if (!target) {
        this._notice = this._t("admin.action.error.action_unavailable");
        this._noticeKind = "status";
        this._render();
        return;
      }
      if (["dect_handset_set_paging", "voip_line_set_active"].includes(actionId)) {
        observedActive =
          actionId === "dect_handset_set_paging"
            ? target.paging
            : target.active;
        expectedActive = !observedActive;
      }
    }

    const targetLabel = target
      ? this._adminActionTargetLabel(actionId, target)
      : undefined;
    const confirmationPhrase =
      descriptor.confirmation === "typed"
        ? descriptor.typed_confirmation
        : undefined;
    if (descriptor.confirmation === "typed" && !confirmationPhrase) {
      this._notice = this._t("admin.action.error.action_unavailable");
      this._noticeKind = "status";
      this._render();
      return;
    }
    const actionLabelKey = expectedActive === false ? "stop" : "run";
    this._pendingAction = {
      source: "admin_action",
      actionId,
      entryId,
      targetToken,
      targetLabel,
      observedActive,
      expectedActive,
      generation: this._adminActionGeneration(),
      focusKey: `${actionId}:${targetToken || "global"}`,
      label: this._t(`admin.action.${actionId}.label`, {
        target: targetLabel || "",
      }),
      actionLabel: this._t(`admin.action.${actionId}.${actionLabelKey}`),
      message: this._t(`admin.action.${actionId}.confirm`, {
        target: targetLabel || "",
      }),
      recovery:
        info.risk === "destructive"
          ? this._t(`admin.action.${actionId}.recovery`)
          : undefined,
      disruptive: ["disruptive", "lockout", "destructive"].includes(
        descriptor.risk,
      ),
      kind: "admin_action",
      confirmationPhrase,
      confirmationDraft: "",
      confirmationPolicy: descriptor.confirmation,
      risk: descriptor.risk,
      confirmationError: false,
      pinIsDefault: actionId === "dect_repeater_enroll" ? false : undefined,
      fullPowerEnabled:
        actionId === "dect_repeater_enroll" ? false : undefined,
      fullEcoDisabled:
        actionId === "dect_repeater_enroll" ? false : undefined,
    };
    this._notice = "";
    this._noticeKind = "status";
    this._render();
  }

  async _runPendingAdminAction(pending) {
    const descriptor = this._adminActionDescriptor(pending.actionId);
    const info = Object.hasOwn(ADMIN_ACTION_INFO, pending.actionId)
      ? ADMIN_ACTION_INFO[pending.actionId]
      : undefined;
    const entryId = pending.entryId;
    const epoch = this._adminActionEpoch;
    if (
      !info ||
      !descriptor?.available ||
      descriptor.confirmation !== pending.confirmationPolicy ||
      descriptor.risk !== pending.risk ||
      (descriptor.typed_confirmation || undefined) !==
        pending.confirmationPhrase ||
      pending.generation !== this._adminActionGeneration() ||
      !this._adminActionContextIsCurrent(entryId, epoch)
    ) {
      this._pendingAction = undefined;
      this._focusAfterAdminAction = pending.focusKey;
      this._notice = this._t("admin.action.error.action_unavailable");
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
    if (
      pending.actionId === "dect_repeater_enroll" &&
      (!pending.pinIsDefault ||
        !pending.fullPowerEnabled ||
        !pending.fullEcoDisabled)
    ) {
      this._render();
      return;
    }

    let parameters = {};
    if (["dect_handset_set_paging", "voip_line_set_active"].includes(pending.actionId)) {
      const target = this._adminActionTarget(
        pending.actionId,
        pending.targetToken,
      );
      const currentActive =
        pending.actionId === "dect_handset_set_paging"
          ? target?.paging
          : target?.active;
      if (typeof currentActive !== "boolean" || currentActive !== pending.observedActive) {
        this._pendingAction = undefined;
        this._focusAfterAdminAction = pending.focusKey;
        this._notice = this._t("admin.action.error.action_unavailable");
        this._noticeKind = "status";
        this._render();
        return;
      }
      parameters =
        pending.actionId === "dect_handset_set_paging"
          ? {
              target_token: pending.targetToken,
              enabled: pending.expectedActive,
            }
          : {
              target_token: pending.targetToken,
              active: pending.expectedActive,
            };
    } else if (info.risk === "destructive") {
      const target = this._adminActionTarget(
        pending.actionId,
        pending.targetToken,
      );
      if (!target) {
        this._pendingAction = undefined;
        this._focusAfterAdminAction = pending.focusKey;
        this._notice = this._t("admin.action.error.action_unavailable");
        this._noticeKind = "status";
        this._render();
        return;
      }
      parameters = { target_token: pending.targetToken };
    } else if (pending.actionId === "dect_repeater_enroll") {
      parameters = {
        pin_is_default: true,
        full_power_enabled: true,
        full_eco_disabled: true,
      };
    }
    const message = adminActionRequest(
      pending.actionId,
      entryId,
      parameters,
      pending.confirmationPhrase,
    );
    if (!message) {
      this._pendingAction = undefined;
      this._notice = this._t("admin.action.error.action_unavailable");
      this._noticeKind = "status";
      this._render();
      return;
    }

    if (pending.actionId === "dect_handset_set_paging") {
      this._resetAdminActionTargets("handsetTargets");
    } else if (pending.actionId === "voip_line_set_active") {
      this._resetAdminActionTargets("voipLineTargets");
    } else if (info.risk === "destructive") {
      this._resetDestructiveActionTargets(pending.actionId);
    }
    this._clearAdminPrivateQueries();
    this._invalidateAdminReadSnapshot();

    this._actionBusy = true;
    this._render();
    try {
      const payload = await this._requestPrivate(message);
      if (
        !this._adminActionContextIsCurrent(entryId, epoch) ||
        this._pendingAction !== pending
      ) {
        return;
      }
      if (
        !normalizeAdminActionResult(
          payload,
          pending.actionId,
          pending.expectedActive,
        )
      ) {
        const error = new Error("Unverified administrator action response");
        error.code = "action_verification_failed";
        throw error;
      }
      this._pendingAction = undefined;
      this._focusAfterAdminAction = pending.focusKey;
      this._notice = this._t(`admin.action.${pending.actionId}.success`);
      this._noticeKind = "status";
    } catch (error) {
      if (this._adminActionContextIsCurrent(entryId, epoch)) {
        this._notice = this._t(this._adminActionErrorKey(error));
        this._noticeKind = "alert";
        this._pendingAction = undefined;
        this._focusAfterAdminAction = pending.focusKey;
      }
    } finally {
      if (this._adminActionContextIsCurrent(entryId, epoch)) {
        this._actionBusy = false;
        await this._loadAdminRead(entryId, { force: true });
        this._render();
      }
    }
  }

  _closeConfirmation() {
    if (this._pendingAction?.source === "admin_action") {
      this._focusAfterAdminAction = this._pendingAction.focusKey;
    } else {
      this._focusAfterRenderEntityId = this._pendingAction?.entityId;
    }
    this._pendingAction = undefined;
    this._render();
  }

  _prepareAction(entityId) {
    const meta = this._entityMetadata(entityId);
    const state = this._state(meta);
    if (!meta?.control || this._isControlUnavailable(meta, state)) {
      const unavailableReason = meta?.control
        ? this._controlUnavailableReason(meta, state)
        : undefined;
      this._notice =
        meta?.domain === "update" && state?.state !== "on"
          ? this._t("notice.firmware_current")
          : unavailableReason
            ? this._t(`control.unavailable_reason.${unavailableReason}`)
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
      meta.translation_key === "reconnect_internet"
    ) {
      message = this._t("confirm.reconnect");
    } else if (
      meta.domain === "button" &&
      meta.translation_key === "retry_protected_data"
    ) {
      actionLabel = this._t("action.retry_protected");
      message = this._t("confirm.retry");
    } else if (
      meta.domain === "button" &&
      meta.translation_key === "capture_read_only_inventory"
    ) {
      actionLabel = this._t("action.capture_inventory");
      message = this._t("confirm.capture_inventory");
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
    if (pending.source === "admin_action") {
      await this._runPendingAdminAction(pending);
      return;
    }
    const actionEntryId = this._currentRouter()?.entry_id;
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
      this._notice =
        meta.translation_key === "capture_read_only_inventory"
          ? this._t("notice.capture_inventory_success")
          : this._t("notice.action_success", {
              action: pending.actionLabel,
            });
      this._noticeKind = "status";
      this._pendingAction = undefined;
      this._focusAfterRenderEntityId = pending.entityId;
      const activeRouter = this._currentRouter();
      if (
        this._activeView === "administration" &&
        this._hass.user?.is_admin === true &&
        activeRouter?.entry_id === actionEntryId &&
        activeRouter.entry_state === "loaded"
      ) {
        await this._loadAdminRead(actionEntryId, { force: true });
      }
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
        ? this._t(telemetry.schedulerState === "cooldown" ? "status.telemetry_cooldown" : "status.telemetry_retrying")
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

  _renderRiskBadge(risk, { summary = false } = {}) {
    if (!ADMIN_RISK_ORDER.includes(risk)) return "";
    const label = this._t(`admin.risk.${risk}`);
    const ariaLabel = summary
      ? this._t("admin.risk.highest", { risk: label })
      : this._t("admin.risk.label", { risk: label });
    return `<span class="admin-risk-badge risk-${escapeHtml(risk)}" aria-label="${escapeHtml(ariaLabel)}">${escapeHtml(label)}</span>`;
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
    const icon = iconFor(
      meta,
      state,
      this._platformIcons,
      this._componentIcons,
      this._hass?.entities,
    );
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
        : meta.domain === "button" &&
            meta.translation_key === "capture_read_only_inventory"
          ? this._t("action.capture_inventory_short")
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
    const riskBadge = isSemanticControl(meta)
      ? this._renderRiskBadge(meta.risk)
      : "";
    const unavailableReason = controlUnavailable
      ? this._controlUnavailableReason(meta, state)
      : undefined;
    const unavailableMessage = unavailableReason
      ? this._t(`control.unavailable_reason.${unavailableReason}`)
      : this._t("notice.control_unavailable");
    const controlAriaLabel = controlUnavailable
      ? `${this._t("action.for_entity", { action: actionLabel, entity: label })}. ${unavailableMessage}`
      : this._t("action.for_entity", { action: actionLabel, entity: label });
    const control = meta.control
      ? `
        <button
          class="entity-action risk-${escapeHtml(ADMIN_RISK_ORDER.includes(meta.risk) ? meta.risk : "unknown")} ${meta.disruptive ? "disruptive" : ""} ${controlUnavailable ? "is-unavailable" : ""}"
          data-control="${escapeHtml(meta.entity_id)}"
          aria-disabled="${controlUnavailable}"
          aria-label="${escapeHtml(controlAriaLabel)}"
          ${controlUnavailable ? `title="${escapeHtml(unavailableMessage)}"` : ""}
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
      <article class="entity-card ${child ? "child-entity-card" : ""} ${stateClass} ${wanPresentation.lastConfirmed ? "last-confirmed" : ""} ${isSemanticControl(meta) ? "control-card" : ""}">
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
        ${riskBadge}
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
          sourceId === "wan_counters" && (sourceState?.retrying === true || sourceState?.state === "cooldown");
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
              ? this._t(sourceState.state === "cooldown" ? "status.telemetry_cooldown" : "status.telemetry_retrying")
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

  _adminFieldLabel(field) {
    const key = `admin.field.${field}`;
    const translated = this._t(key);
    return translated === key ? humanize(field) : translated;
  }

  _renderAdminReadRow(sectionId, row, index) {
    const info = ADMIN_READ_SECTION_INFO[sectionId];
    const titleField = [
      "name",
      "hostname",
      "model",
      "operator",
      "mac",
      "ipv4",
    ].find((field) => typeof row[field] === "string" && row[field].length > 0);
    const title = titleField
      ? row[titleField]
      : this._t("admin.item", { index: index + 1 });
    const values = info.fields
      .filter((field) => Object.hasOwn(row, field))
      .map(
        (field) => `
          <div class="admin-read-value">
            <dt>${escapeHtml(this._adminFieldLabel(field))}</dt>
            <dd>${escapeHtml(formatAdminReadValue(field, row[field], this._locale(), this._language()))}</dd>
          </div>
        `,
      )
      .join("");
    return `
      <article class="admin-read-row">
        <h4>${escapeHtml(title)}</h4>
        <dl>${values}</dl>
      </article>
    `;
  }

  _renderAdminReadSection(
    sectionId,
    section,
    { sourceAvailable = true } = {},
  ) {
    const info = ADMIN_READ_SECTION_INFO[sectionId];
    const observed = Boolean(section);
    const rows = section?.rows || [];
    const temporarilyUnavailable =
      sourceAvailable === false || Boolean(this._adminReadError);
    const loading = !observed && this._adminReadLoading;
    const status = observed
      ? this._t("admin.count.rows", { count: rows.length })
      : loading
        ? this._t("admin.status.loading")
        : temporarilyUnavailable
          ? this._t("admin.status.temporarily_unavailable")
          : this._t("admin.status.not_observed");
    const content = loading
      ? `<div class="admin-read-loading" role="status"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.loading"))}</div>`
      : !observed && temporarilyUnavailable
        ? `<p class="admin-read-empty">${escapeHtml(this._t("admin.empty.temporarily_unavailable"))}</p>`
        : !observed
          ? `<p class="admin-read-empty">${escapeHtml(this._t("admin.empty.not_observed"))}</p>`
          : rows.length === 0
            ? `<p class="admin-read-empty">${escapeHtml(this._t("admin.empty.no_details"))}</p>`
            : `<div class="admin-read-rows">${rows
                .map((row, index) =>
                  this._renderAdminReadRow(sectionId, row, index),
                )
                .join("")}</div>`;
    const stale =
      observed && temporarilyUnavailable
        ? `<p class="admin-read-warning"><ha-icon icon="mdi:cloud-alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.stale"))}</p>`
        : "";
    const truncated = section?.truncated
      ? `<p class="admin-read-warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.truncated"))}</p>`
      : "";
    const stateClass = observed
      ? temporarilyUnavailable
        ? "observed stale"
        : "observed"
      : loading
        ? "loading"
        : temporarilyUnavailable
          ? "temporarily-unavailable"
          : "not-observed";
    return `
      <details class="admin-read-section ${stateClass}" data-detail-id="admin-read:${escapeHtml(sectionId)}">
        <summary>
          <span class="admin-read-section-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(info.icon)}"></ha-icon></span>
          <span>
            <strong>${escapeHtml(this._t(info.titleKey))}</strong>
            <small>${escapeHtml(status)}</small>
          </span>
          <ha-icon class="admin-read-chevron" icon="mdi:chevron-down" aria-hidden="true"></ha-icon>
        </summary>
        <div class="admin-read-section-content">
          ${stale}
          ${truncated}
          ${content}
        </div>
      </details>
    `;
  }

  _renderAdminReadOverview() {
    if (this._hass?.user?.is_admin !== true) {
      return `
        <section class="admin-read-overview restricted">
          <ha-icon icon="mdi:shield-lock-outline" aria-hidden="true"></ha-icon>
          <div>
            <h2>${escapeHtml(this._t("admin.read.title"))}</h2>
            <p>${escapeHtml(this._t("admin.read.admin_only"))}</p>
          </div>
        </section>
      `;
    }

    const error = this._adminReadError
      ? `<div class="admin-read-error" role="alert"><ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon><span>${escapeHtml(this._t(this._adminReadError))}</span></div>`
      : "";
    const loading = this._adminReadLoading
      ? `<div class="admin-read-loading" role="status"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.loading"))}</div>`
      : "";

    return `
      <section class="admin-read-overview">
        <header>
          <div>
            <span class="kicker">${escapeHtml(this._t("admin.read.kicker"))}</span>
            <h2>${escapeHtml(this._t("admin.read.title"))}</h2>
            <p>${escapeHtml(this._t("admin.read.subtitle"))}</p>
          </div>
          <button
            class="icon-button"
            data-admin-refresh
            title="${escapeHtml(this._t("action.refresh_admin_read"))}"
            aria-label="${escapeHtml(this._t("action.refresh_admin_read"))}"
            ${this._adminReadLoading ? "disabled" : ""}
          >
            <ha-icon icon="mdi:refresh" aria-hidden="true"></ha-icon>
          </button>
        </header>
        ${error}
        ${loading}
      </section>
    `;
  }

  _renderAdminPrivateQueryStatus({ errorKey, loading, query }) {
    if (loading) {
      return `<div class="admin-query-status loading" role="status" aria-live="polite"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.query.loading"))}</div>`;
    }
    if (errorKey) {
      return `<div class="admin-query-status error" role="alert" data-admin-query-result="${escapeHtml(query)}" tabindex="-1"><ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon><span>${escapeHtml(this._t(errorKey))}</span></div>`;
    }
    return "";
  }

  _renderAdminPrivatePbxQuery() {
    const state = this._adminPrivateQueries.pbx;
    const available = this._adminPrivateQueryAvailable("ip_pbx_refresh");
    const observed = this._adminPrivateQueryCapabilityObserved(
      "ip_pbx_refresh",
    );
    const error = this._renderAdminPrivateQueryStatus({
      errorKey: state.errorKey,
      loading: state.loading,
      query: "ip_pbx_refresh",
    });
    const result = state.result
      ? `
        <section class="admin-query-result" data-admin-query-result="ip_pbx_refresh" tabindex="-1" aria-live="polite">
          <header>
            <div>
              <strong>${escapeHtml(this._t("admin.query.pbx.result"))}</strong>
              <small>${escapeHtml(this._t("admin.query.ephemeral"))}</small>
            </div>
            <button class="secondary compact" type="button" data-admin-query-clear="ip_pbx_refresh">${escapeHtml(this._t("admin.query.clear"))}</button>
          </header>
          <dl class="admin-query-values">
            ${["client_id", "status", "name", "ipv4", "mac"]
              .filter((field) => Object.hasOwn(state.result, field))
              .map(
                (field) => `<div><dt>${escapeHtml(this._t(`admin.query.field.${field}`))}</dt><dd>${escapeHtml(state.result[field])}</dd></div>`,
              )
              .join("")}
          </dl>
        </section>
      `
      : "";
    return `
      <section class="admin-query-card" data-admin-query="ip_pbx_refresh">
        <header class="admin-query-heading">
          <span aria-hidden="true"><ha-icon icon="mdi:phone-sync-outline"></ha-icon></span>
          <div>
            <strong>${escapeHtml(this._t("admin.query.pbx.title"))}</strong>
            <p>${escapeHtml(this._t("admin.query.pbx.description"))}</p>
          </div>
          <span class="admin-query-read-only">${escapeHtml(this._t("admin.query.read_only"))}</span>
        </header>
        <form class="admin-query-form" data-admin-query-form="ip_pbx_refresh" novalidate>
          <label>
            <span>${escapeHtml(this._t("admin.query.field.client_id"))}</span>
            <input
              data-admin-query-input="pbx-client-id"
              type="text"
              value="${escapeHtml(state.clientId)}"
              minlength="1"
              maxlength="32"
              pattern="[A-Za-z0-9_-]{1,32}"
              aria-describedby="speedport-query-pbx-hint speedport-query-pbx-error"
              ${state.errorKey === "admin.query.error.identifier" ? 'aria-invalid="true"' : ""}
              autocomplete="off"
              autocapitalize="none"
              spellcheck="false"
              ${!available || state.loading ? "disabled" : ""}
            >
            <small id="speedport-query-pbx-hint">${escapeHtml(this._t("admin.query.pbx.hint"))}</small>
            <small id="speedport-query-pbx-error" class="admin-query-input-error" data-admin-query-input-error="pbx-client-id" role="alert">${state.errorKey === "admin.query.error.identifier" ? escapeHtml(this._t(state.errorKey)) : ""}</small>
          </label>
          <button class="primary" type="submit" ${!available || state.loading ? "disabled" : ""}>
            ${escapeHtml(state.loading ? this._t("admin.query.working") : this._t("admin.query.pbx.run"))}
          </button>
        </form>
        ${!available ? `<p class="admin-query-unavailable"><ha-icon icon="${observed ? "mdi:account-lock-outline" : "mdi:help-circle-outline"}" aria-hidden="true"></ha-icon>${escapeHtml(this._t(observed ? "admin.query.unavailable" : "admin.query.not_observed"))}</p>` : ""}
        ${error}
        ${result}
      </section>
    `;
  }

  _renderPhonebookEntry(entry) {
    const displayName = [entry.first_name, entry.last_name]
      .filter(Boolean)
      .join(" ") || this._t("admin.query.phonebook.unnamed");
    return `
      <article class="admin-query-entry">
        <div>
          <strong>${escapeHtml(displayName)}</strong>
          ${entry.number ? `<small>${escapeHtml(entry.number)}</small>` : ""}
        </div>
        <button
          class="secondary compact"
          type="button"
          data-phonebook-contact="${escapeHtml(entry.contact_id)}"
          ${this._adminPrivateQueries.phonebook.contactLoading ? "disabled" : ""}
        >${escapeHtml(this._t("admin.query.phonebook.details"))}</button>
      </article>
    `;
  }

  _renderPhonebookContactResult() {
    const state = this._adminPrivateQueries.phonebook;
    const result = state.contactResult;
    const status = this._renderAdminPrivateQueryStatus({
      errorKey: state.contactErrorKey,
      loading: state.contactLoading,
      query: "phonebook_contact",
    });
    if (!result) return status;
    const fields = [
      "first_name",
      "last_name",
      "private_number",
      "work_number",
      "mobile_number",
      "secondary_mobile_number",
      "street",
      "postal_code",
      "city",
      "birthday",
    ];
    return `${status}
      <section class="admin-query-result contact" data-admin-query-result="phonebook_contact" tabindex="-1" aria-live="polite">
        <header>
          <div>
            <strong>${escapeHtml(this._t("admin.query.phonebook.contact"))}</strong>
            <small>${escapeHtml(this._t("admin.query.ephemeral"))}</small>
          </div>
          <button class="secondary compact" type="button" data-admin-query-clear="phonebook_contact">${escapeHtml(this._t("admin.query.clear"))}</button>
        </header>
        <dl class="admin-query-values">
          ${fields
            .filter((field) => Object.hasOwn(result.contact, field))
            .map(
              (field) => `<div><dt>${escapeHtml(this._t(`admin.query.field.${field}`))}</dt><dd>${escapeHtml(result.contact[field])}</dd></div>`,
            )
            .join("")}
        </dl>
      </section>
    `;
  }

  _renderAdminPrivatePhonebookQuery() {
    const state = this._adminPrivateQueries.phonebook;
    const available = this._adminPrivateQueryAvailable("phonebook_search");
    const observed = this._adminPrivateQueryCapabilityObserved(
      "phonebook_search",
    );
    const searchStatus = this._renderAdminPrivateQueryStatus({
      errorKey: state.searchErrorKey,
      loading: state.searchLoading,
      query: "phonebook_search",
    });
    const result = state.searchResult;
    const resultMarkup = result
      ? `
        <section class="admin-query-result" data-admin-query-result="phonebook_search" tabindex="-1" aria-live="polite">
          <header>
            <div>
              <strong>${escapeHtml(this._t("admin.query.phonebook.result", { count: result.entries.length }))}</strong>
              <small>${escapeHtml(
                [
                  result.total === undefined
                    ? this._t("admin.query.ephemeral")
                    : this._t("admin.query.phonebook.total", {
                        count: result.total,
                      }),
                  result.free_entries === undefined
                    ? undefined
                    : this._t("admin.query.phonebook.free_entries", {
                        count: result.free_entries,
                      }),
                ]
                  .filter(Boolean)
                  .join(" · "),
              )}</small>
            </div>
            <button class="secondary compact" type="button" data-admin-query-clear="phonebook_search">${escapeHtml(this._t("admin.query.clear"))}</button>
          </header>
          ${result.truncated ? `<p class="admin-query-warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.query.phonebook.truncated"))}</p>` : ""}
          ${
            result.entries.length
              ? `<div class="admin-query-entries">${result.entries.map((entry) => this._renderPhonebookEntry(entry)).join("")}</div>`
              : `<p class="admin-query-empty">${escapeHtml(this._t("admin.query.phonebook.empty"))}</p>`
          }
        </section>
      `
      : "";
    const bookOptions = Array.from({ length: 6 }, (_, index) => `
      <option value="${index}" ${state.phonebookId === index ? "selected" : ""}>${escapeHtml(this._t("admin.query.phonebook.book", { number: index + 1 }))}</option>
    `).join("");
    return `
      <section class="admin-query-card" data-admin-query="phonebook_search">
        <header class="admin-query-heading">
          <span aria-hidden="true"><ha-icon icon="mdi:book-search-outline"></ha-icon></span>
          <div>
            <strong>${escapeHtml(this._t("admin.query.phonebook.title"))}</strong>
            <p>${escapeHtml(this._t("admin.query.phonebook.description"))}</p>
          </div>
          <span class="admin-query-read-only">${escapeHtml(this._t("admin.query.read_only"))}</span>
        </header>
        <form class="admin-query-form phonebook" data-admin-query-form="phonebook_search" novalidate>
          <label>
            <span>${escapeHtml(this._t("admin.query.phonebook.selection"))}</span>
            <select
              data-admin-query-input="phonebook-id"
              aria-describedby="speedport-query-phonebook-error"
              ${state.searchErrorKey === "admin.query.error.phonebook" ? 'aria-invalid="true"' : ""}
              ${!available || state.searchLoading ? "disabled" : ""}
            >${bookOptions}</select>
          </label>
          <label>
            <span>${escapeHtml(this._t("admin.query.phonebook.prefix"))}</span>
            <input
              data-admin-query-input="phonebook-prefix"
              type="text"
              value="${escapeHtml(state.prefix)}"
              maxlength="1"
              pattern="[A-Za-z]?"
              placeholder="A"
              aria-describedby="speedport-query-phonebook-hint speedport-query-phonebook-error"
              ${state.searchErrorKey === "admin.query.error.prefix" ? 'aria-invalid="true"' : ""}
              autocomplete="off"
              autocapitalize="characters"
              spellcheck="false"
              ${!available || state.searchLoading ? "disabled" : ""}
            >
            <small id="speedport-query-phonebook-hint">${escapeHtml(this._t("admin.query.phonebook.hint"))}</small>
            <small id="speedport-query-phonebook-error" class="admin-query-input-error" data-admin-query-input-error="phonebook-prefix" role="alert">${["admin.query.error.phonebook", "admin.query.error.prefix"].includes(state.searchErrorKey) ? escapeHtml(this._t(state.searchErrorKey)) : ""}</small>
          </label>
          <button class="primary" type="submit" ${!available || state.searchLoading ? "disabled" : ""}>
            ${escapeHtml(state.searchLoading ? this._t("admin.query.working") : this._t("admin.query.phonebook.run"))}
          </button>
        </form>
        ${!available ? `<p class="admin-query-unavailable"><ha-icon icon="${observed ? "mdi:account-lock-outline" : "mdi:help-circle-outline"}" aria-hidden="true"></ha-icon>${escapeHtml(this._t(observed ? "admin.query.unavailable" : "admin.query.not_observed"))}</p>` : ""}
        ${searchStatus}
        ${resultMarkup}
        ${this._renderPhonebookContactResult()}
      </section>
    `;
  }

  _renderAdminIpInformation() {
    const state = this._adminPrivateQueries.ip;
    const available = this._adminPrivateQueryAvailable("ip_information");
    const content = state.result ? Object.entries(ADMIN_IP_INFORMATION_FIELDS).map(([family, fields]) =>
      `<section class="admin-read-row"><h4>${family === "ipv4" ? "IPv4" : "IPv6"}</h4><dl>${fields.map((field) =>
        `<div class="admin-read-value"><dt>${escapeHtml(this._t(`admin.ip.field.${field}`))}</dt>` +
        `<dd>${escapeHtml(state.result[family][field] ?? this._t("admin.ip.not_reported"))}</dd></div>`).join("")}</dl></section>`).join("") : "";
    return `<section class="admin-query-card" data-admin-query="ip_information">
      <p>${escapeHtml(this._t("admin.ip.description"))}</p>
      <button type="button" class="secondary" data-refresh-ip-information${state.loading || !available ? " disabled" : ""}>${escapeHtml(this._t("admin.ip.refresh"))}</button>
      ${this._renderAdminPrivateQueryStatus({errorKey: state.errorKey, loading: state.loading, query: "ip_information"})}
      ${!available ? `<p>${escapeHtml(this._t("admin.query.unavailable"))}</p>` : ""}
      ${content ? `<div class="admin-read-rows" aria-live="polite">${content}</div>` : !state.loading && !state.errorKey && available ? `<p>${escapeHtml(this._t("admin.ip.not_loaded"))}</p>` : ""}
    </section>`;
  }

  _renderAdminPrivateQueries(queryIds) {
    return queryIds
      .map((query) =>
        query === "ip_information" ? this._renderAdminIpInformation() : query === "ip_pbx_refresh"
          ? this._renderAdminPrivatePbxQuery()
          : query === "phonebook_search"
            ? this._renderAdminPrivatePhonebookQuery()
            : "",
      )
      .join("");
  }

  _adminActionTargetLabel(actionId, target) {
    let label;
    if (
      ["dect_handset_set_paging", "dect_handset_disconnect"].includes(actionId)
    ) {
      label = target.name || this._t("admin.action.target.handset");
    } else if (
      ["voip_line_set_active", "voip_line_delete"].includes(actionId) &&
      target.number_suffix
    ) {
      label = this._t("admin.action.target.line_ending", {
        suffix: target.number_suffix,
      });
    } else if (actionId === "dect_repeater_disconnect") {
      label = this._t("admin.action.target.dect_repeater");
    } else if (actionId === "voip_provider_delete") {
      label = Number.isInteger(target.provider_code)
        ? this._t("admin.action.target.voip_provider_code", {
            code: target.provider_code,
          })
        : this._t("admin.action.target.voip_provider");
    } else if (actionId === "ip_pbx_client_delete") {
      label = target.name || this._t("admin.action.target.ip_pbx_client");
    } else if (actionId === "phonebook_entry_delete") {
      label =
        target.display_name || this._t("admin.action.target.phonebook_entry");
    } else if (actionId === "nas_share_delete") {
      label = target.name || this._t("admin.action.target.nas_share");
    } else {
      label = this._t("admin.action.target.voip_line");
    }
    return target.reference
      ? this._t("admin.action.target.with_reference", {
          target: label,
          reference: target.reference,
        })
      : label;
  }

  _adminActionTargetStatus(actionId, target, active) {
    if (typeof active === "boolean") {
      return this._t(
        active ? "admin.action.state.active" : "admin.action.state.inactive",
      );
    }
    if (actionId === "voip_line_delete" && typeof target.active === "boolean") {
      return this._t(
        target.active
          ? "admin.action.state.active"
          : "admin.action.state.inactive",
      );
    }
    if (
      actionId === "ip_pbx_client_delete" &&
      ADMIN_ACTION_PBX_TARGET_STATUSES.has(target.status)
    ) {
      return this._t(`admin.action.target.status.${target.status}`);
    }
    return "";
  }

  _renderAdminActionTarget(actionId, target, active) {
    const targetToken = target.target_token;
    const label = this._adminActionTargetLabel(actionId, target);
    const status = this._adminActionTargetStatus(actionId, target, active);
    const focusKey = `${actionId}:${targetToken}`;
    const destructive = ADMIN_ACTION_INFO[actionId]?.risk === "destructive";
    const actionLabel = this._t(
      !destructive && active
        ? `admin.action.${actionId}.stop`
        : `admin.action.${actionId}.run`,
    );
    const accessibleLabel = this._t("admin.action.target.button_label", {
      action: actionLabel,
      target: label,
    });
    return `
      <article class="admin-action-target">
        <span>
          <strong>${escapeHtml(label)}</strong>
          ${status ? `<small>${escapeHtml(status)}</small>` : ""}
        </span>
        <button
          class="secondary compact"
          data-admin-action="${escapeHtml(actionId)}"
          data-admin-target-token="${escapeHtml(targetToken)}"
          data-admin-action-key="${escapeHtml(focusKey)}"
          aria-label="${escapeHtml(accessibleLabel)}"
        >${escapeHtml(actionLabel)}</button>
      </article>
    `;
  }

  _renderDectPagingTargets() {
    const state = this._currentAdminActionTargets("handsetTargets");
    if (state.loading) {
      return `<p class="admin-action-status" role="status"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.action.targets_loading"))}</p>`;
    }
    if (state.errorKey) {
      return `
        <p class="admin-action-status error" role="alert"><ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t(state.errorKey))}</p>
        <button class="secondary compact" data-admin-action-targets-refresh>${escapeHtml(this._t("admin.action.targets_retry"))}</button>
      `;
    }
    if (!state.loaded) {
      return `
        <p class="admin-action-status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.targets_open_hint"))}</p>
        <button class="secondary compact" data-admin-action-targets-refresh>${escapeHtml(this._t("admin.action.targets_retry"))}</button>
      `;
    }
    const targets = state.result?.targets || [];
    const rows = targets
      .map((target) =>
        this._renderAdminActionTarget(
          "dect_handset_set_paging",
          target,
          target.paging,
        ),
      )
      .join("");
    return `
      ${rows ? `<div class="admin-action-targets">${rows}</div>` : `<p class="admin-action-status">${escapeHtml(this._t("admin.action.targets_empty"))}</p>`}
      ${state.result?.truncated ? `<p class="admin-action-status warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.targets_truncated"))}</p>` : ""}
    `;
  }

  _renderVoipLineTargets() {
    const state = this._currentAdminActionTargets("voipLineTargets");
    if (state.loading) {
      return `<p class="admin-action-status" role="status"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.action.lines_loading"))}</p>`;
    }
    if (state.errorKey) {
      return `
        <p class="admin-action-status error" role="alert"><ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t(state.errorKey))}</p>
        <button class="secondary compact" data-admin-action-lines-refresh>${escapeHtml(this._t("admin.action.lines_retry"))}</button>
      `;
    }
    if (!state.loaded) {
      return `
        <p class="admin-action-status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.lines_open_hint"))}</p>
        <button class="secondary compact" data-admin-action-lines-refresh>${escapeHtml(this._t("admin.action.lines_retry"))}</button>
      `;
    }
    const targets = state.result?.targets || [];
    const rows = targets
      .map((target) =>
        this._renderAdminActionTarget(
          "voip_line_set_active",
          target,
          target.active,
        ),
      )
      .join("");
    return `
      ${rows ? `<div class="admin-action-targets">${rows}</div>` : `<p class="admin-action-status">${escapeHtml(this._t("admin.action.lines_empty"))}</p>`}
      ${state.result?.truncated ? `<p class="admin-action-status warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.lines_truncated"))}</p>` : ""}
    `;
  }

  _renderDestructiveActionTargets(actionId) {
    const info = Object.hasOwn(ADMIN_ACTION_INFO, actionId)
      ? ADMIN_ACTION_INFO[actionId]
      : undefined;
    const state = this._currentDestructiveActionTargets(actionId);
    if (info?.risk !== "destructive" || !state) return "";
    const phonebookSelector =
      actionId === "phonebook_entry_delete"
        ? `
          <label class="admin-action-context">
            <span>${escapeHtml(this._t("admin.action.phonebook.selection"))}</span>
            <select data-admin-action-phonebook-id ${state.loading ? "disabled" : ""}>
              ${Array.from({ length: 6 }, (_, index) => `
                <option value="${index}" ${this._adminActionState.phonebookId === index ? "selected" : ""}>${escapeHtml(this._t("admin.query.phonebook.book", { number: index + 1 }))}</option>
              `).join("")}
            </select>
          </label>
        `
        : "";
    let result = "";
    if (state.loading) {
      result = `<p class="admin-action-status" role="status"><span class="loading-mark" aria-hidden="true"><i></i><i></i><i></i></span>${escapeHtml(this._t("admin.action.destructive.targets_loading"))}</p>`;
    } else if (state.errorKey) {
      result = `
        <p class="admin-action-status error" role="alert"><ha-icon icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t(state.errorKey))}</p>
        <button class="secondary compact" data-admin-destructive-targets-refresh="${escapeHtml(actionId)}">${escapeHtml(this._t("admin.action.destructive.targets_retry"))}</button>
      `;
    } else if (!state.loaded) {
      result = `
        <p class="admin-action-status"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.destructive.targets_open_hint"))}</p>
        <button class="secondary compact" data-admin-destructive-targets-refresh="${escapeHtml(actionId)}">${escapeHtml(this._t("admin.action.destructive.targets_retry"))}</button>
      `;
    } else {
      const rows = (state.result?.targets || [])
        .map((target) =>
          this._renderAdminActionTarget(actionId, target, undefined),
        )
        .join("");
      result = `
        ${rows ? `<div class="admin-action-targets">${rows}</div>` : `<p class="admin-action-status">${escapeHtml(this._t("admin.action.destructive.targets_empty"))}</p>`}
        ${state.result?.truncated ? `<p class="admin-action-status warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.destructive.targets_truncated", { count: info.maxTargets }))}</p>` : ""}
      `;
    }
    return `${phonebookSelector}${result}`;
  }

  _renderAdminActions(feature) {
    return feature.adminActions
      .map((actionId) => {
        const info = ADMIN_ACTION_INFO[actionId];
        const descriptor = this._adminActionDescriptor(actionId);
        if (!info || info.featureId !== feature.id || !descriptor) return "";
        const available = descriptor.supported && descriptor.available;
        let controls = "";
        if (!available) {
          controls = `
            <p class="admin-action-status unavailable"><ha-icon icon="mdi:shield-lock-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t(this._adminActionUnavailableKey(descriptor.unavailable_reason)))}</p>
            <button class="primary" disabled>${escapeHtml(this._t(`admin.action.${actionId}.run`))}</button>
          `;
        } else if (actionId === "dect_handset_set_paging") {
          controls = this._renderDectPagingTargets();
        } else if (actionId === "voip_line_set_active") {
          controls = this._renderVoipLineTargets();
        } else if (info.risk === "destructive") {
          controls = this._renderDestructiveActionTargets(actionId);
        } else {
          controls = `
            <button
              class="primary"
              data-admin-action="${escapeHtml(actionId)}"
              data-admin-action-key="${escapeHtml(`${actionId}:global`)}"
            >${escapeHtml(this._t(`admin.action.${actionId}.run`))}</button>
          `;
        }
        return `
          <section class="admin-action-card risk-${escapeHtml(descriptor.risk)}" data-admin-action-card="${escapeHtml(actionId)}">
            <header class="admin-action-heading">
              <span aria-hidden="true"><ha-icon icon="${escapeHtml(info.icon)}"></ha-icon></span>
              <div>
                <strong>${escapeHtml(this._t(`admin.action.${actionId}.label`))}</strong>
                <p>${escapeHtml(this._t(`admin.action.${actionId}.description`))}</p>
              </div>
              <span class="admin-action-confirmation">${escapeHtml(this._t(descriptor.confirmation === "typed" ? "admin.action.typed_required" : "admin.action.confirm_required"))}</span>
            </header>
            ${info.risk === "destructive" ? `<p class="admin-action-impact"><ha-icon icon="mdi:alert-octagon-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t(`admin.action.${actionId}.impact`))}</p>` : ""}
            ${controls}
          </section>
        `;
      })
      .join("");
  }

  _adminFeaturePresentation(
    feature,
    entities,
    sections,
    capabilities,
    sourceAvailable,
  ) {
    const settings = this._settingsForFeature(feature.id);
    const maintenance = this._maintenanceForFeature(feature.id);
    const transfer = this._fileTransferForFeature(feature.id);
    if (transfer) return transfer.available
      ? {key: "control_available", icon: "mdi:file-lock-outline"}
      : {key: "control_unavailable", icon: "mdi:shield-lock-outline"};
    if (maintenance) {
      return maintenance.available
        ? { key: "control_available", icon: "mdi:alert-octagon-outline" }
        : { key: "control_unavailable", icon: "mdi:shield-lock-outline" };
    }
    if (settings.length > 0) {
      return settings.some((setting) => setting.available)
        ? { key: "control_available", icon: "mdi:form-select" }
        : { key: "control_unavailable", icon: "mdi:shield-lock-outline" };
    }
    const supportedControls = entities.filter(
      (entity) =>
        isSemanticControl(entity) &&
        adminFeatureForControl(entity) === feature.id,
    );
    const controls = supportedControls.filter((entity) => entity.control === true);
    const reports = entities.filter(
      (entity) =>
        !isSemanticControl(entity) &&
        feature.entityGroups.includes(capabilityGroupFor(entity)),
    );
    const observedRead = feature.readSections.some((sectionId) =>
      sections.has(sectionId),
    );
    const capabilityKnown = feature.capabilities.some((capability) =>
      capabilities.has(capability),
    );
    const adminActions = feature.adminActions
      .map((actionId) => this._adminActionDescriptor(actionId))
      .filter(
        (action) =>
          action &&
          (!feature.adminActionReplacesBlocked || action.supported === true),
      );

    if (adminActions.length > 0) {
      return adminActions.some((action) => action.available)
        ? { key: "control_available", icon: "mdi:gesture-tap-button" }
        : { key: "control_unavailable", icon: "mdi:shield-lock-outline" };
    }

    if (controls.length > 0) {
      const available = controls.some(
        (control) => !this._isControlUnavailable(control, this._state(control)),
      );
      return {
        key: available ? "control_available" : "control_unavailable",
        icon: available
          ? "mdi:toggle-switch"
          : "mdi:toggle-switch-off-outline",
      };
    }
    if (supportedControls.length > 0) {
      return {
        key: "control_permission_required",
        icon: "mdi:shield-lock-outline",
      };
    }

    const reportAvailable = reports.some(
      (report) => entityAvailability(report, this._state(report)) === "available",
    );
    const privateQueryObserved = feature.queries.some((query) =>
      this._adminPrivateQueryCapabilityObserved(query),
    );
    const privateQueryAvailable = feature.queries.some((query) =>
      this._adminPrivateQueryAvailable(query),
    );
    if (reportAvailable || (observedRead && sourceAvailable) || privateQueryAvailable) {
      return { key: "read_only", icon: "mdi:eye-outline" };
    }
    if (
      reports.length > 0 ||
      (observedRead && !sourceAvailable) ||
      privateQueryObserved ||
      (capabilityKnown && !sourceAvailable)
    ) {
      return {
        key: "temporarily_unavailable",
        icon: "mdi:cloud-alert-outline",
      };
    }
    return { key: "not_observed", icon: "mdi:help-circle-outline" };
  }

  _renderAdminFeatureCatalog(
    features,
    entities,
    sections,
    capabilities,
    sourceAvailable,
    accessSourceStates,
    { canReadAdmin = false, pageMode = false, readSections } = {},
  ) {
    if (features.length === 0) return "";
    const cards = features
      .map((feature) => {
        const featureSettings = this._settingsForFeature(feature.id);
        const maintenance = this._maintenanceForFeature(feature.id);
        const transfers = this._fileTransfersForFeature(feature.id);
        const transfer = transfers[0];
        const supportedReplacementAction =
          feature.adminActionReplacesBlocked &&
          feature.adminActions.some(
            (actionId) => this._adminActionDescriptor(actionId)?.supported,
          );
        const featureContract = supportedReplacementAction || (transfer && !feature.id.includes("firmware") && feature.id !== "telephony_phonebook_management") || (maintenance && feature.id !== "system_messages") ||
          (featureSettings.length > 0 && SETTINGS_FEATURE_LINKS[feature.id]?.complete)
          ? "reviewed"
          : feature.contract;
        const featureSourceAvailable = feature.readSections.length
          ? feature.readSections.some((sectionId) => {
              const source =
                ADMIN_READ_SECTION_INFO[sectionId]?.source || "protected_json";
              return source === "protected_json"
                ? sourceAvailable
                : !this._adminReadError &&
                    accessSourceStates[source]?.available !== false;
            })
          : sourceAvailable;
        const presentation = this._adminFeaturePresentation(
          feature,
          entities,
          sections,
          capabilities,
          featureSourceAvailable,
        );
        const statusKey =
          featureContract === "unsupported"
            ? "no_local_control"
            : featureContract === "blocked" && presentation.key === "read_only"
              ? "read_only_control_unproven"
              : featureContract === "blocked" && presentation.key === "not_observed"
                ? "not_exposed"
                : presentation.key;
        const status = this._t(`admin.feature.status.${statusKey}`);
        const contract = this._t(`admin.contract.${featureContract}`);
        const contractHint =
          featureContract === "blocked"
            ? ` title="${escapeHtml(this._t("admin.contract.blocked_hint"))}"`
            : "";
        const featureRisk = feature.risk
          ? this._renderRiskBadge(feature.risk)
          : "";
        const blockedReason =
          featureContract === "blocked" && feature.blockedReasonKey
            ? `<span class="admin-feature-blocked-reason">${escapeHtml(this._t(feature.blockedReasonKey))}</span>`
            : "";
        const featureControls = entities.filter(
          (entity) =>
            isSemanticControl(entity) &&
            adminFeatureForControl(entity) === feature.id,
        );
        const controlMarkup = featureControls.length && !pageMode
          ? this._renderAdministrationEntities(
              featureControls,
              accessSourceStates,
            )
          : "";
        const readMarkup = canReadAdmin
          ? feature.readSections
              .filter(
                (sectionId) =>
                  ADMIN_READ_SECTION_OWNER.get(sectionId) === feature.id &&
                  (!readSections || readSections.includes(sectionId)),
              )
              .map((sectionId) =>
                this._renderAdminReadSection(
                  sectionId,
                  sections.get(sectionId),
                  {
                    sourceAvailable:
                      (ADMIN_READ_SECTION_INFO[sectionId]?.source ||
                        "protected_json") === "protected_json"
                        ? sourceAvailable
                        : !this._adminReadError &&
                          accessSourceStates[
                            ADMIN_READ_SECTION_INFO[sectionId]?.source
                          ]?.available !== false,
                  },
                ),
              )
              .join("")
          : "";
        const queryMarkup = (canReadAdmin && feature.id === "telephony_call_lists"
          ? '<button type="button" class="secondary" data-open-call-history="true">View or export private call history</button>' : "") + (canReadAdmin
          ? this._renderAdminPrivateQueries(feature.queries)
          : "");
        const actionMarkup =
          canReadAdmin &&
          (!feature.adminActionReplacesBlocked || supportedReplacementAction)
          ? this._renderAdminActions(feature)
          : "";
        const settingsMarkup = canReadAdmin && featureSettings.length && !pageMode
          ? `<div class="sp-settings-buttons">${featureSettings.map((setting) => `<button type="button" data-open-setting="${escapeHtml(setting.id)}"${setting.available ? "" : " disabled"}>${escapeHtml(setting.title)}</button>`).join("")}</div>${SETTINGS_FEATURE_LINKS[feature.id]?.complete ? "" : "<p>Partial coverage: the editors above are implemented; other options in this feature remain pending.</p>"}`
          : "";
        const reportMarkup = pageMode && feature.id === "internet_receiver_mode"
          ? this._renderAdministrationEntities(entities.filter((entity) =>
              !isSemanticControl(entity) && entity.translation_key === "receiver_mode" &&
              entity.access_source !== "integration"), accessSourceStates)
          : "";
        const ownedMarkup =
          controlMarkup || readMarkup || reportMarkup || queryMarkup || actionMarkup || settingsMarkup || maintenance || transfer
            ? `<div class="admin-feature-owned" data-admin-feature-content="${escapeHtml(feature.id)}">${transfers.map((item) => `<button type="button" class="secondary" data-open-transfer="${escapeHtml(item.id)}"${item.available ? "" : " disabled"}>${escapeHtml(item.title)}</button>`).join("")}${maintenance ? `<button type="button" class="secondary" data-open-maintenance="${escapeHtml(maintenance.id)}"${maintenance.available ? "" : " disabled"}>Review ${escapeHtml(maintenance.title)}</button>` : ""}${settingsMarkup}${controlMarkup}${readMarkup}${reportMarkup}${queryMarkup}${actionMarkup}</div>`
            : "";
        const headingId = `speedport-admin-feature-${feature.id}`.replace(
          /[^a-z0-9_-]/gi,
          "-",
        );
        const featureHeader = `
          <span class="admin-feature-icon" aria-hidden="true"><ha-icon icon="${escapeHtml(presentation.icon)}"></ha-icon></span>
          <span class="admin-feature-copy">
            <strong id="${escapeHtml(headingId)}">${escapeHtml(this._t(feature.titleKey))}</strong>
            <span class="admin-feature-badges">
              <span class="admin-feature-status">${escapeHtml(status)}</span>
              <span class="admin-contract-badge contract-${escapeHtml(featureContract)}"${contractHint}>${escapeHtml(contract)}</span>
              ${featureRisk}
            </span>
            ${blockedReason}
          </span>
        `;
        if (pageMode) {
          // Forms are already available in the page-local editor, not repeated
          // under every overlapping capability. Preserve contextual read/actions.
          if (!ownedMarkup && (featureSettings.length || featureControls.length)) return "";
          const emptyHint = featureContract === "blocked"
            ? feature.blockedReasonKey || "admin.contract.blocked_hint"
            : featureContract === "read_only" ? "admin.contract.read_only_hint"
              : featureContract === "unsupported" ? "admin.contract.unsupported"
                : `admin.feature.status.${statusKey}`;
          return `<section class="admin-native-section" data-admin-feature="${escapeHtml(feature.id)}" aria-labelledby="${escapeHtml(headingId)}">
            <header><h3 id="${escapeHtml(headingId)}">${escapeHtml(this._t(feature.titleKey))}</h3>
              <span class="admin-feature-status">${escapeHtml(status)}</span>${featureRisk}</header>
            ${ownedMarkup || `<p class="admin-native-unavailable">${escapeHtml(this._t(emptyHint))}</p>`}
          </section>`;
        }
        if (ownedMarkup) {
          return `
            <details class="admin-feature-card status-${escapeHtml(presentation.key)} ${feature.risk ? `risk-${escapeHtml(feature.risk)}` : ""} ${feature.destructive ? "destructive-candidate" : ""} has-owned-content" data-admin-feature="${escapeHtml(feature.id)}" data-detail-id="admin-feature:${escapeHtml(feature.id)}" aria-labelledby="${escapeHtml(headingId)}">
              <summary class="admin-feature-summary">
                ${featureHeader}
                <ha-icon class="admin-feature-chevron" icon="mdi:chevron-down" aria-hidden="true"></ha-icon>
              </summary>
              ${ownedMarkup}
            </details>
          `;
        }
        return `
          <article class="admin-feature-card status-${escapeHtml(presentation.key)} ${feature.risk ? `risk-${escapeHtml(feature.risk)}` : ""} ${feature.destructive ? "destructive-candidate" : ""}" data-admin-feature="${escapeHtml(feature.id)}" aria-labelledby="${escapeHtml(headingId)}">
            ${featureHeader}
          </article>
        `;
      })
      .join("");
    return `
      <section class="admin-feature-catalog" aria-label="${escapeHtml(this._t("admin.feature.catalog"))}">
        ${cards}
      </section>
    `;
  }

  _renderAdministrationEntities(entities, accessSourceStates) {
    const rootEntities = entities.filter((entity) => !entity.child_device);
    const childGroups = new Map();
    for (const entity of entities) {
      const child = entity.child_device;
      if (!child) continue;
      if (!childGroups.has(child.device_id)) {
        childGroups.set(child.device_id, []);
      }
      childGroups.get(child.device_id).push(entity);
    }
    const rootGrid = rootEntities.length
      ? `<div class="entity-grid administration-entity-grid">${rootEntities
          .map((entity) =>
            this._renderEntity(entity, {
              capabilityGroup: capabilityGroupFor(entity),
              sourceState: accessSourceStates[entity.access_source],
            }),
          )
          .join("")}</div>`
      : "";
    const childGrid = childGroups.size
      ? `<div class="child-device-grid">${[...childGroups.values()]
          .map((group) => this._renderChildDevice(group))
          .join("")}</div>`
      : "";
    return `${rootGrid}${childGrid}`;
  }

  _newConfigurationEditor() {
    const editor = createConfigurationEditorController({
      request: (message) => {
        if (message.type.endsWith("/save") && (this._configurationViews(editor).some((view) => view.isSaving) ||
            this._actionBusy || this._maintenanceEditor?.snapshot()?.busy || this._fileTransferEditor?.snapshot()?.busy)) {
          return Promise.reject(Object.assign(new Error("action_busy"), {code: "action_busy"}));
        }
        return this._requestPrivate(message);
      },
      onChange: () => { this._flushAdminSessionInvalidation(); this._renderSettingsEditor(editor); },
      download: async (blob, filename) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url; link.download = filename; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
    });
    return editor;
  }

  _configurationViews(except) {
    return [...new Set([this._settingsEditor, ...[...this._settingsEditors.values()].map((record) => record.editor)])]
      .filter((editor) => editor && editor !== except).map((editor) => editor.snapshot()).filter(Boolean);
  }

  _configurationSaving() {
    return this._configurationViews().some((view) => view.isSaving);
  }

  _clearSettingsEditor({preserve = new Set()} = {}) {
    this._adminSessionInvalidationPending = undefined;
    this._adminPageRecoveryPending = undefined;
    for (const [id, record] of this._settingsEditors) {
      if (preserve.has(record.editor)) continue;
      record.binding?.();
      record.editor.dispose();
      if (record.host) record.host.innerHTML = "";
      this._settingsEditors.delete(id);
    }
    this._callHistoryBinding?.();
    this._callHistoryBinding = undefined;
    this._callHistoryView?.dispose();
    if (this._callHistoryHost) this._callHistoryHost.innerHTML = "";
    this._callHistoryHost = undefined;
    if (!preserve.has(this._settingsEditor)) {
      this._settingsBinding?.();
      this._settingsBinding = undefined;
      this._settingsEditor?.dispose();
      if (this._settingsHost) this._settingsHost.innerHTML = "";
      this._settingsHost = undefined;
    }
    if (!preserve.has(this._maintenanceEditor)) {
      this._maintenanceBinding?.();
      this._maintenanceBinding = undefined;
      this._maintenanceEditor?.dispose();
      if (this._maintenanceHost) this._maintenanceHost.innerHTML = "";
      this._maintenanceHost = undefined;
    }
    if (!preserve.has(this._fileTransferEditor)) {
      this._fileTransferBinding?.();
      this._fileTransferBinding = undefined;
      this._fileTransferEditor?.dispose();
      if (this._fileTransferHost) this._fileTransferHost.innerHTML = "";
      this._fileTransferHost = undefined;
    }
  }

  _adminCallHistoryCategory() {
    return {telephony_calls_missed: "missed", telephony_calls_taken: "taken",
      telephony_calls_dialed: "dialed"}[this._currentAdminPage().page.id];
  }

  _renderCallHistoryEditor() {
    if (!this.shadowRoot || this._activeView !== "administration") return;
    const host = this.shadowRoot.querySelector("[data-call-history-editor-host]");
    if (!host) return;
    this._callHistoryHost = host;
    host.innerHTML = renderCallHistoryView(this._callHistoryView, {pageMode: Boolean(this._adminCallHistoryCategory())});
    if (!this._callHistoryBinding) this._callHistoryBinding = bindCallHistoryView(host, this._callHistoryView);
  }

  _fileTransferForFeature(featureId) {
    const matches = this._fileTransfersForFeature(featureId);
    return matches.find((item) => item.available) || matches[0];
  }

  _fileTransfersForFeature(featureId) {
    if (this._hass?.user?.is_admin !== true) return [];
    const mapped = FILE_TRANSFER_FEATURE_LINKS[featureId];
    const ids = Array.isArray(mapped) ? mapped : [mapped];
    return (this._currentRouter()?.file_transfers || []).filter((action) =>
      ids.includes(action.id) && action.execution_policy === "file_transfer" && action.supported);
  }

  _renderFileTransferEditor() {
    if (!this.shadowRoot || this._activeView !== "administration") return;
    const host = this.shadowRoot.querySelector("[data-file-transfer-editor-host]");
    if (!host) return;
    this._fileTransferHost = host;
    host.innerHTML = renderFileTransferEditor(this._fileTransferEditor);
    if (!this._fileTransferBinding) this._fileTransferBinding = bindFileTransferEditor(host, this._fileTransferEditor);
  }

  _maintenanceForFeature(featureId) {
    if (this._hass?.user?.is_admin !== true) return undefined;
    const id = MAINTENANCE_FEATURE_LINKS[featureId];
    return (this._currentRouter()?.admin_actions || []).find((action) =>
      action.id === id && action.execution_policy === "maintenance" && action.supported);
  }

  _renderMaintenanceEditor() {
    if (!this.shadowRoot || this._activeView !== "administration") return;
    const host = this.shadowRoot.querySelector("[data-maintenance-editor-host]");
    if (!host) return;
    this._maintenanceHost = host;
    host.innerHTML = renderMaintenanceEditor(this._maintenanceEditor);
    if (!this._maintenanceBinding) this._maintenanceBinding = bindMaintenanceEditor(host, this._maintenanceEditor);
  }

  _settingsForFeature(featureId) {
    if (this._hass?.user?.is_admin !== true) return [];
    const ids = SETTINGS_FEATURE_LINKS[featureId]?.ids || [];
    return (this._currentRouter()?.settings || []).filter((setting) =>
      setting.supported && ids.includes(setting.id));
  }

  _renderSettingsEditor(editor = this._settingsEditor) {
    if (!this.shadowRoot || this._activeView !== "administration") return;
    const settingId = editor.snapshot()?.setting.id;
    if (!settingId) return;
    const record = this._settingsEditors.get(settingId);
    const host = (record && this.shadowRoot.querySelector(`[data-settings-section="${settingId}"]`)) ||
      (editor === this._settingsEditor && this.shadowRoot.querySelector("[data-settings-editor-host]"));
    if (!host) return;
    host.innerHTML = renderConfigurationEditor(editor, {pageMode: true});
    if (record) {
      record.host = host;
      if (editor === this._settingsEditor) this._settingsHost = host;
      if (!record.binding) record.binding = bindConfigurationEditor(host, editor, {pageMode: true});
    } else {
      this._settingsHost = host;
      if (!this._settingsBinding) this._settingsBinding = bindConfigurationEditor(host, editor, {pageMode: true});
    }
  }

  _renderSettingsCatalog(router) {
    if (this._hass?.user?.is_admin !== true || !router.settings?.length) return "";
    const sections = [...new Set(router.settings.map((item) => item.section))];
    return `<section class="administration-intro"><h2>Configuration editors</h2>
      <p>Load current settings, edit, then explicitly confirm a save. Opening an editor never changes the router.</p>
      <div class="sp-settings-catalog">${sections.map((section) => `<section><h3>${escapeHtml(section)}</h3>
      <div class="sp-settings-buttons">${router.settings.filter((item) => item.section === section).map((item) =>
        `<button type="button" data-open-setting="${escapeHtml(item.id)}"${!item.supported || !item.available ? " disabled" : ""}>${escapeHtml(item.title)}</button>`).join("")}</div></section>`).join("")}</div>
      <div data-settings-editor-host></div>
      <div data-maintenance-editor-host></div>
      <div data-file-transfer-editor-host></div>
      <div data-call-history-editor-host></div></section>`;
  }

  _renderAdministration(router, controls, reporting, accessSourceStates) {
    const payload =
      this._adminReadEntry === router.entry_id ? this._adminRead : undefined;
    const sections = new Map(
      (payload?.sections || []).map((section) => [section.id, section]),
    );
    const capabilities = new Set([
      ...(router.capabilities || []).map((capability) =>
        String(capability).toLowerCase(),
      ),
      ...(router.capability_families || []).map((family) =>
        String(family.name || "").toLowerCase(),
      ),
    ]);
    const sourceAvailable =
      accessSourceStates.protected_json?.available !== false;
    const adminReadAvailable = sourceAvailable && !this._adminReadError;
    const runtimeEntities = [...controls, ...reporting];
    const {tab, page} = this._currentAdminPage();
    const features = adminPageFeatures(page, ADMIN_IA);
    const settings = adminPageSettings(page, router.settings || [], SETTINGS_FEATURE_LINKS);
    const {inline, contextual} = adminPageSettingSections(page, router.settings || [], SETTINGS_FEATURE_LINKS);
    const canReadAdmin = this._hass?.user?.is_admin === true;
    const typedFeatures = new Set(canReadAdmin ? features.filter((feature) =>
      SETTINGS_FEATURE_LINKS[feature.id]?.complete && inline.some((setting) =>
        setting.supported && SETTINGS_FEATURE_LINKS[feature.id].ids.includes(setting.id))).map((feature) => feature.id) : []);
    const nativeControls = features.flatMap((feature) => runtimeEntities.filter((entity) =>
      !typedFeatures.has(feature.id) && isSemanticControl(entity) && adminFeatureForControl(entity) === feature.id));
    const nativeControlMarkup = features.map((feature) => {
      const owned = nativeControls.filter((entity) => adminFeatureForControl(entity) === feature.id);
      if (!owned.length) return "";
      const presentation = this._adminFeaturePresentation(feature, runtimeEntities, sections, capabilities, adminReadAvailable);
      return `<div data-admin-control-feature="${escapeHtml(feature.id)}"><span class="admin-control-status">${escapeHtml(this._t(`admin.feature.status.${presentation.key}`))}</span>${this._renderAdministrationEntities(owned, accessSourceStates)}</div>`;
    }).join("");
    const pageEntities = reporting.filter((entity) =>
      (page.entityGroups.includes(capabilityGroupFor(entity)) ||
        page.id === "internet_receiver_mode" && entity.translation_key === "receiver_led_mode") &&
      !(page.id === "internet_receiver_mode" && entity.translation_key === "receiver_led_mode" && typedFeatures.has("internet_receiver_led")) &&
      entity.access_source !== "integration");
    const nativeTabs = NATIVE_ADMIN_TABS.map((item) => `<button type="button" data-admin-tab="${escapeHtml(item.id)}"
      ${item.id === tab.id ? 'aria-current="page" class="active"' : ""}>
      <ha-icon icon="${escapeHtml(item.icon)}" aria-hidden="true"></ha-icon>${escapeHtml(item.title)}</button>`).join("");
    const parentId = page.parentId || page.id;
    const navigation = tab.pages.filter((item) => !item.parentId || item.parentId === parentId)
      .map((item) => `<button type="button" data-admin-page="${escapeHtml(item.id)}"
        class="${item.parentId ? "nested " : ""}${item.id === page.id ? "active" : ""}"
        ${item.id === page.id ? 'aria-current="page"' : ""}>${escapeHtml(item.title)}</button>`).join("");
    const forms = canReadAdmin && settings.length ? `<section class="admin-page-forms" aria-label="Page settings">
      ${inline.map((setting) => `<section class="admin-inline-settings" data-inline-setting="${escapeHtml(setting.id)}">
        <div data-settings-section="${escapeHtml(setting.id)}"><h3>${escapeHtml(setting.title)}</h3><p role="status">${this._settingsEditors.get(setting.id)?.error ? "Settings could not be loaded." : setting.supported && setting.available ?
          "Loading current settings…" : "Current settings are unavailable. Check management access and router capability."}</p>${this._settingsEditors.get(setting.id)?.error ?
          `<button type="button" class="secondary" data-retry-setting="${escapeHtml(setting.id)}">Refresh</button>` : ""}</div></section>`).join("")}
      ${contextual.length ? `<section class="admin-contextual-actions" aria-label="Actions"><h3>Actions</h3>${contextual.map((setting) =>
        `<button type="button" class="secondary" data-open-setting="${escapeHtml(setting.id)}"${!setting.supported || !setting.available ? " disabled" : ""}>${escapeHtml(setting.title)}</button>`).join("")}</section>` : ""}
      ${contextual.filter((setting) => this._settingsEditors.has(setting.id)).map((setting) =>
        `<div data-settings-section="${escapeHtml(setting.id)}"></div>`).join("")}
    </section>` : "";
    const overview = tab.id === "overview" ? `${this._renderRouterIdentity(router)}${this._renderAdminReadOverview()}` : "";
    const integrationTools = tab.id === "overview" ? `<details class="admin-native-section" data-detail-id="admin-integration-tools">
      <summary>Home Assistant integration tools</summary>
      ${this._renderAdminFeatureCatalog(ADMIN_IA.filter((area) => area.id === "home_assistant")
        .flatMap((area) => area.subsections.flatMap((section) => section.features)),
      runtimeEntities, sections, capabilities, adminReadAvailable, accessSourceStates, {canReadAdmin})}
    </details>` : "";
    const readSections = page.readSections || [];
    const featureReadSections = new Set(features.flatMap((feature) => feature.readSections.filter((sectionId) =>
      ADMIN_READ_SECTION_OWNER.get(sectionId) === feature.id)));
    const extraRead = canReadAdmin ? readSections.filter((id) => !featureReadSections.has(id)).map((id) =>
      this._renderAdminReadSection(id, sections.get(id), {sourceAvailable: adminReadAvailable})).join("") : "";
    return `
      <div class="administration-view admin-native">
        <nav class="admin-native-tabs" aria-label="Router administration categories">${nativeTabs}</nav>
        <div class="admin-native-layout">
          <aside class="admin-native-sidebar ${this._adminMenuOpen ? "menu-open" : ""}">
            <button type="button" class="admin-menu-toggle" data-admin-menu aria-expanded="${this._adminMenuOpen}" aria-controls="admin-page-navigation">
              <ha-icon icon="mdi:menu" aria-hidden="true"></ha-icon>${escapeHtml(tab.title)} · ${escapeHtml(page.title)}</button>
            <nav id="admin-page-navigation" aria-label="${escapeHtml(tab.title)} settings">${navigation}</nav>
          </aside>
          <section class="admin-native-page" aria-labelledby="admin-page-title" data-native-page="${escapeHtml(page.id)}">
            <header class="admin-page-heading"><div><span class="kicker">${escapeHtml(tab.title)}</span><h2 id="admin-page-title">${escapeHtml(page.title)}</h2></div>
              ${canReadAdmin ? '<span class="admin-local-badge"><ha-icon icon="mdi:lan" aria-hidden="true"></ha-icon>Local router settings</span>' : ""}</header>
            ${!canReadAdmin ? this._renderAdminReadOverview() : ""}
            ${this._adminReadError ? `<p class="admin-native-unavailable" role="status">${escapeHtml(this._t(this._adminReadError))} <button class="secondary compact" data-admin-refresh>Refresh status</button></p>` : ""}
            ${overview}
            ${nativeControlMarkup ? `<section class="admin-native-section admin-native-controls" aria-label="Current controls">${nativeControlMarkup}</section>` : ""}
            ${forms}
            <div data-settings-editor-host></div>
            <div data-maintenance-editor-host></div>
            <div data-file-transfer-editor-host></div>
            <div data-call-history-editor-host></div>
            ${this._renderAdminFeatureCatalog(features, runtimeEntities, sections, capabilities,
              adminReadAvailable, accessSourceStates, {canReadAdmin, pageMode: true, readSections})}
            ${extraRead}
            ${pageEntities.length ? `<section class="admin-native-section"><h3>Current status</h3>${this._renderAdministrationEntities(pageEntities, accessSourceStates)}</section>` : ""}
            ${integrationTools}
          </section>
        </div>
      </div>
    `;
  }

  _wanRecoveryDetails(source) {
    if (source?.state === "learning" && source.retrying !== true && source.success_samples_required === 5 &&
        Number.isSafeInteger(source.success_streak) && source.success_streak >= 0 && source.success_streak <= 5) {
      return `Successful polls ${source.success_streak}/${source.success_samples_required}`;
    }
    const remaining = source?.retry_in_seconds;
    if (source?.state !== "cooldown" || source.cooldown_seconds !== 60 ||
        typeof remaining !== "number" || !Number.isFinite(remaining) || remaining < 0 || remaining > 60) return "";
    if (remaining === 0) return "Waiting for next poll";
    // Report the last received estimate. No browser timer, extra router request
    // or exact dispatch promise; failures always start the same 60-second wait.
    const duration = formatPanelDurationSeconds(Math.ceil(remaining), this._locale(), this._language());
    return `Retry in ~${duration}`;
  }

  _renderDashboard(router, reporting, accessSourceStates) {
    const overview = renderDashboardOverview({
      router: {...router, entities: reporting}, states: this._hass?.states,
      trafficMarkup: `<div data-traffic-history-host>${renderTrafficHistory(this._trafficHistory.snapshot(), {language: this._language()})}</div>`,
      formatState: (state) => this._formatState(state),
    });
    const wan = accessSourceStates.wan_counters;
    const interval = Number(wan?.effective_interval_seconds);
    const recovery = this._wanRecoveryDetails(wan);
    const observed = wan?.observed_interval_seconds;
    const observedText = wan?.available === true && wan.supported !== false && wan.retrying !== true &&
      ["learning", "stable"].includes(wan.state) && typeof observed === "number" && Number.isFinite(observed) && observed > 0
      ? this._t("status.wan_observed_interval", {interval: new Intl.NumberFormat(this._language(), {maximumFractionDigits: 2}).format(observed)}) : "";
    const window = wan?.rate_window_seconds;
    const span = wan?.rate_sample_span_seconds;
    const formatSeconds = (seconds) => new Intl.NumberFormat(this._language(), {maximumFractionDigits: 2}).format(seconds);
    const averageText = typeof window === "number" && Number.isFinite(window) && window > 0
      ? this._t("status.wan_average_window", {interval: formatSeconds(window)}) : "";
    // The configured window is a target: warm-up and sparse replies can span
    // less or more time. Keep materially different actual spans explicit.
    const spanText = averageText && wan.available === true && wan.supported !== false && wan.retrying !== true &&
      ["learning", "stable"].includes(wan.state) && typeof span === "number" && Number.isFinite(span) && span > 0 &&
      Math.abs(span - window) >= window * 0.2
      ? this._t("status.wan_average_span", {interval: formatSeconds(span)}) : "";
    const cadence = wan && Number.isFinite(interval) && interval > 0
      ? `<p class="dashboard-cadence">${escapeHtml(this._t("status.wan_cadence", {interval}))} · ${escapeHtml(humanize(wan.state || wan.mode || ""))}${averageText ? ` · ${escapeHtml(averageText)}` : ""}${spanText ? ` · ${escapeHtml(spanText)}` : ""}${observedText ? ` · ${escapeHtml(observedText)}` : ""}${recovery ? ` · ${escapeHtml(recovery)}` : ""}</p>` : "";
    const deviceLink = router.root_device_id ? `<a href="/config/devices/device/${encodeURIComponent(router.root_device_id)}">All entities in Home Assistant</a>` : "";
    return `${overview}${cadence}<div class="dashboard-tools">${deviceLink}
      <button class="icon-button" data-refresh title="${escapeHtml(this._t("action.refresh_metadata"))}" aria-label="${escapeHtml(this._t("action.refresh_metadata"))}">
        <ha-icon icon="mdi:refresh" aria-hidden="true"></ha-icon></button></div>`;
  }

  _renderViewTabs(router) {
    const administration = this._canShowAdministration(router)
      ? `
        <button
          data-view="administration"
          class="${this._activeView === "administration" ? "active" : ""}"
          ${this._activeView === "administration" ? 'aria-current="page"' : ""}
        >
          <ha-icon icon="mdi:cog-outline" aria-hidden="true"></ha-icon>
          ${escapeHtml(this._t("view.administration"))}
        </button>
      `
      : "";
    return `
      <nav class="view-tabs" aria-label="${escapeHtml(this._t("view.tabs.label"))}">
        <button
          data-view="dashboard"
          class="${this._activeView === "dashboard" ? "active" : ""}"
          ${this._activeView === "dashboard" ? 'aria-current="page"' : ""}
        >
          <ha-icon icon="mdi:view-dashboard-outline" aria-hidden="true"></ha-icon>
          ${escapeHtml(this._t("view.dashboard"))}
        </button>
        ${administration}
      </nav>
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
    if (pending.actionId === "dect_repeater_enroll") {
      describedByIds.push("speedport-repeater-prerequisite-warning");
    }
    if (pending.recovery) describedByIds.push("speedport-action-recovery");
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
    const prerequisiteEditor =
      pending.actionId === "dect_repeater_enroll"
        ? `
          <p id="speedport-repeater-prerequisite-warning" class="confirm-warning"><ha-icon icon="mdi:alert-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._t("admin.action.dect_repeater_enroll.pin_warning"))}</p>
          <label class="confirm-assertion">
            <input
              data-repeater-prerequisite="pinIsDefault"
              type="checkbox"
              ${pending.pinIsDefault ? "checked" : ""}
              ${this._actionBusy ? "disabled" : ""}
            >
            <span>${escapeHtml(this._t("admin.action.dect_repeater_enroll.pin_assertion"))}</span>
          </label>
          <label class="confirm-assertion">
            <input
              data-repeater-prerequisite="fullPowerEnabled"
              type="checkbox"
              ${pending.fullPowerEnabled ? "checked" : ""}
              ${this._actionBusy ? "disabled" : ""}
            >
            <span>${escapeHtml(this._t("admin.action.dect_repeater_enroll.power_assertion"))}</span>
          </label>
          <label class="confirm-assertion">
            <input
              data-repeater-prerequisite="fullEcoDisabled"
              type="checkbox"
              ${pending.fullEcoDisabled ? "checked" : ""}
              ${this._actionBusy ? "disabled" : ""}
            >
            <span>${escapeHtml(this._t("admin.action.dect_repeater_enroll.eco_assertion"))}</span>
          </label>
        `
        : "";
    const recoveryWarning = pending.recovery
      ? `<p id="speedport-action-recovery" class="confirm-warning action-recovery"><ha-icon icon="mdi:backup-restore" aria-hidden="true"></ha-icon>${escapeHtml(pending.recovery)}</p>`
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
          ${recoveryWarning}
          ${prerequisiteEditor}
          ${confirmationEditor}
          <div class="confirm-actions">
            <button class="secondary" data-cancel-action ${this._actionBusy ? "disabled" : ""}>
              ${escapeHtml(this._t("action.cancel"))}
            </button>
            <button class="primary" data-confirm-action ${
              this._actionBusy ||
              (pending.actionId === "dect_repeater_enroll" &&
                (!pending.pinIsDefault ||
                  !pending.fullPowerEnabled ||
                  !pending.fullEcoDisabled)) ||
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

  _renderRouterIdentity(router) {
    const fields = [
      ["hero.firmware", router.firmware],
      ["hero.hardware_version", router.hardware_version],
    ]
      .filter(([, value]) => typeof value === "string" && value.trim())
      .map(([labelKey, value]) => [labelKey, value.trim()]);
    if (fields.length === 0) return "";
    return `
      <dl class="router-identity">
        ${fields
          .map(
            ([labelKey, value]) => `
              <div>
                <dt>${escapeHtml(this._t(labelKey))}</dt>
                <dd>${escapeHtml(value)}</dd>
              </div>
            `,
          )
          .join("")}
      </dl>
    `;
  }

  _render() {
    this._flushAdminSessionInvalidation();
    if (!this.shadowRoot) return;
    const activeEditorElement = this.shadowRoot.activeElement;
    const trafficView = this._trafficHistory.snapshot();
    if (this.isConnected && this._activeView === "dashboard" && this._currentRouter()?.entry_state === "loaded" &&
        trafficView?.entryId === this._currentRouter()?.entry_id && trafficView?.userId === this._hass?.user?.id &&
        activeEditorElement && activeEditorElement === this._trafficHost?.querySelector?.("[data-traffic-window]")) {
      // Keep the native select connected while still refreshing graph data and
      // stale/cooldown readouts. Repaint the rest of the page after focus leaves.
      if (refreshTrafficHistoryContent(this._trafficHost, trafficView, {language: this._language()})) {
        this._trafficBinding?.refresh();
      }
      this._trafficWindowRenderPending = true;
      return;
    }
    this._trafficWindowRenderPending = false;
    const privateFocus = activeEditorElement &&
      [this._settingsHost, ...[...this._settingsEditors.values()].map((record) => record.host), this._maintenanceHost, this._fileTransferHost, this._callHistoryHost]
        .some((host) => host?.contains?.(activeEditorElement)) ? activeEditorElement : undefined;
    const privateSelection = privateFocus && typeof privateFocus.selectionStart === "number"
      ? [privateFocus.selectionStart, privateFocus.selectionEnd] : undefined;
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

    const { controls, reporting } = splitPanelEntities(router.entities);
    if (
      this._activeView === "administration" &&
      !this._canShowAdministration(router)
    ) {
      this._activeView = "dashboard";
    }
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

    const viewContent =
      this._activeView === "administration"
        ? this._renderAdministration(
            router,
            controls,
            reporting,
            accessSourceStates,
          )
        : this._renderDashboard(router, reporting, accessSourceStates);
    const notice = this._notice
      ? `<div class="notice" role="${this._noticeKind}" aria-live="${this._noticeKind === "alert" ? "assertive" : "polite"}"><ha-icon icon="mdi:information-outline" aria-hidden="true"></ha-icon>${escapeHtml(this._notice)}</div>`
      : "";

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <main class="shell ${this._activeView === "administration" ? "administration-shell" : "dashboard-shell"}" ${this._pendingAction ? 'inert aria-hidden="true"' : ""}>
        <header class="hero">
          <div class="hero-copy">
            <div class="eyebrow">
              <span class="telekom-dots" aria-hidden="true"><i></i><i></i><i></i></span>
              ${escapeHtml(this._t("hero.eyebrow"))}
            </div>
            <h1>${escapeHtml(router.title)}</h1>
            ${router.model ? `<p>${escapeHtml(router.model)}</p>` : ""}
            ${this._renderRouterIdentity(router)}
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
        ${this._renderViewTabs(router)}
        ${notice}
        ${this._activeView === "administration" || !this._adminManagementAvailable(this._hass, router) ? this._renderManagement(router) : ""}
        ${viewContent}

        <footer>
          <span>Telekom Speedport Smart</span>
          <span>${escapeHtml(this._t("footer.local"))}</span>
        </footer>
      </main>
      ${this._renderConfirmation()}
    `;
    // Keep the same private editor DOM on telemetry refreshes. Never rehydrate
    // passwords or clear an in-progress draft because WAN statistics changed.
    for (const [settingId, record] of this._settingsEditors) {
      const placeholder = this.shadowRoot.querySelector(`[data-settings-section="${settingId}"]`);
      if (placeholder && record.host && placeholder !== record.host) placeholder.replaceWith(record.host);
      else if (placeholder && !record.host) this._renderSettingsEditor(record.editor);
    }
    const settingsPlaceholder = this.shadowRoot.querySelector("[data-settings-editor-host]");
    if (settingsPlaceholder && this._settingsHost && settingsPlaceholder !== this._settingsHost &&
        ![...this._settingsEditors].some(([id, record]) => record.host === this._settingsHost &&
          this.shadowRoot.querySelector(`[data-settings-section="${id}"]`))) {
      settingsPlaceholder.replaceWith(this._settingsHost);
    }
    const maintenancePlaceholder = this.shadowRoot.querySelector("[data-maintenance-editor-host]");
    if (maintenancePlaceholder && this._maintenanceHost && maintenancePlaceholder !== this._maintenanceHost) {
      maintenancePlaceholder.replaceWith(this._maintenanceHost);
    }
    const transferPlaceholder = this.shadowRoot.querySelector("[data-file-transfer-editor-host]");
    if (transferPlaceholder && this._fileTransferHost && transferPlaceholder !== this._fileTransferHost) {
      transferPlaceholder.replaceWith(this._fileTransferHost);
    }
    const callHistoryPlaceholder = this.shadowRoot.querySelector("[data-call-history-editor-host]");
    if (callHistoryPlaceholder && this._callHistoryHost && callHistoryPlaceholder !== this._callHistoryHost) {
      callHistoryPlaceholder.replaceWith(this._callHistoryHost);
    }
    const trafficPlaceholder = this.shadowRoot.querySelector("[data-traffic-history-host]");
    if (trafficPlaceholder) {
      if (this._trafficHost && trafficPlaceholder !== this._trafficHost) {
        this._trafficHost.innerHTML = trafficPlaceholder.innerHTML;
        trafficPlaceholder.replaceWith(this._trafficHost);
      } else this._trafficHost = trafficPlaceholder;
      if (!this._trafficBinding) this._trafficBinding = bindTrafficHistory(this._trafficHost, this._trafficHistory);
      this._trafficBinding.refresh();
    }
    restoreDetailsState(this.shadowRoot, renderState);
    if (this._pendingAction) {
      window.requestAnimationFrame(() => {
        const dialog = this.shadowRoot.querySelector(".confirm-dialog");
        const editor = this.shadowRoot.querySelector(
          "[data-text-draft]:not([disabled]), [data-select-draft]:not([disabled]), [data-confirm-draft]:not([disabled]), [data-repeater-prerequisite]:not([disabled])",
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
    } else if (this._focusAfterPrivateQuery) {
      const query = this._focusAfterPrivateQuery;
      this._focusAfterPrivateQuery = undefined;
      window.requestAnimationFrame(() => {
        this.shadowRoot
          .querySelector(`[data-admin-query-result="${query}"]`)
          ?.focus();
      });
    } else if (this._focusAfterAdminAction) {
      const focusKey = this._focusAfterAdminAction;
      this._focusAfterAdminAction = undefined;
      window.requestAnimationFrame(() => {
        let restored = false;
        for (const element of this.shadowRoot.querySelectorAll(
          "[data-admin-action-key]",
        )) {
          if (element.dataset.adminActionKey === focusKey) {
            element.focus();
            restored = true;
            break;
          }
        }
        if (!restored) {
          const actionId = focusKey.split(":", 1)[0];
          const featureId = ADMIN_ACTION_INFO[actionId]?.featureId;
          for (const element of this.shadowRoot.querySelectorAll(
            "[data-admin-feature]",
          )) {
            if (element.dataset.adminFeature === featureId) {
              (element.querySelector?.("summary") || element).focus?.();
              break;
            }
          }
        }
      });
    } else if (privateFocus?.isConnected) {
      privateFocus.focus?.({preventScroll: true});
      if (privateSelection) privateFocus.setSelectionRange?.(...privateSelection);
    } else if (renderState.focus) {
      window.requestAnimationFrame(() => {
        restoreFocusState(this.shadowRoot, renderState);
      });
    }
  }

  _styles() {
    return `
      <style>
        ${DASHBOARD_OVERVIEW_STYLES}
        ${TRAFFIC_HISTORY_STYLES}
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
          width: 100%;
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
        .router-identity {
          display: flex;
          flex-wrap: wrap;
          gap: 8px 18px;
          margin: -12px 0 24px;
        }
        .router-identity div {
          display: flex;
          min-width: 0;
          gap: 6px;
          font-size: 12px;
        }
        .router-identity dt { opacity: .72; }
        .router-identity dd {
          margin: 0;
          overflow-wrap: anywhere;
          font-weight: 700;
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
          background: rgba(255,255,255,.46);
          box-shadow: none;
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
        .view-tabs {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 6px;
          width: 100%;
          margin: 22px auto 0;
          padding: 5px;
          border: 1px solid var(--sp-border);
          border-radius: 16px;
          background: var(--sp-surface-soft);
        }
        .view-tabs button {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          min-height: 46px;
          padding: 10px 16px;
          color: var(--sp-muted);
          border: 0;
          border-radius: 11px;
          background: transparent;
          cursor: pointer;
          font-weight: 700;
        }
        .view-tabs button.active {
          color: var(--sp-text);
          background: var(--sp-surface);
          box-shadow: 0 4px 16px rgba(0,0,0,.08);
        }
        .view-tabs button:only-child { grid-column: 1 / -1; }
        .view-tabs ha-icon { --mdc-icon-size: 20px; }
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
        .administration-view { width: 100%; min-width: 0; }
        .administration-shell .hero { min-height: 0; padding: 22px 28px; border-radius: 20px; }
        .administration-shell .hero h1 { font-size: clamp(23px, 2.5vw, 32px); margin: 6px 0; }
        .administration-shell .hero .eyebrow,
        .administration-shell .hero .router-identity,
        .administration-shell .hero .router-visual,
        .administration-shell .hero-copy > p { display: none; }
        .administration-shell .hero-status { margin-top: 8px; }
        .dashboard-shell .hero { min-height: 0; padding: 20px 28px; border-radius: 22px; }
        .dashboard-shell .hero h1 { font-size: clamp(23px, 2.5vw, 32px); margin: 0; }
        .dashboard-shell .hero .eyebrow,
        .dashboard-shell .hero .router-identity,
        .dashboard-shell .hero .router-visual,
        .dashboard-shell .hero-copy > p { display: none; }
        .dashboard-shell .hero-status { margin-top: 10px; }
        .dashboard-shell .view-tabs { margin: 16px 0 20px; }
        .dashboard-cadence { color: var(--sp-muted); font-size: 12px; margin: 14px 0 0; }
        .dashboard-tools { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-top: 16px; font-size: 13px; }
        .dashboard-tools a { color: var(--sp-magenta); }
        .administration-shell .view-tabs { margin-top: 14px; padding: 4px; }
        .administration-shell .view-tabs button { min-height: 42px; padding-block: 10px; }
        .administration-shell .management-alert:not(.warning):not(.caution) { margin-top: 12px; padding: 12px 18px; }
        .administration-shell .management-alert:not(.warning):not(.caution) p { display: none; }
        .admin-native { margin-top: 22px; }
        .admin-native-tabs { display: flex; gap: 4px; overflow-x: auto; padding: 6px; border: 1px solid var(--sp-border); border-radius: 16px; background: var(--sp-surface); }
        .admin-native-tabs button { flex: 1 0 auto; display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 48px; padding: 10px 18px; border: 0; border-radius: 11px; background: transparent; color: var(--sp-muted); cursor: pointer; font-weight: 650; }
        .admin-native-tabs button.active { color: var(--sp-magenta); background: color-mix(in srgb, var(--sp-magenta) 10%, var(--sp-surface)); }
        .admin-native-tabs ha-icon { --mdc-icon-size: 21px; }
        .admin-native-layout { display: grid; grid-template-columns: 235px minmax(0, 1fr); gap: 22px; align-items: start; margin-top: 20px; }
        .admin-native-sidebar { position: sticky; top: 16px; min-width: 0; padding: 10px; border: 1px solid var(--sp-border); border-radius: 16px; background: var(--sp-surface); }
        .admin-native-sidebar nav { display: grid; gap: 3px; }
        .admin-native-sidebar nav button { text-align: left; min-height: 44px; padding: 11px 13px; border: 0; border-radius: 9px; background: transparent; color: var(--sp-text); cursor: pointer; font-size: 14px; overflow-wrap: anywhere; }
        .admin-native-sidebar nav button.nested { margin-inline-start: 12px; padding-inline-start: 16px; border-inline-start: 2px solid var(--sp-border); border-radius: 0 9px 9px 0; color: var(--sp-muted); font-size: 13px; }
        .admin-native-sidebar nav button.active { color: var(--sp-magenta); background: color-mix(in srgb, var(--sp-magenta) 9%, var(--sp-surface)); font-weight: 700; border-color: var(--sp-magenta); }
        .admin-native button:focus-visible { outline: 3px solid var(--sp-magenta); outline-offset: 3px; }
        .admin-native button:hover:not(:disabled) { filter: brightness(.96); }
        .admin-native-page { min-width: 0; width: 100%; }
        .admin-page-heading { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 6px 2px 18px; }
        .admin-page-heading h2 { margin: 6px 0 0; font-size: clamp(22px, 2.4vw, 30px); }
        .admin-local-badge { display: flex; align-items: center; gap: 7px; color: var(--sp-muted); font-size: 12px; white-space: nowrap; }
        .admin-local-badge ha-icon { --mdc-icon-size: 17px; }
        .admin-menu-toggle { display: none; }
        .admin-native-page .admin-read-overview { margin-top: 0; }
        .admin-native-page > .router-identity { padding: 20px; border: 1px solid var(--sp-border); border-radius: 16px; background: var(--sp-surface); }
        .admin-form-nav { display: flex; flex-wrap: wrap; gap: 7px; padding-bottom: 14px; }
        .admin-form-nav button { min-height: 40px; padding: 9px 13px; border: 1px solid var(--sp-border); border-radius: 9px; background: var(--sp-surface); color: var(--sp-text); cursor: pointer; font-size: 13px; }
        .admin-form-nav button.active { border-color: var(--sp-magenta); color: var(--sp-magenta); background: color-mix(in srgb, var(--sp-magenta) 6%, var(--sp-surface)); }
        .admin-form-nav button:disabled { color: var(--sp-muted); cursor: not-allowed; opacity: .65; }
        .admin-native-section { min-width: 0; padding: 22px; margin-top: 16px; border: 1px solid var(--sp-border); border-radius: 16px; background: var(--sp-surface); }
        .admin-native-section > header { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
        .admin-native-section h3 { font-size: 16px; margin: 0 auto 0 0; }
        .admin-native-section > h3 { margin-bottom: 14px; }
        .admin-native-controls { margin: 0 0 16px; }
        .admin-control-status { display: block; margin: 4px 0 8px; color: var(--sp-muted); font-size: 12px; }
        .admin-native-section .admin-feature-owned { border: 0; padding: 0; }
        .admin-native-page .admin-feature-catalog { display: block; margin-top: 0; }
        .admin-native-unavailable { color: var(--sp-muted); line-height: 1.5; font-size: 14px; padding: 14px; border: 1px solid var(--sp-border); border-radius: 12px; background: var(--sp-surface-soft); }
        .admin-native-page [data-settings-editor-host]:not(:empty) { margin-top: 0; }
        @media (max-width: 760px) {
          .administration-shell .hero { padding: 18px; }
          .admin-native-layout { grid-template-columns: minmax(0, 1fr); gap: 16px; }
          .admin-native-tabs button { padding: 9px 13px; min-height: 44px; font-size: 13px; }
          .admin-native-tabs ha-icon { display: none; }
          .admin-native-sidebar { position: static; padding: 8px; }
          .admin-menu-toggle { width: 100%; display: flex; align-items: center; gap: 10px; padding: 10px; min-height: 44px; border: 0; background: transparent; color: var(--sp-text); text-align: left; cursor: pointer; }
          .admin-native-sidebar nav { display: none; }
          .admin-native-sidebar.menu-open nav { display: grid; padding-top: 8px; border-top: 1px solid var(--sp-border); }
          .admin-local-badge { display: none; }
          .admin-native-section { padding: 16px; }
        }
        .sp-settings-catalog { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 18px; }
        .sp-settings-catalog h3 { margin: 8px 0; font-size: 15px; }
        .sp-settings-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
        .sp-settings-buttons button { padding: 10px 14px; border: 1px solid var(--divider-color); border-radius: 10px; background: var(--secondary-background-color); color: var(--primary-text-color); cursor: pointer; }
        .sp-settings-buttons button:disabled { opacity: .5; cursor: default; }
        [data-settings-editor-host]:not(:empty) { margin-top: 20px; width: 100%; min-width: 0; }
        .administration-intro,
        .admin-read-overview {
          width: 100%;
          margin-top: 24px;
          padding: clamp(18px, 3vw, 28px);
          border: 1px solid var(--sp-border);
          border-radius: 22px;
          background: var(--sp-surface);
          box-shadow: 0 10px 32px rgba(0,0,0,.045);
        }
        .administration-intro h2,
        .admin-read-overview h2 {
          margin: 5px 0 4px;
          font-size: 22px;
        }
        .administration-intro p,
        .admin-read-overview header p,
        .administration-empty p {
          margin: 0;
          color: var(--sp-muted);
          line-height: 1.5;
        }
        .admin-read-overview > header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 18px;
          margin-bottom: 18px;
        }
        .admin-read-overview.restricted {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          align-items: center;
          gap: 16px;
        }
        .admin-read-overview.restricted > ha-icon {
          color: var(--sp-muted);
          --mdc-icon-size: 30px;
        }
        .administration-areas {
          display: grid;
          gap: 14px;
          width: 100%;
          margin-top: 18px;
        }
        .administration-area,
        .administration-subsection {
          min-width: 0;
          border: 1px solid var(--sp-border);
          background: var(--sp-surface);
        }
        .administration-area {
          border-radius: 20px;
          box-shadow: 0 10px 32px rgba(0,0,0,.045);
        }
        .administration-subsection {
          border-radius: 15px;
          background: var(--sp-surface-soft);
        }
        .administration-area > summary,
        .administration-subsection > summary {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto auto;
          align-items: center;
          gap: 12px;
          min-height: 64px;
          padding: 13px 16px;
          cursor: pointer;
          list-style: none;
        }
        .administration-area > summary { min-height: 72px; padding-inline: 20px; }
        .administration-area > summary::-webkit-details-marker,
        .administration-subsection > summary::-webkit-details-marker {
          display: none;
        }
        .administration-summary-icon {
          display: grid;
          place-items: center;
          width: 40px;
          height: 40px;
          color: var(--sp-magenta);
          border-radius: 12px;
          background: color-mix(in srgb, var(--sp-magenta) 8%, var(--sp-surface));
        }
        .administration-summary-icon ha-icon { --mdc-icon-size: 22px; }
        .administration-summary-copy { min-width: 0; }
        .administration-summary-copy strong,
        .administration-summary-copy small { display: block; }
        .administration-summary-copy small {
          margin-top: 3px;
          color: var(--sp-muted);
          font-size: 11px;
        }
        .administration-chevron {
          color: var(--sp-muted);
          transition: transform .16s ease;
          --mdc-icon-size: 21px;
        }
        .administration-area[open] > summary .administration-chevron,
        .administration-subsection[open] > summary .administration-chevron {
          transform: rotate(180deg);
        }
        .administration-subsections {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
          padding: 0 16px 16px;
          border-top: 1px solid var(--sp-border);
        }
        .administration-subsection { margin-top: 14px; }
        .administration-subsection[open] { grid-column: 1 / -1; }
        .administration-subsection-content {
          display: grid;
          gap: 12px;
          padding: 0 14px 14px;
          border-top: 1px solid var(--sp-border);
        }
        .admin-query-card {
          min-width: 0;
          padding: 14px;
          border: 1px solid color-mix(in srgb, var(--sp-magenta) 24%, var(--sp-border));
          border-radius: 14px;
          background: color-mix(in srgb, var(--sp-magenta) 3%, var(--sp-surface-soft));
        }
        .admin-query-heading {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: start;
          gap: 11px;
        }
        .admin-query-heading > span:first-child {
          display: grid;
          place-items: center;
          width: 36px;
          height: 36px;
          color: var(--sp-magenta);
          border-radius: 11px;
          background: var(--sp-surface);
        }
        .admin-query-heading ha-icon { --mdc-icon-size: 20px; }
        .admin-query-heading strong { display: block; font-size: 13px; }
        .admin-query-heading p {
          margin: 4px 0 0;
          color: var(--sp-muted);
          font-size: 11px;
          line-height: 1.45;
        }
        .admin-query-read-only {
          padding: 5px 8px;
          color: var(--sp-success);
          border: 1px solid color-mix(in srgb, var(--sp-success) 35%, var(--sp-border));
          border-radius: 999px;
          background: var(--sp-surface);
          font-size: 9px;
          font-weight: 800;
          white-space: nowrap;
        }
        .admin-query-form {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: start;
          gap: 10px;
          margin-top: 14px;
        }
        .admin-query-form.phonebook {
          grid-template-columns: minmax(130px, .45fr) minmax(160px, 1fr) auto;
        }
        .admin-query-form label { display: grid; gap: 5px; min-width: 0; }
        .admin-query-form label > span {
          color: var(--sp-muted);
          font-size: 10px;
          font-weight: 700;
        }
        .admin-query-form input,
        .admin-query-form select {
          width: 100%;
          min-height: 44px;
          padding: 9px 11px;
          color: var(--sp-text);
          border: 1px solid var(--sp-border);
          border-radius: 10px;
          background: var(--sp-surface);
          font: inherit;
        }
        .admin-query-form input[aria-invalid="true"] { border-color: var(--sp-error); }
        .admin-query-form label small {
          color: var(--sp-muted);
          font-size: 9px;
          line-height: 1.35;
        }
        .admin-query-form .primary { align-self: start; }
        .admin-query-input-error {
          min-height: 13px;
          color: var(--sp-error) !important;
        }
        .admin-query-unavailable,
        .admin-query-status,
        .admin-query-warning {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 12px 0 0;
          padding: 10px 12px;
          border: 1px solid var(--sp-border);
          border-radius: 10px;
          color: var(--sp-muted);
          background: var(--sp-surface);
          font-size: 11px;
          line-height: 1.4;
        }
        .admin-query-status.error {
          color: var(--sp-error);
          border-color: color-mix(in srgb, var(--sp-error) 35%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-error) 6%, var(--sp-surface));
        }
        .admin-query-status .loading-mark {
          display: flex;
          align-items: flex-end;
          gap: 3px;
          height: 15px;
        }
        .admin-query-status .loading-mark i {
          width: 4px;
          height: 4px;
          border-radius: 1px;
          background: var(--sp-magenta);
        }
        .admin-query-status .loading-mark i:nth-child(2) { height: 12px; }
        .admin-query-status ha-icon,
        .admin-query-unavailable ha-icon,
        .admin-query-warning ha-icon { flex: none; --mdc-icon-size: 18px; }
        .admin-query-warning { color: var(--sp-warning); }
        .admin-query-result {
          min-width: 0;
          margin-top: 12px;
          padding: 12px;
          border: 1px solid var(--sp-border);
          border-radius: 12px;
          background: var(--sp-surface);
        }
        .admin-query-result:focus-visible {
          outline: 2px solid var(--sp-magenta);
          outline-offset: 2px;
        }
        .admin-query-result > header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
        }
        .admin-query-result > header strong,
        .admin-query-result > header small { display: block; }
        .admin-query-result > header strong { font-size: 12px; }
        .admin-query-result > header small {
          margin-top: 2px;
          color: var(--sp-muted);
          font-size: 9px;
        }
        .secondary.compact {
          flex: none;
          min-height: 36px;
          padding: 7px 10px;
          font-size: 10px;
        }
        .admin-query-values {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
          gap: 9px 12px;
          margin: 12px 0 0;
        }
        .admin-query-values div { min-width: 0; }
        .admin-query-values dt {
          color: var(--sp-muted);
          font-size: 9px;
          font-weight: 700;
        }
        .admin-query-values dd {
          margin: 3px 0 0;
          overflow-wrap: anywhere;
          font-size: 11px;
        }
        .admin-query-entries { display: grid; gap: 7px; margin-top: 12px; }
        .admin-query-entry {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: center;
          gap: 10px;
          min-width: 0;
          padding: 9px 10px;
          border-radius: 10px;
          background: var(--sp-surface-soft);
        }
        .admin-query-entry strong,
        .admin-query-entry small {
          display: block;
          overflow-wrap: anywhere;
        }
        .admin-query-entry strong { font-size: 11px; }
        .admin-query-entry small { margin-top: 2px; color: var(--sp-muted); font-size: 10px; }
        .admin-query-empty { margin: 12px 0 0; color: var(--sp-muted); font-size: 11px; }
        .admin-action-card {
          min-width: 0;
          padding: 14px;
          border: 1px solid color-mix(in srgb, var(--sp-warning) 28%, var(--sp-border));
          border-radius: 14px;
          background: color-mix(in srgb, var(--sp-warning) 3%, var(--sp-surface-soft));
        }
        .admin-action-card.risk-disruptive {
          border-color: color-mix(in srgb, var(--sp-error) 32%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-error) 3%, var(--sp-surface-soft));
        }
        .admin-action-card.risk-destructive {
          border-color: color-mix(in srgb, var(--sp-error) 48%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-error) 5%, var(--sp-surface-soft));
        }
        .admin-action-heading {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: start;
          gap: 11px;
        }
        .admin-action-heading > span:first-child {
          display: grid;
          place-items: center;
          width: 36px;
          height: 36px;
          color: var(--sp-warning);
          border-radius: 11px;
          background: var(--sp-surface);
        }
        .admin-action-card.risk-disruptive .admin-action-heading > span:first-child,
        .admin-action-card.risk-destructive .admin-action-heading > span:first-child {
          color: var(--sp-error);
        }
        .admin-action-heading ha-icon { --mdc-icon-size: 20px; }
        .admin-action-heading strong { display: block; font-size: 13px; }
        .admin-action-heading p {
          margin: 4px 0 0;
          color: var(--sp-muted);
          font-size: 11px;
          line-height: 1.45;
        }
        .admin-action-confirmation {
          padding: 5px 8px;
          color: var(--sp-warning);
          border: 1px solid color-mix(in srgb, var(--sp-warning) 38%, var(--sp-border));
          border-radius: 999px;
          background: var(--sp-surface);
          font-size: 9px;
          font-weight: 800;
          white-space: nowrap;
        }
        .admin-action-card.risk-disruptive .admin-action-confirmation,
        .admin-action-card.risk-destructive .admin-action-confirmation {
          color: var(--sp-error);
          border-color: color-mix(in srgb, var(--sp-error) 38%, var(--sp-border));
        }
        .admin-action-impact {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          margin: 12px 0 0;
          padding: 10px 12px;
          color: var(--sp-error);
          border: 1px solid color-mix(in srgb, var(--sp-error) 35%, var(--sp-border));
          border-radius: 10px;
          background: color-mix(in srgb, var(--sp-error) 6%, var(--sp-surface));
          font-size: 11px;
          font-weight: 700;
          line-height: 1.45;
        }
        .admin-action-impact ha-icon { flex: none; --mdc-icon-size: 18px; }
        .admin-action-context {
          display: grid;
          gap: 6px;
          margin-top: 12px;
          color: var(--sp-muted);
          font-size: 11px;
          font-weight: 700;
        }
        .admin-action-context select {
          width: 100%;
          min-height: 40px;
          padding: 8px 10px;
          color: var(--sp-text);
          border: 1px solid var(--sp-border);
          border-radius: 10px;
          background: var(--sp-surface);
          font: inherit;
        }
        .admin-action-card > .primary,
        .admin-action-card > .secondary { margin-top: 13px; }
        .admin-action-status {
          display: flex;
          align-items: center;
          gap: 8px;
          margin: 12px 0 0;
          padding: 10px 12px;
          color: var(--sp-muted);
          border: 1px solid var(--sp-border);
          border-radius: 10px;
          background: var(--sp-surface);
          font-size: 11px;
          line-height: 1.4;
        }
        .admin-action-status.error { color: var(--sp-error); }
        .admin-action-status.warning { color: var(--sp-warning); }
        .admin-action-status ha-icon { flex: none; --mdc-icon-size: 18px; }
        .admin-action-status .loading-mark {
          display: flex;
          align-items: flex-end;
          gap: 3px;
          height: 15px;
        }
        .admin-action-status .loading-mark i {
          width: 4px;
          height: 4px;
          border-radius: 1px;
          background: var(--sp-magenta);
        }
        .admin-action-status .loading-mark i:nth-child(2) { height: 12px; }
        .admin-action-targets { display: grid; gap: 8px; margin-top: 12px; }
        .admin-action-target {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          align-items: center;
          gap: 10px;
          min-width: 0;
          padding: 10px;
          border-radius: 11px;
          background: var(--sp-surface);
        }
        .admin-action-target strong,
        .admin-action-target small { display: block; overflow-wrap: anywhere; }
        .admin-action-target strong { font-size: 12px; }
        .admin-action-target small { margin-top: 3px; color: var(--sp-muted); font-size: 10px; }
        .admin-feature-catalog {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
          gap: 10px;
          width: 100%;
          padding-top: 14px;
        }
        .admin-feature-card {
          min-width: 0;
          padding: 12px;
          border: 1px solid var(--sp-border);
          border-radius: 13px;
          background: var(--sp-surface);
        }
        .admin-feature-card:not(details),
        .admin-feature-summary {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          align-items: start;
          gap: 11px;
        }
        .admin-feature-summary {
          grid-template-columns: auto minmax(0, 1fr) auto;
          cursor: pointer;
          list-style: none;
        }
        .admin-feature-summary::-webkit-details-marker { display: none; }
        .admin-feature-chevron {
          align-self: center;
          color: var(--sp-muted);
          transition: transform .16s ease;
          --mdc-icon-size: 20px;
        }
        .admin-feature-card[open] > .admin-feature-summary .admin-feature-chevron {
          transform: rotate(180deg);
        }
        .admin-feature-card.status-control_available {
          border-color: color-mix(in srgb, var(--sp-success) 40%, var(--sp-border));
        }
        .admin-feature-card.status-temporarily_unavailable,
        .admin-feature-card.status-control_unavailable {
          border-color: color-mix(in srgb, var(--sp-warning) 42%, var(--sp-border));
        }
        .admin-feature-card.status-not_observed { opacity: .76; }
        .admin-feature-card.risk-sensitive {
          border-color: color-mix(in srgb, var(--sp-warning) 30%, var(--sp-border));
        }
        .admin-feature-card.risk-disruptive,
        .admin-feature-card.risk-lockout {
          border-color: color-mix(in srgb, var(--sp-error) 22%, var(--sp-border));
        }
        .admin-feature-card.destructive-candidate {
          border-color: color-mix(in srgb, var(--sp-error) 30%, var(--sp-border));
        }
        .admin-feature-card.has-owned-content {
          grid-column: 1 / -1;
        }
        .admin-feature-icon {
          display: grid;
          place-items: center;
          width: 34px;
          height: 34px;
          color: var(--sp-muted);
          border-radius: 10px;
          background: var(--sp-surface-soft);
        }
        .status-control_available .admin-feature-icon { color: var(--sp-success); }
        .status-temporarily_unavailable .admin-feature-icon,
        .status-control_unavailable .admin-feature-icon { color: var(--sp-warning); }
        .admin-feature-icon ha-icon { --mdc-icon-size: 20px; }
        .admin-feature-copy { min-width: 0; }
        .admin-feature-copy > strong {
          display: block;
          overflow-wrap: anywhere;
          font-size: 13px;
          line-height: 1.35;
        }
        .admin-feature-blocked-reason {
          display: block;
          margin-top: 8px;
          color: var(--sp-muted);
          font-size: 11px;
          line-height: 1.45;
          overflow-wrap: anywhere;
        }
        .admin-feature-owned {
          display: grid;
          gap: 12px;
          min-width: 0;
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid var(--sp-border);
        }
        .admin-feature-owned > .administration-entity-grid {
          padding-top: 0;
        }
        .admin-feature-owned > .admin-read-section {
          margin-top: 0;
        }
        .administration-subsection-overview {
          min-width: 0;
        }
        .admin-feature-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
          margin-top: 8px;
        }
        .admin-feature-status,
        .admin-contract-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          min-height: 22px;
          padding: 3px 7px;
          border: 1px solid var(--sp-border);
          border-radius: 999px;
          color: var(--sp-muted);
          background: var(--sp-surface-soft);
          font-size: 9px;
          font-weight: 800;
          line-height: 1.15;
        }
        .status-control_available .admin-feature-status,
        .admin-contract-badge.contract-reviewed {
          color: var(--sp-success);
          border-color: color-mix(in srgb, var(--sp-success) 38%, var(--sp-border));
        }
        .status-temporarily_unavailable .admin-feature-status,
        .status-control_unavailable .admin-feature-status,
        .admin-contract-badge.contract-blocked {
          color: var(--sp-warning);
          border-color: color-mix(in srgb, var(--sp-warning) 38%, var(--sp-border));
        }
        .administration-entity-grid { padding-top: 14px; }
        .administration-subsection-content > .child-device-grid,
        .administration-subsection-content > .admin-read-section:first-child {
          margin-top: 14px;
        }
        .administration-empty {
          padding: clamp(18px, 3vw, 28px);
          border: 1px solid var(--sp-border);
          border-radius: 20px;
          background: var(--sp-surface);
        }
        .administration-empty h2 { margin: 0 0 5px; font-size: 18px; }
        .admin-risk-badge {
          display: inline-flex;
          align-items: center;
          width: max-content;
          max-width: 100%;
          min-height: 24px;
          padding: 3px 8px;
          color: var(--sp-muted);
          border: 1px solid var(--sp-border);
          border-radius: 999px;
          background: var(--sp-surface);
          font-size: 10px;
          font-weight: 800;
          line-height: 1.1;
        }
        .admin-risk-badge.risk-normal { color: var(--sp-success); }
        .admin-risk-badge.risk-sensitive {
          color: var(--sp-warning);
          border-color: color-mix(in srgb, var(--sp-warning) 38%, var(--sp-border));
        }
        .admin-risk-badge.risk-disruptive,
        .admin-risk-badge.risk-lockout,
        .admin-risk-badge.risk-destructive {
          color: var(--sp-error);
          border-color: color-mix(in srgb, var(--sp-error) 38%, var(--sp-border));
        }
        .entity-card > .admin-risk-badge { margin: 0 12px 9px; }
        .admin-read-error,
        .admin-read-warning {
          display: flex;
          align-items: center;
          gap: 9px;
          padding: 12px 14px;
          color: var(--sp-error);
          border: 1px solid color-mix(in srgb, var(--sp-error) 35%, var(--sp-border));
          border-radius: 12px;
          background: color-mix(in srgb, var(--sp-error) 7%, var(--sp-surface));
        }
        .admin-read-error { margin-bottom: 14px; }
        .admin-read-warning { margin: 0 0 12px; color: var(--sp-warning); }
        .admin-read-error ha-icon,
        .admin-read-warning ha-icon { flex: none; --mdc-icon-size: 19px; }
        .admin-read-loading,
        .admin-read-empty-state {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          min-height: 120px;
          color: var(--sp-muted);
          text-align: center;
        }
        .admin-read-loading .loading-mark {
          display: flex;
          align-items: flex-end;
          gap: 3px;
          height: 18px;
        }
        .admin-read-loading .loading-mark i {
          width: 5px;
          height: 5px;
          border-radius: 1px;
          background: var(--sp-magenta);
        }
        .admin-read-loading .loading-mark i:nth-child(2) { height: 15px; }
        .admin-read-sections {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
        }
        .admin-read-section {
          min-width: 0;
          border: 1px solid var(--sp-border);
          border-radius: 16px;
          background: var(--sp-surface-soft);
        }
        .admin-read-section[open] { grid-column: 1 / -1; }
        .admin-read-section.not-observed { opacity: .72; }
        .admin-read-section summary {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr) auto;
          align-items: center;
          gap: 11px;
          min-height: 64px;
          padding: 12px 14px;
          cursor: pointer;
          list-style: none;
        }
        .admin-read-section summary::-webkit-details-marker { display: none; }
        .admin-read-section summary strong,
        .admin-read-section summary small { display: block; }
        .admin-read-section summary small {
          margin-top: 2px;
          color: var(--sp-muted);
          font-size: 11px;
        }
        .admin-read-section-icon {
          display: grid;
          place-items: center;
          width: 36px;
          height: 36px;
          color: var(--sp-magenta);
          border-radius: 11px;
          background: var(--sp-surface);
        }
        .admin-read-section-icon ha-icon { --mdc-icon-size: 21px; }
        .admin-read-chevron {
          color: var(--sp-muted);
          transition: transform .16s ease;
          --mdc-icon-size: 20px;
        }
        .admin-read-section[open] .admin-read-chevron { transform: rotate(180deg); }
        .admin-read-section-content {
          padding: 0 14px 14px;
          border-top: 1px solid var(--sp-border);
        }
        .admin-read-empty { margin: 14px 0 0; color: var(--sp-muted); }
        .admin-read-rows {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
          gap: 12px;
          padding-top: 14px;
        }
        .admin-read-row {
          min-width: 0;
          padding: 14px;
          border: 1px solid var(--sp-border);
          border-radius: 13px;
          background: var(--sp-surface);
        }
        .admin-read-row h4 {
          margin: 0 0 12px;
          overflow-wrap: anywhere;
          font-size: 14px;
        }
        .admin-read-row dl {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 9px 12px;
          margin: 0;
        }
        .admin-read-value { min-width: 0; }
        .admin-read-value dt {
          color: var(--sp-muted);
          font-size: 10px;
          font-weight: 700;
        }
        .admin-read-value dd {
          margin: 3px 0 0;
          overflow-wrap: anywhere;
          font-size: 12px;
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
        button:disabled, .entity-action.is-unavailable { cursor: not-allowed; opacity: .48; }
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
        .confirm-warning {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          margin: 16px 0 0;
          padding: 11px 12px;
          color: var(--sp-warning) !important;
          border: 1px solid color-mix(in srgb, var(--sp-warning) 38%, var(--sp-border));
          border-radius: 11px;
          background: color-mix(in srgb, var(--sp-warning) 7%, var(--sp-surface));
          font-size: 12px;
        }
        .confirm-warning ha-icon { flex: none; --mdc-icon-size: 19px; }
        .confirm-dialog.danger .action-recovery {
          color: var(--sp-error) !important;
          border-color: color-mix(in srgb, var(--sp-error) 40%, var(--sp-border));
          background: color-mix(in srgb, var(--sp-error) 7%, var(--sp-surface));
        }
        .confirm-assertion {
          display: grid;
          grid-template-columns: auto minmax(0, 1fr);
          align-items: start;
          gap: 10px;
          margin-top: 13px;
          color: var(--sp-text);
          font-size: 12px;
          line-height: 1.45;
          cursor: pointer;
        }
        .confirm-assertion input { width: 18px; height: 18px; margin: 1px 0 0; accent-color: var(--sp-magenta); }
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
          .admin-read-sections,
          .administration-subsections { grid-template-columns: 1fr; }
          .admin-read-section[open] { grid-column: auto; }
          .administration-subsection[open] { grid-column: auto; }
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
          .access-overview, .dashboard-section, .administration-intro, .admin-read-overview { margin-top: 14px; padding: 16px; border-radius: 17px; }
          .view-tabs { width: 100%; margin-top: 14px; }
          .admin-read-overview > header { align-items: flex-start; }
          .administration-area > summary { padding-inline: 14px; }
          .administration-subsections { padding-inline: 10px; padding-bottom: 10px; }
          .section-heading p { display: none; }
          .entity-source-heading { grid-template-columns: auto 1fr; }
          .entity-source-status { grid-column: 2; justify-self: start; }
          .entity-capability-grid { grid-template-columns: 1fr; }
          .admin-query-form,
          .admin-query-form.phonebook { grid-template-columns: 1fr; }
          .admin-query-form .primary { width: 100%; }
          .admin-action-heading { grid-template-columns: auto minmax(0, 1fr); }
          .admin-action-confirmation { grid-column: 2; justify-self: start; }
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
          .view-tabs button { padding-inline: 9px; }
          .admin-read-row dl { grid-template-columns: 1fr; }
          .admin-query-heading { grid-template-columns: auto minmax(0, 1fr); }
          .admin-query-read-only { grid-column: 2; justify-self: start; }
          .admin-query-result > header { align-items: flex-start; }
          .admin-action-target { grid-template-columns: 1fr; }
          .admin-action-target button { width: 100%; }
          .administration-area > summary,
          .administration-subsection > summary {
            grid-template-columns: auto minmax(0, 1fr) auto;
          }
          .administration-area > summary .admin-risk-badge,
          .administration-subsection > summary .admin-risk-badge {
            grid-column: 2;
          }
          .administration-area > summary .administration-chevron,
          .administration-subsection > summary .administration-chevron {
            grid-column: 3;
            grid-row: 1;
          }
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
