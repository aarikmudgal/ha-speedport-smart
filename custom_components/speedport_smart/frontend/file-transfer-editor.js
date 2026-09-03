/** Explicit administrator file transfers. No router requests on open or selection. */
import {digestFile} from "./file-digest.js?schema=31";

const ACTIONS = new Set(["system_backup_download", "system_backup_restore", "system_firmware_upload", "system_mesh_firmware_upload",
  "system_log_download", "system_router_pass_download",
  ...Array.from({length:6}, (_, book) => [`phonebook_import_${book}`, `phonebook_export_${book}`]).flat()]);
const phonebookIndex = (id) => /^phonebook_(?:import|export)_[0-5]$/.test(id) ? Number(id.at(-1)) : null;
const IMPORT_REJECTIONS = Object.freeze({1:"No valid file was supplied.", 2:"The CSV format was rejected.", 3:"The phonebook has insufficient free space; an import may be partial.", 4:"The CSV columns were rejected.", 5:"The CSV column titles were rejected.", 6:"The CSV column contents were rejected.", 7:"The CSV values were rejected.", 8:"The router reported an import error."});
const importCounter = (value) => Number.isSafeInteger(value) && value >= 0 && value <= 2097152;
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
const MESSAGES = Object.freeze({
  idle: "Review the warning. No router operation starts until you confirm and execute.",
  hashing: "Checking the selected file locally…",
  preparing: "Checking authorization for this one-time transfer…",
  sending: "Transferring once. Do not disconnect power or repeat this action.",
  downloaded: "Backup downloaded. Keep it private; download alone does not prove restore compatibility.",
  phonebook_downloaded: "Private phonebook CSV downloaded. Keep it private. Its format and import compatibility have not been verified.",
  private_downloaded: "Private file downloaded. Keep it private: it may contain credentials, addresses, device names or telephone details.",
  import_accepted: "The router accepted the import. These are router-reported counters, not verification of each imported contact. Inspect the phonebook before repeating the import.",
  phonebook_empty: "This local phonebook is empty. No export was requested from the router.",
  phonebook_full: "This local phonebook has no free entries. No import was sent to the router.",
  phonebook_linked: "This phonebook is linked to an online account. The router does not expose local CSV import while it is linked. No import was sent.",
  processing: "The router reports processing. Check its status after recovery; installation or restoration is not yet verified.",
  reconnect_required: "Reconnect after the router recovers, then verify settings and versions. Completion has not been verified.",
  rejected: "The transfer was rejected. Review the file and router state before trying again.",
  failed: "The transfer could not be prepared. No router file transfer was started.",
  invalid: "Select a file within the stated size limit and type the confirmation exactly.",
  outcome_unknown: "The outcome could not be confirmed. Check the router before repeating anything. No automatic retry will occur.",
});

export function createFileTransferEditorController({request, download, onChange = () => {}, digest = digestFile}) {
  let state = null, epoch = 0, file = null, password = "", confirmation = "", busy = false;
  const clearPrivate = () => { file = null; password = ""; confirmation = ""; };
  const clear = () => { epoch++; clearPrivate(); state = null; busy = false; };
  const controller = {
    open({entryId, action}) {
      clear();
      if (typeof entryId !== "string" || !entryId || entryId.length > 128 || !ACTIONS.has(action?.id) ||
          action.execution_policy !== "file_transfer" || action.supported !== true || !["upload", "download"].includes(action.direction) ||
          typeof action.confirmation !== "string" || !action.confirmation.trim() ||
          !Number.isSafeInteger(action.maximum_bytes) || action.maximum_bytes < 1) throw new Error("invalid_transfer_schema");
      state = {entryId, action: Object.freeze({...action}), status: "idle", complete: false};
      onChange();
    },
    close() { if (busy) return false; clear(); onChange(); return true; },
    dispose() { clear(); },
    snapshot() { return state && {...state, busy, filename: file?.name ?? "", size: file?.size ?? 0}; },
    setFile(value) {
      if (!state || busy || state.complete || state.action.direction !== "upload") return false;
      file = value; return true;
    },
    setPassword(value) {
      if (!state || busy || state.complete || !state.action.password || typeof value !== "string") return false;
      password = value; return true;
    },
    setConfirmation(value) {
      if (!state || busy || state.complete || typeof value !== "string") return false;
      confirmation = value; return true;
    },
    clearSensitiveDrafts() { password = ""; confirmation = ""; },
    async execute() {
      if (!state || busy || state.complete) return false;
      const {action, entryId} = state;
      const upload = action.direction === "upload";
      if (confirmation !== action.confirmation || (upload && (!file || typeof file.name !== "string" ||
          !Number.isSafeInteger(file.size) || file.size < 1 || file.size > action.maximum_bytes))) {
        password = ""; confirmation = ""; state.status = "invalid"; onChange(); return false;
      }
      const generation = epoch;
      let submitted = false;
      let privatePassword = password;
      const selected = file;
      password = ""; confirmation = ""; busy = true;
      const current = () => generation === epoch;
      let body;
      try {
        let sha256 = null;
        if (upload) {
          state.status = "hashing"; onChange();
          sha256 = await digest(selected, current);
          if (!current()) return false;
          if (typeof sha256 !== "string" || !/^[a-f0-9]{64}$/.test(sha256)) throw new Error("invalid_digest");
        }
        state.status = "preparing"; onChange();
        const base = `/api/speedport_smart/file_transfer/${encodeURIComponent(entryId)}`;
        const prepared = await request(`${base}/prepare`, {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({
          action: action.id, size: upload ? selected.size : 0, sha256,
          confirmed: true, confirmation_text: action.confirmation,
        })});
        if (!current()) return false;
        if (!prepared.ok) { state.status = "failed"; return false; }
        const approval = await prepared.json();
        if (!current()) return false;
        if (approval.action !== action.id || typeof approval.grant !== "string" || !/^[a-f0-9]{48,128}$/.test(approval.grant) ||
            !Number.isFinite(approval.expires_in) || approval.expires_in <= 0) throw new Error("invalid_approval");
        body = new FormData();
        body.append("metadata", JSON.stringify({action: action.id, grant: approval.grant, password: privatePassword}));
        if (upload) body.append("file", selected, selected.name);
        privatePassword = "";
        state.status = "sending"; onChange(); submitted = true;
        const response = await request(`${base}/execute`, {method: "POST", body});
        if (!current()) return false;
        if (!response.ok) {
          const error = await response.json().catch(() => null);
          if (!current()) return false;
          state.status = phonebookIndex(action.id) !== null && ["phonebook_empty", "phonebook_full", "phonebook_linked"].includes(error?.error) ? error.error : "outcome_unknown";
          return false;
        }
        if (!upload) {
          if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/octet-stream")) throw new Error("invalid_download");
          const blob = await response.blob();
          if (!current()) return false;
          if (!blob.size || blob.size > action.maximum_bytes) throw new Error("invalid_download");
          const book = phonebookIndex(action.id);
          const localFile = {system_log_download:"speedport-system-log.txt", system_router_pass_download:"speedport-router-pass.txt"}[action.id];
          await download(blob, localFile ?? (book === null ? "speedport-configuration-backup.bin" : `speedport-phonebook-${book + 1}.csv`));
          if (!current()) return false;
          state.status = localFile ? "private_downloaded" : book === null ? "downloaded" : "phonebook_downloaded";
          return true;
        }
        const result = await response.json();
        if (!current()) return false;
        if (phonebookIndex(action.id) !== null && result.action === action.id && result.result?.status === "import_accepted") {
          const details = result.result;
          if (details.verification !== "contents_unverified" || details.router_status !== 0 ||
              !importCounter(details.reported_total) || !importCounter(details.reported_ignored) || details.reported_ignored > details.reported_total ||
              (details.reported_full !== undefined && !importCounter(details.reported_full))) throw new Error("invalid_import_result");
          state.counters = Object.freeze({total:details.reported_total, ignored:details.reported_ignored, ...(details.reported_full === undefined ? {} : {full:details.reported_full})});
          state.status = "import_accepted";
          return true;
        }
        if (phonebookIndex(action.id) !== null && result.action === action.id && result.result?.status === "rejected") {
          const details = result.result;
          if (!Number.isInteger(details.router_status) || !IMPORT_REJECTIONS[details.router_status]) throw new Error("invalid_import_result");
          state.rejection = IMPORT_REJECTIONS[details.router_status];
          if (details.reported_full !== undefined) {
            if (!importCounter(details.reported_full)) throw new Error("invalid_import_result");
            state.rejection += ` Router-reported full: ${details.reported_full}.`;
          }
        }
        state.status = result.action === action.id && ["processing", "reconnect_required", "rejected"].includes(result.result?.status) ? result.result.status : "outcome_unknown";
        return state.status === "processing" || state.status === "reconnect_required";
      } catch (_error) {
        if (current()) state.status = submitted ? "outcome_unknown" : "failed";
        return false;
      } finally {
        privatePassword = "";
        body?.delete("metadata"); body?.delete("file");
        if (current()) { clearPrivate(); busy = false; state.complete = true; onChange(); }
      }
    },
  };
  return controller;
}

export function renderFileTransferEditor(controller) {
  controller.clearSensitiveDrafts();
  const view = controller.snapshot();
  if (!view) return "";
  const disabled = view.busy || view.complete;
  const id = `sp-transfer-${view.action.id}`;
  return `<style>
    .sp-transfer{box-sizing:border-box;width:100%;padding:20px;border:1px solid var(--divider-color);border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);overflow-wrap:anywhere}
    .sp-transfer h3{margin-top:0}.sp-transfer-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:16px}.sp-transfer label{display:flex;flex-direction:column;gap:8px}.sp-transfer input{box-sizing:border-box;width:100%;padding:10px;border:1px solid var(--divider-color);border-radius:8px;color:var(--primary-text-color);background:var(--secondary-background-color)}
    .sp-transfer small{color:var(--secondary-text-color)}.sp-transfer-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}.sp-transfer button{padding:10px 16px;border:1px solid var(--divider-color);border-radius:8px;color:var(--primary-text-color);background:var(--secondary-background-color)}.sp-transfer :focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}.sp-transfer :disabled{opacity:.55}
    </style><section class="sp-transfer" aria-labelledby="${id}" aria-busy="${view.busy}">
    <h3 id="${id}">${escape(view.action.title)}</h3><p>${escape(view.action.warning)}</p>
    <p>${view.action.direction === "upload" ? "Live router changes remain untested. You are responsible for choosing a compatible file and verifying recovery." : "This operation only reads router data. Keep the downloaded file private."}</p>
    <p role="status" aria-live="polite">${escape(MESSAGES[view.status] ?? MESSAGES.outcome_unknown)}</p>
    ${view.rejection ? `<p>${escape(view.rejection)} Check the phonebook before repeating this action.</p>` : ""}
    ${view.counters ? `<p>Router-reported total: ${view.counters.total}. Ignored: ${view.counters.ignored}.${view.counters.full === undefined ? "" : ` Full: ${view.counters.full}.`} Imported contacts have not been individually verified.</p>` : ""}
    <div class="sp-transfer-fields">
    ${view.action.direction === "upload" ? `<label>File<input type="file" data-transfer-file${disabled ? " disabled" : ""}><small>Maximum ${(view.action.maximum_bytes / 1048576).toFixed(2)} MiB. File size and checksum do not prove compatibility.</small></label>` : ""}
    ${view.action.password ? `<label>${escape(view.action.password.label)}<input type="password" data-transfer-password autocomplete="new-password" maxlength="255"${disabled ? " disabled" : ""}></label>` : ""}
    <label>Type ${escape(view.action.confirmation)}<input type="text" data-transfer-confirmation autocomplete="off"${disabled ? " disabled" : ""}></label></div>
    <div class="sp-transfer-actions"><button type="button" data-transfer-action="execute"${disabled ? " disabled" : ""}>${view.action.direction === "upload" ? "Upload and execute once" : ["system_log_download","system_router_pass_download"].includes(view.action.id) ? "Download private file" : phonebookIndex(view.action.id) === null ? "Download backup" : "Download phonebook CSV"}</button><button type="button" data-transfer-action="close"${view.busy ? " disabled" : ""}>Close</button></div></section>`;
}

export function bindFileTransferEditor(root, controller) {
  const clearDOM = () => { for (const input of root.querySelectorAll("input")) input.value = ""; };
  const onInput = (event) => {
    const target = event.target;
    if (!target || !root.contains(target)) return;
    if (target.hasAttribute?.("data-transfer-file")) controller.setFile(target.files?.[0] ?? null);
    if (target.hasAttribute?.("data-transfer-password")) controller.setPassword(target.value);
    if (target.hasAttribute?.("data-transfer-confirmation")) controller.setConfirmation(target.value);
  };
  const onClick = (event) => {
    const button = event.target?.closest?.("[data-transfer-action]");
    if (!button || !root.contains(button) || button.disabled) return;
    event.preventDefault();
    if (button.getAttribute("data-transfer-action") === "close") { clearDOM(); controller.close(); }
    else if (button.getAttribute("data-transfer-action") === "execute") Promise.resolve(controller.execute()).finally(clearDOM);
  };
  root.addEventListener("input", onInput); root.addEventListener("change", onInput); root.addEventListener("click", onClick);
  return () => { clearDOM(); root.removeEventListener("input", onInput); root.removeEventListener("change", onInput); root.removeEventListener("click", onClick); controller.dispose(); };
}
