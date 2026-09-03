import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {DASHBOARD_OVERVIEW_STYLES, renderDashboardOverview} from "../../custom_components/speedport_smart/frontend/dashboard-overview.js";

function fixture() {
  const router = {entry_id: "selected", entities: []};
  const states = {};
  const add = (key, value, options = {}) => {
    const domain = options.domain || "sensor";
    const meta = {entity_id: `${domain}.${key}`, domain, translation_key: key, ...options.meta};
    const state = {state: value, attributes: options.attributes || {}};
    router.entities.push(meta); states[meta.entity_id] = state;
    return meta;
  };
  const client = (id, name, medium, state = "home") => add(`client_${id}`, state, {
    domain: "device_tracker", attributes: {medium, ip: "private-address", mac: "private-mac"},
    meta: {child_device: {device_id: id, kind: "client", name}},
  });
  return {router, states, add, client, render: (options = {}) => renderDashboardOverview({router, states, ...options})};
}

test("empty metadata never fabricates hardware, counters, names or zero values", () => {
  const html = renderDashboardOverview({router: {name: "Secret name", capabilities: ["wifi", "dsl", "mobile", "lan"]}});
  assert.ok(html.includes("No overview telemetry"));
  assert.doesNotMatch(html, /data-more-info|data-overview-section|Secret name|>0</);
});

test("trusted internal traffic graph owns full-width first slot", () => {
  const f = fixture(); f.add("wifi_2_4_clients", "12");
  const html = f.render({trafficMarkup: '<section class="sp-traffic-history">Real graph</section>'});
  assert.ok(html.includes('aria-label="Live WAN traffic"'));
  assert.ok(html.indexOf("sp-traffic-history") < html.indexOf('data-overview-section="wifi"'));
  assert.equal(html.split("Real graph").length - 1, 1);
});

test("wireless bands retain separate actual status, channel and client counts", () => {
  const f = fixture();
  f.add("wifi_2_4_enabled", "on", {domain: "binary_sensor"});
  f.add("wifi_2_4_clients", "15"); f.add("wifi_2_4_channel", "11");
  f.add("wifi_5_enabled", "off", {domain: "binary_sensor"});
  f.add("wifi_5_clients", "0"); f.add("wifi_5_channel", "108");
  const html = f.render();
  assert.ok(html.includes('aria-label="2.4 GHz Wi-Fi"'));
  assert.ok(html.includes('aria-label="5 GHz Wi-Fi"'));
  assert.ok(html.includes('aria-label="2.4 GHz Wi-Fi: On"'));
  assert.ok(html.includes('aria-label="5 GHz Wi-Fi: Off"'));
  for (const value of ["15", "11", "0", "108"]) assert.ok(html.includes(`>${value}</strong>`));
  for (const meta of f.router.entities) assert.equal(html.split(`data-more-info="${meta.entity_id}"`).length - 1, 1);
  assert.doesNotMatch(html, /data-control|data-open-setting|switch|toggle/);
});

test("only advertised band appears, without inferring missing 5GHz", () => {
  const f = fixture(); f.add("wifi_2_4_clients", "2");
  const html = f.render();
  assert.ok(html.includes("2.4 GHz")); assert.ok(!html.includes("5 GHz"));
});

test("unknown and unavailable telemetry remains explicit, never zero", () => {
  const f = fixture(); f.add("wifi_2_4_clients", "unavailable"); f.add("wifi_2_4_channel", "unknown");
  const html = f.render();
  assert.ok(html.includes("Some data unavailable"));
  assert.ok(html.includes(">Unknown</strong>")); assert.ok(html.includes(">Unavailable</strong>"));
  assert.doesNotMatch(html, />0</);
});

test("numeric telemetry rejects empty, nonfinite, boolean and malformed states", () => {
  for (const value of ["", " ", "NaN", "Infinity", "broken", null, undefined, false, [], {}]) {
    const f = fixture(); f.add("wifi_2_4_clients", value);
    assert.ok(f.render().includes(">Unavailable</strong>"), String(value));
  }
});

test("Home Assistant formatting callbacks remain plain-text escaped and receive actual state", () => {
  const f = fixture(); const meta = f.add("dsl_downstream", "204.4");
  const html = f.render({
    formatState: (state, actualMeta) => {assert.equal(actualMeta, meta); assert.equal(state, f.states[meta.entity_id]); return "204.4 <Mbit/s>";},
    entityName: (actualMeta, state) => {assert.equal(actualMeta, meta); assert.equal(state, f.states[meta.entity_id]); return 'DSL "custom"';},
  });
  assert.ok(html.includes("204.4 &lt;Mbit/s&gt;"));
  assert.ok(html.includes("DSL &quot;custom&quot;"));
  assert.ok(!html.includes("<Mbit/s>"));
});

test("DSL sync and WAN capacity remain distinctly labeled, no throughput conflation", () => {
  const f = fixture();
  f.add("dsl_downstream", "204.4", {attributes: {unit_of_measurement: "Mbit/s"}});
  f.add("dsl_upstream", "42.5", {attributes: {unit_of_measurement: "Mbit/s"}});
  f.add("wan_download_capacity", "192.4", {attributes: {unit_of_measurement: "Mbit/s"}});
  f.add("wan_upload_capacity", "40", {attributes: {unit_of_measurement: "Mbit/s"}});
  f.add("download_rate", "7");
  const html = f.render();
  for (const text of ["Download sync", "Upload sync", "WAN download capacity", "WAN upload capacity", "Link speed, not current traffic", "204.4 Mbit/s", "192.4 Mbit/s"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes('data-more-info="sensor.download_rate"'));
});

test("mobile cards show actual network type and signal without assuming 5G", () => {
  const f = fixture();
  f.add("mobile_network_type", "LTE"); f.add("mobile_rsrp", "-81", {attributes: {unit_of_measurement: "dBm"}});
  f.add("mobile_band", "B3"); f.add("mobile_frequency", "1800", {attributes: {unit_of_measurement: "MHz"}});
  f.add("receiver_model", "Observed model");
  const html = f.render();
  for (const value of [">LTE</strong>", "-81 dBm", ">B3</strong>", "1800 MHz", "Observed model"]) assert.ok(html.includes(value));
  assert.ok(!html.includes("5G"));
});

test("NR-only telemetry has explicit 5G signal and band fallback", () => {
  const f = fixture(); f.add("mobile_nr_signal", "-75"); f.add("mobile_nr_band", "NR3500");
  const html = f.render();
  assert.ok(html.includes("5G signal")); assert.ok(html.includes("5G band"));
  assert.ok(html.includes("NR3500"));
});

test("LAN classification uses exact canonical medium, never missing wireless data", () => {
  const f = fixture();
  f.client("ethernet", "Wired desktop", "lan"); f.client("wifi", "Wireless laptop", "wifi_5");
  f.client("unknown", "Unclassified device", undefined); f.client("legacy", "Guessed Ethernet", "ethernet");
  const html = f.render();
  assert.ok(html.includes("Wired desktop")); assert.ok(html.includes("1 connected · 1 reported"));
  for (const text of ["Wireless laptop", "Unclassified device", "Guessed Ethernet", "private-address", "private-mac"]) assert.ok(!html.includes(text));
});

test("LAN presence does not turn unknown states into disconnected or home", () => {
  const f = fixture(); f.client("a", "Online", "lan"); f.client("b", "Offline", "lan", "not_home"); f.client("c", "Uncertain", "lan", "unknown");
  const html = f.render();
  assert.ok(html.includes("1 connected · 3 reported · some status unavailable"));
  assert.ok(html.includes('aria-label="Uncertain: Unavailable"'));
  assert.ok(html.includes('aria-label="Offline: Disconnected"'));
});

test("wired devices show their actual tracker link speed with accessible connectivity", () => {
  const f = fixture(); const meta = f.client("a", "Desktop", "lan");
  f.states[meta.entity_id].attributes.link_speed_bps = 2_500_000_000;
  const html = f.render();
  assert.ok(html.includes('aria-label="Desktop: Connected; Link speed 2.5 Gbit/s"'));
  assert.ok(html.includes(">2.5 Gbit/s</small>"));
  assert.ok(html.includes('title="Connected"'));
  assert.ok(html.includes("Negotiated link speed, not current traffic"));
});

function childSpeed(f, key, value, deviceId = "a", unit = "Mbit/s", flags = {}) {
  return f.add(`${deviceId}_${key}`, value, {attributes: {unit_of_measurement: unit},
    meta: {translation_key: key, child_device: {device_id: deviceId, kind: "client", name: "Desktop"}, ...flags}});
}

test("same-device directional link speeds remain distinct and use their own units", () => {
  const f = fixture(); f.client("a", "Desktop", "lan");
  childSpeed(f, "download_link_speed", "1000"); childSpeed(f, "upload_link_speed", "500");
  const html = f.render();
  assert.ok(html.includes(">↓ 1 Gbit/s · ↑ 500 Mbit/s</small>"));
  assert.ok(html.includes("Link speed download 1 Gbit/s, upload 500 Mbit/s"));
});

test("equal directional speeds collapse to one speed without doubling full duplex", () => {
  const f = fixture(); f.client("a", "Desktop", "lan");
  childSpeed(f, "download_link_speed", "1000"); childSpeed(f, "upload_link_speed", "1", "a", "Gbit/s");
  const html = f.render();
  assert.ok(html.includes(">1 Gbit/s</small>"));
  assert.ok(!html.includes("2 Gbit/s"));
});

test("generic child speed is used only for exact device identity and reported unit", () => {
  const f = fixture(); f.client("a", "Desktop", "lan");
  childSpeed(f, "link_speed", "100"); childSpeed(f, "download_link_speed", "10000", "other");
  const html = f.render();
  assert.ok(html.includes(">100 Mbit/s</small>")); assert.ok(!html.includes("10 Gbit/s"));
});

test("unknown link speeds never borrow per-port capacity or device throughput", () => {
  const f = fixture(); f.client("a", "Desktop", "lan");
  f.add("lan_port_1_speed", "1000", {attributes: {unit_of_measurement: "Mbit/s"}});
  childSpeed(f, "download_rate", "20"); childSpeed(f, "upload_rate", "10");
  const html = f.render();
  assert.ok(html.includes(">Link speed not reported</small>"));
  assert.ok(!html.includes("1 Gbit/s")); assert.ok(!html.includes("20 Mbit/s"));
});

test("offline and unavailable trackers never display cached link speed", () => {
  for (const state of ["not_home", "unknown", "unavailable"]) {
    const f = fixture(); const meta = f.client("a", "Desktop", "lan", state);
    f.states[meta.entity_id].attributes.link_speed_bps = 1_000_000_000;
    childSpeed(f, "download_link_speed", "1000"); childSpeed(f, "upload_link_speed", "1000");
    const html = f.render();
    assert.ok(!html.includes("1 Gbit/s"));
    assert.ok(html.includes(state === "not_home" ? ">Disconnected</small>" : ">Unavailable</small>"));
  }
});

test("malformed, zero, negative, unsupported-unit or disabled speed values fail honestly", () => {
  for (const value of ["0", "-1", "Infinity", "NaN", "", " ", null, true, [], {}, "<svg>"]) {
    const f = fixture(); const meta = f.client("a", "Desktop", "lan");
    f.states[meta.entity_id].attributes.link_speed_bps = value;
    childSpeed(f, "download_link_speed", value);
    assert.ok(f.render().includes(">Link speed not reported</small>"), String(value));
  }
  for (const options of [{unit: undefined}, {unit: "unknown"}, {flags: {disabled: true}}, {flags: {control_supported: true}}]) {
    const f = fixture(); f.client("a", "Desktop", "lan");
    const meta = childSpeed(f, "link_speed", "1000", "a", options.unit ?? "Mbit/s", options.flags);
    if (Object.hasOwn(options, "unit")) f.states[meta.entity_id].attributes.unit_of_measurement = options.unit;
    assert.ok(f.render().includes(">Link speed not reported</small>"));
  }
});

test("single observed direction stays explicitly directional", () => {
  const f = fixture(); f.client("a", "Desktop", "lan"); childSpeed(f, "upload_link_speed", "100");
  const html = f.render();
  assert.ok(html.includes(">↑ 100 Mbit/s</small>"));
  assert.ok(html.includes("Link speed upload 100 Mbit/s"));
});

test("LAN child grouping deduplicates metadata and ignores other child kinds", () => {
  const f = fixture(); const meta = f.client("a", "Desktop", "lan");
  f.router.entities.push(meta, {...meta, entity_id: "device_tracker.duplicate"});
  f.states["device_tracker.duplicate"] = f.states[meta.entity_id];
  f.add("storage", "home", {domain: "device_tracker", attributes: {medium: "lan"}, meta: {child_device: {kind: "storage", device_id: "other", name: "Storage secret"}}});
  const html = f.render();
  assert.ok(html.includes("1 connected · 1 reported"));
  assert.equal(html.split('data-more-info="device_tracker.client_a"').length - 1, 1);
  assert.ok(!html.includes("Storage secret"));
});

test("no known wired clients is absence of evidence, not a fabricated zero count", () => {
  const f = fixture(); f.client("wifi", "Laptop", "wifi_5");
  const html = f.render();
  assert.ok(html.includes("Wired-device details not reported"));
  assert.ok(!html.includes("0 connected"));
});

test("states without router metadata never cross router or permission scope", () => {
  const f = fixture(); f.states["sensor.mobile_operator"] = {state: "Private operator", attributes: {}};
  f.add("wifi_2_4_clients", "3"); f.states["device_tracker.denied"] = {state: "home", attributes: {medium: "lan", friendly_name: "Denied device"}};
  assert.ok(!f.render().includes("Private operator")); assert.ok(!f.render().includes("Denied device"));
});

test("control and disabled entities are excluded even with read-looking translation keys", () => {
  for (const flags of [{control: true}, {control_supported: true}, {disabled: true}, {disabled_by: "user"}]) {
    const f = fixture(); f.add("wifi_2_4_clients", "999", {meta: flags});
    assert.ok(!f.render().includes("999"));
  }
  const f = fixture(); f.add("wifi_2_4_enabled", "on", {domain: "switch"});
  assert.ok(!f.render().includes("data-more-info"));
});

test("root metric selection cannot borrow child sensor with same key", () => {
  const f = fixture(); f.add("mobile_rsrp", "-15", {meta: {child_device: {device_id: "child", kind: "client"}}});
  assert.ok(!f.render().includes("-15"));
});

test("device names, state values and units are escaped; malformed entity IDs rejected", () => {
  const f = fixture(); f.client("a", '<img src=x onerror="attack()">', "lan");
  f.add("mobile_operator", "<script>attack()</script>"); f.add("mobile_frequency", "123", {attributes: {unit_of_measurement: '<svg onload="attack()">'}});
  f.router.entities.push({domain: "sensor", translation_key: "wifi_2_4_clients", entity_id: 'sensor.bad" onclick="attack()'});
  const html = f.render();
  assert.doesNotMatch(html, /<img|<script|<svg| onclick=/);
  assert.ok(html.includes("&lt;img")); assert.ok(html.includes("&lt;script&gt;"));
});

test("Map state input follows same current metadata boundary", () => {
  const f = fixture(); f.add("wifi_2_4_clients", "4");
  assert.equal(f.render(), f.render({states: new Map(Object.entries(f.states))}));
});

test("responsive style inherits HA themes with full-width traffic and two-band hierarchy", () => {
  for (const text of ["var(--primary-text-color)", "var(--ha-card-background", "var(--secondary-text-color)", "var(--divider-color)", "repeat(auto-fit", "min(100%", "grid-column: 1 / -1", "button:focus-visible", "@media (max-width: 600px)"]) assert.ok(DASHBOARD_OVERVIEW_STYLES.includes(text), text);
  assert.doesNotMatch(DASHBOARD_OVERVIEW_STYLES, /#[0-9a-f]{3,8}\b|(?<![-\w])width:\s*\d{3,}px/);
});

test("overview is pure read-only presentation with no network, storage or timer path", async () => {
  const source = await readFile(new URL("../../custom_components/speedport_smart/frontend/dashboard-overview.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /fetch\(|callService|sendMessagePromise|localStorage|sessionStorage|setInterval|setTimeout|data-control=/);
});
