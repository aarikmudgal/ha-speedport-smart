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
