import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {existsSync} from "node:fs";
import {fileURLToPath} from "node:url";
import test from "node:test";
import {createConfigurationEditorController, renderConfigurationEditor} from "../../custom_components/speedport_smart/frontend/configuration-editor.js";

const root = fileURLToPath(new URL("../../", import.meta.url));
const localPython = `${root}.venv/bin/python`;
const python = process.env.SPEEDPORT_TEST_PYTHON || (existsSync(localPython) ? localPython : "python3");
const exported = spawnSync(python, ["-c",
  "import json; from custom_components.speedport_smart.configuration import settings_contracts; from custom_components.speedport_smart.configuration_targets import target_settings_metadata; print(json.dumps([*(item.metadata() for item in settings_contracts().values()),*target_settings_metadata()]))"],
{cwd: root, encoding: "utf8"});
assert.equal(exported.status, 0, exported.stderr);
const settings = JSON.parse(exported.stdout);

test("every advertised scalar and target field has a safe renderer and fresh-read editing gate", async () => {
  const counts = {};
  let fields = 0;
  for (const setting of settings) {
    const calls = [];
    const values = {}, choices = {};
    for (const field of setting.fields) {
      fields++; counts[field.kind] = (counts[field.kind] || 0) + 1;
      if (field.dynamic_choices) choices[field.name] = Array.from({length: Math.max(1, field.minimum || 0)}, (_, index) => ({value: `row-${index}`, label: `Synthetic ${index}`}));
      if (field.kind === "boolean") values[field.name] = false;
      else if (field.kind === "integer") values[field.name] = field.minimum ?? 0;
      else if (field.kind === "enum") values[field.name] = (choices[field.name] || field.choices)[0].value;
      else if (field.kind === "identifiers") values[field.name] = (choices[field.name] || field.choices).slice(0, field.minimum || 0).map((choice) => choice.value);
      else if (field.kind !== "secret") values[field.name] = field.kind === "time" ? "12:30" : "x".repeat(Math.max(1, field.minimum || 0));
    }
    const controller = createConfigurationEditorController({request: async (message) => {
      calls.push(message);
      if (message.type.endsWith("/targets")) return {setting_id: setting.id, targets: [{id: "row-1", label: "Synthetic target"}]};
      return {setting_id: setting.id, ...(setting.requires_target ? {target_id: "row-1"} : {}),
        revision: "synthetic-revision", values, choices, expires_in: 120};
    }});
    controller.open({entryId: "synthetic-entry", setting});
    let html = renderConfigurationEditor(controller, {pageMode: true});
    for (const field of setting.fields) {
      const input = html.match(new RegExp(`<(?:input|select)[^>]*data-setting-field="${field.name}"[^>]*>`));
      assert.ok(input, `${setting.id}.${field.name} absent before read`);
      assert.match(input[0], / disabled/, `${setting.id}.${field.name} editable without revision`);
    }
    assert.equal(calls.length, 0, setting.id);
    assert.equal(await controller.save(), false, setting.id);
    if (setting.requires_target) {await controller.loadTargets(); controller.selectTarget("row-1");}
    assert.equal(await controller.load(), true, setting.id);
    html = renderConfigurationEditor(controller, {pageMode: true});
    for (const field of setting.fields) {
      const input = html.match(new RegExp(`<(?:input|select)[^>]*data-setting-field="${field.name}"[^>]*>`))?.[0];
      assert.ok(input, `${setting.id}.${field.name} absent after read`);
      assert.ok(!input.includes(" disabled"), `${setting.id}.${field.name} disabled after valid read`);
      if (field.kind === "boolean") assert.match(input, /type="checkbox"/);
      else if (field.kind === "enum") assert.match(input, /^<select /);
      else if (field.kind === "identifiers") assert.match(input, /^(?:<select multiple |<input type="checkbox")/);
      else if (field.kind === "integer") assert.match(input, /type="number"/);
      else if (field.kind === "secret") {assert.match(input, /type="password"/); assert.ok(!input.includes(" value="));}
      else assert.match(input, /type="(?:text|time)"/);
    }
    assert.ok(calls.every((call) => !call.type.endsWith("/save")), setting.id);
    controller.dispose();
  }
  assert.equal(settings.length, 110);
  assert.equal(settings.filter((setting) => setting.requires_target).length, 43);
  assert.equal(fields, 454);
  assert.deepEqual(counts, {boolean: 120, enum: 47, text: 214, identifiers: 11, secret: 29, integer: 33});
});
