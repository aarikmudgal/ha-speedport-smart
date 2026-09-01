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

test("retry-key collisions never prepare or execute a control", async () => {
  for (const [domain, state] of [
    ["switch", "on"],
    ["text", "client"],
    ["update", "on"],
  ]) {
    const meta = {
      ...RETRY_META,
      domain,
      entity_id: `${domain}.speedport_retry_protected_data`,
    };
    const fixture = panelFixture({ meta, pending: null, state });

    fixture.panel._prepareAction(meta.entity_id);
    await fixture.panel._runPendingAction();

    assert.equal(fixture.panel._pendingAction, null);
    assert.equal(fixture.calls.length, 0);
  }
});
