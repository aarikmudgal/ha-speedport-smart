import assert from "node:assert/strict";
import test from "node:test";
import {
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
