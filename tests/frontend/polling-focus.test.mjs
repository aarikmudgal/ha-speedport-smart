import assert from "node:assert/strict";
import test from "node:test";
import {createPollingFocusController} from "../../custom_components/speedport_smart/frontend/polling-focus.js";

const flush = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;}); return {promise, resolve, reject}; };
const scope = (connection, extra = {}) => ({connection, entryId: "entry-a", userId: "user-a", view: "dashboard", eligible: true, ...extra});
class Events {
  listeners = new Map();
  addEventListener(name, callback) { if (!this.listeners.has(name)) this.listeners.set(name, new Set()); this.listeners.get(name).add(callback); }
  removeEventListener(name, callback) { this.listeners.get(name)?.delete(callback); }
  emit(name) { for (const callback of [...this.listeners.get(name) ?? []]) callback(); }
}
function connection({subscribeError, renewError, delayed = false} = {}) {
  const value = new Events();
  Object.assign(value, {connected: true, subscriptions: [], renewals: [],
    subscribeMessage(callback, message, options) {
      if (subscribeError) { this.subscriptions.push({message, options}); return Promise.reject(subscribeError); }
      const id = this.subscriptions.length + 2;
      const gate = deferred();
      const item = {id, callback, message, options, gate, closed: 0};
      item.close = async () => { item.closed++; };
      this.subscriptions.push(item);
      callback({subscription_id: id, expires_in_seconds: 45});
      return delayed ? gate.promise : Promise.resolve(item.close);
    },
    sendMessagePromise(message) {
      this.renewals.push(message);
      return renewError ? Promise.reject(renewError) : Promise.resolve({expires_in_seconds: 45});
    },
  });
  return value;
}
function fixture(options = {}) {
  let timerId = 0;
  const timers = new Map();
  const controller = createPollingFocusController({
    setTimer(callback, delay) { const id = ++timerId; timers.set(id, {callback, delay}); return id; },
    clearTimer(id) { timers.delete(id); }, ...options,
  });
  return {controller, timers, async tick() {
    const entry = timers.entries().next().value;
    assert.ok(entry, "expected one scheduled renewal");
    timers.delete(entry[0]); await entry[1].callback(); await flush();
  }};
}

test("focus subscribes once, renews only its ID every 15s, then releases on blur", async () => {
  const conn = connection(); const {controller, timers, tick} = fixture();
  controller.update(scope(conn)); assert.equal(conn.subscriptions.length, 1, "claim starts before later private-read microtasks"); await flush();
  const first = conn.subscriptions[0];
  assert.deepEqual(first.message, {type: "speedport_smart/panel/focus", entry_id: "entry-a", view: "dashboard"});
  assert.equal(first.options.resubscribe, false);
  assert.equal(first.options.preCheck(), true);
  assert.deepEqual([...timers.values()].map(({delay}) => delay), [15000]);
  for (let index = 0; index < 10; index++) controller.update(scope(conn));
  await tick(); await tick();
  assert.equal(conn.subscriptions.length, 1);
  assert.deepEqual(conn.renewals, Array(2).fill({type: "speedport_smart/panel/focus/renew", subscription_id: 2}));
  controller.update(scope(conn, {eligible: false})); await flush();
  assert.equal(first.closed, 1); assert.equal(first.options.preCheck(), false); assert.equal(timers.size, 0);
  controller.dispose(); assert.equal(first.closed, 1);
});

test("view, router, user and connection changes replace only their owned lease", async () => {
  const first = connection(); const second = connection(); const {controller} = fixture();
  let value = scope(first); controller.update(value); await flush();
  for (const change of [{view: "administration"}, {entryId: "entry-b"}, {userId: "user-b"}, {connection: second}]) {
    const oldConnection = value.connection; const old = oldConnection.subscriptions.at(-1);
    value = {...value, ...change}; controller.update(value); await flush();
    assert.equal(old.closed, 1);
    assert.equal(value.connection.subscriptions.at(-1).message.view, value.view);
    assert.equal(value.connection.subscriptions.at(-1).message.entry_id, value.entryId);
  }
  assert.equal(first.listeners.get("ready").size, 0);
  controller.dispose(); assert.equal(second.subscriptions[0].closed, 1);
});

test("late subscription ACK and events cannot revive a blurred or replaced scope", async () => {
  const conn = connection({delayed: true}); const {controller, timers} = fixture();
  controller.update(scope(conn)); await flush();
  const first = conn.subscriptions[0];
  controller.update(scope(conn, {view: "administration"})); await flush();
  const second = conn.subscriptions[1];
  first.callback({subscription_id: 2, expires_in_seconds: 45});
  first.gate.resolve(first.close); await flush();
  assert.equal(first.closed, 1); assert.equal(timers.size, 0);
  second.gate.resolve(second.close); await flush();
  assert.equal(timers.size, 1);
  controller.dispose(); assert.equal(second.closed, 1); assert.equal(timers.size, 0);
});

test("disposing a pending subscription releases its late ACK without renewals", async () => {
  const conn = connection({delayed: true}); const {controller, timers} = fixture();
  controller.update(scope(conn)); await flush(); const first = conn.subscriptions[0];
  controller.dispose(); first.gate.resolve(first.close); await flush();
  assert.equal(first.closed, 1); assert.equal(timers.size, 0); assert.equal(conn.renewals.length, 0);
});

test("HA's awaited preCheck still sends focus before subsequently queued private reads", async () => {
  const order = []; const conn = connection();
  conn.subscribeMessage = async (callback, message, options) => {
    if (!await options.preCheck()) throw new Error("Pre-check failed");
    order.push(message.type);
    callback({subscription_id: 2, expires_in_seconds: 45});
    return async () => {};
  };
  const {controller} = fixture(); controller.update(scope(conn, {view: "administration"}));
  await Promise.resolve().then(() => order.push("private_read")); await flush();
  assert.deepEqual(order, ["speedport_smart/panel/focus", "private_read"]); controller.dispose();
});

test("HA's queued subscription preCheck cancels a scope lost before sending", async () => {
  const queue = deferred(); const conn = connection(); let sent = 0;
  conn.subscribeMessage = async (callback, _message, options) => {
    await queue.promise;
    if (!await options.preCheck()) throw new Error("Pre-check failed");
    sent++; callback({subscription_id: 2, expires_in_seconds: 45});
    return async () => {};
  };
  const {controller, timers} = fixture(); controller.update(scope(conn));
  controller.update(scope(conn, {eligible: false})); queue.resolve(); await flush();
  assert.equal(sent, 0); assert.equal(timers.size, 0); controller.dispose();
});

test("renewal rechecks actual document eligibility even if a blur event was missed", async () => {
  let eligible = true; const conn = connection(); const {controller, timers, tick} = fixture({isEligible: () => eligible});
  controller.update(scope(conn)); await flush(); eligible = false;
  await tick(); assert.equal(conn.renewals.length, 0); assert.equal(conn.subscriptions[0].closed, 1); assert.equal(timers.size, 0);
  eligible = true; controller.update(scope(conn)); await flush(); assert.equal(conn.subscriptions.length, 2);
  controller.dispose();
});

test("reconnect does not replay stale focus and recovers only the current eligible scope", async () => {
  const conn = connection(); const {controller, timers} = fixture();
  controller.update(scope(conn)); await flush();
  conn.connected = false; conn.emit("disconnected");
  assert.equal(timers.size, 0); assert.equal(conn.subscriptions[0].closed, 1);
  controller.update(scope(conn, {view: "administration"})); await flush(); assert.equal(conn.subscriptions.length, 1);
  conn.connected = true; conn.emit("ready"); await flush();
  assert.equal(conn.subscriptions.length, 2); assert.equal(conn.subscriptions[1].message.view, "administration");
  conn.connected = false; conn.emit("disconnected"); controller.update(scope(conn, {eligible: false}));
  conn.connected = true; conn.emit("ready"); await flush(); assert.equal(conn.subscriptions.length, 2);
  controller.dispose();
});

test("unsupported servers stop all retries on that connection, including reconnect", async () => {
  const conn = connection({subscribeError: {code: "unknown_command"}}); const {controller, timers} = fixture();
  controller.update(scope(conn)); await flush();
  for (let index = 0; index < 5; index++) controller.update(scope(conn));
  controller.update(scope(conn, {eligible: false})); controller.update(scope(conn)); conn.emit("ready"); await flush();
  assert.equal(conn.subscriptions.length, 1); assert.equal(timers.size, 0); assert.equal(conn.renewals.length, 0);
  const supported = connection(); controller.update(scope(supported)); await flush(); assert.equal(supported.subscriptions.length, 1);
  controller.dispose();
});

test("lost renewal recovers once after reload, then stops instead of repeatedly reclaiming priority", async () => {
  const conn = connection({renewError: {code: "focus_not_found"}}); const {controller, timers, tick} = fixture();
  controller.update(scope(conn)); await flush(); await tick();
  assert.equal(conn.subscriptions.length, 2); assert.equal(conn.subscriptions[0].closed, 1);
  assert.equal(timers.size, 1);
  await tick();
  for (let index = 0; index < 5; index++) controller.update(scope(conn)); await flush();
  assert.equal(conn.subscriptions.length, 2); assert.equal(conn.subscriptions[1].closed, 1); assert.equal(timers.size, 0);
  controller.update(scope(conn, {eligible: false})); controller.update(scope(conn)); await flush();
  assert.equal(conn.subscriptions.length, 3); controller.dispose();
});

test("initial focus event after ACK starts renewal without creating another subscription", async () => {
  const conn = connection(); const original = conn.subscribeMessage;
  conn.subscribeMessage = function(callback, message, options) {
    const pending = original.call(this, () => {}, message, options);
    this.subscriptions.at(-1).callback = callback;
    return pending;
  };
  const {controller, timers} = fixture(); controller.update(scope(conn)); await flush();
  assert.equal(timers.size, 0);
  conn.subscriptions[0].callback({subscription_id: 2, expires_in_seconds: 45});
  assert.equal(timers.size, 1); assert.equal(conn.subscriptions.length, 1); controller.dispose();
});

test("late failed renewal cannot recover a lease after focus or scope changes", async () => {
  const gate = deferred(); const conn = connection(); conn.sendMessagePromise = () => gate.promise;
  const {controller, timers} = fixture(); controller.update(scope(conn)); await flush();
  const [id, scheduled] = timers.entries().next().value; timers.delete(id);
  const renewal = scheduled.callback();
  controller.update(scope(conn, {eligible: false}));
  gate.reject({code: "focus_not_found"}); await renewal; await flush();
  assert.equal(conn.subscriptions.length, 1); assert.equal(timers.size, 0); controller.dispose();
});

for (const code of ["unauthorized", "entry_not_loaded", "unknown_command"]) {
  test(`${code} renewal errors never reacquire or start another timer`, async () => {
    const conn = connection({renewError: {code}}); const {controller, timers, tick} = fixture();
    controller.update(scope(conn)); await flush(); await tick();
    for (let index = 0; index < 5; index++) controller.update(scope(conn));
    assert.equal(conn.subscriptions.length, 1); assert.equal(timers.size, 0); controller.dispose();
  });
}

test("multiple controls renew their own subscriptions without stealing or releasing another", async () => {
  const conn = connection(); const a = fixture(); const b = fixture();
  a.controller.update(scope(conn)); b.controller.update(scope(conn, {view: "administration"})); await flush();
  await a.tick(); await b.tick();
  assert.deepEqual(conn.renewals.map((item) => item.subscription_id), [2, 3]); assert.equal(conn.subscriptions.length, 2);
  a.controller.dispose(); assert.equal(conn.subscriptions[0].closed, 1); assert.equal(conn.subscriptions[1].closed, 0);
  b.controller.dispose();
});

test("invalid or inactive scopes do not claim focus", async () => {
  const conn = connection(); const {controller, timers} = fixture();
  for (const change of [{entryId: ""}, {userId: undefined}, {view: "settings"}, {eligible: false}, {connection: {}}]) controller.update(scope(conn, change));
  await flush(); assert.equal(conn.subscriptions.length, 0); assert.equal(timers.size, 0); controller.dispose();
});

class TestElement {
  constructor() { this.isConnected = true; }
  attachShadow() { this.shadowRoot = {innerHTML: "", addEventListener() {}, querySelector() {}, querySelectorAll() { return []; }}; return this.shadowRoot; }
  toggleAttribute() {}
}
globalThis.HTMLElement = TestElement;
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=polling-focus");

test("panel claims only its mounted visible focused document and releases every lifecycle boundary", async (t) => {
  const window = new Events(); Object.assign(window, {setInterval: () => 1, clearInterval() {}, cancelAnimationFrame() {}});
  const document = new Events(); Object.assign(document, {defaultView: window, visibilityState: "visible", focused: false, hasFocus() {return this.focused;}});
  const previousWindow = globalThis.window; globalThis.window = window;
  const panel = new SpeedportSmartPanel(); panel.ownerDocument = document;
  for (const method of ["_render", "_scheduleRender", "_syncTrafficHistory", "_loadMetadata", "_loadPlatformIcons", "_loadAdminReadAndPage"]) panel[method] = () => {};
  panel._canLeaveAdminPage = () => true;
  panel._metadata = {routers: ["entry-a", "entry-b"].map((entry_id) => ({entry_id, entry_state: "loaded", entities: []}))};
  panel._selectedEntry = "entry-a";
  const conn = connection(); panel._hass = {connection: conn, user: {id: "user-a", is_admin: true}, states: {}};
  t.after(() => {
    panel.isConnected = false; panel.disconnectedCallback();
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
  });
  panel.connectedCallback(); await flush(); assert.equal(conn.subscriptions.length, 0);
  document.focused = true; window.emit("focus"); await flush(); assert.equal(conn.subscriptions.length, 1);
  document.focused = false; window.emit("blur"); await flush(); assert.equal(conn.subscriptions[0].closed, 1);
  document.focused = true; document.visibilityState = "hidden"; window.emit("focus"); await flush(); assert.equal(conn.subscriptions.length, 1);
  document.visibilityState = "visible"; document.emit("visibilitychange"); await flush(); assert.equal(conn.subscriptions.length, 2);
  panel._selectView("administration"); await flush(); assert.equal(conn.subscriptions.at(-1).message.view, "administration");
  panel._selectRouter("entry-b"); await flush(); assert.equal(conn.subscriptions.at(-1).message.entry_id, "entry-b");
  panel.hass = {...panel._hass, user: {id: "user-b", is_admin: true}}; await flush(); assert.equal(conn.subscriptions.length, 5);
  const replacement = connection(); panel.hass = {...panel._hass, connection: replacement}; await flush();
  assert.equal(conn.subscriptions.at(-1).closed, 1); assert.equal(replacement.subscriptions.length, 1);
  panel.isConnected = false; panel.disconnectedCallback(); await flush(); assert.equal(replacement.subscriptions[0].closed, 1);
  assert.equal(window.listeners.get("focus").size, 0); assert.equal(document.listeners.get("visibilitychange").size, 0);
});
