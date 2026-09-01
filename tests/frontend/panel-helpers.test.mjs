import assert from "node:assert/strict";
import test from "node:test";

globalThis.HTMLElement = class {};
globalThis.customElements = {
  define() {},
  get() {
    return undefined;
  },
};

const {
  capabilityGroupFor,
  internetConnectionPresentation,
} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=panel-helpers"
);

test("dashboard fallback hierarchy keeps related router features together", () => {
  const cases = [
    ["wireless", "wifi_2_4_visible", "wireless_2_4"],
    ["wireless", "wifi_5_visible", "wireless_5"],
    ["wireless", "wifi_wps_active", "wireless_wps"],
    ["wireless", "wifi_mac_filter_enabled", "wireless_access"],
    ["wireless", "wifi_schedule_enabled", "wireless_schedule"],
    ["telephony", "pbx_enabled", "telephony_pbx"],
  ];

  for (const [section, translationKey, expectedGroup] of cases) {
    assert.equal(
      capabilityGroupFor({
        section,
        translation_key: translationKey,
        domain: "binary_sensor",
      }),
      expectedGroup,
      translationKey,
    );
  }
});

test("explicit backend capability groups remain authoritative", () => {
  assert.equal(
    capabilityGroupFor({
      section: "wireless",
      translation_key: "wifi_band_mode",
      capability_group: "wireless_radios",
      domain: "sensor",
    }),
    "wireless_radios",
  );
});

test("Internet connection presentation distinguishes unavailable from offline", () => {
  assert.deepEqual(internetConnectionPresentation(undefined), {
    className: "unavailable",
    labelKey: "hero.connection_unavailable",
  });
  assert.deepEqual(internetConnectionPresentation({ state: "unavailable" }), {
    className: "unavailable",
    labelKey: "hero.connection_unavailable",
  });
  assert.deepEqual(internetConnectionPresentation({ state: "unknown" }), {
    className: "unavailable",
    labelKey: "hero.connection_unavailable",
  });
  assert.deepEqual(internetConnectionPresentation({ state: "off" }), {
    className: "offline",
    labelKey: "hero.disconnected",
  });
  assert.deepEqual(internetConnectionPresentation({ state: "on" }), {
    className: "online",
    labelKey: "hero.connected",
  });
});
