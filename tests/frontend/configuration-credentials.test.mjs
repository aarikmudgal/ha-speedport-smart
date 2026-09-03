import assert from "node:assert/strict";
import test from "node:test";
import {createConfigurationEditorController, renderConfigurationEditor} from "../../custom_components/speedport_smart/frontend/configuration-editor.js";

const setting = {id: "vpn_peer_create", title: "New VPN peer", confirmation: "CREATE VPN PEER",
  fields: [{name: "name", label: "Name", kind: "text", minimum: 0, maximum: 20}]};
const secret = "SYNTHETIC-PRIVATE-VPN-CREDENTIAL";
const response = () => ({status: "verified", private_download: {
  filename: "Wireguard.conf", media_type: "text/plain;charset=utf-8", content: secret,
}});
async function ready(result = response(), overrides = {}) {
  const requests = []; const downloads = [];
  const controller = createConfigurationEditorController({request: async (message) => {
    requests.push(message.type);
    return message.type.endsWith("/read") ? {setting_id: setting.id, values: {name: ""}, revision: "opaque", expires_in: 120} : result;
  }, download: async (blob, filename) => downloads.push({text: await blob.text(), filename}), ...overrides});
  controller.open({entryId: "entry", setting}); await controller.load();
  controller.setValue("name", "New peer"); controller.setConfirmation(setting.confirmation);
  return {controller, requests, downloads, result};
}

test("verified credentials stay outside rendered state and download only on explicit click", async () => {
  const {controller, requests, downloads, result} = await ready();
  assert.equal(await controller.save(), true);
  assert.equal(controller.snapshot().status, "credentials_ready");
  assert.equal(controller.snapshot().downloadAvailable, true);
  assert.doesNotMatch(JSON.stringify(controller.snapshot()), /SYNTHETIC-PRIVATE/);
  assert.doesNotMatch(renderConfigurationEditor(controller), /SYNTHETIC-PRIVATE/);
  assert.equal(result.private_download.content, "");
  assert.equal(downloads.length, 0);
  assert.equal(await controller.downloadCredentials(), true);
  assert.deepEqual(downloads, [{text: secret, filename: "Wireguard.conf"}]);
  assert.equal(await controller.downloadCredentials(), false);
  assert.equal(requests.length, 2);
  controller.dispose();
});

test("credential expiry erases the temporary result without any router request", async (t) => {
  t.mock.timers.enable({apis: ["setTimeout"]});
  const {controller, requests, downloads} = await ready(); await controller.save();
  t.mock.timers.tick(120000);
  assert.equal(controller.snapshot().downloadAvailable, false);
  assert.equal(controller.snapshot().status, "credentials_expired");
  assert.equal(await controller.downloadCredentials(), false);
  assert.equal(requests.length, 2); assert.equal(downloads.length, 0);
  controller.dispose();
});

test("closing or changing the editor destroys generated secrets", async () => {
  for (const action of ["close", "dispose", "load"]) {
    const {controller, downloads} = await ready(); await controller.save();
    await controller[action]();
    assert.equal(await controller.downloadCredentials(), false);
    assert.equal(downloads.length, 0); controller.dispose();
  }
});

test("local download failure may retry locally but never repeats the router write", async () => {
  let attempts = 0;
  const {controller, requests} = await ready(response(), {download: async () => {
    if (++attempts === 1) throw new Error("local download blocked");
  }});
  await controller.save();
  assert.equal(await controller.downloadCredentials(), false);
  assert.equal(await controller.downloadCredentials(), true);
  assert.equal(requests.length, 2); controller.dispose();
});

for (const bad of [
  {filename: "../secret.txt"}, {media_type: "text/html"}, {content: ""}, {content: "x".repeat(65537)}, {extra: "secret"},
]) test("malformed credential result fails without a download", async () => {
  const result = response(); Object.assign(result.private_download, bad);
  const {controller, downloads} = await ready(result);
  assert.equal(await controller.save(), false);
  assert.equal(controller.snapshot().status, "outcome_unknown");
  assert.equal(controller.snapshot().downloadAvailable, false);
  assert.equal(downloads.length, 0); controller.dispose();
});

test("unverified actions cannot deliver a private credential file", async () => {
  const result = response(); result.status = "outcome_unknown";
  const {controller} = await ready(result);
  assert.equal(await controller.save(), false);
  assert.equal(await controller.downloadCredentials(), false); controller.dispose();
});
