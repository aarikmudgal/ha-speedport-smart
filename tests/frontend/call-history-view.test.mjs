import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {
  bindCallHistoryView, createCallHistoryViewController, renderCallHistoryView,
} from "../../custom_components/speedport_smart/frontend/call-history-view.js";

const row = {date: "02.09.2026", time: "12:34", remote_party: "PRIVATE-CALLER", local_party: "PRIVATE-LINE", duration_seconds: 12};
const response = (category = "taken", entries = [row]) => ({schema_version: 1, query: "call_history", result: {category, entries, total: entries.length}});
const csv = (category = "taken") => ({schema_version: 1, query: "call_history", result: {category, private_download: {
  filename: `Speedport-${category}-calls.csv`, media_type: "text/csv;charset=utf-8", content: "PRIVATE-CSV",
}}});
const deferred = () => { let resolve; const promise = new Promise((accept) => { resolve = accept; }); return {promise, resolve}; };

test("opening and rendering never load or export", () => {
  let calls = 0;
  const controller = createCallHistoryViewController({request: async () => { calls++; }});
  controller.open({entryId: "entry-a"});
  assert.equal(controller.snapshot().category, "taken");
  renderCallHistoryView(controller);
  assert.equal(calls, 0); assert.deepEqual(controller.entries(), []);
});

test("explicit GET projects private rows but excludes them from snapshot", async () => {
  const calls = [];
  const controller = createCallHistoryViewController({request: async (message) => { calls.push(message); return response(); }});
  controller.open({entryId: "entry-a"});
  assert.equal(await controller.load(), true);
  assert.deepEqual(calls, [{type: "speedport_smart/panel/call_history", entry_id: "entry-a", category: "taken", export: false}]);
  assert.equal(controller.snapshot().total, 1);
  assert.doesNotMatch(JSON.stringify(controller.snapshot()), /PRIVATE/);
  assert.match(renderCallHistoryView(controller), /PRIVATE-CALLER/);
  controller.close(); assert.equal(controller.snapshot(), null); assert.deepEqual(controller.entries(), []);
});

test("CSV is an explicit fresh read and private download is not retained", async () => {
  const calls = []; let borrowed;
  const controller = createCallHistoryViewController({request: async (message) => { calls.push(message); return message.export ? csv() : response(); },
    download: (value) => { borrowed = value; assert.equal(value.content, "PRIVATE-CSV"); }});
  controller.open({entryId: "entry-a"}); await controller.load();
  assert.equal(await controller.exportCsv(), true);
  assert.equal(calls.length, 2); assert.equal(calls[1].export, true);
  assert.equal(borrowed.content, ""); assert.deepEqual(controller.entries(), []);
  assert.doesNotMatch(JSON.stringify(controller.snapshot()) + renderCallHistoryView(controller), /PRIVATE-CALLER|PRIVATE-CSV/);
});

test("new category, close and navigation disposal reject late results", async () => {
  for (const transition of ["category", "close", "dispose", "new-entry"]) {
    const pending = deferred(); let downloads = 0;
    const controller = createCallHistoryViewController({request: () => pending.promise, download: () => { downloads++; }});
    controller.open({entryId: "entry-a"}); const started = controller.load();
    if (transition === "category") controller.setCategory("missed");
    else if (transition === "new-entry") controller.open({entryId: "entry-b"});
    else controller[transition]();
    pending.resolve(response()); assert.equal(await started, false);
    assert.deepEqual(controller.entries(), []); assert.equal(downloads, 0);
  }
});

test("late export after close never downloads private data", async () => {
  const pending = deferred(); let downloads = 0;
  const controller = createCallHistoryViewController({request: () => pending.promise, download: () => { downloads++; }});
  controller.open({entryId: "entry-a"}); const started = controller.exportCsv();
  controller.close(); pending.resolve(csv()); assert.equal(await started, false); assert.equal(downloads, 0);
});

test("double click is coalesced without polling or retry", async () => {
  const pending = deferred(); let calls = 0;
  const controller = createCallHistoryViewController({request: () => { calls++; return pending.promise; }});
  controller.open({entryId: "entry-a"}); const first = controller.load();
  assert.equal(await controller.load(), false); assert.equal(await controller.exportCsv(), false);
  pending.resolve(response()); assert.equal(await first, true); assert.equal(calls, 1);
});

test("missing, malformed, partial or mismatched records are never empty success", async () => {
  const cases = [
    {schema_version: 1, query: "call_history", result: {category: "taken"}},
    {...response(), schema_version: 2}, {...response(), query: "phonebook_search"}, response("missed"),
    {schema_version: 1, query: "call_history", result: {category: "taken", entries: [], total: 1}},
    response("taken", [{...row, duration_seconds: "12"}]), response("taken", [{...row, date: ""}]),
    response("taken", [{...row, remote_party: "PRIVATE\nRAW"}]), response("taken", Array(1001).fill(row)),
  ];
  for (const value of cases) {
    const controller = createCallHistoryViewController({request: async () => value});
    controller.open({entryId: "entry-a"}); assert.equal(await controller.load(), false);
    assert.equal(controller.snapshot().status, "unavailable"); assert.deepEqual(controller.entries(), []);
    assert.doesNotMatch(renderCallHistoryView(controller), /PRIVATE-CALLER/);
  }
});

test("explicit empty history is displayed as zero, not fabricated from an error", async () => {
  const controller = createCallHistoryViewController({request: async () => response("taken", [])});
  controller.open({entryId: "entry-a"}); assert.equal(await controller.load(), true);
  assert.match(renderCallHistoryView(controller), /0 calls/);
});

test("wrong CSV identity, unsafe filenames and invalid types never download", async () => {
  for (const mutation of ["category", "filename", "media_type", "content", "huge"]) {
    const value = csv(); let downloads = 0;
    if (mutation === "category") value.result.category = "missed";
    else if (mutation === "huge") value.result.private_download.content = "x".repeat(4200001);
    else value.result.private_download[mutation] = mutation === "content" ? {} : "../PRIVATE";
    const controller = createCallHistoryViewController({request: async () => value, download: () => { downloads++; }});
    controller.open({entryId: "entry-a"}); assert.equal(await controller.exportCsv(), false); assert.equal(downloads, 0);
    assert.equal(controller.snapshot().status, "unavailable");
  }
});

test("raw error text stays private and failed refresh clears older data", async () => {
  let count = 0;
  const controller = createCallHistoryViewController({request: async () => {
    if (count++ === 0) return response(); throw new Error("PRIVATE-ERROR");
  }});
  controller.open({entryId: "entry-a"}); await controller.load();
  assert.equal(await controller.load(), false); assert.deepEqual(controller.entries(), []);
  assert.doesNotMatch(renderCallHistoryView(controller), /PRIVATE-ERROR|PRIVATE-CALLER/);
});

test("private rendering escapes router labels and keeps native accessible theme", async () => {
  const controller = createCallHistoryViewController({request: async () => response("taken", [{...row, remote_party: '<img src=x onerror="bad">', local_party: "<script>bad</script>"}])});
  controller.open({entryId: "entry-a"}); await controller.load();
  const html = renderCallHistoryView(controller);
  assert.doesNotMatch(html, /<img|<script>/); assert.match(html, /&lt;img/);
  assert.match(html, /aria-live="polite"/); assert.match(html, /var\(--primary-text-color\)/);
});

test("category change clears current records without autoload; selector is closed", async () => {
  let calls = 0;
  const controller = createCallHistoryViewController({request: async () => { calls++; return response(); }});
  controller.open({entryId: "entry-a"}); await controller.load();
  assert.equal(controller.setCategory("missed"), true); assert.deepEqual(controller.entries(), []); assert.equal(calls, 1);
  assert.equal(controller.setCategory("constructor"), false);
  assert.throws(() => controller.open({entryId: "entry-a", category: "__proto__"}));
  assert.throws(() => controller.open({entryId: ""})); assert.equal(controller.snapshot(), null);
});

test("delegated binding clears private DOM and disposes navigation listeners", async () => {
  const listeners = new Map(); let clears = 0;
  const root = {addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener: (name) => listeners.delete(name),
    contains: () => true, querySelectorAll: () => [{replaceChildren: () => { clears++; }}]};
  const controller = createCallHistoryViewController({request: async () => response()});
  controller.open({entryId: "entry-a"}); await controller.load();
  const dispose = bindCallHistoryView(root, controller); assert.equal(listeners.size, 2);
  dispose(); assert.equal(controller.snapshot(), null); assert.deepEqual(controller.entries(), []);
  assert.equal(clears, 1); assert.equal(listeners.size, 0);
});

test("view has no storage, background request, iframe or raw error rendering", () => {
  const source = readFileSync(new URL("../../custom_components/speedport_smart/frontend/call-history-view.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /setInterval|setTimeout|localStorage|sessionStorage|indexedDB|<iframe|console\.|error\.message/);
  assert.match(source, /URL\.revokeObjectURL/);
});

test("native download uses a temporary blob URL and removes it after click", async () => {
  const oldDocument = globalThis.document;
  const oldCreate = URL.createObjectURL;
  const oldRevoke = URL.revokeObjectURL;
  const events = [];
  const anchor = {click() { events.push(["click", this.href, this.download]); }, remove() { events.push(["remove"]); }};
  globalThis.document = {createElement: (name) => { assert.equal(name, "a"); return anchor; }, body: {append: (value) => { assert.equal(value, anchor); events.push(["append"]); }}};
  URL.createObjectURL = (blob) => { assert.equal(blob.type, "text/csv;charset=utf-8"); events.push(["create"]); return "blob:private-test"; };
  URL.revokeObjectURL = (url) => { events.push(["revoke", url]); };
  try {
    const controller = createCallHistoryViewController({request: async () => csv()});
    controller.open({entryId: "entry-a"}); assert.equal(await controller.exportCsv(), true);
    assert.deepEqual(events, [["create"], ["append"], ["click", "blob:private-test", "Speedport-taken-calls.csv"], ["remove"], ["revoke", "blob:private-test"]]);
  } finally {
    globalThis.document = oldDocument; URL.createObjectURL = oldCreate; URL.revokeObjectURL = oldRevoke;
  }
});

test("download failure clears borrowed content and reveals only a fixed error", async () => {
  let borrowed;
  const controller = createCallHistoryViewController({request: async () => csv(), download: (value) => { borrowed = value; throw new Error("PRIVATE-ERROR"); }});
  controller.open({entryId: "entry-a"}); assert.equal(await controller.exportCsv(), false);
  assert.equal(borrowed.content, ""); assert.equal(controller.snapshot().status, "unavailable");
  assert.doesNotMatch(renderCallHistoryView(controller), /PRIVATE-ERROR|PRIVATE-CSV/);
});
