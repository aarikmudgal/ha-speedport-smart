import assert from "node:assert/strict";
import test from "node:test";
import {
  bindTrafficHistory,
  createTrafficHistoryController,
  renderTrafficHistory,
  trafficRateMbit,
  TRAFFIC_HISTORY_MAX_POINTS,
  TRAFFIC_HISTORY_STYLES,
  TRAFFIC_HISTORY_WINDOW_MS,
} from "../../custom_components/speedport_smart/frontend/traffic-history.js";

const END = Date.parse("2026-09-03T12:00:00Z");
const DOWN = "sensor.router_download";
const UP = "sensor.router_upload";
const SCOPE = {entryId: "entry-a", userId: "user-a", entities: {download: DOWN, upload: UP}};
const iso = (time) => new Date(time).toISOString();
const row = (time, value = "12", unit = "Mbit/s", extra = {}) => ({s: value, a: {unit_of_measurement: unit}, lu: time / 1000, ...extra});
const current = (time, value = "12", unit = "Mbit/s") => ({state: value, last_updated: iso(time), attributes: {unit_of_measurement: unit}});
const states = (time, down = "12", up = "3") => ({[DOWN]: current(time, down), [UP]: current(time, up)});
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
function setup(response = {}, initialTime = END) {
  const calls = [];
  let time = initialTime;
  let changes = 0;
  const controller = createTrafficHistoryController({request: async (message) => {
    calls.push(message);
    if (response instanceof Error) throw response;
    return response;
  }, now: () => time, onChange: () => { changes++; }});
  return {controller, calls, setTime: (value) => { time = value; }, changes: () => changes};
}

test("rate normalization preserves bits versus bytes and canonical HA units", () => {
  for (const [value, unit, result] of [[1000000, "bit/s", 1], [1000000, "bps", 1],
    [1000, "kbit/s", 1], [1000, "kbps", 1], [1, "Mbit/s", 1], [1, "Mbps", 1],
    [1, "Gbit/s", 1000], [1, "Gbps", 1000], [1, "Tbit/s", 1000000],
    [125000, "B/s", 1], [125, "kB/s", 1], [1, "MB/s", 8], [1, "GB/s", 8000], [1, "TB/s", 8000000]])
    assert.equal(trafficRateMbit(String(value), unit), result, unit);
  assert.equal(trafficRateMbit("0", "Mbit/s"), 0);
  assert.equal(trafficRateMbit("1.25e2", "bit/s"), 0.000125);
  assert.equal(trafficRateMbit(" .25 ", "Mbit/s"), 0.25);
});

test("unknown units and nonnumeric states never become a zero sample", () => {
  for (const value of ["", " ", "unknown", "unavailable", "none", "NaN", "Infinity", "-1", "0x10", null, undefined, true, [], {}, Infinity, -1, "9".repeat(65)])
    assert.equal(trafficRateMbit(value, "Mbit/s"), null, String(value));
  for (const unit of [undefined, null, "Mb/s", "mbit/s", "bits", "__proto__", "constructor", "<svg>"])
    assert.equal(trafficRateMbit("20", unit), null, String(unit));
});

test("one fixed two-entity read covers the preceding15min without artificial boundary state", async () => {
  const {controller, calls} = setup();
  await controller.open({...SCOPE, states: states(END)});
  assert.deepEqual(calls, [{type: "history/history_during_period", entity_ids: [DOWN, UP],
    start_time: iso(END - TRAFFIC_HISTORY_WINDOW_MS), end_time: iso(END),
    include_start_time_state: false, significant_changes_only: false, minimal_response: false, no_attributes: false}]);
  for (let index = 0; index < 10; index++) {
    controller.update({...SCOPE, states: states(END)});
    await controller.open({...SCOPE, states: states(END)});
  }
  assert.equal(calls.length, 1);
  assert.equal(controller.snapshot().series.download.points.length, 1);
  assert.equal(controller.snapshot().historyStatus, "empty");
});

test("compact history uses last_updated, per-row units, and only selected entities", async () => {
  const response = {
    [DOWN]: [row(END - 60000, "1000000", "bit/s", {lc: (END - 200000) / 1000}),
      row(END - 30000, "2", "MB/s"), {s: "3", a: {unit_of_measurement: "Mbit/s"}, lc: (END - 15000) / 1000}],
    [UP]: [row(END - 30000, "1000", "kbit/s")],
    "sensor.other_user": [row(END, "999999")],
  };
  const {controller} = setup(response);
  await controller.open({...SCOPE, states: states(END)});
  const view = controller.snapshot();
  assert.equal(view.historyStatus, "ready");
  assert.deepEqual(view.series.download.points.map(({time, value}) => [time, value]),
    [[END - 60000, 1], [END - 30000, 16], [END - 15000, 3], [END, 12]]);
  assert.deepEqual(view.series.upload.points.map(({value}) => value), [1, 3]);
  assert.doesNotMatch(JSON.stringify(view), /other_user|999999|unit_of_measurement/);
});

test("expanded HA state objects use each observation timestamp and unit too", async () => {
  const {controller} = setup({[DOWN]: [current(END - 60000, "1000000", "bit/s")], [UP]: []});
  await controller.open({...SCOPE, states: states(END)});
  assert.equal(controller.snapshot().series.download.points[0].value, 1);
});

test("missing historical attributes remain a gap, never borrow today's unit", async () => {
  const {controller} = setup({[DOWN]: [{s: "1000000", lu: (END - 60000) / 1000}], [UP]: []});
  await controller.open({...SCOPE, states: states(END)});
  assert.equal(controller.snapshot().series.download.points[0].value, null);
  assert.equal(controller.snapshot().historyStatus, "empty");
});

test("an absent series is empty history, not a failed history response", async () => {
  const {controller} = setup({[DOWN]: [row(END - 60000)]});
  await controller.open({...SCOPE, states: states(END)});
  assert.equal(controller.snapshot().historyStatus, "ready");
  assert.equal(controller.snapshot().series.upload.points.length, 1);
  assert.doesNotMatch(renderTrafficHistory(controller.snapshot()), /History unavailable/);
});

test("live updates received while history loads survive merge and duplicate timestamps", async () => {
  const gate = deferred();
  let time = END;
  const controller = createTrafficHistoryController({request: () => gate.promise, now: () => time});
  const loading = controller.open({...SCOPE, states: states(END, "7")});
  time += 10000;
  controller.update({...SCOPE, states: states(time, "8")});
  gate.resolve({[DOWN]: [row(END - 10000, "1"), row(END, "999")], [UP]: []});
  await loading;
  assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [1, 7, 8]);
  assert.equal(controller.snapshot().series.download.current, 8);
});

test("history failure keeps live warming samples, masks errors, and never retries", async () => {
  const {controller, calls} = setup(new Error("PRIVATE-TOKEN-RAW-ERROR"));
  await controller.open({...SCOPE, states: {}});
  assert.equal(controller.snapshot().historyStatus, "unavailable");
  assert.match(renderTrafficHistory(controller.snapshot()), /History unavailable.*Waiting for usable samples/s);
  controller.update({...SCOPE, states: states(END, "0")});
  assert.equal(controller.snapshot().series.download.current, 0);
  assert.doesNotMatch(renderTrafficHistory(controller.snapshot()), /PRIVATE-TOKEN|RAW-ERROR/);
  assert.match(renderTrafficHistory(controller.snapshot()), /sp-traffic-dot sp-traffic-download/);
  assert.equal(calls.length, 1);
});

test("malformed and oversized history is rejected atomically without erasing live samples", async () => {
  for (const response of [null, [], {[DOWN]: "rows"}, {[DOWN]: [null]}, {[DOWN]: [{s: "5", lu: "123"}]},
    {[DOWN]: [row(END + 1)]}, {[DOWN]: [row(END - TRAFFIC_HISTORY_WINDOW_MS - 1)]},
    {[DOWN]: Array.from({length: 4097}, () => row(END))},
    {[DOWN]: [row(END - 5000, "888")], [UP]: "invalid"}]) {
    const {controller} = setup(response);
    await controller.open({...SCOPE, states: states(END)});
    assert.equal(controller.snapshot().historyStatus, "unavailable");
    assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [12]);
  }
});

test("unknown and unavailable samples create real gaps, not zero-valued lines", async () => {
  const {controller} = setup({[DOWN]: [row(END - 90000, "10"), row(END - 60000, "unknown"),
    row(END - 30000, "20"), row(END - 15000, "unavailable")], [UP]: []});
  await controller.open({...SCOPE, states: states(END, "30")});
  assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [10, null, 20, null, 30]);
  const output = renderTrafficHistory(controller.snapshot());
  assert.equal((output.match(/class="sp-traffic-line sp-traffic-download"/g) ?? []).length, 3);
  assert.equal((output.match(/class="sp-traffic-dot sp-traffic-download"/g) ?? []).length, 3);
});

test("missing current entity invalidates the headline and breaks the next segment", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END)});
  setTime(END + 10000);
  controller.update({...SCOPE, states: {[UP]: current(END + 10000, "1")}});
  assert.equal(controller.snapshot().series.download.current, null);
  setTime(END + 20000);
  controller.update({...SCOPE, states: states(END + 20000)});
  assert.equal(controller.snapshot().series.download.points.at(-1).breakBefore, true);
});

test("unchanged HA state objects never grow a flat line to now", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END)});
  setTime(END + 60000);
  controller.update({...SCOPE, states: states(END)});
  const points = controller.snapshot().series.download.points;
  assert.equal(points.length, 1);
  assert.equal(points[0].time, END);
  assert.match(renderTrafficHistory(controller.snapshot()), /d="M694\.13,/);
  assert.doesNotMatch(renderTrafficHistory(controller.snapshot()), /d="M[^\"]+ L/);
  setTime(END + 120001);
  assert.equal(controller.snapshot().series.download.current, null);
  assert.equal(controller.snapshot().series.download.stale, true);
});

test("explicit stale source never ingests cached samples and recovery breaks the line", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END)});
  setTime(END + 10000);
  controller.update({...SCOPE, states: states(END + 10000, "999"), stale: true});
  assert.equal(controller.snapshot().series.download.current, null);
  assert.equal(controller.snapshot().series.download.points.length, 1);
  setTime(END + 20000);
  controller.update({...SCOPE, states: states(END + 20000, "20"), stale: false});
  assert.equal(controller.snapshot().series.download.points.at(-1).breakBefore, true);
  assert.equal(controller.snapshot().series.download.current, 20);
});

test("unchanged zero rates use only the successful WAN observation clock", async () => {
  const {controller, setTime} = setup();
  const same = states(END - 600000, "0", "0");
  await controller.open({...SCOPE, states: same, sampledAt: iso(END)});
  assert.equal(controller.snapshot().series.download.current, 0);
  assert.equal(controller.snapshot().series.download.points.at(-1).time, END);
  setTime(END + 10000);
  controller.update({...SCOPE, states: same, sampledAt: iso(END + 10000)});
  assert.deepEqual(controller.snapshot().series.download.points.map(({time, value}) => [time, value]), [[END, 0], [END + 10000, 0]]);
  setTime(END + 20000);
  controller.update({...SCOPE, states: same, sampledAt: iso(END + 10000)});
  assert.equal(controller.snapshot().series.download.points.length, 2);
  setTime(END + 200000);
  controller.update({...SCOPE, states: same, sampledAt: iso(END + 10000)});
  assert.equal(controller.snapshot().series.download.current, null);
  assert.equal(controller.snapshot().series.download.points.length, 2);
});

test("successful clock accepts numeric milliseconds but never revives unavailable or stale values", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END - 60000, "unavailable"), sampledAt: END});
  assert.equal(controller.snapshot().series.download.current, null);
  assert.equal(controller.snapshot().series.download.points[0].value, null);
  assert.equal(controller.snapshot().series.upload.points[0].time, END);
  setTime(END + 10000);
  controller.update({...SCOPE, states: states(END, "99"), sampledAt: END + 10000, stale: true});
  assert.equal(controller.snapshot().series.download.points.length, 1);
  assert.equal(controller.snapshot().series.download.current, null);
});

test("future, invalid, and older WAN observation clocks cannot advance a state", async () => {
  const {controller} = setup();
  await controller.open({...SCOPE, states: states(END)});
  for (const sampledAt of [iso(END + 1), "invalid", iso(END - 1000), true, null, Infinity])
    controller.update({...SCOPE, states: states(END), sampledAt});
  assert.deepEqual(controller.snapshot().series.download.points.map(({time}) => time), [END]);
});

test("long unobserved intervals break lines even when history contains no unavailable state", async () => {
  const {controller} = setup({[DOWN]: [row(END - 600000), row(END - 500000), row(END - 200000)], [UP]: []});
  await controller.open({...SCOPE, states: states(END)});
  const output = renderTrafficHistory(controller.snapshot());
  assert.equal((output.match(/class="sp-traffic-line sp-traffic-download"/g) ?? []).length, 3);
});

test("live out-of-order, future, and unparseable timestamps never create fabricated samples", async () => {
  const {controller} = setup();
  await controller.open({...SCOPE, states: states(END)});
  controller.update({...SCOPE, states: states(END - 5000, "99")});
  assert.equal(controller.snapshot().series.download.current, 12);
  controller.update({...SCOPE, states: states(END + 1, "100")});
  controller.update({...SCOPE, states: {[DOWN]: {state: "999", attributes: {unit_of_measurement: "Mbit/s"}}}});
  assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [12]);
  assert.equal(controller.snapshot().series.download.current, null);
});

test("points stay bounded, preserve actual subsecond timestamps, and expire after15min", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END)});
  for (let index = 1; index <= 10000; index++) {
    const time = END + index * 125;
    setTime(time); controller.update({...SCOPE, states: states(time, String(index))});
  }
  const view = controller.snapshot();
  assert.ok(view.series.download.points.length <= TRAFFIC_HISTORY_MAX_POINTS);
  assert.ok(view.series.download.points.every(({time}) => time >= view.start && time <= view.end));
  assert.equal(view.series.download.points.at(-1).time, END + 1250000);
  assert.equal(view.series.download.points.at(-1).value, 10000);
  setTime(view.end + TRAFFIC_HISTORY_WINDOW_MS + 1);
  assert.equal(controller.snapshot().series.download.points.length, 0);
});

test("subsecond bucketing cannot erase an unknown interval", async () => {
  const {controller} = setup({[DOWN]: [row(END - 2000, "1"), row(END - 1800, "unknown"),
    row(END - 1500, "2")], [UP]: []});
  await controller.open({...SCOPE, states: states(END)});
  const points = controller.snapshot().series.download.points;
  assert.equal(points[0].value, 2);
  assert.equal(points[0].time, END - 1500);
  assert.equal(points[0].breakBefore, true);
});

test("router or user switch clears samples and ignores a previous in-flight response", async () => {
  for (const replacement of [{...SCOPE, entryId: "entry-b"}, {...SCOPE, userId: "user-b"}]) {
    const first = deferred();
    let requests = 0;
    const controller = createTrafficHistoryController({request: () => ++requests === 1 ? first.promise : Promise.resolve({}), now: () => END});
    const loading = controller.open({...SCOPE, states: states(END, "111")});
    await controller.open({...replacement, states: states(END, "222")});
    first.resolve({[DOWN]: [row(END - 5000, "999")], [UP]: []});
    assert.equal(await loading, false);
    assert.equal(controller.update({...SCOPE, states: states(END, "888")}), false);
    assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [222]);
    assert.equal(requests, 2);
  }
});

test("close and dispose ignore late success or failure without extra notifications", async () => {
  for (const method of ["close", "dispose"]) for (const fail of [false, true]) {
    const gate = deferred();
    let changed = 0;
    const controller = createTrafficHistoryController({request: () => gate.promise, now: () => END, onChange: () => { changed++; }});
    const loading = controller.open({...SCOPE, states: states(END)});
    controller[method]();
    const notifications = changed;
    if (fail) gate.reject(new Error("secret")); else gate.resolve({[DOWN]: [row(END)]});
    assert.equal(await loading, false);
    assert.equal(controller.snapshot(), null);
    assert.equal(changed, notifications);
    assert.equal(controller.update({...SCOPE, states: states(END)}), false);
  }
});

test("reentering a closed view fetches once anew; invalid scopes clear without a request", async () => {
  const {controller, calls} = setup();
  await controller.open({...SCOPE, states: states(END)});
  controller.close();
  await controller.open({...SCOPE, states: states(END)});
  assert.equal(calls.length, 2);
  for (const value of [{...SCOPE, userId: ""}, {...SCOPE, entryId: null}, {...SCOPE, entities: {download: "light.other"}},
    {...SCOPE, entities: {download: DOWN, upload: DOWN}}, {...SCOPE, entities: {download: "sensor.<script>"}}]) {
    assert.throws(() => controller.open(value), /invalid_history_scope/);
    assert.equal(controller.snapshot(), null);
  }
  assert.equal(calls.length, 2);
});

test("missing entity metadata cannot broaden the request to global history", async () => {
  const {controller, calls} = setup();
  await controller.open({...SCOPE, entities: {download: null, upload: null}});
  assert.equal(calls.length, 0);
  assert.equal(controller.snapshot().historyStatus, "empty");
  await controller.open({...SCOPE, entities: {download: DOWN, upload: null}, states: states(END)});
  assert.deepEqual(calls[0].entity_ids, [DOWN]);
});

test("snapshots contain no raw state attributes and cannot mutate controller state", async () => {
  const raw = states(END);
  raw[DOWN].attributes.private_value = "PRIVATE-RAW-ATTRIBUTE";
  const {controller} = setup({[DOWN]: [row(END - 1000, "10", "Mbit/s", {private_value: "PRIVATE-RAW-HISTORY"})]});
  await controller.open({...SCOPE, states: raw});
  const view = controller.snapshot();
  view.series.download.points[0].value = 999;
  view.series.download.points.push({time: END, value: 999});
  raw[DOWN].state = "999";
  assert.deepEqual(controller.snapshot().series.download.points.map(({value}) => value), [10, 12]);
  assert.doesNotMatch(JSON.stringify(controller.snapshot()), /PRIVATE-RAW/);
});

test("renderer escapes labels, rejects malformed points, and renders accessible bounded SVG", async () => {
  const {controller} = setup({[DOWN]: [row(END - 10000, "12"), row(END - 5000, "13")], [UP]: []});
  await controller.open({...SCOPE, states: states(END)});
  const view = controller.snapshot();
  view.series.download.points.push({time: END, value: '<script>alert(1)</script>'});
  const output = renderTrafficHistory(view, {title: '<img src=x onerror="alert(1)">', downloadLabel: '<svg/onload=alert(1)>', uploadLabel: "A&B"});
  assert.doesNotMatch(output, /<img|<script|<svg\/onload|NaN|Infinity|PRIVATE-RAW/);
  assert.match(output, /&lt;img/);
  assert.match(output, /A&amp;B/);
  assert.match(output, /role="img" aria-label=/);
  assert.match(output, /class="sp-traffic-line sp-traffic-download" d="M/);
  assert.match(output, /Last 15 minutes/);
  assert.match(TRAFFIC_HISTORY_STYLES, /stroke-dasharray/);
  assert.match(TRAFFIC_HISTORY_STYLES, /max-width:480px/);
});

test("German renderer uses localized messages and decimal format", async () => {
  const {controller} = setup();
  await controller.open({...SCOPE, states: states(END, "12.5")});
  const output = renderTrafficHistory(controller.snapshot(), {language: "de-DE"});
  assert.match(output, /WAN-Datenverkehr/);
  assert.match(output, /12,5/);
  assert.match(output, /Keine gespeicherten Änderungen/);
  assert.match(output, /Jetzt/);
});

test("full-width plot uses bounded height without stretching axis labels", async () => {
  const {controller} = setup({[DOWN]: [row(END - 90000, "10")], [UP]: []});
  await controller.open({...SCOPE, states: states(END, "20", "5")});
  const output = renderTrafficHistory(controller.snapshot());
  const svg = output.match(/<svg\b[^>]*>[\s\S]*?<\/svg>/)?.[0];
  assert.ok(svg);
  assert.match(svg, /viewBox="52 26 688 148" preserveAspectRatio="none"/);
  assert.doesNotMatch(svg, /<text\b|15 min ago|Now<|22<\/span>/);
  assert.match(output, /class="sp-traffic-y-axis"[^>]*><span>22<\/span><span>11<\/span><span>0<\/span>/);
  assert.match(output, /class="sp-traffic-x-axis"[^>]*><span>15 min ago<\/span><span>Now<\/span>/);
  assert.match(svg, /x1="52" x2="740" y1="174.00" y2="174.00"/);
  assert.match(svg, /x1="52" x2="740" y1="26.00" y2="26.00"/);
  assert.match(TRAFFIC_HISTORY_STYLES, /grid-template-columns:auto minmax\(0,1fr\)/);
  assert.match(TRAFFIC_HISTORY_STYLES, /grid-template-rows:220px auto/);
  assert.match(TRAFFIC_HISTORY_STYLES, /grid-template-rows:180px auto/);
  assert.doesNotMatch(TRAFFIC_HISTORY_STYLES, /max-height:260px|height:auto/);
});

test("stale threshold is bounded and a zero numeric observation stays visible", async () => {
  const {controller, setTime} = setup();
  await controller.open({...SCOPE, states: states(END, "0"), staleAfterMs: 99999999});
  assert.equal(controller.snapshot().staleAfterMs, 300000);
  assert.equal(controller.snapshot().series.download.current, 0);
  setTime(END + 300001);
  assert.equal(controller.snapshot().series.download.current, null);
  controller.update({...SCOPE, states: states(END + 300001), staleAfterMs: -1});
  assert.equal(controller.snapshot().staleAfterMs, 5000);
});

test("invalid renderer snapshots stay empty", () => {
  for (const view of [null, {}, {start: "1", end: END}, {start: END, end: END}, {start: -Infinity, end: END}])
    assert.equal(renderTrafficHistory(view), "");
  assert.throws(() => createTrafficHistoryController({}), /invalid_history_controller/);
});

function inspectionFixture(initial) {
  let view = initial;
  const listeners = new Map();
  let dom;
  const host = {
    addEventListener(name, handler) { listeners.set(name, handler); },
    removeEventListener(name, handler) { if (listeners.get(name) === handler) listeners.delete(name); },
    querySelector(selector) { return ({"[data-traffic-plot]": dom.plot, "[data-traffic-tooltip]": dom.tooltip, "[data-traffic-crosshair]": dom.line})[selector]; },
  };
  const replaceDOM = () => {
    const tooltip = {hidden: true, textContent: "", style: {}, attributes: {}, setAttribute(name, value) { this.attributes[name] = value; }};
    Object.defineProperty(tooltip, "innerHTML", {set() { throw new Error("tooltip_html_forbidden"); }});
    const line = {hidden: true, style: {}};
    const plot = {dataset: {trafficLanguage: "en", trafficDownload: "Download", trafficUpload: "Upload"}, focused: false,
      contains(target) { return target === this || target === dom.svg; },
      getBoundingClientRect() { return {left: 40, width: 900}; },
      setPointerCapture(id) { this.capture = id; }, releasePointerCapture(id) { this.released = id; this.capture = null; },
      focus() {
        if (this.focused) return;
        this.focused = true; listeners.get("focusin")?.({target: this});
      },
    };
    dom = {plot, tooltip, line, svg: {}};
    return dom;
  };
  replaceDOM();
  const bind = bindTrafficHistory(host, () => view);
  return {host, bind, listeners, dom: () => dom, replaceDOM, view: () => view, setView: (value) => { view = value; },
    event(name, options = {}) {
      const event = {target: dom.plot, pointerType: "mouse", pointerId: 1, clientX: 490, prevented: false,
        preventDefault() { this.prevented = true; }, ...options};
      listeners.get(name)?.(event); return event;
    },
    at(time, name = "pointermove", options = {}) {
      return this.event(name, {clientX: 40 + (time - view.start) / TRAFFIC_HISTORY_WINDOW_MS * 900, ...options});
    },
  };
}
const inspectionView = (down, up = []) => ({entryId: "entry-a", userId: "user-a", start: END - TRAFFIC_HISTORY_WINDOW_MS,
  end: END, staleAfterMs: 120000, series: {download: {points: down}, upload: {points: up}}});
const point = (time, value, breakBefore = false) => ({time, value, breakBefore});

test("inspection hooks are keyboard-focusable and labels remain escaped", async () => {
  const {controller} = setup();
  await controller.open({...SCOPE, states: states(END)});
  const markup = renderTrafficHistory(controller.snapshot(), {downloadLabel: '<img src=x onerror="alert(1)">'});
  assert.match(markup, /data-traffic-plot[^>]*tabindex="0" role="group"/);
  assert.match(markup, /data-traffic-download="&lt;img/);
  assert.match(markup, /aria-describedby="sp-traffic-inspection"/);
  assert.match(markup, /data-traffic-tooltip role="status" aria-live="off" aria-atomic="true" hidden/);
  assert.match(markup, /data-traffic-crosshair aria-hidden="true" hidden/);
  assert.match(markup, /Arrow keys/);
  assert.match(TRAFFIC_HISTORY_STYLES, /touch-action:pan-y/);
});

test("hover reports formatted observed speeds and exact timestamps instead of interpolated values", () => {
  const time = END - 30000;
  const fixture = inspectionFixture(inspectionView([point(time, 10.123456789), point(END, 30)],
    [point(time, 0), point(END, 8)]));
  fixture.at(time + 10000);
  const {tooltip, line} = fixture.dom();
  assert.equal(tooltip.hidden, false);
  assert.match(tooltip.textContent, /Download: 10.123 Mbit\/s/);
  assert.match(tooltip.textContent, /Upload: 0 Mbit\/s/);
  assert.equal(tooltip.attributes["aria-live"], "off");
  const date = new Intl.DateTimeFormat("en", {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
    minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3, hourCycle: "h23", timeZoneName: "short"}).format(time);
  assert.ok(tooltip.textContent.includes(date));
  assert.equal(tooltip.textContent.split(date).length - 1, 1);
  assert.doesNotMatch(tooltip.textContent.split("\n").slice(1).join("\n"), / · /);
  assert.ok(Math.abs(parseFloat(line.style.left) - 96.66666666666667) < 1e-8);
  assert.doesNotMatch(tooltip.textContent, /16\.66|2\.66/);
});

test("different direction observation times are both disclosed, never silently synchronized", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 30000, 1), point(END, 2)],
    [point(END - 25000, 3), point(END, 4)]));
  fixture.at(END - 24000);
  const lines = fixture.dom().tooltip.textContent.split("\n");
  assert.match(lines[1], /Download: 1 Mbit\/s/);
  assert.match(lines[2], /Upload: 3 Mbit\/s/);
  assert.ok(lines[1].includes(" · "));
  assert.ok(!lines[2].includes(" · "));
});

test("tooltip keeps bounded intrinsic width at left, right and mobile chart edges", () => {
  const tooltipCSS = TRAFFIC_HISTORY_STYLES.match(/\.sp-traffic-tooltip\{([^}]+)\}/)[1];
  assert.match(tooltipCSS, /(?:^|;)width:max-content(?:;|$)/);
  assert.match(tooltipCSS, /max-width:min\(360px,100%\)/);
  // For the actual left/translation values set by the binding, intrinsic width
  // capped to the plot gives x = ratio * (plotWidth - tooltipWidth), including End.
  for (const plotWidth of [240, 320, 640, 1200]) for (const ratio of [0, 0.5, 0.97, 1]) {
    const time = END - TRAFFIC_HISTORY_WINDOW_MS + ratio * TRAFFIC_HISTORY_WINDOW_MS;
    const fixture = inspectionFixture(inspectionView([point(time, 12.345)]));
    fixture.dom().plot.getBoundingClientRect = () => ({left: 40, width: plotWidth});
    fixture.event("pointermove", {clientX: 40 + ratio * plotWidth});
    if (ratio === 1) fixture.event("keydown", {key: "End"});
    const {style} = fixture.dom().tooltip;
    const tooltipWidth = Math.min(330, 360, plotWidth);
    const translate = Number(style.transform.match(/translateX\(-([\d.]+)%\)/)[1]) / 100;
    const left = parseFloat(style.left) / 100 * plotWidth - translate * tooltipWidth;
    assert.ok(tooltipWidth >= Math.min(330, plotWidth));
    assert.ok(left >= -1e-8, `${plotWidth}px, ${ratio}: left overflow`);
    assert.ok(left + tooltipWidth <= plotWidth + 1e-8, `${plotWidth}px, ${ratio}: right overflow`);
  }
});

test("tooltip precision stays readable without rounding small nonzero traffic to zero", () => {
  for (const [value, display] of [[12.345678901234, "12.346"], [0, "0"], [0.00100001, "0.001"],
    [0.000123456, "0.000123"], [0.00000000000123456, "0.00000000000123"]]) {
    const fixture = inspectionFixture(inspectionView([point(END, value)]));
    fixture.at(END);
    assert.equal(fixture.dom().tooltip.textContent.split("\n")[1], `Download: ${display} Mbit/s`);
  }
});

test("hover inside unavailable or long unobserved gaps never reaches across them", () => {
  for (const down of [[point(END - 180000, 1), point(END - 120000, null), point(END - 30000, 3)],
    [point(END - 240000, 1), point(END - 30000, 3)],
    [point(END - 100000, 1), point(END - 30000, 3, true)]]) {
    const fixture = inspectionFixture(inspectionView(down));
    fixture.at(END - 70000);
    assert.match(fixture.dom().tooltip.textContent, /Download: No sample/);
    assert.match(fixture.dom().tooltip.textContent, /Upload: No sample/);
    assert.doesNotMatch(fixture.dom().tooltip.textContent, /Mbit\/s/);
    assert.equal(fixture.dom().line.hidden, false);
  }
});

test("a lone actual point is selectable near its marker without turning distant gaps into values", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 10000, 5)]));
  fixture.at(END - 12000);
  assert.match(fixture.dom().tooltip.textContent, /Download: 5 Mbit\/s/);
  fixture.at(END - 70000);
  assert.match(fixture.dom().tooltip.textContent, /Download: No sample/);
});

test("overlapping sparse marker hit areas select the nearest actual observation", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 10000, 1), point(END - 5000, 2, true)]));
  fixture.at(END - 4000);
  assert.match(fixture.dom().tooltip.textContent, /Download: 2 Mbit\/s/);
});

test("pointer inspection is bounded to the plot and leaves outside events untouched", () => {
  const fixture = inspectionFixture(inspectionView([point(END, 7)]));
  fixture.event("pointermove", {target: {}, clientX: 940});
  assert.equal(fixture.dom().tooltip.hidden, true);
  fixture.event("pointermove", {clientX: Infinity});
  assert.equal(fixture.dom().tooltip.hidden, true);
  fixture.dom().plot.getBoundingClientRect = () => ({left: 40, width: 0});
  fixture.event("pointermove");
  assert.equal(fixture.dom().tooltip.hidden, true);
  fixture.dom().plot.getBoundingClientRect = () => ({left: 40, width: 900});
  fixture.at(END, "pointermove", {target: fixture.dom().svg});
  assert.equal(fixture.dom().tooltip.hidden, false);
  fixture.event("pointerout", {relatedTarget: fixture.dom().svg});
  assert.equal(fixture.dom().tooltip.hidden, false);
  fixture.event("pointerout", {relatedTarget: {}});
  assert.equal(fixture.dom().tooltip.hidden, true);
});

test("touch tap and drag retain selected values and release pointer capture", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 30000, 1), point(END, 2)]));
  fixture.at(END - 30000, "pointerdown", {pointerType: "touch", pointerId: 7});
  assert.equal(fixture.dom().plot.capture, 7);
  assert.match(fixture.dom().tooltip.textContent, /Download: 1 Mbit\/s/);
  fixture.at(END, "pointermove", {pointerType: "touch", pointerId: 99});
  assert.match(fixture.dom().tooltip.textContent, /Download: 1 Mbit\/s/);
  fixture.at(END, "pointermove", {pointerType: "touch", pointerId: 7});
  assert.match(fixture.dom().tooltip.textContent, /Download: 2 Mbit\/s/);
  fixture.event("pointerup", {pointerType: "touch", pointerId: 7});
  assert.equal(fixture.dom().plot.released, 7);
  fixture.event("pointerout", {pointerType: "touch", relatedTarget: {}});
  assert.equal(fixture.dom().tooltip.hidden, false);
  fixture.event("pointercancel", {pointerType: "touch", pointerId: 7});
  assert.equal(fixture.dom().tooltip.hidden, true);
});

test("keyboard navigation visits actual times, handles boundaries and Escape", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 60000, 1), point(END, 3)], [point(END - 30000, 2)]));
  fixture.event("focusin");
  assert.match(fixture.dom().tooltip.textContent, /Download: 3 Mbit\/s/);
  const first = fixture.event("keydown", {key: "Home"});
  assert.equal(first.prevented, true);
  assert.match(fixture.dom().tooltip.textContent, /Download: 1 Mbit\/s/);
  fixture.event("keydown", {key: "ArrowLeft"});
  assert.match(fixture.dom().tooltip.textContent, /Download: 1 Mbit\/s/);
  fixture.event("keydown", {key: "ArrowRight"});
  assert.match(fixture.dom().tooltip.textContent, /Upload: 2 Mbit\/s/);
  assert.equal(fixture.dom().tooltip.attributes["aria-live"], "polite");
  fixture.event("keydown", {key: "End"});
  fixture.event("keydown", {key: "ArrowRight"});
  assert.match(fixture.dom().tooltip.textContent, /Download: 3 Mbit\/s/);
  fixture.event("keydown", {key: "ArrowLeft"});
  assert.match(fixture.dom().tooltip.textContent, /Upload: 2 Mbit\/s/);
  assert.equal(fixture.event("keydown", {key: "Tab"}).prevented, false);
  fixture.event("keydown", {key: "Escape"});
  assert.equal(fixture.dom().tooltip.hidden, true);
  assert.equal(fixture.dom().tooltip.textContent, "");
  assert.equal(fixture.dom().line.hidden, true);
});

test("all-gap series stays honest on pointer inspection and keyboard focus", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 10000, null)]));
  fixture.event("focusin");
  fixture.event("keydown", {key: "End"});
  assert.equal(fixture.dom().tooltip.hidden, true);
  fixture.at(END - 10000);
  assert.match(fixture.dom().tooltip.textContent, /Download: No sample/);
});

test("refresh preserves selected absolute time across WAN rerenders and restores keyboard focus", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 30000, 1), point(END, 2)]));
  fixture.event("focusin"); fixture.event("keydown", {key: "Home"});
  const before = fixture.dom().tooltip.textContent;
  const moved = {...fixture.view(), start: fixture.view().start + 10000, end: END + 10000};
  fixture.setView(moved); fixture.replaceDOM(); fixture.bind.refresh();
  assert.equal(fixture.dom().plot.focused, true);
  assert.equal(fixture.dom().tooltip.textContent, before);
  assert.ok(Math.abs(parseFloat(fixture.dom().line.style.left) - 95.55555555555556) < 1e-8);
});

test("refresh retains a hover marker hit area without inventing a newer observation", () => {
  const fixture = inspectionFixture(inspectionView([point(END - 10000, 5)]));
  fixture.at(END - 12000);
  const before = fixture.dom().tooltip.textContent;
  fixture.replaceDOM(); fixture.bind.refresh();
  assert.equal(fixture.dom().tooltip.textContent, before);
  assert.equal(fixture.dom().plot.focused, false);
});

test("WAN plot replacement releases detached touch or pen capture and permits a new drag", () => {
  for (const pointerType of ["touch", "pen"]) {
    const fixture = inspectionFixture(inspectionView([point(END - 30000, 1), point(END, 2)]));
    fixture.at(END - 30000, "pointerdown", {pointerType, pointerId: 7});
    const old = fixture.dom();
    const selected = old.tooltip.textContent;
    assert.equal(old.plot.capture, 7);
    fixture.replaceDOM(); fixture.bind.refresh();
    assert.equal(old.plot.released, 7);
    assert.equal(fixture.dom().tooltip.textContent, selected);
    fixture.at(END, "pointermove", {pointerType, pointerId: 9});
    assert.match(fixture.dom().tooltip.textContent, /Download: 2 Mbit\/s/);
    fixture.at(END, "pointerdown", {pointerType, pointerId: 9});
    assert.equal(fixture.dom().plot.capture, 9);
    fixture.event("pointercancel", {pointerType, pointerId: 9});
    assert.equal(fixture.dom().plot.released, 9);
    assert.equal(fixture.dom().tooltip.hidden, true);
    fixture.bind();
    assert.equal(fixture.listeners.size, 0);
  }
});

test("refresh leaves capture on an unchanged plot until cleanup releases it", () => {
  const fixture = inspectionFixture(inspectionView([point(END, 2)]));
  fixture.at(END, "pointerdown", {pointerType: "touch", pointerId: 7});
  fixture.bind.refresh();
  assert.equal(fixture.dom().plot.capture, 7);
  assert.equal(fixture.dom().plot.released, undefined);
  fixture.bind();
  assert.equal(fixture.dom().plot.released, 7);
});

test("scope change, disposed controller, expired selection and getter failure clear inspection", () => {
  for (const change of [(view) => ({...view, entryId: "entry-b"}), (view) => ({...view, userId: "user-b"}), () => null,
    (view) => ({...view, start: view.start + TRAFFIC_HISTORY_WINDOW_MS + 1, end: view.end + TRAFFIC_HISTORY_WINDOW_MS + 1})]) {
    const fixture = inspectionFixture(inspectionView([point(END - 10000, 5)]));
    fixture.at(END - 10000);
    fixture.setView(change(fixture.view())); fixture.bind.refresh();
    assert.equal(fixture.dom().tooltip.hidden, true);
    assert.equal(fixture.dom().tooltip.textContent, "");
    assert.equal(fixture.dom().line.hidden, true);
  }
  const fixture = inspectionFixture(inspectionView([point(END, 5)]));
  fixture.bind();
  let fail = false;
  const replacement = bindTrafficHistory(fixture.host, () => { if (fail) throw new Error("PRIVATE"); return fixture.view(); });
  fixture.at(END); fail = true; replacement.refresh();
  assert.equal(fixture.dom().tooltip.textContent, "");
  replacement();
});

test("cleanup removes every listener, releases capture and makes refresh inert", () => {
  const fixture = inspectionFixture(inspectionView([point(END, 5)]));
  fixture.at(END, "pointerdown", {pointerType: "touch", pointerId: 3});
  assert.equal(fixture.listeners.size, 8);
  fixture.bind(); fixture.bind();
  assert.equal(fixture.listeners.size, 0);
  assert.equal(fixture.dom().plot.released, 3);
  assert.equal(fixture.dom().tooltip.textContent, "");
  fixture.bind.refresh(); fixture.at(END);
  assert.equal(fixture.dom().tooltip.hidden, true);
});

test("tooltip uses textContent for hostile labels and localizes formatted values", () => {
  const fixture = inspectionFixture(inspectionView([point(END, 1.234567)]));
  fixture.dom().plot.dataset.trafficLanguage = "de";
  fixture.dom().plot.dataset.trafficDownload = '<img src=x onerror="alert(1)">';
  fixture.at(END);
  assert.match(fixture.dom().tooltip.textContent, /<img src=x onerror="alert\(1\)">: 1,235 Mbit\/s/);
  assert.match(fixture.dom().tooltip.textContent, /Upload: Kein Messwert/);
  assert.match(fixture.dom().tooltip.textContent, /Beobachtete Messwerte/);
});

test("binder accepts a controller and performs no history query on any interaction", async () => {
  const {controller, calls} = setup();
  await controller.open({...SCOPE, states: states(END)});
  const fixture = inspectionFixture(controller.snapshot());
  fixture.bind();
  const cleanup = bindTrafficHistory(fixture.host, controller);
  fixture.at(END); fixture.event("focusin"); fixture.event("keydown", {key: "Home"}); cleanup.refresh(); cleanup();
  assert.equal(calls.length, 1);
  assert.throws(() => bindTrafficHistory({}, controller), /invalid_history_binding/);
  assert.throws(() => bindTrafficHistory(fixture.host, {}), /invalid_history_binding/);
});
