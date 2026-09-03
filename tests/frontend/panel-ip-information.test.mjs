import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {
  attachShadow() {return this.shadowRoot = {addEventListener() {}, querySelector() {}, querySelectorAll() {return [];}};}
};
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel, normalizeAdminPrivateQueryPayload} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=ip-information");
const RESULT = {ipv4: {address: "192.0.2.10", gateway: "192.0.2.1", dns_primary: "192.0.2.53"},
  ipv6: {address: "2001:db8::1", delegated_prefix: "2001:db8:1::/56", lan_prefix: "2001:db8:1::/64", gateway: "fe80::1"}};
const payload = (result = RESULT) => ({schema_version: 1, query: "ip_information", result});
const response = (result = RESULT) => new Response(JSON.stringify({result: payload(result)}), {headers: {"content-type": "application/json"}});
function fixture(request) {
  const calls = [], panel = new SpeedportSmartPanel();
  panel._render = () => {}; panel._scheduleRender = () => {};
  panel._privateReadNow = () => 1000; panel._privateReadWait = async () => {};
  panel._selectedEntry = "entry-a"; panel._activeView = "administration";
  panel._metadata = {routers: [{entry_id: "entry-a", entry_state: "loaded", title: "Router",
    settings: [], entities: [], admin_actions: [], management: {controls_available: true, state: "available"}}]};
  panel._hass = {user: {id: "admin", is_admin: true}, states: {}, fetchWithAuth: async (_path, options) => {
    const message = JSON.parse(options.body); calls.push(message);
    return request ? request(message) : response();
  }};
  return {panel, calls};
}

test("IP page reads once on entry, never on rendering or WAN ticks, and exposes read-only fields", async () => {
  const {panel, calls} = fixture();
  await panel._selectAdminPage("internet", "internet_ip_information");
  assert.deepEqual(calls, [{type: "speedport_smart/panel/ip_information", entry_id: "entry-a"}]);
  assert.deepEqual(panel._adminPrivateQueries.ip.result, RESULT);
  const html = panel._renderAdminIpInformation();
  for (const label of ["IPv4", "IPv6", "Public IP address", "Gateway", "Primary DNS server", "Delegated IPv6 prefix", "Not reported by router"]) assert.ok(html.includes(label), label);
  assert.ok(!/<input|<select|data-setting|data-more-info/.test(html));
  assert.ok(!JSON.stringify(panel._metadata).includes("192.0.2.10"));
  assert.ok(!JSON.stringify(panel._hass.states).includes("192.0.2.10"));
  await panel._selectAdminPage("internet", "internet_ip_information"); await panel._loadAdminPage();
  panel._renderAdminIpInformation(); panel.hass = {...panel._hass, states: {...panel._hass.states}};
  assert.equal(calls.length, 1);
  await panel._handleClick({target: {closest: () => ({dataset: {refreshIpInformation: ""}})}});
  assert.equal(calls.length, 2);
  await panel._selectAdminPage("network", "network_wifi_environment");
  assert.equal(panel._adminPrivateQueries.ip.result, undefined);
  await panel._runIpInformationQuery(); assert.equal(calls.length, 2);
});

test("invalid IP response rejects completely instead of showing injected or partial values", () => {
  assert.deepEqual(normalizeAdminPrivateQueryPayload(payload(), "ip_information"), RESULT);
  assert.deepEqual(normalizeAdminPrivateQueryPayload(payload({ipv4: {}, ipv6: {}}), "ip_information"), {ipv4: {}, ipv6: {}});
  assert.deepEqual(normalizeAdminPrivateQueryPayload(payload({ipv4: {}, ipv6: {delegated_prefix: "2001:db8::"}}), "ip_information"), {ipv4: {}, ipv6: {delegated_prefix: "2001:db8::"}});
  for (const result of [
    {ipv4: {address: "<script>"}, ipv6: {}}, {ipv4: {address: "192.0.2.999"}, ipv6: {}},
    {ipv4: {}, ipv6: {address: "2001:db8::1%secret"}}, {ipv4: {}, ipv6: {address: "2001:::1"}},
    {ipv4: {}, ipv6: {delegated_prefix: "2001:db8::/129"}}, {ipv4: {}, ipv6: {address: "2001:db8::/64"}},
    {ipv4: {password: "private"}, ipv6: {}},
    {ipv4: {}, ipv6: {}, extra: "private"}, {ipv4: {}},
  ]) assert.equal(normalizeAdminPrivateQueryPayload(payload(result), "ip_information"), undefined);
});

for (const change of ["page", "view", "user", "permission", "router", "unload", "disconnect"]) {
  test(`${change} clears private IP state and ignores late results`, async () => {
    let finish;
    const {panel, calls} = fixture(() => new Promise((resolve) => {finish = resolve;}));
    const opening = panel._selectAdminPage("internet", "internet_ip_information");
    for (let index = 0; index < 100 && !calls.length; index++) await Promise.resolve();
    assert.equal(calls.length, 1);
    if (change === "page") await panel._selectAdminPage("network", "network_wifi_environment");
    else if (change === "view") panel._selectView("dashboard");
    else if (change === "user") panel.hass = {...panel._hass, user: {id: "other", is_admin: true}};
    else if (change === "permission") panel.hass = {...panel._hass, user: {id: "admin", is_admin: false}};
    else if (change === "router") {panel._selectRouter("missing-entry");}
    else if (change === "unload") {panel._metadata.routers[0].entry_state = "not_loaded"; panel._clearAdminRead();}
    else {panel.isConnected = false; panel.disconnectedCallback();}
    finish(response()); await opening;
    assert.equal(panel._adminPrivateQueries.ip.result, undefined);
    assert.ok(!panel._renderAdminIpInformation().includes("192.0.2.10"));
    assert.equal(calls.filter((call) => call.type.endsWith("/ip_information")).length, 1);
  });
}

test("failed IP read exposes a fixed error, no stale data, no automatic retry, and permits explicit refresh", async () => {
  let fail = true;
  const {panel, calls} = fixture(() => fail ? Promise.reject(new Error("PRIVATE-ADDRESS")) : response({ipv4: {}, ipv6: {}}));
  await panel._selectAdminPage("internet", "internet_ip_information");
  assert.ok(panel._adminPrivateQueries.ip.errorKey);
  assert.ok(!panel._renderAdminIpInformation().includes("PRIVATE-ADDRESS"));
  await panel._loadAdminPage(); assert.equal(calls.length, 1);
  fail = false; await panel._runIpInformationQuery();
  assert.equal(calls.length, 2);
  assert.ok(panel._renderAdminIpInformation().includes("Not reported by router"));
});

test("leaving a queued IP read cancels before transport and no non-admin page reads", async () => {
  let release;
  const {panel, calls} = fixture();
  panel._privateRequestQueue = new Promise((resolve) => {release = resolve;});
  const opening = panel._selectAdminPage("internet", "internet_ip_information");
  await Promise.resolve();
  await panel._selectAdminPage("network", "network_wifi_environment");
  release(); await opening;
  assert.equal(calls.length, 0);
  panel._hass.user.is_admin = false;
  await panel._selectAdminPage("internet", "internet_ip_information");
  assert.equal(calls.length, 0);
});
