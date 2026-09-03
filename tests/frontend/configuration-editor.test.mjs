import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

import {
  bindConfigurationEditor,
  createConfigurationEditorController,
  renderConfigurationEditor,
} from "../../custom_components/speedport_smart/frontend/configuration-editor.js";

const SETTING = {
  id: "example_settings", title: "Example settings", section: "network",
  warning: "Changing this may interrupt access.", confirmation: "SAVE SETTINGS",
  live_write_verified: false,
  fields: [
    {name: "enabled", label: "Enabled", kind: "boolean"},
    {name: "mode", label: "Mode", kind: "enum", choices: [{value: 0, label: "Normal"}, {value: 1, label: "Quiet"}]},
    {name: "count", label: "Count", kind: "integer", minimum: 0, maximum: 10},
    {name: "name", label: "Name", kind: "text", minimum: 1, maximum: 32},
    {name: "password", label: "Password", kind: "secret", minimum: 8, maximum: 64},
    {name: "start", label: "Start time", kind: "time"},
  ],
};
const VALUES = {enabled: true, mode: 0, count: 2, name: "Example", start: "12:30"};
const RESPONSE = {setting_id: SETTING.id, revision: "opaque-revision", expires_in: 120, values: VALUES};
test("unloaded and failed enum reads show no invented current option and cannot save", async () => {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(message); throw new Error("private backend detail");
  }});
  controller.open({entryId: "entry", setting: SETTING});
  const selected = () => renderConfigurationEditor(controller, {pageMode: true})
    .match(/<select[^>]*data-setting-field="mode"[^>]*>(.*?)<\/select>/s)?.[1];
  assert.match(selected(), /<option value="" disabled selected>Current value unavailable<\/option>/);
  assert.equal(await controller.load(), false);
  assert.match(selected(), /<option value="" disabled selected>Current value unavailable<\/option>/);
  assert.equal(controller.snapshot().loaded, false);
  assert.equal(controller.setValue("mode", 1), false);
  assert.equal(await controller.save(), false);
  assert.equal(calls.length, 1);
  assert.ok(!renderConfigurationEditor(controller).includes("private backend detail"));
});

test("successful enum read selects only its actual typed option without an unavailable placeholder", async () => {
  const controller = createConfigurationEditorController({request: async () => RESPONSE});
  controller.open({entryId: "entry", setting: SETTING});
  assert.equal(await controller.load(), true);
  const html = renderConfigurationEditor(controller, {pageMode: true});
  assert.ok(!html.includes("Current value unavailable"));
  assert.match(html, /<option value="0" selected>Normal<\/option>/);
});

test("failed target inventory preserves a safe missing-prerequisite reason without enabling an editor", async () => {
  let calls = 0;
  const controller = createConfigurationEditorController({request: async () => {
    calls++; throw Object.assign(new Error("PRIVATE-TARGET-DETAIL"), {code: "settings_prerequisites_unavailable"});
  }});
  controller.open({entryId: "entry", setting: {...SETTING, requires_target: true}});
  assert.equal(await controller.loadTargets(), false);
  assert.equal(controller.snapshot().status, "load_setting_unavailable");
  assert.deepEqual(controller.snapshot().targets, []);
  assert.equal(controller.snapshot().loaded, false);
  assert.equal(await controller.save(), false);
  assert.equal(calls, 1);
  const html = renderConfigurationEditor(controller);
  assert.ok(html.includes("required state or prerequisites"));
  assert.ok(!html.includes("PRIVATE-TARGET-DETAIL"));
  assert.match(html, /data-setting-action="save" disabled/);
});

for (const [code, status, explanation] of [
  ["management_unavailable", "load_management_unavailable", "management access is unavailable"],
  ["settings_busy", "load_busy", "Another router request is still running"],
  ["action_busy", "load_busy", "Another router request is still running"],
  ["rate_limited", "load_rate_limited", "requests too quickly"],
  ["setting_unavailable", "load_setting_unavailable", "required state or prerequisites"],
  ["settings_prerequisites_unavailable", "load_setting_unavailable", "required state or prerequisites"],
  ["settings_unavailable", "load_setting_unavailable", "required state or prerequisites"],
  ["bonding_managed_by_easy_support", "load_bonding_managed", "EasySupport manages bonding"],
  ["usb_disabled", "load_usb_disabled", "USB is disabled on this router"],
  ["tethering_unavailable_with_receiver", "load_tethering_receiver", "USB tethering is unavailable while the receiver is active"],
  ["system_mesh_unavailable", "load_mesh_unavailable", "No eligible Mesh target was returned"],
  ["system_mesh_local_update_only", "load_mesh_local_update_only", "Online firmware updates are unavailable for the eligible Mesh nodes"],
  ["system_firmware_managed_automatically", "load_firmware_managed", "Router or provider settings manage firmware automatically"],
  ["system_firmware_offer_unavailable", "load_firmware_offer_unavailable", "The router did not return a valid installable firmware offer"],
  ["vpn_key_rotation_unavailable", "load_vpn_key_rotation_unavailable", "requires IPsec mode and an existing IPsec peer"],
  ["system_smarthome_unavailable", "load_smarthome_unavailable", "already in the requested state or a state change is still in progress"],
  ["call_history_unavailable", "load_call_history_unavailable", "Missing data is not an empty list. Clearing remains disabled"],
  ["unreviewed_private_error", "load_failed", "could not be loaded"],
]) {
  test(`read failure ${code} retains only an actionable safe reason and no revision`, async () => {
    let calls = 0;
    const controller = createConfigurationEditorController({request: async () => {
      calls++;
      throw Object.assign(new Error("PRIVATE-SECRET-MESSAGE"), {code});
    }});
    controller.open({entryId: "entry", setting: SETTING});
    assert.equal(await controller.load(), false);
    assert.equal(controller.snapshot().status, status);
    assert.equal(controller.snapshot().loaded, false);
    assert.equal(await controller.save(), false);
    assert.equal(calls, 1);
    const html = renderConfigurationEditor(controller);
    assert.ok(html.includes(explanation));
    assert.ok(!html.includes("PRIVATE-SECRET-MESSAGE"));
    if (code === "system_firmware_offer_unavailable") assert.ok(!html.includes("up to date"));
    assert.match(html, /data-setting-action="save" disabled/);
  });
}

function deferred() {
  let resolve; let reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}

test("uppercase firmware field names remain usable", async () => {
  const setting = {...SETTING, fields: [{name: "other_MTU", label: "MTU", kind: "integer", minimum: 1440, maximum: 1492}]};
  const controller = createConfigurationEditorController({request: async () => ({...RESPONSE, values: {other_MTU: 1492}})});
  controller.open({entryId: "entry", setting});
  assert.equal(await controller.load(), true);
  assert.match(renderConfigurationEditor(controller), /other_MTU/);
});

const DYNAMIC_SETTING = {...SETTING, fields: [
  {name: "members", label: "Members", kind: "identifiers", minimum: 0, maximum: 2, dynamic_choices: true, choices: []},
  {name: "outgoing", label: "Outgoing number", kind: "enum", dynamic_choices: true, choices: []},
]};
const CHOICES = [{value: "a", label: "First"}, {value: "b", label: "<Second>"}];
const DYNAMIC_RESPONSE = {...RESPONSE, values: {members: ["a"], outgoing: "a"}, choices: {members: CHOICES, outgoing: CHOICES}};

test("fresh dynamic options support single and multiple selection", async () => {
  const sent = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    sent.push(structuredClone(message));
    return message.type.endsWith("/read") ? DYNAMIC_RESPONSE : {status: "verified"};
  }});
  controller.open({entryId: "entry", setting: DYNAMIC_SETTING});
  assert.equal(await controller.load(), true);
  assert.match(renderConfigurationEditor(controller), /select multiple/);
  assert.match(renderConfigurationEditor(controller), /&lt;Second&gt;/);
  const selection = ["b"];
  controller.setValue("members", selection);
  selection.push("unknown");
  controller.setValue("outgoing", "b");
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.deepEqual(sent[1].changes, {members: ["b"], outgoing: "b"});
});

for (const value of [["unknown"], ["a", "a"], ["a", "b", "c"], "a"]) {
  test(`dynamic selector rejects unreviewed membership ${JSON.stringify(value)}`, async () => {
    let requests = 0;
    const controller = createConfigurationEditorController({request: async () => {requests++; return DYNAMIC_RESPONSE;}});
    controller.open({entryId: "entry", setting: DYNAMIC_SETTING});
    await controller.load();
    controller.setValue("members", value);
    controller.setConfirmation("SAVE SETTINGS");
    assert.equal(await controller.save(), false);
    assert.equal(requests, 1);
  });
}

for (const choices of [{}, {members: CHOICES, outgoing: CHOICES, extra: CHOICES}, {members: CHOICES, outgoing: [CHOICES[0], CHOICES[0]]}]) {
  test("missing duplicate or extra dynamic schemas cannot load", async () => {
    const controller = createConfigurationEditorController({request: async () => ({...DYNAMIC_RESPONSE, choices})});
    controller.open({entryId: "entry", setting: DYNAMIC_SETTING});
    assert.equal(await controller.load(), false);
    assert.equal(controller.snapshot().loaded, false);
  });
}

test("unknown reconnect result shows recovery warning without success", async () => {
  const {controller} = await loaded(async () => ({status: "outcome_unknown", verification: "reconnect_required"}));
  controller.setValue("enabled", false);
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), false);
  assert.equal(controller.snapshot().status, "reconnect_unknown");
  assert.match(renderConfigurationEditor(controller), /did not confirm.*Reconnect/);
});
async function loaded(requestSave = async () => ({status: "verified"})) {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/read") ? RESPONSE : requestSave(message);
  }});
  controller.open({entryId: "entry-a", setting: SETTING});
  await controller.load();
  return {controller, calls};
}

test("opening and input never automatically read or write", async () => {
  let calls = 0;
  const controller = createConfigurationEditorController({request: async () => {calls++; return RESPONSE;}});
  controller.open({entryId: "entry-a", setting: SETTING});
  assert.equal(calls, 0);
  assert.equal(controller.setValue("name", "New"), false);
  assert.equal(await controller.save(), false);
  assert.match(renderConfigurationEditor(controller), /Load current settings/);
  await controller.load();
  controller.setValue("name", "New");
  assert.equal(calls, 1);
});

test("one confirmed save sends only dirty typed values with exact revision", async () => {
  const {controller, calls} = await loaded();
  controller.setValue("name", "New");
  controller.setValue("mode", 1);
  controller.setValue("count", 2);
  controller.setValue("enabled", false);
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.deepEqual(calls[1], {
    type: "speedport_smart/panel/settings/save", entry_id: "entry-a",
    setting_id: SETTING.id, revision: "opaque-revision",
    changes: {enabled: false, mode: 1, name: "New"}, confirmed: true,
    confirmation_text: "SAVE SETTINGS",
  });
  assert.equal(controller.snapshot().status, "verified");
  assert.equal(controller.snapshot().loaded, false);
  assert.equal(await controller.save(), false);
  assert.equal(calls.length, 2);
});

test("password never loads, renders, hashes, or remains after send", async () => {
  let messageReference;
  const controller = createConfigurationEditorController({request: async (message) => {
    if (message.type.endsWith("/read")) return {...RESPONSE, values: {...VALUES, password: "ROUTER-SHOULD-NOT-LEAK"}};
    messageReference = message;
    assert.equal(message.changes.password, "USER-SECRET-123");
    return {status: "secret_unverified"};
  }});
  controller.open({entryId: "entry-a", setting: SETTING});
  await controller.load();
  assert.equal(controller.snapshot().values.password, undefined);
  controller.setValue("password", "USER-SECRET-123");
  assert.doesNotMatch(JSON.stringify(controller.snapshot()), /USER-SECRET|ROUTER-SHOULD/);
  controller.setConfirmation("SAVE SETTINGS");
  await controller.save();
  assert.deepEqual(Object.keys(messageReference.changes), []);
  assert.equal(messageReference.confirmation_text, "");
  assert.equal(controller.snapshot().status, "secret_unverified");
  const html = renderConfigurationEditor(controller);
  assert.match(html, /Use HTTPS for Home Assistant when entering credentials/);
  assert.doesNotMatch(html, /USER-SECRET|ROUTER-SHOULD/);
  assert.match(html, /type="password"/);
  assert.doesNotMatch(html.match(/<input type="password"[^>]*>/)[0], /\svalue=/);
});

test("rerender clears hidden credentials and typed confirmation", async () => {
  const {controller, calls} = await loaded();
  controller.setValue("password", "USER-SECRET-123");
  controller.setConfirmation("SAVE SETTINGS");
  renderConfigurationEditor(controller);
  assert.equal(controller.snapshot().confirmationReady, false);
  assert.equal(controller.snapshot().dirty.includes("password"), false);
  assert.equal(await controller.save(), false);
  assert.equal(calls.length, 1);
});

test("confirmation is exact and no-op save makes no router request", async () => {
  const {controller, calls} = await loaded();
  controller.setValue("enabled", false);
  for (const phrase of ["save settings", "SAVE SETTINGS ", ""]) {
    controller.setConfirmation(phrase);
    assert.equal(await controller.save(), false);
  }
  controller.setValue("enabled", true);
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.equal(calls.length, 1);
});

for (const [name, value] of [["mode", "1"], ["enabled", "false"], ["count", 1.5], ["count", 11],
  ["name", ""], ["password", "********"], ["password", "[REDACTED]"], ["start", "25:00"]]) {
  test(`reject invalid ${name} value without sending`, async () => {
    const {controller, calls} = await loaded();
    controller.setValue(name, value); controller.setConfirmation("SAVE SETTINGS");
    assert.equal(await controller.save(), false);
    assert.equal(controller.snapshot().status, "invalid");
    assert.equal(calls.length, 1);
  });
}

test("read expires without timers or automatic retries", async () => {
  let clock = 0; let calls = 0;
  const controller = createConfigurationEditorController({now: () => clock, request: async () => {calls++; return RESPONSE;}});
  controller.open({entryId: "entry-a", setting: SETTING}); await controller.load();
  controller.setValue("enabled", false); controller.setConfirmation("SAVE SETTINGS");
  clock = 120001;
  assert.equal(await controller.save(), false);
  assert.equal(controller.snapshot().status, "expired");
  assert.equal(calls, 1);
});

test("late read cannot repopulate closed or different-router editor", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: () => response.promise});
  controller.open({entryId: "entry-a", setting: SETTING});
  const load = controller.load();
  controller.open({entryId: "entry-b", setting: SETTING});
  response.resolve(RESPONSE);
  assert.equal(await load, false);
  assert.equal(controller.snapshot().entryId, "entry-b");
  assert.equal(controller.snapshot().status, "idle");
  assert.deepEqual(controller.snapshot().values, {});
  controller.close(); assert.equal(controller.snapshot(), null);
});

test("late save cannot alter new session; repeated clicks do not duplicate", async () => {
  const response = deferred();
  const {controller, calls} = await loaded(() => response.promise);
  controller.setValue("enabled", false); controller.setConfirmation("SAVE SETTINGS");
  const save = controller.save();
  assert.equal(await controller.save(), false);
  controller.open({entryId: "entry-b", setting: SETTING});
  response.resolve({status: "verified"});
  assert.equal(await save, false);
  assert.equal(controller.snapshot().status, "idle");
  assert.equal(calls.length, 2);
});

for (const [code, status] of [["command_rejected", "rejected"], ["stale_settings", "rejected"], ["invalid_settings", "rejected"], ["outcome_unknown", "outcome_unknown"], ["network_error", "outcome_unknown"]]) {
  test(`${code} clears secret, does not retry, requires fresh read`, async () => {
    const {controller, calls} = await loaded(async () => {throw {code, message: "PRIVATE ROUTER PASSWORD"};});
    controller.setValue("password", "USER-SECRET-123"); controller.setConfirmation("SAVE SETTINGS");
    assert.equal(await controller.save(), false);
    assert.equal(controller.snapshot().status, status);
    assert.equal(controller.snapshot().loaded, false);
    assert.equal(await controller.save(), false);
    assert.equal(calls.length, 2);
    assert.doesNotMatch(renderConfigurationEditor(controller), /PRIVATE ROUTER|USER-SECRET/);
  });
}

test("malformed and mismatched reads fail closed without partial form values", async () => {
  for (const response of [{...RESPONSE, setting_id: "wrong"}, {...RESPONSE, revision: null},
    {...RESPONSE, expires_in: 0}, {...RESPONSE, values: {...VALUES, start: "bad"}}]) {
    const controller = createConfigurationEditorController({request: async () => response});
    controller.open({entryId: "entry-a", setting: SETTING});
    assert.equal(await controller.load(), false);
    assert.equal(controller.snapshot().status, "load_failed");
    assert.deepEqual(controller.snapshot().values, {});
  }
});

test("schema rejects unknown types, duplicate fields and prototype keys", () => {
  for (const fields of [[{name: "constructor", kind: "text"}], [{name: "a", kind: "html"}],
    [{name: "a", kind: "text"}, {name: "a", kind: "text"}], [{name: "a", kind: "enum", choices: []}]]) {
    const controller = createConfigurationEditorController({request: async () => RESPONSE});
    assert.throws(() => controller.open({entryId: "entry-a", setting: {...SETTING, fields}}), /invalid_schema/);
  }
});

test("render escapes every metadata value and inherits HA responsive styling", async () => {
  const controller = createConfigurationEditorController({request: async () => RESPONSE});
  controller.open({entryId: "entry-a", setting: {...SETTING,
    title: '<img src=x onerror="evil()">', warning: "<script>evil()</script>",
    fields: SETTING.fields.map((field) => ({...field, label: '<img src=x>', description: '" onfocus="evil()'}))}});
  await controller.load();
  controller.setValue("name", '"><script>evil()</script>');
  const html = renderConfigurationEditor(controller);
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /grid-template-columns:repeat\(auto-fit/);
  assert.match(html, /var\(--primary-text-color\)/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /label for="sp-setting-example_settings-name"/);
  assert.match(html, /aria-describedby="sp-setting-example_settings-name-help"/);
});

test("binder disposes listeners and clears credential DOM on navigation", async () => {
  const {controller} = await loaded();
  const listeners = new Map();
  const password = {value: "USER-SECRET-123"};
  const confirmation = {value: "SAVE SETTINGS"};
  const root = {
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: (name, handler) => {assert.equal(listeners.get(name), handler); listeners.delete(name);},
    querySelectorAll: () => [password, confirmation], contains: () => true,
  };
  const dispose = bindConfigurationEditor(root, controller);
  assert.equal(listeners.size, 3);
  dispose();
  assert.equal(listeners.size, 0);
  assert.equal(password.value, ""); assert.equal(confirmation.value, "");
  assert.equal(controller.snapshot(), null);
});

test("source has no polling, storage, fetch or router-control services", () => {
  const source = readFileSync(new URL("../../custom_components/speedport_smart/frontend/configuration-editor.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /localStorage|sessionStorage|setInterval|\bfetch\(|callService/);
  assert.equal((source.match(/setTimeout\(/g) || []).length, 2, "only private credential and pending phonebook approval expiry may schedule timers");
});

const TARGET_SETTING = {...SETTING, requires_target: true};
const TARGETS = {setting_id: SETTING.id, targets: [{id: "7", label: "Share"}, {id: "8", label: "Share"}]};

test("targets require explicit discovery, selection, read and confirmed save", async () => {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    if (message.type.endsWith("/targets")) return TARGETS;
    if (message.type.endsWith("/read")) return {...RESPONSE, target_id: message.target_id};
    return {status: "verified"};
  }});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  assert.equal(calls.length, 0);
  assert.equal(await controller.load(), false);
  assert.equal(await controller.save(), false);
  assert.equal(calls.length, 0);
  assert.equal(await controller.loadTargets(), true);
  assert.equal(controller.snapshot().targetId, null);
  assert.equal(controller.selectTarget("999"), false);
  assert.equal(controller.selectTarget("7"), true);
  assert.equal(calls.length, 1);
  assert.equal(await controller.load(), true);
  assert.deepEqual(calls[1], {type: "speedport_smart/panel/settings/read", entry_id: "entry-a",
    setting_id: SETTING.id, target_id: "7"});
  controller.setValue("name", "Changed"); controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.equal(calls[2].target_id, "7");
  assert.equal(calls[2].revision, "opaque-revision");
});

test("target changes erase revisions, credentials and drafts without a request", async () => {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/targets") ? TARGETS : RESPONSE;
  }});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  await controller.loadTargets(); controller.selectTarget("7"); await controller.load();
  controller.setValue("password", "USER-SECRET-123"); controller.setValue("name", "Draft");
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(controller.selectTarget("8"), true);
  assert.equal(calls.length, 2);
  const view = controller.snapshot();
  assert.equal(view.revision, null); assert.equal(view.loaded, false);
  assert.deepEqual(view.values, {}); assert.deepEqual(view.dirty, []);
  assert.equal(view.confirmationReady, false);
  assert.equal(await controller.save(), false);
});

test("late target read cannot populate a newly selected target", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: (message) =>
    message.type.endsWith("/targets") ? Promise.resolve(TARGETS) : response.promise});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  await controller.loadTargets(); controller.selectTarget("7");
  const pending = controller.load();
  controller.selectTarget("8");
  response.resolve({...RESPONSE, target_id: "7"});
  assert.equal(await pending, false);
  assert.equal(controller.snapshot().targetId, "8");
  assert.equal(controller.snapshot().loaded, false);
});

test("late target inventory cannot repopulate another router or closed editor", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: () => response.promise});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  const pending = controller.loadTargets();
  controller.open({entryId: "entry-b", setting: TARGET_SETTING});
  response.resolve(TARGETS);
  assert.equal(await pending, false);
  assert.deepEqual(controller.snapshot().targets, []);
  assert.equal(controller.snapshot().entryId, "entry-b");
});

test("malformed, duplicate and empty target lists fail safely", async () => {
  for (const targets of [[{id: "-1", label: "New"}], [{id: "7", label: "Share"}, {id: "7", label: "Duplicate"}],
    [{id: "7", label: ""}], [{id: 7, label: "Share"}], [{id: "../7", label: "Share"}]]) {
    const controller = createConfigurationEditorController({request: async () => ({setting_id: SETTING.id, targets})});
    controller.open({entryId: "entry-a", setting: TARGET_SETTING});
    assert.equal(await controller.loadTargets(), false);
    assert.deepEqual(controller.snapshot().targets, []);
    assert.equal(controller.snapshot().targetId, null);
  }
  const controller = createConfigurationEditorController({request: async () => ({setting_id: SETTING.id, targets: []})});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  assert.equal(await controller.loadTargets(), true);
  assert.equal(controller.snapshot().status, "targets_empty");
  assert.equal(await controller.load(), false);
});

test("target labels are escaped and duplicate names include exact identity", async () => {
  const controller = createConfigurationEditorController({request: async () => ({...TARGETS,
    targets: TARGETS.targets.map((target) => ({...target, label: '<img src=x onerror="evil()">'}))})});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING}); await controller.loadTargets();
  const html = renderConfigurationEditor(controller);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.match(html, /\(7\)/); assert.match(html, /\(8\)/);
  assert.match(html, /label for="sp-setting-example_settings-target"/);
  assert.match(html, /Load available targets/);
});

test("mismatched target result cannot create a usable revision", async () => {
  const controller = createConfigurationEditorController({request: async (message) =>
    message.type.endsWith("/targets") ? TARGETS : {...RESPONSE, target_id: "8"}});
  controller.open({entryId: "entry-a", setting: TARGET_SETTING});
  await controller.loadTargets(); controller.selectTarget("7");
  assert.equal(await controller.load(), false);
  assert.equal(controller.snapshot().revision, null);
});

test("page opening reads once but input, rerender and successful save never auto-repeat", async () => {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/read") ? RESPONSE : {status: "verified"};
  }});
  assert.equal(await controller.open({entryId: "entry-a", setting: SETTING, autoLoad: true}), true);
  assert.equal(controller.snapshot().autoLoad, true);
  assert.equal(controller.snapshot().isBusy, false);
  assert.equal(calls.length, 1);
  renderConfigurationEditor(controller, {pageMode: true});
  controller.setValue("name", "Page draft");
  assert.equal(controller.snapshot().isDirty, true);
  assert.equal(calls.length, 1);
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.deepEqual(calls.map((call) => call.type.split("/").at(-1)), ["read", "save"]);
  assert.equal(controller.snapshot().isDirty, false, "submitted values are not unsaved drafts");
  assert.equal(await controller.save(), false);
  assert.equal(calls.length, 2);
});

test("automatic target discovery serializes before the first exact-target read", async () => {
  const inventory = deferred();
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/targets") ? inventory.promise : {...RESPONSE, target_id: message.target_id};
  }});
  const opening = controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
  assert.equal(controller.snapshot().status, "targets_loading");
  assert.equal(controller.snapshot().isBusy, true);
  assert.equal(controller.snapshot().isSaving, false);
  assert.equal(await controller.refresh(), false);
  assert.equal(calls.length, 1);
  inventory.resolve(TARGETS);
  assert.equal(await opening, true);
  assert.deepEqual(calls.map((call) => call.type.split("/").at(-1)), ["targets", "read"]);
  assert.equal(calls[1].target_id, "7");
  assert.equal(controller.snapshot().targetId, "7");
  assert.equal(controller.snapshot().loaded, true);
});

test("automatic target opening honors a requested identity without fallback", async () => {
  for (const targetId of ["8", "missing", "../7"]) {
    const calls = [];
    const controller = createConfigurationEditorController({request: async (message) => {
      calls.push(message);
      return message.type.endsWith("/targets") ? TARGETS : {...RESPONSE, target_id: message.target_id};
    }});
    assert.equal(await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true, targetId}), targetId === "8");
    assert.equal(calls.length, targetId === "8" ? 2 : 1);
    assert.equal(controller.snapshot().targetId, targetId === "8" ? "8" : null);
  }
});

test("empty or malformed automatic inventories do not cause guessed target reads", async () => {
  for (const result of [{...TARGETS, targets: []}, {...TARGETS, setting_id: "wrong"},
    {...TARGETS, targets: [{id: "7", label: "A"}, {id: "7", label: "B"}]}]) {
    const calls = [];
    const controller = createConfigurationEditorController({request: async (message) => {calls.push(message); return result;}});
    assert.equal(await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true}), false);
    assert.equal(calls.length, 1);
    assert.equal(controller.snapshot().loaded, false);
    assert.equal(controller.snapshot().targetId, null);
  }
});

test("late automatic inventory cannot start a read after another page opens", async () => {
  const inventory = deferred();
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.entry_id === "old" ? inventory.promise : RESPONSE;
  }});
  const stale = controller.open({entryId: "old", setting: TARGET_SETTING, autoLoad: true});
  await controller.open({entryId: "new", setting: SETTING, autoLoad: true});
  inventory.resolve(TARGETS);
  assert.equal(await stale, false);
  assert.equal(controller.snapshot().entryId, "new");
  assert.equal(controller.snapshot().loaded, true);
  assert.deepEqual(calls.map((call) => [call.entry_id, call.type.split("/").at(-1)]), [["old", "targets"], ["new", "read"]]);
});

test("rapid automatic target changes discard the older current-value response", async () => {
  const first = deferred();
  const second = deferred();
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    if (message.type.endsWith("/targets")) return TARGETS;
    return message.target_id === "7" ? first.promise : second.promise;
  }});
  const opening = controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.equal(controller.snapshot().targetId, "7");
  assert.equal(controller.snapshot().busy, true);
  const changing = controller.selectTarget("8");
  assert.equal(controller.selectTarget("8"), true, "duplicate DOM input/change events do not read twice");
  first.resolve({...RESPONSE, target_id: "7", values: {...VALUES, name: "Stale target"}});
  assert.equal(await opening, false);
  assert.equal(controller.snapshot().targetId, "8");
  assert.deepEqual(controller.snapshot().values, {});
  second.resolve({...RESPONSE, target_id: "8", values: {...VALUES, name: "Current target"}});
  assert.equal(await changing, true);
  assert.equal(controller.snapshot().values.name, "Current target");
  assert.equal(calls.length, 3);
});

test("automatic target switch erases secret drafts and confirmation before read", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: async (message) => {
    if (message.type.endsWith("/targets")) return TARGETS;
    return message.target_id === "7" ? {...RESPONSE, target_id: "7"} : response.promise;
  }});
  await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
  controller.setValue("password", "PRIVATE-DRAFT-123");
  controller.setValue("name", "Unsaved"); controller.setConfirmation("SAVE SETTINGS");
  const changing = controller.selectTarget("8");
  assert.equal(controller.snapshot().isDirty, false);
  assert.equal(controller.snapshot().confirmationReady, false);
  assert.equal(controller.snapshot().revision, null);
  assert.deepEqual(controller.snapshot().values, {});
  response.resolve({...RESPONSE, target_id: "8"});
  await changing;
});

test("Refresh rediscovers targets and preserves exact selection; vanished target is not substituted", async () => {
  let targets = TARGETS;
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/targets") ? targets : {...RESPONSE, target_id: message.target_id};
  }});
  await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true, targetId: "8"});
  assert.equal(await controller.refresh(), true);
  assert.equal(calls[3].target_id, "8");
  targets = {...TARGETS, targets: [TARGETS.targets[0]]};
  assert.equal(await controller.refresh(), false);
  assert.equal(calls.length, 5);
  assert.equal(controller.snapshot().targetId, null);
  assert.equal(controller.snapshot().loaded, false);
  assert.equal(controller.snapshot().status, "target_required");
});

test("automatic load failure and expired revisions never trigger retries or writes", async () => {
  let clock = 0;
  let fail = true;
  const calls = [];
  const controller = createConfigurationEditorController({now: () => clock, request: async (message) => {
    calls.push(message);
    if (fail) throw new Error("PRIVATE ROUTER ERROR");
    return RESPONSE;
  }});
  assert.equal(await controller.open({entryId: "entry-a", setting: SETTING, autoLoad: true}), false);
  assert.equal(controller.snapshot().status, "load_failed");
  assert.equal(calls.length, 1);
  fail = false;
  await controller.refresh();
  controller.setValue("enabled", false); controller.setConfirmation("SAVE SETTINGS");
  clock = 120001;
  assert.equal(await controller.save(), false);
  assert.equal(controller.snapshot().status, "expired");
  assert.equal(calls.length, 2);
});

test("disposing page during automatic read clears state and ignores late data", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: () => response.promise});
  const opening = controller.open({entryId: "entry-a", setting: SETTING, autoLoad: true});
  controller.dispose(); response.resolve(RESPONSE);
  assert.equal(await opening, false);
  assert.equal(controller.snapshot(), null);
});

test("Cancel changes restores baseline locally without extending revision lifetime", async () => {
  let clock = 0; let calls = 0;
  const controller = createConfigurationEditorController({now: () => clock, request: async () => {calls++; return RESPONSE;}});
  await controller.open({entryId: "entry-a", setting: SETTING, autoLoad: true});
  controller.setValue("name", "Unsaved"); controller.setValue("password", "PRIVATE-DRAFT-123");
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(controller.snapshot().isDirty, true);
  clock = 60000;
  assert.equal(controller.cancelChanges(), true);
  assert.deepEqual(controller.snapshot().values, VALUES);
  assert.equal(controller.snapshot().isDirty, false);
  assert.equal(controller.snapshot().confirmationReady, false);
  assert.equal(controller.snapshot().revision, RESPONSE.revision);
  assert.equal(calls, 1);
  clock = 120001;
  assert.equal(controller.snapshot().expired, true);
});

test("Cancel and target navigation cannot interrupt an in-flight confirmed save", async () => {
  const response = deferred();
  const controller = createConfigurationEditorController({request: async (message) => {
    if (message.type.endsWith("/targets")) return TARGETS;
    return message.type.endsWith("/read") ? {...RESPONSE, target_id: message.target_id} : response.promise;
  }});
  await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
  controller.setValue("name", "Changed"); controller.setConfirmation("SAVE SETTINGS");
  const saving = controller.save();
  assert.equal(controller.snapshot().isSaving, true);
  assert.equal(controller.cancelChanges(), false);
  assert.equal(controller.selectTarget("8"), false);
  assert.equal(await controller.refresh(), false);
  response.resolve({status: "verified"}); await saving;
});

test("page mode exposes Refresh Save Cancel without manual loading or Close wall", async () => {
  const {controller} = await loaded();
  const html = renderConfigurationEditor(controller, {pageMode: true});
  assert.match(html, /data-setting-action="refresh"[^>]*>Refresh/);
  assert.match(html, /data-setting-action="save"[^>]*>Save changes/);
  assert.match(html, /data-setting-action="cancelChanges"[^>]*>Cancel changes/);
  assert.doesNotMatch(html, /data-setting-action="(?:load|loadTargets|close)"/);
  assert.match(html, /<fieldset class="sp-settings-group"><legend>Credentials/);
  assert.match(html, /data-setting-confirmation/);
  assert.match(html, /type="time"[^>]*data-setting-field="start"/);
  assert.match(html, /sp-settings-check/);
});

test("Wi-Fi identity groups each band before shared security without hidden credentials", async () => {
  const fields = [
    {name: "wlan_ssid", label: "2.4 GHz name", kind: "text"},
    {name: "wlan_5ghz_ssid", label: "5 GHz name", kind: "text"},
    {name: "wlan_wpa_key", label: "Shared password", kind: "secret"},
    {name: "wlan_visible", label: "Broadcast 2.4 GHz", kind: "boolean"},
    {name: "wlan_5ghz_visible", label: "Broadcast 5 GHz", kind: "boolean"},
    {name: "wlan_enc", label: "Security", kind: "enum", choices: [{value: "5", label: "WPA2/WPA3"}]},
  ];
  const values = {wlan_ssid: "First", wlan_visible: true, wlan_5ghz_ssid: "Second", wlan_5ghz_visible: false, wlan_enc: "5"};
  const controller = createConfigurationEditorController({request: async () => ({...RESPONSE, setting_id: "wifi_identity", values})});
  await controller.open({entryId: "entry-a", setting: {...SETTING, id: "wifi_identity", fields}, autoLoad: true});
  const html = renderConfigurationEditor(controller, {pageMode: true});
  const two = html.indexOf("<legend>2.4 GHz network");
  const five = html.indexOf("<legend>5 GHz network");
  const security = html.indexOf("<legend>Shared security and password");
  assert.ok(two < five && five < security);
  assert.ok(html.indexOf('data-setting-field="wlan_visible"') < five);
  assert.ok(html.indexOf('data-setting-field="wlan_5ghz_visible"') < security);
  assert.ok(html.indexOf('data-setting-field="wlan_wpa_key"') > security);
  assert.doesNotMatch(html.match(/<input type="password"[^>]*>/)[0], /\svalue=/);
});

const INTERNET_ACCESS_FIELDS = ["isp_selection", "t_number", "t_mbnr0", "t_mbnr1", "t_mbnr2", "t_mbnr3",
  "t_password", "t_callident", "zustart_user", "zustart_password", "other_name", "other_user", "other_password",
  "other_MTU", "other_vlan", "other_vlanid", "other_ip", "fixed_ipv4_address"];
const INTERNET_DNS_FIELDS = ["other_dns", "dns_ipv4_primary", "dns_ipv4_secondary", "other_dns6", "other_dns6_prim", "other_dns6_sek"];
function pageField(name) {
  const choices = {isp_selection: ["0", "89", "1", "99"], led_mode: ["0", "1"], wlan_band: ["0", "1", "2"], wlan_power: ["0", "1", "2"]}[name];
  if (choices) return {name, label: name, kind: "enum", choices: choices.map((value) => ({value, label: `${name} ${value}`}))};
  const kind = name.endsWith("password") || name === "new_secret" ? "secret" :
    ["other_vlan", "other_ip", "other_dns", "other_dns6", "use_wlan", "use_usb"].includes(name) ? "boolean" :
      ["other_MTU", "other_vlanid"].includes(name) ? "integer" : "text";
  return {name, label: name, kind};
}
function pageGroups(html) {
  return new Map(html.split('<fieldset class="sp-settings-group">').slice(1).map((chunk) =>
    [chunk.match(/^<legend>([^<]+)<\/legend>/)[1], [...chunk.matchAll(/data-setting-field="([^"]+)"/g)].map((match) => match[1])]));
}
async function groupedPage(settingId, fields, supplied = {}) {
  const values = Object.fromEntries(fields.map((field) => [field.name,
    field.kind === "boolean" ? true : field.kind === "integer" ? 1 : field.kind === "enum" ? field.choices[0].value :
      field.kind === "secret" ? "PRIVATE-RESPONSE-SECRET" : "Existing"]));
  Object.assign(values, supplied);
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/read") ? {...RESPONSE, setting_id: settingId, values} : {status: "verified"};
  }});
  await controller.open({entryId: "entry-a", setting: {...SETTING, id: settingId, fields}, autoLoad: true});
  assert.equal(controller.snapshot().loaded, true);
  return {controller, html: renderConfigurationEditor(controller, {pageMode: true}), calls};
}

test("Internet page separates native Access data and DNS server with every declared field once", async () => {
  const fields = [...INTERNET_DNS_FIELDS, ...INTERNET_ACCESS_FIELDS].map(pageField);
  const {controller, html, calls} = await groupedPage("internet_connection", fields);
  const groups = pageGroups(html);
  assert.deepEqual([...groups.keys()], ["Access data", "DNS server"]);
  assert.deepEqual(groups.get("Access data"), INTERNET_ACCESS_FIELDS);
  assert.deepEqual(groups.get("DNS server"), INTERNET_DNS_FIELDS);
  const rendered = [...groups.values()].flat();
  assert.equal(rendered.length, fields.length);
  assert.equal(new Set(rendered).size, fields.length);
  assert.deepEqual([...rendered].sort(), fields.map((field) => field.name).sort());
  assert.doesNotMatch(html, /PRIVATE-RESPONSE-SECRET/);
  assert.equal((html.match(/<input type="password"/g) ?? []).length, 3);
  for (const input of html.match(/<input type="password"[^>]*>/g)) assert.doesNotMatch(input, /\svalue=/);
  assert.equal(controller.snapshot().values.t_password, undefined);
  assert.equal(controller.snapshot().values.other_password, undefined);
  assert.deepEqual(controller.snapshot().setting.fields.find((field) => field.name === "isp_selection").choices.map((choice) => choice.value), ["0", "89", "1", "99"]);
  assert.equal(calls.length, 1);
});

test("native page groups omit absent sections and leave unknown fields visible exactly once", async () => {
  for (const id of ["internet_connection", "system_led_schedule", "system_energy"]) {
    const fields = [pageField("future_native_flag"), pageField("new_secret")];
    const {html} = await groupedPage(id, fields);
    assert.deepEqual([...pageGroups(html)], [["Settings", ["future_native_flag"]], ["Credentials", ["new_secret"]]]);
    assert.doesNotMatch(html, /PRIVATE-RESPONSE-SECRET/);
  }
  const {html} = await groupedPage("internet_connection", [pageField("dns_ipv4_primary"), pageField("other_dns_future"), pageField("new_secret")]);
  assert.deepEqual([...pageGroups(html)], [["DNS server", ["dns_ipv4_primary"]], ["Settings", ["other_dns_future"]], ["Credentials", ["new_secret"]]]);
  assert.doesNotMatch(html, /<legend>Access data/);
});

test("LED page keeps mode and both native time fields together without changing24:00", async () => {
  const fields = ["led_mode", "led_from", "led_to"].map(pageField);
  const {controller, html} = await groupedPage("system_led_schedule", fields, {led_mode: "1", led_from: "22:00", led_to: "24:00"});
  assert.deepEqual([...pageGroups(html)], [["Display mode for LEDs", ["led_mode", "led_from", "led_to"]]]);
  assert.match(html, /data-setting-field="led_to"[^>]*value="24:00"/);
  assert.equal(controller.snapshot().values.led_to, "24:00");
  assert.doesNotMatch(html, /data-setting-schedule-group/);
});

test("energy page separates the native Wi-Fi network and USB port without duplicate controls", async () => {
  const fields = ["use_usb", "use_wlan", "wlan_band", "wlan_power", "future_energy_option"].map(pageField);
  const {html} = await groupedPage("system_energy", fields);
  assert.deepEqual([...pageGroups(html)], [["Wi-Fi network", ["use_wlan", "wlan_band", "wlan_power"]],
    ["USB port", ["use_usb"]], ["Settings", ["future_energy_option"]]]);
  assert.equal((html.match(/data-setting-field=/g) ?? []).length, fields.length);
});

test("native grouping does not alter secret lifecycle, draft changes or save payload", async () => {
  const {controller, calls} = await groupedPage("internet_connection", [...INTERNET_ACCESS_FIELDS, ...INTERNET_DNS_FIELDS].map(pageField));
  controller.setValue("other_user", "Changed PPPoE user");
  controller.setValue("other_password", "PRIVATE-ENTERED-SECRET");
  const html = renderConfigurationEditor(controller, {pageMode: true});
  assert.doesNotMatch(html, /PRIVATE-ENTERED-SECRET|PRIVATE-RESPONSE-SECRET/);
  assert.equal(controller.snapshot().values.other_user, "Changed PPPoE user");
  assert.deepEqual(controller.snapshot().dirty, ["other_user"]);
  controller.setValue("other_password", "New explicit password");
  controller.setValue("dns_ipv4_primary", "192.0.2.53");
  controller.setConfirmation("SAVE SETTINGS");
  assert.equal(await controller.save(), true);
  assert.deepEqual(calls[1].changes, {other_user: "Changed PPPoE user", other_password: "New explicit password", dns_ipv4_primary: "192.0.2.53"});
  assert.match(html, /data-setting-action="refresh"/);
  assert.match(html, /data-setting-action="save"/);
  assert.match(html, /data-setting-action="cancelChanges"/);
});

test("legacy rendering remains ungrouped and preserves native metadata order", async () => {
  const fields = ["other_dns", "other_user", "other_password", "dns_ipv4_primary"].map(pageField);
  const {controller} = await groupedPage("internet_connection", fields);
  const html = renderConfigurationEditor(controller);
  assert.deepEqual([...html.matchAll(/data-setting-field="([^"]+)"/g)].map((match) => match[1]), fields.map((field) => field.name));
  assert.doesNotMatch(html, /<fieldset class="sp-settings-group"/);
  assert.doesNotMatch(html, /PRIVATE-RESPONSE-SECRET/);
});

test("weekly time sections retain blank windows and 24:00 endpoints", async () => {
  const fields = [
    {name: "wlan_timerule", label: "Mode", kind: "enum", choices: [{value: "2", label: "Weekly"}]},
    ...["mo", "di"].flatMap((day) => ["from", "to"].map((suffix) => ({name: `wlan_time_${day}_${suffix}`,
      label: `${day} ${suffix}`, kind: "text", maximum: 5, description: "HH:MM; 24:00 is allowed for end times"}))),
  ];
  const values = {wlan_timerule: "2", wlan_time_mo_from: "08:00", wlan_time_mo_to: "24:00", wlan_time_di_from: "", wlan_time_di_to: ""};
  const controller = createConfigurationEditorController({request: async () => ({...RESPONSE, setting_id: "wifi_schedule", values})});
  await controller.open({entryId: "entry-a", setting: {...SETTING, id: "wifi_schedule", fields}, autoLoad: true});
  const html = renderConfigurationEditor(controller, {pageMode: true});
  assert.match(html, /<legend>Monday<\/legend>/);
  assert.match(html, /<legend>Tuesday<\/legend>/);
  assert.match(html, /type="time"[^>]*data-setting-field="wlan_time_mo_from"/);
  assert.match(html, /type="text"[^>]*data-setting-field="wlan_time_mo_to"[^>]*value="24:00"/);
  assert.match(html, /data-setting-field="wlan_time_di_from"[^>]*value=""/);
  assert.deepEqual(controller.snapshot().values, values);
});

test("page small selections render accessible checkbox choices with escaped labels", async () => {
  const controller = createConfigurationEditorController({request: async () => DYNAMIC_RESPONSE});
  await controller.open({entryId: "entry-a", setting: DYNAMIC_SETTING, autoLoad: true});
  const html = renderConfigurationEditor(controller, {pageMode: true});
  assert.match(html, /data-setting-field="members" data-setting-choice="0" checked/);
  assert.match(html, /for="sp-setting-example_settings-members-1"/);
  assert.match(html, /&lt;Second&gt;/);
  assert.doesNotMatch(html, /<Second>/);
});

test("page binder reads checkbox selections and Cancel clears DOM without router I/O", async () => {
  let calls = 0;
  const controller = createConfigurationEditorController({request: async () => {calls++; return DYNAMIC_RESPONSE;}});
  await controller.open({entryId: "entry-a", setting: DYNAMIC_SETTING, autoLoad: true});
  const listeners = new Map();
  const inputs = [0, 1].map((index) => ({checked: index === 1,
    hasAttribute: (name) => name === "data-setting-choice",
    getAttribute: (name) => name === "data-setting-field" ? "members" : String(index)}));
  const confirmation = {value: "SAVE SETTINGS"};
  const root = {contains: () => true,
    addEventListener: (name, callback) => listeners.set(name, callback),
    removeEventListener: (name) => listeners.delete(name),
    querySelectorAll: (selector) => selector.startsWith("[data-setting-field=") ? inputs : [confirmation]};
  const dispose = bindConfigurationEditor(root, controller);
  listeners.get("change")({target: inputs[1]});
  assert.deepEqual(controller.snapshot().values.members, ["b"]);
  listeners.get("click")({preventDefault() {}, target: {closest: () => ({disabled: false, getAttribute: () => "cancelChanges"})}});
  await Promise.resolve();
  assert.deepEqual(controller.snapshot().values.members, ["a"]);
  assert.equal(confirmation.value, "");
  assert.equal(calls, 1);
  dispose();
});

test("page target picker keeps dirty draft, credentials and selection when discard is declined", async () => {
  const calls = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    calls.push(structuredClone(message));
    return message.type.endsWith("/targets") ? TARGETS : {...RESPONSE, target_id: message.target_id};
  }});
  await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
  controller.setValue("name", "Keep this draft");
  controller.setValue("password", "PRIVATE-DRAFT-123");
  controller.setConfirmation("SAVE SETTINGS");
  const listeners = new Map();
  const password = {value: "PRIVATE-DRAFT-123"};
  const picker = {value: "1", hasAttribute: (name) => name === "data-setting-target"};
  const root = {contains: () => true, querySelectorAll: () => [password],
    addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener() {}};
  let confirmations = 0;
  const dispose = bindConfigurationEditor(root, controller, {pageMode: true, confirmDiscard: () => {confirmations++; return false;}});
  listeners.get("change")({target: picker});
  assert.equal(confirmations, 1);
  assert.equal(picker.value, "0");
  assert.equal(controller.snapshot().targetId, "7");
  assert.equal(controller.snapshot().values.name, "Keep this draft");
  assert.equal(controller.snapshot().confirmationReady, true);
  assert.ok(controller.snapshot().dirty.includes("password"));
  assert.equal(password.value, "PRIVATE-DRAFT-123");
  assert.equal(calls.length, 2);
  dispose();
});

for (const mode of ["accepted", "failed", "clean", "legacy", "page-marker"]) {
  test(`target discard protection handles ${mode} without implicit writes`, async () => {
    const calls = [];
    const controller = createConfigurationEditorController({request: async (message) => {
      calls.push(structuredClone(message));
      return message.type.endsWith("/targets") ? TARGETS : {...RESPONSE, target_id: message.target_id};
    }});
    await controller.open({entryId: "entry-a", setting: TARGET_SETTING, autoLoad: true});
    if (mode !== "clean") controller.setValue("name", "Unsaved");
    const listeners = new Map();
    const password = {value: "PRIVATE-DRAFT-123"};
    const picker = {value: "1", hasAttribute: (name) => name === "data-setting-target"};
    const root = {contains: () => true, querySelectorAll: () => [password],
      querySelector: () => mode === "page-marker" ? {} : null,
      addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener() {}};
    let confirmations = 0;
    const dispose = bindConfigurationEditor(root, controller, {
      pageMode: !["legacy", "page-marker"].includes(mode),
      confirmDiscard: () => {confirmations++; if (mode === "failed") throw Error("unavailable"); return mode === "accepted";},
    });
    listeners.get("change")({target: picker});
    await Promise.resolve(); await Promise.resolve();
    const allowed = ["accepted", "clean", "legacy"].includes(mode);
    assert.equal(confirmations, ["clean", "legacy"].includes(mode) ? 0 : 1);
    assert.equal(controller.snapshot().targetId, allowed ? "8" : "7");
    assert.equal(calls.length, allowed ? 3 : 2);
    assert.equal(password.value, allowed ? "" : "PRIVATE-DRAFT-123");
    assert.ok(calls.every((message) => !message.type.endsWith("/save")));
    dispose();
  });
}

const SCHEDULE_DAYS = ["mo", "di", "mi", "do", "fr", "sa", "so"];
const SCHEDULE_SETTING = {...SETTING, id: "wifi_schedule", fields: [
  {name: "wlan_timerule", label: "Schedule mode", kind: "enum", choices: [
    {value: "0", label: "No schedule"}, {value: "1", label: "Daily"}, {value: "2", label: "Weekly"},
  ]},
  {name: "wlan_dfrom", label: "Daily start", kind: "text", maximum: 5},
  {name: "wlan_dto", label: "Daily end", kind: "text", maximum: 5},
  {name: "wlan_fdis", label: "Force disconnect", kind: "boolean"},
  ...SCHEDULE_DAYS.flatMap((day) => ["from", "to"].map((suffix) => ({
    name: `wlan_time_${day}_${suffix}`, label: `${day} ${suffix}`, kind: "text", maximum: 5,
  }))),
]};
const SCHEDULE_VALUES = {wlan_timerule: "1", wlan_dfrom: "07:00", wlan_dto: "24:00", wlan_fdis: false,
  ...Object.fromEntries(SCHEDULE_DAYS.flatMap((day) => [[`wlan_time_${day}_from`, "09:00"], [`wlan_time_${day}_to`, "18:00"]]))};

for (const mode of ["0", "1", "2"]) {
  test(`page schedule initially shows only the groups for mode ${mode}`, async () => {
    const controller = createConfigurationEditorController({request: async () => ({...RESPONSE,
      setting_id: SCHEDULE_SETTING.id, values: {...SCHEDULE_VALUES, wlan_timerule: mode}})});
    await controller.open({entryId: "entry-a", setting: SCHEDULE_SETTING, autoLoad: true});
    const html = renderConfigurationEditor(controller, {pageMode: true});
    const daily = html.match(/<fieldset[^>]*data-setting-schedule-group="daily"[^>]*>/g) ?? [];
    const weekly = html.match(/<fieldset[^>]*data-setting-schedule-group="weekly"[^>]*>/g) ?? [];
    assert.equal(daily.length, 1);
    assert.equal(weekly.length, 7);
    assert.equal(/\shidden(?:\s|>)/.test(daily[0]), mode !== "1");
    assert.ok(weekly.every((group) => /\shidden(?:\s|>)/.test(group) === (mode !== "2")));
    assert.match(html, /<fieldset class="sp-settings-group"><legend>Schedule settings/);
    assert.match(html, /data-setting-field="wlan_fdis"/);
    assert.deepEqual(controller.snapshot().values, {...SCHEDULE_VALUES, wlan_timerule: mode});
  });
}

test("page schedule mode updates hidden directly, preserving dormant drafts and confirmation without I/O", async () => {
  let calls = 0; let notifications = 0;
  const controller = createConfigurationEditorController({onChange: () => {notifications++;}, request: async () => {
    calls++; return {...RESPONSE, setting_id: SCHEDULE_SETTING.id, values: SCHEDULE_VALUES};
  }});
  await controller.open({entryId: "entry-a", setting: SCHEDULE_SETTING, autoLoad: true});
  controller.setValue("wlan_dfrom", "06:30");
  controller.setValue("wlan_time_mo_from", "10:00");
  controller.setConfirmation("SAVE SETTINGS");
  const unchangedNotifications = notifications;
  const daily = {hidden: false, getAttribute: () => "daily"};
  const weekly = SCHEDULE_DAYS.map(() => ({hidden: true, getAttribute: () => "weekly"}));
  const password = {value: "PRIVATE-DRAFT-123"};
  const confirmation = {value: "SAVE SETTINGS"};
  const listeners = new Map();
  const root = {contains: () => true,
    querySelectorAll: (selector) => selector === "[data-setting-schedule-group]" ? [daily, ...weekly] : [password, confirmation],
    addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener() {}};
  const dispose = bindConfigurationEditor(root, controller, {pageMode: true});
  const input = {value: "2", hasAttribute: () => false, getAttribute: () => "wlan_timerule"};
  for (const mode of ["2", "0", "1"]) {
    input.value = mode;
    listeners.get("change")({target: input});
    assert.equal(daily.hidden, mode !== "1");
    assert.ok(weekly.every((group) => group.hidden === (mode !== "2")));
    assert.equal(controller.snapshot().values.wlan_timerule, mode);
    assert.equal(controller.snapshot().values.wlan_dfrom, "06:30");
    assert.equal(controller.snapshot().values.wlan_time_mo_from, "10:00");
    assert.equal(controller.snapshot().confirmationReady, true);
    assert.equal(password.value, "PRIVATE-DRAFT-123");
    assert.equal(confirmation.value, "SAVE SETTINGS");
    assert.equal(notifications, unchangedNotifications);
    assert.equal(calls, 1);
  }
  dispose();
});

test("legacy schedule rendering and binding do not add conditional visibility", async () => {
  const controller = createConfigurationEditorController({request: async () => ({...RESPONSE,
    setting_id: SCHEDULE_SETTING.id, values: SCHEDULE_VALUES})});
  controller.open({entryId: "entry-a", setting: SCHEDULE_SETTING}); await controller.load();
  assert.doesNotMatch(renderConfigurationEditor(controller), /data-setting-schedule-group/);
  const listeners = new Map();
  const root = {contains: () => true, querySelectorAll: () => {throw Error("should not update groups");},
    addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener() {}};
  bindConfigurationEditor(root, controller);
  listeners.get("change")({target: {value: "2", hasAttribute: () => false, getAttribute: () => "wlan_timerule"}});
  assert.equal(controller.snapshot().values.wlan_timerule, "2");
});
