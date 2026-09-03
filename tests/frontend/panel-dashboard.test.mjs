import assert from "node:assert/strict";
import test from "node:test";

class TestElement {
  constructor() { this.isConnected = true; }
  attachShadow() {
    this.shadowRoot = {innerHTML: "", activeElement: undefined, addEventListener() {}, querySelector() {}, querySelectorAll() { return []; }};
    return this.shadowRoot;
  }
  dispatchEvent() {}
  toggleAttribute() {}
}
globalThis.HTMLElement = TestElement;
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=dashboard-integration");

const settle = () => new Promise((resolve) => setImmediate(resolve));
function deferred() { let resolve; const promise = new Promise((done) => {resolve = done;}); return {promise, resolve}; }
function rate(direction, suffix = "a") {
  return {entity_id: `sensor.${suffix}_${direction}`, domain: "sensor", translation_key: `wan_${direction}_rate`, section: "bandwidth", access_source: "wan_counters", control: false, control_supported: false};
}
function router(id = "entry-a", suffix = "a") {
  return {entry_id: id, entry_state: "loaded", title: `Router ${suffix}`, model: "Observed model", capabilities: [], access_sources: [], management: {state: "available"},
    entities: [rate("download", suffix), rate("upload", suffix),
      {entity_id: `sensor.${suffix}_wifi`, domain: "sensor", translation_key: "wifi_5_clients", section: "wireless", control: false},
      {entity_id: `switch.${suffix}_wifi`, domain: "switch", translation_key: "wifi", section: "controls", management_feature: "network_wifi_main", control: true, control_supported: true}]};
}
function fixture(options = {}) {
  const panel = new SpeedportSmartPanel();
  const calls = [];
  const first = router(); const second = router("entry-b", "b");
  panel._metadata = {schema_version: 24, routers: [first, second]};
  panel._selectedEntry = first.entry_id;
  panel._platformIcons = {}; panel._componentIcons = {};
  panel._scheduleRender = () => {}; panel._render = () => {};
  const timestamp = new Date(Date.now() - 2000).toISOString();
  panel._hass = {user: {id: "user-a", is_admin: false}, language: "en", locale: {language: "en-US"}, entities: {}, states: {}, connection: {
    sendMessagePromise(message) { calls.push(message); return options.request ? options.request(message) : Promise.resolve({}); },
  }};
  for (const selected of [first, second]) for (const meta of selected.entities) {
    panel._hass.states[meta.entity_id] = {state: meta.domain === "switch" ? "on" : "6", last_updated: timestamp,
      attributes: {unit_of_measurement: meta.translation_key.startsWith("wan_") ? "Mbit/s" : undefined}};
  }
  return {panel, calls, first, second};
}

test("dashboard history reads exactly the two selected router WAN entities once", async () => {
  const {panel, calls} = fixture();
  panel._syncTrafficHistory(); await settle();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].type, "history/history_during_period");
  assert.deepEqual(calls[0].entity_ids, ["sensor.a_download", "sensor.a_upload"]);
  assert.equal(Date.parse(calls[0].end_time) - Date.parse(calls[0].start_time), 15 * 60 * 1000);
  assert.equal(calls[0].no_attributes, false);
  assert.equal(calls[0].significant_changes_only, false);
  panel._syncTrafficHistory(); panel._syncTrafficHistory(); await settle();
  assert.equal(calls.length, 1);
  assert.equal(panel._trafficHistory.snapshot().series.download.current, 6);
});

test("disabled, child, control and wrong-domain lookalikes cannot become WAN history scope", async () => {
  const {panel, calls, first} = fixture();
  first.entities.unshift(
    {...rate("download"), entity_id: "sensor.disabled", disabled_by: "user"},
    {...rate("download"), entity_id: "sensor.child", child_device: {kind: "client", device_id: "child"}},
    {...rate("download"), entity_id: "sensor.control", control_supported: true},
    {...rate("download"), entity_id: "sensor.writable", control: true},
    {...rate("download"), entity_id: "binary_sensor.wrong", domain: "binary_sensor"},
  );
  panel._syncTrafficHistory(); await settle();
  assert.deepEqual(calls[0].entity_ids, ["sensor.a_download", "sensor.a_upload"]);
});

test("normal Home Assistant WAN updates append current samples without history rereads", async () => {
  const {panel, calls} = fixture(); panel._syncTrafficHistory(); await settle();
  for (let index = 0; index < 5; index++) {
    panel.hass = {...panel._hass, states: {...panel._hass.states, "sensor.a_download": {
      state: String(20 + index), last_updated: new Date(Date.now() - 1000 + index).toISOString(), attributes: {unit_of_measurement: "Mbit/s"},
    }}};
  }
  await settle();
  assert.equal(calls.length, 1);
  assert.equal(panel._trafficHistory.snapshot().series.download.current, 24);
});

test("switching away drops graph scope and does not read history in Administration", async () => {
  const {panel, calls} = fixture(); panel._syncTrafficHistory(); await settle();
  panel._selectView("administration");
  assert.equal(panel._trafficHistory.snapshot(), null);
  panel._syncTrafficHistory(); await settle(); assert.equal(calls.length, 1);
  panel._selectView("dashboard"); await settle();
  assert.equal(calls.length, 2);
  assert.equal(panel._trafficHistory.snapshot().entryId, "entry-a");
});

test("router switch drops old points before scoped replacement history completes", async () => {
  const pending = deferred();
  const {panel, calls} = fixture({request: () => pending.promise});
  panel._syncTrafficHistory();
  panel._selectRouter("entry-b");
  const snapshot = panel._trafficHistory.snapshot();
  assert.equal(snapshot.entryId, "entry-b"); assert.equal(snapshot.historyStatus, "loading");
  assert.deepEqual(calls.map((item) => item.entity_ids), [["sensor.a_download", "sensor.a_upload"], ["sensor.b_download", "sensor.b_upload"]]);
  pending.resolve({"sensor.a_download": [{s: "777", lu: Date.now() / 1000 - 4, a: {unit_of_measurement: "Mbit/s"}}]});
  await settle();
  assert.equal(panel._trafficHistory.snapshot().entryId, "entry-b");
  assert.ok(panel._trafficHistory.snapshot().series.download.points.every((point) => point.value !== 777));
});

test("user change discards old history and binds the next read to the new user", async () => {
  const {panel, calls} = fixture(); panel._syncTrafficHistory(); await settle();
  panel.hass = {...panel._hass, user: {id: "user-b", is_admin: false}};
  assert.equal(panel._trafficHistory.snapshot().userId, "user-b");
  await settle(); assert.equal(calls.length, 2);
  panel.hass = {...panel._hass, user: {is_admin: false}};
  assert.equal(panel._trafficHistory.snapshot(), null);
  assert.equal(calls.length, 2);
});

test("unload clears graph memory and ignores a late history response", async () => {
  const pending = deferred(); const {panel, calls} = fixture({request: () => pending.promise});
  panel._syncTrafficHistory(); panel.isConnected = false; panel.disconnectedCallback();
  assert.equal(panel._trafficHistory.snapshot(), null); assert.equal(panel.shadowRoot.innerHTML, "");
  pending.resolve({"sensor.a_download": [{s: "888", lu: Date.now() / 1000 - 4, a: {unit_of_measurement: "Mbit/s"}}]});
  await settle(); assert.equal(panel._trafficHistory.snapshot(), null);
  panel.hass = {...panel._hass, states: {...panel._hass.states, "sensor.a_download": {...panel._hass.states["sensor.a_download"], state: "32"}}};
  await settle(); assert.equal(calls.length, 1); assert.equal(panel._trafficHistory.snapshot(), null);
});

test("metadata removal drops inaccessible series and requests only still advertised entity", async () => {
  const {panel, calls, first} = fixture(); panel._syncTrafficHistory(); await settle();
  first.entities = first.entities.filter((meta) => meta.translation_key !== "wan_download_rate");
  panel._syncTrafficHistory(); await settle();
  assert.deepEqual(calls[1].entity_ids, ["sensor.a_upload"]);
  assert.equal(panel._trafficHistory.snapshot().series.download.current, null);
  assert.deepEqual(panel._trafficHistory.snapshot().series.download.points, []);
});

test("missing, unloaded router or unavailable connection cannot start history", () => {
  for (const alter of [
    (panel) => {panel._metadata = {routers: []};},
    (_panel, first) => {first.entry_state = "setup_error";},
    (panel) => {panel._hass.connection = {};},
  ]) {
    const {panel, calls, first} = fixture(); alter(panel, first); panel._syncTrafficHistory();
    assert.equal(calls.length, 0); assert.equal(panel._trafficHistory.snapshot(), null);
  }
});

test("history rejection leaves live samples usable and does not retry on normal updates", async () => {
  const {panel, calls} = fixture({request: () => Promise.reject(new Error("unavailable"))});
  panel._syncTrafficHistory(); await settle();
  assert.equal(panel._trafficHistory.snapshot().historyStatus, "unavailable");
  assert.equal(panel._trafficHistory.snapshot().series.download.current, 6);
  panel._syncTrafficHistory(); await settle(); assert.equal(calls.length, 1);
});

test("current degraded WAN source makes graph stale rather than presenting frozen rates as live", async () => {
  const {panel, first} = fixture(); first.access_sources = [{id: "wan_counters", available: false, retrying: true}];
  panel._syncTrafficHistory(); await settle();
  assert.equal(panel._trafficHistory.snapshot().series.download.current, null);
  assert.equal(panel._trafficHistory.snapshot().series.download.stale, true);
});

test("actual panel render is read-only and contains graph plus headlines without admin data", async () => {
  const {panel, calls, first} = fixture(); panel._syncTrafficHistory(); await settle();
  panel._adminRead = {sections: [{id: "clients", rows: [{name: "Private admin result"}]}]};
  panel._adminReadEntry = first.entry_id;
  const before = calls.length;
  for (let count = 0; count < 3; count++) SpeedportSmartPanel.prototype._render.call(panel);
  const html = panel.shadowRoot.innerHTML.split("</style>").at(-1);
  assert.ok(html.includes('class="dashboard-overview"'));
  assert.ok(html.includes('class="sp-traffic-history"'));
  assert.ok(html.includes('data-more-info="sensor.a_wifi"'));
  assert.doesNotMatch(html, /data-control=|data-open-setting=|Private admin result|data-admin-feature=/);
  assert.equal(calls.length, before);
});
