import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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
const panelSource = await readFile(
  new URL(
    "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js",
    import.meta.url,
  ),
  "utf8",
);

function cssDeclarations(selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = panelSource.match(
    new RegExp(`^\\s*${escapedSelector}\\s*\\{([^}]*)\\}`, "m"),
  );
  assert.ok(match, `Missing CSS rule for ${selector}`);
  return match[1].replace(/\s+/g, " ");
}

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

test("major sections fill the dashboard while source groups respond inside them", () => {
  const sections = cssDeclarations(".sections");
  assert.match(
    sections,
    /grid-template-columns:\s*(?:1fr|minmax\(\s*0\s*,\s*1fr\s*\))\s*;/,
  );
  assert.doesNotMatch(sections, /repeat\(\s*2\s*,/);

  const dashboardSection = cssDeclarations(".dashboard-section");
  assert.match(dashboardSection, /grid-column:\s*1\s*\/\s*-1\s*;/);
  assert.match(dashboardSection, /width:\s*100%\s*;/);

  const sourceGroups = cssDeclarations(".entity-source-groups");
  assert.match(
    sourceGroups,
    /grid-template-columns:\s*repeat\(\s*auto-fit\s*,\s*minmax\(\s*min\(\s*100%\s*,\s*400px\s*\)\s*,\s*1fr\s*\)\s*\)\s*;/,
  );

  const narrowSourceGroups = cssDeclarations(
    ":host([narrow]) .entity-source-groups",
  );
  assert.match(narrowSourceGroups, /grid-template-columns:\s*1fr\s*;/);
});
