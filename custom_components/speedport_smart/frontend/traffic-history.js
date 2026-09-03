/** Read-only, in-memory WAN history. No recorder configuration or subscriptions.
 * HA's history/history_during_period returns entity-keyed compact {s,a,lu,lc}:
 * https://github.com/home-assistant/core/blob/dev/homeassistant/components/history/websocket_api.py
 * https://github.com/home-assistant/frontend/blob/dev/src/data/history.ts
 * Keep attributes in this two-entity query so historical unit changes stay honest.
 */
export const TRAFFIC_HISTORY_WINDOW_MS = 15 * 60 * 1000;
export const TRAFFIC_HISTORY_WINDOWS_MINUTES = Object.freeze([5, 15, 30, 60]);
export const TRAFFIC_HISTORY_MAX_POINTS = 1024;
// HA and the browser use independent clocks. Tolerate a small live-only lead
// without rewriting observation times or accepting future Recorder history.
export const LIVE_TRAFFIC_CLOCK_SKEW_MS = 5000;
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
const windowValid = (value) => TRAFFIC_HISTORY_WINDOWS_MINUTES.includes(value);
const windowDuration = (view) => windowValid((view?.end - view?.start) / 60000) ? view.end - view.start : null;

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

function sample(row, start, end, sampledAt, futureTolerance = 0) {
  let time = timestamp(row);
  // HA does not emit a new state for an unchanged rate. The caller may provide
  // the integration's successful WAN sample clock, never a render-time clock.
  const observed = typeof sampledAt === "string" ? Date.parse(sampledAt) : sampledAt;
  if (Number.isFinite(time) && Number.isFinite(observed) && observed >= time && observed <= end + futureTolerance) time = observed;
  if (!Number.isFinite(time) || time < start || time > end + futureTolerance) return null;
  const compact = Object.hasOwn(row, "s");
  const attributes = compact ? row.a : row.attributes;
  return {time, value: trafficRateMbit(compact ? row.s : row.state, attributes?.unit_of_measurement), breakBefore: false};
}

// Retain actual observations across the whole window, never just its tail.
// Longer windows use wider buckets; values and timestamps are never averaged.
// Unknown observations inside a bucket must still break the next line segment.
function bounded(points, start, end) {
  const buckets = new Map();
  const width = Math.max(1000, Math.ceil((end - start) / (TRAFFIC_HISTORY_MAX_POINTS - 1) / 1000) * 1000);
  for (const point of points.sort((a, b) => a.time - b.time)) {
    // Retain slightly ahead live samples until the plot's clock catches up.
    // The plot and hover window still end at the browser's actual current time.
    if (point.time < start || point.time > end + LIVE_TRAFFIC_CLOCK_SKEW_MS) continue;
    const key = Math.floor(point.time / width);
    const previous = buckets.get(key);
    buckets.set(key, {...point, breakBefore: point.breakBefore || previous?.breakBefore || previous?.value === null});
  }
  return [...buckets.values()].slice(-TRAFFIC_HISTORY_MAX_POINTS);
}

/** open() reads once per scope. Explicit timeframe changes read history once.
 * update() never performs I/O. close() clears it all.
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
    for (const key of SERIES) points[key] = bounded(points[key], end - state.windowMinutes * 60000, end);
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
      const next = row ? sample(row, end - state.windowMinutes * 60000, end, value.sampledAt, LIVE_TRAFFIC_CLOCK_SKEW_MS) : null;
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
    const start = end - state.windowMinutes * 60000;
    if (!ids.length) { state.historyStatus = "empty"; onChange(); return false; }
    try {
      const response = await request({type: "history/history_during_period",
        start_time: new Date(start).toISOString(), end_time: new Date(end).toISOString(),
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
          const point = sample(row, start, end);
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
        windowMinutes: 15, historyStatus: "loading", stale: false, staleAfterMs: DEFAULT_STALE_MS};
      update(value, false); onChange();
      pending = load(epoch, now());
      return pending;
    },
    setWindowMinutes(minutes) {
      if (!state || !windowValid(minutes)) return Promise.resolve(false);
      if (state.windowMinutes === minutes) return pending ?? Promise.resolve(true);
      epoch++;
      state.windowMinutes = minutes;
      state.historyStatus = "loading";
      // The latest live observation remains useful while history reloads. Do
      // not carry downsampled historical buckets into a different resolution.
      for (const key of SERIES) points[key] = live[key] ? [{...live[key], breakBefore: breaks[key]}] : [];
      prune(now());
      onChange();
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
          current.time <= end + LIVE_TRAFFIC_CLOCK_SKEW_MS && end - current.time <= state.staleAfterMs;
        series[key] = {entityId: state.entities[key], points: points[key].map((point) => ({...point})),
          current: fresh ? current.value : null, stale: !fresh,
          lastSampleAt: current?.time ?? points[key].at(-1)?.time ?? null};
      }
      return {entryId: state.entryId, userId: state.userId, windowMinutes: state.windowMinutes,
        start: end - state.windowMinutes * 60000, end,
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
    stale: "No recent sample", latest: "Latest sample", window: (minutes) => `Last ${minutes} minutes`, ago: (minutes) => `${minutes} min ago`, now: "Now", timeframe: "Traffic history timeframe",
    inspect: "Hover or touch to inspect samples. Arrow keys move between samples; Home and End jump; Escape clears.",
    sample: "Observed samples", missing: "No sample", selected: "Selected time", moreInfo: "Open entity details"},
  de: {title: "WAN-Datenverkehr", download: "Download", upload: "Upload", loading: "Gespeicherter Verlauf wird geladen…",
    ready: "Gespeicherte Änderungen und beobachtete Messwerte. Lücken bedeuten nicht null Datenverkehr.", empty: "Keine gespeicherten Änderungen in diesem Zeitraum. Neue Messwerte werden gesammelt.",
    unavailable: "Verlauf nicht verfügbar. Nur in dieser Ansicht empfangene Messwerte werden angezeigt.", waiting: "Warten auf nutzbare Messwerte.",
    stale: "Kein aktueller Messwert", latest: "Letzter Messwert", window: (minutes) => `Letzte ${minutes} Minuten`, ago: (minutes) => `Vor ${minutes} Min.`, now: "Jetzt", timeframe: "Zeitraum des Datenverkehrs",
    inspect: "Mit Maus oder Berührung Messwerte prüfen. Pfeiltasten wechseln Messwerte; Pos1 und Ende springen; Escape schließt.",
    sample: "Beobachtete Messwerte", missing: "Kein Messwert", selected: "Gewählter Zeitpunkt", moreInfo: "Entitätsdetails öffnen"},
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
  const duration = windowDuration(snapshot);
  if (!snapshot || !Number.isFinite(snapshot.start) || !Number.isFinite(snapshot.end) ||
      !duration) return "";
  const minutes = duration / 60000;
  const words = LABELS[language?.toLowerCase().startsWith("de") ? "de" : "en"];
  const format = new Intl.NumberFormat(language?.toLowerCase().startsWith("de") ? "de" : "en", {maximumFractionDigits: 2});
  const labels = {download: downloadLabel ?? words.download, upload: uploadLabel ?? words.upload};
  const staleAfterMs = Number.isFinite(snapshot.staleAfterMs) ? Math.max(5000, Math.min(300000, snapshot.staleAfterMs)) : DEFAULT_STALE_MS;
  const segments = Object.fromEntries(SERIES.map((key) => [key, chartSegments(snapshot.series?.[key], snapshot.start, snapshot.end, staleAfterMs)]));
  let maximum = 1;
  for (const key of SERIES) for (const segment of segments[key]) for (const point of segment) maximum = Math.max(maximum, point.value);
  const ceiling = Math.ceil(maximum * 1.1 * 100) / 100;
  const x = (time) => 52 + (time - snapshot.start) / duration * 688;
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
    const entityId = snapshot.series?.[key]?.entityId;
    const tag = entityValid(entityId) ? "button" : "div";
    const readout = available ? format.format(value) : "—";
    const description = available ? `${readout} Mbit/s. ${words.latest}` : words.stale;
    const attributes = tag === "button" ? ` type="button" class="sp-traffic-metric sp-traffic-${key}" data-more-info="${escape(entityId)}" aria-label="${escape(`${labels[key]}: ${description}. ${words.moreInfo}`)}"` :
      ` class="sp-traffic-metric sp-traffic-${key}"`;
    return `<${tag}${attributes}><span>${escape(labels[key])}</span><strong>${escape(readout)} <small>Mbit/s</small></strong><small>${available ? words.latest : words.stale}</small></${tag}>`;
  }).join("");
  const grid = [0, 0.5, 1].map((fraction) => `<line x1="52" x2="740" y1="${fixed(y(ceiling * fraction))}" y2="${fixed(y(ceiling * fraction))}"/>`).join("");
  const axis = [1, 0.5, 0].map((fraction) => `<span>${escape(format.format(ceiling * fraction))}</span>`).join("");
  const options = TRAFFIC_HISTORY_WINDOWS_MINUTES.map((value) => `<option value="${value}"${value === minutes ? " selected" : ""}>${words.window(value)}</option>`).join("");
  return `<section class="sp-traffic-history"><header><h2>${escape(title ?? words.title)}</h2><select class="sp-traffic-window" data-traffic-window aria-label="${words.timeframe}">${options}</select></header><div class="sp-traffic-metrics">${legends}</div>` +
    `<div class="sp-traffic-chart"><div class="sp-traffic-y-axis" aria-hidden="true">${axis}</div>` +
    `<div class="sp-traffic-plot" data-traffic-plot data-traffic-language="${language?.toLowerCase().startsWith("de") ? "de" : "en"}" data-traffic-download="${escape(labels.download)}" data-traffic-upload="${escape(labels.upload)}" tabindex="0" role="group" aria-label="${escape(`${title ?? words.title}. ${words.inspect}`)}" aria-describedby="sp-traffic-inspection">` +
    `<svg viewBox="52 26 688 148" preserveAspectRatio="none" role="img" aria-label="${escape(`${title ?? words.title}: ${labels.download}, ${labels.upload}. ${words.window(minutes)}. Mbit/s.`)}"><g class="sp-traffic-grid">${grid}</g>${paths}</svg>` +
    `<div class="sp-traffic-crosshair" data-traffic-crosshair aria-hidden="true" hidden></div><div id="sp-traffic-inspection" class="sp-traffic-tooltip" data-traffic-tooltip role="status" aria-live="off" aria-atomic="true" hidden></div></div>` +
    `<div class="sp-traffic-x-axis" aria-hidden="true"><span>${words.ago(minutes)}</span><span>${words.now}</span></div></div>` +
    `<p class="sp-traffic-note">${words[snapshot.historyStatus] ?? words.unavailable}${paths ? "" : ` ${words.waiting}`}</p></section>`;
}

function inspectionSegments(view) {
  if (!view || !Number.isFinite(view.start) || !Number.isFinite(view.end) ||
      !windowDuration(view)) return null;
  const gap = Number.isFinite(view.staleAfterMs) ? Math.max(5000, Math.min(300000, view.staleAfterMs)) : DEFAULT_STALE_MS;
  return Object.fromEntries(SERIES.map((key) => [key, chartSegments(view.series?.[key], view.start, view.end, gap)]));
}

/** Refresh live graph content without detaching the native timeframe select.
 * The caller owns scope validation and refreshes the inspection binding after
 * replacing the plot. No event binding, focus changes or I/O occurs here.
 */
export function refreshTrafficHistoryContent(host, snapshot, options) {
  if (!host?.ownerDocument?.createElement) return false;
  const markup = renderTrafficHistory(snapshot, options);
  if (!markup) return false;
  const template = host.ownerDocument.createElement("template");
  template.innerHTML = markup;
  const replacements = [".sp-traffic-metrics", ".sp-traffic-chart", ".sp-traffic-note"]
    .map((selector) => [host.querySelector(selector), template.content.querySelector(selector)]);
  if (replacements.some(([current, next]) => !current?.replaceWith || !next)) return false;
  for (const [current, next] of replacements) current.replaceWith(next);
  return true;
}

function nearestSample(segments, time, tolerance) {
  // Intervals broken by unavailable or unobserved data are never searched across.
  // A lone point is still selectable within a small pointer hit area.
  const segment = segments.find((points) => time >= points[0].time && time <= points.at(-1).time);
  const candidates = segment ?? segments.filter((points) => points.length === 1 &&
    Math.abs(points[0].time - time) <= tolerance).map((points) => points[0]);
  return candidates.reduce((best, point) => !best || Math.abs(point.time - time) < Math.abs(best.time - time) ? point : best, null);
}

/** Bind inspection and explicit timeframe selection. Only selection reads HA
 * history once; no router requests, writes, timers or persistent data.
 * Keep this host stable across renders, then call cleanup.refresh() after updating
 * its markup. Selection is an absolute timestamp, never an extrapolated value.
 */
export function bindTrafficHistory(host, controllerOrSnapshotGetter) {
  const getSnapshot = typeof controllerOrSnapshotGetter === "function" ? controllerOrSnapshotGetter :
    typeof controllerOrSnapshotGetter?.snapshot === "function" ? () => controllerOrSnapshotGetter.snapshot() : null;
  if (!host?.addEventListener || !host?.removeEventListener || !getSnapshot) throw new TypeError("invalid_history_binding");
  let disposed = false;
  let selectedTime = null;
  let selectionTolerance = 0;
  let scope = null;
  let keyboard = false;
  let captured = null;
  const nodes = () => ({plot: host.querySelector("[data-traffic-plot]"),
    tooltip: host.querySelector("[data-traffic-tooltip]"), line: host.querySelector("[data-traffic-crosshair]")});
  const release = () => {
    if (captured) {
      try { captured.plot.releasePointerCapture?.(captured.id); } catch { /* The browser may already have cancelled it. */ }
      captured = null;
    }
  };
  const hide = () => {
    const {tooltip, line} = nodes();
    if (tooltip) { tooltip.hidden = true; tooltip.textContent = ""; }
    if (line) line.hidden = true;
  };
  const clear = () => { selectedTime = null; selectionTolerance = 0; keyboard = false; release(); hide(); };
  function context() {
    if (disposed) return null;
    let view;
    try { view = getSnapshot(); } catch { clear(); return null; }
    const segments = inspectionSegments(view);
    if (!segments) { scope = null; clear(); return null; }
    const nextScope = JSON.stringify([view.entryId, view.userId, windowDuration(view)]);
    if (scope !== nextScope) { clear(); scope = nextScope; }
    return {view, segments};
  }
  function show(value) {
    const {plot, tooltip, line} = nodes();
    if (!plot || !tooltip || !line || selectedTime === null) return;
    const {view, segments} = value;
    if (selectedTime < view.start || selectedTime > view.end) { clear(); return; }
    const samples = Object.fromEntries(SERIES.map((key) => [key, nearestSample(segments[key], selectedTime, selectionTolerance)]));
    const language = plot.dataset.trafficLanguage === "de" ? "de" : "en";
    const words = LABELS[language];
    const number = new Intl.NumberFormat(language, {maximumFractionDigits: 3});
    const smallNumber = new Intl.NumberFormat(language, {maximumSignificantDigits: 3});
    const time = new Intl.DateTimeFormat(language, {year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3, hourCycle: "h23", timeZoneName: "short"});
    const chosen = SERIES.map((key) => samples[key]).filter(Boolean)
      .sort((a, b) => Math.abs(a.time - selectedTime) - Math.abs(b.time - selectedTime))[0];
    const position = chosen?.time ?? selectedTime;
    const ratio = (position - view.start) / (view.end - view.start) * 100;
    line.style.left = `${ratio}%`; line.hidden = false;
    tooltip.style.left = `${ratio}%`;
    tooltip.style.transform = `translateX(-${ratio}%)`;
    tooltip.setAttribute("aria-live", keyboard ? "polite" : "off");
    const labels = {download: plot.dataset.trafficDownload || words.download, upload: plot.dataset.trafficUpload || words.upload};
    // textContent is intentional: labels and state-derived text never become HTML.
    tooltip.textContent = `${chosen ? words.sample : words.selected}: ${time.format(position)}\n` + SERIES.map((key) => {
      const point = samples[key];
      if (!point) return `${labels[key]}: ${words.missing}`;
      const value = point.value > 0 && point.value < 0.001 ? smallNumber.format(point.value) : number.format(point.value);
      return `${labels[key]}: ${value} Mbit/s${point.time === position ? "" : ` · ${time.format(point.time)}`}`;
    }).join("\n");
    tooltip.hidden = false;
  }
  const inside = (plot, target) => Boolean(plot && (plot === target || plot.contains(target)));
  function pointer(event) {
    const value = context();
    const {plot} = nodes();
    if (!value || !inside(plot, event.target) || !Number.isFinite(event.clientX)) return;
    if (captured && captured.id !== event.pointerId) return;
    const rect = plot.getBoundingClientRect();
    if (!Number.isFinite(rect.width) || rect.width <= 0) return;
    const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const duration = value.view.end - value.view.start;
    selectedTime = value.view.start + fraction * duration;
    selectionTolerance = Math.min(15000, duration / rect.width * 6);
    keyboard = false;
    show(value);
  }
  function pointerDown(event) {
    const {plot} = nodes();
    if (!inside(plot, event.target) || !context()) return;
    plot.focus?.({preventScroll: true});
    if (event.pointerType === "touch" || event.pointerType === "pen") {
      try { plot.setPointerCapture?.(event.pointerId); captured = {plot, id: event.pointerId}; } catch { /* Inspection still works without capture. */ }
    }
    pointer(event);
  }
  function pointerUp(event) { if (captured?.id === event.pointerId) release(); }
  function pointerOut(event) {
    const {plot} = nodes();
    if (inside(plot, event.target) && !inside(plot, event.relatedTarget) &&
        event.pointerType !== "touch" && event.pointerType !== "pen" && !captured && !keyboard) clear();
  }
  function focus(event) {
    const value = context();
    const {plot} = nodes();
    if (!value || !inside(plot, event.target)) return;
    keyboard = true;
    const times = Object.values(value.segments).flat(2).map((point) => point.time);
    if (selectedTime === null && times.length) selectedTime = Math.max(...times);
    selectionTolerance = 0;
    show(value);
  }
  function blur(event) {
    const {plot} = nodes();
    if (inside(plot, event.target) && !inside(plot, event.relatedTarget)) clear();
  }
  function keydown(event) {
    const {plot} = nodes();
    if (!inside(plot, event.target) || !["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") { clear(); return; }
    const value = context();
    if (!value) return;
    const times = [...new Set(Object.values(value.segments).flat(2).map((point) => point.time))].sort((a, b) => a - b);
    if (!times.length) { clear(); return; }
    if (event.key === "Home") selectedTime = times[0];
    else if (event.key === "End" || selectedTime === null) selectedTime = times.at(-1);
    else if (event.key === "ArrowLeft") selectedTime = times.findLast((time) => time < selectedTime) ?? times[0];
    else selectedTime = times.find((time) => time > selectedTime) ?? times.at(-1);
    keyboard = true; selectionTolerance = 0; show(value);
  }
  function changeWindow(event) {
    if (disposed || !event.target || event.target !== host.querySelector("[data-traffic-window]") || !context() ||
        typeof controllerOrSnapshotGetter?.setWindowMinutes !== "function") return;
    const minutes = Number(event.target.value);
    if (!windowValid(minutes) || String(minutes) !== event.target.value) return;
    clear();
    // A rejected history read is handled by the controller, never retried here.
    void controllerOrSnapshotGetter.setWindowMinutes(minutes);
  }
  const listeners = {pointermove: pointer, pointerdown: pointerDown, pointerup: pointerUp,
    pointercancel: clear, pointerout: pointerOut, focusin: focus, focusout: blur, keydown, change: changeWindow};
  for (const [name, handler] of Object.entries(listeners)) host.addEventListener(name, handler);
  const cleanup = () => {
    if (disposed) return;
    disposed = true; clear(); scope = null;
    for (const [name, handler] of Object.entries(listeners)) host.removeEventListener(name, handler);
  };
  cleanup.refresh = () => {
    const value = context();
    if (!value) return;
    // WAN renders replace the inner plot. Its detached capture cannot deliver a
    // later pointerup here and must not block the next touch or pen pointer ID.
    if (captured && captured.plot !== nodes().plot) release();
    if (keyboard && selectedTime !== null) nodes().plot?.focus?.({preventScroll: true});
    show(value);
  };
  return cleanup;
}

export const TRAFFIC_HISTORY_STYLES = `
  .sp-traffic-history{padding:22px;border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,16px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);min-width:0}
  .sp-traffic-history header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.sp-traffic-history h2{font-size:18px;margin:0}.sp-traffic-history header>span,.sp-traffic-note{color:var(--secondary-text-color,#666);font-size:12px}
  .sp-traffic-window{max-width:100%;min-height:40px;padding:8px 30px 8px 12px;border:1px solid var(--divider-color,#ddd);border-radius:8px;background:var(--secondary-background-color,#f5f5f5);color:var(--primary-text-color,#222);font:inherit;font-size:13px}.sp-traffic-window:focus-visible{outline:2px solid var(--primary-color,#e20074);outline-offset:2px}
  .sp-traffic-metrics{display:flex;gap:40px;margin:20px 0 10px;flex-wrap:wrap}.sp-traffic-metric{display:grid;gap:6px;flex:1 1 140px;min-width:0;text-align:start;padding:8px 0;border:0;border-radius:6px;background:none;font:inherit}.sp-traffic-metric>span{font-size:16px;font-weight:600;line-height:1.4}.sp-traffic-metric strong{font-size:clamp(28px,2.6vw,36px);font-weight:600;line-height:1.2;letter-spacing:-.025em;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.sp-traffic-metric small{font-size:12px;font-weight:400;color:var(--secondary-text-color,#666)}.sp-traffic-metric strong small{font-size:clamp(13px,1.2vw,16px);letter-spacing:normal}.sp-traffic-metric[data-more-info]{cursor:pointer}.sp-traffic-metric[data-more-info]:hover{background:var(--secondary-background-color,#0001)}.sp-traffic-metric:focus-visible{outline:2px solid var(--primary-color,#e20074);outline-offset:4px}
  .sp-traffic-download{color:var(--sp-magenta,#e20074);stroke:var(--sp-magenta,#e20074)}.sp-traffic-upload{color:var(--info-color,#039be5);stroke:var(--info-color,#039be5)}
  .sp-traffic-chart{display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:220px auto;gap:12px 10px;margin-top:22px}.sp-traffic-y-axis,.sp-traffic-x-axis{font-size:11px;line-height:1;color:var(--secondary-text-color,#666);font-variant-numeric:tabular-nums}.sp-traffic-y-axis{display:flex;flex-direction:column;justify-content:space-between;text-align:right}.sp-traffic-y-axis>span:first-child{transform:translateY(-50%)}.sp-traffic-y-axis>span:last-child{transform:translateY(50%)}.sp-traffic-x-axis{grid-column:2;display:flex;justify-content:space-between;gap:12px}
  .sp-traffic-plot{position:relative;min-width:0;touch-action:pan-y;outline-offset:5px}.sp-traffic-plot:focus-visible{outline:2px solid var(--sp-magenta,#e20074)}.sp-traffic-crosshair{position:absolute;top:0;bottom:0;border-left:1px dashed var(--primary-text-color,#222);pointer-events:none}.sp-traffic-tooltip{position:absolute;top:10px;z-index:1;width:max-content;max-width:min(360px,100%);box-sizing:border-box;padding:10px 12px;border:1px solid var(--divider-color,#ddd);border-radius:8px;background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);box-shadow:0 3px 12px #0002;font-size:12px;line-height:1.5;white-space:pre-line;overflow-wrap:anywhere;pointer-events:none}.sp-traffic-tooltip[hidden],.sp-traffic-crosshair[hidden]{display:none}
  .sp-traffic-history svg{display:block;width:100%;height:100%;min-width:0;overflow:visible}.sp-traffic-grid line{stroke:var(--divider-color,#ddd);stroke-width:1;vector-effect:non-scaling-stroke}.sp-traffic-line{fill:none;stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}.sp-traffic-line.sp-traffic-upload{stroke-dasharray:5 3}.sp-traffic-dot{fill:currentColor;stroke:none}.sp-traffic-note{line-height:1.5;margin:8px 0 0}
  @media(max-width:480px){.sp-traffic-history{padding:16px}.sp-traffic-metrics{gap:16px}.sp-traffic-chart{grid-template-rows:180px auto}.sp-traffic-y-axis,.sp-traffic-x-axis{font-size:12px}}
`;
