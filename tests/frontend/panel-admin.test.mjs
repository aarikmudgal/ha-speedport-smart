import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

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
  ADMIN_READ_FIELD_KEYS,
  ADMIN_READ_SECTION_FIELDS,
  ADMIN_READ_SECTION_ORDER,
  SpeedportSmartPanel,
  adminPlacementFor,
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
  return { entry_id: entryId, schema_version: 1, sections };
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
  return { calls, panel };
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
  const html = fixture.panel._renderAdministration(
    router("entry-a", [READ_ONLY_CONTROL_META]),
    [READ_ONLY_CONTROL_META],
    [],
    {},
  );

  assert.match(html, /button\.speedport_reboot_router/);
  assert.doesNotMatch(html, /data-control="button\.speedport_reboot_router"/);
});

test("all reviewed permission-denied controls retain exact placement and zero actions", () => {
  const reviewed = ADMIN_IA.flatMap((area) =>
    area.subsections.flatMap((subsection) =>
      subsection.controls.map((control) => ({
        control,
        placement: { areaId: area.id, subsectionId: subsection.id },
      })),
    ),
  );
  assert.equal(reviewed.length, 14);

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
    const html = fixture.panel._renderAdministration(
      router("entry-a", [meta]),
      [meta],
      [],
      {},
    );
    assert.match(html, new RegExp(meta.entity_id.replaceAll(".", "\\.")), control);
    assert.doesNotMatch(html, /data-control=/, control);
  }
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
    mesh_nodes: "network",
    nas_shares: "network",
    pbx_clients: "telephony",
    port_block_rules: "internet",
    port_forward_rules: "internet",
    powerline_nodes: "network",
    qos_prioritized_clients: "network",
    receivers: "internet",
    storage_devices: "network",
    telephony_providers: "telephony",
    telephone_lines: "telephony",
    usb_devices: "network",
    vpn_peers: "internet",
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
  assert.equal(readSubsectionPlacements.ddns_identity, "internet_ddns");
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
  const analogFeature = ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.id === "telephony_analog_sockets");
  assert.deepEqual(analogFeature.capabilities, ["telephony", "analog"]);
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
    ["system", "system_operating_mode", ["system", "system_information"]],
    ["system", "router_https_enabled", ["system", "system_security"]],
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

test("Administration catalog covers every reviewed management family without generic controls", () => {
  const subsections = ADMIN_IA.flatMap((area) => area.subsections);
  const features = subsections.flatMap((subsection) => subsection.features);
  const featureIds = features.map((feature) => feature.id);

  assert.equal(subsections.length, 27);
  assert.equal(features.length, 73);
  assert.equal(new Set(featureIds).size, featureIds.length);
  assert.deepEqual(
    [...new Set(features.map((feature) => feature.contract))].sort(),
    ["blocked", "read_only", "reviewed", "unsupported"],
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
      byId("internet_vpn_management"),
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

  const html = fixture.panel._renderAdministration(
    router("entry-a", [unknown]),
    [unknown],
    [],
    {},
  );

  assert.doesNotMatch(html, /button\.speedport_future_generic_admin_action/);
  assert.match(html, /Router management capabilities/);
  assert.doesNotMatch(html, /data-control="button\.speedport_future_generic_admin_action"/);
});

test("complete capability catalog remains visible and noninteractive without live data", () => {
  const fixture = panelFixture();
  const html = fixture.panel._renderAdministration(
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  const featureCards =
    html.match(/<article class="admin-feature-card[\s\S]*?<\/article>/g) || [];
  const inventoryCard = featureCards.find((card) =>
    card.includes("Read-only router capability inventory"),
  );

  assert.equal(featureCards.length, 73);
  assert.ok(inventoryCard);
  assert.match(inventoryCard, /Read-only by design/);
  assert.doesNotMatch(inventoryCard, /destructive-candidate/);
  assert.equal(
    (html.match(/class="administration-area"/g) || []).length,
    ADMIN_IA.length,
  );
  assert.equal(
    (html.match(/class="administration-subsection"/g) || []).length,
    27,
  );
  for (const label of [
    "Provider, account, MTU, VLAN, and fixed-IP configuration",
    "Analog socket configuration",
    "Wi-Fi environment scan",
    "NAS shares and folders",
    "Restore local configuration backup",
    "Email notifications and event selection",
    "Front-panel display and key actions",
    "Read-only router capability inventory",
  ]) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /No local router control/);
  assert.match(html, /Read-only until safely verified/);
  assert.match(
    html,
    /safe local write and readback flow has not yet been verified/,
  );
  assert.match(html, /Recovery-critical candidate/);
  assert.ok(
    featureCards.every(
      (card) => !card.includes("<button") && !card.includes("data-control"),
    ),
  );
});

test("Administration renders integration polling and endpoint health cards", () => {
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

  const html = fixture.panel._renderAdministration(
    router("entry-a", entities),
    [],
    entities,
    {},
  );

  assert.match(html, /sensor\.speedport_fast_polling_health/);
  assert.match(html, /sensor\.speedport_endpoint_failures/);
  assert.match(html, /Fast polling health/);
  assert.match(html, /Endpoint failures/);
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

test("Dashboard keeps every report while Administration mirrors reviewed groups", () => {
  const fixture = panelFixture();
  fixture.panel._metadata = {
    routers: [router("entry-a", [REPORTING_META, CONFIG_META, CONTROL_META])],
  };
  fixture.panel._hass.states = {
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
  assert.match(fixture.panel.shadowRoot.innerHTML, /sensor\.speedport_system_cpu/);
  assert.match(
    fixture.panel.shadowRoot.innerHTML,
    /sensor\.speedport_wifi_schedule_mode/,
  );
  assert.doesNotMatch(
    fixture.panel.shadowRoot.innerHTML,
    /button\.speedport_reboot_router|Cached laptop/,
  );

  fixture.panel._activeView = "administration";
  SpeedportSmartPanel.prototype._render.call(fixture.panel);
  assert.match(
    fixture.panel.shadowRoot.innerHTML,
    /button\.speedport_reboot_router/,
  );
  assert.match(fixture.panel.shadowRoot.innerHTML, /Cached laptop/);
  assert.match(
    fixture.panel.shadowRoot.innerHTML,
    /sensor\.speedport_wifi_schedule_mode/,
  );
  assert.match(fixture.panel.shadowRoot.innerHTML, /sensor\.speedport_system_cpu/);
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
    normalizeAdminReadPayload({ ...payload, schema_version: 2 }, "entry-a"),
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
  fixture.panel._hass.connection.sendMessagePromise = () =>
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
  fixture.panel._hass.connection.sendMessagePromise = async () => {
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
        source: "protected_json",
        truncated: id === "clients",
      })),
    ),
    "entry-a",
  );

  const html = fixture.panel._renderAdministration(
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

  assert.equal(
    (html.match(/class="admin-read-section /g) || []).length,
    ADMIN_READ_SECTION_ORDER.length,
  );
  for (const id of [
    "admin-area:internet",
    "admin-area:telephony",
    "admin-area:network",
  ]) {
    assert.match(html, new RegExp(`data-detail-id="${id}"`));
  }
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

  let html = fixture.panel._renderAdministration(
    natRouter,
    [],
    [],
    { protected_json: { available: true } },
  );
  assert.match(html, /Port forwarding rules/);
  assert.match(html, /Not present in the cached snapshot/);
  assert.match(html, /Network devices|Mesh nodes|VPN peers/);

  html = fixture.panel._renderAdministration(
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
  html = fixture.panel._renderAdministration(
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

  const html = fixture.panel._renderAdministration(
    router("entry-a", []),
    [],
    [],
    { protected_json: { available: true } },
  );
  const card = [...html.matchAll(/<article class="admin-feature-card ([^"]*)"[\s\S]*?<\/article>/g)]
    .find((match) => match[0].includes("Connected-device inventory and addressing"));

  assert.ok(card);
  assert.match(card[1], /status-temporarily_unavailable/);
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

  const html = fixture.panel._renderAdministration(
    router("entry-a", [normalControl, lockoutControl]),
    [normalControl, lockoutControl],
    [],
    {},
  );

  assert.match(html, /class="admin-risk-badge risk-normal"/);
  assert.match(html, /class="admin-risk-badge risk-lockout"/);
  assert.match(html, /aria-label="Risk: Lockout">Lockout/);
  assert.match(html, /aria-label="Highest risk: Lockout">Lockout/);
  assert.doesNotMatch(html, /Destructive/);
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
  assert.equal(ADMIN_READ_SECTION_ORDER.length, 23);
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
        item.section_id: list(item.fields)
        for item in (*module._COLLECTIONS, *module._RECORDS)
    },
}))
`;
  const result = spawnSync(python, ["-c", script, modulePath], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const backend = JSON.parse(result.stdout);
  assert.equal(backend.schema_version, 1);
  assert.deepEqual(Object.keys(backend.sections), ADMIN_READ_SECTION_ORDER);
  assert.deepEqual(backend.sections, ADMIN_READ_SECTION_FIELDS);
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
  assert.match(source, /data-detail-id="admin-area:/);
  assert.match(source, /data-detail-id="admin-subsection:/);
  assert.match(source, /color-mix\(in srgb, var\(--sp-warning\)/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\)/);
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\./);
});
