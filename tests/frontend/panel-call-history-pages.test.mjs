import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {
  attachShadow() {return this.shadowRoot = {addEventListener() {}, querySelector() {}, querySelectorAll() {return [];}};}
};
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=call-history-pages");
const pages = {telephony_calls_missed: "missed", telephony_calls_taken: "taken", telephony_calls_dialed: "dialed"};
function response(category) {return new Response(JSON.stringify({result: {schema_version: 1, query: "call_history",
  result: {category, total: 0, entries: []}}}), {headers: {"content-type": "application/json"}});}
function fixture(request) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._scheduleRender = () => {};
  panel._selectedEntry = "entry-a"; panel._activeView = "administration";
  panel._metadata = {routers: [{entry_id: "entry-a", entry_state: "loaded", title: "Router",
    settings: [], entities: [], admin_actions: [], management: {controls_available: true, state: "available"}}]};
  panel._hass = {user: {id: "admin", is_admin: true}, states: {}, fetchWithAuth: async (_path, options) => {
    const message = JSON.parse(options.body); calls.push(message);
    return request ? request(message) : response(message.category);
  }};
  return {panel, calls};
}
for (const [page, category] of Object.entries(pages)) {
  test(`native ${page} reads only ${category} once; renders and same-page selection do not reread`, async () => {
    const {panel, calls} = fixture();
    await panel._selectAdminPage("telephony", page);
    assert.deepEqual(calls, [{type: "speedport_smart/panel/call_history", entry_id: "entry-a", category, export: false}]);
    assert.equal(panel._callHistoryView.snapshot().category, category);
    assert.equal(panel._callHistoryView.snapshot().status, "loaded");
    await panel._selectAdminPage("telephony", page); await panel._loadAdminPage(); panel._render();
    assert.equal(calls.length, 1);
    panel._callHistoryView.close();
    panel._handleClick({target: {closest: () => ({dataset: {openCallHistory: "true"}})}});
    assert.equal(panel._callHistoryView.snapshot().category, category);
    assert.equal(calls.length, 1, "explicit opener selects current category without implicit I/O");
    await panel._selectAdminPage("network", "network_wifi_environment");
    assert.equal(panel._callHistoryView.snapshot(), null);
    assert.deepEqual(panel._callHistoryView.entries(), []);
    assert.equal(calls.length, 1);
  });
}
for (const change of ["navigation", "permission"]) {
  test(`${change} discards an in-flight native call-list response without another category read`, async () => {
    let finish;
    const pending = new Promise((resolve) => {finish = resolve;});
    const {panel, calls} = fixture(() => pending);
    const opening = panel._selectAdminPage("telephony", "telephony_calls_dialed");
    for (let index = 0; index < 100 && !calls.length; index++) await Promise.resolve();
    assert.equal(calls.length, 1);
    if (change === "navigation") await panel._selectAdminPage("network", "network_wifi_environment");
    else panel.hass = {...panel._hass, user: {id: "admin", is_admin: false}};
    finish(response("dialed")); await opening;
    assert.equal(panel._callHistoryView.snapshot(), null);
    assert.deepEqual(panel._callHistoryView.entries(), []);
    assert.equal(calls.length, 1);
  });
}

test("rapid category navigation and explicit export share completion-based pacing", async () => {
  let now = 0;
  const sent = [];
  const {panel} = fixture((message) => {sent.push({category: message.category, export: message.export, time: now}); return response(message.category);});
  panel._privateReadNow = () => now;
  const waits = [];
  panel._privateReadWait = async (delay) => {waits.push(delay); now += delay;};
  for (const page of Object.keys(pages)) await panel._selectAdminPage("telephony", page);
  // The mock intentionally has no CSV; failed validation must not retry export.
  await panel._callHistoryView.exportCsv();
  assert.deepEqual(sent, [{category: "missed", export: false, time: 0},
    {category: "taken", export: false, time: 1000}, {category: "dialed", export: false, time: 2000},
    {category: "dialed", export: true, time: 3000}]);
  assert.deepEqual(waits, [1000, 1000, 1000]);
  panel._clearSettingsEditor();
});

test("leaving while call-list pacing waits cancels the queued read before transport", async () => {
  const {panel, calls} = fixture();
  await panel._selectAdminPage("telephony", "telephony_calls_missed");
  let resume;
  let waiting = false;
  panel._privateReadWait = () => {waiting = true; return new Promise((resolve) => {resume = resolve;});};
  const opening = panel._selectAdminPage("telephony", "telephony_calls_taken");
  for (let index = 0; index < 100 && !waiting; index++) await Promise.resolve();
  assert.equal(waiting, true);
  await panel._selectAdminPage("network", "network_wifi_environment");
  resume(); await opening;
  assert.equal(calls.length, 1);
  assert.equal(panel._callHistoryView.snapshot(), null);
});
