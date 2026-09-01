import assert from "node:assert/strict";
import test from "node:test";

class TestElement {
  attachShadow() {
    this.shadowRoot = {
      activeElement: undefined,
      addEventListener() {},
      querySelector() {
        return undefined;
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

const { SpeedportSmartPanel } = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js"
);

const WIFI_META = Object.freeze({
  confirmation: "typed",
  control: true,
  disruptive: true,
  domain: "switch",
  entity_id: "switch.speedport_wifi",
  risk: "lockout",
  translation_key: "wifi",
});

const RETRY_META = Object.freeze({
  confirmation: "confirm",
  control: true,
  disruptive: false,
  domain: "button",
  entity_id: "button.speedport_retry_protected_data",
  risk: "normal",
  translation_key: "retry_protected_data",
});

const CAPTURE_META = Object.freeze({
  confirmation: "confirm",
  control: true,
  disruptive: false,
  domain: "button",
  entity_id: "button.speedport_capture_read_only_inventory",
  risk: "normal",
  translation_key: "capture_read_only_inventory",
});

const RECONNECT_META = Object.freeze({
  confirmation: "confirm",
  control: true,
  disruptive: true,
  domain: "button",
  entity_id: "button.speedport_reconnect_internet",
  risk: "disruptive",
  translation_key: "reconnect_internet",
});

function pendingAction(overrides = {}) {
  return {
    actionLabel: "Turn off",
    confirmationDraft: "TURN OFF WI-FI",
    confirmationError: false,
    confirmationPhrase: "TURN OFF WI-FI",
    confirmationPolicy: "typed",
    entityId: WIFI_META.entity_id,
    kind: "action",
    observedState: "on",
    risk: "lockout",
    ...overrides,
  };
}

function panelFixture({ meta = WIFI_META, state = "on", pending = pendingAction() } = {}) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._selectedEntry = "entry";
  panel._metadata = {
    routers: [
      {
        entities: [meta],
        entry_id: "entry",
        management: { controls_available: true, state: "available" },
      },
    ],
  };
  panel._hass = {
    callService: async (...args) => calls.push(args),
    language: "en",
    states: {
      [meta.entity_id]: { attributes: {}, state },
    },
  };
  panel._pendingAction = pending;
  return { calls, panel };
}

test("panel confirmation rejects policy refresh and state races without service calls", async () => {
  for (const fixture of [
    panelFixture({ meta: { ...WIFI_META, risk: "destructive" } }),
    panelFixture({ state: "off" }),
  ]) {
    await fixture.panel._runPendingAction();
    assert.equal(fixture.calls.length, 0);
    assert.equal(fixture.panel._pendingAction, undefined);
  }
});

test("permission-denied semantic controls make zero service calls", async () => {
  const fixture = panelFixture({
    meta: { ...WIFI_META, control: false, control_supported: true },
  });

  await fixture.panel._runPendingAction();

  assert.equal(fixture.calls.length, 0);
  assert.equal(fixture.panel._pendingAction, undefined);
});

test("wrong typed phrase submitted with Enter makes zero service calls", async () => {
  const fixture = panelFixture({
    pending: pendingAction({ confirmationDraft: "turn off wi-fi" }),
  });
  let prevented = false;

  fixture.panel._handleKeyDown({
    key: "Enter",
    preventDefault() {
      prevented = true;
    },
    target: { dataset: { confirmDraft: "" } },
  });
  await Promise.resolve();

  assert.equal(prevented, true);
  assert.equal(fixture.calls.length, 0);
  assert.equal(fixture.panel._pendingAction.confirmationError, true);
});

test("one valid typed confirmation makes exactly one reviewed service call", async () => {
  const fixture = panelFixture();

  await fixture.panel._runPendingAction();

  assert.deepEqual(fixture.calls, [
    ["switch", "turn_off", { entity_id: WIFI_META.entity_id }],
  ]);
  assert.equal(fixture.panel._pendingAction, undefined);
});

test("protected-data retry remains callable during management backoff", async () => {
  const fixture = panelFixture({
    meta: RETRY_META,
    pending: null,
    state: "2026-09-01T12:00:00+00:00",
  });
  fixture.panel._metadata.routers[0].management = {
    controls_available: false,
    state: "blocked",
  };

  fixture.panel._prepareAction(RETRY_META.entity_id);
  assert.equal(fixture.panel._pendingAction?.entityId, RETRY_META.entity_id);
  await fixture.panel._runPendingAction();

  assert.deepEqual(fixture.calls, [
    ["button", "press", { entity_id: RETRY_META.entity_id }],
  ]);
});

test("read-only inventory remains callable during backoff with exact safe copy", async () => {
  for (const [language, fragments] of [
    [
      "en",
      [
        /Logout in every open Speedport web interface/,
        /every known safe candidate source once/,
        /Wi-Fi scans, update checks, and other action-like endpoints are excluded/,
        /only value-free response shapes/,
        /changes no router setting/,
      ],
    ],
    [
      "de",
      [
        /Abmelden in jeder geöffneten Speedport-Weboberfläche/,
        /jede bekannte sichere mögliche Quelle genau einmal/,
        /WLAN-Suchen, Update-Prüfungen und andere aktionsartige Endpunkte sind ausgeschlossen/,
        /nur wertfreie Antwortstrukturen/,
        /ändert keine Router-Einstellung/,
      ],
    ],
  ]) {
    const fixture = panelFixture({
      meta: CAPTURE_META,
      pending: null,
      state: "unknown",
    });
    fixture.panel._hass.language = language;
    fixture.panel._metadata.routers[0].management = {
      controls_available: false,
      state: "blocked",
    };

    fixture.panel._prepareAction(CAPTURE_META.entity_id);

    assert.equal(
      fixture.panel._pendingAction?.actionLabel,
      language === "de"
        ? "Schreibgeschützte Übersicht erfassen"
        : "Capture read-only inventory",
    );
    for (const fragment of fragments) {
      assert.match(fixture.panel._pendingAction?.message, fragment);
    }

    await fixture.panel._runPendingAction();
    assert.deepEqual(fixture.calls, [
      ["button", "press", { entity_id: CAPTURE_META.entity_id }],
    ]);
    assert.equal(
      fixture.panel._notice,
      language === "de"
        ? "Die schreibgeschützte Funktionsübersicht ist abgeschlossen. Status, Zähler und wertfreie Antwortstrukturen findest du jetzt in der Home-Assistant-Diagnose."
        : "Read-only inventory finished. Check Home Assistant diagnostics for its complete or partial status, counts, and value-free response shapes.",
    );
  }
});

test("reconnect confirmation warns that telephones and emergency calls are unavailable", () => {
  for (const [language, expected] of [
    ["en", [/all telephones connected to this router/, /emergency calls/]],
    ["de", [/alle an diesem Router angeschlossenen Telefone/, /Notrufe/]],
  ]) {
    const fixture = panelFixture({
      meta: RECONNECT_META,
      pending: null,
      state: "unknown",
    });
    fixture.panel._hass.language = language;

    fixture.panel._prepareAction(RECONNECT_META.entity_id);

    for (const fragment of expected) {
      assert.match(fixture.panel._pendingAction?.message, fragment);
    }
  }
});

test("read-only action key collisions never prepare or execute a control", async () => {
  for (const safeMeta of [RETRY_META, CAPTURE_META]) {
    for (const [domain, state] of [
      ["switch", "on"],
      ["text", "client"],
      ["update", "on"],
    ]) {
      const meta = {
        ...safeMeta,
        domain,
        entity_id: `${domain}.speedport_${safeMeta.translation_key}`,
      };
      const fixture = panelFixture({ meta, pending: null, state });

      fixture.panel._prepareAction(meta.entity_id);
      await fixture.panel._runPendingAction();

      assert.equal(fixture.panel._pendingAction, null);
      assert.equal(fixture.calls.length, 0);
    }
  }
});
