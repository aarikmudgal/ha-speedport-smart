import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

class TestElement {
  attachShadow() {
    this.shadowRoot = {
      activeElement: undefined,
      innerHTML: "",
      addEventListener() {},
      querySelector() {
        return undefined;
      },
      querySelectorAll() {
        return [];
      },
    };
    return this.shadowRoot;
  }

  dispatchEvent() {}

  toggleAttribute() {}
}

globalThis.HTMLElement = TestElement;
globalThis.customElements = {
  define() {},
  get() {
    return undefined;
  },
};

const {
  ADMIN_READ_FIELD_KEYS,
  ADMIN_READ_SECTION_FIELDS,
  ADMIN_READ_SECTION_ORDER,
  SpeedportSmartPanel,
  formatAdminReadValue,
  normalizeAdminReadPayload,
  splitPanelEntities,
} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=panel-admin"
);
const { PANEL_TRANSLATIONS } = await import(
  "../../custom_components/speedport_smart/frontend/translations.js"
);

const REPORTING_META = Object.freeze({
  access_source: "protected_json",
  confirmation: "confirm",
  control: false,
  disruptive: false,
  domain: "sensor",
  entity_id: "sensor.speedport_system_cpu",
  risk: "normal",
  section: "system",
  translation_key: "system_cpu",
});
const CONTROL_META = Object.freeze({
  access_source: "router_control",
  confirmation: "confirm",
  control: true,
  disruptive: true,
  domain: "button",
  entity_id: "button.speedport_reboot_router",
  risk: "disruptive",
  section: "controls",
  translation_key: "reboot_router",
});

function adminPayload(entryId = "entry-a", sections = []) {
  return { entry_id: entryId, schema_version: 1, sections };
}

function router(entryId, entities = [REPORTING_META, CONTROL_META]) {
  return {
    access_sources: [],
    capabilities: [],
    capability_families: [],
    entities,
    entry_id: entryId,
    entry_state: "loaded",
    management: undefined,
    model: "Speedport Smart 4R Typ A",
    title: entryId,
  };
}

function panelFixture({ admin = true, entries = ["entry-a"] } = {}) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._metadata = { routers: entries.map((entry) => router(entry)) };
  panel._selectedEntry = entries[0];
  panel._hass = {
    connection: {
      async sendMessagePromise(message) {
        calls.push(message);
        return adminPayload(message.entry_id, [
          {
            id: "clients",
            rows: [{ connected: true, name: "Laptop" }],
            source: "protected_json",
            truncated: false,
          },
        ]);
      },
    },
    language: "en",
    locale: { language: "en-US" },
    states: {},
    user: { is_admin: admin },
  };
  return { calls, panel };
}

test("Dashboard and Administration use disjoint entity sets", () => {
  assert.deepEqual(splitPanelEntities([REPORTING_META, CONTROL_META]), {
    controls: [CONTROL_META],
    reporting: [REPORTING_META],
  });
});

test("panel renders reporting only on Dashboard and controls only in Administration", () => {
  const fixture = panelFixture();
  fixture.panel._hass.states = {
    [REPORTING_META.entity_id]: {
      attributes: { friendly_name: "Router CPU" },
      state: "20",
    },
    [CONTROL_META.entity_id]: {
      attributes: { friendly_name: "Reboot router" },
      state: "unknown",
    },
  };
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ name: "Cached laptop" }],
        source: "protected_json",
        truncated: false,
      },
    ]),
    "entry-a",
  );

  SpeedportSmartPanel.prototype._render.call(fixture.panel);
  assert.match(fixture.panel.shadowRoot.innerHTML, /sensor\.speedport_system_cpu/);
  assert.doesNotMatch(
    fixture.panel.shadowRoot.innerHTML,
    /button\.speedport_reboot_router|Cached laptop/,
  );

  fixture.panel._activeView = "administration";
  SpeedportSmartPanel.prototype._render.call(fixture.panel);
  assert.match(
    fixture.panel.shadowRoot.innerHTML,
    /button\.speedport_reboot_router/,
  );
  assert.match(fixture.panel.shadowRoot.innerHTML, /Cached laptop/);
  assert.doesNotMatch(
    fixture.panel.shadowRoot.innerHTML,
    /sensor\.speedport_system_cpu/,
  );
});

test("administrator payload validation keeps only fixed sections and fields", () => {
  const payload = adminPayload("entry-a", [
    {
      id: "clients",
      source: "protected_json",
      rows: [
        {
          connected: true,
          endpoint: "/data/private.json",
          name: "x".repeat(400),
          nested: { hidden: true },
        },
      ],
      truncated: false,
    },
  ]);

  const normalized = normalizeAdminReadPayload(payload, "entry-a");

  assert.equal(normalized.sections[0].rows[0].name.length, 256);
  assert.deepEqual(Object.keys(normalized.sections[0].rows[0]).sort(), [
    "connected",
    "name",
  ]);
  assert.equal(
    normalizeAdminReadPayload({ ...payload, schema_version: 2 }, "entry-a"),
    undefined,
  );
  assert.equal(normalizeAdminReadPayload(payload, "entry-b"), undefined);
  assert.equal(
    normalizeAdminReadPayload(
      adminPayload("entry-a", [
        {
          id: "unknown",
          rows: [],
          source: "protected_json",
          truncated: false,
        },
      ]),
      "entry-a",
    ),
    undefined,
  );
});

test("only Home Assistant administrators call the cached-read endpoint", async () => {
  const allowed = panelFixture({ admin: true });
  await allowed.panel._loadAdminRead("entry-a");

  assert.deepEqual(allowed.calls, [
    { entry_id: "entry-a", type: "speedport_smart/panel/admin_read" },
  ]);
  assert.equal(allowed.panel._adminReadEntry, "entry-a");
  assert.equal(allowed.panel._adminRead.sections[0].rows[0].name, "Laptop");

  const denied = panelFixture({ admin: false });
  await denied.panel._loadAdminRead("entry-a");
  assert.deepEqual(denied.calls, []);
  assert.equal(denied.panel._adminRead, undefined);
});

test("router change and disconnect clear private cached data", async () => {
  const fixture = panelFixture({ entries: ["entry-a", "entry-b"] });
  await fixture.panel._loadAdminRead("entry-a");
  assert.ok(fixture.panel._adminRead);

  fixture.panel._selectRouter("entry-b");
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);

  fixture.panel._adminRead = adminPayload("entry-b");
  fixture.panel._adminReadEntry = "entry-b";
  fixture.panel.disconnectedCallback();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("administrator demotion rerenders and clears private cached data", () => {
  const fixture = panelFixture({ admin: true });
  let scheduled = false;
  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._scheduleRender = () => {
    scheduled = true;
  };

  fixture.panel.hass = {
    ...fixture.panel._hass,
    user: { id: "limited-user", is_admin: false },
  };

  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
  assert.equal(scheduled, true);
});

test("entry unload and metadata failure clear private cached data", async () => {
  const fixture = panelFixture({ admin: true });
  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._hass.connection.sendMessagePromise = async () => ({
    routers: [{ ...router("entry-a"), entry_state: "not_loaded" }],
    schema_version: 8,
  });

  await fixture.panel._loadMetadata();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);

  fixture.panel._adminRead = adminPayload("entry-a");
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._hass.connection.sendMessagePromise = async () => {
    throw new Error("connection unavailable");
  };

  await fixture.panel._loadMetadata();
  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("stale administrator response cannot cross a router change", async () => {
  let resolveRequest;
  const fixture = panelFixture({ entries: ["entry-a", "entry-b"] });
  fixture.panel._hass.connection.sendMessagePromise = () =>
    new Promise((resolve) => {
      resolveRequest = resolve;
    });

  const pending = fixture.panel._loadAdminRead("entry-a");
  fixture.panel._selectRouter("entry-b");
  resolveRequest(adminPayload("entry-a"));
  await pending;

  assert.equal(fixture.panel._adminRead, undefined);
  assert.equal(fixture.panel._adminReadEntry, undefined);
});

test("administrator read failure is isolated from normal metadata", async () => {
  const fixture = panelFixture();
  const metadata = fixture.panel._metadata;
  fixture.panel._hass.connection.sendMessagePromise = async () => {
    throw new Error("backend unavailable");
  };

  await fixture.panel._loadAdminRead("entry-a");

  assert.equal(fixture.panel._metadata, metadata);
  assert.equal(fixture.panel._loadError, "");
  assert.equal(fixture.panel._adminReadError, "error.admin_read_unavailable");
});

test("administrator renderer exposes nine read-only expandable groups", () => {
  const fixture = panelFixture();
  fixture.panel._adminReadEntry = "entry-a";
  fixture.panel._adminRead = normalizeAdminReadPayload(
    adminPayload("entry-a", [
      {
        id: "clients",
        rows: [{ connected: true, name: "<script>unsafe</script>" }],
        source: "protected_json",
        truncated: true,
      },
    ]),
    "entry-a",
  );

  const html = fixture.panel._renderAdminRead(router("entry-a"));

  assert.equal((html.match(/class="admin-read-section /g) || []).length, 9);
  for (const title of [
    "Network devices",
    "Mesh nodes",
    "Port forwarding rules",
    "VPN peers",
    "Telephone lines",
    "DECT handsets",
    "IP phones",
    "USB devices",
    "Mobile receivers",
  ]) {
    assert.match(html, new RegExp(title));
  }
  assert.match(html, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>unsafe<\/script>/);
  assert.doesNotMatch(html, /data-control|callService|sendMessagePromise/);
  assert.match(html, /bounded display/);
  assert.match(html, /not present in the current cached snapshot/);
});

test("every administrator field has English and German labels", () => {
  assert.equal(ADMIN_READ_SECTION_ORDER.length, 9);
  for (const field of ADMIN_READ_FIELD_KEYS) {
    const key = `admin.field.${field}`;
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.de, key), key);
  }
});

test("frontend and backend administrator read contracts stay identical", () => {
  const modulePath = fileURLToPath(
    new URL(
      "../../custom_components/speedport_smart/panel_read.py",
      import.meta.url,
    ),
  );
  const localPython = fileURLToPath(
    new URL("../../.venv/bin/python", import.meta.url),
  );
  const python = existsSync(localPython) ? localPython : "python";
  const script = `
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("speedport_panel_read_contract", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps({
    "schema_version": module.ADMIN_READ_SCHEMA_VERSION,
    "sections": {item.section_id: list(item.fields) for item in module._COLLECTIONS},
}))
`;
  const result = spawnSync(python, ["-c", script, modulePath], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  const backend = JSON.parse(result.stdout);
  assert.equal(backend.schema_version, 1);
  assert.deepEqual(Object.keys(backend.sections), ADMIN_READ_SECTION_ORDER);
  assert.deepEqual(backend.sections, ADMIN_READ_SECTION_FIELDS);
});

test("administrator values use bounded native units", () => {
  assert.equal(formatAdminReadValue("connected", true, "en-US", "en"), "Yes");
  assert.equal(
    formatAdminReadValue("link_speed_bps", 1_000_000_000, "en-US", "en"),
    "1,000 Mbit/s",
  );
  assert.equal(
    formatAdminReadValue("total_bytes", 1_500_000_000, "en-US", "en"),
    "1.5 GB",
  );
  assert.equal(
    formatAdminReadValue("uptime_seconds", 3_661, "en-US", "en"),
    "1 h 1 min",
  );
});

test("Administration stays full-width, responsive, and theme-native", async () => {
  const source = await readFile(
    new URL(
      "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /\.administration-view\s*\{[^}]*width:\s*100%/s);
  assert.match(
    source,
    /\.admin-read-sections\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s,
  );
  assert.match(
    source,
    /@media \(max-width: 900px\)[\s\S]*?\.admin-read-sections\s*\{\s*grid-template-columns:\s*1fr;/,
  );
  assert.match(
    source,
    /\.admin-read-overview\s*\{[^}]*background:\s*var\(--sp-surface\)/s,
  );
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\./);
});
