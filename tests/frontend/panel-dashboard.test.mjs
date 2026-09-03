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
const {SpeedportSmartPanel, liveWanSourceFromEntityStates, wanTelemetryPresentation} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=dashboard-integration");

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
  panel._metadata = {schema_version: 28, routers: [first, second]};
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

function recoverySource(overrides = {}) {
  return {id: "wan_counters", available: true, state: "cooldown", mode: "auto",
    effective_interval_seconds: 3, cooldown_seconds: 60,
    retry_in_seconds: 45, retrying: true, success_streak: 0,
    success_samples_required: 5, ...overrides};
}

test("dashboard shows fixed sixty-second cooldown without changing cadence or requesting data", () => {
  const {panel, first, calls} = fixture();
  for (const [remaining, text] of [[60, "1 min"], [45, "45 s"], [0.2, "1 s"]]) {
    const html = panel._renderDashboard(first, first.entities.filter((item) => !item.control),
      {wan_counters: recoverySource({retry_in_seconds: remaining})});
    assert.ok(html.includes("WAN samples every 3 s · Cooldown"));
    assert.ok(html.includes(`Retry in ~${text}`));
    assert.ok(!html.includes("5 min cooldown"));
    assert.ok(!html.includes("will start"));
  }
  assert.equal(calls.length, 0);
  assert.equal(panel._trafficHistory.snapshot(), null);
});

for (const [source, text] of [
  [recoverySource({retry_in_seconds: 0}), "Waiting for next poll"],
  [recoverySource({available: false}), "Retry in ~45 s"],
  [recoverySource({polling_available: false}), "Retry in ~45 s"],
  [recoverySource({state: "learning", retrying: false}), "Successful polls 0/5"],
  [recoverySource({state: "learning", retrying: false, success_streak: 4}), "Successful polls 4/5"],
  [recoverySource({state: "learning", retrying: false, success_streak: 5}), "Successful polls 5/5"],
]) {
  test(`dashboard cadence distinguishes ${source.state}/${source.retry_in_seconds}/${source.success_streak}/${source.available}/${source.polling_available}`, () => {
    const {panel, first, calls} = fixture();
    const html = panel._renderDashboard(first, first.entities, {wan_counters: source});
    assert.ok(html.includes(text));
    assert.ok(!html.includes("Retry in ~0 s"));
    assert.equal(calls.length, 0);
  });
}

test("missing, malformed, settled and obsolete metadata do not invent progress or retry timing", () => {
  const {panel, first, calls} = fixture();
  for (const source of [
    {id: "wan_counters", effective_interval_seconds: 5, state: "limited"},
    {id: "wan_counters", effective_interval_seconds: 5, state: "limited", recovery_cooldown_seconds: 300,
      next_probe_in_seconds: 270, recovery_success_samples: 6, recovery_required_success_samples: 12},
    ...["stable", "manual", "unknown", "retrying", "limited"].map((state) => recoverySource({state})),
    ...[undefined, null, "45", -1, 61, NaN, Infinity, false, []].map((retry_in_seconds) => recoverySource({retry_in_seconds})),
    ...[undefined, null, 300, "60"].map((cooldown_seconds) => recoverySource({cooldown_seconds})),
    ...[undefined, null, "4", -1, 6, 0.5].map((success_streak) => recoverySource({state: "learning", retrying: false, success_streak})),
    ...[undefined, null, "5", 0, 12, 0.5].map((success_samples_required) => recoverySource({state: "learning", retrying: false, success_samples_required})),
  ]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: source});
    assert.ok(!html.includes("Faster trial"));
    assert.ok(!html.includes("Retry in ~"));
    assert.ok(!html.includes("Successful polls"));
  }
  assert.equal(calls.length, 0);
});

test("live Cooldown sensor overrides cached Learning state and remains degraded", () => {
  const source = liveWanSourceFromEntityStates(recoverySource({state: "learning", retrying: false}),
    [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}],
    {"sensor.poll_state": {state: "cooldown", attributes: {source_available: false, retry_in_seconds: 30,
      cooldown_seconds: 60, success_samples_required: 5, success_streak: 0}}});
  assert.equal(source.state, "cooldown");
  assert.equal(source.retrying, true);
  assert.equal(source.retry_in_seconds, 30);
  const presentation = wanTelemetryPresentation(undefined, undefined, source);
  assert.equal(presentation.schedulerState, "cooldown");
  assert.equal(presentation.retrying, true);
  assert.equal(presentation.degraded, true);
});

test("fresh Learning attributes override stale counters while malformed values stay unknown", () => {
  const {panel, first, calls} = fixture();
  const entities = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  const source = liveWanSourceFromEntityStates(recoverySource(), entities,
    {"sensor.poll_state": {state: "learning", attributes: {source_available: true, retry_in_seconds: 0,
      success_streak: 2, success_samples_required: 5, cooldown_seconds: 60}}});
  assert.equal(source.retrying, false);
  assert.equal(source.success_streak, 2);
  assert.ok(panel._renderDashboard(first, first.entities, {wan_counters: source}).includes("Successful polls 2/5"));
  for (const invalid of [null, false, "2", NaN, Infinity, -1]) {
    const malformed = liveWanSourceFromEntityStates(source, entities,
      {"sensor.poll_state": {state: "learning", attributes: {success_streak: invalid}}});
    assert.equal(malformed.success_streak, undefined);
    assert.ok(!panel._renderDashboard(first, first.entities, {wan_counters: malformed}).includes("Successful polls"));
    const cooldown = liveWanSourceFromEntityStates(recoverySource(), entities,
      {"sensor.poll_state": {state: "cooldown", attributes: {retry_in_seconds: invalid}}});
    assert.equal(cooldown.retry_in_seconds, undefined);
    assert.ok(!panel._renderDashboard(first, first.entities, {wan_counters: cooldown}).includes("Retry in ~"));
  }
  assert.equal(calls.length, 0);
});

for (const [language, label] of [["en", "Cooldown"], ["de", "Abkühlphase"]]) {
  test(`detailed ${language} WAN cooldown labels never claim the router is busy`, () => {
    const {panel, first, calls} = fixture();
    panel._hass.language = language; panel._hass.locale.language = language;
    const source = recoverySource({retrying: false});
    const meta = first.entities[0];
    assert.equal(wanTelemetryPresentation(meta, panel._hass.states[meta.entity_id], source).rateStatusKey, "status.rate_cooldown");
    for (const html of [panel._renderSource(source),
      panel._renderSection("bandwidth", [meta], first, {wan_counters: source}),
      panel._renderEntity(meta, {hero: true, sourceState: source})]) {
      assert.ok(html.toLowerCase().includes(label.toLowerCase()));
      assert.doesNotMatch(html, /telemetry busy|Telemetrie belegt|recent aggregate WAN rate|aktuelle gesamte WAN-Rate/);
    }
    assert.equal(calls.length, 0);
  });
}

test("explicit Cooldown keeps cached graph samples non-live even without a retry flag", async () => {
  const {panel, first, calls} = fixture();
  first.access_sources = [recoverySource({retrying: false})];
  panel._syncTrafficHistory(); await settle();
  assert.equal(panel._trafficHistory.snapshot().series.download.current, null);
  assert.equal(panel._trafficHistory.snapshot().series.upload.current, null);
  assert.equal(calls.length, 1);
});

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

test("WAN readouts delegate more-info to their actual HA entities without router I/O", async () => {
  const {panel, calls} = fixture();
  panel._hass.states["sensor.a_upload"].state = "unavailable";
  panel._syncTrafficHistory(); await settle();
  SpeedportSmartPanel.prototype._render.call(panel);
  const html = panel.shadowRoot.innerHTML.split("</style>").at(-1);
  const targets = [...html.matchAll(/<button\b[^>]*class="sp-traffic-metric[^>]*data-more-info="([^"]+)"/g)]
    .map((match) => match[1]);
  assert.deepEqual(targets, ["sensor.a_download", "sensor.a_upload"]);
  const sent = calls.length;
  const events = [];
  panel.dispatchEvent = (event) => {events.push(event); return true;};
  for (const moreInfo of targets) panel._handleClick({target: {closest: () => ({dataset: {moreInfo}})}});
  assert.deepEqual(events.map((event) => [event.type, event.detail.entityId, event.bubbles, event.composed]),
    [["hass-more-info", "sensor.a_download", true, true], ["hass-more-info", "sensor.a_upload", true, true]]);
  assert.equal(calls.length, sent);
});

test("actual panel keeps one graph binding on a stable host and disposes it on every scope exit", async () => {
  const {panel, calls} = fixture();
  const shadow = panel.shadowRoot;
  let currentHost;
  Object.defineProperty(shadow, "innerHTML", {
    set(value) {
      this.html = value;
      if (!value.includes("data-traffic-history-host")) {currentHost = undefined; return;}
      currentHost = {
        innerHTML: value, listeners: new Map(),
        addEventListener(name, handler) {this.listeners.set(name, handler);},
        removeEventListener(name, handler) {if (this.listeners.get(name) === handler) this.listeners.delete(name);},
        querySelector() {},
        replaceWith(host) {currentHost = host;},
      };
    },
    get() {return this.html ?? "";},
  });
  shadow.querySelector = (selector) => selector === "[data-traffic-history-host]" ? currentHost : undefined;
  panel._syncTrafficHistory(); await settle();
  SpeedportSmartPanel.prototype._render.call(panel);
  const first = panel._trafficHost;
  const binding = panel._trafficBinding;
  assert.equal(first.listeners.size, 8);
  const listeners = [...first.listeners];
  SpeedportSmartPanel.prototype._render.call(panel);
  assert.equal(panel._trafficHost, first);
  assert.equal(panel._trafficBinding, binding);
  assert.deepEqual([...first.listeners], listeners);
  assert.equal(calls.length, 1);
  panel._selectRouter("entry-b");
  assert.equal(first.listeners.size, 0);
  assert.equal(first.innerHTML, "");
  SpeedportSmartPanel.prototype._render.call(panel);
  const second = panel._trafficHost;
  assert.notEqual(second, first);
  assert.equal(second.listeners.size, 8);
  panel.hass = {...panel._hass, user: {id: "user-b", is_admin: false}};
  assert.equal(second.listeners.size, 0);
  SpeedportSmartPanel.prototype._render.call(panel);
  const third = panel._trafficHost;
  panel._selectView("administration");
  assert.equal(third.listeners.size, 0);
  assert.equal(panel._trafficHost, undefined);
  panel._selectView("dashboard");
  SpeedportSmartPanel.prototype._render.call(panel);
  const fourth = panel._trafficHost;
  panel.isConnected = false; panel.disconnectedCallback();
  assert.equal(fourth.listeners.size, 0);
  assert.equal(panel._trafficHost, undefined);
});
