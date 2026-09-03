import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

class Host {
  constructor(owner, key) { this.owner = owner; this.key = key; this.innerHTML = ""; this.listeners = new Map(); }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  removeEventListener(name, handler) { if (this.listeners.get(name) === handler) this.listeners.delete(name); }
  querySelectorAll() { return []; }
  contains() { return false; }
  scrollIntoView() {}
  replaceWith(host) { this.owner.hosts.set(this.key, host); }
}
class Shadow {
  constructor() { this.hosts = new Map(); }
  set innerHTML(value) {
    this.html = value; this.hosts.clear();
    for (const key of ["settings", "maintenance", "call-history", "file-transfer"]) {
      if (value.includes(`data-${key}-editor-host`)) this.hosts.set(key, new Host(this, key));
    }
  }
  get innerHTML() { return this.html; }
  querySelector(selector) {
    const key = selector.match(/^\[data-(settings|maintenance|call-history|file-transfer)-editor-host\]$/)?.[1];
    return key ? this.hosts.get(key) : undefined;
  }
  querySelectorAll() { return []; }
  addEventListener() {}
}
globalThis.HTMLElement = class {
  attachShadow() { this.shadowRoot = new Shadow(); return this.shadowRoot; }
  dispatchEvent() {}
  toggleAttribute() {}
};
globalThis.customElements = {define() {}, get() { return undefined; }};
const panelUrl = new URL("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js", import.meta.url);
const schema = Number(readFileSync(panelUrl, "utf8").match(/const PANEL_SCHEMA_VERSION = (\d+);/)[1]);
const {SpeedportSmartPanel} = await import(`${panelUrl}?test=native-security`);

const SETTING = {
  id: "wifi_identity", title: "Wi-Fi identity", section: "Wi-Fi",
  supported: true, available: true, controls_enabled: true, confirmation: "CHANGE WIFI",
  fields: [{name: "wlan_ssid", label: "Network name", kind: "text", minimum: 1, maximum: 32},
    {name: "wlan_wpa_key", label: "Password", kind: "secret", minimum: 8, maximum: 63}],
};
const TRANSFER = {
  id: "system_backup_restore", title: "Restore configuration", execution_policy: "file_transfer",
  supported: true, available: true, direction: "upload", confirmation: "RESTORE CONFIGURATION",
  maximum_bytes: 1024, warning: "Synthetic transfer", password: {maximum: 255},
};
const OTHER_TRANSFER = {...TRANSFER, id: "system_firmware_upload", title: "Firmware upload"};
const MAINTENANCE = {
  id: "system_factory_reset", title: "Factory reset", supported: true, available: true,
  execution_policy: "maintenance", confirmation: "typed", typed_confirmation: "FACTORY RESET ROUTER",
  warning: "Synthetic reset", inputs: [], readback_policy: "reconnect_required",
};
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return {promise, resolve};
}
function json(result) { return new Response(JSON.stringify({result}), {headers: {"content-type": "application/json"}}); }
function settingsResult(entry, value = entry === "entry-a" ? "SYNTHETIC-A" : "SYNTHETIC-B") {
  return {setting_id: SETTING.id, revision: `revision-${entry}`, values: {wlan_ssid: value}, expires_in: 120};
}
function click(panel, dataset) { return panel._handleClick({target: {closest: () => ({dataset})}}); }
async function settled(panel) {
  for (let count = 0; count < 12; count++) {
    const queue = panel._privateRequestQueue;
    await queue; await Promise.resolve(); await Promise.resolve();
    if (queue === panel._privateRequestQueue) return;
  }
  assert.fail("Private request queue did not settle");
}
function fixture() {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  const metadata = {schema_version: schema, routers: ["entry-a", "entry-b"].map(entry_id => ({
    entry_id, entry_state: "loaded", title: entry_id, settings: [SETTING],
    admin_actions: [MAINTENANCE], file_transfers: [TRANSFER, OTHER_TRANSFER], entities: [],
    capabilities: [], capability_families: [], access_sources: [],
    management: {controls_available: true, state: "available", generation: 1},
  }))};
  panel._metadata = metadata;
  panel._selectedEntry = "entry-a"; panel._activeView = "administration";
  panel._platformIcons = {}; panel._componentIcons = {};
  panel._scheduleRender = () => panel._render();
  panel._hass = {user: {id: "admin-a", is_admin: true}, language: "en", locale: {language: "en-US"}, states: {},
    connection: {sendMessagePromise: async () => metadata},
    fetchWithAuth: async (path, options) => {
      assert.equal(options.method, "POST");
      const message = JSON.parse(options.body);
      assert.equal(path, `/api/speedport_smart/private/${message.entry_id}`);
      calls.push(message);
      if (message.type.endsWith("/admin_read")) return json({entry_id: message.entry_id, schema_version: 2, sections: []});
      assert.equal(message.type, "speedport_smart/panel/settings/read");
      return json(settingsResult(message.entry_id));
    }};
  panel._render();
  return {panel, calls, metadata};
}

test("router switch clears old private host and automatically reads the same page for the new entry", async () => {
  const {panel, calls} = fixture();
  await panel._selectAdminPage("network", "network_wifi_identity");
  const previousHost = panel._settingsHost;
  assert.equal(panel._settingsEditor.snapshot().values.wlan_ssid, "SYNTHETIC-A");
  panel._selectRouter("entry-b");
  await settled(panel);
  assert.equal(panel._currentAdminPage().page.id, "network_wifi_identity");
  assert.equal(panel._settingsEditor.snapshot().entryId, "entry-b");
  assert.equal(panel._settingsEditor.snapshot().values.wlan_ssid, "SYNTHETIC-B");
  assert.equal(previousHost.innerHTML, "");
  assert.equal(previousHost.listeners.size, 0);
  assert.notEqual(panel._settingsHost, previousHost);
  assert.deepEqual(calls.map(({type, entry_id}) => [type, entry_id]), [
    ["speedport_smart/panel/settings/read", "entry-a"],
    ["speedport_smart/panel/admin_read", "entry-b"],
    ["speedport_smart/panel/settings/read", "entry-b"],
  ]);
});

for (const change of ["demotion", "unload"]) {
  test(`${change} disposes private editors and ignores a late page read`, async () => {
    const {panel, calls, metadata} = fixture();
    const entered = deferred(), response = deferred();
    panel._hass.fetchWithAuth = async (_path, options) => {
      calls.push(JSON.parse(options.body)); entered.resolve(); return response.promise;
    };
    const loading = panel._selectAdminPage("network", "network_wifi_identity");
    await entered.promise;
    const oldHost = panel._settingsHost;
    assert.equal(panel._settingsEditor.snapshot().busy, true);
    if (change === "demotion") {
      panel.hass = {...panel._hass, user: {...panel._hass.user, is_admin: false}};
    } else {
      const unloaded = {...metadata, routers: metadata.routers.map(router => ({...router, entry_state: "not_loaded"}))};
      panel._hass.connection.sendMessagePromise = async () => unloaded;
      await panel._loadMetadata();
    }
    assert.equal(panel._settingsEditor.snapshot(), null);
    assert.equal(oldHost.innerHTML, "");
    assert.equal(oldHost.listeners.size, 0);
    response.resolve(json(settingsResult("entry-a", "LATE-PRIVATE-NAME")));
    await loading; await settled(panel);
    assert.equal(panel._settingsEditor.snapshot(), null);
    assert.equal(panel._settingsHost, undefined);
    assert.doesNotMatch(panel.shadowRoot.innerHTML, /LATE-PRIVATE-NAME/);
    assert.equal(calls.length, 1);
  });
}

test("a dispatched file upload blocks replacement, maintenance, settings, and page navigation", async () => {
  const {panel, calls} = fixture();
  await panel._selectAdminPage("system", "system_backup");
  const entered = deferred(), completed = deferred();
  panel._hass.fetchWithAuth = async (path, options) => {
    calls.push({path});
    if (path.endsWith("/prepare")) {
      const data = JSON.parse(options.body);
      return new Response(JSON.stringify({action: data.action, grant: "a".repeat(48), expires_in: 120}),
        {headers: {"content-type": "application/json"}});
    }
    assert.equal(path, "/api/speedport_smart/file_transfer/entry-a/execute");
    assert.equal(await options.body.get("file").text(), "file");
    entered.resolve(); return completed.promise;
  };
  click(panel, {openTransfer: TRANSFER.id});
  panel._fileTransferEditor.setFile(new File(["file"], "synthetic-backup.bin"));
  panel._fileTransferEditor.setConfirmation(TRANSFER.confirmation);
  const uploading = panel._fileTransferEditor.execute();
  await entered.promise;
  const host = panel._fileTransferHost;
  click(panel, {openTransfer: OTHER_TRANSFER.id});
  click(panel, {openMaintenance: MAINTENANCE.id});
  await click(panel, {openSetting: SETTING.id});
  await panel._selectAdminPage("network", "network_wifi_identity");
  panel._selectRouter("entry-b");
  assert.equal(panel._fileTransferEditor.snapshot().action.id, TRANSFER.id);
  assert.equal(panel._fileTransferEditor.snapshot().busy, true);
  assert.equal(panel._fileTransferHost, host);
  assert.equal(panel._maintenanceEditor.snapshot(), null);
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.equal(panel._currentRouter().entry_id, "entry-a");
  assert.equal(panel._currentAdminPage().page.id, "system_backup");
  assert.equal(calls.length, 2);
  completed.resolve(new Response(JSON.stringify({action: TRANSFER.id, result: {status: "reconnect_required"}}),
    {headers: {"content-type": "application/json"}}));
  await uploading;
  assert.equal(panel._fileTransferEditor.snapshot().busy, false);
  assert.equal(panel._fileTransferEditor.snapshot().complete, true);
  assert.equal(panel._fileTransferEditor.snapshot().status, "reconnect_required");
  assert.equal(calls.length, 2);
});
