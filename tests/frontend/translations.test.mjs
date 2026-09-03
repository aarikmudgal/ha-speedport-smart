import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { keepDialogFocus } from "../../custom_components/speedport_smart/frontend/accessibility.js";

import {
  formatPanelDurationSeconds,
  PANEL_TRANSLATIONS,
  panelTranslate,
  resolvePanelLanguage,
} from "../../custom_components/speedport_smart/frontend/translations.js";

function placeholders(value) {
  return [...value.matchAll(/\{([a-z0-9_]+)\}/gi)]
    .map((match) => match[1])
    .sort();
}

test("English and German panel dictionaries have identical keys and placeholders", () => {
  const englishKeys = Object.keys(PANEL_TRANSLATIONS.en).sort();
  const germanKeys = Object.keys(PANEL_TRANSLATIONS.de).sort();
  assert.deepEqual(germanKeys, englishKeys);
  for (const key of englishKeys) {
    assert.deepEqual(
      placeholders(PANEL_TRANSLATIONS.de[key]),
      placeholders(PANEL_TRANSLATIONS.en[key]),
      key,
    );
  }
});

test("removed control groups have no labels while catalog labels remain", () => {
  const removedControlGroups = [
    "group.controls_mesh",
    "group.controls_ddns",
    "group.controls_vpn",
    "group.controls_parental",
    "group.controls_media",
  ];
  const retainedCatalogLabels = [
    "admin.feature.internet_parental_controls",
    "admin.feature.internet_ddns_management",
    "admin.feature.network_vpn_management",
    "admin.feature.network_usb_printer_media",
    "admin.feature.network_media_folders",
    "admin.feature.system_dsl_modem_mode",
  ];

  for (const language of ["en", "de"]) {
    for (const key of removedControlGroups) {
      assert.equal(Object.hasOwn(PANEL_TRANSLATIONS[language], key), false, key);
    }
    for (const key of retainedCatalogLabels) {
      assert.equal(Object.hasOwn(PANEL_TRANSLATIONS[language], key), true, key);
    }
  }
});

test("Home Assistant language selects German with English fallback", () => {
  assert.equal(resolvePanelLanguage({ language: "de-DE" }, "en-US"), "de");
  assert.equal(
    resolvePanelLanguage({ locale: { language: "de_AT" } }, "en-US"),
    "de",
  );
  assert.equal(resolvePanelLanguage({ language: "fr-FR" }, "de-DE"), "en");
  assert.equal(resolvePanelLanguage(undefined, "de-DE"), "de");
});

test("Firmware-discovered detail families have localized capability labels", () => {
  const expected = {
    de: {
      dect_repeater: "DECT-Repeater",
      mesh_topology: "Mesh-Topologie",
      system_services: "Systemdienste",
      vpn_details: "VPN-Details",
      wifi_schedule: "WLAN-Zeitplan",
    },
    en: {
      dect_repeater: "DECT repeaters",
      mesh_topology: "Mesh topology",
      system_services: "System services",
      vpn_details: "VPN details",
      wifi_schedule: "Wi-Fi schedule",
    },
  };
  for (const [language, labels] of Object.entries(expected)) {
    for (const [family, label] of Object.entries(labels)) {
      assert.equal(panelTranslate(language, `capability.${family}`), label);
    }
  }
});

test("Every registered child-device kind has a localized label", () => {
  const expected = {
    en: {
      dect_repeater: "DECT repeater",
      powerline_node: "Powerline device",
    },
    de: {
      dect_repeater: "DECT-Repeater",
      powerline_node: "Powerline-Gerät",
    },
  };
  for (const [language, labels] of Object.entries(expected)) {
    for (const [kind, label] of Object.entries(labels)) {
      assert.equal(panelTranslate(language, `child.${kind}`), label);
    }
  }
});

test("Panel translation interpolates values and falls back to English", () => {
  assert.equal(
    panelTranslate("de", "count.entities", { count: 4 }),
    "4 Entitäten",
  );
  assert.equal(panelTranslate("fr", "action.cancel"), "Cancel");
  assert.equal(panelTranslate("de", "missing.key"), "missing.key");
});

test("Unavailable-control reasons are complete, localized, and bounded", () => {
  const reasons = [
    "authenticated_access_unavailable",
    "capability_not_proven",
    "command_handler_unavailable",
    "contract_unavailable",
    "control_surface_unavailable",
    "controls_disabled",
    "disabled_by_firmware",
    "disabled_by_setting",
    "firmware_not_supported",
    "incompatible_encryption",
    "management_session_unavailable",
    "polling_unavailable",
    "ssid_hidden",
    "state_readback_unavailable",
    "state_readback_unsupported",
    "wifi_off",
    "wps_in_progress",
    "wps_prerequisite_unavailable",
  ];
  const keys = Object.keys(PANEL_TRANSLATIONS.en)
    .filter((key) => key.startsWith("control.unavailable_reason."))
    .map((key) => key.slice("control.unavailable_reason.".length))
    .sort();

  assert.deepEqual(keys, reasons.sort());
  assert.equal(
    panelTranslate("en", "control.unavailable_reason.capability_not_proven"),
    "This router has not confirmed that this control is supported.",
  );
  assert.equal(
    panelTranslate("de", "control.unavailable_reason.disabled_by_setting"),
    "Diese Steuerung ist in den Router-Einstellungen deaktiviert.",
  );
  assert.equal(
    panelTranslate("de", "control.unavailable_reason.firmware_not_supported"),
    "Diese Router-Firmware unterstützt diese Steuerung nicht.",
  );
  assert.equal(
    panelTranslate("en", "control.unavailable_reason.wps_in_progress"),
    "WPS pairing is already in progress.",
  );
  assert.equal(
    panelTranslate("de", "control.unavailable_reason.wps_in_progress"),
    "Die WPS-Kopplung läuft bereits.",
  );
});

test("Durations use localized compact units and reject invalid samples", () => {
  assert.equal(formatPanelDurationSeconds(0, "en-US", "en"), "0 s");
  assert.equal(formatPanelDurationSeconds(59, "de-DE", "de"), "59 Sek.");
  assert.equal(formatPanelDurationSeconds(60, "de-DE", "de"), "1 Min.");
  assert.equal(
    formatPanelDurationSeconds(3_661, "en-US", "en"),
    "1 h 1 min",
  );
  assert.equal(formatPanelDurationSeconds(-1, "en-US", "en"), undefined);
  assert.equal(formatPanelDurationSeconds("bad", "en-US", "en"), undefined);
});

test("Panel keeps the accessible dialog and live-status contract", async () => {
  const [panel, backend, entityState] = await Promise.all([
    readFile(
      new URL(
        "../../custom_components/speedport_smart/frontend/speedport-smart-panel.js",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        "../../custom_components/speedport_smart/panel.py",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        "../../custom_components/speedport_smart/frontend/entity-state.js",
        import.meta.url,
      ),
      "utf8",
    ),
  ]);
  assert.match(panel, /speedport-confirm-description/);
  assert.match(panel, /ACCESS_SOURCE_ORDER = \[[\s\S]*"public_json"/);
  assert.match(
    panel,
    /public_json:\s*\{[\s\S]*?titleKey:\s*"source\.public_json\.title",[\s\S]*?shortKey:\s*"source\.public_json\.short",[\s\S]*?descriptionKey:\s*"source\.public_json\.description",/,
  );
  assert.match(panel, /tabindex="-1"/);
  assert.match(panel, /\(editor \|\| cancel \|\| dialog\)\?\.focus\(\)/);
  assert.match(panel, /keepDialogFocus/);
  assert.match(entityState, /meta\?\.custom_name/);
  assert.match(panel, /aria-live="\$\{/);
  assert.match(panel, /aria-label="Router administration categories"/);
  assert.match(panel, /data-admin-menu aria-expanded=/);
  assert.match(panel, /inert aria-hidden="true"/);
  assert.match(panel, /_focusAfterRenderEntityId/);
  assert.match(panel, /!meta\?\.control/);
  assert.match(panel, /data-text-draft/);
  assert.match(panel, /data-select-draft/);
  assert.match(panel, /data-confirm-draft/);
  assert.match(panel, /typedConfirmationMatches/);
  assert.match(panel, /controlConfirmationPolicyMatches/);
  assert.match(panel, /confirm\.sensitive_switch/);
  assert.match(panel, /selectControlServiceCall/);
  assert.match(panel, /escapeHtml\(this\._translatedSelectOption/);
  assert.match(panel, /"hybrid_bonding",[\s\S]*"internet_privacy_level_control"/);
  assert.match(panel, /receiver_led_mode_control"\) return "controls_mobile"/);
  assert.doesNotMatch(
    panel,
    /router\.model\s*\|\|\s*["']Telekom Speedport Smart["']/,
  );
  assert.match(panel, /router\.model\s*\?\s*`<p>/);
  assert.match(panel, /online-dot \$\{connectionPresentation\.className\}/);
  assert.match(panel, /\.online-dot\.unavailable\s*\{/);
  assert.match(panel, /if \(this\._pendingAction\) return false/);
  assert.match(panel, /pending\.observedState/);
  assert.match(panel, /action\.for_entity/);
  assert.match(
    panel,
    /if \(meta\.capability_group && CAPABILITY_GROUP_INFO\[meta\.capability_group\]\)/,
  );
  assert.match(panel, /return meta\.capability_group;/);
  assert.doesNotMatch(panel, /localStorage|sessionStorage/);

  const frontendSchema = panel.match(/PANEL_SCHEMA_VERSION = (\d+)/)?.[1];
  const backendSchema = backend.match(/PANEL_SCHEMA_VERSION: Final = (\d+)/)?.[1];
  assert.ok(frontendSchema);
  assert.equal(frontendSchema, "26");
  assert.equal(frontendSchema, backendSchema);
  assert.match(panel, new RegExp(`accessibility\\.js\\?schema=${frontendSchema}`));
  assert.match(panel, new RegExp(`translations\\.js\\?schema=${frontendSchema}`));
  assert.match(panel, new RegExp(`controls\\.js\\?schema=${frontendSchema}`));
  assert.match(panel, new RegExp(`entity-state\\.js\\?schema=${frontendSchema}`));
  assert.match(panel, new RegExp(`render-state\\.js\\?schema=${frontendSchema}`));
  assert.match(
    panel,
    /\.entity-card\.unknown > \.entity-main \.availability-dot/,
  );
  assert.doesNotMatch(panel, /\.unknown \.availability-dot/);

  const referencedKeys = new Set([
    ...[...panel.matchAll(/this\._t\("([a-z0-9_.]+)"/gi)].map(
      (match) => match[1],
    ),
    ...[
      ...panel.matchAll(
        /(?:titleKey|subtitleKey|shortKey|descriptionKey|labelKey):\s*"([a-z0-9_.]+)"/gi,
      ),
    ].map((match) => match[1]),
  ]);
  for (const key of referencedKeys) {
    assert.ok(Object.hasOwn(PANEL_TRANSLATIONS.en, key), key);
  }
});

test("Busy dialogs retain focus when every action is disabled", () => {
  let prevented = false;
  let focused = false;
  const event = {
    key: "Tab",
    shiftKey: false,
    preventDefault() {
      prevented = true;
    },
  };
  const dialog = {
    querySelectorAll() {
      return [];
    },
    focus() {
      focused = true;
    },
  };

  assert.equal(keepDialogFocus(event, dialog, undefined), true);
  assert.equal(prevented, true);
  assert.equal(focused, true);
});

test("Dialog focus wraps in both directions", () => {
  const visits = [];
  const first = { focus: () => visits.push("first") };
  const middle = { focus: () => visits.push("middle") };
  const last = { focus: () => visits.push("last") };
  const dialog = { querySelectorAll: () => [first, middle, last] };
  const event = {
    key: "Tab",
    shiftKey: false,
    preventDefault() {},
  };

  assert.equal(keepDialogFocus(event, dialog, last), true);
  event.shiftKey = true;
  assert.equal(keepDialogFocus(event, dialog, first), true);
  assert.deepEqual(visits, ["first", "last"]);
});
