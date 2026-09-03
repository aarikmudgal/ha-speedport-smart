import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

import {
  NATIVE_ADMIN_TABS, resolveAdminPage, adminPageSettings, adminPageFeatures,
  adminPageSettingSections, adminPageInlineSettings,
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

test("native main tabs preserve the six observed router tabs and order", () => {
  assert.deepEqual(NATIVE_ADMIN_TABS.map((item) => item.id),
    ["overview", "status", "internet", "telephony", "network", "system"]);
  assert.deepEqual(NATIVE_ADMIN_TABS.map((item) => item.title),
    ["Overview", "Status", "Internet", "Telephony", "Network", "System"]);
});

test("native sidebar main ordering matches authenticated router sidebar including QoS", () => {
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

test("observed native subpages retain exact separate headings and order", () => {
  const expected = {
    internet_receiver: ["Connection", "Mode settings", "Firmware and reset", "Routing exceptions"],
    telephony_dect: ["Settings for DECT", "Registered handsets", "Registered repeaters"],
    telephony_number_settings: ["Phone number usage", "Security settings", "High voice quality (HD Voice)", "Dial delay", "Status message", "Number memory (Speeddial)"],
    telephony_calls: ["Missed calls", "Received calls", "Dialed outgoing calls"],
    telephony_phonebook: ["Basic settings", "Entries", "Assignment"],
    network_wifi: ["Basic settings", "Name and encryption", "Send settings", "Prioritized Wi-Fi", "Guest access", "Environment scan"],
    network_wifi_access: ["Add device via WPS", "Access limit"],
    network_addresses: ["Router addresses", "Address assignment (DHCP)"],
    network_storage: ["USB port", "Sharing", "Workgroup", "Media playback"],
    system_recovery: ["Restart", "Reset", "DECT", "Mesh"],
    system_firmware: ["Speedport", "Mesh"],
    system_information: ["Data and version numbers", "Active services", "System messages"],
  };
  for (const [id, titles] of Object.entries(expected)) {
    assert.deepEqual(pages.filter((item) => item.parentId === id).map((item) => item.title), titles, id);
  }
  for (const [id, title] of Object.entries({system_backup: "Save settings", system_recovery: "Problem handling", system_notifications: "E-mail notification", system_protection: "Guard functions"})) assert.equal(find(id).title, title);
});

test("all 69 observed destinations are leaf pages; every navigation parent opens first child", () => {
  const parentIds = new Set(pages.map((item) => item.parentId).filter(Boolean));
  assert.equal(pages.filter((item) => !parentIds.has(item.id)).length, 69);
  for (const item of NATIVE_ADMIN_TABS) for (const parent of item.pages.filter((current) => parentIds.has(current.id))) {
    assert.equal(resolveAdminPage(item.id, parent.id).page, item.pages.find((current) => current.parentId === parent.id));
    for (const key of ["features", "settings", "entityGroups", "readSections"]) assert.equal(parent[key].length, 0, `${parent.id}: ${key}`);
  }
});

test("observed native paths are parity evidence only, never arbitrary URL navigation", () => {
  const known = {
    internet_receiver_connection: "internet/lte.html", internet_receiver_mode: "internet/lte_mode.html", internet_receiver_firmware: "internet/lte_firmware.html", internet_receiver_exceptions: "internet/except.html",
    telephony_number_usage: "phone/phone_lineset.html", telephony_number_security: "phone/phone_linevosip.html", telephony_number_hd_voice: "phone/phone_linehdvoice.html", telephony_number_dial_delay: "phone/phone_linedialdelay.html", telephony_number_status_message: "phone/phone_linestataudio.html", telephony_number_speeddial: "phone/phone_linespeeddial.html",
    telephony_calls_missed: "phone/phone_call_missed.html", telephony_calls_taken: "phone/phone_call_taken.html", telephony_calls_dialed: "phone/phone_call_dialed.html",
    telephony_phonebook_basic: "phone/phone_book_basic.html", telephony_phonebook_entries: "phone/phone_book_entries.html", telephony_phonebook_assignment: "phone/phone_book_assign.html",
    network_wifi_wps: "network/wlan_wps.html", network_wifi_access_limit: "network/wlan_access.html", network_lan_addresses: "network/lan.html", network_lan_dhcp: "network/dhcp.html", network_prioritization: "network/qos.html",
    network_storage_usb: "network/nas_overview.html", network_storage_sharing: "network/nas_share.html", network_storage_workgroup: "network/nas_workgroup.html", network_storage_media: "network/nas_mediareplay.html",
    system_recovery_restart: "config/restart.html", system_recovery_reset: "config/reset.html", system_recovery_dect: "config/problem_handling_dect.html", system_recovery_mesh: "config/problem_handling_mesh.html",
    system_firmware_speedport: "config/check_for_updates.html", system_firmware_mesh: "config/check_for_updates_mesh.html", system_information_data: "config/system_info.html", system_information_services: "config/system_services.html", system_information_messages: "config/system_log.html",
  };
  for (const [id, nativePath] of Object.entries(known)) {
    assert.equal(find(id).nativePath, nativePath);
    assert.equal(resolveAdminPage("overview", nativePath).page.id, "overview");
  }
  for (const item of pages.filter((current) => current.nativePath)) assert.match(item.nativePath, /^(?:(?:internet|network|phone|config)\/[a-z_]+|\/html\/content\/overview\/index|\/html\/login\/status)\.html$/);
});

test("all 69 leaf paths and their order exactly match the completed authenticated audit", async () => {
  const audit = await readFile(new URL("../../docs/NATIVE_ADMIN_NAVIGATION.md", import.meta.url), "utf8");
  const observed = [...audit.matchAll(/^\|[^|\n]+\| `([^`]+\.html)` \|/gm)].map((match) => match[1]);
  const canonical = (path) => path.startsWith("/") ? path : `/html/content/${path}`;
  const parentIds = new Set(pages.map((item) => item.parentId).filter(Boolean));
  const leaves = pages.filter((item) => !parentIds.has(item.id));
  assert.equal(observed.length, 69);
  assert.equal(leaves.length, 69);
  assert.ok(leaves.every((item) => typeof item.nativePath === "string"));
  assert.deepEqual(leaves.map((item) => canonical(item.nativePath)), observed.map(canonical));
  assert.equal(new Set(leaves.map((item) => canonical(item.nativePath))).size, 69);
  assert.ok(pages.filter((item) => parentIds.has(item.id)).every((item) => !Object.hasOwn(item, "nativePath")));
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

test("broad phonebook, call-list and NAS features keep each form on its exact native page", () => {
  const expected = {
    call_history_clear_missed: "telephony_calls_missed", call_history_clear_taken: "telephony_calls_taken", call_history_clear_dialed: "telephony_calls_dialed",
    telephony_phonebook_update_interval: "telephony_phonebook_basic", telephony_phonebook_rename: "telephony_phonebook_basic", telephony_phonebook_account_create: "telephony_phonebook_basic",
    telephony_phonebook_contact: "telephony_phonebook_entries", telephony_phonebook_create: "telephony_phonebook_entries", telephony_handset_phonebook: "telephony_phonebook_assignment",
    nas_workgroup: "network_storage_workgroup", storage_nas_share: "network_storage_sharing", storage_media_folder: "network_storage_media",
    receiver_bonding: "internet_receiver_mode", receiver_led_mode: "internet_receiver_mode",
    telephony_hd_voice: "telephony_number_hd_voice", telephony_dial_delay: "telephony_number_dial_delay", telephony_voice_encryption: "telephony_number_security",
  };
  for (const [id, owner] of Object.entries(expected)) {
    assert.deepEqual(pages.filter((item) => adminPageSettings(item, settings, SETTINGS_FEATURE_LINKS).some((setting) => setting.id === id)).map((item) => item.id), [owner], id);
  }
});

test("existing scalar and target-bound edits are inline; actions remain contextual", () => {
  for (const [pageId, inline, contextual] of [
    ["telephony_assignment", ["telephony_incoming_assignment", "telephony_outgoing_assignment"], []],
    ["telephony_number_usage", ["telephony_line_options"], []],
    ["telephony_number_speeddial", ["telephony_automatic_speed_dial"], ["telephony_number_memory_clear"]],
    ["network_storage_sharing", ["storage_nas_share"], ["storage_nas_share_create"]],
    ["network_vpn", ["vpn_peer_enabled"], ["vpn_peer_create", "vpn_peer_delete", "vpn_ipsec_key_rotate"]],
    ["internet_parental", ["parental_profile_edit", "system_oled_display_rule"], ["parental_profile_create", "parental_profile_delete"]],
    ["system_firmware_speedport", [], ["system_router_firmware_online"]],
    ["system_password", ["system_router_password_change"], []],
  ]) {
    const sections = adminPageSettingSections(find(pageId), settings, SETTINGS_FEATURE_LINKS);
    assert.deepEqual(sections.inline.map((item) => item.id), inline, pageId);
    assert.deepEqual(sections.contextual.map((item) => item.id), contextual, pageId);
    assert.deepEqual(adminPageInlineSettings(find(pageId), settings, SETTINGS_FEATURE_LINKS), sections.inline);
  }
});

test("parental Display switch belongs only to the observed time-rules page", () => {
  const parental = find("internet_parental");
  const energy = find("system_energy");
  assert.equal(parental.nativePath, "internet/chd_timerules.html");
  assert.ok(parental.features.includes("system_local_display_settings"));
  assert.ok(parental.entityGroups.includes("system_local_display"));
  assert.ok(!energy.features.includes("system_local_display_settings"));
  assert.ok(!energy.entityGroups.includes("system_local_display"));
  assert.deepEqual(pages.filter((item) => adminPageSettings(item, settings, SETTINGS_FEATURE_LINKS).some((setting) => setting.id === "system_oled_display_rule")).map((item) => item.id), ["internet_parental"]);
  assert.deepEqual(adminPageInlineSettings(energy, settings, SETTINGS_FEATURE_LINKS).map((item) => item.id), ["system_led_schedule", "system_energy"]);
  assert.ok(!adminPageSettings(parental, settings, SETTINGS_FEATURE_LINKS).some((item) => ["wifi_identity", "wifi_guest_settings"].includes(item.id)));
});

test("inline classification is conservative and preserves every descriptor and permission flag", () => {
  const exact = {id: "telephony_line_options", requires_target: true, available: false, supported: false, confirmation: "SAVE SETTINGS"};
  const sections = adminPageSettingSections(find("telephony_number_usage"), [exact], SETTINGS_FEATURE_LINKS);
  assert.equal(sections.inline[0], exact);
  const unknown = {id: "future_action", available: true};
  assert.deepEqual(adminPageSettingSections(find("telephony_number_usage"), [unknown], {telephony_number_use: {ids: ["future_action"]}}), {inline: [], contextual: [unknown]});
  for (const item of pages) {
    const mapped = adminPageSettings(item, settings, SETTINGS_FEATURE_LINKS);
    const split = adminPageSettingSections(item, settings, SETTINGS_FEATURE_LINKS);
    assert.equal(split.inline.length + split.contextual.length, mapped.length);
    for (const descriptor of mapped) assert.ok([...split.inline, ...split.contextual].includes(descriptor));
    assert.ok(split.inline.every((descriptor) => !/(?:create|delete|_reset|_clear|_reindex|_activate|_deactivate|_rotate|_firmware_online)/.test(descriptor.id)));
  }
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
  assert.equal(resolveAdminPage("internet", "network_wifi_guest").page, find("internet_access_data"));
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
  assert.deepEqual(adminPageSettingSections(forged, settings, SETTINGS_FEATURE_LINKS), {inline: [], contextual: []});
});
