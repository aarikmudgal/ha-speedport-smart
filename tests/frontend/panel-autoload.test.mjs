import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {querySelector() {}, querySelectorAll() {return [];}, addEventListener() {}};
  }
};
globalThis.customElements = {get() {}, define() {}};
const {SpeedportSmartPanel} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=autoload"
);
const schemaVersion = Number(readFileSync(new URL(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js", import.meta.url,
), "utf8").match(/const PANEL_SCHEMA_VERSION = (\d+);/)[1]);
const SETTING = {id: "qos_devices", title: "Device priority", supported: true, available: true,
  confirmation: "SAVE SETTINGS", fields: [{name: "hdvoice", label: "HD voice", kind: "boolean"}]};
const ENTRY = "synthetic-entry";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {resolve = done;});
  return {promise, resolve};
}

function response(result) {
  return new Response(JSON.stringify({result}), {headers: {"content-type": "application/json"}});
}

function values() {
  return response({setting_id: SETTING.id, revision: "synthetic-revision", expires_in: 120,
    values: {hdvoice: true}});
}

function metadata({generation = 1, available = true, supported = true} = {}) {
  return {schema_version: schemaVersion, routers: [
    {entry_id: ENTRY, entry_state: "loaded", settings: [{...SETTING, supported, available: available && supported}],
      entities: [], admin_actions: [], capabilities: [], capability_families: [], access_sources: [],
      management: {generation, controls_available: available, state: available ? "available" : "recovering"}},
    {entry_id: "other-entry", entry_state: "loaded", settings: [], entities: [], admin_actions: [],
      capabilities: [], capability_families: [], access_sources: [],
      management: {generation: 1, controls_available: true, state: "available"}},
  ]};
}

function fixture(options = {}) {
  const panel = new SpeedportSmartPanel();
  panel._privateReadWait = async () => {};
  // Exercise real controller, navigation, metadata and private transport. Rendering
  // is inert here so no browser, entity refresh, or live router is involved.
  panel._render = () => {};
  panel._renderSettingsEditor = () => {};
  panel._scheduleRender = () => {};
  panel._platformIcons = {}; panel._componentIcons = {};
  panel._metadata = metadata(options);
  panel._selectedEntry = ENTRY;
  panel._activeView = "administration";
  const calls = [];
  let nextMetadata = metadata(options);
  let fetchResult = async (message) => message.type.endsWith("/admin_read")
    ? response({entry_id: message.entry_id, schema_version: 2, sections: []}) : values();
  panel._hass = {user: {id: "synthetic-admin", is_admin: true}, states: {},
    connection: {sendMessagePromise: async () => structuredClone(nextMetadata)},
    fetchWithAuth: async (_path, request) => {
      const message = JSON.parse(request.body);
      calls.push(structuredClone(message));
      return fetchResult(message);
    }};
  return {panel, calls,
    setMetadata: (next) => {nextMetadata = next;},
    setFetch: (next) => {fetchResult = next;},
    reads: () => calls.filter((item) => item.type.endsWith("/settings/read")),
  };
}

async function turns() {
  for (let index = 0; index < 12; index++) await Promise.resolve();
}

async function settled(panel) {
  // The transport's completion-only queue may receive a newly selected read
  // after a previous response finishes. No real timer or retry is introduced.
  for (let index = 0; index < 4; index++) {
    await turns();
    await panel._privateRequestQueue;
  }
}

async function openPage(panel) {
  await panel._selectAdminPage("network", "network_prioritization");
  await settled(panel);
}

test("management generation recovery reopens exactly the selected page once", async () => {
  const {panel, setMetadata, reads, calls} = fixture();
  await openPage(panel);
  assert.equal(reads().length, 1);
  setMetadata(metadata({generation: 2}));
  await panel._loadMetadata(); await settled(panel);
  assert.equal(panel._settingsEditor.snapshot()?.loaded, true);
  assert.equal(reads().length, 2);
  assert.equal(panel._currentAdminPage().page.id, "network_prioritization");
  await panel._loadMetadata(); await settled(panel);
  panel._render(); panel._render();
  assert.equal(reads().length, 2, "unchanged metadata and telemetry must not repeat the read");
  assert.ok(calls.every((message) => !message.type.endsWith("/save")));
});

test("generation transition during initial read discards old data then obtains one current read", async () => {
  const {panel, setMetadata, setFetch, reads} = fixture();
  const pending = deferred();
  setFetch(async () => reads().length === 1 ? pending.promise : values());
  const opening = panel._selectAdminPage("network", "network_prioritization");
  await turns();
  assert.equal(reads().length, 1);
  setMetadata(metadata({generation: 2}));
  const refreshing = panel._loadMetadata();
  await turns();
  pending.resolve(response({setting_id: SETTING.id, revision: "stale-revision", expires_in: 120,
    values: {hdvoice: false}}));
  await opening; await refreshing; await settled(panel);
  assert.equal(reads().length, 2);
  assert.equal(panel._settingsEditor.snapshot()?.revision, "synthetic-revision");
  assert.equal(panel._settingsEditor.snapshot()?.values.hdvoice, true);
});

for (const generation of [1, 2]) {
  test(`availability recovery loads an initially empty page once with generation ${generation}`, async () => {
    const {panel, setMetadata, reads} = fixture({available: false});
    await openPage(panel);
    assert.equal(reads().length, 0);
    assert.equal(panel._settingsEditor.snapshot(), null);
    setMetadata(metadata({generation, available: true}));
    await panel._loadMetadata(); await settled(panel);
    assert.equal(panel._settingsEditor.snapshot()?.loaded, true);
    assert.equal(reads().length, 1);
    await panel._loadMetadata(); await settled(panel);
    assert.equal(reads().length, 1);
  });
}

test("descriptor support becoming available loads an empty page without a management-generation change", async () => {
  const {panel, setMetadata, reads} = fixture({supported: false});
  await openPage(panel);
  assert.equal(reads().length, 0);
  setMetadata(metadata({supported: true}));
  await panel._loadMetadata(); await settled(panel);
  assert.equal(reads().length, 1);
  assert.equal(panel._settingsEditor.snapshot()?.loaded, true);
  await panel._loadMetadata(); await settled(panel);
  assert.equal(reads().length, 1);
});

for (const rejected of [false, true]) {
  test(`newly available sibling ${rejected ? "fails once without automatic retries" : "loads once"} while existing draft survives`, async () => {
    const {panel, setMetadata, setFetch, reads, calls} = fixture();
    const siblingId = "qos_voice_priority";
    const pageMetadata = (available) => {
      const next = metadata();
      next.routers[0].settings.push({...SETTING, id: siblingId, available});
      return next;
    };
    panel._metadata = pageMetadata(false);
    setFetch(async (message) => {
      if (rejected && message.setting_id === siblingId) return response({setting_id: "wrong", values: {}});
      return response({setting_id: message.setting_id, revision: `revision-${message.setting_id}`,
        expires_in: 120, values: {hdvoice: true}});
    });
    await openPage(panel);
    const first = panel._settingsEditors.get(SETTING.id).editor;
    first.setValue("hdvoice", false);
    first.setConfirmation("SAVE SETTINGS");
    const before = first.snapshot();
    setMetadata(pageMetadata(true));
    await panel._loadMetadata(); await settled(panel);
    assert.deepEqual(reads().map((call) => call.setting_id), [SETTING.id, siblingId]);
    assert.equal(panel._settingsEditors.get(SETTING.id).editor, first);
    assert.deepEqual(first.snapshot(), before, "existing revision, dirty draft and confirmation remain untouched");
    assert.equal(panel._settingsEditors.get(siblingId).editor.snapshot().status, rejected ? "load_failed" : "ready");
    for (let index = 0; index < 3; index++) {
      await panel._loadMetadata();
      panel.hass = {...panel._hass, states: {"sensor.synthetic_wan": {state: String(index)}}};
      await settled(panel);
    }
    assert.deepEqual(reads().map((call) => call.setting_id), [SETTING.id, siblingId]);
    assert.deepEqual(first.snapshot(), before);
    assert.ok(calls.every((call) => !call.type.endsWith("/save")));
    panel._clearSettingsEditor();
  });
}

test("failed recovery read is not retried on each metadata or telemetry update", async () => {
  const {panel, setMetadata, setFetch, reads} = fixture({available: false});
  await openPage(panel);
  setFetch(async () => response({setting_id: "wrong", values: {}}));
  setMetadata(metadata({generation: 2}));
  await panel._loadMetadata(); await settled(panel);
  assert.equal(reads().length, 1);
  assert.equal(panel._settingsEditor.snapshot()?.status, "load_failed");
  for (let index = 0; index < 3; index++) {
    await panel._loadMetadata();
    panel.hass = {...panel._hass, states: {"sensor.unrelated": {state: String(index)}}};
    await settled(panel);
  }
  assert.equal(reads().length, 1);
});

for (const cancel of [null, "permission", "unload"]) {
  test(`new sibling waits for an existing save${cancel ? ` and is cancelled on ${cancel}` : " without losing the completed result"}`, async () => {
    const {panel, setMetadata, setFetch, reads, calls} = fixture();
    const siblingId = "qos_voice_priority";
    const pageMetadata = (available) => {
      const next = metadata();
      next.routers[0].settings.push({...SETTING, id: siblingId, available});
      return next;
    };
    panel._metadata = pageMetadata(false);
    await openPage(panel);
    const first = panel._settingsEditors.get(SETTING.id).editor;
    first.setValue("hdvoice", false);
    first.setConfirmation("SAVE SETTINGS");
    const pending = deferred();
    setFetch(async (message) => message.type.endsWith("/save") ? pending.promise :
      response({setting_id: message.setting_id, revision: "sibling-revision", expires_in: 120, values: {hdvoice: true}}));
    const saving = first.save();
    await turns();
    const epoch = panel._adminPageEpoch;
    setMetadata(pageMetadata(true));
    await panel._loadMetadata(); await turns();
    assert.equal(panel._adminPageEpoch, epoch, "availability recovery must not invalidate an in-flight save");
    assert.equal(first.snapshot().isSaving, true);
    assert.deepEqual(reads().map((call) => call.setting_id), [SETTING.id]);
    if (cancel === "permission") panel.hass = {...panel._hass, user: {id: "synthetic-admin", is_admin: false}};
    else if (cancel === "unload") {panel.isConnected = false; panel.disconnectedCallback();}
    pending.resolve(response({status: "verified"}));
    await saving; await settled(panel);
    if (!cancel) {
      assert.equal(panel._settingsEditors.get(SETTING.id).editor, first);
      assert.equal(first.snapshot().status, "verified");
      assert.equal(panel._settingsEditors.get(siblingId)?.editor.snapshot().status, "ready");
      for (let index = 0; index < 3; index++) {await panel._loadMetadata(); await settled(panel);}
    } else assert.equal(panel._settingsEditors.has(siblingId), false);
    assert.deepEqual(reads().map((call) => call.setting_id), cancel ? [SETTING.id] : [SETTING.id, siblingId]);
    assert.equal(calls.filter((call) => call.type.endsWith("/save")).length, 1);
    assert.equal(panel._adminPageRecoveryPending, undefined);
    panel._clearSettingsEditor();
  });
}

for (const change of ["page", "router", "view", "permission"]) {
  test(`${change} change cancels a queued recovery read before it can send`, async () => {
    const {panel, setMetadata, setFetch, reads, calls} = fixture();
    const pending = deferred();
    setFetch(async (message) => {
      if (message.type.endsWith("/admin_read")) return response({entry_id: message.entry_id, schema_version: 2, sections: []});
      return reads().length === 1 ? pending.promise : values();
    });
    const opening = panel._selectAdminPage("network", "network_prioritization");
    await turns();
    assert.equal(reads().length, 1);
    setMetadata(metadata({generation: 2}));
    const refreshing = panel._loadMetadata();
    await turns();
    if (change === "page") await panel._selectAdminPage("network", "network_wifi_environment");
    else if (change === "router") panel._selectRouter("other-entry");
    else if (change === "view") panel._selectView("dashboard");
    else panel.hass = {...panel._hass, user: {id: "synthetic-admin", is_admin: false}};
    pending.resolve(values());
    await opening; await refreshing; await settled(panel);
    assert.equal(reads().length, 1, "old-page queued read must never reach transport");
    assert.equal(panel._settingsEditor.snapshot(), null);
    assert.ok(calls.every((message) => !message.type.endsWith("/save")));
  });
}

test("management entity availability recovery reloads current page without waiting for metadata", async () => {
  const {panel, reads} = fixture();
  panel._metadata.routers[0].entities = [{entity_id: "sensor.management", translation_key: "management_access"}];
  panel._hass.states = {"sensor.management": {state: "available"}};
  await openPage(panel);
  panel.hass = {...panel._hass, states: {"sensor.management": {state: "unavailable"}}};
  await settled(panel);
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.equal(reads().length, 1);
  panel.hass = {...panel._hass, states: {"sensor.management": {state: "available"}}};
  await settled(panel);
  assert.equal(panel._settingsEditor.snapshot()?.loaded, true);
  assert.equal(reads().length, 2);
});

for (const busy of ["maintenance", "file_transfer", "native_action"]) {
  test(`${busy} in progress blocks invalidation-driven automatic reads`, async () => {
    const {panel, setMetadata, reads} = fixture();
    await openPage(panel);
    const revision = panel._settingsEditor.snapshot().revision;
    if (busy === "maintenance") panel._maintenanceEditor.snapshot = () => ({busy: true});
    else if (busy === "file_transfer") panel._fileTransferEditor.snapshot = () => ({busy: true});
    else panel._actionBusy = true;
    setMetadata(metadata({generation: 2}));
    await panel._loadMetadata(); await settled(panel);
    assert.equal(reads().length, 1);
    assert.equal(panel._settingsEditor.snapshot()?.revision, revision);
  });
}

test("in-flight confirmed save is neither cleared nor followed by a recovery auto-read", async () => {
  const {panel, setMetadata, setFetch, reads, calls} = fixture();
  await openPage(panel);
  const pending = deferred();
  setFetch(async (message) => message.type.endsWith("/save") ? pending.promise : values());
  panel._settingsEditor.setValue("hdvoice", false);
  panel._settingsEditor.setConfirmation("SAVE SETTINGS");
  const saving = panel._settingsEditor.save();
  await turns();
  assert.equal(panel._settingsEditor.snapshot().isSaving, true);
  setMetadata(metadata({generation: 2}));
  const refreshing = panel._loadMetadata();
  await turns();
  assert.equal(panel._settingsEditor.snapshot().isSaving, true);
  pending.resolve(response({status: "outcome_unknown", verification: "manual_required"}));
  await saving; await refreshing; await settled(panel);
  assert.equal(reads().length, 1);
  assert.equal(calls.filter((message) => message.type.endsWith("/save")).length, 1);
  assert.equal(panel._settingsEditor.snapshot().status, "manual_required");
});

const SECONDARY_SETTING = {...SETTING, id: "qos_voice_priority", title: "Voice priority",
  fields: [...SETTING.fields, {name: "credential", label: "Credential", kind: "secret"}]};

function secondaryMetadata(options = {}, {targeted = false} = {}) {
  const result = metadata(options);
  result.routers[0].settings.push({...SECONDARY_SETTING, requires_target: targeted,
    available: options.available !== false});
  return result;
}

test("recovery preserves the secondary form but discards its old revision, draft and secret", async () => {
  const {panel, setMetadata, setFetch, reads, calls} = fixture();
  setFetch(async (message) => response({setting_id: message.setting_id,
    revision: `revision-${reads().length}`, expires_in: 120, values: {hdvoice: true}}));
  await openPage(panel);
  panel._metadata = secondaryMetadata();
  await panel._openAdminSetting(SECONDARY_SETTING.id);
  const oldRevision = panel._settingsEditor.snapshot().revision;
  panel._settingsEditor.setValue("hdvoice", false);
  panel._settingsEditor.setValue("credential", "synthetic-private-draft");
  panel._settingsEditor.setConfirmation("SAVE SETTINGS");
  assert.equal(panel._settingsEditor.snapshot().isDirty, true);
  setMetadata(secondaryMetadata({generation: 2, available: false}));
  await panel._loadMetadata(); await settled(panel);
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.deepEqual(panel._adminRecoverySelection, {pageId: "network_prioritization",
    settingId: SECONDARY_SETTING.id, targetId: null});
  assert.match(panel._notice, /Unsaved changes were discarded/);
  setMetadata(secondaryMetadata({generation: 3}));
  await panel._loadMetadata(); await settled(panel);
  const view = panel._settingsEditor.snapshot();
  assert.equal(view.setting.id, SECONDARY_SETTING.id);
  assert.notEqual(view.revision, oldRevision);
  assert.equal(view.values.hdvoice, true);
  assert.deepEqual(view.dirty, []);
  assert.equal(view.confirmationReady, false);
  assert.equal(panel._adminRecoverySelection, undefined);
  assert.deepEqual(reads().map((call) => call.setting_id), [SETTING.id, SECONDARY_SETTING.id, SETTING.id, SECONDARY_SETTING.id]);
  assert.ok(calls.every((call) => !call.type.endsWith("/save")));
  assert.doesNotMatch(JSON.stringify(view), /synthetic-private-draft/);
});

for (const vanished of [false, true]) {
  test(`targeted recovery ${vanished ? "does not substitute a vanished target" : "preserves the exact selected target after rediscovery"}`, async () => {
    const {panel, setMetadata, setFetch, reads, calls} = fixture();
    let targets = [{id: "7", label: "First"}, {id: "8", label: "Second"}];
    setFetch(async (message) => message.type.endsWith("/targets")
      ? response({setting_id: message.setting_id, targets})
      : response({setting_id: message.setting_id, target_id: message.target_id,
        revision: "target-revision", expires_in: 120, values: {hdvoice: true}}));
    await openPage(panel);
    panel._metadata = secondaryMetadata({}, {targeted: true});
    await panel._openAdminSetting(SECONDARY_SETTING.id, {targetId: "8"});
    assert.equal(panel._settingsEditor.snapshot().targetId, "8");
    const count = reads().length;
    if (vanished) targets = [targets[0]];
    setMetadata(secondaryMetadata({generation: 2}, {targeted: true}));
    await panel._loadMetadata(); await settled(panel);
    const view = panel._settingsEditor.snapshot();
    assert.equal(view.setting.id, SECONDARY_SETTING.id);
    assert.equal(view.targetId, vanished ? null : "8");
    assert.equal(view.loaded, !vanished);
    assert.equal(reads().length, count + 1 + Number(!vanished));
    if (vanished) assert.equal(view.status, "target_required");
    else assert.equal(reads().at(-1).target_id, "8");
    assert.equal(calls.filter((call) => call.type.endsWith("/targets")).length, 2);
    await panel._loadMetadata(); await settled(panel);
    assert.equal(reads().length, count + 1 + Number(!vanished));
    if (vanished) {
      setMetadata(secondaryMetadata({generation: 3}, {targeted: true}));
      await panel._loadMetadata(); await settled(panel);
      assert.equal(panel._settingsEditor.snapshot().targetId, null);
      assert.equal(reads().filter((call) => call.target_id).length, 1, "another session change must not select a replacement target");
    }
    assert.ok(calls.every((call) => !call.type.endsWith("/save")));
  });
}

for (const loader of ["session recovery", "initial page loader"]) {
  test(`invalid schema in ${loader} is bounded without a detached rejection or retry`, async () => {
    const {panel, setMetadata, reads} = fixture();
    await openPage(panel);
    const malformed = metadata({generation: 2});
    malformed.routers[0].settings[0].fields = [];
    const rejections = [];
    const capture = (error) => rejections.push(error);
    process.on("unhandledRejection", capture);
    try {
      if (loader === "session recovery") {
        setMetadata(malformed);
        await panel._loadMetadata();
      } else {
        panel._clearAdminRead();
        panel._metadata = malformed;
        await panel._loadAdminReadAndPage(ENTRY);
      }
      await settled(panel);
      await new Promise((resolve) => setImmediate(resolve));
      assert.deepEqual(rejections, []);
      assert.equal(panel._settingsEditor.snapshot(), null);
      assert.match(panel._notice, /Settings could not be loaded/);
      assert.equal(reads().length, 1);
      setMetadata(malformed);
      await panel._loadMetadata(); await settled(panel);
      assert.equal(reads().length, 1);
    } finally {
      process.removeListener("unhandledRejection", capture);
    }
  });
}

test("a second session change during target rediscovery cannot replace the selected target", async () => {
  const {panel, setMetadata, setFetch, reads, calls} = fixture();
  const targets = [{id: "7", label: "First"}, {id: "8", label: "Second"}];
  const inventory = () => response({setting_id: SECONDARY_SETTING.id, targets});
  const pending = deferred();
  setFetch(async (message) => {
    if (message.type.endsWith("/targets")) {
      return calls.filter((call) => call.type.endsWith("/targets")).length === 2 ? pending.promise : inventory();
    }
    return response({setting_id: message.setting_id, target_id: message.target_id,
      revision: "target-revision", expires_in: 120, values: {hdvoice: true}});
  });
  await openPage(panel);
  panel._metadata = secondaryMetadata({}, {targeted: true});
  await panel._openAdminSetting(SECONDARY_SETTING.id, {targetId: "8"});
  setMetadata(secondaryMetadata({generation: 2}, {targeted: true}));
  await panel._loadMetadata();
  for (let index = 0; index < 6 && panel._settingsEditor.snapshot()?.status !== "targets_loading"; index++) await turns();
  assert.equal(panel._settingsEditor.snapshot().status, "targets_loading");
  setMetadata(secondaryMetadata({generation: 3}, {targeted: true}));
  await panel._loadMetadata(); await turns();
  pending.resolve(inventory());
  await settled(panel);
  assert.equal(panel._settingsEditor.snapshot().targetId, "8");
  assert.equal(reads().at(-1).target_id, "8");
  assert.ok(reads().every((call) => call.target_id !== "7"));
});

test("metadata recovery restores a cleared page once without a generation change", async () => {
  const {panel, setMetadata, reads, calls} = fixture();
  await openPage(panel);
  setMetadata({schema_version: schemaVersion, routers: null});
  await panel._loadMetadata(); await settled(panel);
  assert.equal(panel._loadError, "error.metadata_unavailable");
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.equal(reads().length, 1);
  setMetadata(metadata());
  await panel._loadMetadata(); await settled(panel);
  assert.equal(panel._loadError, "");
  assert.equal(panel._settingsEditor.snapshot()?.loaded, true);
  assert.equal(reads().length, 2);
  await panel._loadMetadata(); await settled(panel);
  assert.equal(reads().length, 2);
  assert.ok(calls.every((call) => !call.type.endsWith("/save")));
});

test("metadata arriving after detach cannot reopen the private page or send reads", async () => {
  const {panel, reads, calls} = fixture();
  panel.isConnected = true;
  await openPage(panel);
  const pending = deferred();
  panel._hass.connection.sendMessagePromise = () => pending.promise;
  const loading = panel._loadMetadata();
  await turns();
  panel.isConnected = false;
  panel.disconnectedCallback();
  const count = calls.length;
  pending.resolve(metadata({generation: 2}));
  await loading; await settled(panel);
  assert.equal(panel._settingsEditor.snapshot(), null);
  assert.equal(reads().length, 1);
  assert.equal(calls.length, count);
});
