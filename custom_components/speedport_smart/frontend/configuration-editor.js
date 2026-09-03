/** Revision-bound editing with optional page-local reads. No polling or storage. */
const KINDS = new Set(["boolean", "enum", "integer", "text", "secret", "time", "identifiers"]);
const NAME = /^[A-Za-z][A-Za-z0-9_]*$/;
const TARGET_ID = /^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$/;
const RESERVED = new Set(["constructor", "prototype", "__proto__"]);
const SUCCESS = new Set(["verified", "secret_unverified", "unchanged", "reconnect_required"]);
const LINK_SETTING = "telephony_phonebook_link";
const LINK_PHRASES = Object.freeze({merge: "MERGE ONLINE PHONEBOOK CONTACTS", replace: "REPLACE LOCAL PHONEBOOK CONTACTS"});
const MESSAGES = Object.freeze({
  idle: "Load current settings to begin. Nothing changes until you save.",
  loading: "Loading current router settings…",
  targets_loading: "Loading available targets. Nothing will be changed.",
  targets_ready: "Choose a target, then explicitly load its current settings.",
  targets_empty: "No existing editable target was returned. Nothing was changed.",
  target_required: "Load available targets and select one before loading settings.",
  ready: "Review your changes, then confirm and save.",
  saving: "Saving once and checking the resulting router state…",
  verified: "The router state was verified. Reload before editing again.",
  secret_unverified: "Other settings were verified. The credential could not be independently verified. Reload before editing again.",
  unchanged: "No changes were needed. Reload before editing again.",
  reconnect_required: "The request was sent. This setting can change router connectivity. Reconnect and update the integration connection settings if needed, then verify the router state. It has not been verified yet.",
  reconnect_unknown: "The router did not confirm the resulting state. This setting can change connectivity. Reconnect and update the integration connection settings if needed, then check the router before retrying. Nothing will be repeated automatically.",
  manual_required: "The request was sent once, but this action has no independent state readback. Inspect the physical result before repeating anything. No automatic retry will occur.",
  credentials_ready: "The VPN configuration was verified. Download its private credentials now and keep the file secure. This temporary copy expires in two minutes or when you leave this editor. Do not repeat creation to retrieve a lost response.",
  credentials_downloaded: "Private VPN credentials downloaded. Keep the file secure. The router request will not be repeated.",
  credentials_expired: "The temporary credential copy was cleared. Check the router's VPN page; do not repeat creation without checking the existing peer first.",
  invalid: "Check the field values and type the confirmation exactly.",
  expired: "This read has expired. Reload current settings before saving.",
  rejected: "The request was rejected. Reload current settings before trying again.",
  load_failed: "Current settings could not be loaded. Nothing was changed.",
  outcome_unknown: "The resulting router state could not be verified. Check the router and reload before trying again. The request will not be repeated automatically.",
  pending_confirmation: "The account-link request was sent. Choose whether to merge or replace local contacts, then confirm that separate operation. Nothing will continue automatically.",
  link_finishing: "Sending the separately confirmed phonebook decision once…",
  link_invalid: "Choose merge or replace, then type its exact confirmation. No second request was sent.",
  link_expired: "The pending phonebook decision expired and was cleared. Inspect the router's phonebook before starting again; the account-link request may already have changed it.",
  link_manual_required: "The phonebook decision was sent once. Online synchronization and individual contact results could not be independently verified. Inspect the phonebook before repeating anything.",
});

const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

function fieldsOf(fields) {
  if (!Array.isArray(fields) || fields.length === 0) throw new Error("invalid_schema");
  const seen = new Set();
  return fields.map((source) => {
    if (!source || !NAME.test(source.name) || RESERVED.has(source.name) ||
        seen.has(source.name) || !KINDS.has(source.kind)) throw new Error("invalid_schema");
    seen.add(source.name);
    const field = {
      name: source.name, kind: source.kind, label: String(source.label ?? source.name),
      description: String(source.description ?? ""),
      dynamic_choices: source.dynamic_choices === true,
    };
    for (const limit of ["minimum", "maximum"]) {
      if (source[limit] !== undefined && source[limit] !== null) {
        if (!Number.isSafeInteger(source[limit])) throw new Error("invalid_schema");
        field[limit] = source[limit];
      }
    }
    if (field.minimum !== undefined && field.maximum !== undefined &&
        field.minimum > field.maximum) throw new Error("invalid_schema");
    if (source.kind === "enum" || source.kind === "identifiers") {
      if (!Array.isArray(source.choices) || source.choices.length > 256 ||
          (source.choices.length === 0 && source.kind === "enum" && !field.dynamic_choices)) {
        throw new Error("invalid_schema");
      }
      const values = new Set();
      field.choices = source.choices.map((choice) => {
        if (!choice || !["string", "number"].includes(typeof choice.value) ||
            (typeof choice.value === "number" && !Number.isSafeInteger(choice.value)) ||
            values.has(choice.value)) throw new Error("invalid_schema");
        values.add(choice.value);
        return Object.freeze({value: choice.value, label: String(choice.label ?? choice.value)});
      });
      Object.freeze(field.choices);
    }
    return Object.freeze(field);
  });
}

function validValue(field, value) {
  if (field.kind === "identifiers") return Array.isArray(value) &&
    value.length <= Math.min(field.maximum ?? 256, 256) && value.length >= (field.minimum ?? 0) &&
    new Set(value).size === value.length && value.every((key) =>
      typeof key === "string" && TARGET_ID.test(key) && field.choices.some((choice) => choice.value === key));
  if (field.kind === "boolean") return typeof value === "boolean";
  if (field.kind === "enum") return field.choices.some((choice) => choice.value === value);
  if (field.kind === "integer") {
    return Number.isSafeInteger(value) &&
      (field.minimum === undefined || value >= field.minimum) &&
      (field.maximum === undefined || value <= field.maximum);
  }
  if (typeof value !== "string") return false;
  if (/[\x00-\x1f\x7f]/.test(value)) return false;
  if (field.kind === "time" && !/^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$/.test(value)) return false;
  if (field.kind === "secret" && (!value || /^[*•●]+$/.test(value) ||
      /^(?:\[|<)?(?:\*\*)?redacted(?:\*\*)?(?:\]|>)?$/i.test(value))) return false;
  return (field.minimum === undefined || value.length >= field.minimum) &&
    (field.maximum === undefined || value.length <= field.maximum);
}

/** request sends one private HTTP command and resolves its plain result. */
export function createConfigurationEditorController({request, download, onChange = () => {}, now = Date.now}) {
  if (typeof request !== "function") throw new TypeError("request_required");
  let generation = 0;
  let state = null;
  let baseline = new Map();
  let drafts = new Map();
  let secrets = new Map();
  let confirmation = "";
  let expiresAt = 0;
  let busy = false;
  let loaded = false;
  let credentialDownload = null;
  let credentialTimer = null;
  let pendingLink = null;
  let linkTimer = null;
  let linkConfirmation = "";
  const clearLink = () => {
    pendingLink = null; linkConfirmation = "";
    if (linkTimer !== null) clearTimeout(linkTimer);
    linkTimer = null;
    if (state) state.link = null;
  };
  const expireLink = () => {
    if (pendingLink !== null && now() >= pendingLink.expiresAt) {
      clearLink(); state.status = "link_expired"; return true;
    }
    return false;
  };
  const clearDownload = () => {
    credentialDownload = null;
    if (credentialTimer !== null) clearTimeout(credentialTimer);
    credentialTimer = null;
  };
  const notify = () => onChange();
  const clearCredentials = () => { secrets.clear(); confirmation = ""; linkConfirmation = ""; };
  const clear = () => {
    generation += 1;
    clearDownload();
    clearLink();
    baseline.clear(); drafts.clear(); clearCredentials();
    expiresAt = 0; loaded = false; busy = false; state = null;
  };
  const changes = () => {
    const result = Object.create(null);
    if (!state) return result;
    for (const field of state.setting.fields) {
      if (field.kind === "secret") {
        if (secrets.has(field.name)) result[field.name] = secrets.get(field.name);
      } else if (drafts.has(field.name) && JSON.stringify(drafts.get(field.name)) !== JSON.stringify(baseline.get(field.name))) {
        result[field.name] = drafts.get(field.name);
      }
    }
    return result;
  };
  const controller = {
    open({entryId, setting, autoLoad = false, targetId = null}) {
      clear();
      if (typeof entryId !== "string" || !entryId || !setting ||
          typeof setting.id !== "string" || !NAME.test(setting.id) ||
          typeof setting.confirmation !== "string" || !setting.confirmation.trim()) {
        throw new Error("invalid_schema");
      }
      state = {entryId, setting: Object.freeze({
        id: setting.id, title: String(setting.title ?? setting.id),
        section: String(setting.section ?? ""), warning: String(setting.warning ?? ""),
        confirmation: setting.confirmation, live_write_verified: setting.live_write_verified === true,
        requires_target: setting.requires_target === true,
        target_limit: Number.isInteger(setting.target_limit) && setting.target_limit > 0 && setting.target_limit <= 5000 ? setting.target_limit : 256,
        fields: Object.freeze(fieldsOf(setting.fields)),
      }), autoLoad: autoLoad === true, status: setting.requires_target === true ? "target_required" : "idle",
        revision: null, targets: Object.freeze([]), targetId: null, link: null};
      const epoch = generation;
      notify();
      if (epoch === generation && state?.autoLoad) return controller.refresh({targetId});
    },
    close() { if (busy) return false; clear(); notify(); return true; },
    dispose() { clear(); },
    clearSensitiveDrafts() { clearCredentials(); },
    snapshot() {
      if (!state) return null;
      expireLink();
      // Secret values and typed confirmation never enter the render snapshot.
      const dirty = [...Object.keys(changes())];
      return {...state, busy, isBusy: busy, isSaving: ["saving", "link_finishing"].includes(state.status),
        loaded, values: Object.fromEntries(drafts),
        downloadAvailable: credentialDownload !== null,
        linkPending: pendingLink !== null,
        link: state.link && {...state.link},
        dirty, isDirty: dirty.length > 0 && (loaded || state.status === "expired"),
        confirmationReady: confirmation === state.setting.confirmation,
        expired: loaded && now() >= expiresAt};
    },
    async refresh({targetId} = {}) {
      if (!state || busy) return false;
      if (!state.setting.requires_target) return controller.load();
      const preferred = targetId ?? state.targetId;
      const inventory = controller.loadTargets();
      const epoch = generation;
      if (!await inventory || epoch !== generation || !state) return false;
      const selected = preferred === null || preferred === undefined
        ? state.targets[0] : state.targets.find((target) => target.id === preferred);
      // Never silently substitute another object after a selected target disappears.
      if (!selected) {
        if (state.targets.length) { state.status = "target_required"; notify(); }
        return false;
      }
      const automatic = state.autoLoad;
      const selection = controller.selectTarget(selected.id);
      return automatic ? selection : controller.load();
    },
    cancelChanges() {
      if (!state || busy || !loaded || pendingLink !== null) return false;
      drafts = new Map(baseline);
      clearCredentials(); state.status = "ready"; notify(); return true;
    },
    async loadTargets() {
      if (!state || busy || !state.setting.requires_target) return false;
      const epoch = ++generation;
      const {entryId, setting} = state;
      clearDownload();
      clearLink();
      clearCredentials(); baseline.clear(); drafts.clear(); loaded = false; expiresAt = 0;
      state.revision = null; state.targetId = null; state.targets = Object.freeze([]);
      busy = true; state.status = "targets_loading"; notify();
      try {
        const result = await request({type: "speedport_smart/panel/settings/targets",
          entry_id: entryId, setting_id: setting.id});
        if (epoch !== generation) return false;
        if (!result || result.setting_id !== setting.id || !Array.isArray(result.targets) ||
            result.targets.length > setting.target_limit) throw new Error("invalid_response");
        const seen = new Set();
        state.targets = Object.freeze(result.targets.map((target) => {
          if (!target || typeof target.id !== "string" || !TARGET_ID.test(target.id) ||
              seen.has(target.id) || typeof target.label !== "string" ||
              !target.label.trim() || target.label.length > 512) throw new Error("invalid_response");
          seen.add(target.id);
          return Object.freeze({id: target.id, label: target.label});
        }));
        state.status = state.targets.length ? "targets_ready" : "targets_empty";
        return true;
      } catch (_error) {
        if (epoch !== generation) return false;
        state.targets = Object.freeze([]); state.status = "load_failed";
        return false;
      } finally {
        if (epoch === generation) { busy = false; notify(); }
      }
    },
    selectTarget(targetId) {
      if (!state?.setting.requires_target || ["saving", "link_finishing"].includes(state.status) ||
          !state.targets.some((target) => target.id === targetId)) return false;
      if (targetId === state.targetId) return true;
      generation += 1; busy = false; loaded = false; expiresAt = 0;
      clearDownload();
      clearLink();
      clearCredentials(); baseline.clear(); drafts.clear();
      state.revision = null; state.targetId = targetId; state.status = "targets_ready";
      const epoch = generation;
      notify();
      if (epoch !== generation) return false;
      if (state.autoLoad) return controller.load();
      return true;
    },
    async load() {
      if (!state || busy) return false;
      if (state.setting.requires_target && !state.targetId) {
        state.status = "target_required"; notify(); return false;
      }
      const epoch = ++generation;
      const {entryId, setting, targetId} = state;
      clearDownload();
      clearLink();
      clearCredentials(); baseline.clear(); drafts.clear(); loaded = false;
      busy = true; state.status = "loading"; notify();
      try {
        const result = await request({type: "speedport_smart/panel/settings/read",
          entry_id: entryId, setting_id: setting.id,
          ...(setting.requires_target ? {target_id: targetId} : {})});
        if (epoch !== generation) return false;
        if (!result || result.setting_id !== setting.id ||
            (result.target_id !== undefined && result.target_id !== targetId) ||
            typeof result.revision !== "string" || !result.revision ||
            !result.values || typeof result.values !== "object" || Array.isArray(result.values) ||
            !Number.isFinite(result.expires_in) || result.expires_in <= 0) {
          throw new Error("invalid_response");
        }
        const dynamic = setting.fields.filter((field) => field.dynamic_choices);
        const supplied = result.choices ?? {};
        if (!supplied || typeof supplied !== "object" || Array.isArray(supplied) ||
            Object.keys(supplied).length !== dynamic.length ||
            Object.keys(supplied).some((name) => !dynamic.some((field) => field.name === name))) {
          throw new Error("invalid_response");
        }
        const fields = fieldsOf(setting.fields.map((field) => !field.dynamic_choices ? field :
          {...field, choices: supplied[field.name]}));
        for (const field of fields) {
          if (field.kind === "secret") continue;
          const value = result.values[field.name];
          if (!validValue(field, value)) throw new Error("invalid_response");
          baseline.set(field.name, Array.isArray(value) ? Object.freeze([...value]) : value);
          drafts.set(field.name, Array.isArray(value) ? Object.freeze([...value]) : value);
        }
        state.setting = Object.freeze({...state.setting, fields: Object.freeze(fields)});
        state.revision = result.revision;
        expiresAt = now() + result.expires_in * 1000;
        state.status = "ready"; loaded = true;
        return true;
      } catch (_error) {
        if (epoch !== generation) return false;
        baseline.clear(); drafts.clear(); state.revision = null; state.status = "load_failed";
        return false;
      } finally {
        if (epoch === generation) { busy = false; notify(); }
      }
    },
    setValue(name, value) {
      if (!state || busy || !loaded) return false;
      const field = state.setting.fields.find((item) => item.name === name);
      if (!field) return false;
      if (field.kind === "secret") {
        if (value === "") secrets.delete(name);
        else secrets.set(name, value);
      } else drafts.set(name, Array.isArray(value) ? Object.freeze([...value]) : value);
      state.status = "ready";
      return true;
    },
    setConfirmation(value) {
      if (!state || busy || !loaded || typeof value !== "string") return false;
      confirmation = value;
      return true;
    },
    setLinkChoice(mergeExisting) {
      if (!state || busy || !pendingLink || typeof mergeExisting !== "boolean") return false;
      if (expireLink()) { notify(); return false; }
      linkConfirmation = "";
      state.link = Object.freeze({...state.link, mergeExisting});
      state.status = "pending_confirmation"; notify(); return true;
    },
    setLinkConfirmation(value) {
      if (!state || busy || !pendingLink || typeof value !== "string") return false;
      if (expireLink()) { notify(); return false; }
      linkConfirmation = value; return true;
    },
    async finishLink() {
      if (!state || busy || !pendingLink) return false;
      if (expireLink()) { notify(); return false; }
      const merge = state.link?.mergeExisting;
      const phrase = merge === true ? LINK_PHRASES.merge : merge === false ? LINK_PHRASES.replace : null;
      if (!phrase || linkConfirmation !== phrase) {
        linkConfirmation = ""; state.status = "link_invalid"; notify(); return false;
      }
      if (state.setting.id !== LINK_SETTING || state.entryId !== pendingLink.entryId ||
          state.targetId !== pendingLink.targetId) {
        clearLink(); state.status = "outcome_unknown"; notify(); return false;
      }
      const epoch = generation;
      const message = {type: "speedport_smart/panel/phonebook_link/finish", entry_id: state.entryId,
        pending_link: pendingLink.token, target_id: pendingLink.targetId, phonebook_id: pendingLink.phonebookId,
        merge_existing: merge, confirmed: true, confirmation_text: phrase};
      // Burn the one-use continuation before any await; transport failure is not a retry grant.
      clearLink(); clearCredentials(); busy = true; loaded = false;
      state.status = "link_finishing"; state.revision = null; notify();
      try {
        const result = await request(message);
        if (epoch !== generation) return false;
        state.status = result?.status === "outcome_unknown" && result.verification === "manual_required"
          ? "link_manual_required" : "outcome_unknown";
        return false;
      } catch (_error) {
        if (epoch === generation) state.status = "outcome_unknown";
        return false;
      } finally {
        message.pending_link = ""; message.confirmation_text = "";
        if (epoch === generation) { busy = false; notify(); }
      }
    },
    async downloadCredentials() {
      if (!state || busy || credentialDownload === null || typeof download !== "function") return false;
      const selected = credentialDownload;
      const epoch = generation;
      try {
        await download(new Blob([selected.content], {type: selected.media_type}), selected.filename);
        if (epoch !== generation) return false;
        clearDownload(); state.status = "credentials_downloaded"; notify(); return true;
      } catch (_error) {
        // Retrying this local download never sends another router request.
        return false;
      }
    },
    async save() {
      if (!state || busy || !loaded) return false;
      if (now() >= expiresAt) {
        clearCredentials(); loaded = false; state.status = "expired"; notify(); return false;
      }
      const updates = changes();
      if (confirmation !== state.setting.confirmation ||
          Object.entries(updates).some(([name, value]) =>
            !validValue(state.setting.fields.find((field) => field.name === name), value))) {
        clearCredentials(); state.status = "invalid"; notify(); return false;
      }
      if (Object.keys(updates).length === 0) {
        clearCredentials(); loaded = false; state.revision = null;
        state.status = "unchanged"; notify(); return true;
      }
      const epoch = generation;
      busy = true; state.status = "saving";
      const message = {type: "speedport_smart/panel/settings/save", entry_id: state.entryId,
        setting_id: state.setting.id, revision: state.revision, changes: updates,
        ...(state.setting.requires_target ? {target_id: state.targetId} : {}),
        confirmed: true, confirmation_text: confirmation};
      clearCredentials(); notify();
      try {
        const result = await request(message);
        if (epoch !== generation) return false;
        if (result?.status === "pending_confirmation") {
          if (state.setting.id !== LINK_SETTING || !state.setting.requires_target ||
              result.target_id !== state.targetId || typeof result.pending_link !== "string" ||
              !/^[a-f0-9]{48}$/.test(result.pending_link) || !Number.isFinite(result.expires_in) ||
              result.expires_in <= 0 || result.expires_in > 120 ||
              !Number.isInteger(result.phonebook_id) || result.phonebook_id < 0 || result.phonebook_id > 5 ||
              !Number.isInteger(result.online_contacts) || result.online_contacts < 0 || result.online_contacts > 1000 ||
              !Number.isInteger(result.local_contacts) || result.local_contacts < 0 || result.local_contacts > 1000) {
            state.status = "outcome_unknown"; return false;
          }
          pendingLink = {token: result.pending_link, entryId: state.entryId, targetId: state.targetId,
            phonebookId: result.phonebook_id, expiresAt: now() + result.expires_in * 1000};
          state.link = Object.freeze({phonebookId: result.phonebook_id, onlineContacts: result.online_contacts,
            localContacts: result.local_contacts, mergeExisting: null});
          linkTimer = setTimeout(() => {
            if (epoch !== generation || pendingLink === null) return;
            clearLink(); state.status = "link_expired"; notify();
          }, result.expires_in * 1000);
          linkTimer?.unref?.();
          state.status = "pending_confirmation"; return true;
        }
        if (!SUCCESS.has(result?.status)) {
          state.status = result?.status === "outcome_unknown" && result.verification === "reconnect_required"
            ? "reconnect_unknown" : result?.status === "outcome_unknown" && result.verification === "manual_required"
              ? "manual_required" : "outcome_unknown";
          return false;
        }
        if (result.private_download !== undefined) {
          const value = result.private_download;
          const allowed = new Set(["vpn_peer_create", "vpn_ipsec_key_rotate"]);
          const fileTypes = {"Wireguard.conf": "text/plain;charset=utf-8", "Speedport-IPsec.json": "application/json", "Speedport-IPsec-peers.json": "application/json"};
          if (result.status !== "verified" || !allowed.has(state.setting.id) || !value ||
              Object.keys(value).sort().join(",") !== "content,filename,media_type" ||
              !Object.hasOwn(fileTypes, value.filename) || fileTypes[value.filename] !== value.media_type ||
              typeof value.content !== "string" || value.content.length < 1 || value.content.length > 65536) {
            state.status = "outcome_unknown"; return false;
          }
          credentialDownload = {...value};
          value.content = "";
          credentialTimer = setTimeout(() => {
            if (epoch !== generation) return;
            clearDownload(); state.status = "credentials_expired"; notify();
          }, 120000);
          credentialTimer?.unref?.();
          state.status = "credentials_ready";
          return true;
        }
        state.status = result.status;
        return true;
      } catch (error) {
        if (epoch !== generation) return false;
        // Raw server error messages may contain submitted private data.
        state.status = ["rejected", "command_rejected", "invalid_input", "stale_revision",
          "unauthorized", "confirmation_required", "stale_settings", "administrator_required",
          "invalid_settings", "invalid_settings_target", "setting_unavailable", "rate_limited"].includes(error?.code)
          ? "rejected" : "outcome_unknown";
        return false;
      } finally {
        for (const field of state?.setting.fields ?? []) {
          if (field.kind === "secret") delete updates[field.name];
        }
        // Clear all request changes as well when navigation replaced the schema.
        for (const key of Object.keys(updates)) delete updates[key];
        message.confirmation_text = "";
        if (epoch === generation) { busy = false; loaded = false; state.revision = null; notify(); }
      }
    },
  };
  return controller;
}

const WEEKDAYS = Object.freeze({mo: "Monday", di: "Tuesday", mi: "Wednesday", do: "Thursday", fr: "Friday", sa: "Saturday", so: "Sunday"});

function fieldGroup(setting, field) {
  const name = field.name;
  if (setting.id === "wifi_identity") {
    if (["wlan_ssid", "wlan_visible"].includes(name)) return "2.4 GHz network";
    if (["wlan_5ghz_ssid", "wlan_5ghz_visible"].includes(name)) return "5 GHz network";
    return "Shared security and password";
  }
  if (setting.id === "wifi_radio") {
    if (["wlan_band", "wlan_power"].includes(name)) return "Radio settings";
    return name.startsWith("wlan_5ghz_") ? "5 GHz radio" : "2.4 GHz radio";
  }
  if (setting.id === "wifi_schedule") {
    const weekday = name.match(/^wlan_time_(mo|di|mi|do|fr|sa|so)_/);
    if (weekday) return WEEKDAYS[weekday[1]];
    return ["wlan_dfrom", "wlan_dto"].includes(name) ? "Daily schedule" : "Schedule settings";
  }
  const parentalDay = name.match(/^(?:trule_|tr_)(mo|di|mi|do|fr|sa|so)_/);
  if (parentalDay) return WEEKDAYS[parentalDay[1]];
  if (/^(?:trule_d(?:from|to)|tr_dmaxtime)/.test(name)) return "Daily schedule";
  if (setting.id === "dynamic_dns") {
    if (["dyndns_user", "dyndns_password"].includes(name)) return "Provider credentials";
    if (name.startsWith("dyndns_upd") || name === "dyndns_update_path") return "Custom update server";
    return "Dynamic DNS service";
  }
  if (field.kind === "secret") return "Credentials";
  if (field.kind === "identifiers") return "Selections and assignments";
  if (field.kind === "time") return "Schedule";
  return "Settings";
}

function scheduleGroupHidden(group, mode) {
  return group === "daily" ? mode !== "1" : group === "weekly" && mode !== "2";
}

function groupedFields(setting, renderField, values) {
  const groups = new Map();
  for (const field of setting.fields) {
    const title = fieldGroup(setting, field);
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(field);
  }
  // Keep the two networks together even when metadata arrives interleaved.
  const order = setting.id === "wifi_identity"
    ? ["2.4 GHz network", "5 GHz network", "Shared security and password"] : [...groups.keys()];
  return order.filter((title) => groups.has(title)).map((title) => {
    const scheduleGroup = setting.id !== "wifi_schedule" ? null :
      title === "Daily schedule" ? "daily" : Object.values(WEEKDAYS).includes(title) ? "weekly" : null;
    const visibility = scheduleGroup === null ? "" :
      ` data-setting-schedule-group="${scheduleGroup}"${scheduleGroupHidden(scheduleGroup, values.wlan_timerule) ? " hidden" : ""}`;
    return `<fieldset class="sp-settings-group"${visibility}><legend>${escape(title)}</legend><div class="sp-settings-fields">` +
      groups.get(title).map(renderField).join("") + "</div></fieldset>";
  }).join("");
}

/** Render within the native panel; pageMode keeps loading/navigation chrome local. */
export function renderConfigurationEditor(controller, {pageMode = false} = {}) {
  // A replaced DOM cannot secretly retain an earlier password/confirmation.
  // The host should rerender on editor notifications, not on live WAN ticks.
  controller.clearSensitiveDrafts();
  const view = controller.snapshot();
  if (!view) return "";
  const prefix = `sp-setting-${view.setting.id}`;
  const disabled = !view.loaded || view.busy || view.expired;
  const targetPicker = !view.setting.requires_target ? "" :
    `<div class="sp-settings-field"><label for="${prefix}-target">Existing target</label>` +
    `<select id="${prefix}-target" data-setting-target aria-describedby="${prefix}-target-help"${view.busy || !view.targets.length ? " disabled" : ""}>` +
    `<option value="" disabled${view.targetId === null ? " selected" : ""}>Select a target</option>` +
    view.targets.map((target, index) => `<option value="${index}"${target.id === view.targetId ? " selected" : ""}>${escape(target.label)} (${escape(target.id)})</option>`).join("") +
    `</select><small id="${prefix}-target-help">${pageMode ? "Changing targets asks before discarding unsaved changes." : "Changing targets discards unsaved changes."} ${view.autoLoad ? "Selection loads current values; it never saves changes." : "Selection does not load or save settings."}</small></div>`;
  const renderField = (field) => {
    const id = `${prefix}-${field.name}`;
    const value = view.values[field.name];
    const common = `id="${escape(id)}" data-setting-field="${escape(field.name)}"` +
      ` aria-describedby="${escape(id)}-help"${disabled ? " disabled" : ""}`;
    let input;
    if (field.kind === "boolean") {
      input = `<input type="checkbox" ${common}${value === true ? " checked" : ""}>`;
    } else if (field.kind === "identifiers") {
      if (pageMode && field.choices.length > 0 && field.choices.length <= 8) {
        return `<fieldset class="sp-settings-field sp-settings-choices" aria-describedby="${escape(id)}-help"><legend>${escape(field.label)}</legend>` +
          field.choices.map((choice, index) => `<label class="sp-settings-check" for="${escape(id)}-${index}">` +
            `<input type="checkbox" id="${escape(id)}-${index}" data-setting-field="${escape(field.name)}" data-setting-choice="${index}"${disabled ? " disabled" : ""}${Array.isArray(value) && value.includes(choice.value) ? " checked" : ""}>` +
            `<span>${escape(choice.label)}</span></label>`).join("") +
          `<small id="${escape(id)}-help">${escape(field.description)}</small></fieldset>`;
      }
      input = `<select multiple size="${Math.min(8, Math.max(3, field.choices.length))}" ${common}>` +
        field.choices.map((choice, index) => `<option value="${index}"${Array.isArray(value) && value.includes(choice.value) ? " selected" : ""}>${escape(choice.label)}</option>`).join("") + "</select>";
    } else if (field.kind === "enum") {
      input = `<select ${common}>${field.choices.map((choice, index) =>
        `<option value="${index}"${choice.value === value ? " selected" : ""}>${escape(choice.label)}</option>`).join("")}</select>`;
    } else {
      const scheduleClock = /^wlan_(?:d(?:from|to)|time_(?:mo|di|mi|do|fr|sa|so)_(?:from|to))$/.test(field.name) ||
        /^trule_(?:d|(?:mo|di|mi|do|fr|sa|so)_)(?:from|to)[23]?$/.test(field.name);
      const clock = field.kind === "time" || scheduleClock;
      const startClock = scheduleClock && /from[23]?$/.test(field.name);
      const allowsEndOfDay = (!startClock && /24:00/.test(field.description)) || /(?:_to|dto)[23]?$/.test(field.name) || value === "24:00";
      const type = pageMode && clock && !allowsEndOfDay ? "time" :
        {secret: "password", integer: "number", time: "text", text: "text"}[field.kind];
      const constraints = ["minimum", "maximum"].filter((key) => field[key] !== undefined)
        .map((key) => ` ${field.kind === "integer" ? (key === "minimum" ? "min" : "max") :
          (key === "minimum" ? "minlength" : "maxlength")}="${field[key]}"`).join("");
      input = `<input type="${type}" ${common}${constraints}` +
        (type === "time" ? ' step="60"' : clock ? ' inputmode="numeric" placeholder="HH:MM" pattern="(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)"' : "") +
        (field.kind === "secret" ? ' autocomplete="new-password"' : ` value="${escape(value ?? "")}"`) + ">";
    }
    return `<div class="sp-settings-field${pageMode && field.kind === "boolean" ? " sp-settings-boolean" : ""}">` +
      (pageMode && field.kind === "boolean" ? `<label class="sp-settings-check" for="${escape(id)}">${input}<span>${escape(field.label)}</span></label>` : `<label for="${escape(id)}">${escape(field.label)}</label>${input}`) +
      `<small id="${escape(id)}-help">${escape(field.description)}` +
      `${field.kind === "secret" ? " Leave blank to request no credential change. Some edits require re-entering it. Credentials are never loaded into this form." : ""}</small></div>`;
  };
  const fields = pageMode ? groupedFields(view.setting, renderField, view.values) :
    `<div class="sp-settings-fields">${view.setting.fields.map(renderField).join("")}</div>`;
  const linkPhrase = view.link?.mergeExisting === true ? LINK_PHRASES.merge :
    view.link?.mergeExisting === false ? LINK_PHRASES.replace : null;
  const linkSection = !view.linkPending ? "" : `<fieldset class="sp-settings-link">
    <legend>Separate phonebook merge decision</legend>
    <p>Router-reported online contacts: ${view.link.onlineContacts}. Current local contacts: ${view.link.localContacts}.
    These counts do not verify individual contacts. Replacing may overwrite local contacts.</p>
    <div class="sp-settings-fields"><div class="sp-settings-field"><label for="${prefix}-link-choice">Choose explicitly</label>
    <select id="${prefix}-link-choice" data-setting-link-choice${view.busy ? " disabled" : ""}>
    <option value="" disabled${view.link.mergeExisting === null ? " selected" : ""}>Select merge or replace</option>
    <option value="merge"${view.link.mergeExisting === true ? " selected" : ""}>Merge existing contacts</option>
    <option value="replace"${view.link.mergeExisting === false ? " selected" : ""}>Replace local contacts</option></select></div>
    <div class="sp-settings-field"><label for="${prefix}-link-confirm">${linkPhrase ? `Type <strong>${escape(linkPhrase)}</strong>` : "Choose a decision before confirming"}</label>
    <input id="${prefix}-link-confirm" type="text" data-setting-link-confirmation autocomplete="off"${view.busy || !linkPhrase ? " disabled" : ""}></div></div>
    <div class="sp-settings-actions"><button type="button" data-setting-action="finishLink"${view.busy || !linkPhrase ? " disabled" : ""}>Confirm phonebook decision once</button></div></fieldset>`;
  return `<style>
    .sp-settings-editor{box-sizing:border-box;width:100%;padding:20px;border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color));color:var(--primary-text-color);border:1px solid var(--divider-color)}
    .sp-settings-editor *{box-sizing:border-box}.sp-settings-editor h3{margin:0 0 12px}.sp-settings-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:16px}
    .sp-settings-field{display:flex;min-width:0;flex-direction:column;gap:8px}.sp-settings-field input:not([type=checkbox]),.sp-settings-field select{width:100%;min-width:0;padding:10px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color)}
    .sp-settings-field input[type=checkbox]{align-self:flex-start;width:22px;height:22px;accent-color:var(--primary-color)}.sp-settings-field small{color:var(--secondary-text-color);overflow-wrap:anywhere}
    .sp-settings-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}.sp-settings-actions button{padding:10px 16px;color:var(--primary-text-color);background:var(--secondary-background-color);border:1px solid var(--divider-color);border-radius:8px;cursor:pointer}.sp-settings-editor :focus-visible{outline:2px solid var(--primary-color);outline-offset:3px}.sp-settings-editor :disabled{opacity:.55;cursor:default}.sp-settings-warning{white-space:pre-wrap;overflow-wrap:anywhere}.sp-settings-confirmation{margin-top:16px}.sp-settings-link{min-width:0;margin:20px 0 0;padding:16px;border:1px solid var(--divider-color);border-radius:8px}
    .sp-settings-group{min-width:0;margin:20px 0 0;padding:16px;border:1px solid var(--divider-color);border-radius:8px}.sp-settings-group>legend{font-weight:600;padding:0 6px}.sp-settings-check{display:flex;align-items:center;gap:10px;cursor:pointer}.sp-settings-check input[type=checkbox]{flex:none;margin:0;align-self:auto}.sp-settings-boolean{justify-content:flex-start;padding-top:8px}.sp-settings-choices{margin:0;padding:0;border:0}.sp-settings-choices>legend{margin-bottom:10px}.sp-settings-page .sp-settings-confirmation{padding-top:16px;border-top:1px solid var(--divider-color)}
    </style><section class="sp-settings-editor${pageMode ? " sp-settings-page" : ""}" aria-labelledby="${prefix}-title" aria-busy="${view.busy}">
    <h3 id="${prefix}-title">${escape(view.setting.title)}</h3>
    ${view.setting.warning ? `<p class="sp-settings-warning">${escape(view.setting.warning)}</p>` : ""}
    ${view.setting.fields.some((field) => field.kind === "secret") ? "<p class=\"sp-settings-warning\">Use HTTPS for Home Assistant when entering credentials. Router HTTPS does not secure the connection between this browser and Home Assistant.</p>" : ""}
    ${view.setting.live_write_verified ? "" : "<p>Live router changes for this setting still require user validation.</p>"}
    <p role="status" aria-live="polite">${escape(MESSAGES[view.status] ?? MESSAGES.load_failed)}</p>
    ${targetPicker}
    ${fields}
    <div class="sp-settings-field sp-settings-confirmation"><label for="${prefix}-confirm">Type <strong>${escape(view.setting.confirmation)}</strong> to confirm these changes</label>
    <input id="${prefix}-confirm" type="text" data-setting-confirmation autocomplete="off"${disabled ? " disabled" : ""}></div>
    ${linkSection}
    <div class="sp-settings-actions">${pageMode ? `<button type="button" data-setting-action="refresh"${view.busy ? " disabled" : ""}>Refresh</button>` :
      `${view.setting.requires_target ? `<button type="button" data-setting-action="loadTargets"${view.busy ? " disabled" : ""}>Load available targets</button>` : ""}
      <button type="button" data-setting-action="load"${view.busy || (view.setting.requires_target && !view.targetId) ? " disabled" : ""}>Load current settings</button>`}
    <button type="button" data-setting-action="save"${disabled ? " disabled" : ""}>Save changes</button>
    ${view.downloadAvailable ? '<button type="button" data-setting-action="downloadCredentials">Download private VPN credentials</button>' : ""}
    ${pageMode ? `<button type="button" data-setting-action="cancelChanges"${view.busy || !view.loaded ? " disabled" : ""}>Cancel changes</button>` : `<button type="button" data-setting-action="close"${view.busy ? " disabled" : ""}>Close</button>`}</div></section>`;
}

/** Bind once to a stable container; caller must dispose on router/navigation change. */
export function bindConfigurationEditor(root, controller, {
  pageMode = false,
  confirmDiscard = (message) => globalThis.confirm?.(message) === true,
} = {}) {
  const onInput = (event) => {
    const target = event.target;
    if (!target || !root.contains(target)) return;
    if (target.hasAttribute?.("data-setting-target")) {
      const index = target.value;
      if (/^\d+$/.test(index)) {
        const view = controller.snapshot();
        const item = view?.targets[Number(index)];
        if (item && item.id !== view.targetId) {
          if ((pageMode || root.querySelector?.(".sp-settings-page")) && view.isDirty) {
            let accepted = false;
            try { accepted = confirmDiscard("Discard unsaved changes and load the selected target?") === true; }
            catch (_error) { /* No usable confirmation means no draft may be discarded. */ }
            if (!accepted) {
              const previous = view.targets.findIndex((candidate) => candidate.id === view.targetId);
              target.value = previous < 0 ? "" : String(previous);
              return;
            }
          }
          clearDOMCredentials(); controller.selectTarget(item.id);
        }
      }
      return;
    }
    if (target.hasAttribute?.("data-setting-confirmation")) {
      controller.setConfirmation(target.value); return;
    }
    if (target.hasAttribute?.("data-setting-link-choice")) {
      if (["merge", "replace"].includes(target.value)) {
        clearDOMCredentials(); controller.setLinkChoice(target.value === "merge");
      }
      return;
    }
    if (target.hasAttribute?.("data-setting-link-confirmation")) {
      controller.setLinkConfirmation(target.value); return;
    }
    const name = target.getAttribute?.("data-setting-field");
    const field = controller.snapshot()?.setting.fields.find((item) => item.name === name);
    if (!field) return;
    let value = target.value;
    if (field.kind === "boolean") value = target.checked;
    if (field.kind === "integer") value = /^-?\d+$/.test(value) ? Number(value) : NaN;
    if (field.kind === "enum") value = field.choices[Number(value)]?.value;
    if (field.kind === "identifiers") value = target.hasAttribute?.("data-setting-choice")
      ? [...root.querySelectorAll(`[data-setting-field="${field.name}"][data-setting-choice]`)]
        .filter((input) => input.checked).map((input) => field.choices[Number(input.getAttribute("data-setting-choice"))]?.value)
      : [...target.selectedOptions].map((option) => field.choices[Number(option.value)]?.value);
    if (controller.setValue(name, value) && name === "wlan_timerule" &&
        controller.snapshot()?.setting.id === "wifi_schedule" &&
        (pageMode || root.querySelector?.(".sp-settings-page"))) {
      // Change visibility in place: no rerender, draft clearing or router request.
      for (const group of root.querySelectorAll("[data-setting-schedule-group]")) {
        group.hidden = scheduleGroupHidden(group.getAttribute("data-setting-schedule-group"), value);
      }
    }
  };
  const clearDOMCredentials = () => {
    for (const input of root.querySelectorAll('input[type="password"], [data-setting-confirmation], [data-setting-link-confirmation]')) input.value = "";
  };
  const onClick = (event) => {
    const button = event.target?.closest?.("[data-setting-action]");
    if (!button || !root.contains(button) || button.disabled) return;
    event.preventDefault();
    const action = button.getAttribute("data-setting-action");
    if (!["load", "loadTargets", "refresh", "cancelChanges", "save", "close", "downloadCredentials", "finishLink"].includes(action)) return;
    if (action === "close") { clearDOMCredentials(); controller.close(); return; }
    Promise.resolve(controller[action]()).finally(clearDOMCredentials);
  };
  root.addEventListener("input", onInput);
  root.addEventListener("change", onInput);
  root.addEventListener("click", onClick);
  return () => {
    clearDOMCredentials();
    root.removeEventListener("input", onInput);
    root.removeEventListener("change", onInput);
    root.removeEventListener("click", onClick);
    controller.dispose();
  };
}
