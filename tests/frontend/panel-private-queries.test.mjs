import assert from "node:assert/strict";
import test from "node:test";

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
  ADMIN_IA,
  SpeedportSmartPanel,
  adminPrivateQueryInputError,
  normalizeAdminPrivateQueryPayload,
} = await import(
  "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js?test=private-queries"
);

function router({
  capabilities = ["pbx", "pbx_clients", "phonebook"],
  managementState = "available",
} = {}) {
  return {
    access_sources: [
      { id: "protected_json", available: true, supported: true },
    ],
    capabilities,
    capability_families: [],
    entities: [],
    entry_id: "entry-a",
    entry_state: "loaded",
    management: { controls_available: false, state: managementState },
    title: "Router",
  };
}

function fixture(options = {}) {
  const calls = [];
  const panel = new SpeedportSmartPanel();
  panel._render = () => {};
  panel._activeView = "administration";
  panel._metadata = { routers: [router(options)] };
  panel._selectedEntry = "entry-a";
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

function envelope(query, result) {
  return { query, result, schema_version: 1 };
}

function featureById(id) {
  return ADMIN_IA.flatMap((area) => area.subsections)
    .flatMap((subsection) => subsection.features)
    .find((feature) => feature.id === id);
}

function featureWindow(html, id) {
  const start = html.indexOf(`data-admin-feature="${id}"`);
  assert.notEqual(start, -1, id);
  const next = html.indexOf('data-admin-feature="', start + 1);
  return html.slice(start, next === -1 ? undefined : next);
}

test("private query inputs match the closed backend schemas", () => {
  assert.equal(
    adminPrivateQueryInputError("ip_pbx_refresh", { clientId: "client_2" }),
    undefined,
  );
  assert.equal(
    adminPrivateQueryInputError("ip_pbx_refresh", { clientId: "../2" }),
    "admin.query.error.identifier",
  );
  assert.equal(
    adminPrivateQueryInputError("phonebook_search", {
      phonebookId: 4,
      prefix: "Z",
    }),
    undefined,
  );
  assert.equal(
    adminPrivateQueryInputError("phonebook_search", {
      phonebookId: true,
      prefix: "A",
    }),
    "admin.query.error.phonebook",
  );
  assert.equal(
    adminPrivateQueryInputError("phonebook_search", {
      phonebookId: 0,
      prefix: "AB",
    }),
    "admin.query.error.prefix",
  );
});

test("private responses are allowlisted, bounded, and bound to their request", () => {
  const pbx = normalizeAdminPrivateQueryPayload(
    envelope("ip_pbx_refresh", {
      client_id: "2",
      status: "registered",
      status_code: 1,
      name: "<script>Phone</script>",
      ipv4: "192.168.2.20",
      mac: "AA:BB:CC:DD:EE:FF",
      password: "MUST-NOT-SURVIVE",
    }),
    "ip_pbx_refresh",
    { clientId: "2" },
  );
  assert.deepEqual(pbx, {
    client_id: "2",
    status: "registered",
    status_code: 1,
    name: "<script>Phone</script>",
    ipv4: "192.168.2.20",
    mac: "AA:BB:CC:DD:EE:FF",
  });
  assert.equal(
    normalizeAdminPrivateQueryPayload(
      envelope("ip_pbx_refresh", {
        client_id: "3",
        status: "registered",
        status_code: 1,
      }),
      "ip_pbx_refresh",
      { clientId: "2" },
    ),
    undefined,
  );

  const contact = normalizeAdminPrivateQueryPayload(
    envelope("phonebook_contact", {
      phonebook_id: 1,
      contact_id: "8",
      contact: {
        first_name: "Alice",
        private_number: "+49 30 1234",
        secret_note: "MUST-NOT-SURVIVE",
      },
    }),
    "phonebook_contact",
    { phonebookId: 1, contactId: "8" },
  );
  assert.deepEqual(contact, {
    phonebook_id: 1,
    contact_id: "8",
    contact: { first_name: "Alice", private_number: "+49 30 1234" },
  });
  assert.doesNotMatch(JSON.stringify(contact), /MUST-NOT-SURVIVE/);

  const search = normalizeAdminPrivateQueryPayload(
    envelope("phonebook_search", {
      phonebook_id: 1,
      prefix: "A",
      entries: [],
      truncated: false,
      total: 3,
      free_entries: 997,
      private_capacity: "MUST-NOT-SURVIVE",
    }),
    "phonebook_search",
    { phonebookId: 1, prefix: "A" },
  );
  assert.deepEqual(search, {
    phonebook_id: 1,
    prefix: "A",
    entries: [],
    truncated: false,
    total: 3,
    free_entries: 997,
  });
  assert.doesNotMatch(JSON.stringify(search), /private_capacity|MUST-NOT-SURVIVE/);
});

test("queries render only under their owning read-only feature cards", () => {
  const { panel } = fixture();
  const html = panel._renderAdministration(
    router(),
    [],
    [],
    { protected_json: { available: true } },
  );
  const pbx = featureWindow(html, "telephony_ip_pbx");
  const phonebook = featureWindow(html, "telephony_phonebook_management");

  assert.match(pbx, /data-admin-query="ip_pbx_refresh"/);
  assert.match(phonebook, /data-admin-query="phonebook_search"/);
  assert.match(pbx, /Read-only query/);
  assert.match(phonebook, /data-admin-query-form="phonebook_search"/);
  assert.match(phonebook, /aria-describedby=/);
  assert.doesNotMatch(`${pbx}${phonebook}`, /data-control=|callService|localStorage|sessionStorage/);
});

test("query support is distinct from temporary session availability", () => {
  const absent = fixture({ capabilities: [] });
  const absentFeature = featureById("telephony_phonebook_management");
  assert.equal(
    absent.panel._adminFeaturePresentation(
      absentFeature,
      [],
      new Map(),
      new Set(),
      true,
    ).key,
    "not_observed",
  );
  const absentMarkup = absent.panel._renderAdminPrivatePhonebookQuery();
  assert.match(absentMarkup, /has not exposed the required capability/);
  assert.match(absentMarkup, /<button class="primary" type="submit" disabled>/);

  const blocked = fixture({ managementState: "blocked" });
  assert.equal(
    blocked.panel._adminFeaturePresentation(
      absentFeature,
      [],
      new Map(),
      new Set(["phonebook"]),
      false,
    ).key,
    "temporarily_unavailable",
  );
  assert.match(
    blocked.panel._renderAdminPrivatePhonebookQuery(),
    /protected router session must be available/,
  );
});

test("broad PBX evidence cannot unlock the targeted IPClients query", () => {
  const broadOnly = fixture({ capabilities: ["pbx", "phonebook"] });

  assert.equal(
    broadOnly.panel._adminPrivateQueryCapabilityObserved("ip_pbx_refresh"),
    false,
  );
  assert.match(
    broadOnly.panel._renderAdminPrivatePbxQuery(),
    /has not exposed the required capability/,
  );
});

test("successful queries send only the fixed messages and retain only normalized results", async () => {
  const { calls, panel } = fixture();
  panel._requestPrivate = async (message) => {
    calls.push(message);
    if (message.type.endsWith("/ip_pbx_refresh")) {
      return envelope("ip_pbx_refresh", {
        client_id: "2",
        status: "registered",
        status_code: 1,
        name: "<img src=x onerror=alert(1)>",
        password: "MUST-NOT-SURVIVE",
      });
    }
    if (message.type.endsWith("/phonebook_search")) {
      return envelope("phonebook_search", {
        phonebook_id: 0,
        prefix: "A",
        entries: [
          { contact_id: "8", first_name: "Alice", number: "+49 30 1" },
        ],
        truncated: false,
        total: 1,
        free_entries: 999,
      });
    }
    return envelope("phonebook_contact", {
      phonebook_id: 0,
      contact_id: "8",
      contact: { first_name: "Alice", private_number: "+49 30 1" },
    });
  };

  panel._adminPrivateQueries.pbx.clientId = "2";
  await panel._runIpPbxQuery();
  panel._adminPrivateQueries.phonebook.prefix = "A";
  await panel._runPhonebookSearchQuery();
  await panel._runPhonebookContactQuery("8");

  assert.deepEqual(calls, [
    {
      type: "speedport_smart/panel/ip_pbx_refresh",
      entry_id: "entry-a",
      client_id: "2",
    },
    {
      type: "speedport_smart/panel/phonebook_search",
      entry_id: "entry-a",
      phonebook_id: 0,
      prefix: "A",
    },
    {
      type: "speedport_smart/panel/phonebook_contact",
      entry_id: "entry-a",
      phonebook_id: 0,
      contact_id: "8",
    },
  ]);
  assert.doesNotMatch(JSON.stringify(panel._adminPrivateQueries), /MUST-NOT-SURVIVE/);
  assert.equal(panel._adminPrivateQueries.phonebook.searchResult.free_entries, 999);
  assert.match(panel._renderAdminPrivatePhonebookQuery(), /Free entries: 999/);
  const pbxMarkup = panel._renderAdminPrivatePbxQuery();
  assert.doesNotMatch(pbxMarkup, /MUST-NOT-SURVIVE|<img/);
  assert.match(pbxMarkup, /&lt;img src=x onerror=alert\(1\)&gt;/);
  panel._selectView("dashboard");
  assert.equal(panel._adminPrivateQueries.pbx.result, undefined);
  assert.equal(panel._adminPrivateQueries.phonebook.contactResult, undefined);
});

test("a replacement search and Clear invalidate an in-flight private contact", async () => {
  const { panel } = fixture();
  const pendingContacts = [];
  panel._requestPrivate = (message) => {
    if (message.type.endsWith("/phonebook_contact")) {
      return new Promise((resolve) => pendingContacts.push(resolve));
    }
    return Promise.resolve(
      envelope("phonebook_search", {
        phonebook_id: 0,
        prefix: "B",
        entries: [{ contact_id: "9", first_name: "Bob" }],
        truncated: false,
      }),
    );
  };
  const state = panel._adminPrivateQueries.phonebook;
  state.searchResult = {
    phonebook_id: 0,
    prefix: "A",
    entries: [{ contact_id: "8", first_name: "Alice" }],
    truncated: false,
  };
  const oldContact = panel._runPhonebookContactQuery("8");
  state.prefix = "B";
  await panel._runPhonebookSearchQuery();
  pendingContacts[0](
    envelope("phonebook_contact", {
      phonebook_id: 0,
      contact_id: "8",
      contact: { first_name: "Alice" },
    }),
  );
  await oldContact;
  assert.equal(state.contactResult, undefined);
  assert.equal(state.searchResult.entries[0].contact_id, "9");

  const newContact = panel._runPhonebookContactQuery("9");
  panel._clearAdminPrivateQueryResult("phonebook_search");
  pendingContacts[1](
    envelope("phonebook_contact", {
      phonebook_id: 0,
      contact_id: "9",
      contact: { first_name: "Bob" },
    }),
  );
  await newContact;
  assert.equal(state.searchResult, undefined);
  assert.equal(state.contactResult, undefined);
});

test("rate-limit failures are typed and never echo server text", async () => {
  const { panel } = fixture();
  panel._adminPrivateQueries.pbx.clientId = "2";
  panel._requestPrivate = async () => {
    const error = new Error("PRIVATE SERVER DETAIL");
    error.code = "rate_limited";
    throw error;
  };

  await panel._runIpPbxQuery();

  assert.equal(
    panel._adminPrivateQueries.pbx.errorKey,
    "admin.query.error.rate_limited",
  );
  assert.doesNotMatch(
    panel._renderAdminPrivatePbxQuery(),
    /PRIVATE SERVER DETAIL/,
  );
});

test("disconnect clears both private state and detached shadow markup", () => {
  const { panel } = fixture();
  panel._adminPrivateQueries.phonebook.contactResult = {
    phonebook_id: 0,
    contact_id: "8",
    contact: { private_number: "+49 30 1" },
  };
  panel.shadowRoot.innerHTML = "PRIVATE CONTACT MARKUP";

  panel.disconnectedCallback();

  assert.equal(panel._adminPrivateQueries.phonebook.contactResult, undefined);
  assert.equal(panel.shadowRoot.innerHTML, "");
});
