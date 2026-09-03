/** Read-only, in-memory WAN history. No recorder configuration or subscriptions.
 * HA's history/history_during_period returns entity-keyed compact {s,a,lu,lc}:
 * https://github.com/home-assistant/core/blob/dev/homeassistant/components/history/websocket_api.py
 * https://github.com/home-assistant/frontend/blob/dev/src/data/history.ts
 * Keep attributes in this two-entity query so historical unit changes stay honest.
 */
export const TRAFFIC_HISTORY_WINDOW_MS = 15 * 60 * 1000;
export const TRAFFIC_HISTORY_MAX_POINTS = 1024;
const MAX_HISTORY_ROWS = 4096;
const DEFAULT_STALE_MS = 120000;
const SERIES = ["download", "upload"];
const FACTORS = Object.freeze({
  "bit/s": 1e-6, bps: 1e-6, "kbit/s": 1e-3, kbps: 1e-3,
  "Mbit/s": 1, Mbps: 1, "Gbit/s": 1e3, Gbps: 1e3, "Tbit/s": 1e6,
  "B/s": 8e-6, "kB/s": 8e-3, "MB/s": 8, "GB/s": 8e3, "TB/s": 8e6,
});
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const entityValid = (value) => typeof value === "string" && value.length <= 255 && /^sensor\.[a-z0-9_]+$/.test(value);
const identityValid = (value) => typeof value === "string" && value.length > 0 && value.length <= 128;

export function trafficRateMbit(value, unit) {
  if (typeof unit !== "string" || !Object.hasOwn(FACTORS, unit) ||
      !["string", "number"].includes(typeof value)) return null;
  if (typeof value === "string" && (value.length > 64 ||
      !/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()))) return null;
  const result = Number(value) * FACTORS[unit];
  return Number.isFinite(result) && result >= 0 && result <= 1e9 ? result : null;
}

function timestamp(row) {
  if (!row || typeof row !== "object") return NaN;
  if (Object.hasOwn(row, "lu") || Object.hasOwn(row, "lc")) {
    const value = row.lu ?? row.lc;
    return typeof value === "number" && Number.isFinite(value) ? value * 1000 : NaN;
  }
  const value = row.last_updated ?? row.last_changed;
  return typeof value === "string" ? Date.parse(value) : NaN;
}

function sample(row, start, end, sampledAt) {
  let time = timestamp(row);
  // HA does not emit a new state for an unchanged rate. The caller may provide
  // the integration's successful WAN sample clock, never a render-time clock.
  const observed = typeof sampledAt === "string" ? Date.parse(sampledAt) : sampledAt;
  if (Number.isFinite(time) && Number.isFinite(observed) && observed >= time && observed <= end) time = observed;
  if (!Number.isFinite(time) || time < start || time > end) return null;
  const compact = Object.hasOwn(row, "s");
  const attributes = compact ? row.a : row.attributes;
  return {time, value: trafficRateMbit(compact ? row.s : row.state, attributes?.unit_of_measurement), breakBefore: false};
}

// At most one actual observation per second, keeping its original timestamp.
// Unknown observations inside a bucket must still break the next line segment.
function bounded(points, start, end) {
  const buckets = new Map();
  for (const point of points.sort((a, b) => a.time - b.time)) {
    if (point.time < start || point.time > end) continue;
    const key = Math.floor(point.time / 1000);
    const previous = buckets.get(key);
    buckets.set(key, {...point, breakBefore: point.breakBefore || previous?.breakBefore || previous?.value === null});
  }
  return [...buckets.values()].slice(-TRAFFIC_HISTORY_MAX_POINTS);
}

/** open() reads once per scope. update() never performs I/O. close() clears it all.
 * The caller must close on view exit/unload and include the current user and entry
 * in every update. Snapshot and notification callbacks never retain HA objects.
 */
export function createTrafficHistoryController({request, onChange = () => {}, now = Date.now}) {
  if (typeof request !== "function" || typeof onChange !== "function" || typeof now !== "function")
    throw new TypeError("invalid_history_controller");
  let state = null;
  let epoch = 0;
  let pending = null;
  let points = {download: [], upload: []};
  let live = {download: null, upload: null};
  let breaks = {download: false, upload: false};
  const clear = () => {
    epoch++; state = null; pending = null;
    points = {download: [], upload: []}; live = {download: null, upload: null};
    breaks = {download: false, upload: false};
  };
  const matches = (value) => state && value?.entryId === state.entryId && value?.userId === state.userId;
  const prune = (end) => {
    for (const key of SERIES) points[key] = bounded(points[key], end - TRAFFIC_HISTORY_WINDOW_MS, end);
  };
  function update(value, notify = true) {
    if (!matches(value)) return false;
    const end = now();
    state.stale = value.stale === true;
    if (Number.isFinite(value.staleAfterMs))
      state.staleAfterMs = Math.max(5000, Math.min(300000, value.staleAfterMs));
    for (const key of SERIES) {
      const id = state.entities[key];
      const row = id && value.states?.[id];
      const next = row ? sample(row, end - TRAFFIC_HISTORY_WINDOW_MS, end, value.sampledAt) : null;
      if (state.stale) { breaks[key] = true; continue; }
      if (!next) { live[key] = null; breaks[key] = true; continue; }
      if (live[key] && next.time < live[key].time) continue;
      const unchanged = live[key]?.time === next.time && live[key]?.value === next.value;
      live[key] = next;
      if (unchanged) continue;
      points[key].push({...next, breakBefore: breaks[key]});
      breaks[key] = next.value === null;
    }
    prune(end);
    if (notify) onChange();
    return true;
  }
  async function load(generation, end) {
    const ids = SERIES.map((key) => state.entities[key]).filter(Boolean);
    if (!ids.length) { state.historyStatus = "empty"; onChange(); return false; }
    try {
      const response = await request({type: "history/history_during_period",
        start_time: new Date(end - TRAFFIC_HISTORY_WINDOW_MS).toISOString(), end_time: new Date(end).toISOString(),
        entity_ids: ids, include_start_time_state: false, significant_changes_only: false,
        minimal_response: false, no_attributes: false});
      if (generation !== epoch) return false;
      if (!response || typeof response !== "object" || Array.isArray(response)) throw new Error("invalid_history");
      const incoming = {};
      let count = 0;
      for (const key of SERIES) {
        const id = state.entities[key];
        const rows = id && Object.hasOwn(response, id) ? response[id] : [];
        if (!Array.isArray(rows) || rows.length > MAX_HISTORY_ROWS) throw new Error("invalid_history");
        incoming[key] = [];
        for (const row of rows) {
          const point = sample(row, end - TRAFFIC_HISTORY_WINDOW_MS, end);
          if (!point) throw new Error("invalid_history");
          incoming[key].push(point);
          if (point.value !== null) count++;
        }
      }
      for (const key of SERIES) points[key] = [...incoming[key], ...points[key]];
      prune(now());
      state.historyStatus = count ? "ready" : "empty";
      return true;
    } catch {
      if (generation !== epoch) return false;
      state.historyStatus = "unavailable";
      return false;
    } finally {
      if (generation === epoch) { pending = null; onChange(); }
    }
  }
  return {
    open(value) {
      const entities = {download: value?.entities?.download ?? null, upload: value?.entities?.upload ?? null};
      if (!identityValid(value?.entryId) || !identityValid(value?.userId) ||
          SERIES.some((key) => entities[key] !== null && !entityValid(entities[key])) ||
          (entities.download && entities.download === entities.upload)) {
        clear(); onChange(); throw new Error("invalid_history_scope");
      }
      if (matches(value) && SERIES.every((key) => entities[key] === state.entities[key])) {
        update(value); return pending ?? Promise.resolve(true);
      }
      clear();
      state = {entryId: value.entryId, userId: value.userId, entities,
        historyStatus: "loading", stale: false, staleAfterMs: DEFAULT_STALE_MS};
      update(value, false); onChange();
      pending = load(epoch, now());
      return pending;
    },
    update,
    snapshot() {
      if (!state) return null;
      const end = now(); prune(end);
      const series = {};
      for (const key of SERIES) {
        const current = live[key];
        const fresh = !state.stale && current?.value !== null && current &&
          current.time <= end && end - current.time <= state.staleAfterMs;
        series[key] = {points: points[key].map((point) => ({...point})),
          current: fresh ? current.value : null, stale: !fresh,
          lastSampleAt: current?.time ?? points[key].at(-1)?.time ?? null};
      }
      return {entryId: state.entryId, userId: state.userId, start: end - TRAFFIC_HISTORY_WINDOW_MS, end,
        historyStatus: state.historyStatus, staleAfterMs: state.staleAfterMs, series};
    },
    close() { clear(); onChange(); },
    dispose() { clear(); },
  };
}

const LABELS = Object.freeze({
  en: {title: "WAN traffic", download: "Download", upload: "Upload", loading: "Loading recorded history…",
    ready: "Recorded changes and observed live samples. Gaps are not zero traffic.", empty: "No recorded changes in this window. Collecting live samples.",
    unavailable: "History unavailable. Showing only samples received in this view.", waiting: "Waiting for usable samples.",
    stale: "No recent sample", latest: "Latest sample", window: "Last 15 minutes", ago: "15 min ago", now: "Now"},
  de: {title: "WAN-Datenverkehr", download: "Download", upload: "Upload", loading: "Gespeicherter Verlauf wird geladen…",
    ready: "Gespeicherte Änderungen und beobachtete Messwerte. Lücken bedeuten nicht null Datenverkehr.", empty: "Keine gespeicherten Änderungen in diesem Zeitraum. Neue Messwerte werden gesammelt.",
    unavailable: "Verlauf nicht verfügbar. Nur in dieser Ansicht empfangene Messwerte werden angezeigt.", waiting: "Warten auf nutzbare Messwerte.",
    stale: "Kein aktueller Messwert", latest: "Letzter Messwert", window: "Letzte 15 Minuten", ago: "Vor 15 Min.", now: "Jetzt"},
});

function chartSegments(series, start, end, staleAfterMs) {
  const segments = [];
  let current = [];
  for (const point of (Array.isArray(series?.points) ? series.points : []).slice(-TRAFFIC_HISTORY_MAX_POINTS)) {
    if (!point || !Number.isFinite(point.time) || point.time < start || point.time > end ||
        !Number.isFinite(point.value) || point.value < 0 || point.value > 1e9) {
      if (current.length) segments.push(current);
      current = []; continue;
    }
    if (current.length && (point.breakBefore || point.time <= current.at(-1).time ||
        point.time - current.at(-1).time > staleAfterMs)) {
      segments.push(current); current = [];
    }
    current.push(point);
  }
  if (current.length) segments.push(current);
  return segments;
}

export function renderTrafficHistory(snapshot, {language = "en", title, downloadLabel, uploadLabel} = {}) {
  if (!snapshot || !Number.isFinite(snapshot.start) || !Number.isFinite(snapshot.end) ||
      snapshot.end - snapshot.start !== TRAFFIC_HISTORY_WINDOW_MS) return "";
  const words = LABELS[language?.toLowerCase().startsWith("de") ? "de" : "en"];
  const format = new Intl.NumberFormat(language?.toLowerCase().startsWith("de") ? "de" : "en", {maximumFractionDigits: 2});
  const labels = {download: downloadLabel ?? words.download, upload: uploadLabel ?? words.upload};
  const staleAfterMs = Number.isFinite(snapshot.staleAfterMs) ? Math.max(5000, Math.min(300000, snapshot.staleAfterMs)) : DEFAULT_STALE_MS;
  const segments = Object.fromEntries(SERIES.map((key) => [key, chartSegments(snapshot.series?.[key], snapshot.start, snapshot.end, staleAfterMs)]));
  let maximum = 1;
  for (const key of SERIES) for (const segment of segments[key]) for (const point of segment) maximum = Math.max(maximum, point.value);
  const ceiling = Math.ceil(maximum * 1.1 * 100) / 100;
  const x = (time) => 52 + (time - snapshot.start) / TRAFFIC_HISTORY_WINDOW_MS * 688;
  const y = (value) => 174 - value / ceiling * 148;
  const fixed = (value) => value.toFixed(2);
  const paths = SERIES.map((key) => segments[key].map((segment) =>
    `<path class="sp-traffic-line sp-traffic-${key}" d="${segment.map((point, index) => `${index ? "L" : "M"}${fixed(x(point.time))},${fixed(y(point.value))}`).join(" ")}"/>` +
    // Single samples are points, not a fabricated flat line across the window.
    (segment.length === 1 ? `<circle class="sp-traffic-dot sp-traffic-${key}" cx="${fixed(x(segment[0].time))}" cy="${fixed(y(segment[0].value))}" r="2.5"/>` : "")
  ).join("")).join("");
  const legends = SERIES.map((key) => {
    const value = snapshot.series?.[key]?.current;
    const available = Number.isFinite(value) && value >= 0 && value <= 1e9 && snapshot.series[key].stale === false;
    return `<div class="sp-traffic-metric sp-traffic-${key}"><span>${escape(labels[key])}</span><strong>${available ? escape(format.format(value)) : "—"} <small>Mbit/s</small></strong><small>${available ? words.latest : words.stale}</small></div>`;
  }).join("");
  const grid = [0, 0.5, 1].map((fraction) => `<line x1="52" x2="740" y1="${fixed(y(ceiling * fraction))}" y2="${fixed(y(ceiling * fraction))}"/>`).join("");
  const axis = [1, 0.5, 0].map((fraction) => `<span>${escape(format.format(ceiling * fraction))}</span>`).join("");
  return `<section class="sp-traffic-history"><header><h2>${escape(title ?? words.title)}</h2><span>${words.window}</span></header><div class="sp-traffic-metrics">${legends}</div>` +
    `<div class="sp-traffic-chart"><div class="sp-traffic-y-axis" aria-hidden="true">${axis}</div>` +
    `<svg viewBox="52 26 688 148" preserveAspectRatio="none" role="img" aria-label="${escape(`${title ?? words.title}: ${labels.download}, ${labels.upload}. ${words.window}. Mbit/s.`)}"><g class="sp-traffic-grid">${grid}</g>${paths}</svg>` +
    `<div class="sp-traffic-x-axis" aria-hidden="true"><span>${words.ago}</span><span>${words.now}</span></div></div>` +
    `<p class="sp-traffic-note">${words[snapshot.historyStatus] ?? words.unavailable}${paths ? "" : ` ${words.waiting}`}</p></section>`;
}

export const TRAFFIC_HISTORY_STYLES = `
  .sp-traffic-history{padding:22px;border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,16px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);min-width:0}
  .sp-traffic-history header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.sp-traffic-history h2{font-size:18px;margin:0}.sp-traffic-history header>span,.sp-traffic-note{color:var(--secondary-text-color,#666);font-size:12px}
  .sp-traffic-metrics{display:flex;gap:40px;margin:20px 0 10px;flex-wrap:wrap}.sp-traffic-metric{display:grid;gap:4px}.sp-traffic-metric>span{font-size:13px}.sp-traffic-metric strong{font-size:26px;line-height:1.15;font-variant-numeric:tabular-nums}.sp-traffic-metric small{font-size:11px;font-weight:400;color:var(--secondary-text-color,#666)}
  .sp-traffic-download{color:var(--sp-magenta,#e20074);stroke:var(--sp-magenta,#e20074)}.sp-traffic-upload{color:var(--info-color,#039be5);stroke:var(--info-color,#039be5)}
  .sp-traffic-chart{display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:220px auto;gap:12px 10px;margin-top:22px}.sp-traffic-y-axis,.sp-traffic-x-axis{font-size:11px;line-height:1;color:var(--secondary-text-color,#666);font-variant-numeric:tabular-nums}.sp-traffic-y-axis{display:flex;flex-direction:column;justify-content:space-between;text-align:right}.sp-traffic-y-axis>span:first-child{transform:translateY(-50%)}.sp-traffic-y-axis>span:last-child{transform:translateY(50%)}.sp-traffic-x-axis{grid-column:2;display:flex;justify-content:space-between;gap:12px}
  .sp-traffic-history svg{display:block;width:100%;height:100%;min-width:0;overflow:visible}.sp-traffic-grid line{stroke:var(--divider-color,#ddd);stroke-width:1;vector-effect:non-scaling-stroke}.sp-traffic-line{fill:none;stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}.sp-traffic-line.sp-traffic-upload{stroke-dasharray:5 3}.sp-traffic-dot{fill:currentColor;stroke:none}.sp-traffic-note{line-height:1.5;margin:8px 0 0}
  @media(max-width:480px){.sp-traffic-history{padding:16px}.sp-traffic-metrics{gap:26px}.sp-traffic-metric strong{font-size:22px}.sp-traffic-chart{grid-template-rows:180px auto}.sp-traffic-y-axis,.sp-traffic-x-axis{font-size:12px}}
`;
