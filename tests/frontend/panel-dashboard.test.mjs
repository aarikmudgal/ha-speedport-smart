import assert from "node:assert/strict";
import test from "node:test";

class TestElement {
  constructor() { this.isConnected = true; }
  attachShadow() {
    this.shadowRoot = {innerHTML: "", activeElement: undefined, listeners: new Map(),
      addEventListener(name, handler) {this.listeners.set(name, handler);}, querySelector() {}, querySelectorAll() { return []; }};
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
  panel._metadata = {schema_version: 31, routers: [first, second]};
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
    assert.ok(html.includes("WAN cadence 3 s · Cooldown"));
    assert.ok(html.includes(`Retry in ~${text}`));
    assert.ok(!html.includes("5 min cooldown"));
    assert.ok(!html.includes("will start"));
  }
  assert.equal(calls.length, 0);
  assert.equal(panel._trafficHistory.snapshot(), null);
});

test("WAN cadence distinguishes configured cadence from the last achieved sample interval", () => {
  const {panel, first, calls} = fixture();
  for (const [observed, display] of [[2.34, "2.34"], [1, "1"], [60.1234, "60.12"]]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: {
      ...recoverySource(), state: "stable", retrying: false, effective_interval_seconds: 1,
      observed_interval_seconds: observed,
    }});
    assert.ok(html.includes("WAN cadence 1 s · Stable"));
    assert.ok(html.includes(`Last sample interval ${display} s`));
    assert.ok(!html.includes("WAN samples every"));
  }
  for (const observed of [null, undefined, 0, -1, "2.3", NaN, Infinity, {}, []]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: {
      ...recoverySource(), observed_interval_seconds: observed,
    }});
    assert.ok(!html.includes("Last sample interval"));
    assert.ok(html.includes("Cooldown"));
  }
  assert.equal(calls.length, 0);
});

test("WAN averaging target is distinct from polling and reports materially different actual spans", () => {
  const {panel, first, calls} = fixture();
  for (const [window, span, extra] of [[5, 5.02, false], [5, 2, true], [5, 10, true], [10, 10, false]]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: {
      ...recoverySource(), state: "stable", retrying: false, effective_interval_seconds: 1,
      observed_interval_seconds: 1.1, rate_window_seconds: window, rate_sample_span_seconds: span,
    }});
    assert.ok(html.includes("WAN cadence 1 s · Stable"));
    assert.ok(html.includes(`${window} s average window`));
    assert.ok(html.includes("Last sample interval 1.1 s"));
    assert.equal(html.includes("Current average span"), extra);
    if (extra) assert.ok(html.includes(`Current average span ${span} s`));
  }
  for (const window of [undefined, null, "5", 0, -1, Infinity, NaN, true, {}, []]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: {
      ...recoverySource(), rate_window_seconds: window, rate_sample_span_seconds: 10,
    }});
    assert.ok(!html.includes("average window"));
    assert.ok(!html.includes("Current average span"));
  }
  for (const unavailable of [{state: "cooldown", retrying: true}, {available: false}, {supported: false}]) {
    const html = panel._renderDashboard(first, first.entities, {wan_counters: {
      ...recoverySource(), state: "stable", retrying: false, ...unavailable,
      rate_window_seconds: 5, rate_sample_span_seconds: 10,
    }});
    assert.ok(html.includes("5 s average window"));
    assert.ok(!html.includes("Current average span"));
  }
  assert.equal(calls.length, 0);
});

test("live averaging telemetry keeps configured window but clears stale actual spans", () => {
  const entity = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  const source = {...recoverySource(), state: "stable", retrying: false, rate_window_seconds: 10, rate_sample_span_seconds: 10};
  const healthy = liveWanSourceFromEntityStates(source, entity, {"sensor.poll_state": {
    state: "stable", attributes: {rate_window_seconds: 5, rate_sample_span_seconds: 2},
  }});
  assert.equal(healthy.rate_window_seconds, 5);
  assert.equal(healthy.rate_sample_span_seconds, 2);
  for (const value of [null, undefined, "5", 0, -1, NaN, Infinity, false, {}]) {
    const live = liveWanSourceFromEntityStates(source, entity, {"sensor.poll_state": {
      state: "stable", attributes: {rate_window_seconds: value, rate_sample_span_seconds: value},
    }});
    assert.equal(live.rate_window_seconds, undefined);
    assert.equal(live.rate_sample_span_seconds, undefined);
  }
  const cooldown = liveWanSourceFromEntityStates(source, entity, {"sensor.poll_state": {
    state: "cooldown", attributes: {rate_window_seconds: 5, rate_sample_span_seconds: 10},
  }});
  assert.equal(cooldown.rate_window_seconds, 5);
  assert.equal(cooldown.rate_sample_span_seconds, undefined);
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

test("only genuinely newer healthy scheduler evidence overrides cached failed polling metadata", (t) => {
  const now = Date.parse("2026-09-03T12:00:10Z");
  t.mock.method(Date, "now", () => now);
  const entities = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  const source = {...recoverySource(), supported: true, available: false, polling_available: false,
    availability_checked_at: new Date(now - 5000).toISOString()};
  const fresh = {state: "stable", last_updated: new Date(now - 1000).toISOString(), attributes: {source_available: true}};
  const merged = liveWanSourceFromEntityStates(source, entities, {"sensor.poll_state": fresh});
  assert.equal(merged.available, true);
  assert.equal(merged.retrying, false);
  assert.equal(source.available, false);
  for (const candidate of [
    {...fresh, state: "unknown"}, {...fresh, state: "unavailable"}, {...fresh, state: "cooldown"},
    {...fresh, state: "retrying"}, {...fresh, state: "arbitrary"}, {...fresh, last_updated: undefined},
    {...fresh, last_updated: "invalid"}, {...fresh, last_updated: new Date(now - 5000).toISOString()},
    {...fresh, last_updated: new Date(now - 10000).toISOString()},
    {...fresh, last_updated: new Date(now + 5001).toISOString()},
    {...fresh, attributes: {source_available: false}}, {...fresh, attributes: {source_available: "true"}},
  ]) {
    assert.equal(liveWanSourceFromEntityStates(source, entities, {"sensor.poll_state": candidate}).available, false);
  }
  for (const changed of [
    {...source, availability_checked_at: undefined}, {...source, availability_checked_at: "invalid"},
    {...source, availability_checked_at: new Date(now + 5001).toISOString()}, {...source, supported: false},
  ]) assert.equal(liveWanSourceFromEntityStates(changed, entities, {"sensor.poll_state": fresh}).available, false);
  const old = {...source, availability_checked_at: new Date(now - 60000).toISOString()};
  assert.equal(liveWanSourceFromEntityStates(old, entities, {"sensor.poll_state": {...fresh, last_updated: new Date(now - 31000).toISOString()}}).available, false);
  const newerFailure = {...source, polling_available: true, availability_checked_at: new Date(now).toISOString()};
  assert.equal(liveWanSourceFromEntityStates(newerFailure, entities, {"sensor.poll_state": fresh}).available, false);
});

test("retained healthy attributes cannot revive an unavailable or unsupported WAN scheduler", () => {
  const entities = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  for (const state of ["unknown", "unavailable", "cooldown", "retrying"]) {
    const source = liveWanSourceFromEntityStates({...recoverySource(), available: true, polling_available: true}, entities,
      {"sensor.poll_state": {state, attributes: {source_available: true}}});
    assert.equal(source.available, false);
  }
});

test("live achieved interval attributes override metadata without coercing missing data to zero", () => {
  const entities = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  const source = {...recoverySource(), state: "stable", retrying: false, observed_interval_seconds: 4};
  for (const value of [1, 2.35, 59.2]) {
    assert.equal(liveWanSourceFromEntityStates(source, entities, {"sensor.poll_state": {
      state: "stable", attributes: {observed_interval_seconds: value},
    }}).observed_interval_seconds, value);
  }
  for (const value of [null, undefined, -1, 0, Infinity, NaN, "2", {}, []]) {
    assert.equal(liveWanSourceFromEntityStates(source, entities, {"sensor.poll_state": {
      state: "stable", attributes: {observed_interval_seconds: value},
    }}).observed_interval_seconds, undefined);
  }
});

test("retained measured intervals disappear immediately on live failure and stay hidden during recovery warmup", () => {
  const {panel, first} = fixture();
  const source = {...recoverySource(), available: true, state: "stable", retrying: false, observed_interval_seconds: 1};
  const entities = [{entity_id: "sensor.poll_state", translation_key: "wan_polling_state"}];
  for (const state of ["cooldown", "retrying", "unavailable", "unknown"]) {
    const live = liveWanSourceFromEntityStates(source, entities, {"sensor.poll_state": {
      state, attributes: {source_available: true, observed_interval_seconds: 1},
    }});
    assert.equal(live.observed_interval_seconds, undefined);
    assert.ok(!panel._renderDashboard(first, first.entities, {wan_counters: live}).includes("Last sample interval"));
  }
  for (const changed of [{available: false}, {supported: false}, {retrying: true}, {state: "cooldown"},
    {state: "learning", observed_interval_seconds: null}]) {
    assert.ok(!panel._renderDashboard(first, first.entities, {wan_counters: {...source, ...changed}}).includes("Last sample interval"));
  }
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

test("focused native timeframe selection survives WAN rerenders and drains once on blur", async () => {
  const {panel, calls} = fixture();
  panel._syncTrafficHistory(); await settle();
  const selector = {matches: (value) => value === "[data-traffic-window]"};
  const parts = [".sp-traffic-metrics", ".sp-traffic-chart", ".sp-traffic-note"];
  let latestMarkup; let refreshed = 0; const replacements = [];
  const nodes = Object.fromEntries(parts.map((part) => [part, {replaceWith(node) {replacements.push([part, node]);}}]));
  panel._trafficHost = {querySelector: (value) => value === "[data-traffic-window]" ? selector : nodes[value],
    ownerDocument: {createElement: () => ({set innerHTML(value) {latestMarkup = value;},
      content: {querySelector: (value) => ({part: value})}})}};
  panel._trafficBinding = Object.assign(() => {}, {refresh: () => {refreshed++;}});
  panel.shadowRoot.activeElement = selector;
  panel.shadowRoot.innerHTML = "native selector stays connected";
  SpeedportSmartPanel.prototype._render.call(panel);
  assert.equal(panel.shadowRoot.innerHTML, "native selector stays connected");
  assert.equal(panel._trafficWindowRenderPending, true);
  assert.equal(refreshed, 1);
  assert.deepEqual(replacements.map(([part]) => part), parts);
  await panel._trafficHistory.setWindowMinutes(60);
  panel._syncTrafficHistory(); await settle();
  SpeedportSmartPanel.prototype._render.call(panel);
  assert.equal(calls.length, 2);
  assert.equal(panel._trafficHistory.snapshot().windowMinutes, 60);
  assert.equal(panel.shadowRoot.innerHTML, "native selector stays connected");
  assert.match(latestMarkup, /60 min ago/);
  assert.equal(refreshed, 2);
  panel._trafficHistory.update({entryId: "entry-a", userId: "user-a", stale: true, states: panel._hass.states});
  SpeedportSmartPanel.prototype._render.call(panel);
  assert.match(latestMarkup, /No recent sample/);
  assert.equal(refreshed, 3);
  let renders = 0;
  panel._scheduleRender = () => {renders++;};
  panel.shadowRoot.activeElement = undefined;
  panel.shadowRoot.listeners.get("focusout")({target: selector});
  panel.shadowRoot.listeners.get("focusout")({target: selector});
  assert.equal(renders, 1);
  assert.equal(panel._trafficWindowRenderPending, false);
  SpeedportSmartPanel.prototype._render.call(panel);
  assert.ok(panel.shadowRoot.innerHTML.includes('<option value="60" selected>'));
  assert.equal(calls.length, 2);
});

test("timeframe focus cannot delay clearing another user, router, view or unloaded scope", async () => {
  for (const change of [
    (panel) => {panel._hass = {...panel._hass, user: {id: "user-b"}};},
    (panel) => {panel._selectedEntry = "entry-b";},
    (panel) => {panel._activeView = "connection";},
    (panel) => {panel.isConnected = false;},
  ]) {
    const {panel} = fixture(); panel._syncTrafficHistory(); await settle();
    const selector = {};
    panel._trafficHost = {querySelector: () => selector, innerHTML: "private old data"};
    panel.shadowRoot.activeElement = selector;
    SpeedportSmartPanel.prototype._render.call(panel);
    assert.equal(panel._trafficWindowRenderPending, true);
    change(panel); panel._syncTrafficHistory();
    assert.equal(panel._trafficWindowRenderPending, false);
    assert.equal(panel._trafficHost, undefined);
  }
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
  assert.equal(first.listeners.size, 9);
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
  assert.equal(second.listeners.size, 9);
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
