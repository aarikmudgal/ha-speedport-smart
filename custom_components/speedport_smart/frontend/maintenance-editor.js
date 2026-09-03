/** One-shot native administrator maintenance. No polling or browser storage. */
const ACTIONS = new Set(["system_factory_reset", "system_dect_reset", "system_dsl_modem_mode", "system_log_clear"]);
const INPUTS = new Set(["backup_saved", "physical_access", "link_lan1_ready", "firewall_warning_accepted", "retain_registrations"]);
const MESSAGES = Object.freeze({
  ready: "Review the warning, make each choice, then type the exact confirmation. Runtime prerequisites will be checked before sending.",
  invalid: "Make every required choice and type the confirmation exactly.",
  running: "Checking prerequisites and sending this action at most once…",
  verified: "A fresh complete read confirms all previous messages are absent. New messages may already exist.",
  unchanged: "The complete unfiltered message list was already empty. No clear request was sent.",
  rejected: "The action could not be accepted. Close this form and check the router before trying again.",
  outcome_unknown: "The action outcome is unknown. Inspect the router before doing anything else. No automatic retry will occur.",
  reconnect_required: "The action outcome is unknown. Reconnect and reconfigure Home Assistant if necessary, then inspect the router manually. No alternate address, automatic retry, or successful reset is assumed.",
});
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

export function createMaintenanceEditorController({request, onChange = () => {}}) {
  if (typeof request !== "function") throw new TypeError("request_required");
  let state = null;
  let generation = 0;
  let confirmation = "";
  let values = new Map();
  const clear = () => { generation++; state = null; confirmation = ""; values.clear(); };
  return {
    open({entryId, action}) {
      clear();
      if (typeof entryId !== "string" || !entryId || !action || !ACTIONS.has(action.id) ||
          action.execution_policy !== "maintenance" || action.confirmation !== "typed" ||
          typeof action.typed_confirmation !== "string" || action.typed_confirmation.length < 8 ||
          action.typed_confirmation.length > 64 || !Array.isArray(action.inputs) ||
          !["exact", "reconnect_required"].includes(action.readback_policy)) throw new Error("invalid_schema");
      const seen = new Set();
      const inputs = action.inputs.map((input) => {
        if (!input || !INPUTS.has(input.name) || seen.has(input.name) || input.kind !== "boolean" ||
            typeof input.must_be_true !== "boolean") throw new Error("invalid_schema");
        seen.add(input.name);
        return Object.freeze({name: input.name, label: String(input.label ?? input.name),
          kind: "boolean", must_be_true: input.must_be_true});
      });
      state = {entryId, action: Object.freeze({id: action.id, title: String(action.title ?? action.id),
        warning: String(action.warning ?? ""), typed_confirmation: action.typed_confirmation,
        available: action.available === true, readback_policy: action.readback_policy,
        inputs: Object.freeze(inputs)}), status: "ready", busy: false, consumed: false};
      onChange();
    },
    close() { clear(); onChange(); },
    dispose() { clear(); },
    clearConfirmation() { confirmation = ""; },
    snapshot() { return state ? {...state, values: Object.fromEntries(values)} : null; },
    setValue(name, value) {
      if (!state || state.busy || state.consumed || typeof value !== "boolean" ||
          !state.action.inputs.some((input) => input.name === name)) return false;
      values.set(name, value); return true;
    },
    clearValue(name) {
      if (!state || state.busy || state.consumed) return false;
      values.delete(name); return true;
    },
    setConfirmation(value) {
      if (!state || state.busy || state.consumed || typeof value !== "string") return false;
      confirmation = value; return true;
    },
    async execute() {
      if (!state || state.busy || state.consumed || !state.action.available) return false;
      if (confirmation !== state.action.typed_confirmation || state.action.inputs.some((input) =>
        !values.has(input.name) || (input.must_be_true && values.get(input.name) !== true))) {
        confirmation = ""; state.status = "invalid"; onChange(); return false;
      }
      const epoch = generation;
      const action = state.action;
      const message = {type: "speedport_smart/panel/maintenance", entry_id: state.entryId,
        action: action.id, parameters: Object.fromEntries(values), confirmed: true,
        confirmation_text: confirmation};
      confirmation = ""; state.busy = true; state.consumed = true; state.status = "running"; onChange();
      try {
        const response = await request(message);
        if (generation !== epoch) return false;
        if (response?.schema_version !== 1 || response?.action !== action.id) throw new Error("invalid_response");
        const result = response.result;
        if (action.id === "system_log_clear" && ["verified", "unchanged"].includes(result?.status) &&
            result.previous_messages_absent === true) {
          state.status = result.status; return true;
        }
        state.status = action.readback_policy === "reconnect_required" ? "reconnect_required" : "outcome_unknown";
        return false;
      } catch (error) {
        if (generation !== epoch) return false;
        state.status = ["unauthorized", "confirmation_required", "action_rejected", "action_unavailable",
          "action_rate_limited", "action_busy", "entry_not_found", "entry_not_loaded"].includes(error?.code)
          ? "rejected" : (action.readback_policy === "reconnect_required" ? "reconnect_required" : "outcome_unknown");
        return false;
      } finally {
        message.confirmation_text = "";
        for (const key of Object.keys(message.parameters)) delete message.parameters[key];
        if (generation === epoch) { state.busy = false; values.clear(); onChange(); }
      }
    },
  };
}

export function renderMaintenanceEditor(controller) {
  controller.clearConfirmation();
  const view = controller.snapshot();
  if (!view) return "";
  const prefix = `sp-maintenance-${view.action.id}`;
  const disabled = view.busy || view.consumed || !view.action.available;
  const inputs = view.action.inputs.map((input) => {
    const id = `${prefix}-${input.name}`;
    const common = `id="${id}" data-maintenance-field="${input.name}"${disabled ? " disabled" : ""}`;
    const control = input.must_be_true
      ? `<input type="checkbox" ${common}${view.values[input.name] === true ? " checked" : ""}>`
      : `<select ${common}><option value=""${view.values[input.name] === undefined ? " selected" : ""}>Choose explicitly</option><option value="true"${view.values[input.name] === true ? " selected" : ""}>Keep registered</option><option value="false"${view.values[input.name] === false ? " selected" : ""}>Remove registrations</option></select>`;
    return `<div class="sp-maintenance-field"><label for="${id}">${escape(input.label)}</label>${control}</div>`;
  }).join("");
  return `<style>
    .sp-maintenance{box-sizing:border-box;padding:20px;border:1px solid var(--divider-color);border-radius:var(--ha-card-border-radius,12px);color:var(--primary-text-color);background:var(--ha-card-background,var(--card-background-color));overflow-wrap:anywhere}
    .sp-maintenance h3{margin-top:0}.sp-maintenance-field{display:flex;flex-direction:column;gap:8px;margin:16px 0}.sp-maintenance input:not([type=checkbox]),.sp-maintenance select{box-sizing:border-box;width:100%;min-width:0;padding:10px;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px}.sp-maintenance input[type=checkbox]{align-self:flex-start;width:22px;height:22px;accent-color:var(--primary-color)}
    .sp-maintenance-actions{display:flex;gap:12px;flex-wrap:wrap}.sp-maintenance button{padding:10px 16px;border:1px solid var(--divider-color);border-radius:8px;color:var(--primary-text-color);background:var(--secondary-background-color);cursor:pointer}.sp-maintenance :disabled{opacity:.55;cursor:default}.sp-maintenance :focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}
    </style><section class="sp-maintenance" aria-labelledby="${prefix}-title" aria-busy="${view.busy}"><h3 id="${prefix}-title">${escape(view.action.title)}</h3>
    <p>${escape(view.action.warning)}</p><p>Beta: static firmware contract and offline tests. No live maintenance roundtrip is claimed.</p>
    <p role="status" aria-live="polite">${escape(MESSAGES[view.status] ?? MESSAGES.outcome_unknown)}</p>${inputs}
    <div class="sp-maintenance-field"><label for="${prefix}-confirmation">Type <strong>${escape(view.action.typed_confirmation)}</strong> to confirm</label><input id="${prefix}-confirmation" data-maintenance-confirmation type="text" autocomplete="off"${disabled ? " disabled" : ""}></div>
    <div class="sp-maintenance-actions"><button type="button" data-maintenance-action="execute"${disabled ? " disabled" : ""}>Execute once</button><button type="button" data-maintenance-action="close">Close</button></div></section>`;
}

export function bindMaintenanceEditor(root, controller) {
  const clearDOM = () => { for (const input of root.querySelectorAll("[data-maintenance-confirmation]")) input.value = ""; };
  const onInput = (event) => {
    const target = event.target;
    if (!target || !root.contains(target)) return;
    if (target.hasAttribute?.("data-maintenance-confirmation")) { controller.setConfirmation(target.value); return; }
    const name = target.getAttribute?.("data-maintenance-field");
    if (!name) return;
    const value = target.type === "checkbox" ? target.checked : target.value;
    if (typeof value === "boolean") controller.setValue(name, value);
    else if (value === "true" || value === "false") controller.setValue(name, value === "true");
    else controller.clearValue(name);
  };
  const onClick = (event) => {
    const target = event.target?.closest?.("[data-maintenance-action]");
    if (!target || !root.contains(target) || target.disabled) return;
    event.preventDefault();
    if (target.getAttribute("data-maintenance-action") === "close") { clearDOM(); controller.close(); }
    else if (target.getAttribute("data-maintenance-action") === "execute") Promise.resolve(controller.execute()).finally(clearDOM);
  };
  root.addEventListener("input", onInput); root.addEventListener("change", onInput); root.addEventListener("click", onClick);
  return () => { clearDOM(); controller.dispose(); root.removeEventListener("input", onInput); root.removeEventListener("change", onInput); root.removeEventListener("click", onClick); };
}
