import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  captureRenderState,
  restoreDetailsState,
  restoreFocusState,
} from "../../custom_components/speedport_smart/frontend/render-state.js";

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

const { SpeedportSmartPanel } = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=completion-contract"
);

const REPORTING_META = Object.freeze({
  access_source: "protected_json",
  confirmation: "none",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_runtime_metric",
  risk: "normal",
  section: "system",
  translation_key: "runtime_metric",
});
const WIFI_CONTROL_META = Object.freeze({
  access_source: "router_control",
  confirmation: "typed",
  control: true,
  control_supported: true,
  disruptive: true,
  domain: "switch",
  entity_id: "switch.speedport_wifi",
  management_feature: "network_wifi_main",
  risk: "lockout",
  section: "controls",
  translation_key: "wifi",
});

function router(overrides = {}) {
  return {
    access_sources: [],
    capabilities: ["authenticated_json", "wifi"],
    capability_families: [],
    entities: [REPORTING_META, WIFI_CONTROL_META],
    entry_id: "entry-a",
    entry_state: "loaded",
    firmware: "Firmware-A-Unique",
    hardware_version: "Hardware-A-Unique",
    management: { controls_available: true, state: "available" },
    model: "Model-A-Unique",
    title: "Router-A-Unique",
    ...overrides,
  };
}

function panelFixture(routerData = router()) {
  const panel = new SpeedportSmartPanel();
  panel._metadata = { routers: [routerData], schema_version: 23 };
  panel._selectedEntry = routerData.entry_id;
  panel._platformIcons = {};
  panel._componentIcons = {};
  panel._hass = {
    entities: {},
    language: "en",
    locale: { language: "en-US" },
    states: {
      [REPORTING_META.entity_id]: {
        attributes: { friendly_name: "Runtime metric" },
        state: "Metric-A-Unique",
      },
      [WIFI_CONTROL_META.entity_id]: {
        attributes: { friendly_name: "Wi-Fi" },
        state: "on",
      },
    },
    user: { is_admin: true },
  };
  return panel;
}

function renderedMarkup(panel) {
  SpeedportSmartPanel.prototype._render.call(panel);
  return panel.shadowRoot.innerHTML.split("</style>").at(-1);
}

function exactCount(value, fragment) {
  return value.split(fragment).length - 1;
}

function viewButton(value, view) {
  const match = value.match(
    new RegExp(
      `<button\\s+data-view="${view}"(?:(?!<\\/button>)[\\s\\S])*?<\\/button>`,
    ),
  );
  assert.ok(match, `missing ${view} view button`);
  return match[0];
}

function focusable() {
  return {
    focusCount: 0,
    focus() {
      this.focusCount += 1;
    },
  };
}

function detail(id, open, summary = focusable()) {
  return {
    dataset: { detailId: id },
    open,
    querySelector(selector) {
      return selector === "summary" ? summary : undefined;
    },
  };
}

function detailsRoot(details, activeElement = undefined) {
  return {
    activeElement,
    querySelectorAll(selector) {
      return selector === "details" ? details : [];
    },
  };
}

test("eligible router renders exactly two mutually exclusive panel views", () => {
  const panel = panelFixture();

  const dashboard = renderedMarkup(panel);
  assert.equal(exactCount(dashboard, 'data-view="dashboard"'), 1);
  assert.equal(exactCount(dashboard, 'data-view="administration"'), 1);
  assert.match(viewButton(dashboard, "dashboard"), /aria-current="page"/);
  assert.doesNotMatch(
    viewButton(dashboard, "administration"),
    /aria-current="page"/,
  );
  assert.match(dashboard, /<section class="access-overview">/);
  assert.doesNotMatch(dashboard, /<div class="administration-view">/);
  assert.doesNotMatch(dashboard, /switch\.speedport_wifi/);

  panel._activeView = "administration";
  const administration = renderedMarkup(panel);
  assert.equal(exactCount(administration, 'data-view="dashboard"'), 1);
  assert.equal(exactCount(administration, 'data-view="administration"'), 1);
  assert.match(
    viewButton(administration, "administration"),
    /aria-current="page"/,
  );
  assert.doesNotMatch(
    viewButton(administration, "dashboard"),
    /aria-current="page"/,
  );
  assert.ok(administration.includes('<div class="administration-view admin-native">'));
  assert.doesNotMatch(administration, /<section class="access-overview">/);
  assert.ok(!administration.includes('data-control="switch.speedport_wifi"'));
  panel._adminTab = "network"; panel._adminPage = "network_wifi_basic";
  assert.ok(renderedMarkup(panel).includes('data-control="switch.speedport_wifi"'));
});

test("all nested administration expansion identities survive rerender and reorder", () => {
  const ids = [
    "admin-area:network",
    "admin-subsection:network_wifi",
    "admin-feature:network_wifi_main",
    "admin-read:wifi_2_4_identity",
  ];
  const oldDetails = ids.map((id, index) => detail(id, index % 2 === 0));
  const focusedSummary = oldDetails[2].querySelector("summary");
  const state = captureRenderState(detailsRoot(oldDetails, focusedSummary));
  const newDetail = detail("admin-feature:new_feature", true);
  const restored = [newDetail, ...ids.toReversed().map((id) => detail(id, false))];
  const root = detailsRoot(restored);

  restoreDetailsState(root, state);

  assert.equal(newDetail.open, true, "new identities keep rendered defaults");
  for (const [index, id] of ids.entries()) {
    assert.equal(
      restored.find((item) => item.dataset.detailId === id).open,
      index % 2 === 0,
      id,
    );
  }
  assert.equal(restoreFocusState(root, state), true);
  assert.equal(
    restored
      .find(
        (item) =>
          item.dataset.detailId === "admin-feature:network_wifi_main",
      )
      .querySelector("summary").focusCount,
    1,
  );
});

test("panel layout locks full-width breakpoints and Home Assistant theme inheritance", async () => {
  const source = await readFile(
    new URL(
      "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js",
      import.meta.url,
    ),
    "utf8",
  );

  for (const variable of [
    ["--sp-surface", "--ha-card-background"],
    ["--sp-surface-soft", "--secondary-background-color"],
    ["--sp-text", "--primary-text-color"],
    ["--sp-muted", "--secondary-text-color"],
    ["--sp-border", "--divider-color"],
    ["--sp-success", "--success-color"],
    ["--sp-warning", "--warning-color"],
    ["--sp-error", "--error-color"],
  ]) {
    assert.match(
      source,
      new RegExp(`${variable[0]}:\\s*var\\(${variable[1].replace("--", "\\-\\-")}`),
      variable.join(" uses "),
    );
  }
  assert.match(source, /var\(--primary-background-color,/);
  assert.doesNotMatch(source, /@media\s*\(\s*prefers-color-scheme/);
  assert.match(source, /\*\s*\{\s*box-sizing:\s*border-box;/);

  for (const selector of [
    "\\.shell",
    "\\.administration-view",
    "\\.administration-intro,\\s*\\n\\s*\\.admin-read-overview",
    "\\.administration-areas",
    "\\.admin-feature-catalog",
  ]) {
    assert.match(
      source,
      new RegExp(`${selector}\\s*\\{[^}]*width:\\s*100%`, "s"),
      `${selector} fills its container`,
    );
  }

  assert.match(
    source,
    /\.source-grid\s*\{[^}]*grid-template-columns:\s*repeat\(4,/s,
  );
  assert.match(
    source,
    /\.admin-read-sections\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s,
  );
  assert.match(
    source,
    /\.administration-subsections\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s,
  );
  assert.match(
    source,
    /@media \(max-width: 900px\)[\s\S]*?\.source-grid\s*\{[^}]*repeat\(2,[^}]*\}[\s\S]*?\.admin-read-sections,[\s\S]*?\.administration-subsections\s*\{[^}]*grid-template-columns:\s*1fr;/,
  );
  assert.match(
    source,
    /@media \(max-width: 430px\)[\s\S]*?\.source-grid\s*\{[^}]*grid-template-columns:\s*1fr;[\s\S]*?\.entity-grid\s*\{[^}]*grid-template-columns:\s*1fr;[\s\S]*?\.child-device-grid\s*\{[^}]*grid-template-columns:\s*1fr;/,
  );
});

test("router identity and telemetry are rendered only from current runtime data", () => {
  const panel = panelFixture();
  const first = renderedMarkup(panel);
  for (const value of [
    "Router-A-Unique",
    "Model-A-Unique",
    "Firmware-A-Unique",
    "Hardware-A-Unique",
    "Metric-A-Unique",
  ]) {
    assert.match(first, new RegExp(value));
  }

  const secondRouter = router({
    firmware: "Firmware-B-Unique",
    hardware_version: "Hardware-B-Unique",
    model: "Model-B-Unique",
    title: "Router-B-Unique",
  });
  panel._metadata = { routers: [secondRouter], schema_version: 23 };
  panel._hass.states[REPORTING_META.entity_id] = {
    attributes: { friendly_name: "Runtime metric" },
    state: "Metric-B-Unique",
  };
  const second = renderedMarkup(panel);

  for (const value of [
    "Router-B-Unique",
    "Model-B-Unique",
    "Firmware-B-Unique",
    "Hardware-B-Unique",
    "Metric-B-Unique",
  ]) {
    assert.match(second, new RegExp(value));
  }
  for (const staleValue of [
    "Router-A-Unique",
    "Model-A-Unique",
    "Firmware-A-Unique",
    "Hardware-A-Unique",
    "Metric-A-Unique",
  ]) {
    assert.doesNotMatch(second, new RegExp(staleValue));
  }
});

test("control stays singular and recovers in place across session loss", () => {
  const panel = panelFixture();
  panel._activeView = "administration";
  panel._adminTab = "network"; panel._adminPage = "network_wifi_basic";

  const available = renderedMarkup(panel);
  assert.equal(
    exactCount(available, `data-more-info="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.equal(
    exactCount(available, `data-control="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.doesNotMatch(
    available,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*aria-disabled="true"`),
  );
  assert.match(
    available,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*aria-disabled="false"`),
  );

  const blockedRouter = router({
    management: { controls_available: false, state: "blocked" },
  });
  panel._metadata = { routers: [blockedRouter], schema_version: 23 };
  const blocked = renderedMarkup(panel);
  assert.equal(
    exactCount(blocked, `data-more-info="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.equal(
    exactCount(blocked, `data-control="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.match(
    blocked,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*aria-disabled="true"`),
  );
  assert.match(
    blocked,
    new RegExp(
      `class="[^"]*is-unavailable[^"]*"[^>]*data-control="${WIFI_CONTROL_META.entity_id}"`,
    ),
  );
  assert.doesNotMatch(
    blocked,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*\\sdisabled(?:\\s|>|=)`),
  );

  panel._metadata = { routers: [router()], schema_version: 23 };
  const recovered = renderedMarkup(panel);
  assert.equal(
    exactCount(recovered, `data-more-info="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.equal(
    exactCount(recovered, `data-control="${WIFI_CONTROL_META.entity_id}"`),
    1,
  );
  assert.doesNotMatch(
    recovered,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*aria-disabled="true"`),
  );
  assert.match(
    recovered,
    new RegExp(`data-control="${WIFI_CONTROL_META.entity_id}"[^>]*aria-disabled="false"`),
  );
});
