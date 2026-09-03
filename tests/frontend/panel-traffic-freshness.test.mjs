import assert from "node:assert/strict";
import test from "node:test";

class TestElement {
  constructor() { this.isConnected = true; }
  attachShadow() {
    this.shadowRoot = {innerHTML: "", addEventListener() {}, querySelector() {}, querySelectorAll() { return []; }};
    return this.shadowRoot;
  }
}
globalThis.HTMLElement = TestElement;
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=traffic-freshness");

const BASE = Date.parse("2026-09-03T09:00:00Z");
const iso = (seconds) => new Date(BASE + seconds * 1000).toISOString();

function fixture(t, value = "0") {
  let seconds = 0;
  t.mock.method(Date, "now", () => BASE + seconds * 1000);
  const panel = new SpeedportSmartPanel();
  panel._scheduleRender = () => {};
  panel._render = () => {};
  const calls = [];
  const source = {id: "wan_counters", supported: true, available: true, polling_available: true,
    state: "stable", retrying: false, effective_interval_seconds: 1, last_sampled_at: iso(0)};
  const router = {entry_id: "entry-a", entry_state: "loaded", access_sources: [source], entities: [
    {entity_id: "sensor.download", domain: "sensor", translation_key: "wan_download_rate"},
    {entity_id: "sensor.upload", domain: "sensor", translation_key: "wan_upload_rate"},
    {entity_id: "sensor.sample_clock", domain: "sensor", translation_key: "wan_last_sample"},
  ]};
  const rate = {state: value, last_updated: iso(-600), attributes: {unit_of_measurement: "Mbit/s"}};
  const states = {"sensor.download": rate, "sensor.upload": rate, "sensor.sample_clock": {state: iso(0)}};
  panel._metadata = {routers: [router]};
  panel._selectedEntry = router.entry_id;
  panel._hass = {user: {id: "user-a", is_admin: false}, states, connection: {
    sendMessagePromise(message) { calls.push(message); return Promise.resolve({}); },
  }};
  t.after(() => panel._trafficHistory.dispose());
  return {
    panel, source, states, calls, router,
    setTime(value) { seconds = value; },
    async sync() { panel._syncTrafficHistory(); await Promise.resolve(); },
    current() { return panel._trafficHistory.snapshot().series.download; },
  };
}

for (const value of ["0", "37.125"]) {
  test(`fresh precise WAN observations keep unchanged ${value} Mbit/s usable across minute boundaries`, async (t) => {
    const view = fixture(t, value);
    const original = view.states["sensor.download"];
    const times = [0, 29, 31, 59, 60, 89, 91];
    for (const seconds of times) {
      view.setTime(seconds);
      view.source.last_sampled_at = iso(seconds);
      view.states["sensor.sample_clock"] = {state: iso(Math.floor(seconds / 60) * 60)};
      await view.sync();
      assert.equal(view.current().current, Number(value), `false stale at second ${seconds}`);
      assert.equal(view.current().lastSampleAt, BASE + seconds * 1000);
      assert.equal(view.states["sensor.download"], original);
    }
    assert.deepEqual(view.current().points.map(({time}) => time), times.map((seconds) => BASE + seconds * 1000));
    assert.equal(view.calls.length, 1);
    assert.equal(view.calls[0].type, "history/history_during_period");
  });
}

test("stopped precise and diagnostic sample clocks expire without artificial heartbeat points", async (t) => {
  const view = fixture(t);
  view.setTime(29); view.source.last_sampled_at = iso(29);
  await view.sync();
  assert.equal(view.current().current, 0);
  view.setTime(59); await view.sync();
  assert.equal(view.current().current, 0);
  view.setTime(60); await view.sync();
  assert.equal(view.current().current, null);
  assert.equal(view.current().stale, true);
  assert.deepEqual(view.current().points.map(({time}) => time), [BASE + 29000]);
  assert.equal(view.calls.length, 1);
});

for (const offset of [0.001, 0.25, 2, 5]) {
  test(`a ${offset}s HA clock lead keeps real unchanged WAN samples visible without inventing observations`, async (t) => {
    const view = fixture(t, "0");
    for (let seconds = 0; seconds <= 90; seconds += 10) {
      view.setTime(seconds);
      view.source.last_sampled_at = iso(seconds + offset);
      view.states["sensor.sample_clock"].state = iso(Math.floor((seconds + offset) / 60) * 60);
      await view.sync();
      assert.equal(view.current().current, 0, `false stale at second ${seconds}`);
      assert.equal(view.current().lastSampleAt, BASE + (seconds + offset) * 1000);
    }
    const actualTimes = view.current().points.map(({time}) => time);
    assert.equal(actualTimes.at(-1), BASE + (90 + offset) * 1000);
    view.setTime(121 + offset);
    await view.sync();
    assert.equal(view.current().current, null);
    assert.deepEqual(view.current().points.map(({time}) => time), actualTimes);
    assert.equal(view.calls.length, 1);
  });
}

test("subsecond clock skew and network jitter do not alternate valid native WAN values with blanks", async (t) => {
  const view = fixture(t);
  for (const [browser, observed, value] of [[31, 31.25, "1.66"], [32, 31.9, "4.41"], [33, 33.25, "4.59"], [33.5, 33.25, "4.59"]]) {
    view.setTime(browser);
    view.source.last_sampled_at = iso(observed);
    view.states["sensor.download"] = {state: value, last_updated: iso(observed), attributes: {unit_of_measurement: "Mbit/s"}};
    await view.sync();
    assert.equal(view.current().current, Number(value));
    assert.equal(view.current().lastSampleAt, BASE + observed * 1000);
  }
  assert.deepEqual(view.current().points.map(({time}) => time), [31.9, 33.25].map((seconds) => BASE + seconds * 1000));
  assert.equal(view.calls.length, 1);
});

test("a genuinely newer diagnostic clock wins over older precise metadata", async (t) => {
  const view = fixture(t);
  view.setTime(61); view.source.last_sampled_at = iso(29);
  view.states["sensor.sample_clock"].state = iso(60);
  await view.sync();
  assert.equal(view.current().current, 0);
  assert.equal(view.current().lastSampleAt, BASE + 60000);
});

for (const [label, metadata, diagnostic, expected] of [
  ["invalid metadata", "invalid", iso(60), 60],
  ["future metadata", iso(67), iso(60), 60],
  ["invalid diagnostic", iso(59), "unknown", 59],
  ["future diagnostic", iso(59), iso(67), 59],
  ["both invalid", "unavailable", "invalid", -600],
  ["both future", iso(67), iso(68), -600],
  ["non-string clocks", true, null, -600],
]) {
  test(`${label} cannot displace the freshest valid WAN observation`, async (t) => {
    const view = fixture(t);
    view.setTime(61); view.source.last_sampled_at = metadata;
    view.states["sensor.sample_clock"].state = diagnostic;
    await view.sync();
    assert.equal(view.current().lastSampleAt, BASE + expected * 1000);
    assert.equal(view.current().current, expected >= 0 ? 0 : null);
  });
}

test("missing diagnostic entity still uses precise source metadata", async (t) => {
  const view = fixture(t);
  view.router.entities = view.router.entities.filter((meta) => meta.translation_key !== "wan_last_sample");
  view.setTime(59); view.source.last_sampled_at = iso(59);
  await view.sync();
  assert.equal(view.current().current, 0);
  assert.equal(view.current().lastSampleAt, BASE + 59000);
});

test("missing source metadata retains a valid diagnostic observation", async (t) => {
  const view = fixture(t);
  view.router.access_sources = [];
  view.setTime(61); view.states["sensor.sample_clock"].state = iso(60);
  await view.sync();
  assert.equal(view.current().current, 0);
  assert.equal(view.current().lastSampleAt, BASE + 60000);
});

test("source clock selection preserves a newer actual rate-state timestamp", async (t) => {
  const view = fixture(t, "12.5");
  view.setTime(59); view.source.last_sampled_at = iso(55);
  view.states["sensor.download"] = {...view.states["sensor.download"], last_updated: iso(58)};
  await view.sync();
  assert.equal(view.current().current, 12.5);
  assert.equal(view.current().lastSampleAt, BASE + 58000);
});

for (const value of ["unknown", "unavailable"]) {
  test(`fresh clocks never revive ${value} rate state`, async (t) => {
    const view = fixture(t, value);
    view.setTime(59); view.source.last_sampled_at = iso(59);
    await view.sync();
    assert.equal(view.current().current, null);
    assert.equal(view.current().stale, true);
    assert.ok(view.current().points.every(({value}) => value === null));
  });
}

for (const blocked of [{retrying: true}, {available: false}, {supported: false}]) {
  test(`${Object.keys(blocked)[0]} WAN gate is not bypassed by fresh clocks`, async (t) => {
    const view = fixture(t, "12.5");
    view.setTime(59); view.source.last_sampled_at = iso(59);
    Object.assign(view.source, blocked);
    await view.sync();
    assert.equal(view.current().current, null);
    assert.equal(view.current().stale, true);
    assert.deepEqual(view.current().points, []);
  });
}
