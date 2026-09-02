import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

class Host {
  constructor(owner, key) { this.owner = owner; this.key = key; this.innerHTML = ""; this.listeners = new Map(); }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  removeEventListener(name, handler) { if (this.listeners.get(name) === handler) this.listeners.delete(name); }
  querySelectorAll() { return []; }
  contains() { return true; }
  scrollIntoView() {}
  replaceWith(host) { this.owner.hosts.set(this.key, host); }
}
class Shadow {
  constructor() { this.hosts = new Map(); this.activeElement = undefined; }
  set innerHTML(value) {
    this.html = value; this.hosts.clear();
    for (const key of ["settings", "maintenance", "call-history", "file-transfer"]) {
      if (value.includes(`data-${key}-editor-host`)) this.hosts.set(key, new Host(this, key));
    }
  }
  get innerHTML() { return this.html; }
  querySelector(selector) {
    if (selector === "[data-settings-editor-host]") return this.hosts.get("settings");
    if (selector === "[data-maintenance-editor-host]") return this.hosts.get("maintenance");
    if (selector === "[data-call-history-editor-host]") return this.hosts.get("call-history");
    if (selector === "[data-file-transfer-editor-host]") return this.hosts.get("file-transfer");
    return undefined;
  }
  querySelectorAll() { return []; }
  addEventListener() {}
}
class TestElement {
  attachShadow() { this.shadowRoot = new Shadow(); return this.shadowRoot; }
  dispatchEvent() {}
  toggleAttribute() {}
}
globalThis.HTMLElement = TestElement;
globalThis.customElements = {define() {}, get() { return undefined; }};
const {ADMIN_IA, SETTINGS_FEATURE_LINKS, SpeedportSmartPanel} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=settings"
);

const SETTING = {
  id: "telephony_hd_voice", title: "HD Voice", section: "Telephony",
  supported: true, available: true, controls_enabled: true, confirmation: "SAVE SETTINGS",
  warning: "Changing this may interrupt calls.", live_write_verified: false,
  fields: [{name: "hdvoice", label: "HD Voice", kind: "boolean"},
    {name: "password", label: "Password", kind: "secret", minimum: 8, maximum: 32}],
};
const MAINTENANCE = {
  id: "system_factory_reset", title: "Factory reset", supported: true, available: true,
  execution_policy: "maintenance", confirmation: "typed", typed_confirmation: "FACTORY RESET ROUTER",
  warning: "All settings will be lost.", inputs: [], readback_policy: "reconnect_required",
};
function fixture() {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._metadata = {routers: [{entry_id: "entry-a", entry_state: "loaded", title: "Router",
    settings: [SETTING], admin_actions: [MAINTENANCE], entities: [], capabilities: [], capability_families: [],
    access_sources: [], management: {controls_available: true, state: "available"}}]};
  panel._selectedEntry = "entry-a"; panel._activeView = "administration";
  panel._hass = {user: {id: "admin", is_admin: true}, language: "en", states: {},
    locale: {language: "en-US"}, fetchWithAuth: async (path, options) => {
      assert.equal(path, "/api/speedport_smart/private/entry-a");
      assert.equal(options.method, "POST");
      const message = JSON.parse(options.body);
      calls.push(structuredClone(message));
      return new Response(JSON.stringify({result: {
        setting_id: SETTING.id, revision: "revision", values: {hdvoice: true}, expires_in: 120,
      }}), {headers: {"content-type": "application/json"}});
    }};
  panel._renderAdministration = (router) => panel._renderSettingsCatalog(router);
  panel._render();
  return {panel, calls};
}
function click(panel, dataset) { panel._handleClick({target: {closest: () => ({dataset})}}); }

test("every editor feature link names a real administration feature", () => {
  const features = new Set(ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features).map((feature) => feature.id));
  for (const [id, link] of Object.entries(SETTINGS_FEATURE_LINKS)) {
    assert.ok(features.has(id), `missing catalog feature ${id}`);
    assert.equal(typeof link.complete, "boolean");
    assert.ok(link.ids.length > 0);
    assert.equal(new Set(link.ids).size, link.ids.length);
  }
});

test("catalog and feature buttons open the same editor without router requests", () => {
  const {panel, calls} = fixture();
  assert.match(panel.shadowRoot.innerHTML, /data-open-setting="telephony_hd_voice"/);
  assert.deepEqual(panel._settingsForFeature("telephony_hd_voice"), [SETTING]);
  click(panel, {openSetting: SETTING.id});
  assert.equal(panel._settingsEditor.snapshot().setting.id, SETTING.id);
  assert.match(panel._settingsHost.innerHTML, /HD Voice/);
  assert.equal(calls.length, 0);
});

test("unsupported unavailable and nonadministrator editor clicks cannot open", () => {
  for (const conditions of [{supported: false}, {available: false}, {admin: false}]) {
    const {panel, calls} = fixture();
    panel._metadata.routers[0].settings = [{...SETTING, ...conditions}];
    if (conditions.admin === false) panel._hass.user.is_admin = false;
    click(panel, {openSetting: SETTING.id});
    assert.equal(panel._settingsEditor.snapshot(), null);
    assert.equal(calls.length, 0);
  }
});

test("metadata catalog escapes text, has disabled capabilities, exposes no private values", () => {
  const {panel} = fixture();
  const router = {...panel._currentRouter(), settings: [{...SETTING, title: '<img src=x>', available: false}]};
  const html = panel._renderSettingsCatalog(router);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img src=x&gt;/);
  assert.match(html, /data-open-setting="telephony_hd_voice" disabled/);
  panel._hass.user.is_admin = false;
  assert.equal(panel._renderSettingsCatalog(router), "");
  assert.deepEqual(panel._settingsForFeature("telephony_hd_voice"), []);
});

test("WAN telemetry rerender preserves editor host, listeners and private drafts", async () => {
  const {panel, calls} = fixture();
  click(panel, {openSetting: SETTING.id});
  await panel._settingsEditor.load();
  panel._settingsEditor.setValue("password", "SYNTHETIC-SECRET");
  panel._settingsEditor.setValue("hdvoice", false);
  panel._settingsEditor.setConfirmation("SAVE SETTINGS");
  const host = panel._settingsHost;
  const content = host.innerHTML;
  const listeners = [...host.listeners.entries()];
  panel._hass.states = {"sensor.wan": {state: "5"}};
  panel._render();
  assert.equal(panel._settingsHost, host);
  assert.equal(panel.shadowRoot.querySelector("[data-settings-editor-host]"), host);
  assert.equal(host.innerHTML, content);
  assert.deepEqual([...host.listeners.entries()], listeners);
  assert.equal(panel._settingsEditor.snapshot().confirmationReady, true);
  assert.deepEqual(panel._settingsEditor.snapshot().dirty.sort(), ["hdvoice", "password"]);
  assert.doesNotMatch(JSON.stringify(panel._settingsEditor.snapshot()), /SYNTHETIC-SECRET/);
  assert.equal(calls.length, 1);
});

test("navigation away from administration clears both editors and their drafts", async () => {
  const {panel} = fixture();
  click(panel, {openSetting: SETTING.id}); await panel._settingsEditor.load();
  panel._settingsEditor.setValue("password", "SYNTHETIC-SECRET");
  click(panel, {openMaintenance: MAINTENANCE.id});
  assert.equal(panel._maintenanceEditor.snapshot().action.id, MAINTENANCE.id);
  const host = panel._settingsHost;
  panel._selectView("dashboard");
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.equal(panel._maintenanceEditor.snapshot(), null);
  assert.equal(host.innerHTML, ""); assert.equal(host.listeners.size, 0);
});

test("maintenance buttons open a warning without executing anything", () => {
  const {panel, calls} = fixture();
  click(panel, {openMaintenance: MAINTENANCE.id});
  assert.equal(panel._maintenanceEditor.snapshot().action.id, MAINTENANCE.id);
  assert.match(panel._maintenanceHost.innerHTML, /All settings will be lost/);
  assert.match(panel._maintenanceHost.innerHTML, /FACTORY RESET ROUTER/);
  assert.equal(calls.length, 0);
});

test("frontend deployment assets include both imported editor modules", () => {
  const panelSource = readFileSync(new URL("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js", import.meta.url), "utf8");
  const backendSource = readFileSync(new URL("../../custom_components/speedport_smart/panel.py", import.meta.url), "utf8");
  assert.match(backendSource, /StaticPathConfig\([\s\S]*?str\(_FRONTEND_DIR\)/);
  const version = backendSource.match(/PANEL_SCHEMA_VERSION: Final = (\d+)/)[1];
  for (const filename of ["configuration-editor.js", "maintenance-editor.js", "call-history-view.js", "private-api.js"]) {
    assert.ok(panelSource.includes(filename));
    assert.ok(panelSource.includes(`${filename}?schema=${version}`), `${filename} missing asset revision`);
    assert.ok(readFileSync(new URL(`../../custom_components/speedport_smart/frontend/${filename}`, import.meta.url), "utf8").length > 0);
  }
});

test("call history opens without a read and remains private across telemetry refreshes", async () => {
  const {panel, calls} = fixture();
  click(panel, {openCallHistory: "true"});
  assert.equal(panel._callHistoryView.snapshot().category, "taken");
  assert.equal(calls.length, 0);
  panel._hass.fetchWithAuth = async (path, options) => {
    assert.equal(path, "/api/speedport_smart/private/entry-a");
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify({result: {schema_version: 1, query: "call_history", result: {
      category: "taken", total: 1, entries: [{date: "2026-09-02", time: "12:30",
        remote_party: "SYNTHETIC-CALLER", local_party: "Line 1", duration_seconds: 90}],
    }}}), {headers: {"content-type": "application/json"}});
  };
  await panel._callHistoryView.load();
  assert.equal(panel._callHistoryView.snapshot().status, "loaded");
  const host = panel._callHistoryHost;
  assert.match(host.innerHTML, /SYNTHETIC-CALLER/);
  assert.doesNotMatch(JSON.stringify(panel._callHistoryView.snapshot()), /SYNTHETIC-CALLER/);
  panel._render();
  assert.equal(panel.shadowRoot.querySelector("[data-call-history-editor-host]"), host);
  assert.equal(calls.length, 1);
  panel._selectView("dashboard");
  assert.equal(panel._callHistoryView.snapshot(), null);
  assert.deepEqual(panel._callHistoryView.entries(), []);
  assert.equal(host.innerHTML, "");
  assert.equal(host.listeners.size, 0);
});

test("call history cannot open for nonadministrators or an unloaded entry", () => {
  for (const unavailable of ["permission", "entry", "view"]) {
    const {panel, calls} = fixture();
    if (unavailable === "permission") panel._hass.user.is_admin = false;
    if (unavailable === "entry") panel._metadata.routers[0].entry_state = "not_loaded";
    if (unavailable === "view") panel._activeView = "dashboard";
    click(panel, {openCallHistory: "true"});
    assert.equal(panel._callHistoryView.snapshot(), null);
    assert.equal(calls.length, 0);
  }
});
