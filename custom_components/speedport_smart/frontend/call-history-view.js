/** Private call-list view. Reads require controller calls; no persistent state. */
const CATEGORIES = Object.freeze({dialed: "Dialed calls", missed: "Missed calls", taken: "Answered calls"});
const PAGE_CATEGORIES = Object.freeze({dialed: "Dialed outgoing calls", missed: "Missed calls", taken: "Received calls"});
const MAX_ROWS = 1000;
const MAX_CSV = 4200000;
const MESSAGES = Object.freeze({
  ready: "Choose a category, then load it explicitly. Call records stay only in this private view.",
  loading: "Loading this private call list…",
  loaded: "Complete selected call list loaded. Closing or changing the view clears these records.",
  exporting: "Reading the selected list for a local CSV download…",
  exported: "Private CSV download prepared. Keep the downloaded file secure.",
  unavailable: "This call list could not be read completely. Missing data is not an empty list. No automatic retry occurs.",
});
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);
const categoryValid = (value) => typeof value === "string" && Object.hasOwn(CATEGORIES, value);
const textValid = (value) => typeof value === "string" && value.length <= 512 && !/[\x00-\x1f\x7f]/.test(value);

function projectRecords(result, category) {
  if (!result || result.category !== category || !Array.isArray(result.entries) ||
      result.entries.length > MAX_ROWS || !Number.isInteger(result.total) ||
      result.total !== result.entries.length) throw new Error("invalid_response");
  return result.entries.map((row) => {
    if (!row || !["date", "time", "remote_party", "local_party"].every((key) => textValid(row[key])) ||
        !row.date || !row.time) throw new Error("invalid_response");
    const record = {date: row.date, time: row.time, remote_party: row.remote_party, local_party: row.local_party};
    if (category !== "missed") {
      if (!Number.isInteger(row.duration_seconds) || row.duration_seconds < 0 ||
          row.duration_seconds > 2147483647) throw new Error("invalid_response");
      record.duration_seconds = row.duration_seconds;
    }
    return Object.freeze(record);
  });
}

function browserDownload({filename, media_type, content}) {
  const url = URL.createObjectURL(new Blob([content], {type: media_type}));
  const anchor = document.createElement("a");
  try {
    anchor.href = url; anchor.download = filename;
    document.body.append(anchor); anchor.click();
  } finally {
    anchor.remove(); URL.revokeObjectURL(url);
  }
}

export function createCallHistoryViewController({request, onChange = () => {}, download = browserDownload}) {
  if (typeof request !== "function" || typeof download !== "function") throw new TypeError("request_required");
  let state = null;
  let records = [];
  let generation = 0;
  const clear = () => { generation++; records = []; state = null; };
  async function query(exporting) {
    if (!state || state.busy) return false;
    const epoch = generation;
    const {entryId, category} = state;
    records = []; state.total = null; state.busy = true;
    state.status = exporting ? "exporting" : "loading"; onChange();
    try {
      const response = await request({type: "speedport_smart/panel/call_history",
        entry_id: entryId, category, export: exporting});
      if (epoch !== generation) return false;
      if (response?.schema_version !== 1 || response.query !== "call_history" ||
          response.result?.category !== category) throw new Error("invalid_response");
      if (exporting) {
        const value = response.result.private_download;
        if (!value || value.filename !== `Speedport-${category}-calls.csv` ||
            value.media_type !== "text/csv;charset=utf-8" || typeof value.content !== "string" ||
            !value.content || value.content.length > MAX_CSV) throw new Error("invalid_response");
        const payload = {filename: value.filename, media_type: value.media_type, content: value.content};
        try { await download(payload); }
        finally { payload.content = ""; }
        if (epoch !== generation) return false;
        state.status = "exported";
      } else {
        records = projectRecords(response.result, category);
        state.total = records.length; state.status = "loaded";
      }
      return true;
    } catch {
      if (epoch !== generation) return false;
      records = []; state.total = null; state.status = "unavailable"; return false;
    } finally {
      if (epoch === generation) { state.busy = false; onChange(); }
    }
  }
  return {
    open({entryId, category = "taken"}) {
      clear();
      if (typeof entryId !== "string" || !entryId || entryId.length > 64 || !categoryValid(category))
        throw new Error("invalid_view");
      state = {entryId, category, status: "ready", busy: false, total: null}; onChange();
    },
    close() { clear(); onChange(); },
    dispose() { clear(); },
    snapshot() { return state ? {...state} : null; },
    // Records are supplied only to the private renderer, never the panel snapshot.
    entries() { return records.map((row) => ({...row})); },
    setCategory(category) {
      if (!state || !categoryValid(category)) return false;
      generation++; records = [];
      state = {...state, category, status: "ready", busy: false, total: null}; onChange(); return true;
    },
    load() { return query(false); },
    exportCsv() { return query(true); },
  };
}

export function renderCallHistoryView(controller, {pageMode = false} = {}) {
  const view = controller.snapshot();
  if (!view) return "";
  const categoryTitle = (pageMode ? PAGE_CATEGORIES : CATEGORIES)[view.category];
  const options = Object.entries(CATEGORIES).map(([value, label]) =>
    `<option value="${value}"${value === view.category ? " selected" : ""}>${label}</option>`).join("");
  const duration = view.category !== "missed";
  const rows = controller.entries().map((row) => `<tr><td>${escape(row.date)}</td><td>${escape(row.time)}</td>` +
    `<td>${escape(row.remote_party)}</td><td>${escape(row.local_party)}</td>` +
    (duration ? `<td>${row.duration_seconds}</td>` : "") + "</tr>").join("");
  const table = view.status === "loaded" ? `<div class="sp-call-history-table" data-call-history-private><p>${view.total} calls</p>` +
    `<table><caption>${categoryTitle}</caption><thead><tr><th scope="col">Date</th><th scope="col">Time</th>` +
    `<th scope="col">Caller / destination</th><th scope="col">Local line</th>${duration ? '<th scope="col">Duration (seconds)</th>' : ""}` +
    `</tr></thead><tbody>${rows}</tbody></table></div>` : "";
  return `<style>
    .sp-call-history{box-sizing:border-box;padding:20px;border:1px solid var(--divider-color);border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);overflow-wrap:anywhere}
    .sp-call-history h3{margin-top:0}.sp-call-history-actions{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.sp-call-history select,.sp-call-history button{padding:10px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color)}.sp-call-history :disabled{opacity:.55}.sp-call-history :focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}
    .sp-call-history-table{overflow-x:auto}.sp-call-history table{width:100%;border-collapse:collapse}.sp-call-history th,.sp-call-history td{text-align:left;padding:8px;border-bottom:1px solid var(--divider-color)}.sp-call-history caption{text-align:left;font-weight:600;padding:8px}
    </style><section class="sp-call-history" aria-labelledby="sp-call-history-title" aria-busy="${view.busy}"><h3 id="sp-call-history-title">${pageMode ? categoryTitle : "Private call history"}</h3>
    <p>${pageMode ? "Opening this page reads its private call list automatically. Records stay only in this private view and never enter Recorder history. Downloads happen only when you choose Download fresh CSV; the file stays on your device." : "Records and exports are private. Nothing loads automatically or enters recorder history. A downloaded CSV remains on your device."}</p>
    ${pageMode ? "" : `<label for="sp-call-history-category">Call category</label><select id="sp-call-history-category" data-call-history-category>${options}</select>`}
    <p role="status" aria-live="polite">${pageMode && view.status === "ready" ? "This page reads its private call list on entry. Use Refresh to read it again." : MESSAGES[view.status] ?? MESSAGES.unavailable}</p>
    <div class="sp-call-history-actions"><button type="button" data-call-history-action="load"${view.busy ? " disabled" : ""}>${pageMode ? "Refresh" : "Load private list"}</button><button type="button" data-call-history-action="export"${view.busy ? " disabled" : ""}>Download fresh CSV</button><button type="button" data-call-history-action="close">Close and clear</button></div>${table}</section>`;
}

export function bindCallHistoryView(root, controller) {
  const clearDOM = () => {
    for (const node of root.querySelectorAll("[data-call-history-private]")) node.replaceChildren();
  };
  const onChange = (event) => {
    const target = event.target;
    if (!target || !root.contains(target) || !target.hasAttribute?.("data-call-history-category")) return;
    clearDOM(); controller.setCategory(target.value);
  };
  const onClick = (event) => {
    const target = event.target?.closest?.("[data-call-history-action]");
    if (!target || !root.contains(target) || target.disabled) return;
    event.preventDefault();
    const action = target.getAttribute("data-call-history-action");
    clearDOM();
    if (action === "close") controller.close();
    else if (action === "load") void controller.load();
    else if (action === "export") void controller.exportCsv();
  };
  root.addEventListener("change", onChange); root.addEventListener("click", onClick);
  return () => {
    clearDOM(); controller.dispose(); root.removeEventListener("change", onChange); root.removeEventListener("click", onClick);
  };
}
