import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { NATIVE_ADMIN_TABS, resolveAdminPage } from "../../custom_components/speedport_smart/frontend/admin-navigation.js";

class TestElement {
  attachShadow() {
    this.shadowRoot = {
      activeElement: undefined,
      innerHTML: "",
      addEventListener() {},
      querySelector() {
        return undefined;
      },
      querySelectorAll() {
        return [];
      },
    };
    return this.shadowRoot;
  }

  dispatchEvent() {}

  toggleAttribute() {}
}

globalThis.HTMLElement = TestElement;
globalThis.customElements = {
  define() {},
  get() {
    return undefined;
  },
};

const {
  ADMIN_IA,
  ADMIN_READ_CLOSED_ENUM_VALUES,
  ADMIN_READ_FIELD_KEYS,
  ADMIN_READ_SECTION_FIELDS,
  ADMIN_READ_SECTION_ORDER,
  ADMIN_READ_SECTION_SOURCES,
  ADMIN_SHARED_ENTITY_GROUP_OWNERS,
  SpeedportSmartPanel,
  adminPlacementFor,
  buildAdminEntityGroupPlacements,
  capabilityGroupFor,
  formatAdminReadValue,
  highestAdminRisk,
  iconFor,
  normalizeAdminReadPayload,
  splitPanelEntities,
} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=panel-admin"
);
const { PANEL_TRANSLATIONS } = await import(
  "../../custom_components/speedport_smart/frontend/translations.js"
);

const REPORTING_META = Object.freeze({
  access_source: "protected_json",
  confirmation: "confirm",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_system_cpu",
  risk: "normal",
  section: "system",
  translation_key: "system_cpu",
});
const CONFIG_META = Object.freeze({
  access_source: "protected_json",
  capability_group: "wireless_schedule",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_wifi_schedule_mode",
  risk: "normal",
  section: "wireless",
  translation_key: "wifi_schedule_mode",
});
const CONTROL_META = Object.freeze({
  access_source: "router_control",
  confirmation: "confirm",
  control: true,
  control_supported: true,
  disruptive: true,
  domain: "button",
  entity_id: "button.speedport_reboot_router",
  risk: "disruptive",
  section: "controls",
  translation_key: "reboot_router",
});
const READ_ONLY_CONTROL_META = Object.freeze({
  ...CONTROL_META,
  control: false,
});
const WAN_RATE_META = Object.freeze({
  access_source: "wan_counters",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_wan_download_rate",
  risk: "normal",
  section: "bandwidth",
  translation_key: "wan_download_rate",
});
const WAN_INTERFACE_META = Object.freeze({
  access_source: "wan_counters",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_wan_interface_status",
  risk: "normal",
  section: "bandwidth",
  translation_key: "wan_interface_status",
});
const LTE_TUNNEL_META = Object.freeze({
  access_source: "protected_json",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_lte_tunnel_bytes_received",
  risk: "normal",
  section: "mobile",
  translation_key: "lte_tunnel_bytes_received",
});
const FAST_POLLING_HEALTH_META = Object.freeze({
  access_source: "integration",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_fast_polling_health",
  risk: "normal",
  section: "management",
  translation_key: "fast_polling_health",
});
const ENDPOINT_FAILURE_META = Object.freeze({
  access_source: "integration",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_endpoint_failures",
  risk: "normal",
  section: "management",
  translation_key: "endpoint_failures",
});

function adminPayload(entryId = "entry-a", sections = []) {
  return { entry_id: entryId, schema_version: 2, sections };
}

function router(entryId, entities = [REPORTING_META, CONTROL_META]) {
  return {
    access_sources: [],
    capabilities: [],
    capability_families: [],
    entities,
    entry_id: entryId,
    entry_state: "loaded",
    management: { controls_available: true, state: "available" },
    model: "Speedport Smart 4R Typ A",
    title: entryId,
  };
}

function panelFixture({ admin = true, entries = ["entry-a"] } = {}) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._metadata = { routers: entries.map((entry) => router(entry)) };
  panel._selectedEntry = entries[0];
  panel._hass = {
    connection: {
      async sendMessagePromise(message) {
        calls.push(message);
        return adminPayload(message.entry_id, [
          {
            id: "clients",
            rows: [{ connected: true, name: "Laptop" }],
            source: "protected_json",
            truncated: false,
          },
        ]);
      },
    },
    language: "en",
    locale: { language: "en-US" },
    states: {},
    user: { is_admin: admin },
  };
  panel._requestPrivate = async (message) => {
    calls.push(message);
    return adminPayload(message.entry_id, [{
      id: "clients", rows: [{ connected: true, name: "Laptop" }],
      source: "protected_json", truncated: false,
    }]);
  };
  return { calls, panel };
}

function renderNativePages(panel, ...args) {
  // Coverage is across explicit native pages, never an all-features landing page.
  const previous = [panel._adminTab, panel._adminPage];
  const markup = [];
  const seen = new Set();
  try {
    for (const tab of NATIVE_ADMIN_TABS) {
      for (const item of tab.pages) {
        const {page} = resolveAdminPage(tab.id, item.id);
        if (seen.has(page.id)) continue;
        seen.add(page.id);
        panel._adminTab = tab.id; panel._adminPage = page.id;
        const html = panel._renderAdministration(...args);
        assert.ok(html.includes(`data-native-page="${page.id}"`), page.id);
        markup.push(html);
      }
    }
    return markup.join("\n");
  } finally {
    [panel._adminTab, panel._adminPage] = previous;
  }
}

test("Dashboard and Administration use disjoint entity sets", () => {
  assert.deepEqual(
    splitPanelEntities([REPORTING_META, CONFIG_META, CONTROL_META]),
    {
      controls: [CONTROL_META],
      reporting: [REPORTING_META, CONFIG_META],
    },
  );
});

test("permission-denied controls stay in Administration without an action", () => {
  assert.deepEqual(
    splitPanelEntities([REPORTING_META, READ_ONLY_CONTROL_META]),
    {
      controls: [READ_ONLY_CONTROL_META],
      reporting: [REPORTING_META],
    },
  );
  assert.deepEqual(adminPlacementFor(READ_ONLY_CONTROL_META), {
    areaId: "system",
    subsectionId: "system_maintenance",
  });

  const fixture = panelFixture();
  fixture.panel._hass.states = {
    [READ_ONLY_CONTROL_META.entity_id]: {
      attributes: { friendly_name: "Reboot router" },
      state: "unknown",
    },
  };
  const html = renderNativePages(fixture.panel,
    router("entry-a", [READ_ONLY_CONTROL_META]),
    [READ_ONLY_CONTROL_META],
    [],
    {},
  );

  assert.match(html, /button\.speedport_reboot_router/);
  assert.doesNotMatch(html, /data-control="button\.speedport_reboot_router"/);
});

test("all reviewed permission-denied controls retain exact placement and zero actions", () => {
  const reviewed = ADMIN_IA.filter((area) => area.id !== "home_assistant").flatMap((area) =>
    area.subsections.flatMap((subsection) =>
      subsection.controls.map((control) => ({
        control,
        placement: { areaId: area.id, subsectionId: subsection.id },
      })),
    ),
  );
  assert.equal(reviewed.length, 12);

  const fixture = panelFixture();
  for (const { control, placement } of reviewed) {
    const [domain, translationKey] = control.split(":");
    const meta = {
      ...READ_ONLY_CONTROL_META,
      domain,
      entity_id: `${domain}.speedport_${translationKey}`,
      translation_key: translationKey,
    };
    fixture.panel._hass.states[meta.entity_id] = {
      attributes: { friendly_name: translationKey },
      state: domain === "switch" ? "off" : "unknown",
    };
    assert.deepEqual(adminPlacementFor(meta), placement, control);
    const html = renderNativePages(fixture.panel,
      router("entry-a", [meta]),
      [meta],
      [],
      {},
    );
    assert.match(html, new RegExp(meta.entity_id.replaceAll(".", "\\.")), control);
    assert.doesNotMatch(html, /data-control=/, control);
  }
});

test("backend management feature owns controls before the legacy semantic fallback", () => {
  const fixture = panelFixture();
  const semanticControl = {
    ...CONTROL_META,
    disruptive: false,
    entity_id: "button.speedport_semantic_reconnect",
    management_feature: "internet_reconnect",
    risk: "normal",
  };
  fixture.panel._hass.states[semanticControl.entity_id] = {
    attributes: { friendly_name: "Semantic reconnect" },
    state: "unknown",
  };

  assert.deepEqual(adminPlacementFor(semanticControl), {
    areaId: "internet",
    subsectionId: "internet_connection",
  });
  assert.deepEqual(adminPlacementFor(CONTROL_META), {
    areaId: "system",
    subsectionId: "system_maintenance",
  });
  assert.equal(
    adminPlacementFor({
      ...CONTROL_META,
      management_feature: "unreviewed_feature",
    }),
    undefined,
  );

  const html = renderNativePages(fixture.panel,
    router("entry-a", [semanticControl]),
    [semanticControl],
    [],
    {},
  );
  const featureStart = html.indexOf(
    'data-admin-control-feature="internet_reconnect"',
  );
  const controlStart = html.indexOf(
    `data-control="${semanticControl.entity_id}"`,
  );
  const nextFeature = html.indexOf('data-admin-control-feature="', featureStart + 1);
  assert.notEqual(featureStart, -1);
  assert.ok(controlStart > featureStart);
  assert.ok(nextFeature === -1 || controlStart < nextFeature);
  assert.equal(html.split(`data-control="${semanticControl.entity_id}"`).length - 1, 1);
  assert.ok(html.slice(featureStart, controlStart).includes("Control available"));
  assert.ok(html.indexOf('aria-label="Current controls"') < controlStart);
});

test("capability catalog explains permission-denied controls", () => {
  const fixture = panelFixture();
  const rebootFeature = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.controls.includes("button:reboot_router"));

  assert.equal(
    fixture.panel._adminFeaturePresentation(
      rebootFeature,
      [READ_ONLY_CONTROL_META],
      new Map(),
      new Set(),
      true,
    ).key,
    "control_permission_required",
  );
  assert.equal(
    PANEL_TRANSLATIONS.en[
      "admin.feature.status.control_permission_required"
    ],
    "Control permission required",
  );
});

test("global Wi-Fi state remains reporting while its writable switch is a control", () => {
  const wifiState = {
    ...CONFIG_META,
    capability_group: "wireless_general",
    domain: "binary_sensor",
    entity_id: "binary_sensor.speedport_wifi_enabled",
    translation_key: "wifi_enabled",
  };
  const wifiControl = {
    ...CONTROL_META,
    disruptive: false,
    domain: "switch",
    entity_id: "switch.speedport_wifi",
    risk: "normal",
    translation_key: "wifi",
  };

  assert.deepEqual(splitPanelEntities([wifiState, wifiControl]), {
    controls: [wifiControl],
    reporting: [wifiState],
  });
});

test("fixed Administration manifest places reviewed controls and collections", () => {
  assert.deepEqual(
    ADMIN_IA.map((area) => area.id),
    ["internet", "telephony", "network", "system", "home_assistant"],
  );
  const readPlacements = Object.fromEntries(
    ADMIN_IA.flatMap((area) =>
      area.subsections.flatMap((subsection) =>
        subsection.readSections.map((read) => [read.id, area.id]),
      ),
    ),
  );
  const readSubsectionPlacements = Object.fromEntries(
    ADMIN_IA.flatMap((area) =>
      area.subsections.flatMap((subsection) =>
        subsection.readSections.map((read) => [read.id, subsection.id]),
      ),
    ),
  );
  assert.deepEqual(readPlacements, {
    clients: "network",
    dect_handsets: "telephony",
    dect_repeaters: "telephony",
    ddns_identity: "internet",
    dns_rebind_exceptions: "network",
    ip_phones: "telephony",
    internet_status_technical: "internet",
    lan_ipv6_technical: "network",
    mesh_nodes: "network",
    nas_shares: "network",
    pbx_clients: "telephony",
    port_block_rules: "internet",
    port_forward_rules: "internet",
    powerline_nodes: "network",
    qos_prioritized_clients: "network",
    receivers: "internet",
    status_technical: "system",
    storage_devices: "network",
    telephony_providers: "telephony",
    telephone_lines: "telephony",
    usb_devices: "network",
    vpn_peers: "network",
    wifi_2_4_identity: "network",
    wifi_5_identity: "network",
    wifi_guest_identity: "network",
    wifi_office_identity: "network",
  });
  assert.deepEqual(
    Object.keys(readPlacements).sort(),
    [...ADMIN_READ_SECTION_ORDER].sort(),
  );
  assert.equal(readSubsectionPlacements.mesh_nodes, "network_mesh");
  assert.equal(readSubsectionPlacements.powerline_nodes, "network_mesh");
  assert.equal(readSubsectionPlacements.vpn_peers, "network_vpn");
  assert.equal(readSubsectionPlacements.ddns_identity, "internet_ddns");
  assert.equal(
    readSubsectionPlacements.internet_status_technical,
    "internet_connection",
  );
  assert.equal(readSubsectionPlacements.status_technical, "system_information");
  assert.equal(readSubsectionPlacements.wifi_2_4_identity, "network_wifi");
  assert.equal(readSubsectionPlacements.wifi_5_identity, "network_wifi");
  assert.equal(readSubsectionPlacements.wifi_guest_identity, "network_wifi_access");
  assert.equal(readSubsectionPlacements.wifi_office_identity, "network_wifi_access");
  const controls = ADMIN_IA.flatMap((area) =>
    area.subsections.flatMap((subsection) => subsection.controls),
  );
  assert.deepEqual(controls.sort(), [
    "button:capture_read_only_inventory",
    "button:reboot_router",
    "button:reconnect_internet",
    "button:retry_protected_data",
    "button:wps",
    "select:internet_privacy_level_control",
    "select:receiver_led_mode_control",
    "switch:client_fixed_dhcp",
    "switch:guest_wifi",
    "switch:hybrid_bonding",
    "switch:office_wifi",
    "switch:port_forward_rule",
    "switch:wifi",
    "text:client_name",
  ]);
  const privacyFeature = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.id === "internet_privacy");
  assert.deepEqual(privacyFeature?.capabilities, ["connection_privacy"]);
  const analogFeatures = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .filter((feature) => feature.id.startsWith("telephony_analog_"));
  assert.equal(analogFeatures.length, 4);
  assert.ok(
    analogFeatures.every(
      (feature) =>
        JSON.stringify(feature.capabilities) ===
        JSON.stringify(["telephony", "analog"]),
    ),
  );
  assert.deepEqual(adminPlacementFor(CONFIG_META), {
    areaId: "network",
    subsectionId: "network_wifi",
  });
  assert.deepEqual(adminPlacementFor(REPORTING_META), {
    areaId: "system",
    subsectionId: "system_information",
  });
  for (const [section, translationKey, expected] of [
    ["connection", "internet_error_code", ["internet", "internet_connection"]],
    ["mobile", "mobile_status_code", ["internet", "internet_mobile"]],
    ["mobile", "mobile_nr_signal", ["internet", "internet_mobile"]],
    ["mobile", "mobile_lte_band", ["internet", "internet_mobile"]],
    ["clients", "lan_port_1_connected", ["system", "system_information"]],
    ["wireless", "guest_wifi_display_key_enabled", ["system", "system_information"]],
    ["system", "system_operating_mode", ["system", "system_information"]],
    ["system", "easy_support_enabled", ["system", "system_support"]],
    ["system", "firmware_automatic_updates", ["system", "system_support"]],
    ["system", "remote_support_active", ["system", "system_support"]],
    ["system", "router_https_enabled", ["system", "system_security"]],
    ["telephony", "telephony_voip_policy", ["telephony", "telephony_numbers"]],
    ["telephony", "telephony_hd_voice_active", ["telephony", "telephony_numbers"]],
    ["telephony", "dect_enabled", ["telephony", "telephony_dect"]],
    ["telephony", "dect_scan_active", ["telephony", "telephony_dect"]],
    ["telephony", "dect_paging_active", ["telephony", "telephony_dect"]],
    ["telephony", "dect_handsets", ["telephony", "telephony_dect"]],
    ["telephony", "dect_repeaters", ["telephony", "telephony_dect"]],
  ]) {
    assert.deepEqual(
      adminPlacementFor({
        access_source: "public_status",
        control: false,
        domain: "sensor",
        section,
        translation_key: translationKey,
      }),
      { areaId: expected[0], subsectionId: expected[1] },
      translationKey,
    );
  }
  for (const [section, translationKey, expectedGroup] of [
    ["system", "firmware_automatic_updates", "system_easysupport_firmware"],
    ["telephony", "telephony_voip_policy", "telephony_call_encryption"],
    ["telephony", "telephony_hd_voice_active", "telephony_hd_voice"],
    ["telephony", "dect_enabled", "telephony_dect_base"],
    ["telephony", "dect_scan_active", "telephony_dect_scan"],
    ["telephony", "dect_paging_active", "telephony_dect_paging"],
    ["telephony", "dect_paging_handsets", "telephony_dect_paging"],
    ["telephony", "dect_handsets", "telephony_dect_handsets"],
    ["telephony", "dect_repeaters", "telephony_dect_repeaters"],
  ]) {
    assert.equal(
      capabilityGroupFor({
        access_source: "protected_json",
        control: false,
        domain: "sensor",
        section,
        translation_key: translationKey,
      }),
      expectedGroup,
      translationKey,
    );
  }
  assert.deepEqual(
    adminPlacementFor({
      access_source: "public_status",
      capability_group: "mobile_receiver_status",
      control: false,
      domain: "sensor",
      section: "mobile",
      translation_key: "receiver_model",
    }),
    { areaId: "internet", subsectionId: "internet_mobile" },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "integration",
      control: true,
      domain: "button",
      section: "controls",
      translation_key: "capture_read_only_inventory",
    }),
    {
      areaId: "home_assistant",
      subsectionId: "home_assistant_diagnostics",
    },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "integration",
      control: false,
      domain: "sensor",
      section: "management",
      translation_key: "fast_polling_health",
    }),
    {
      areaId: "home_assistant",
      subsectionId: "home_assistant_diagnostics",
    },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      child_device: { device_id: "repeater-1", kind: "dect_repeater" },
      control: false,
      domain: "binary_sensor",
      section: "telephony",
      translation_key: "registered",
    }),
    { areaId: "telephony", subsectionId: "telephony_dect" },
  );
  assert.equal(
    capabilityGroupFor({
      access_source: "protected_json",
      child_device: { device_id: "handset-1", kind: "dect_handset" },
      control: false,
      domain: "binary_sensor",
      section: "telephony",
      translation_key: "registered",
    }),
    "telephony_dect_handsets",
  );
  assert.equal(
    capabilityGroupFor({
      access_source: "protected_json",
      child_device: { device_id: "repeater-1", kind: "dect_repeater" },
      control: false,
      domain: "binary_sensor",
      section: "telephony",
      translation_key: "registered",
    }),
    "telephony_dect_repeaters",
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      child_device: { device_id: "powerline-1", kind: "powerline_node" },
      control: false,
      domain: "sensor",
      section: "clients",
      translation_key: "powerline_mode",
    }),
    { areaId: "network", subsectionId: "network_mesh" },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      child_device: { device_id: "client-1", kind: "client" },
      control: false,
      domain: "binary_sensor",
      section: "clients",
      translation_key: "client_connected",
    }),
    { areaId: "network", subsectionId: "network_devices" },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      child_device: { device_id: "receiver-1", kind: "receiver" },
      control: false,
      domain: "sensor",
      section: "mobile",
      translation_key: "receiver_signal_strength",
    }),
    { areaId: "internet", subsectionId: "internet_mobile" },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      control: false,
      domain: "sensor",
      section: "telephony",
      translation_key: "phonebook_entries",
    }),
    { areaId: "telephony", subsectionId: "telephony_phonebooks" },
  );
  assert.equal(
    adminPlacementFor({
      ...CONTROL_META,
      translation_key: "future_generic_admin_action",
    }),
    undefined,
  );
});

test("shared Administration entity groups require explicit deterministic owners", () => {
  assert.deepEqual(ADMIN_SHARED_ENTITY_GROUP_OWNERS, {
    system_health: {
      areaId: "system",
      subsectionId: "system_information",
    },
    system_security: {
      areaId: "system",
      subsectionId: "system_security",
    },
  });
  assert.deepEqual(adminPlacementFor(REPORTING_META), {
    areaId: "system",
    subsectionId: "system_information",
  });

  const duplicated = [
    {
      id: "system",
      subsections: [
        { id: "first", entityGroups: ["shared"] },
        { id: "second", entityGroups: ["shared"] },
      ],
    },
  ];
  assert.throws(
    () => buildAdminEntityGroupPlacements(duplicated, {}),
    /has no explicit shared owner: shared/,
  );
  assert.throws(
    () =>
      buildAdminEntityGroupPlacements(duplicated, {
        shared: { areaId: "system", subsectionId: "missing" },
      }),
    /is not a declared placement: shared/,
  );
  assert.deepEqual(
    buildAdminEntityGroupPlacements(duplicated, {
      shared: { areaId: "system", subsectionId: "first" },
    }).get("shared"),
    { areaId: "system", subsectionId: "first" },
  );
});

test("Administration catalog covers every reviewed management family without generic controls", () => {
  const subsections = ADMIN_IA.flatMap((area) => area.subsections);
  const features = subsections.flatMap((subsection) => subsection.features);
  const featureIds = features.map((feature) => feature.id);

  assert.equal(subsections.length, 28);
  assert.equal(features.length, 122);
  assert.equal(new Set(featureIds).size, featureIds.length);
  assert.deepEqual(
    [...new Set(features.map((feature) => feature.contract))].sort(),
    ["blocked", "read_only", "reviewed", "unsupported"],
  );
  assert.ok(
    features.every(
      (feature) =>
        feature.risk === undefined ||
        [
          "normal",
          "sensitive",
          "disruptive",
          "lockout",
          "destructive",
        ].includes(feature.risk),
    ),
  );
  assert.ok(features.some((feature) => feature.destructive));
  assert.ok(
    features
      .filter((feature) => feature.destructive)
      .every((feature) => feature.controls.length === 0),
  );

  const subsectionControls = subsections.flatMap(
    (subsection) => subsection.controls,
  );
  const interactiveFeatureControls = features
    .filter((feature) => feature.controls.length > 0)
    .flatMap((feature) => feature.controls);
  assert.deepEqual(
    [...new Set(interactiveFeatureControls)].sort(),
    [...new Set(subsectionControls)].sort(),
  );
  assert.deepEqual(
    features
      .filter((feature) => feature.contract !== "reviewed")
      .flatMap((feature) => feature.controls),
    ["button:capture_read_only_inventory"],
  );
  const inventory = features.find(
    (feature) => feature.id === "home_assistant_capability_inventory",
  );
  assert.equal(inventory.contract, "read_only");
  assert.equal(inventory.destructive, false);
  assert.deepEqual(inventory.controls, ["button:capture_read_only_inventory"]);
  const webUiVersion = features.find(
    (feature) => feature.id === "system_web_ui_version",
  );
  assert.equal(webUiVersion.contract, "blocked");
  assert.deepEqual(webUiVersion.controls, []);
  assert.deepEqual(webUiVersion.entityGroups, []);
  assert.deepEqual(webUiVersion.readSections, []);
  assert.equal(webUiVersion.blockedReasonKey, undefined);
  const receiverLed = features.find(
    (feature) => feature.id === "internet_receiver_led",
  );
  assert.deepEqual(receiverLed?.capabilities, ["receiver_led"]);
  const guestAccessPass = features.find(
    (feature) => feature.id === "network_wifi_guest_access_pass",
  );
  assert.equal(guestAccessPass?.contract, "blocked");
  assert.deepEqual(guestAccessPass?.controls, []);
  assert.deepEqual(guestAccessPass?.entityGroups, []);
  assert.deepEqual(guestAccessPass?.readSections, []);
  assert.equal(
    guestAccessPass?.blockedReasonKey,
    "admin.feature.blocked_reason.wifi_guest_access_pass",
  );

  const featureById = new Map(features.map((feature) => [feature.id, feature]));
  for (const featureId of [
    "internet_parental_controls",
    "internet_ddns_management",
    "network_vpn_management",
    "network_usb_printer_media",
    "network_media_folders",
    "system_dsl_modem_mode",
  ]) {
    assert.ok(featureById.has(featureId), featureId);
    assert.deepEqual(featureById.get(featureId).controls, [], featureId);
  }
  for (const featureId of [
    "telephony_number_assignment",
    "telephony_number_use",
    "telephony_dect_base_pin",
    "telephony_dect_transmit_power",
    "telephony_dect_full_eco",
    "telephony_dect_handset_call_waiting",
    "network_mesh_node_rename",
    "network_powerline_node_rename",
    "internet_receiver_factory_esim_restore",
    "telephony_provider_delete",
    "telephony_number_delete",
    "telephony_number_activation",
    "network_mesh_identify",
    "network_mesh_node_delete",
    "network_usb_safe_remove",
  ]) {
    assert.deepEqual(featureById.get(featureId).entityGroups, [], featureId);
    assert.deepEqual(featureById.get(featureId).readSections, [], featureId);
  }
  for (const [featureId, expectedGroups] of [
    ["telephony_call_encryption", ["telephony_call_encryption"]],
    ["telephony_hd_voice", ["telephony_hd_voice"]],
    ["telephony_dect_base", ["telephony_dect_base"]],
    ["telephony_dect_handset_enrollment", ["telephony_dect_scan"]],
    ["telephony_dect_handset_configuration", ["telephony_dect_handsets"]],
    ["telephony_dect_handset_disconnect", ["telephony_dect_handsets"]],
    ["telephony_dect_handset_paging", ["telephony_dect_paging"]],
    ["telephony_dect_repeater_enrollment", ["telephony_dect_repeaters"]],
    ["telephony_dect_repeater_disconnect", ["telephony_dect_repeaters"]],
    ["system_easysupport_automatic_firmware", ["system_easysupport_firmware"]],
  ]) {
    assert.deepEqual(
      featureById.get(featureId).entityGroups,
      expectedGroups,
      featureId,
    );
  }

  const records = new Map(
    ADMIN_IA.flatMap((area) =>
      area.subsections.flatMap((subsection) =>
        subsection.features.map((feature) => [
          feature.id,
          { areaId: area.id, subsectionId: subsection.id },
        ]),
      ),
    ),
  );
  assert.deepEqual(records.get("network_vpn_management"), {
    areaId: "network",
    subsectionId: "network_vpn",
  });
  assert.deepEqual(records.get("network_smarthome_activation"), {
    areaId: "network",
    subsectionId: "network_smarthome",
  });
  for (const featureId of [
    "internet_receiver_mode",
    "internet_receiver_routing_exceptions",
    "internet_receiver_firmware_update",
    "internet_receiver_factory_esim_restore",
    "telephony_provider_delete",
    "telephony_number_delete",
    "telephony_number_activation",
    "telephony_automatic_speed_dial",
    "telephony_number_use",
    "telephony_call_encryption",
    "telephony_hd_voice",
    "telephony_dialing_delay",
    "telephony_status_messages",
    "telephony_analog_socket_name",
    "telephony_analog_number_assignment",
    "telephony_analog_device_type",
    "telephony_analog_call_waiting",
    "telephony_dect_base_pin",
    "telephony_dect_transmit_power",
    "telephony_dect_full_eco",
    "telephony_dect_handset_enrollment",
    "telephony_dect_handset_configuration",
    "telephony_dect_handset_call_waiting",
    "telephony_dect_handset_disconnect",
    "telephony_dect_handset_paging",
    "telephony_dect_repeater_enrollment",
    "telephony_dect_repeater_disconnect",
    "telephony_ip_pbx",
    "telephony_ip_phone_enrollment",
    "telephony_ip_phone_configuration",
    "telephony_ip_phone_disconnect",
    "network_client_delete",
    "network_mesh_management",
    "network_mesh_node_rename",
    "network_mesh_identify",
    "network_mesh_node_delete",
    "network_powerline_management",
    "network_powerline_node_rename",
    "network_usb_safe_remove",
    "network_wifi_wps_enablement",
    "network_wifi_wps_pin_mode",
    "system_lan_port_status",
    "system_mesh_restart",
    "system_mesh_reset",
    "system_router_firmware",
    "system_mesh_firmware",
    "system_local_display_settings",
    "system_physical_front_panel_actions",
    "system_easysupport_automatic_setup",
    "system_easysupport_automatic_firmware",
    "system_easysupport_wifi_backup",
    "system_easysupport_remote_support",
  ]) {
    assert.ok(records.has(featureId), featureId);
  }
  for (const conflatedId of [
    "internet_receiver_management",
    "internet_vpn_management",
    "telephony_dect_handsets",
    "telephony_dect_repeaters",
    "telephony_number_behavior",
    "telephony_analog_sockets",
    "telephony_pbx_management",
    "network_mesh_powerline_management",
    "network_mesh_maintenance",
    "network_mesh_restart",
    "network_mesh_reset",
    "network_wifi_wps_settings",
    "network_lan_port_status",
    "system_router_mesh_firmware",
    "system_smarthome",
    "system_front_panel",
    "system_cloud_backup",
  ]) {
    assert.equal(records.has(conflatedId), false, conflatedId);
  }
  assert.deepEqual(records.get("system_mesh_restart"), {
    areaId: "system",
    subsectionId: "system_maintenance",
  });
  assert.deepEqual(records.get("system_mesh_reset"), {
    areaId: "system",
    subsectionId: "system_maintenance",
  });
  assert.deepEqual(records.get("system_lan_port_status"), {
    areaId: "system",
    subsectionId: "system_information",
  });
});

test("hero renders only safe runtime router identity with neutral decorative LEDs", () => {
  const fixture = panelFixture();
  assert.equal(fixture.panel._renderRouterIdentity(router("entry-a", [])), "");
  fixture.panel._metadata = {
    routers: [
      {
        ...router("entry-a", []),
        firmware: "FW <1.2>",
        hardware_version: "Rev & A",
        identifier: "private-router-identifier",
        serial_number: "private-router-serial",
      },
    ],
  };

  SpeedportSmartPanel.prototype._render.call(fixture.panel);

  const html = fixture.panel.shadowRoot.innerHTML;
  assert.match(html, /<dt>Firmware<\/dt>\s*<dd>FW &lt;1\.2&gt;<\/dd>/);
  assert.match(
    html,
    /<dt>Hardware version<\/dt>\s*<dd>Rev &amp; A<\/dd>/,
  );
  assert.doesNotMatch(html, /private-router-identifier|private-router-serial/);
  assert.match(
    html,
    /\.router-leds i \{[\s\S]*?background: rgba\(255,255,255,\.46\);[\s\S]*?box-shadow: none;/,
  );
  assert.doesNotMatch(html, /#7df4b3/);
});

test("manual capability gaps are explicit safe cards without invented controls", () => {
  const records = new Map(
    ADMIN_IA.flatMap((area) =>
      area.subsections.flatMap((subsection) =>
        subsection.features.map((feature) => [
          feature.id,
          { areaId: area.id, feature, subsectionId: subsection.id },
        ]),
      ),
    ),
  );
  const expected = {
    internet_ip_information: {
      areaId: "internet",
      contract: "read_only",
      entityGroups: ["connection_addressing"],
      subsectionId: "internet_connection",
    },
    network_client_manual_add: {
      areaId: "network",
      contract: "blocked",
      entityGroups: ["clients_devices"],
      subsectionId: "network_devices",
    },
    network_lan_identity: {
      areaId: "network",
      contract: "read_only",
      entityGroups: ["clients_lan"],
      readSections: ["lan_ipv6_technical"],
      subsectionId: "network_lan",
    },
    network_wifi_guest_access_pass: {
      areaId: "network",
      contract: "blocked",
      entityGroups: [],
      subsectionId: "network_wifi_access",
    },
    system_energy_settings: {
      areaId: "system",
      contract: "blocked",
      entityGroups: ["wireless_general", "wireless_radios"],
      subsectionId: "system_information",
    },
  };

  for (const [featureId, shape] of Object.entries(expected)) {
    const record = records.get(featureId);
    assert.ok(record, featureId);
    assert.equal(record.areaId, shape.areaId, featureId);
    assert.equal(record.subsectionId, shape.subsectionId, featureId);
    assert.equal(record.feature.contract, shape.contract, featureId);
    assert.deepEqual(record.feature.entityGroups, shape.entityGroups, featureId);
    assert.deepEqual(record.feature.controls, [], featureId);
    assert.deepEqual(
      record.feature.readSections,
      shape.readSections || [],
      featureId,
    );
    assert.equal(record.feature.destructive, false, featureId);
  }

  const fixture = panelFixture();
  const html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  for (const featureId of Object.keys(expected)) {
    const marker = `data-admin-feature="${featureId}"`;
    assert.equal(html.split(marker).length - 1, 1, featureId);
    assert.ok(html.includes(`<section class="admin-native-section" data-admin-feature="${featureId}"`), featureId);
  }
  assert.ok(
    html.includes(
      PANEL_TRANSLATIONS.en[
        "admin.feature.blocked_reason.wifi_guest_access_pass"
      ],
    ),
  );
  assert.doesNotMatch(html, /data-control=/);

  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      capability_group: "wireless_general",
      control: false,
      domain: "binary_sensor",
      entity_id: "binary_sensor.speedport_wifi_enabled",
      section: "wireless",
      translation_key: "wifi_enabled",
    }),
    { areaId: "network", subsectionId: "network_wifi" },
  );
  assert.deepEqual(
    adminPlacementFor({
      access_source: "protected_json",
      capability_group: "system_services",
      control: false,
      domain: "binary_sensor",
      entity_id: "binary_sensor.speedport_smarthome_linked",
      section: "system",
      translation_key: "smarthome_linked",
    }),
    { areaId: "network", subsectionId: "network_smarthome" },
  );
});

test("DECT action candidates explain exact proof gaps without exposing controls", () => {
  const featureById = new Map(
    ADMIN_IA.flatMap((area) =>
      area.subsections.flatMap((subsection) =>
        subsection.features.map((feature) => [feature.id, feature]),
      ),
    ),
  );
  const expected = [
    {
      id: "telephony_dect_handset_disconnect",
      blockedReasonKey:
        "admin.feature.blocked_reason.dect_handset_disconnect",
      destructive: true,
    },
    {
      id: "telephony_dect_repeater_disconnect",
      blockedReasonKey:
        "admin.feature.blocked_reason.dect_repeater_disconnect",
      destructive: true,
    },
    {
      id: "network_wifi_guest_access_pass",
      blockedReasonKey:
        "admin.feature.blocked_reason.wifi_guest_access_pass",
      destructive: false,
    },
  ];

  for (const candidate of expected) {
    const feature = featureById.get(candidate.id);
    assert.ok(feature, candidate.id);
    assert.equal(feature.contract, "blocked", candidate.id);
    assert.deepEqual(feature.controls, [], candidate.id);
    assert.equal(feature.destructive, candidate.destructive, candidate.id);
    assert.equal(
      feature.blockedReasonKey,
      candidate.blockedReasonKey,
      candidate.id,
    );
  }

  const fixture = panelFixture();
  const html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  for (const candidate of expected) {
    assert.equal(
      html.split(`data-admin-feature="${candidate.id}"`).length - 1,
      1,
      candidate.id,
    );
    assert.ok(
      html.includes(PANEL_TRANSLATIONS.en[candidate.blockedReasonKey]),
      candidate.blockedReasonKey,
    );
  }
  assert.ok(html.includes('class="admin-native-unavailable"'));
  assert.doesNotMatch(html, /data-control=/);
});

test("static blocked operations stay noninteractive and use backend risk tiers", () => {
  const features = new Map(
    ADMIN_IA.flatMap((area) => area.subsections)
      .flatMap((subsection) => subsection.features)
      .map((feature) => [feature.id, feature]),
  );
  const expected = {
    internet_receiver_firmware_update: "disruptive",
    internet_receiver_factory_esim_restore: "destructive",
    telephony_provider_registration: "sensitive",
    telephony_provider_delete: "destructive",
    telephony_number_delete: "destructive",
    network_mesh_identify: "disruptive",
    network_mesh_node_delete: "destructive",
    network_usb_safe_remove: "disruptive",
    system_mesh_restart: "disruptive",
    system_dsl_modem_mode: "lockout",
    system_router_firmware: "disruptive",
  };

  for (const [featureId, risk] of Object.entries(expected)) {
    const feature = features.get(featureId);
    assert.ok(feature, featureId);
    assert.equal(feature.contract, "blocked", featureId);
    assert.deepEqual(feature.controls, [], featureId);
    assert.equal(feature.risk, risk, featureId);
    assert.equal(feature.destructive, risk === "destructive", featureId);
  }

  const fixture = panelFixture();
  const html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  const featureWindow = (featureId) => {
    const marker = `data-admin-feature="${featureId}"`;
    const start = html.indexOf(marker);
    assert.notEqual(start, -1, featureId);
    const following = html.slice(start + marker.length);
    const next = following.search(/data-admin-feature="[^"]+"/);
    return next === -1
      ? html.slice(start)
      : html.slice(start, start + marker.length + next);
  };
  for (const [featureId, risk] of Object.entries(expected)) {
    const card = featureWindow(featureId);
    const label = PANEL_TRANSLATIONS.en[`admin.risk.${risk}`];
    assert.match(card, new RegExp(`risk-${risk}`), featureId);
    assert.ok(card.includes(`aria-label="Risk: ${label}"`), featureId);
    assert.doesNotMatch(card, /data-control=/, featureId);
  }
});

test("reviewed controls and cached reads render once under deterministic feature owners", () => {
  const featureRecords = ADMIN_IA.filter((area) => area.id !== "home_assistant").flatMap((area) =>
    area.subsections.flatMap((subsection) =>
      subsection.features.map((feature) => ({
        areaId: area.id,
        feature,
        subsectionId: subsection.id,
      })),
    ),
  );
  const controlOwners = new Map();
  const readReferences = new Map();
  for (const { feature } of featureRecords) {
    for (const control of feature.controls) {
      assert.equal(controlOwners.has(control), false, control);
      controlOwners.set(control, feature.id);
    }
    for (const sectionId of feature.readSections) {
      if (!readReferences.has(sectionId)) readReferences.set(sectionId, []);
      readReferences.get(sectionId).push(feature.id);
    }
  }

  const sharedReadOwners = Object.fromEntries(
    [...readReferences]
      .filter(([, owners]) => owners.length > 1)
      .map(([sectionId, owners]) => [sectionId, owners[0]])
      .sort(([left], [right]) => left.localeCompare(right)),
  );
  assert.deepEqual(sharedReadOwners, {
    dect_handsets: "telephony_dect_handset_configuration",
    dect_repeaters: "telephony_dect_repeater_enrollment",
    mesh_nodes: "network_mesh_management",
    port_forward_rules: "internet_port_forward_toggle",
    storage_devices: "network_usb_printer_media",
  });

  const controls = [...controlOwners].map(([control, featureId]) => {
    const [domain, translationKey] = control.split(":");
    return {
      access_source: "router_control",
      confirmation: "confirm",
      control: true,
      control_supported: true,
      disruptive: false,
      domain,
      entity_id: `${domain}.speedport_${translationKey}`,
      management_feature: featureId,
      risk: "normal",
      section: "controls",
      translation_key: translationKey,
    };
  });
  const fixture = panelFixture();
  for (const meta of controls) {
    const options =
      meta.translation_key === "internet_privacy_level_control"
        ? ["off", "level_1", "level_2"]
        : meta.translation_key === "receiver_led_mode_control"
          ? ["use_leds", "off_after_timeout", "disabled"]
          : undefined;
    fixture.panel._hass.states[meta.entity_id] = {
      attributes: {
        friendly_name: meta.translation_key,
        ...(options ? { options } : {}),
      },
      state:
        meta.domain === "switch"
          ? "off"
          : meta.domain === "select"
            ? options[0]
            : meta.domain === "text"
              ? "Router client"
              : "unknown",
    };
  }
  const html = renderNativePages(fixture.panel,
    router("entry-a", controls),
    controls,
    [],
    { protected_json: { available: true } },
  );
  const controlWindow = (featureId) => {
    const marker = `data-admin-control-feature="${featureId}"`;
    const start = html.indexOf(marker);
    assert.notEqual(start, -1, featureId);
    const following = html.slice(start + marker.length);
    const next = following.search(/data-admin-control-feature="[^"]+"|<\/section>/);
    return next === -1
      ? html.slice(start)
      : html.slice(start, start + marker.length + next);
  };

  for (const meta of controls) {
    const marker = `data-control="${meta.entity_id}"`;
    assert.equal(html.split(marker).length - 1, 1, meta.entity_id);
    assert.match(controlWindow(meta.management_feature), new RegExp(marker));
    assert.ok(controlWindow(meta.management_feature).includes('class="admin-control-status"'));
  }
  for (const sectionId of ADMIN_READ_SECTION_ORDER) {
    const marker = `data-detail-id="admin-read:${sectionId}"`;
    assert.ok(html.includes(marker), sectionId);
  }
  for (const tab of NATIVE_ADMIN_TABS) for (const page of tab.pages) {
    fixture.panel._adminTab = tab.id; fixture.panel._adminPage = page.id;
    const current = fixture.panel._renderAdministration(router("entry-a", controls), controls, [], {protected_json: {available: true}});
    for (const sectionId of ADMIN_READ_SECTION_ORDER) {
      assert.ok(current.split(`data-detail-id="admin-read:${sectionId}"`).length - 1 <= 1, `${page.id}: ${sectionId}`);
    }
  }
  assert.ok(html.includes('<section class="admin-native-section" data-admin-feature="internet_connection_diagnostics"'));
  assert.ok(html.includes('<section class="admin-native-section" data-admin-feature="internet_provider_configuration"'));
});

test("feature status comes only from current entities, collections, and capabilities", () => {
  const fixture = panelFixture();
  const features = ADMIN_IA.flatMap((area) => area.subsections).flatMap(
    (subsection) => subsection.features,
  );
  const byId = (id) => features.find((feature) => feature.id === id);
  const reconnect = {
    ...CONTROL_META,
    entity_id: "button.speedport_reconnect_internet",
    translation_key: "reconnect_internet",
  };
  fixture.panel._hass.states[reconnect.entity_id] = {
    attributes: {},
    state: "unknown",
  };
  fixture.panel._hass.states[CONFIG_META.entity_id] = {
    attributes: {},
    state: "weekly",
  };
  const phonebookEntries = {
    access_source: "protected_json",
    control: false,
    domain: "sensor",
    entity_id: "sensor.speedport_phonebook_entries",
    section: "telephony",
    translation_key: "phonebook_entries",
  };
  fixture.panel._hass.states[phonebookEntries.entity_id] = {
    attributes: {},
    state: "3",
  };

  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("internet_reconnect"),
      [reconnect],
      new Map(),
      new Set(),
      true,
    ).key,
    "control_available",
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("network_wifi_schedule"),
      [CONFIG_META],
      new Map(),
      new Set(),
      true,
    ).key,
    "read_only",
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("telephony_phonebook_management"),
      [phonebookEntries],
      new Map(),
      new Set(),
      true,
    ).key,
    "read_only",
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("network_vpn_management"),
      [],
      new Map(),
      new Set(["vpn"]),
      false,
    ).key,
    "temporarily_unavailable",
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("system_safe_mail_allowlist"),
      [],
      new Map(),
      new Set(),
      true,
    ).key,
    "not_observed",
  );

  fixture.panel._hass.states[reconnect.entity_id] = {
    attributes: {},
    state: "unavailable",
  };
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      byId("internet_reconnect"),
      [reconnect],
      new Map(),
      new Set(),
      true,
    ).key,
    "control_unavailable",
  );
});

test("Administration explains blocked, absent, and unsupported features distinctly", () => {
  const fixture = panelFixture();
  const reconnect = {
    ...CONTROL_META,
    entity_id: "button.speedport_reconnect_internet",
    management_feature: "internet_reconnect",
    translation_key: "reconnect_internet",
  };
  fixture.panel._hass.states[CONFIG_META.entity_id] = {
    attributes: {},
    state: "weekly",
  };
  fixture.panel._hass.states[reconnect.entity_id] = {
    attributes: {},
    state: "unknown",
  };
  const html = renderNativePages(fixture.panel,
    router("entry-a", [CONFIG_META, reconnect]),
    [reconnect],
    [CONFIG_META],
    { protected_json: { available: true } },
  );
  const featureWindow = (featureId) => {
    const marker = `data-admin-feature="${featureId}"`;
    const start = html.indexOf(marker);
    assert.notEqual(start, -1, featureId);
    const following = html.slice(start + marker.length);
    const next = following.search(/data-admin-feature="[^"]+"/);
    return next === -1
      ? html.slice(start)
      : html.slice(start, start + marker.length + next);
  };

  assert.match(
    featureWindow("network_wifi_schedule"),
    /Read-only; control contract not proven/,
  );
  assert.match(
    featureWindow("internet_dns_servers"),
    /Not exposed by this router/,
  );
  for (const featureId of [
    "telephony_number_assignment",
    "telephony_number_use",
    "telephony_dect_base_pin",
    "telephony_dect_transmit_power",
    "telephony_dect_full_eco",
    "telephony_dect_handset_call_waiting",
    "network_mesh_node_rename",
    "network_powerline_node_rename",
    "system_easysupport_automatic_firmware",
    "system_easysupport_wifi_backup",
  ]) {
    assert.match(featureWindow(featureId), /Not exposed by this router/, featureId);
  }
  assert.match(
    featureWindow("system_safe_mail_allowlist"),
    /No local router control/,
  );
  const reconnectStart = html.indexOf('data-admin-control-feature="internet_reconnect"');
  assert.notEqual(reconnectStart, -1);
  const reconnectControl = html.indexOf(`data-control="${reconnect.entity_id}"`, reconnectStart);
  assert.ok(reconnectControl > reconnectStart);
  assert.ok(html.slice(reconnectStart, reconnectControl).includes("Control available"));
});

test("broad related telemetry never claims exact blocked-setting coverage", () => {
  const fixture = panelFixture();
  const providerFeature = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.id === "internet_provider_configuration");
  const genericInternet = {
    access_source: "public_status",
    capability_group: "connection_internet",
    control: false,
    domain: "binary_sensor",
    entity_id: "binary_sensor.speedport_internet_connected",
    section: "connection",
    translation_key: "internet_connected",
  };
  fixture.panel._hass.states[genericInternet.entity_id] = {
    attributes: {},
    state: "on",
  };

  assert.equal(
    fixture.panel._adminFeaturePresentation(
      providerFeature,
      [genericInternet],
      new Map(),
      new Set(["internet"]),
      true,
    ).key,
    "read_only",
  );
  assert.equal(
    PANEL_TRANSLATIONS.en["admin.feature.status.read_only"],
    "Related read-only data available",
  );
});

test("split management cards require exact read evidence", () => {
  const fixture = panelFixture();
  const features = new Map(
    ADMIN_IA.flatMap((area) => area.subsections)
      .flatMap((subsection) => subsection.features)
      .map((feature) => [feature.id, feature]),
  );
  const entity = (translationKey, section, state = "on", extra = {}) => {
    const meta = {
      access_source: "protected_json",
      control: false,
      domain: "binary_sensor",
      entity_id: `binary_sensor.speedport_${translationKey}`,
      section,
      translation_key: translationKey,
      ...extra,
    };
    fixture.panel._hass.states[meta.entity_id] = { attributes: {}, state };
    return meta;
  };
  const dectBase = entity("dect_enabled", "telephony");
  const genericVoip = entity("telephony_providers", "telephony", "1", {
    capability_group: "telephony_voip",
    domain: "sensor",
  });
  const routerFirmware = entity("firmware_version", "system", "1.2.3", {
    domain: "sensor",
  });
  const presentation = (featureId, entities) =>
    fixture.panel._adminFeaturePresentation(
      features.get(featureId),
      entities,
      new Map(),
      new Set(["dect", "telephony", "system", "easysupport"]),
      true,
    ).key;

  assert.equal(presentation("telephony_dect_base", [dectBase]), "read_only");
  for (const featureId of [
    "telephony_dect_base_pin",
    "telephony_dect_transmit_power",
    "telephony_dect_full_eco",
    "telephony_dect_handset_call_waiting",
  ]) {
    assert.equal(presentation(featureId, [dectBase]), "not_observed", featureId);
  }
  for (const featureId of [
    "telephony_number_assignment",
    "telephony_number_use",
    "telephony_call_encryption",
    "telephony_hd_voice",
  ]) {
    assert.equal(presentation(featureId, [genericVoip]), "not_observed", featureId);
  }
  assert.equal(
    presentation("system_easysupport_automatic_firmware", [routerFirmware]),
    "not_observed",
  );

  const exactEncryption = entity(
    "telephony_voip_policy",
    "telephony",
    "level_1",
    { domain: "sensor" },
  );
  const exactHdVoice = entity("telephony_hd_voice_active", "telephony");
  const exactAutomaticFirmware = entity(
    "firmware_automatic_updates",
    "system",
  );
  assert.equal(
    presentation("telephony_call_encryption", [exactEncryption]),
    "read_only",
  );
  assert.equal(
    presentation("telephony_hd_voice", [exactHdVoice]),
    "read_only",
  );
  assert.equal(
    presentation("system_easysupport_automatic_firmware", [exactAutomaticFirmware]),
    "read_only",
  );
});

test("receiver telemetry never proves receiver firmware evidence", () => {
  const fixture = panelFixture();
  const features = new Map(
    ADMIN_IA.flatMap((area) => area.subsections)
      .flatMap((subsection) => subsection.features)
      .map((feature) => [feature.id, feature]),
  );
  const receiverMode = {
    access_source: "protected_json",
    child_device: { device_id: "receiver-1", kind: "receiver" },
    control: false,
    domain: "sensor",
    entity_id: "sensor.speedport_receiver_mode",
    section: "mobile",
    translation_key: "receiver_mode",
  };
  fixture.panel._hass.states[receiverMode.entity_id] = {
    attributes: {},
    state: "hybrid",
  };
  const receiverSections = new Map([
    [
      "receivers",
      {
        id: "receivers",
        rows: [{ model: "5G receiver", connected: true }],
        source: "protected_json",
        truncated: false,
      },
    ],
  ]);

  assert.deepEqual(
    features.get("internet_receiver_firmware_update").entityGroups,
    ["mobile_receiver_firmware"],
  );
  assert.deepEqual(
    features.get("internet_receiver_firmware_update").readSections,
    [],
  );
  assert.deepEqual(
    features.get("internet_receiver_factory_esim_restore").entityGroups,
    [],
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      features.get("internet_receiver_firmware_update"),
      [receiverMode],
      receiverSections,
      new Set(["receiver"]),
      true,
    ).key,
    "not_observed",
  );
  assert.equal(
    fixture.panel._adminFeaturePresentation(
      features.get("internet_receiver_mode"),
      [receiverMode],
      receiverSections,
      new Set(["receiver"]),
      true,
    ).key,
    "read_only",
  );
});

test("exact receiver firmware entity proves receiver firmware evidence", () => {
  const fixture = panelFixture();
  const feature = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find(
      (candidate) => candidate.id === "internet_receiver_firmware_update",
    );
  const firmware = {
    access_source: "protected_json",
    capability_group: "mobile_receiver_firmware",
    control: false,
    domain: "sensor",
    entity_id: "sensor.speedport_receiver_firmware_version",
    section: "mobile",
    translation_key: "receiver_firmware_version",
  };
  fixture.panel._hass.states[firmware.entity_id] = {
    attributes: {},
    state: "1.2.3",
  };

  assert.equal(
    fixture.panel._adminFeaturePresentation(
      feature,
      [firmware],
      new Map(),
      new Set(["receiver"]),
      true,
    ).key,
    "read_only",
  );
});

test("highest Administration risk uses exact backend risk order only", () => {
  assert.equal(
    highestAdminRisk([
      { control: true, risk: "normal" },
      { control: true, risk: "sensitive" },
      { control: true, risk: "lockout" },
      { control: false, risk: "destructive" },
    ]),
    "lockout",
  );
  assert.equal(
    highestAdminRisk([{ control: true, risk: "future-unknown" }]),
    undefined,
  );
  assert.equal(
    highestAdminRisk([
      { control: false, control_supported: true, risk: "destructive" },
    ]),
    "destructive",
  );
});

test("unmanifested controls cannot appear in Administration", () => {
  const fixture = panelFixture();
  const unknown = {
    ...CONTROL_META,
    entity_id: "button.speedport_future_generic_admin_action",
    translation_key: "future_generic_admin_action",
  };
  fixture.panel._hass.states = {
    [unknown.entity_id]: { attributes: {}, state: "unknown" },
  };

  const html = renderNativePages(fixture.panel,
    router("entry-a", [unknown]),
    [unknown],
    [],
    {},
  );

  assert.doesNotMatch(html, /button\.speedport_future_generic_admin_action/);
  assert.match(html, /Router management capabilities/);
  assert.doesNotMatch(html, /data-control="button\.speedport_future_generic_admin_action"/);
});

test("all native pages retain capability coverage without inventing controls", () => {
  const fixture = panelFixture();
  const html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  const featureMarkers = (html.match(/data-admin-feature="[^"]+"/g) || [])
    .filter((marker) => !marker.includes('="home_assistant_'));
  assert.equal(featureMarkers.length, 120);
  assert.equal(new Set(featureMarkers).size, 120);
  assert.ok(html.includes('data-detail-id="admin-integration-tools"'));
  assert.ok(html.includes('data-admin-feature="home_assistant_capability_inventory"'));
  assert.ok(!html.includes('data-admin-tab="home_assistant"'));
  assert.ok(!html.includes('class="administration-area"'));
  assert.ok(!html.includes('class="administration-subsection"'));
  assert.equal(new Set([...html.matchAll(/data-native-page="([^"]+)"/g)].map((match) => match[1])).size, 69);
  for (const label of [
    "Provider, account, MTU, VLAN, and fixed-IP configuration",
    "Analog socket incoming and outgoing number assignment",
    "Wi-Fi environment scan",
    "NAS shares and folders",
    "Restore local configuration backup",
    "Email notifications and event selection",
    "Local router display settings",
    "Rename a Mesh node",
    "Identify a Mesh node",
    "Delete a Mesh node",
    "Rename a Powerline node",
    "Safely remove or unmount a USB storage device",
    "Delete a VoIP provider",
    "Activate or deactivate a VoIP telephone number",
    "Restore 5G receiver factory settings, optionally deleting its eSIM",
  ]) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /No local router control/);
  assert.match(
    html,
    /safe local write and readback flow has not yet been verified/,
  );
  assert.doesNotMatch(html, /data-control=/);
});

test("integration diagnostics stay out of headline overview and native router pages", () => {
  const fixture = panelFixture();
  const entities = [FAST_POLLING_HEALTH_META, ENDPOINT_FAILURE_META];
  fixture.panel._hass.states = {
    [FAST_POLLING_HEALTH_META.entity_id]: {
      attributes: { friendly_name: "Fast polling health" },
      state: "healthy",
    },
    [ENDPOINT_FAILURE_META.entity_id]: {
      attributes: { friendly_name: "Endpoint failures" },
      state: "0",
    },
  };

  const html = renderNativePages(fixture.panel,
    router("entry-a", entities),
    [],
    entities,
    {},
  );

  assert.ok(!html.includes(FAST_POLLING_HEALTH_META.entity_id));
  assert.ok(!html.includes(ENDPOINT_FAILURE_META.entity_id));
  const dashboard = fixture.panel._renderDashboard(router("entry-a", entities), entities, {});
  assert.ok(!dashboard.includes(FAST_POLLING_HEALTH_META.entity_id));
  assert.ok(!dashboard.includes(ENDPOINT_FAILURE_META.entity_id));
  // Presentation narrowing never deletes or changes the underlying entity data.
  assert.equal(fixture.panel._hass.states[FAST_POLLING_HEALTH_META.entity_id].state, "healthy");
  assert.equal(fixture.panel._hass.states[ENDPOINT_FAILURE_META.entity_id].state, "0");
});

test("panel uses Home Assistant platform and state icons with custom overrides", async () => {
  const platformIcons = {
    binary_sensor: {
      wifi_enabled: { default: "mdi:wifi" },
    },
    sensor: {
      management_access: {
        default: "mdi:account-lock",
        state: { blocked: "mdi:account-alert" },
      },
    },
  };
  const componentIcons = {
    binary_sensor: {
      connectivity: {
        default: "mdi:close-network-outline",
        state: { on: "mdi:check-network-outline" },
      },
      problem: {
        default: "mdi:check-circle-outline",
        state: { on: "mdi:alert-circle-outline" },
      },
    },
    sensor: {
      duration: { default: "mdi:timer-outline" },
    },
  };
  const messages = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._hass = {
    connection: {
      async sendMessagePromise(message) {
        messages.push(message);
        return message.category === "entity"
          ? { resources: { speedport_smart: platformIcons } }
          : { resources: componentIcons };
      },
    },
  };

  await panel._loadPlatformIcons();

  assert.deepEqual(messages, [
    {
      type: "frontend/get_icons",
      category: "entity",
      integration: "speedport_smart",
    },
    {
      type: "frontend/get_icons",
      category: "entity_component",
    },
  ]);
  assert.equal(
    iconFor(
      { domain: "sensor", section: "management", translation_key: "management_access" },
      { attributes: {}, state: "blocked" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:account-alert",
  );
  assert.equal(
    iconFor(
      { domain: "sensor", section: "management", translation_key: "management_access" },
      { attributes: {}, state: "unknown" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:account-lock",
  );
  const registryMeta = {
    domain: "sensor",
    entity_id: "sensor.speedport_management_access",
    section: "management",
    translation_key: "management_access",
  };
  const registryState = {
    attributes: { icon: "mdi:star" },
    state: "blocked",
  };
  const registryEntries = {
    [registryMeta.entity_id]: { icon: "mdi:account-cog" },
  };
  assert.equal(
    iconFor(
      registryMeta,
      registryState,
      panel._platformIcons,
      panel._componentIcons,
      registryEntries,
    ),
    "mdi:account-cog",
  );
  panel._hass.entities = registryEntries;
  panel._hass.states = { [registryMeta.entity_id]: registryState };
  assert.match(
    panel._renderEntity(registryMeta),
    /<ha-icon icon="mdi:account-cog"><\/ha-icon>/,
  );
  assert.equal(
    iconFor(
      { domain: "binary_sensor", section: "wireless", translation_key: "wifi_enabled" },
      { attributes: { icon: "mdi:star" }, state: "on" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:star",
  );
  assert.equal(
    iconFor(
      {
        domain: "binary_sensor",
        section: "connection",
        translation_key: "internet_connected",
      },
      { attributes: { device_class: "connectivity" }, state: "on" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:check-network-outline",
  );
  assert.equal(
    iconFor(
      {
        domain: "binary_sensor",
        section: "system",
        translation_key: "router_problem",
      },
      { attributes: { device_class: "problem" }, state: "on" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:alert-circle-outline",
  );
  assert.equal(
    iconFor(
      {
        domain: "sensor",
        section: "management",
        translation_key: "request_latency",
      },
      { attributes: { device_class: "duration" }, state: "1.2" },
      panel._platformIcons,
      panel._componentIcons,
    ),
    "mdi:timer-outline",
  );
  const rangePlatformIcons = {
    sensor: {
      request_latency: {
        default: "mdi:speedometer-slow",
        range: {
          0: "mdi:speedometer-slow",
          "2.50": "mdi:speedometer-medium",
          10: "mdi:speedometer",
          "-Infinity": "mdi:alert",
          Infinity: "mdi:alert",
          invalid: "mdi:alert",
        },
      },
    },
  };
  const rangeMeta = {
    domain: "sensor",
    section: "management",
    translation_key: "request_latency",
  };
  assert.equal(
    iconFor(
      rangeMeta,
      { attributes: {}, state: "3" },
      rangePlatformIcons,
      panel._componentIcons,
    ),
    "mdi:speedometer-medium",
  );
  assert.equal(
    iconFor(
      rangeMeta,
      { attributes: {}, state: "-100" },
      rangePlatformIcons,
      panel._componentIcons,
    ),
    "mdi:speedometer-slow",
  );
  assert.equal(
    iconFor(
      {
        domain: "sensor",
        section: "management",
        translation_key: "request_latency",
      },
      { attributes: { device_class: "duration" }, state: "11" },
      {},
      {
        sensor: {
          duration: {
            default: "mdi:timer-outline",
            range: {
              0: "mdi:timer-sand-empty",
              5: "mdi:timer-sand",
              10: "mdi:timer-alert-outline",
            },
          },
        },
      },
    ),
    "mdi:timer-alert-outline",
  );
});

test("panel retries a transient Home Assistant icon-resource failure", async () => {
  let platformAttempts = 0;
  let componentAttempts = 0;
  const categories = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._hass = {
    connection: {
      async sendMessagePromise(message) {
        categories.push(message.category);
        if (message.category === "entity") {
          platformAttempts += 1;
          return { resources: { speedport_smart: {} } };
        }
        componentAttempts += 1;
        if (componentAttempts === 1) throw new Error("temporary failure");
        return { resources: { sensor: {} } };
      },
    },
  };

  await panel._loadPlatformIcons();
  assert.deepEqual(panel._platformIcons, {});
  assert.equal(panel._componentIcons, undefined);
  await panel._loadPlatformIcons();

  assert.deepEqual(panel._componentIcons, { sensor: {} });
  assert.equal(platformAttempts, 1);
  assert.equal(componentAttempts, 2);
  assert.deepEqual(categories, ["entity", "entity_component", "entity_component"]);
});

test("Dashboard shows headline telemetry while Administration keeps reviewed reports and controls", () => {
  const fixture = panelFixture();
  const headline = {...REPORTING_META, entity_id: "sensor.wifi_5_clients", translation_key: "wifi_5_clients", section: "wireless"};
  fixture.panel._metadata = {
    routers: [router("entry-a", [REPORTING_META, CONFIG_META, CONTROL_META, headline])],
  };
  fixture.panel._hass.states = {
    [headline.entity_id]: {attributes: {}, state: "25"},
    [REPORTING_META.entity_id]: {
      attributes: { friendly_name: "Router CPU" },
      state: "20",
    },
    [CONFIG_META.entity_id]: {
      attributes: { friendly_name: "Wi-Fi schedule mode" },
      state: "weekly",
    },
    [CONTROL_META.entity_id]: {
      attributes: { friendly_name: "Reboot router" },
      state: "unknown",
    },
  };
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ name: "Cached laptop" }],
        source: "protected_json",
        truncated: false,
      },
    ]),
    "entry-a",
  );

  SpeedportSmartPanel.prototype._render.call(fixture.panel);
  assert.match(fixture.panel.shadowRoot.innerHTML, /data-more-info="sensor\.wifi_5_clients"/);
  assert.doesNotMatch(fixture.panel.shadowRoot.innerHTML, /sensor\.speedport_system_cpu/);
  assert.doesNotMatch(
    fixture.panel.shadowRoot.innerHTML,
    /sensor\.speedport_wifi_schedule_mode/,
  );
  assert.doesNotMatch(
    fixture.panel.shadowRoot.innerHTML,
    /button\.speedport_reboot_router|Cached laptop/,
  );

  fixture.panel._activeView = "administration";
  for (const [tab, page, expected] of [
    ["system", "system_recovery_restart", "button.speedport_reboot_router"],
    ["network", "network_devices", "Cached laptop"],
    ["network", "network_wifi_basic", "sensor.speedport_wifi_schedule_mode"],
    ["system", "system_information_data", "sensor.speedport_system_cpu"],
  ]) {
    fixture.panel._adminTab = tab; fixture.panel._adminPage = page;
    SpeedportSmartPanel.prototype._render.call(fixture.panel);
    assert.ok(fixture.panel.shadowRoot.innerHTML.includes(expected), page);
    assert.ok(fixture.panel.shadowRoot.innerHTML.includes(`data-native-page="${page}"`));
  }
});

test("administrator payload validation keeps only fixed sections and fields", () => {
  const payload = adminPayload("entry-a", [
    {
      id: "clients",
      source: "protected_json",
      rows: [
        {
          connected: true,
          endpoint: "/data/private.json",
          name: "x".repeat(400),
          nested: { hidden: true },
        },
      ],
      truncated: false,
    },
  ]);

  const normalized = normalizeAdminReadPayload(payload, "entry-a");

  assert.equal(normalized.sections[0].rows[0].name.length, 256);
  assert.deepEqual(Object.keys(normalized.sections[0].rows[0]).sort(), [
    "connected",
    "name",
  ]);
  assert.equal(
    normalizeAdminReadPayload({ ...payload, schema_version: 1 }, "entry-a"),
    undefined,
  );
  assert.equal(normalizeAdminReadPayload(payload, "entry-b"), undefined);
  assert.equal(
    normalizeAdminReadPayload(
      adminPayload("entry-a", [
        {
          id: "unknown",
          rows: [],
          source: "protected_json",
          truncated: false,
        },
      ]),
      "entry-a",
    ),
    undefined,
  );
  for (const id of ["__proto__", "constructor"]) {
    for (const rows of [[], [{ name: "must not be read" }]]) {
      assert.doesNotThrow(() =>
        normalizeAdminReadPayload(
          adminPayload("entry-a", [
            { id, rows, source: "protected_json", truncated: false },
          ]),
          "entry-a",
        ),
      );
      assert.equal(
        normalizeAdminReadPayload(
          adminPayload("entry-a", [
            { id, rows, source: "protected_json", truncated: false },
          ]),
          "entry-a",
        ),
        undefined,
      );
    }
  }
});

test("new administrator identifiers stay read-only and section-bound", () => {
  const rows = {
    mesh_nodes: {
      wifi_2_4_mac: "AA:BB:CC:DD:EE:01",
      wifi_5_mac: "AA:BB:CC:DD:EE:02",
    },
    vpn_peers: { id: "peer-safe-id" },
    telephone_lines: { provider_id: "provider-safe-id" },
    storage_devices: { serial: "SERIAL-SAFE" },
    nas_shares: { id: "share-safe-id" },
  };
  const normalized = normalizeAdminReadPayload(
    adminPayload(
      "entry-a",
      Object.entries(rows).map(([id, row]) => ({
        id,
        rows: [{ ...row, private_secret: "MUST-NOT-SURVIVE" }],
        source: "protected_json",
        truncated: false,
      })),
    ),
    "entry-a",
  );
  assert.deepEqual(
    Object.fromEntries(
      normalized.sections.map((section) => [section.id, section.rows[0]]),
    ),
    rows,
  );

  const { panel } = panelFixture();
  const markup = normalized.sections
    .map((section) =>
      panel._renderAdminReadSection(section.id, section, {
        sourceAvailable: true,
      }),
    )
    .join("");
  for (const value of [
    "AA:BB:CC:DD:EE:01",
    "AA:BB:CC:DD:EE:02",
    "peer-safe-id",
    "provider-safe-id",
    "SERIAL-SAFE",
    "share-safe-id",
  ]) {
    assert.match(markup, new RegExp(value));
  }
  assert.match(markup, /2\.4 GHz radio MAC address/);
  assert.match(markup, /5 GHz radio MAC address/);
  assert.match(markup, /Provider identifier/);
  assert.doesNotMatch(markup, /MUST-NOT-SURVIVE|private_secret/);
});

test("LAN IPv6 technical flags stay exact read-only administrator data", () => {
  const normalized = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "lan_ipv6_technical",
        source: "protected_json",
        rows: [
          {
            ipv6_pext_flag: true,
            ipv6_arec_flag: false,
            semantic_guess: "must not survive",
          },
        ],
        truncated: false,
      },
    ]),
    "entry-a",
  );

  assert.deepEqual(normalized.sections[0].rows, [
    { ipv6_pext_flag: true, ipv6_arec_flag: false },
  ]);

  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalized;
  const html = renderNativePages(fixture.panel,
    { ...router("entry-a"), capabilities: ["lan"] },
    [],
    [],
    { protected_json: { available: true } },
  );
  assert.match(html, /LAN IPv6 firmware flags/);
  assert.match(html, /lan_ip_v6_pext \(undocumented\)/);
  assert.match(html, /lan_ip_v6_arec \(undocumented\)/);
  assert.match(html, /<dd>Yes<\/dd>/);
  assert.match(html, /<dd>No<\/dd>/);
  assert.doesNotMatch(html, /semantic_guess|must not survive/);
  assert.doesNotMatch(html, /data-control=.*lan_ip_v6/);
});

test("public Status domain_name stays an exact administrator-only technical read", () => {
  const normalized = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "status_technical",
        source: "public_status",
        rows: [
          {
            domain_name: "speedport.ip",
            loginstate: "must not survive",
          },
        ],
        truncated: false,
      },
    ]),
    "entry-a",
  );

  assert.deepEqual(normalized.sections[0], {
    id: "status_technical",
    source: "public_status",
    rows: [{ domain_name: "speedport.ip" }],
    truncated: false,
  });

  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalized;
  const html = renderNativePages(fixture.panel,
    { ...router("entry-a"), capabilities: ["system"] },
    [],
    [],
    {
      protected_json: { available: false },
      public_status: { available: true },
    },
  );
  assert.match(html, /Firmware status fields/);
  assert.match(html, /Firmware field: domain_name/);
  assert.match(html, /speedport\.ip/);
  assert.doesNotMatch(html, /must not survive/);
  assert.doesNotMatch(html, /data-control=.*domain_name/);
});

test("public Status fail_reason stays an exact Internet technical read", () => {
  const normalized = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "internet_status_technical",
        source: "public_status",
        rows: [
          {
            failure_reason: "net",
            failure_detail: "must not survive",
          },
        ],
        truncated: false,
      },
    ]),
    "entry-a",
  );

  assert.deepEqual(normalized.sections[0], {
    id: "internet_status_technical",
    source: "public_status",
    rows: [{ failure_reason: "net" }],
    truncated: false,
  });

  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalized;
  const html = renderNativePages(fixture.panel,
    { ...router("entry-a"), capabilities: ["internet"] },
    [],
    [],
    {
      protected_json: { available: false },
      public_status: { available: true },
    },
  );
  assert.match(html, /Internet firmware status/);
  assert.match(html, /Firmware field: fail_reason/);
  assert.match(html, /<dd>net<\/dd>/);
  assert.doesNotMatch(html, /failure_detail|must not survive/);
  assert.doesNotMatch(html, /data-control=.*failure_reason/);
  const featureWindow = (featureId) => {
    const marker = `data-admin-feature="${featureId}"`;
    const start = html.indexOf(marker);
    assert.notEqual(start, -1, featureId);
    const following = html.slice(start + marker.length);
    const next = following.search(/data-admin-feature="[^"]+"/);
    return next === -1
      ? html.slice(start)
      : html.slice(start, start + marker.length + next);
  };
  const diagnosticsWindow = featureWindow("internet_connection_diagnostics");
  assert.match(diagnosticsWindow, /data-detail-id="admin-read:internet_status_technical"/);
  assert.doesNotMatch(
    featureWindow("internet_provider_configuration"),
    /data-detail-id="admin-read:internet_status_technical"/,
  );

  const rejected = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "internet_status_technical",
        source: "public_status",
        rows: [{ failure_reason: "account@example.net" }],
        truncated: false,
      },
    ]),
    "entry-a",
  );
  assert.deepEqual(rejected.sections[0].rows, []);
});

test("only Home Assistant administrators call the cached-read endpoint", async () => {
  const allowed = panelFixture({ admin: true });
  await allowed.panel._loadAdminRead("entry-a");

  assert.deepEqual(allowed.calls, [
    { entry_id: "entry-a", type: "speedport_smart/panel/admin_read" },
  ]);
  assert.equal(allowed.panel._adminReadEntry, "entry-a");
  assert.equal(allowed.panel._adminRead.sections[0].rows[0].name, "Laptop");

  const denied = panelFixture({ admin: false });
  await denied.panel._loadAdminRead("entry-a");
  assert.deepEqual(denied.calls, []);
  assert.equal(denied.panel._adminRead, undefined);
});

test("cached Administration re-entry renders immediately and refreshes without overlap", async () => {
  const fixture = panelFixture({ admin: true });
  const requests = [];
  const resolveReads = [];
  fixture.panel._requestPrivate = (message) => {
    requests.push(message);
    return new Promise((resolve) => {
      resolveReads.push(resolve);
    });
  };
  fixture.panel._adminRead = adminPayload("entry-a", [
    {
      id: "clients",
      rows: [{ connected: true, name: "Cached laptop" }],
      source: "protected_json",
      truncated: false,
    },
  ]);
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._activeView = "dashboard";
  const renders = [];
  fixture.panel._render = () => {
    renders.push({
      loading: fixture.panel._adminReadLoading,
      view: fixture.panel._activeView,
    });
  };

  fixture.panel._selectView("administration");

  assert.deepEqual(renders[0], { loading: false, view: "administration" });
  assert.equal(requests.length, 1);
  assert.equal(fixture.panel._adminReadLoading, true);

  fixture.panel._selectView("dashboard");
  fixture.panel._selectView("administration");
  assert.equal(requests.length, 1);

  resolveReads[0](
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ connected: true, name: "Fresh laptop" }],
        source: "protected_json",
        truncated: false,
      },
    ]),
  );
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(requests.length, 2);
  assert.equal(fixture.panel._adminReadLoading, true);
  resolveReads[1](
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ connected: true, name: "Latest laptop" }],
        source: "protected_json",
        truncated: false,
      },
    ]),
  );
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(fixture.panel._adminReadLoading, false);
  assert.equal(fixture.panel._adminRead.sections[0].rows[0].name, "Latest laptop");
});

test("router change and disconnect clear private cached data", async () => {
  const fixture = panelFixture({ entries: ["entry-a", "entry-b"] });
  await fixture.panel._loadAdminRead("entry-a");
  assert.ok(fixture.panel._adminRead);

  fixture.panel._selectRouter("entry-b");
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);

  fixture.panel._adminRead = adminPayload("entry-b");
  fixture.panel._adminReadEntry = "entry-b";
  fixture.panel.disconnectedCallback();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("Entity Registry icon changes rerender without a state change", () => {
  const fixture = panelFixture();
  const state = { attributes: {}, state: "20" };
  fixture.panel._metadata = {
    routers: [router("entry-a", [REPORTING_META])],
  };
  fixture.panel._hass = {
    ...fixture.panel._hass,
    entities: {
      [REPORTING_META.entity_id]: { icon: "mdi:gauge" },
    },
    states: { [REPORTING_META.entity_id]: state },
  };
  let scheduled = 0;
  fixture.panel._scheduleRender = () => {
    scheduled += 1;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    entities: {
      [REPORTING_META.entity_id]: { icon: "mdi:chip" },
    },
  };

  assert.equal(scheduled, 1);
  assert.equal(fixture.panel._hass.states[REPORTING_META.entity_id], state);
});

test("rapid WAN telemetry changes rerender Dashboard, not Administration", () => {
  const fixture = panelFixture();
  const configurationState = { attributes: {}, state: "weekly" };
  const controlState = { attributes: {}, state: "unknown" };
  fixture.panel._metadata = {
    routers: [
      router("entry-a", [WAN_RATE_META, CONFIG_META, CONTROL_META]),
    ],
  };
  fixture.panel._hass = {
    ...fixture.panel._hass,
    states: {
      [WAN_RATE_META.entity_id]: { attributes: {}, state: "1" },
      [CONFIG_META.entity_id]: configurationState,
      [CONTROL_META.entity_id]: controlState,
    },
  };
  let scheduled = 0;
  fixture.panel._scheduleRender = () => {
    scheduled += 1;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    states: {
      ...fixture.panel._hass.states,
      [WAN_RATE_META.entity_id]: { attributes: {}, state: "2" },
    },
  };
  assert.equal(scheduled, 1);

  fixture.panel._activeView = "administration";
  scheduled = 0;
  for (let sample = 3; sample <= 20; sample += 1) {
    fixture.panel.hass = {
      ...fixture.panel._hass,
      states: {
        ...fixture.panel._hass.states,
        [WAN_RATE_META.entity_id]: {
          attributes: {},
          state: String(sample),
        },
      },
    };
  }

  assert.equal(scheduled, 0);

  let renderedWanState;
  fixture.panel._render = () => {
    renderedWanState =
      fixture.panel._hass.states[WAN_RATE_META.entity_id].state;
  };
  fixture.panel._selectView("dashboard");
  assert.equal(renderedWanState, "20");
});

test("available feature-only WAN and LTE values do not rerender Administration", () => {
  const fixture = panelFixture();
  fixture.panel._activeView = "administration";
  fixture.panel._metadata = {
    routers: [router("entry-a", [WAN_INTERFACE_META, LTE_TUNNEL_META])],
  };
  fixture.panel._hass = {
    ...fixture.panel._hass,
    states: {
      [WAN_INTERFACE_META.entity_id]: { attributes: {}, state: "down" },
      [LTE_TUNNEL_META.entity_id]: { attributes: {}, state: "100" },
    },
  };
  let scheduled = 0;
  fixture.panel._scheduleRender = () => {
    scheduled += 1;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    states: {
      ...fixture.panel._hass.states,
      [WAN_INTERFACE_META.entity_id]: { attributes: {}, state: "up" },
    },
  };
  assert.equal(scheduled, 0);

  for (let sample = 101; sample <= 120; sample += 1) {
    fixture.panel.hass = {
      ...fixture.panel._hass,
      states: {
        ...fixture.panel._hass.states,
        [LTE_TUNNEL_META.entity_id]: {
          attributes: {},
          state: String(sample),
        },
      },
    };
  }
  assert.equal(scheduled, 0);
});

test("feature-only availability recovery rerenders Administration", () => {
  const fixture = panelFixture();
  fixture.panel._activeView = "administration";
  fixture.panel._metadata = {
    routers: [router("entry-a", [WAN_INTERFACE_META])],
  };
  fixture.panel._hass = {
    ...fixture.panel._hass,
    states: {
      [WAN_INTERFACE_META.entity_id]: {
        attributes: {},
        state: "unavailable",
      },
    },
  };
  let scheduled = 0;
  fixture.panel._scheduleRender = () => {
    scheduled += 1;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    states: {
      ...fixture.panel._hass.states,
      [WAN_INTERFACE_META.entity_id]: { attributes: {}, state: "up" },
    },
  };

  assert.equal(scheduled, 1);
});

test("Administration rerenders for visible reporting and control changes", () => {
  const fixture = panelFixture();
  fixture.panel._activeView = "administration";
  fixture.panel._metadata = {
    routers: [router("entry-a", [CONFIG_META, CONTROL_META])],
  };
  fixture.panel._hass = {
    ...fixture.panel._hass,
    states: {
      [CONFIG_META.entity_id]: { attributes: {}, state: "weekly" },
      [CONTROL_META.entity_id]: { attributes: {}, state: "unknown" },
    },
  };
  let scheduled = 0;
  fixture.panel._scheduleRender = () => {
    scheduled += 1;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    states: {
      ...fixture.panel._hass.states,
      [CONFIG_META.entity_id]: { attributes: {}, state: "disabled" },
    },
  };
  assert.equal(scheduled, 1);

  fixture.panel.hass = {
    ...fixture.panel._hass,
    states: {
      ...fixture.panel._hass.states,
      [CONTROL_META.entity_id]: { attributes: {}, state: "pressed" },
    },
  };
  assert.equal(scheduled, 2);
});

test("administrator demotion rerenders and clears private cached data", () => {
  const fixture = panelFixture({ admin: true });
  let scheduled = false;
  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._scheduleRender = () => {
    scheduled = true;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    user: { id: "limited-user", is_admin: false },
  };

  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
  assert.equal(scheduled, true);
});

test("entry unload and metadata failure clear private cached data", async () => {
  const fixture = panelFixture({ admin: true });
  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._hass.connection.sendMessagePromise = async () => ({
    routers: [{ ...router("entry-a"), entry_state: "not_loaded" }],
    schema_version: 8,
  });

  await fixture.panel._loadMetadata();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);

  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._hass.connection.sendMessagePromise = async () => {
    throw new Error("connection unavailable");
  };

  await fixture.panel._loadMetadata();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("stale administrator response cannot cross a router change", async () => {
  let resolveRequest;
  const fixture = panelFixture({ entries: ["entry-a", "entry-b"] });
  fixture.panel._requestPrivate = () =>
    new Promise((resolve) => {
      resolveRequest = resolve;
    });

  const pending = fixture.panel._loadAdminRead("entry-a");
  fixture.panel._selectRouter("entry-b");
  resolveRequest(adminPayload("entry-a"));
  await pending;

  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("administrator read failure is isolated from normal metadata", async () => {
  const fixture = panelFixture();
  const metadata = fixture.panel._metadata;
  fixture.panel._requestPrivate = async () => {
    throw new Error("backend unavailable");
  };

  await fixture.panel._loadAdminRead("entry-a");

  assert.equal(fixture.panel._metadata, metadata);
  assert.equal(fixture.panel._loadError, "");
  assert.equal(fixture.panel._adminReadError, "error.admin_read_unavailable");
});

test("administrator renderer nests all collections in fixed related areas", () => {
  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload(
      "entry-a",
      ADMIN_READ_SECTION_ORDER.map((id) => ({
        id,
        rows:
          id === "clients"
            ? [{ connected: true, name: "<script>unsafe</script>" }]
            : [],
        source: ["internet_status_technical", "status_technical"].includes(id)
          ? "public_status"
          : "protected_json",
        truncated: id === "clients",
      })),
    ),
    "entry-a",
  );

  const html = renderNativePages(fixture.panel,
    router("entry-a"),
    [CONTROL_META],
    [
      {
        access_source: "protected_json",
        child_device: { device_id: "client-1", kind: "client", name: "Laptop" },
        confirmation: "none",
        control: false,
        disruptive: false,
        domain: "binary_sensor",
        entity_id: "binary_sensor.speedport_laptop_connected",
        risk: "normal",
        section: "clients",
        translation_key: "client_connected",
      },
      {
        access_source: "protected_json",
        child_device: {
          device_id: "receiver-1",
          kind: "receiver",
          name: "5G receiver",
        },
        confirmation: "none",
        control: false,
        disruptive: false,
        domain: "sensor",
        entity_id: "sensor.speedport_receiver_signal_strength",
        risk: "normal",
        section: "mobile",
        translation_key: "receiver_signal_strength",
      },
    ],
    { protected_json: { available: true } },
  );

  assert.equal(new Set([...html.matchAll(/data-detail-id="admin-read:([^"]+)"/g)].map((match) => match[1])).size, ADMIN_READ_SECTION_ORDER.length);
  for (const id of ["internet_receiver_connection", "telephony_registration", "network_devices"]) assert.ok(html.includes(`data-native-page="${id}"`));
  for (const title of [
    "Network devices",
    "Mesh nodes",
    "Port forwarding rules",
    "Port-blocking rules",
    "DNS rebind exceptions",
    "Prioritized client slots",
    "VPN peers",
    "Telephony providers",
    "Telephone lines",
    "DECT handsets",
    "DECT repeaters",
    "IP phones",
    "Telephone-system clients",
    "USB devices",
    "Mobile receivers",
    "Storage devices",
    "NAS shares",
    "Powerline devices",
  ]) {
    assert.match(html, new RegExp(title));
  }
  assert.match(html, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>unsafe<\/script>/);
  assert.doesNotMatch(html, /callService|sendMessagePromise/);
  assert.match(html, /data-control="button\.speedport_reboot_router"/);
  assert.match(html, /binary_sensor\.speedport_laptop_connected/);
  assert.match(html, /sensor\.speedport_receiver_signal_strength/);
  assert.doesNotMatch(
    html,
    /data-control="(?:binary_sensor\.speedport_laptop_connected|sensor\.speedport_receiver_signal_strength)"/,
  );
  assert.doesNotMatch(html, /sendMessagePromise|speedport_smart\/panel\/admin_read/);
  assert.match(html, /bounded display/);
  assert.match(html, /No displayable reviewed details/);
  assert.ok(html.indexOf("Mobile receivers") < html.indexOf("Telephone lines"));
  assert.ok(html.indexOf("Telephone lines") < html.indexOf("Network devices"));
});

test("known, empty, unavailable, and not-observed collections remain distinct", () => {
  const fixture = panelFixture();
  const natRouter = {
    ...router("entry-a", []),
    capabilities: ["nat"],
  };

  let html = renderNativePages(fixture.panel,
    natRouter,
    [],
    [],
    { protected_json: { available: true } },
  );
  assert.match(html, /Port forwarding rules/);
  assert.match(html, /Not present in the cached snapshot/);
  assert.match(html, /Network devices|Mesh nodes|VPN peers/);

  html = renderNativePages(fixture.panel,
    natRouter,
    [],
    [],
    { protected_json: { available: false } },
  );
  assert.match(html, /Temporarily unavailable/);
  assert.match(html, /known collection is temporarily unavailable/);

  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [],
        source: "protected_json",
        truncated: false,
      },
    ]),
    "entry-a",
  );
  html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  assert.match(html, /0 cached rows/);
  assert.match(html, /No displayable reviewed details/);
  assert.doesNotMatch(html, /Temporarily unavailable/);
});

test("failed admin refresh marks cached feature evidence temporarily unavailable", () => {
  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ connected: true, name: "Laptop" }],
        source: "protected_json",
        truncated: false,
      },
    ]),
    "entry-a",
  );
  fixture.panel._adminReadError = "error.admin_read_unavailable";

  const html = renderNativePages(fixture.panel,
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  const start = html.indexOf('data-admin-feature="network_client_inventory"');
  assert.notEqual(start, -1);
  const next = html.indexOf('data-admin-feature="', start + 1);
  const card = html.slice(start, next === -1 ? undefined : next);
  assert.ok(card.includes(PANEL_TRANSLATIONS.en["admin.feature.status.temporarily_unavailable"]));
});

test("risk badges and summaries show exact backend-provided tiers", () => {
  const fixture = panelFixture();
  const normalControl = {
    ...CONTROL_META,
    disruptive: false,
    domain: "button",
    entity_id: "button.speedport_wps",
    risk: "normal",
    translation_key: "wps",
  };
  const lockoutControl = {
    ...CONTROL_META,
    entity_id: "button.speedport_reboot_router",
    risk: "lockout",
  };
  fixture.panel._hass.states = {
    [normalControl.entity_id]: { attributes: {}, state: "unknown" },
    [lockoutControl.entity_id]: { attributes: {}, state: "unknown" },
  };

  const html = renderNativePages(fixture.panel,
    router("entry-a", [normalControl, lockoutControl]),
    [normalControl, lockoutControl],
    [],
    {},
  );

  assert.ok(html.includes(`data-control="${normalControl.entity_id}"`));
  assert.ok(html.includes(`data-control="${lockoutControl.entity_id}"`));
  // Native navigation has no risk summary cards; action-level risk labels stay exact.
  assert.ok(fixture.panel._renderRiskBadge("lockout").includes('aria-label="Risk: Lockout">Lockout'));
  assert.ok(fixture.panel._renderRiskBadge("destructive").includes('aria-label="Risk: Destructive">Destructive'));
  assert.equal(highestAdminRisk([normalControl, lockoutControl]), "lockout");
});

test("successful existing action refreshes only the active administrator cache", async () => {
  const fixture = panelFixture();
  const serviceCalls = [];
  const reloads = [];
  fixture.panel._activeView = "administration";
  fixture.panel._hass.states = {
    [CONTROL_META.entity_id]: { attributes: {}, state: "unknown" },
  };
  fixture.panel._hass.callService = async (...args) => serviceCalls.push(args);
  fixture.panel._loadAdminRead = async (...args) => reloads.push(args);
  fixture.panel._pendingAction = {
    actionLabel: "Restart",
    confirmationDraft: "",
    confirmationPhrase: undefined,
    confirmationPolicy: "confirm",
    entityId: CONTROL_META.entity_id,
    kind: "action",
    risk: "disruptive",
  };

  await fixture.panel._runPendingAction();

  assert.deepEqual(serviceCalls, [
    ["button", "press", { entity_id: CONTROL_META.entity_id }],
  ]);
  assert.deepEqual(reloads, [["entry-a", { force: true }]]);
});

test("successful Dashboard action does not request administrator cache", async () => {
  const fixture = panelFixture();
  const reloads = [];
  fixture.panel._activeView = "dashboard";
  fixture.panel._hass.states = {
    [CONTROL_META.entity_id]: { attributes: {}, state: "unknown" },
  };
  fixture.panel._hass.callService = async () => {};
  fixture.panel._loadAdminRead = async (...args) => reloads.push(args);
  fixture.panel._pendingAction = {
    actionLabel: "Restart",
    confirmationDraft: "",
    confirmationPhrase: undefined,
    confirmationPolicy: "confirm",
    entityId: CONTROL_META.entity_id,
    kind: "action",
    risk: "disruptive",
  };

  await fixture.panel._runPendingAction();

  assert.deepEqual(reloads, []);
});

test("every administrator field, section, and feature has English and German labels", () => {
  assert.equal(ADMIN_READ_SECTION_ORDER.length, 26);
  for (const section of ADMIN_READ_SECTION_ORDER) {
    const key = `admin.section.${section}`;
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.de, key), key);
  }
  for (const field of ADMIN_READ_FIELD_KEYS) {
    const key = `admin.field.${field}`;
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.de, key), key);
  }
  for (const area of ADMIN_IA) {
    for (const key of [
      area.titleKey,
      ...area.subsections.map((subsection) => subsection.titleKey),
      ...area.subsections.flatMap((subsection) =>
        subsection.features.map((feature) => feature.titleKey),
      ),
    ]) {
      assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
      assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.de, key), key);
    }
  }
  for (const risk of [
    "normal",
    "sensitive",
    "disruptive",
    "lockout",
    "destructive",
  ]) {
    const key = `admin.risk.${risk}`;
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.de, key), key);
  }
});

test("frontend and backend administrator read contracts stay identical", () => {
  const modulePath = fileURLToPath(
    new URL(
      "../../custom_components/speedport_smart/panel_read.py",
      import.meta.url,
    ),
  );
  const localPython = fileURLToPath(
    new URL("../../.venv/bin/python", import.meta.url),
  );
  const python = existsSync(localPython) ? localPython : "python";
  const script = `
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("speedport_panel_read_contract", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps({
    "schema_version": module.ADMIN_READ_SCHEMA_VERSION,
    "sections": {
        item.section_id: {
            "fields": list(item.fields),
            "source": item.source,
        }
        for item in (*module._COLLECTIONS, *module._RECORDS)
    },
    "closed_enums": {
        "failure_reason": sorted(module._INTERNET_FAILURE_REASONS),
    },
}))
`;
  const result = spawnSync(python, ["-c", script, modulePath], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const backend = JSON.parse(result.stdout);
  assert.equal(backend.schema_version, 2);
  assert.deepEqual(Object.keys(backend.sections), ADMIN_READ_SECTION_ORDER);
  assert.deepEqual(
    backend.sections,
    Object.fromEntries(
      ADMIN_READ_SECTION_ORDER.map((sectionId) => [
        sectionId,
        {
          fields: ADMIN_READ_SECTION_FIELDS[sectionId],
          source: ADMIN_READ_SECTION_SOURCES[sectionId],
        },
      ]),
    ),
  );
  assert.deepEqual(backend.closed_enums, ADMIN_READ_CLOSED_ENUM_VALUES);
});

test("frontend reviewed router controls stay identical to backend write mappings", () => {
  const modulePath = fileURLToPath(
    new URL(
      "../../custom_components/speedport_smart/management.py",
      import.meta.url,
    ),
  );
  const localPython = fileURLToPath(
    new URL("../../.venv/bin/python", import.meta.url),
  );
  const python = existsSync(localPython) ? localPython : "python";
  const script = `
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("speedport_management_contract", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps(sorted(
    f"{domain}:{translation_key}"
    for domain, translation_key in module._ENTITY_WRITE_COMMANDS
)))
`;
  const result = spawnSync(python, ["-c", script, modulePath], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const backendControls = JSON.parse(result.stdout);
  const homeAssistantFeatures = ADMIN_IA.find(
    (area) => area.id === "home_assistant",
  ).subsections.flatMap((subsection) => subsection.features);
  assert.deepEqual(
    homeAssistantFeatures
      .filter((feature) => feature.controls.length > 0)
      .map((feature) => [feature.contract, ...feature.controls]),
    [
      ["reviewed", "button:retry_protected_data"],
      ["read_only", "button:capture_read_only_inventory"],
    ],
  );

  const frontendControls = ADMIN_IA.filter(
    (area) => area.id !== "home_assistant",
  )
    .flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .filter((feature) => feature.contract === "reviewed")
    .flatMap((feature) => feature.controls)
    .filter((control) => control !== "button:capture_read_only_inventory")
    .sort();

  assert.deepEqual(frontendControls, backendControls);
});

test("administrator values use bounded native units", () => {
  assert.equal(formatAdminReadValue("connected", true, "en-US", "en"), "Yes");
  assert.equal(
    formatAdminReadValue("link_speed_bps", 1_000_000_000, "en-US", "en"),
    "1,000 Mbit/s",
  );
  assert.equal(
    formatAdminReadValue("total_bytes", 1_500_000_000, "en-US", "en"),
    "1.5 GB",
  );
  assert.equal(
    formatAdminReadValue("uptime_seconds", 3_661, "en-US", "en"),
    "1 h 1 min",
  );
});

test("Administration stays full-width, responsive, and theme-native", async () => {
  const source = await readFile(
    new URL(
      "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /\.shell\s*\{[^}]*width:\s*100%/s);
  assert.doesNotMatch(source, /1540px/);
  assert.match(source, /\.administration-view\s*\{[^}]*width:\s*100%/s);
  assert.match(source, /\.view-tabs\s*\{[^}]*width:\s*100%/s);
  assert.match(
    source,
    /\.view-tabs button:only-child\s*\{[^}]*grid-column:\s*1\s*\/\s*-1/s,
  );
  assert.doesNotMatch(source, /\.view-tabs\s*\{[^}]*620px/s);
  assert.match(
    source,
    /\.administration-subsections\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s,
  );
  assert.match(
    source,
    /@media \(max-width: 900px\)[\s\S]*?\.administration-subsections\s*\{[^}]*grid-template-columns:\s*1fr;/,
  );
  assert.match(
    source,
    /\.admin-read-overview\s*\{[^}]*background:\s*var\(--sp-surface\)/s,
  );
  assert.ok(source.includes('class="admin-native-layout"'));
  assert.ok(source.includes('class="admin-native-page"'));
  assert.ok(source.includes('data-admin-menu aria-expanded='));
  assert.match(source, /color-mix\(in srgb, var\(--sp-warning\)/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\./);
});
