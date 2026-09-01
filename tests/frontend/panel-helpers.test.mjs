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

test("major sections fill the dashboard with wrapping source groups", () => {
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
  assert.match(sourceGroups, /display:\s*flex\s*;/);
  assert.match(sourceGroups, /flex-wrap:\s*wrap\s*;/);
  assert.doesNotMatch(sourceGroups, /grid-template-columns|auto-fit/);

  const sourceGroup = cssDeclarations(".entity-source-group");
  assert.match(
    sourceGroup,
    /flex:\s*1\s+1\s+min\(\s*100%\s*,\s*400px\s*\)\s*;/,
  );

  assert.ok(
    /const sourceGroupClass\s*=\s*capabilityGroups\.size\s*>=\s*3\s*\?\s*"entity-source-group source-group-wide"\s*:\s*"entity-source-group"/.test(
      panelSource,
    ),
    "Three or more capability blocks must mark their source group wide",
  );
  assert.ok(
    /class="\$\{sourceGroupClass\}"/.test(panelSource),
    "Rendered source groups must use the computed width class",
  );
  const wideSourceGroup = cssDeclarations(
    ".entity-source-group.source-group-wide",
  );
  assert.match(wideSourceGroup, /flex-basis:\s*100%\s*;/);

  const narrowSourceGroups = cssDeclarations(
    ":host([narrow]) .entity-source-group",
  );
  assert.match(narrowSourceGroups, /flex-basis:\s*100%\s*;/);

  assert.equal(
    /^\s*\.entity-source-groups\s*\{[^}]*grid-template-columns/ims.test(
      panelSource,
    ),
    false,
    "Source groups must not return to a fixed auto-fit grid",
  );
});
