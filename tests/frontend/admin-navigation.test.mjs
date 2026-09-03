import assert from "node:assert/strict";
import test from "node:test";

import {
  NATIVE_ADMIN_TABS, resolveAdminPage, adminPageSettings, adminPageFeatures,
} from "../../custom_components/speedport_smart/frontend/admin-navigation.js";

globalThis.HTMLElement = class {};
globalThis.customElements = {get() {}, define() {}};
const {ADMIN_IA, SETTINGS_FEATURE_LINKS} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=native-navigation"
);
const pages = NATIVE_ADMIN_TABS.flatMap((item) => item.pages);
const routerAreas = ADMIN_IA.filter((item) => item.id !== "home_assistant");
const routerFeatures = routerAreas.flatMap((area) => area.subsections)
  .flatMap((section) => section.features);
const find = (id) => pages.find((item) => item.id === id);
const settings = [...new Set(Object.values(SETTINGS_FEATURE_LINKS).flatMap((item) => item.ids))]
  .map((id) => ({id, title: id, supported: true, available: true}));

test("native main tabs preserve the six manual tabs and order", () => {
  assert.deepEqual(NATIVE_ADMIN_TABS.map((item) => item.id),
    ["overview", "status", "internet", "telephony", "network", "system"]);
  assert.deepEqual(NATIVE_ADMIN_TABS.map((item) => item.title),
    ["Overview", "Status", "Internet", "Telephony", "Network", "System"]);
});

test("native sidebar main ordering matches the reviewed manual screenshots", () => {
  const roots = (id) => NATIVE_ADMIN_TABS.find((item) => item.id === id).pages
    .filter((item) => !item.parentId).map((item) => item.id);
  assert.deepEqual(roots("internet"), ["internet_connection", "internet_receiver", "internet_parental", "internet_port_forwarding", "internet_port_blocking", "internet_ddns"]);
  assert.deepEqual(roots("telephony"), ["telephony_registration", "telephony_assignment", "telephony_socket", "telephony_dect", "telephony_pbx", "telephony_number_settings", "telephony_calls", "telephony_phonebook"]);
  assert.deepEqual(roots("network"), ["network_devices", "network_wifi", "network_wifi_access", "network_addresses", "network_prioritization", "network_dns_rebind", "network_vpn", "network_smarthome", "network_storage"]);
  assert.deepEqual(roots("system"), ["system_password", "system_easysupport", "system_energy", "system_backup", "system_recovery", "system_firmware", "system_information", "system_notifications", "system_dsl_modem", "system_protection", "system_external_modem"]);
});

test("connection and Wi-Fi children have native grouping and order", () => {
  const children = (id) => pages.filter((item) => item.parentId === id).map((item) => item.id);
  assert.deepEqual(children("internet_connection"), ["internet_access_data", "internet_usb_tethering", "internet_ip_information", "internet_privacy"]);
  assert.deepEqual(children("network_wifi"), ["network_wifi_basic", "network_wifi_identity", "network_wifi_transmission", "network_wifi_office", "network_wifi_guest", "network_wifi_environment"]);
  assert.deepEqual(adminPageSettings(find("internet_access_data"), settings, SETTINGS_FEATURE_LINKS).map((item) => item.id), ["internet_connection"]);
});

test("navigation objects and every nested collection are immutable", () => {
  assert.ok(Object.isFrozen(NATIVE_ADMIN_TABS));
  for (const item of NATIVE_ADMIN_TABS) {
    assert.ok(Object.isFrozen(item)); assert.ok(Object.isFrozen(item.pages));
    for (const current of item.pages) {
      assert.ok(Object.isFrozen(current));
      for (const key of ["features", "settings", "entityGroups", "readSections"]) assert.ok(Object.isFrozen(current[key]));
    }
  }
  assert.throws(() => find("network_wifi_basic").features.push("arbitrary"), TypeError);
});

test("all IDs are unique and children belong to an earlier page in the same tab", () => {
  assert.equal(new Set(pages.map((item) => item.id)).size, pages.length);
  for (const item of NATIVE_ADMIN_TABS) {
    const seen = new Set();
    for (const current of item.pages) {
      assert.match(current.id, /^[a-z][a-z0-9_]*$/);
      if (current.parentId) assert.ok(seen.has(current.parentId), current.id);
      seen.add(current.id);
      for (const key of ["features", "settings", "entityGroups", "readSections"]) assert.equal(new Set(current[key]).size, current[key].length);
    }
  }
});

test("every existing router feature, control and action remains mapped exactly once", () => {
  const ids = pages.flatMap((item) => item.features);
  assert.equal(new Set(ids).size, ids.length, "a capability must have one primary native page");
  assert.deepEqual([...ids].sort(), routerFeatures.map((item) => item.id).sort());
  const mapped = pages.flatMap((item) => adminPageFeatures(item, ADMIN_IA));
  assert.equal(mapped.length, routerFeatures.length);
  for (const feature of routerFeatures) assert.equal(mapped.find((item) => item.id === feature.id), feature);
  for (const property of ["controls", "adminActions", "queries"]) {
    assert.deepEqual(mapped.flatMap((item) => item[property]).sort(), routerFeatures.flatMap((item) => item[property]).sort());
  }
});

test("every router read section and entity family remains represented", () => {
  const sections = routerAreas.flatMap((area) => area.subsections);
  const groups = new Set(pages.flatMap((item) => item.entityGroups));
  const reads = new Set(pages.flatMap((item) => item.readSections));
  for (const section of sections) {
    for (const group of section.entityGroups) assert.ok(groups.has(group), group);
    for (const read of section.readSections) assert.ok(reads.has(read.id), read.id);
  }
});

test("all advertised linked settings remain mapped without duplicate page launchers", () => {
  const mapped = pages.flatMap((item) => adminPageSettings(item, settings, SETTINGS_FEATURE_LINKS));
  assert.deepEqual([...new Set(mapped.map((item) => item.id))].sort(), settings.map((item) => item.id).sort());
  assert.equal(mapped.length, settings.length, "shared catalog links must not duplicate an editor across native pages");
});

test("main, guest and prioritized Wi-Fi settings never leak across feature aliases", () => {
  const expected = {
    wifi_identity: "network_wifi_identity",
    wifi_guest_settings: "network_wifi_guest",
    wifi_office_settings: "network_wifi_office",
  };
  for (const [id, owner] of Object.entries(expected)) {
    const owners = pages.filter((item) => adminPageSettings(item, settings, SETTINGS_FEATURE_LINKS).some((setting) => setting.id === id));
    assert.deepEqual(owners.map((item) => item.id), [owner]);
  }
  assert.deepEqual(find("network_wifi_identity").readSections, ["wifi_2_4_identity", "wifi_5_identity"]);
  assert.deepEqual(find("network_wifi_guest").readSections, ["wifi_guest_identity"]);
});

test("settings preserve advertised availability, exclude unknown IDs and deduplicate", () => {
  const unavailable = {id: "wifi_identity", available: false, supported: false};
  const advertised = [unavailable, {id: "wifi_identity", available: true}, {id: "not_a_router_setting"}];
  assert.deepEqual(adminPageSettings(find("network_wifi_identity"), advertised, SETTINGS_FEATURE_LINKS), [unavailable]);
  assert.equal(adminPageSettings(find("network_wifi_identity"), advertised, SETTINGS_FEATURE_LINKS)[0], unavailable);
  assert.deepEqual(adminPageSettings(find("network_wifi_identity"), [], SETTINGS_FEATURE_LINKS), []);
});

test("HA-only diagnostics do not become native router navigation", () => {
  assert.ok(pages.every((item) => !item.features.some((id) => id.startsWith("home_assistant_"))));
  assert.ok(pages.every((item) => !item.entityGroups.includes("management_session")));
});

test("resolver rejects cross-tab pages and unknown paths with deterministic defaults", () => {
  assert.equal(resolveAdminPage("network", "network_wifi_guest").page, find("network_wifi_guest"));
  assert.equal(resolveAdminPage("network", "network_wifi").page, find("network_wifi_basic"));
  assert.equal(resolveAdminPage("internet", "network_wifi_guest").page, find("internet_connection"));
  for (const value of [undefined, null, "__proto__", "constructor", "/data/Login.json", "https://router.invalid"]) {
    assert.equal(resolveAdminPage(value, value).page, find("overview"));
  }
});

test("mapping helpers do not accept an injected page model", () => {
  const forged = {...find("network_wifi_identity"), features: ["system_router_password"]};
  assert.deepEqual(adminPageFeatures(forged, ADMIN_IA), []);
  assert.deepEqual(adminPageSettings(forged, settings, SETTINGS_FEATURE_LINKS), []);
  assert.deepEqual(adminPageFeatures(null, ADMIN_IA), []);
  assert.deepEqual(adminPageSettings(null, settings, SETTINGS_FEATURE_LINKS), []);
});
