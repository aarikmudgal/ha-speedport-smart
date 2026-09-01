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
  liveWanSourceFromEntityStates,
  wanTelemetryPresentation,
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

test("WAN telemetry presentation separates cached totals from rate warm-up", () => {
  const source = {
    id: "wan_counters",
    mode: "auto",
    state: "retrying",
    retrying: true,
    effective_interval_seconds: 4,
    last_stable_interval_seconds: 5,
    last_sampled_at: "2026-09-01T10:00:00.000Z",
  };
  const now = Date.parse("2026-09-01T10:00:12.900Z");

  assert.deepEqual(
    wanTelemetryPresentation(
      { access_source: "wan_counters", translation_key: "wan_bytes_received" },
      { state: "12.3" },
      source,
      now,
    ),
    {
      degraded: true,
      effectiveIntervalSeconds: 4,
      fastestProvenIntervalSeconds: 5,
      lastConfirmed: true,
      mode: "auto",
      rateStatusKey: undefined,
      retrying: true,
      retryInSeconds: undefined,
      sampleAgeSeconds: 12,
      schedulerState: "retrying",
    },
  );
  assert.equal(
    wanTelemetryPresentation(
      { access_source: "wan_counters", translation_key: "wan_download_rate" },
      { state: "unavailable" },
      source,
      now,
    ).rateStatusKey,
    "status.rate_retrying",
  );

  assert.equal(
    wanTelemetryPresentation(
      { access_source: "wan_counters", translation_key: "wan_download_rate" },
      { state: "unavailable" },
      { ...source, state: "learning", retrying: false },
      now,
    ).rateStatusKey,
    "status.rate_warming",
  );
});

test("generic WAN endpoint errors are stale, never rate warm-up", () => {
  const source = {
    id: "wan_counters",
    supported: true,
    available: false,
    state: "stable",
    retrying: false,
    last_sampled_at: "2026-09-01T10:00:00.000Z",
  };
  const total = wanTelemetryPresentation(
    { access_source: "wan_counters", translation_key: "wan_packets_received" },
    { state: "42" },
    source,
    Date.parse("2026-09-01T10:00:03.000Z"),
  );
  const rate = wanTelemetryPresentation(
    { access_source: "wan_counters", translation_key: "wan_download_rate" },
    { state: "unavailable" },
    source,
  );
  const warmUpRate = wanTelemetryPresentation(
    { access_source: "wan_counters", translation_key: "wan_download_rate" },
    { state: "unavailable" },
    { ...source, available: true },
  );

  assert.equal(total.lastConfirmed, true);
  assert.equal(total.degraded, true);
  assert.equal(rate.rateStatusKey, "status.rate_unavailable");
  assert.equal(warmUpRate.rateStatusKey, "status.rate_warming");
});

test("native WAN diagnostics override stale metadata between refreshes", () => {
  const source = {
    id: "wan_counters",
    supported: true,
    available: true,
    mode: "auto",
    state: "stable",
    retrying: false,
    effective_interval_seconds: 5,
  };
  const entities = [
    ["wan_polling_mode", "sensor.router_wan_polling_mode"],
    ["wan_polling_interval", "sensor.router_wan_polling_interval"],
    ["wan_polling_state", "sensor.router_wan_polling_state"],
    [
      "wan_fastest_proven_interval",
      "sensor.router_wan_fastest_proven_interval",
    ],
    ["wan_last_sample", "sensor.router_wan_last_sample"],
  ].map(([translation_key, entity_id]) => ({ translation_key, entity_id }));
  const states = {
    "sensor.router_wan_polling_mode": { state: "auto", attributes: {} },
    "sensor.router_wan_polling_interval": { state: "4", attributes: {} },
    "sensor.router_wan_polling_state": {
      state: "retrying",
      attributes: { source_available: false, retry_in_seconds: 3 },
    },
    "sensor.router_wan_fastest_proven_interval": {
      state: "5",
      attributes: {},
    },
    "sensor.router_wan_last_sample": {
      state: "2026-09-01T10:00:00+00:00",
      attributes: {},
    },
  };

  const live = liveWanSourceFromEntityStates(source, entities, states);

  assert.equal(live.available, false);
  assert.equal(live.retrying, true);
  assert.equal(live.state, "retrying");
  assert.equal(live.effective_interval_seconds, 4);
  assert.equal(live.last_stable_interval_seconds, 5);
  assert.equal(live.retry_in_seconds, 3);
  assert.equal(live.last_sampled_at, "2026-09-01T10:00:00+00:00");
});

test("WAN metadata refresh and stale styling meet the freshness contract", () => {
  const refresh = panelSource.match(
    /const METADATA_REFRESH_INTERVAL_MS\s*=\s*([\d_]+)\s*;/,
  );
  assert.ok(refresh, "Missing metadata refresh interval constant");
  assert.ok(
    Number(refresh[1].replaceAll("_", "")) <= 10_000,
    "WAN source metadata must refresh within ten seconds",
  );
  assert.match(cssDeclarations(".entity-card.last-confirmed"), /sp-warning/);
  assert.match(
    cssDeclarations(
      ".entity-card.last-confirmed > .entity-main .availability-dot",
    ),
    /sp-warning/,
  );
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
