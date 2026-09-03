import assert from "node:assert/strict";
import test from "node:test";
import {NATIVE_ADMIN_TABS} from "../../custom_components/speedport_smart/frontend/admin-navigation.js";

globalThis.HTMLElement = class {
  attachShadow() {return this.shadowRoot = {addEventListener() {}, querySelector() {}, querySelectorAll() {return [];}};}
};
globalThis.customElements = {define() {}, get() {}};
const {SpeedportSmartPanel, ADMIN_IA, SETTINGS_FEATURE_LINKS} = await import("../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=setting-ownership");
const overlaps = ADMIN_IA.flatMap((area) => area.subsections.flatMap((section) => section.features))
  .filter((feature) => feature.controls.length && SETTINGS_FEATURE_LINKS[feature.id]);

test("all legacy entity controls with complete inline editors have one dashboard editing surface", () => {
  assert.deepEqual(overlaps.map((feature) => feature.id), ["internet_hybrid_bonding", "internet_receiver_led", "network_wifi_guest", "network_wifi_office"]);
  for (const feature of overlaps) {
    const settingId = SETTINGS_FEATURE_LINKS[feature.id].ids[0];
    const [domain, key] = feature.controls[0].split(":");
    const control = {entity_id: `${domain}.test_${key}`, domain, translation_key: key,
      control: true, control_supported: true, section: "controls", access_source: "protected_json"};
    const tab = NATIVE_ADMIN_TABS.find((item) => item.pages.some((page) => page.features.includes(feature.id)));
    const page = tab.pages.find((item) => item.features.includes(feature.id));
    const panel = new SpeedportSmartPanel();
    panel._render = () => {}; panel._adminTab = tab.id; panel._adminPage = page.id;
    panel._hass = {user: {id: "owner", is_admin: true}, states: {[control.entity_id]: {state: "on", attributes: {}}}};
    const setting = {id: settingId, title: "Reviewed setting", supported: true, available: true};
    const router = {entry_id: "entry", entry_state: "loaded", entities: [control], settings: [setting], management: {state: "available"}};
    panel._selectedEntry = "entry"; panel._metadata = {routers: [router]};
    const render = () => panel._renderAdministration(router, [control], [], {protected_json: {available: true}});
    const visible = () => render().includes(`data-admin-control-feature="${feature.id}"`);
    assert.equal(visible(), false, feature.id);
    assert.ok(render().includes(`data-settings-section="${settingId}"`), feature.id);
    setting.available = false;
    assert.equal(visible(), false, `${feature.id}: failed read must not add a second edit path`);
    setting.supported = false;
    assert.equal(visible(), true, `${feature.id}: unsupported editor must not remove legacy control`);
    setting.supported = true; panel._hass.user.is_admin = false;
    assert.equal(visible(), true, `${feature.id}: no admin editor means existing HA permission surface remains`);
    panel._hass.user.is_admin = true; router.settings = [];
    assert.equal(visible(), true, `${feature.id}: no editor advertisement means no suppression`);
  }
});

test("receiver mode stays read-only while the LED editor replaces duplicate LED report and control", () => {
  const panel = new SpeedportSmartPanel(); panel._render = () => {};
  panel._adminTab = "internet"; panel._adminPage = "internet_receiver_mode";
  const report = (key) => ({entity_id: `sensor.${key}`, domain: "sensor", translation_key: key,
    control: false, child_device: {device_id: "receiver", kind: "receiver"}, section: "mobile", access_source: "protected_json"});
  const reports = [report("receiver_mode"), report("receiver_led_mode")];
  const router = {entry_id: "entry", entry_state: "loaded", entities: reports,
    settings: [{id: "receiver_led_mode", title: "LED mode", supported: true, available: false}], management: {state: "available"}};
  panel._selectedEntry = "entry"; panel._metadata = {routers: [router]};
  panel._hass = {user: {id: "owner", is_admin: true}, states: {"sensor.receiver_mode": {state: "3", attributes: {}},
    "sensor.receiver_led_mode": {state: "use_leds", attributes: {}}}};
  const html = panel._renderAdministration(router, [], reports, {protected_json: {available: true}});
  assert.ok(html.includes('data-more-info="sensor.receiver_mode"'));
  assert.equal(html.split('data-more-info="sensor.receiver_mode"').length - 1, 1);
  assert.ok(html.includes('data-admin-feature-content="internet_receiver_mode"'));
  assert.ok(!html.includes('data-more-info="sensor.receiver_led_mode"'));
  assert.equal(html.split('data-settings-section="receiver_led_mode"').length - 1, 1);
});
