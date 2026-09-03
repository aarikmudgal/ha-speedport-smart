import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {
  attachShadow() { return this.shadowRoot = {addEventListener() {}, querySelector() {}, querySelectorAll() {return [];}}; }
};
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=session-invalidation");
const settings = ["system_led_schedule", "system_energy"].map((id, index) => ({
  id, title: id, section: "System", supported: true, available: true,
  confirmation: "SAVE SETTINGS", requires_target: index === 1,
  fields: [{name: "enabled", label: "Enabled", kind: "boolean"},
    {name: "password", label: "Password", kind: "secret", minimum: 8, maximum: 63}],
}));
function response(result) {return new Response(JSON.stringify({result}), {headers: {"content-type": "application/json"}});}
async function until(check) {
  for (let index = 0; index < 200 && !check(); index++) await Promise.resolve();
  assert.ok(check(), "bounded asynchronous transition completed");
}
async function fixture() {
  const calls = [];
  let finish;
  const write = new Promise((resolve) => {finish = resolve;});
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._renderSettingsEditor = () => {};
  panel._scheduleRender = () => {};
  panel._privateReadWait = async () => {};
  panel._selectedEntry = "entry-a";
  panel._activeView = "administration";
  panel._metadata = {routers: [{entry_id: "entry-a", entry_state: "loaded", title: "Router",
    settings, entities: [], admin_actions: [], management: {controls_available: true, state: "available"}}]};
  panel._hass = {user: {id: "admin", is_admin: true}, states: {}, fetchWithAuth: async (_path, options) => {
    const message = JSON.parse(options.body); calls.push(message);
    if (message.type.endsWith("/save")) return write;
    if (message.type.endsWith("/targets")) return response({setting_id: message.setting_id,
      targets: [{id: "one", label: "First"}, {id: "two", label: "Second"}]});
    return response({setting_id: message.setting_id, target_id: message.target_id,
      revision: `revision-${calls.length}`, values: {enabled: true}, expires_in: 120});
  }};
  await panel._selectAdminPage("system", "system_energy");
  const first = panel._settingsEditors.get(settings[0].id).editor;
  const second = panel._settingsEditors.get(settings[1].id).editor;
  await second.selectTarget("two");
  second.setValue("password", "PRIVATE-DRAFT");
  first.setValue("enabled", false); first.setConfirmation("SAVE SETTINGS");
  const saving = first.save();
  await until(() => calls.some((call) => call.type.endsWith("/save")));
  return {panel, calls, first, second, saving, finish};
}

test("session change during one save invalidates idle siblings after completion and recovers exact targets", async () => {
  const {panel, calls, first, second, saving, finish} = await fixture();
  panel._invalidateAdminPageSession();
  finish(response({status: "verified"})); await saving;
  await until(() => panel._settingsEditors.get(settings[1].id)?.editor !== second &&
    panel._settingsEditors.get(settings[1].id)?.editor.snapshot()?.loaded);
  assert.equal(first.snapshot().status, "verified");
  assert.equal(panel._settingsEditors.get(settings[0].id).editor, first);
  assert.equal(second.snapshot(), null);
  const recovered = panel._settingsEditors.get(settings[1].id).editor.snapshot();
  assert.equal(recovered.targetId, "two");
  assert.deepEqual(recovered.dirty, []);
  assert.equal(calls.filter((call) => call.type.endsWith("/save")).length, 1);
  assert.equal(calls.filter((call) => call.type.endsWith("/read") && call.setting_id === settings[0].id).length, 1);
  assert.equal(calls.filter((call) => call.type.endsWith("/read")).at(-1).target_id, "two");
  panel._clearSettingsEditor();
});

test("permission loss cancels deferred session recovery and ignores a dispatched response", async () => {
  const {panel, calls, first, second, saving, finish} = await fixture();
  panel._invalidateAdminPageSession();
  panel.hass = {...panel._hass, user: {id: "admin", is_admin: false}};
  const sent = calls.length;
  finish(response({status: "verified"})); await saving;
  for (let index = 0; index < 20; index++) await Promise.resolve();
  assert.equal(panel._settingsEditors.size, 0);
  assert.equal(first.snapshot(), null);
  assert.equal(second.snapshot(), null);
  assert.equal(calls.length, sent);
});
