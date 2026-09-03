import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { PRIVATE_COMMAND_TYPES } from "../../custom_components/speedport_smart/frontend/private-api.js";

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
  ADMIN_ACTION_INFO,
  ADMIN_IA,
  SpeedportSmartPanel,
  adminActionRequest,
  normalizeAdminActionMetadata,
  normalizeAdminActionResult,
  normalizeDectHandsetTargets,
  normalizeDestructiveAdminActionTargets,
  normalizeVoipLineTargets,
} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=admin-actions"
);

const HANDSET_TOKEN = "a".repeat(32);
const LINE_TOKEN = "b".repeat(32);
const SECOND_TARGET_TOKEN = "c".repeat(32);
const DESTRUCTIVE_ACTION_IDS = Object.keys(ADMIN_ACTION_INFO).filter(
  (actionId) => ADMIN_ACTION_INFO[actionId].risk === "destructive",
);

function actionMetadata(id, overrides = {}) {
  const info = ADMIN_ACTION_INFO[id];
  const available = overrides.available ?? true;
  return {
    id,
    feature_id: info.featureId,
    supported: overrides.supported ?? true,
    available,
    unavailable_reason:
      overrides.unavailable_reason ?? (available ? null : "management_unavailable"),
    risk: info.risk,
    confirmation: info.confirmation,
    typed_confirmation: info.typedConfirmation,
    prerequisite: info.prerequisite,
    prerequisite_confirmation_required: info.prerequisite !== null,
    target_query: info.targetQuery,
    target_token_ttl_seconds: info.targetTokenTtlSeconds,
    ...overrides,
  };
}

function router(adminActions = []) {
  return {
    access_sources: [
      { id: "protected_json", available: true, supported: true },
    ],
    admin_actions: adminActions,
    capabilities: ["dect", "telephony"],
    capability_families: [],
    entities: [],
    entry_id: "entry-a",
    entry_state: "loaded",
    management: { controls_available: true, generation: 1, state: "available" },
    title: "Router",
  };
}

function fixture(adminActions = []) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._activeView = "administration";
  panel._metadata = { routers: [router(adminActions)] };
  panel._selectedEntry = "entry-a";
  panel._render = () => {};
  panel._loadAdminRead = async () => {};
  panel._hass = {
    connection: {
      async sendMessagePromise(message) {
        calls.push(message);
        throw new Error("No response configured");
      },
    },
    language: "en",
    locale: { language: "en-US" },
    states: {},
    user: { id: "admin", is_admin: true },
  };
  panel._requestPrivate = async (message) => {
    calls.push(message);
    throw new Error("No response configured");
  };
  return { calls, panel };
}

function featureById(id) {
  return ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.id === id);
}

function actionEnvelope(action, result) {
  return { schema_version: 1, action, result };
}

test("administrator action metadata is exact, closed, and tamper resistant", () => {
  const valid = actionMetadata("dect_repeater_enroll");
  const normalized = normalizeAdminActionMetadata([
    valid,
    actionMetadata("voip_line_set_active", {
      feature_id: "telephony_provider_delete",
    }),
    actionMetadata("dect_handset_enroll", {
      confirmation: "typed",
      typed_confirmation: "DELETE HANDSET",
    }),
    actionMetadata("dect_handset_set_paging", {
      risk: "normal",
    }),
  ]);

  assert.deepEqual([...normalized.keys()], ["dect_repeater_enroll"]);
  assert.deepEqual(normalized.get("dect_repeater_enroll"), valid);
  assert.equal(normalizeAdminActionMetadata([{ id: "__proto__" }]).size, 0);
  assert.equal(
    normalizeAdminActionMetadata([
      actionMetadata("dect_repeater_enroll", {
        prerequisite: null,
        prerequisite_confirmation_required: false,
      }),
    ]).size,
    0,
  );
  assert.equal(
    normalizeAdminActionMetadata([
      actionMetadata("voip_line_set_active", {
        target_query: "dect_handset_targets",
      }),
    ]).size,
    0,
  );
  assert.equal(
    normalizeAdminActionMetadata([
      actionMetadata("dect_handset_disconnect", {
        typed_confirmation: "DISCONNECT ANOTHER HANDSET",
      }),
    ]).size,
    0,
  );
});

test("frontend administrator action contracts stay identical to backend contracts", () => {
  const repository = fileURLToPath(new URL("../../", import.meta.url));
  const localPython = fileURLToPath(new URL("../../.venv/bin/python", import.meta.url));
  const python = existsSync(localPython) ? localPython : "python";
  const script = `
import json
from custom_components.speedport_smart import panel_queries
from custom_components.speedport_smart.admin_actions import ADMIN_ACTION_CONTRACTS
contracts = {
    action: contract for action, contract in ADMIN_ACTION_CONTRACTS.items()
    if contract.execution_policy != "maintenance"
}

types = {
    action: getattr(panel_queries, f"PANEL_{action.upper()}_WS_TYPE")
    for action in contracts
}
print(json.dumps({
    "actions": {
        action: {
            "apiType": types[action],
            "featureId": contract.feature_id,
            "confirmation": contract.confirmation.value,
            "typedConfirmation": contract.typed_confirmation,
            "prerequisite": contract.prerequisite,
            "targetQuery": contract.target_query,
            "targetTokenTtlSeconds": contract.target_token_ttl_seconds,
            "risk": contract.risk.value,
        }
        for action, contract in contracts.items()
    },
    "targetTypes": {
        action: getattr(
            panel_queries,
            f"PANEL_{contract.target_query.upper()}_WS_TYPE",
        )
        for action, contract in contracts.items()
        if contract.target_query is not None
    },
    "privateTypes": sorted([
        *panel_queries.private_panel_command_handlers(),
        "speedport_smart/panel/admin_read",
    ]),
}))
`;
  const result = spawnSync(python, ["-c", script], {
    cwd: repository,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  const backend = JSON.parse(result.stdout);
  assert.deepEqual([...PRIVATE_COMMAND_TYPES].sort(), backend.privateTypes);
  assert.deepEqual(
    backend.actions,
    Object.fromEntries(
      Object.entries(ADMIN_ACTION_INFO).map(([id, info]) => [
        id,
        {
          apiType: info.apiType,
          featureId: info.featureId,
          confirmation: info.confirmation,
          typedConfirmation: info.typedConfirmation,
          prerequisite: info.prerequisite,
          targetQuery: info.targetQuery,
          targetTokenTtlSeconds: info.targetTokenTtlSeconds,
          risk: info.risk,
        },
      ]),
    ),
  );
  assert.deepEqual(
    backend.targetTypes,
    Object.fromEntries(
      Object.entries(ADMIN_ACTION_INFO)
        .filter(([, info]) => info.targetQuery)
        .map(([id, info]) => [
          id,
          `speedport_smart/panel/action/${info.targetQuery}`,
        ]),
    ),
  );
});

test("fixed requests and acknowledgements match the backend action schemas", () => {
  assert.deepEqual(adminActionRequest("dect_handset_enroll", "entry-a"), {
    type: "speedport_smart/panel/action/dect_handset_enroll",
    entry_id: "entry-a",
    confirmed: true,
  });
  assert.deepEqual(
    adminActionRequest("dect_repeater_enroll", "entry-a", {
      pin_is_default: true,
      full_power_enabled: true,
      full_eco_disabled: true,
    }),
    {
      type: "speedport_smart/panel/action/dect_repeater_enroll",
      entry_id: "entry-a",
      confirmed: true,
      pin_is_default: true,
      full_power_enabled: true,
      full_eco_disabled: true,
    },
  );
  assert.deepEqual(
    adminActionRequest("dect_handset_set_paging", "entry-a", {
      target_token: HANDSET_TOKEN,
      enabled: false,
    }),
    {
      type: "speedport_smart/panel/action/dect_handset_set_paging",
      entry_id: "entry-a",
      confirmed: true,
      target_token: HANDSET_TOKEN,
      enabled: false,
    },
  );
  assert.deepEqual(
    adminActionRequest("voip_line_set_active", "entry-a", {
      target_token: LINE_TOKEN,
      active: true,
    }),
    {
      type: "speedport_smart/panel/action/voip_line_set_active",
      entry_id: "entry-a",
      confirmed: true,
      target_token: LINE_TOKEN,
      active: true,
    },
  );
  assert.equal(
    adminActionRequest("dect_repeater_enroll", "entry-a", {
      pin_is_default: false,
      full_power_enabled: true,
      full_eco_disabled: true,
    }),
    undefined,
  );
  assert.equal(
    adminActionRequest("voip_line_set_active", "entry-a", {
      target_token: "../line",
      active: true,
    }),
    undefined,
  );
  assert.equal(
    adminActionRequest("dect_handset_enroll", "entry-a", {
      hidden: true,
    }),
    undefined,
  );
  assert.equal(
    adminActionRequest(
      "dect_handset_enroll",
      "entry-a",
      {},
      "TAMPERED PHRASE",
    ),
    undefined,
  );

  for (const [actionId, info] of Object.entries(ADMIN_ACTION_INFO).filter(
    ([, candidate]) => candidate.risk === "destructive",
  )) {
    assert.deepEqual(
      adminActionRequest(
        actionId,
        "entry-a",
        { target_token: HANDSET_TOKEN },
        info.typedConfirmation,
      ),
      {
        type: `speedport_smart/panel/action/${actionId}`,
        entry_id: "entry-a",
        confirmed: true,
        confirmation_text: info.typedConfirmation,
        target_token: HANDSET_TOKEN,
      },
    );
    assert.equal(
      adminActionRequest(
        actionId,
        "entry-a",
        { target_token: HANDSET_TOKEN },
        `${info.typedConfirmation} TAMPERED`,
      ),
      undefined,
    );
    for (const status of ["verified", "unchanged"]) {
      assert.equal(
        normalizeAdminActionResult(
          actionEnvelope(actionId, { status, deleted: true }),
          actionId,
        ),
        true,
      );
    }
    assert.equal(
      normalizeAdminActionResult(
        actionEnvelope(actionId, { status: "verified", deleted: false }),
        actionId,
      ),
      false,
    );
  }

  assert.equal(
    normalizeAdminActionResult(
      actionEnvelope("dect_handset_enroll", {
        status: "verified",
        lifecycle: "scan_active",
      }),
      "dect_handset_enroll",
    ),
    true,
  );
  for (const status of ["verified", "unchanged"]) {
    assert.equal(
      normalizeAdminActionResult(
        actionEnvelope("voip_line_set_active", { status, active: true }),
        "voip_line_set_active",
        true,
      ),
      true,
    );
  }
  assert.equal(
    normalizeAdminActionResult(
      actionEnvelope("dect_handset_enroll", {
        status: "unchanged",
        lifecycle: "scan_active",
      }),
      "dect_handset_enroll",
    ),
    false,
  );
  assert.equal(
    normalizeAdminActionResult(
      actionEnvelope("voip_line_set_active", {
        status: "unchanged",
        active: false,
      }),
      "voip_line_set_active",
      true,
    ),
    false,
  );
});

test("ephemeral target handshakes retain only bounded action-safe tokens", () => {
  const handsets = normalizeDectHandsetTargets({
    schema_version: 1,
    query: "dect_handset_targets",
    result: {
      targets: [
        {
          target_token: HANDSET_TOKEN,
          reference: "2",
          name: "<script>Kitchen</script>",
          paging: false,
          secret: "MUST-NOT-SURVIVE",
        },
        { target_token: "../invalid", name: "Bad", paging: true },
        { target_token: HANDSET_TOKEN, name: "Duplicate", paging: true },
      ],
      truncated: false,
    },
  });
  assert.deepEqual(handsets, {
    targets: [
      {
        target_token: HANDSET_TOKEN,
        reference: "2",
        name: "<script>Kitchen</script>",
        paging: false,
      },
    ],
    truncated: false,
  });
  assert.doesNotMatch(JSON.stringify(handsets), /MUST-NOT-SURVIVE/);

  assert.deepEqual(
    normalizeVoipLineTargets({
      schema_version: 1,
      query: "voip_line_targets",
      result: {
        targets: [
          {
            target_token: LINE_TOKEN,
            reference: "line-1",
            active: true,
            number_suffix: "1234",
            label: "MUST-NOT-BE-TRUSTED",
            number: "+491234",
          },
          { target_token: "line 2", active: false },
        ],
        truncated: true,
      },
    }),
    {
      targets: [
        {
          target_token: LINE_TOKEN,
          reference: "line-1",
          active: true,
          number_suffix: "1234",
        },
      ],
      truncated: true,
    },
  );
  assert.doesNotMatch(
    JSON.stringify(
      normalizeVoipLineTargets({
        schema_version: 1,
        query: "voip_line_targets",
        result: {
          targets: [
            {
              target_token: LINE_TOKEN,
              reference: "line-1",
              active: true,
              number_suffix: "12A4",
              label: "Number ending in 9999",
            },
          ],
          truncated: false,
        },
      }),
    ),
    /9999|12A4|label/,
  );
});

test("target references keep identical human labels unambiguous", () => {
  const handsets = normalizeDectHandsetTargets({
    schema_version: 1,
    query: "dect_handset_targets",
    result: {
      targets: [
        {
          target_token: HANDSET_TOKEN,
          reference: "1",
          name: "Handset",
          paging: false,
        },
        {
          target_token: SECOND_TARGET_TOKEN,
          reference: "2",
          name: "Handset",
          paging: false,
        },
      ],
      truncated: false,
    },
  });
  assert.deepEqual(
    handsets?.targets.map((target) => target.reference),
    ["1", "2"],
  );

  const { panel } = fixture([actionMetadata("dect_handset_set_paging")]);
  panel._adminActionState.handsetTargets.loaded = true;
  panel._adminActionState.handsetTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.handsetTargets.generation = 1;
  panel._adminActionState.handsetTargets.result = handsets;
  const markup = panel._renderDectPagingTargets();
  assert.match(markup, /Handset · reference 1/);
  assert.match(markup, /Handset · reference 2/);
  assert.match(markup, /aria-label="Start paging: Handset · reference 1"/);
  assert.match(markup, /aria-label="Start paging: Handset · reference 2"/);
});

test("destructive target handshakes retain only safe labels and one-use tokens", () => {
  const cases = {
    dect_handset_disconnect: [
      { reference: "hs1", name: "Kitchen handset" },
      { reference: "hs1", name: "Kitchen handset" },
    ],
    dect_repeater_disconnect: [
      { reference: "rp1", name: "MUST-NOT-SURVIVE" },
      { reference: "rp1" },
    ],
    voip_provider_delete: [
      { reference: "vp1", provider_code: 17 },
      { reference: "vp1", provider_code: 17 },
    ],
    voip_line_delete: [
      { reference: "vl1", active: true, number_suffix: "1234" },
      { reference: "vl1", active: true, number_suffix: "1234" },
    ],
    ip_pbx_client_delete: [
      { reference: "pbx1", name: "Desk phone", status: "registered" },
      { reference: "pbx1", name: "Desk phone", status: "registered" },
    ],
    phonebook_entry_delete: [
      { reference: "contact1", display_name: "Alice Example" },
      { reference: "contact1", display_name: "Alice Example" },
    ],
    nas_share_delete: [
      { reference: "share1", name: "Photos" },
      { reference: "share1", name: "Photos" },
    ],
  };
  for (const [actionId, [safeFields, expectedFields]] of Object.entries(cases)) {
    const info = ADMIN_ACTION_INFO[actionId];
    const normalized = normalizeDestructiveAdminActionTargets(
      {
        schema_version: 1,
        query: info.targetQuery,
        result: {
          targets: [
            {
              target_token: HANDSET_TOKEN,
              ...safeFields,
              target_id: "FIRMWARE-ID-MUST-NOT-SURVIVE",
              private_value: "PRIVATE-MUST-NOT-SURVIVE",
            },
          ],
          truncated: false,
        },
      },
      actionId,
    );
    assert.deepEqual(normalized, {
      targets: [{ target_token: HANDSET_TOKEN, ...expectedFields }],
      truncated: false,
    });
    assert.doesNotMatch(
      JSON.stringify(normalized),
      /FIRMWARE-ID|PRIVATE|target_id|private_value/,
    );
  }

  assert.equal(
    normalizeDestructiveAdminActionTargets(
      {
        schema_version: 1,
        query: "voip_line_delete_targets",
        result: { targets: [], truncated: false },
      },
      "dect_handset_disconnect",
    ),
    undefined,
  );
});

test("actions render only for exact advertisements, including disabled descriptors", () => {
  const paging = featureById("telephony_dect_handset_paging");
  const absent = fixture();
  assert.equal(absent.panel._renderAdminActions(paging), "");
  assert.notEqual(
    absent.panel._adminFeaturePresentation(
      paging,
      [],
      new Map(),
      new Set(["dect"]),
      true,
    ).key,
    "control_available",
  );

  const unsupported = fixture([
    actionMetadata("dect_handset_set_paging", {
      supported: false,
      available: false,
      unavailable_reason: "unsupported_firmware",
    }),
  ]);
  const disabledMarkup = unsupported.panel._renderAdminActions(paging);
  assert.match(disabledMarkup, /data-admin-action-card="dect_handset_set_paging"/);
  assert.match(disabledMarkup, /has not been reviewed for the current router firmware/);
  assert.match(disabledMarkup, /<button class="primary" disabled>/);
  assert.doesNotMatch(disabledMarkup, /data-admin-action="/);

  const available = fixture([actionMetadata("dect_handset_enroll")]);
  const enrollMarkup = available.panel._renderAdminActions(
    featureById("telephony_dect_handset_enrollment"),
  );
  assert.match(enrollMarkup, /data-admin-action="dect_handset_enroll"/);
  assert.match(enrollMarkup, /Confirmation required/);
});

test("destructive actions replace blocked cards only after exact backend support", () => {
  const feature = featureById("telephony_dect_handset_disconnect");
  const unsupported = fixture([
    actionMetadata("dect_handset_disconnect", {
      supported: false,
      available: false,
      unavailable_reason: "unsupported_firmware",
    }),
  ]);
  const blockedMarkup = unsupported.panel._renderAdminFeatureCatalog(
    [feature],
    [],
    new Map(),
    new Set(["dect"]),
    true,
    {},
    { canReadAdmin: true },
  );
  assert.match(blockedMarkup, /contract-blocked/);
  assert.match(blockedMarkup, /positive command acknowledgement/);
  assert.doesNotMatch(blockedMarkup, /data-admin-action-card/);
  assert.deepEqual(unsupported.calls, []);

  const supported = fixture([
    actionMetadata("dect_handset_disconnect", {
      available: false,
      unavailable_reason: "management_unavailable",
    }),
  ]);
  const reviewedMarkup = supported.panel._renderAdminFeatureCatalog(
    [feature],
    [],
    new Map(),
    new Set(["dect"]),
    false,
    {},
    { canReadAdmin: true },
  );
  assert.match(reviewedMarkup, /contract-reviewed/);
  assert.match(
    reviewedMarkup,
    /data-admin-action-card="dect_handset_disconnect"/,
  );
  assert.doesNotMatch(reviewedMarkup, /positive command acknowledgement/);
  assert.deepEqual(supported.calls, []);
});

test("destructive action cards stay in their fixed Administration hierarchy", () => {
  const expected = {
    dect_handset_disconnect: ["telephony", "telephony_dect"],
    dect_repeater_disconnect: ["telephony", "telephony_dect"],
    voip_provider_delete: ["telephony", "telephony_numbers"],
    voip_line_delete: ["telephony", "telephony_numbers"],
    ip_pbx_client_delete: ["telephony", "telephony_pbx"],
    phonebook_entry_delete: ["telephony", "telephony_phonebooks"],
    nas_share_delete: ["network", "network_storage"],
  };
  for (const [actionId, [areaId, subsectionId]] of Object.entries(expected)) {
    const area = ADMIN_IA.find((candidate) => candidate.id === areaId);
    const subsection = area.subsections.find(
      (candidate) => candidate.id === subsectionId,
    );
    const feature = subsection.features.find(
      (candidate) => candidate.id === ADMIN_ACTION_INFO[actionId].featureId,
    );
    assert.deepEqual(feature.adminActions, [actionId]);
    assert.equal(feature.adminActionReplacesBlocked, true);
    assert.equal(feature.risk, "destructive");
  }
});

test("all destructive actions lazily query and dispatch exact typed token requests", async () => {
  const { calls, panel } = fixture(
    DESTRUCTIVE_ACTION_IDS.map((actionId) => actionMetadata(actionId)),
  );
  const tokens = Object.fromEntries(
    DESTRUCTIVE_ACTION_IDS.map((actionId, index) => [
      actionId,
      (index + 1).toString(16).repeat(32),
    ]),
  );
  const projections = {
    dect_handset_disconnect: { reference: "hs1", name: "Kitchen handset" },
    dect_repeater_disconnect: { reference: "rp1" },
    voip_provider_delete: { reference: "vp1", provider_code: 17 },
    voip_line_delete: { reference: "vl1", active: true, number_suffix: "1234" },
    ip_pbx_client_delete: {
      reference: "pbx1",
      name: "Desk phone",
      status: "registered",
    },
    phonebook_entry_delete: {
      reference: "contact1",
      display_name: "Alice Example",
    },
    nas_share_delete: { reference: "share1", name: "Photos" },
  };
  panel._requestPrivate = async (message) => {
    calls.push(message);
    const operation = message.type.split("/").at(-1);
    if (operation.endsWith("_targets")) {
      const actionId = operation.slice(0, -"_targets".length);
      return {
        schema_version: 1,
        query: operation,
        result: {
          targets: [
            { target_token: tokens[actionId], ...projections[actionId] },
          ],
          truncated: false,
        },
      };
    }
    return actionEnvelope(operation, { status: "verified", deleted: true });
  };

  for (const actionId of DESTRUCTIVE_ACTION_IDS) {
    panel._renderAdminActions(featureById(ADMIN_ACTION_INFO[actionId].featureId));
  }
  assert.deepEqual(calls, []);

  for (const actionId of DESTRUCTIVE_ACTION_IDS) {
    panel._handleToggle({
      target: {
        open: true,
        dataset: { adminFeature: ADMIN_ACTION_INFO[actionId].featureId },
      },
    });
  }
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(
    calls,
    DESTRUCTIVE_ACTION_IDS.map((actionId) => ({
      type: `speedport_smart/panel/action/${actionId}_targets`,
      entry_id: "entry-a",
      ...(actionId === "phonebook_entry_delete" ? { phonebook_id: 0 } : {}),
    })),
  );

  for (const actionId of DESTRUCTIVE_ACTION_IDS) {
    const queryCount = calls.length;
    panel._prepareAdminAction(actionId, tokens[actionId]);
    const confirmation = panel._renderConfirmation();
    assert.match(confirmation, /confirm-dialog danger/);
    assert.match(confirmation, new RegExp(ADMIN_ACTION_INFO[actionId].typedConfirmation));
    assert.match(confirmation, /backup-restore/);
    await panel._runPendingAction();
    assert.equal(calls.length, queryCount);
    panel._pendingAction.confirmationDraft =
      ADMIN_ACTION_INFO[actionId].typedConfirmation;
    await panel._runPendingAction();
    assert.deepEqual(calls.at(-1), {
      type: `speedport_smart/panel/action/${actionId}`,
      entry_id: "entry-a",
      confirmed: true,
      confirmation_text: ADMIN_ACTION_INFO[actionId].typedConfirmation,
      target_token: tokens[actionId],
    });
    assert.equal(
      panel._adminActionState.destructiveTargets[actionId].result,
      undefined,
    );
  }
});

test("phonebook deletion selector reloads targets without an open dialog", () => {
  const { panel } = fixture([actionMetadata("phonebook_entry_delete")]);
  const requested = [];
  panel._loadDestructiveAdminActionTargets = (actionId) => requested.push(actionId);

  panel._handleInput({
    target: {
      value: "3",
      dataset: { adminActionPhonebookId: "" },
    },
  });

  assert.equal(panel._pendingAction, undefined);
  assert.equal(panel._adminActionState.phonebookId, 3);
  assert.deepEqual(requested, ["phonebook_entry_delete"]);
});

test("truncated destructive lists render their action-specific bound", () => {
  const { panel } = fixture([
    actionMetadata("dect_handset_disconnect"),
    actionMetadata("voip_provider_delete"),
  ]);
  for (const [actionId, count] of [
    ["dect_handset_disconnect", 16],
    ["voip_provider_delete", 32],
  ]) {
    const state = panel._adminActionState.destructiveTargets[actionId];
    state.loaded = true;
    state.expiresAt = Date.now() + 60_000;
    state.generation = 1;
    state.result = { targets: [], truncated: true };
    assert.match(
      panel._renderDestructiveActionTargets(actionId),
      new RegExp(`first ${count} action-safe targets`),
    );
  }
});

test("unproven DDNS deletion stays blocked and cannot create WebSocket messages", async () => {
  const actionId = "ddns_configuration_delete";
  const advertised = {
    id: actionId,
    feature_id: "internet_ddns_configuration_delete",
    supported: true,
    available: true,
    unavailable_reason: null,
    risk: "destructive",
    confirmation: "typed",
    typed_confirmation: "DELETE DDNS CONFIGURATION",
    prerequisite: null,
    prerequisite_confirmation_required: false,
    target_query: "ddns_configuration_delete_targets",
    target_token_ttl_seconds: 60,
  };
  const { calls, panel } = fixture([advertised]);
  const feature = featureById("internet_ddns_configuration_delete");

  assert.equal(Object.hasOwn(ADMIN_ACTION_INFO, actionId), false);
  assert.equal(normalizeAdminActionMetadata([advertised]).size, 0);
  assert.equal(
    adminActionRequest(
      actionId,
      "entry-a",
      { target_token: HANDSET_TOKEN },
      advertised.typed_confirmation,
    ),
    undefined,
  );
  assert.equal(
    normalizeDestructiveAdminActionTargets(
      {
        schema_version: 1,
        query: advertised.target_query,
        result: {
          targets: [{ target_token: HANDSET_TOKEN }],
          truncated: false,
        },
      },
      actionId,
    ),
    undefined,
  );
  assert.equal(feature.contract, "blocked");
  assert.deepEqual(feature.adminActions, []);
  assert.equal(feature.adminActionReplacesBlocked, false);
  const markup = panel._renderAdminFeatureCatalog(
    [feature],
    [],
    new Map(),
    new Set(["ddns"]),
    true,
    {},
    { canReadAdmin: true },
  );
  assert.match(markup, /contract-blocked/);
  assert.match(markup, /safe local write and readback flow has not yet been verified/);
  assert.doesNotMatch(markup, /data-admin-action/);

  panel._handleToggle({
    target: { open: true, dataset: { adminFeature: feature.id } },
  });
  panel._prepareAdminAction(actionId, HANDSET_TOKEN);
  await panel._runPendingAction();
  assert.deepEqual(calls, []);
});

test("confirmation metadata tampering after review fails closed before dispatch", async () => {
  const metadata = actionMetadata("dect_handset_enroll");
  const { calls, panel } = fixture([metadata]);
  panel._prepareAdminAction("dect_handset_enroll");
  metadata.typed_confirmation = "TAMPERED PHRASE";

  await panel._runPendingAction();

  assert.deepEqual(calls, []);
  assert.equal(panel._pendingAction, undefined);
  assert.equal(
    panel._notice,
    "This administrator action is no longer available. Refresh and try again.",
  );
});

test("target queries run lazily and never join broad cached line IDs", async () => {
  const { calls, panel } = fixture([
    actionMetadata("dect_handset_set_paging"),
    actionMetadata("voip_line_set_active"),
  ]);
  panel._adminRead = {
    entry_id: "entry-a",
    sections: [
      {
        id: "telephone_lines",
        rows: [{ id: "broad-cache-id", name: "Private line", status: "ok" }],
      },
    ],
  };
  panel._requestPrivate = async (message) => {
    calls.push(message);
    if (message.type.endsWith("/dect_handset_targets")) {
      return {
        schema_version: 1,
        query: "dect_handset_targets",
        result: {
          targets: [
            {
              target_token: HANDSET_TOKEN,
              reference: "2",
              name: "Kitchen",
              paging: false,
            },
          ],
          truncated: false,
        },
      };
    }
    return {
      schema_version: 1,
      query: "voip_line_targets",
      result: {
        targets: [
          {
            target_token: LINE_TOKEN,
            reference: "line-1",
            number_suffix: "1234",
            active: true,
          },
        ],
        truncated: false,
      },
    };
  };

  panel._handleToggle({
    target: {
      open: false,
      dataset: { adminFeature: "telephony_dect_handset_paging" },
    },
  });
  assert.deepEqual(calls, []);
  panel._handleToggle({
    target: {
      open: true,
      dataset: { adminFeature: "telephony_dect_handset_paging" },
    },
  });
  panel._handleToggle({
    target: {
      open: true,
      dataset: { adminFeature: "telephony_number_activation" },
    },
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(calls, [
    {
      type: "speedport_smart/panel/action/dect_handset_targets",
      entry_id: "entry-a",
    },
    {
      type: "speedport_smart/panel/action/voip_line_targets",
      entry_id: "entry-a",
    },
  ]);
  const lineMarkup = panel._renderAdminActions(
    featureById("telephony_number_activation"),
  );
  assert.match(lineMarkup, new RegExp(`data-admin-target-token="${LINE_TOKEN}"`));
  assert.match(lineMarkup, /Number ending in 1234/);
  assert.doesNotMatch(lineMarkup, /broad-cache-id|Private line/);
});

test("expired target tokens disappear before they can prepare an action", () => {
  const { panel } = fixture([actionMetadata("dect_handset_set_paging")]);
  panel._adminActionNow = () => 1_000;
  panel._adminActionState.handsetTargets.loaded = true;
  panel._adminActionState.handsetTargets.expiresAt = 999;
  panel._adminActionState.handsetTargets.generation = 1;
  panel._adminActionState.handsetTargets.result = {
    targets: [
      {
        target_token: HANDSET_TOKEN,
        reference: "2",
        name: "Kitchen",
        paging: false,
      },
    ],
    truncated: false,
  };

  panel._prepareAdminAction("dect_handset_set_paging", HANDSET_TOKEN);

  assert.equal(panel._pendingAction, undefined);
  assert.equal(panel._adminActionState.handsetTargets.result, undefined);
});

test("all four actions require confirmation and dispatch exact token-only messages", async () => {
  const actionIds = [
    "dect_handset_enroll",
    "dect_repeater_enroll",
    "dect_handset_set_paging",
    "voip_line_set_active",
  ];
  const { calls, panel } = fixture(actionIds.map((id) => actionMetadata(id)));
  panel._requestPrivate = async (message) => {
    calls.push(message);
    if (Object.hasOwn(message, "target_token")) {
      assert.equal(panel._adminActionState.handsetTargets.result, undefined);
      assert.equal(panel._adminActionState.voipLineTargets.result, undefined);
    }
    const action = message.type.split("/").at(-1);
    if (action.endsWith("enroll")) {
      return actionEnvelope(action, {
        status: "verified",
        lifecycle: "scan_active",
        private_id: "MUST-NOT-SURVIVE",
      });
    }
    return actionEnvelope(action, {
      status: "verified",
      active: message.enabled ?? message.active,
      private_id: "MUST-NOT-SURVIVE",
    });
  };

  panel._prepareAdminAction("dect_handset_enroll");
  assert.deepEqual(calls, []);
  await panel._runPendingAction();

  panel._prepareAdminAction("dect_repeater_enroll");
  await panel._runPendingAction();
  assert.equal(calls.length, 1);
  assert.match(panel._renderConfirmation(), /current DECT base PIN is 0000/);
  assert.match(panel._renderConfirmation(), /data-confirm-action disabled/);
  for (const prerequisite of [
    "pinIsDefault",
    "fullPowerEnabled",
    "fullEcoDisabled",
  ]) {
    panel._handleInput({
      target: {
        checked: true,
        dataset: { repeaterPrerequisite: prerequisite },
      },
    });
  }
  await panel._runPendingAction();

  panel._adminActionState.handsetTargets.loaded = true;
  panel._adminActionState.handsetTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.handsetTargets.generation = 1;
  panel._adminActionState.handsetTargets.result = {
    targets: [{ target_token: HANDSET_TOKEN, name: "Kitchen", paging: false }],
    truncated: false,
  };
  panel._prepareAdminAction("dect_handset_set_paging", HANDSET_TOKEN);
  await panel._runPendingAction();

  panel._adminActionState.voipLineTargets.loaded = true;
  panel._adminActionState.voipLineTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.voipLineTargets.generation = 1;
  panel._adminActionState.voipLineTargets.result = {
    targets: [{ target_token: LINE_TOKEN, active: true }],
    truncated: false,
  };
  panel._prepareAdminAction("voip_line_set_active", LINE_TOKEN);
  assert.match(panel._renderConfirmation(), /confirm-dialog danger/);
  await panel._runPendingAction();

  assert.deepEqual(calls, [
    {
      type: "speedport_smart/panel/action/dect_handset_enroll",
      entry_id: "entry-a",
      confirmed: true,
    },
    {
      type: "speedport_smart/panel/action/dect_repeater_enroll",
      entry_id: "entry-a",
      confirmed: true,
      pin_is_default: true,
      full_power_enabled: true,
      full_eco_disabled: true,
    },
    {
      type: "speedport_smart/panel/action/dect_handset_set_paging",
      entry_id: "entry-a",
      confirmed: true,
      target_token: HANDSET_TOKEN,
      enabled: true,
    },
    {
      type: "speedport_smart/panel/action/voip_line_set_active",
      entry_id: "entry-a",
      confirmed: true,
      target_token: LINE_TOKEN,
      active: false,
    },
  ]);
  assert.doesNotMatch(JSON.stringify(panel._adminActionState), /MUST-NOT-SURVIVE/);
  assert.equal(panel._pendingAction, undefined);
});

test("fixed action errors and context changes expose no server detail", async () => {
  const { calls, panel } = fixture([actionMetadata("dect_handset_enroll")]);
  assert.equal(
    panel._adminActionErrorKey({ code: "action_busy" }),
    "admin.action.error.action_busy",
  );
  panel._requestPrivate = async (message) => {
    calls.push(message);
    const error = new Error("PRIVATE ROUTER DETAIL");
    error.code = "action_outcome_unknown";
    throw error;
  };
  panel._prepareAdminAction("dect_handset_enroll");
  await panel._runPendingAction();
  assert.equal(
    panel._notice,
    "The router response was inconclusive. Check the current router state before trying again.",
  );
  assert.doesNotMatch(panel._notice, /PRIVATE ROUTER DETAIL/);

  let resolveAction;
  panel._requestPrivate = (message) => {
    calls.push(message);
    return new Promise((resolve) => {
      resolveAction = resolve;
    });
  };
  panel._metadata.routers.push({ ...router(), entry_id: "entry-b" });
  panel._prepareAdminAction("dect_handset_enroll");
  const pending = panel._runPendingAction();
  panel._selectRouter("entry-b");
  assert.equal(panel._selectedEntry, "entry-a");
  assert.equal(panel._actionBusy, true);
  resolveAction(
    actionEnvelope("dect_handset_enroll", {
      status: "verified",
      lifecycle: "scan_active",
    }),
  );
  await pending;
  panel._loadAdminRead = async () => {};
  panel._selectRouter("entry-b");
  assert.equal(panel._selectedEntry, "entry-b");
  assert.equal(panel._pendingAction, undefined);
  assert.equal(panel._actionBusy, false);
  assert.equal(panel._notice, "");
  assert.equal(panel._adminActionState.handsetTargets.result, undefined);
});

test("action dispatch invalidates private caches even when outcome is unknown", async () => {
  const { panel } = fixture([actionMetadata("dect_handset_enroll")]);
  panel._adminRead = { schema_version: 2, entry_id: "entry-a", sections: [] };
  panel._adminReadEntry = "entry-a";
  panel._adminPrivateQueries.pbx.result = { client_id: "PRIVATE" };
  const refreshes = [];
  panel._loadAdminRead = async (entryId, options) => {
    refreshes.push([entryId, options]);
  };
  panel._requestPrivate = async () => {
    const error = new Error("PRIVATE ROUTER DETAIL");
    error.code = "action_outcome_unknown";
    throw error;
  };

  panel._prepareAdminAction("dect_handset_enroll");
  await panel._runPendingAction();

  assert.equal(panel._adminRead, undefined);
  assert.equal(panel._adminReadEntry, undefined);
  assert.equal(panel._adminPrivateQueries.pbx.result, undefined);
  assert.deepEqual(refreshes, [["entry-a", { force: true }]]);
  assert.doesNotMatch(JSON.stringify(panel._adminPrivateQueries), /PRIVATE/);
});

test("management availability and generation changes invalidate target tokens", async () => {
  const { panel } = fixture([actionMetadata("voip_line_set_active")]);
  panel._platformIcons = {};
  panel._componentIcons = {};
  panel._adminActionState.voipLineTargets.loaded = true;
  panel._adminActionState.voipLineTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.voipLineTargets.generation = 1;
  panel._adminActionState.voipLineTargets.result = {
    targets: [{ target_token: LINE_TOKEN, active: true }],
    truncated: false,
  };
  panel._hass.connection.sendMessagePromise = async () => ({
    schema_version: 24,
    routers: [
      {
        ...router([actionMetadata("voip_line_set_active")]),
        management: {
          controls_available: true,
          generation: 2,
          state: "available",
        },
      },
    ],
  });

  await panel._loadMetadata();

  assert.equal(panel._adminActionState.voipLineTargets.result, undefined);
  assert.equal(panel._adminActionGeneration(), 2);

  panel._adminActionState.voipLineTargets.result = {
    targets: [{ target_token: LINE_TOKEN, active: true }],
    truncated: false,
  };
  panel._adminActionState.voipLineTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.voipLineTargets.generation = 2;
  panel._hass.connection.sendMessagePromise = async () => ({
    schema_version: 24,
    routers: [
      {
        ...router([
          actionMetadata("voip_line_set_active", {
            available: false,
            unavailable_reason: "controls_disabled",
          }),
        ]),
        management: {
          controls_available: false,
          generation: 2,
          state: "available",
        },
      },
    ],
  });

  await panel._loadMetadata();

  assert.equal(panel._adminActionState.voipLineTargets.result, undefined);
  panel._prepareAdminAction("voip_line_set_active", LINE_TOKEN);
  assert.equal(panel._pendingAction, undefined);
});

test("leaving Administration and disconnecting clear transient action data", () => {
  const { panel } = fixture([actionMetadata("dect_handset_set_paging")]);
  panel._adminActionState.handsetTargets.result = {
    targets: [{ target_token: HANDSET_TOKEN, name: "Kitchen", paging: false }],
    truncated: false,
  };
  panel._adminActionState.handsetTargets.expiresAt = Date.now() + 60_000;
  panel._adminActionState.handsetTargets.generation = 1;
  panel._prepareAdminAction("dect_handset_set_paging", HANDSET_TOKEN);
  panel._selectView("dashboard");
  assert.equal(panel._pendingAction, undefined);
  assert.equal(panel._adminActionState.handsetTargets.result, undefined);

  panel._activeView = "administration";
  panel._metadata.routers[0].entities = [
    {
      entity_id: "sensor.management_access",
      translation_key: "management_access",
    },
  ];
  panel._hass.states = {
    "sensor.management_access": { state: "available", attributes: {} },
  };
  panel._adminActionState.handsetTargets.result = {
    targets: [{ target_token: HANDSET_TOKEN, paging: false }],
    truncated: false,
  };
  panel._scheduleRender = () => {};
  panel._adminActionState.destructiveTargets.nas_share_delete.result = {
    targets: [{ target_token: LINE_TOKEN, reference: "share1", name: "Photos" }],
    truncated: false,
  };
  panel._adminActionState.destructiveTargets.nas_share_delete.expiresAt =
    Date.now() + 60_000;
  panel._adminActionState.destructiveTargets.nas_share_delete.generation = 1;
  panel.hass = {
    ...panel._hass,
    states: {
      "sensor.management_access": { state: "unavailable", attributes: {} },
    },
  };
  assert.equal(panel._adminActionState.handsetTargets.result, undefined);
  assert.equal(
    panel._adminActionState.destructiveTargets.nas_share_delete.result,
    undefined,
  );

  panel._adminActionState.handsetTargets.result = {
    targets: [{ target_token: HANDSET_TOKEN, paging: false }],
    truncated: false,
  };
  panel.hass = {
    ...panel._hass,
    user: { id: "viewer", is_admin: false },
  };
  assert.equal(panel._adminActionState.handsetTargets.result, undefined);

  panel._adminActionState.voipLineTargets.result = {
    targets: [{ target_token: LINE_TOKEN, active: true }],
    truncated: false,
  };
  panel._adminActionState.destructiveTargets.phonebook_entry_delete.result = {
    targets: [
      {
        target_token: HANDSET_TOKEN,
        reference: "contact1",
        display_name: "Alice Example",
      },
    ],
    truncated: false,
  };
  panel.shadowRoot.innerHTML = "PRIVATE TARGET MARKUP";
  panel.disconnectedCallback();
  assert.equal(panel._adminActionState.voipLineTargets.result, undefined);
  assert.equal(
    panel._adminActionState.destructiveTargets.phonebook_entry_delete.result,
    undefined,
  );
  assert.equal(panel.shadowRoot.innerHTML, "");
});
