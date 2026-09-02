import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {
  bindMaintenanceEditor,
  createMaintenanceEditorController,
  renderMaintenanceEditor,
} from "../../custom_components/speedport_smart/frontend/maintenance-editor.js";

const RESET = {
  id: "system_factory_reset", title: "Factory reset router", execution_policy: "maintenance",
  confirmation: "typed", typed_confirmation: "FACTORY RESET ROUTER", available: true,
  readback_policy: "reconnect_required", warning: "This erases settings.",
  inputs: [
    {name: "backup_saved", kind: "boolean", label: "Backup saved", must_be_true: true},
    {name: "physical_access", kind: "boolean", label: "Physical access", must_be_true: true},
  ],
};
const DECT = {...RESET, id: "system_dect_reset", typed_confirmation: "RESET DECT SETTINGS",
  inputs: [{name: "retain_registrations", kind: "boolean", label: "Keep handsets and repeaters", must_be_true: false}]};
const LOG = {...RESET, id: "system_log_clear", typed_confirmation: "CLEAR SYSTEM MESSAGES", readback_policy: "exact", inputs: []};
const response = (action, result) => ({schema_version: 1, action: action.id, result});
const ready = (controller, action = RESET) => {
  controller.open({entryId: "entry-a", action});
  for (const input of action.inputs) controller.setValue(input.name, true);
  controller.setConfirmation(action.typed_confirmation);
};
const deferred = () => {
  let resolve;
  const promise = new Promise((accept) => {resolve = accept;});
  return {promise, resolve};
};

test("opening, rendering and input do not read or mutate", async () => {
  let calls = 0;
  const controller = createMaintenanceEditorController({request: async () => {calls++;}});
  controller.open({entryId: "entry-a", action: RESET});
  renderMaintenanceEditor(controller);
  assert.equal(await controller.execute(), false);
  assert.equal(calls, 0);
  assert.equal(controller.snapshot().status, "invalid");
});

test("strict confirmation and each true attestation precede one send", async () => {
  const calls = [];
  let original;
  const controller = createMaintenanceEditorController({request: async (message) => {
    original = message; calls.push(structuredClone(message));
    return response(RESET, {status: "outcome_unknown", verification: "reconnect_required", retry_safe: false});
  }});
  ready(controller);
  controller.setValue("physical_access", false);
  assert.equal(await controller.execute(), false);
  controller.setValue("physical_access", true);
  controller.setConfirmation("FACTORY RESET ROUTER ");
  assert.equal(await controller.execute(), false);
  controller.setConfirmation(RESET.typed_confirmation);
  assert.equal(await controller.execute(), false);
  assert.equal(controller.snapshot().status, "reconnect_required");
  assert.equal(await controller.execute(), false);
  assert.deepEqual(calls, [{type: "speedport_smart/panel/maintenance", entry_id: "entry-a",
    action: RESET.id, parameters: {backup_saved: true, physical_access: true}, confirmed: true,
    confirmation_text: RESET.typed_confirmation}]);
  assert.deepEqual(original.parameters, {});
  assert.equal(original.confirmation_text, "");
});

test("DECT retention requires explicit choice, preserving false", async () => {
  const calls = [];
  const controller = createMaintenanceEditorController({request: async (message) => {
    calls.push(structuredClone(message)); return response(DECT, {status: "outcome_unknown"});
  }});
  controller.open({entryId: "entry-a", action: DECT});
  controller.setConfirmation(DECT.typed_confirmation);
  assert.equal(await controller.execute(), false);
  controller.setValue("retain_registrations", false);
  controller.clearValue("retain_registrations");
  controller.setConfirmation(DECT.typed_confirmation);
  assert.equal(await controller.execute(), false);
  controller.setValue("retain_registrations", false);
  controller.setConfirmation(DECT.typed_confirmation);
  await controller.execute();
  assert.deepEqual(calls[0].parameters, {retain_registrations: false});
});

test("double click and late result cannot resend or replace a new editor", async () => {
  const pending = deferred(); let calls = 0;
  const controller = createMaintenanceEditorController({request: () => {calls++; return pending.promise;}});
  ready(controller);
  const first = controller.execute();
  assert.equal(await controller.execute(), false);
  controller.close();
  controller.open({entryId: "entry-b", action: LOG});
  pending.resolve(response(RESET, {status: "verified"}));
  assert.equal(await first, false);
  assert.equal(calls, 1);
  assert.equal(controller.snapshot().entryId, "entry-b");
  assert.equal(controller.snapshot().status, "ready");
});

test("only exact log absence can be verified", async () => {
  for (const [action, result, expected] of [
    [LOG, {status: "verified", previous_messages_absent: true}, "verified"],
    [LOG, {status: "unchanged", previous_messages_absent: true}, "unchanged"],
    [LOG, {status: "verified"}, "outcome_unknown"],
    [LOG, {status: "ok", private: "PRIVATE"}, "outcome_unknown"],
    [RESET, {status: "verified", previous_messages_absent: true}, "reconnect_required"],
  ]) {
    const controller = createMaintenanceEditorController({request: async () => response(action, result)});
    ready(controller, action); await controller.execute();
    assert.equal(controller.snapshot().status, expected);
    assert.doesNotMatch(JSON.stringify(controller.snapshot()), /PRIVATE/);
  }
});

test("wrong response identity and raw errors never produce success or private text", async () => {
  for (const request of [
    async () => response(RESET, {status: "verified", previous_messages_absent: true}),
    async () => {throw new Error("PRIVATE 0123456789");},
    async () => {throw {code: "action_rejected", message: "PRIVATE"};},
  ]) {
    const controller = createMaintenanceEditorController({request});
    ready(controller, LOG); await controller.execute();
    assert.ok(["outcome_unknown", "rejected"].includes(controller.snapshot().status));
    assert.doesNotMatch(renderMaintenanceEditor(controller), /PRIVATE|0123456789/);
    assert.equal(await controller.execute(), false);
  }
});

test("renderer escapes labels, keeps native theme, clears confirmation on rerender", async () => {
  let calls = 0;
  const controller = createMaintenanceEditorController({request: async () => {calls++;}});
  ready(controller, {...RESET, title: '<img src=x onerror="bad">', warning: "<script>bad</script>"});
  const html = renderMaintenanceEditor(controller);
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /var\(--primary-text-color\)/);
  assert.match(html, /aria-live="polite"/);
  assert.equal(await controller.execute(), false);
  assert.equal(calls, 0);
});

test("invalid schemas, unavailable actions and unknown values fail closed", async () => {
  const controller = createMaintenanceEditorController({request: async () => assert.fail("not called")});
  for (const action of [{...RESET, id: "constructor"}, {...RESET, execution_policy: "boolean"},
    {...RESET, inputs: [{name: "__proto__", kind: "boolean", must_be_true: true}]}]) {
    assert.throws(() => controller.open({entryId: "entry", action}));
  }
  ready(controller, {...RESET, available: false});
  assert.equal(await controller.execute(), false);
  assert.equal(controller.setValue("backup_saved", "true"), false);
  assert.equal(controller.setValue("unknown", true), false);
});

test("binding is delegated, removes listeners and clears typed text on disposal", () => {
  const listeners = new Map(); const input = {value: "PRIVATE"};
  const root = {addEventListener: (name, fn) => listeners.set(name, fn),
    removeEventListener: (name) => listeners.delete(name), contains: () => true,
    querySelectorAll: () => [input]};
  const controller = createMaintenanceEditorController({request: async () => {}});
  ready(controller);
  const dispose = bindMaintenanceEditor(root, controller);
  assert.equal(listeners.size, 3);
  dispose(); assert.equal(listeners.size, 0); assert.equal(input.value, "");
  assert.equal(controller.snapshot(), null);
});

test("editor has no background polling, iframe, browser storage or raw error rendering", () => {
  const source = readFileSync(new URL("../../custom_components/speedport_smart/frontend/maintenance-editor.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /setInterval|setTimeout|localStorage|sessionStorage|<iframe|error\.message|console\./);
});
