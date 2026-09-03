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
    for (const match of value.matchAll(/data-settings-section="([a-z0-9_]+)"/g)) {
      this.hosts.set(`section:${match[1]}`, new Host(this, `section:${match[1]}`));
    }
  }
  get innerHTML() { return this.html; }
  querySelector(selector) {
    const section = selector.match(/^\[data-settings-section="([a-z0-9_]+)"\]$/);
    if (section) return this.hosts.get(`section:${section[1]}`);
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
function fixture({native = false, settings = [SETTING], fetchResult} = {}) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._privateReadWait = async () => {};
  panel._scheduleRender = () => {};
  panel._metadata = {routers: [{entry_id: "entry-a", entry_state: "loaded", title: "Router",
    settings, admin_actions: [MAINTENANCE], entities: [], capabilities: [], capability_families: [],
    access_sources: [], management: {controls_available: true, state: "available"}}]};
  panel._selectedEntry = "entry-a"; panel._activeView = "administration";
  panel._hass = {user: {id: "admin", is_admin: true}, language: "en", states: {},
    locale: {language: "en-US"}, fetchWithAuth: async (path, options) => {
      assert.equal(path, "/api/speedport_smart/private/entry-a");
      assert.equal(options.method, "POST");
      const message = JSON.parse(options.body);
      calls.push(structuredClone(message));
      if (fetchResult) return fetchResult(message);
      if (message.type.endsWith("/admin_read")) return new Response(JSON.stringify({result: {
        entry_id: message.entry_id, schema_version: 2, sections: [],
      }}), {headers: {"content-type": "application/json"}});
      return new Response(JSON.stringify({result: {
        setting_id: message.setting_id, revision: "revision", values: {hdvoice: true}, expires_in: 120,
      }}), {headers: {"content-type": "application/json"}});
    }};
  if (!native) panel._renderAdministration = (router) => panel._renderSettingsCatalog(router);
  panel._render();
  return {panel, calls};
}
function click(panel, dataset) { return panel._handleClick({target: {closest: () => ({dataset})}}); }

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

test("page setting selection automatically reads current settings without a write", async () => {
  const {panel, calls} = fixture();
  assert.match(panel.shadowRoot.innerHTML, /data-open-setting="telephony_hd_voice"/);
  assert.deepEqual(panel._settingsForFeature("telephony_hd_voice"), [SETTING]);
  await click(panel, {openSetting: SETTING.id});
  assert.equal(panel._settingsEditor.snapshot().setting.id, SETTING.id);
  assert.match(panel._settingsHost.innerHTML, /HD Voice/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].type, "speedport_smart/panel/settings/read");
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
  await click(panel, {openSetting: SETTING.id});
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
  await click(panel, {openSetting: SETTING.id});
  panel._settingsEditor.setValue("password", "SYNTHETIC-SECRET");
  const host = panel._settingsHost;
  click(panel, {openMaintenance: MAINTENANCE.id});
  assert.equal(panel._maintenanceEditor.snapshot().action.id, MAINTENANCE.id);
  assert.equal(panel._settingsEditor.snapshot(), null);
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

test("native navigation loads only selected page and does not repeat reads on telemetry renders", async () => {
  const {panel, calls} = fixture({native: true});
  assert.ok(panel.shadowRoot.innerHTML.includes('data-admin-tab="network"'));
  assert.ok(!panel.shadowRoot.innerHTML.includes('data-open-setting="telephony_hd_voice"'));
  await panel._selectAdminPage("telephony", "telephony_number_hd_voice");
  assert.equal(panel._settingsEditor.snapshot().setting.id, SETTING.id);
  assert.equal(calls.length, 1);
  assert.ok(panel.shadowRoot.innerHTML.includes('data-native-page="telephony_number_hd_voice"'));
  assert.ok(!panel.shadowRoot.innerHTML.includes("Configuration editors"));
  panel._render(); panel._render();
  assert.equal(calls.length, 1);
  assert.ok(calls.every((call) => call.type.endsWith("/read")));
});

test("cancelled page navigation preserves unsaved private drafts without reading", async () => {
  const {panel, calls} = fixture({native: true});
  await panel._selectAdminPage("telephony", "telephony_number_hd_voice");
  panel._settingsEditor.setValue("hdvoice", false);
  panel._settingsEditor.setValue("password", "SYNTHETIC-SECRET");
  const previous = globalThis.confirm;
  globalThis.confirm = () => false;
  try {
    await panel._selectAdminPage("network", "network_wifi_basic");
    assert.equal(panel._currentAdminPage().page.id, "telephony_number_hd_voice");
    assert.equal(panel._settingsEditor.snapshot().isDirty, true);
    assert.equal(calls.length, 1);
  } finally { globalThis.confirm = previous; }
});

test("confirmed native navigation disposes private hosts and old drafts", async () => {
  const {panel} = fixture({native: true});
  await panel._selectAdminPage("telephony", "telephony_number_hd_voice");
  panel._settingsEditor.setValue("password", "SYNTHETIC-SECRET");
  const host = panel._settingsHost;
  const previous = globalThis.confirm;
  globalThis.confirm = () => true;
  try {
    await panel._selectAdminPage("network", "network_wifi_basic");
    assert.equal(panel._settingsEditor.snapshot(), null);
    assert.equal(host.innerHTML, "");
    assert.equal(host.listeners.size, 0);
    assert.ok(!panel.shadowRoot.innerHTML.includes("SYNTHETIC-SECRET"));
  } finally { globalThis.confirm = previous; }
});

test("an in-flight setting write blocks page and destructive-editor replacement", async () => {
  const {panel, calls} = fixture({native: true});
  await panel._selectAdminPage("telephony", "telephony_number_hd_voice");
  panel._settingsEditor.setValue("hdvoice", false);
  panel._settingsEditor.setConfirmation("SAVE SETTINGS");
  let resolve;
  panel._hass.fetchWithAuth = async (_path, options) => {
    calls.push(JSON.parse(options.body));
    return new Promise((done) => { resolve = done; });
  };
  const saving = panel._settingsEditor.save();
  await Promise.resolve();
  await panel._selectAdminPage("system", "system_recovery");
  click(panel, {openMaintenance: MAINTENANCE.id});
  assert.equal(panel._currentAdminPage().page.id, "telephony_number_hd_voice");
  assert.equal(panel._settingsEditor.snapshot().isSaving, true);
  assert.equal(panel._maintenanceEditor.snapshot(), null);
  resolve(new Response(JSON.stringify({result: {status: "verified"}}), {headers: {"content-type": "application/json"}}));
  await saving;
  assert.equal(calls.length, 2);
});

test("serialized private reads discard stale queued page requests before sending", async () => {
  const {panel, calls} = fixture({native: true});
  let release;
  panel._hass.fetchWithAuth = async (_path, options) => {
    calls.push(JSON.parse(options.body));
    if (calls.length === 1) await new Promise((resolve) => { release = resolve; });
    return new Response(JSON.stringify({result: {}}), {headers: {"content-type": "application/json"}});
  };
  const one = panel._requestPrivate({type: "speedport_smart/panel/settings/read", entry_id: "entry-a", setting_id: SETTING.id});
  await Promise.resolve();
  const two = panel._requestPrivate({type: "speedport_smart/panel/settings/read", entry_id: "entry-a", setting_id: SETTING.id});
  const rejected = assert.rejects(two, /administrator_required/);
  await panel._selectAdminPage("network", "network_wifi_basic");
  release(); await one; await rejected;
  assert.equal(calls.length, 1);
  assert.equal(await panel._privateRequestQueue, undefined);
});

test("late global administrator cache cannot restart selected page auto-loading", async () => {
  const {panel, calls} = fixture({native: true});
  panel._activeView = "dashboard";
  let release;
  panel._loadAdminRead = () => new Promise((resolve) => { release = resolve; });
  panel._selectView("administration");
  await panel._selectAdminPage("telephony", "telephony_number_hd_voice");
  const epoch = panel._adminPageEpoch;
  release(); await Promise.resolve(); await Promise.resolve();
  assert.equal(panel._adminPageEpoch, epoch);
  assert.equal(calls.length, 1);
  assert.equal(panel._settingsEditor.snapshot().loaded, true);
});

const ENERGY_SETTINGS = ["system_led_schedule", "system_energy"].map((id) => ({...SETTING, id, title: id}));
function privateResponse(result) {
  return new Response(JSON.stringify({result}), {headers: {"content-type": "application/json"}});
}
function sectionResponse(message) {
  return privateResponse({setting_id: message.setting_id, target_id: message.target_id,
    revision: `revision-${message.setting_id}`, values: {hdvoice: true}, expires_in: 120});
}
async function microtasksUntil(predicate) {
  for (let index = 0; index < 150 && !predicate(); index++) await Promise.resolve();
  assert.ok(predicate(), "expected bounded asynchronous state transition");
}

test("native page automatically loads every inline section once with no setting launchers", async () => {
  const {panel, calls} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: sectionResponse});
  await panel._selectAdminPage("system", "system_energy");
  assert.deepEqual(calls.map((call) => call.setting_id), ENERGY_SETTINGS.map((setting) => setting.id));
  assert.equal(panel._settingsEditors.size, 2);
  for (const setting of ENERGY_SETTINGS) {
    const record = panel._settingsEditors.get(setting.id);
    assert.equal(record.editor.snapshot().loaded, true);
    assert.match(record.host.innerHTML, /data-setting-action="save"/);
    assert.ok(panel.shadowRoot.innerHTML.includes(`data-settings-section="${setting.id}"`));
  }
  assert.equal(/<nav class="admin-form-nav"|data-open-setting=|data-load-admin-page/.test(panel.shadowRoot.innerHTML), false);
  await panel._selectAdminPage("system", "system_energy");
  await panel._loadAdminPage(); panel._render();
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call.type.endsWith("/read")));
});

test("each inline host, binding, private draft and confirmation survives sibling and WAN rendering", async () => {
  const {panel, calls} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: sectionResponse});
  await panel._selectAdminPage("system", "system_energy");
  const records = [...panel._settingsEditors.values()];
  const hosts = records.map((record) => record.host);
  const listeners = hosts.map((host) => [...host.listeners]);
  for (const record of records) {
    record.editor.setValue("hdvoice", false);
    record.editor.setValue("password", "SYNTHETIC-PRIVATE");
    record.editor.setConfirmation("SAVE SETTINGS");
  }
  panel._hass.states = {"sensor.wan": {state: "30"}};
  panel._render();
  for (let index = 0; index < records.length; index++) {
    const {editor, host} = records[index];
    assert.equal(host, hosts[index]);
    assert.equal(panel.shadowRoot.querySelector(`[data-settings-section="${editor.snapshot().setting.id}"]`), host);
    assert.deepEqual([...host.listeners], listeners[index]);
    assert.equal(editor.snapshot().confirmationReady, true);
    assert.deepEqual(editor.snapshot().dirty.sort(), ["hdvoice", "password"]);
  }
  records[0].editor.cancelChanges();
  assert.equal(records[1].editor.snapshot().confirmationReady, true);
  assert.deepEqual(records[1].editor.snapshot().dirty.sort(), ["hdvoice", "password"]);
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /SYNTHETIC-PRIVATE/);
  assert.equal(calls.length, 2);
});

test("multi-section navigation checks secondary dirty drafts and disposes all sections only after confirmation", async () => {
  const {panel, calls} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: sectionResponse});
  await panel._selectAdminPage("system", "system_energy");
  const records = [...panel._settingsEditors.values()];
  records[1].editor.setValue("password", "SYNTHETIC-PRIVATE");
  const before = globalThis.confirm;
  try {
    globalThis.confirm = () => false;
    await panel._selectAdminPage("network", "network_wifi_environment");
    assert.equal(panel._currentAdminPage().page.id, "system_energy");
    assert.equal(panel._settingsEditors.size, 2);
    globalThis.confirm = () => true;
    await panel._selectAdminPage("network", "network_wifi_environment");
    assert.equal(panel._settingsEditors.size, 0);
    for (const record of records) {
      assert.equal(record.editor.snapshot(), null);
      assert.equal(record.host.innerHTML, "");
      assert.equal(record.host.listeners.size, 0);
    }
    assert.equal(calls.length, 2);
  } finally {globalThis.confirm = before;}
});

test("finite multi-section reads are paced after completion and duplicate opens share the current job", async () => {
  let now = 0;
  const sent = [];
  const {panel} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: (message) => {
    sent.push({id: message.setting_id, time: now});
    return sectionResponse(message);
  }});
  panel._privateReadNow = () => now;
  const waits = [];
  panel._privateReadWait = async (delay) => {waits.push(delay); now += delay;};
  const opening = panel._selectAdminPage("system", "system_energy");
  const firstJob = panel._loadAdminPage();
  assert.equal(panel._loadAdminPage(), firstJob);
  await opening; await firstJob;
  assert.deepEqual(sent.map((item) => item.time), [0, 1000]);
  assert.deepEqual(waits, [1000]);
});

for (const change of ["page", "permission", "detach"]) {
  test(`${change} change cancels a paced section read before transport`, async () => {
    const {panel, calls} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: sectionResponse});
    let release;
    const wait = new Promise((resolve) => {release = resolve;});
    let waiting = false;
    panel._privateReadWait = () => {waiting = true; return wait;};
    const opening = panel._selectAdminPage("system", "system_energy");
    await microtasksUntil(() => waiting);
    if (change === "page") await panel._selectAdminPage("network", "network_wifi_environment");
    else if (change === "permission") panel.hass = {...panel._hass, user: {id: "admin", is_admin: false}};
    else {panel.isConnected = false; panel.disconnectedCallback();}
    release(); await opening;
    assert.equal(calls.length, 1);
    assert.equal(panel._settingsEditors.size, 0);
  });
}

test("existing target editor reads automatically while create/delete actions stay unopened", async () => {
  const settings = ["parental_profile_create", "parental_profile_edit", "parental_profile_delete"]
    .map((id) => ({...SETTING, id, requires_target: id !== "parental_profile_create"}));
  const {panel, calls} = fixture({native: true, settings, fetchResult: (message) =>
    message.type.endsWith("/targets") ? privateResponse({setting_id: message.setting_id,
      targets: [{id: "8", label: "Existing profile"}]}) : sectionResponse(message)});
  await panel._selectAdminPage("internet", "internet_parental");
  assert.deepEqual(calls.map((call) => call.type.split("/").at(-1)), ["targets", "read"]);
  assert.ok(calls.every((call) => call.setting_id === "parental_profile_edit"));
  assert.equal(calls[1].target_id, "8");
  assert.equal(panel._settingsEditors.get("parental_profile_edit").editor.snapshot().loaded, true);
  assert.match(panel.shadowRoot.innerHTML, /data-open-setting="parental_profile_create"/);
  assert.match(panel.shadowRoot.innerHTML, /data-open-setting="parental_profile_delete"/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML, /data-open-setting="parental_profile_edit"/);
});

test("one inline section failure does not prevent another section from loading", async () => {
  const settings = ENERGY_SETTINGS.map((setting, index) => index ? setting : {...setting, fields: []});
  const {panel, calls} = fixture({native: true, settings, fetchResult: sectionResponse});
  await panel._selectAdminPage("system", "system_energy");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].setting_id, "system_energy");
  assert.equal(panel._settingsEditors.get("system_energy").editor.snapshot().loaded, true);
  assert.match(panel.shadowRoot.innerHTML, /data-retry-setting="system_led_schedule"/);
});

test("saving one inline section preserves sibling drafts and cannot dispatch another concurrent write", async () => {
  let complete;
  const saved = new Promise((resolve) => {complete = resolve;});
  const {panel, calls} = fixture({native: true, settings: ENERGY_SETTINGS, fetchResult: (message) =>
    message.type.endsWith("/save") ? saved : sectionResponse(message)});
  await panel._selectAdminPage("system", "system_energy");
  const [first, second] = [...panel._settingsEditors.values()].map((record) => record.editor);
  for (const editor of [first, second]) {editor.setValue("hdvoice", false); editor.setConfirmation("SAVE SETTINGS");}
  const saving = first.save();
  await microtasksUntil(() => calls.some((call) => call.type.endsWith("/save")));
  assert.deepEqual(second.snapshot().dirty, ["hdvoice"]);
  assert.equal(second.snapshot().confirmationReady, true);
  await panel._selectAdminPage("network", "network_wifi_environment");
  assert.equal(panel._currentAdminPage().page.id, "system_energy");
  await second.save();
  assert.equal(calls.filter((call) => call.type.endsWith("/save")).length, 1);
  assert.equal(second.snapshot().status, "busy_rejected");
  assert.match(panel._settingsEditors.get("system_energy").host.innerHTML, /This change was not sent/);
  assert.equal(first.snapshot().status, "saving");
  complete(privateResponse({status: "verified"})); await saving;
  assert.equal(first.snapshot().status, "verified");
  const write = calls.find((call) => call.type.endsWith("/save"));
  assert.equal(write.setting_id, "system_led_schedule");
  assert.equal(write.revision, "revision-system_led_schedule");
  assert.deepEqual(write.changes, {hdvoice: false});
  assert.equal(calls.length, 3);
});
