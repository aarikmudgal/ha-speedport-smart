import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  CLIENT_NAME_PATTERN,
  SELECT_CONTROL_OPTIONS,
  controlConfirmationPhrase,
  controlConfirmationPolicyMatches,
  controlUnavailableReason,
  isSupportedSelectControl,
  isSupportedTextControl,
  managementControlAvailable,
  selectControlOptions,
  selectControlServiceCall,
  switchControlServiceCall,
  textControlConstraints,
  textControlServiceCall,
  typedConfirmationMatches,
  validateTextControlValue,
} from "../../custom_components/speedport_smart/frontend/controls.js";

const CLIENT_NAME_META = Object.freeze({
  control: true,
  domain: "text",
  entity_id: "text.speedport_client_name",
  translation_key: "client_name",
});
const PRIVACY_SELECT_META = Object.freeze({
  control: true,
  domain: "select",
  entity_id: "select.speedport_internet_privacy_level_control",
  translation_key: "internet_privacy_level_control",
});
const RECEIVER_LED_SELECT_META = Object.freeze({
  control: true,
  domain: "select",
  entity_id: "select.speedport_receiver_led_mode_control",
  translation_key: "receiver_led_mode_control",
});

function selectState(state, options) {
  return {
    state,
    attributes: { options: [...options] },
  };
}

test("switch confirmation keeps the exact state transition the user approved", () => {
  const meta = {
    control: true,
    domain: "switch",
    entity_id: "switch.speedport_wifi",
  };
  assert.deepEqual(switchControlServiceCall(meta, "on", "on"), {
    domain: "switch",
    service: "turn_off",
    data: { entity_id: "switch.speedport_wifi" },
  });
  assert.deepEqual(switchControlServiceCall(meta, "off", "off"), {
    domain: "switch",
    service: "turn_on",
    data: { entity_id: "switch.speedport_wifi" },
  });
  assert.equal(switchControlServiceCall(meta, "on", "off"), undefined);
  assert.equal(
    switchControlServiceCall({ ...meta, control: false }, "on", "on"),
    undefined,
  );
});

test("typed confirmation is fixed to the reviewed main Wi-Fi transition", () => {
  const meta = {
    confirmation: "typed",
    control: true,
    domain: "switch",
    entity_id: "switch.speedport_wifi",
    translation_key: "wifi",
  };

  assert.equal(controlConfirmationPhrase(meta, "on"), "TURN OFF WI-FI");
  assert.equal(controlConfirmationPhrase(meta, "off"), "TURN ON WI-FI");
  assert.equal(
    controlConfirmationPhrase({ ...meta, translation_key: "factory_reset" }, "on"),
    undefined,
  );
  assert.equal(
    controlConfirmationPhrase({ ...meta, confirmation: "confirm" }, "on"),
    undefined,
  );
  assert.equal(typedConfirmationMatches("TURN OFF WI-FI", "TURN OFF WI-FI"), true);
  assert.equal(typedConfirmationMatches("TURN OFF WI-FI", "turn off wi-fi"), false);
  assert.equal(typedConfirmationMatches(undefined, ""), false);
});

test("confirmation policy changes and direction races fail closed", () => {
  const meta = {
    confirmation: "typed",
    control: true,
    domain: "switch",
    entity_id: "switch.speedport_wifi",
    risk: "lockout",
    translation_key: "wifi",
  };
  assert.equal(
    controlConfirmationPolicyMatches(
      meta,
      "on",
      "typed",
      "lockout",
      "TURN OFF WI-FI",
    ),
    true,
  );
  assert.equal(
    controlConfirmationPolicyMatches(
      meta,
      "off",
      "typed",
      "lockout",
      "TURN OFF WI-FI",
    ),
    false,
  );
  assert.equal(
    controlConfirmationPolicyMatches(
      { ...meta, confirmation: "confirm" },
      "on",
      "typed",
      "lockout",
      "TURN OFF WI-FI",
    ),
    false,
  );
  assert.equal(
    controlConfirmationPolicyMatches(
      { ...meta, risk: "destructive" },
      "on",
      "typed",
      "lockout",
      "TURN OFF WI-FI",
    ),
    false,
  );
});

test("reviewed selects emit only the standard Home Assistant service payload", () => {
  const state = selectState("off", SELECT_CONTROL_OPTIONS.internet_privacy_level_control);

  assert.equal(isSupportedSelectControl(PRIVACY_SELECT_META, state), true);
  assert.deepEqual(selectControlOptions(PRIVACY_SELECT_META, state), [
    "off",
    "level_1",
    "level_2",
  ]);
  assert.deepEqual(
    selectControlServiceCall(PRIVACY_SELECT_META, "level_2", "off", state),
    {
      domain: "select",
      service: "select_option",
      data: {
        entity_id: "select.speedport_internet_privacy_level_control",
        option: "level_2",
      },
    },
  );
});

test("receiver LED select uses its separate fixed semantic contract", () => {
  const state = selectState(
    "use_leds",
    SELECT_CONTROL_OPTIONS.receiver_led_mode_control,
  );

  assert.equal(isSupportedSelectControl(RECEIVER_LED_SELECT_META, state), true);
  assert.deepEqual(
    selectControlServiceCall(
      RECEIVER_LED_SELECT_META,
      "off_after_timeout",
      "use_leds",
      state,
    ),
    {
      domain: "select",
      service: "select_option",
      data: {
        entity_id: "select.speedport_receiver_led_mode_control",
        option: "off_after_timeout",
      },
    },
  );
});

test("select allowlist rejects arbitrary entities and option injection", () => {
  const expected = SELECT_CONTROL_OPTIONS.internet_privacy_level_control;
  const valid = selectState("off", expected);
  const candidates = [
    [{ ...PRIVACY_SELECT_META, control: false }, valid],
    [{ ...PRIVACY_SELECT_META, domain: "sensor" }, valid],
    [{ ...PRIVACY_SELECT_META, entity_id: "sensor.speedport_privacy" }, valid],
    [{ ...PRIVACY_SELECT_META, translation_key: "router_raw_endpoint" }, valid],
    [{ ...PRIVACY_SELECT_META, translation_key: "__proto__" }, valid],
    [{ ...PRIVACY_SELECT_META, translation_key: "constructor" }, valid],
    [PRIVACY_SELECT_META, selectState("off", [...expected, "raw_value"])],
    [PRIVACY_SELECT_META, selectState("off", [...expected].reverse())],
    [PRIVACY_SELECT_META, selectState("raw_value", expected)],
  ];

  for (const [meta, state] of candidates) {
    assert.equal(isSupportedSelectControl(meta, state), false);
    assert.equal(
      selectControlServiceCall(meta, "level_1", "off", state),
      undefined,
    );
  }
});

test("select confirmation rejects invalid values and state races", () => {
  const expected = SELECT_CONTROL_OPTIONS.internet_privacy_level_control;
  const unchanged = selectState("off", expected);
  const changed = selectState("level_1", expected);

  assert.equal(
    selectControlServiceCall(PRIVACY_SELECT_META, "raw_value", "off", unchanged),
    undefined,
  );
  assert.equal(
    selectControlServiceCall(PRIVACY_SELECT_META, "level_2", "off", changed),
    undefined,
  );
});

test("frontend and backend use the same client-name contract", () => {
  const constants = readFileSync(
    new URL(
      "../../custom_components/speedport_smart/const.py",
      import.meta.url,
    ),
    "utf8",
  );
  const backendPattern = constants.match(
    /DEVICE_NAME_PATTERN: Final = r"([^"]+)"/,
  )?.[1];
  assert.equal(CLIENT_NAME_PATTERN, backendPattern);
});

test("client rename emits only the exact Home Assistant text service payload", () => {
  assert.deepEqual(
    textControlServiceCall(
      CLIENT_NAME_META,
      "Living-Room",
      "Old-Name",
      "Old-Name",
    ),
    {
      domain: "text",
      service: "set_value",
      data: {
        entity_id: "text.speedport_client_name",
        value: "Living-Room",
      },
    },
  );
});

test("client rename rejects a state changed after confirmation", () => {
  assert.equal(
    textControlServiceCall(
      CLIENT_NAME_META,
      "Living-Room",
      "Old-Name",
      "Changed-Elsewhere",
    ),
    undefined,
  );
});

test("management backoff disables mutations but preserves read-only actions", () => {
  assert.equal(
    managementControlAvailable(CLIENT_NAME_META, "blocked", false),
    false,
  );
  assert.equal(
    managementControlAvailable(
      {
        control: true,
        domain: "button",
        entity_id: "button.speedport_retry_protected_data",
        translation_key: "retry_protected_data",
      },
      "blocked",
      false,
    ),
    true,
  );
  assert.equal(
    managementControlAvailable(
      {
        control: true,
        domain: "button",
        entity_id: "button.speedport_capture_read_only_inventory",
        translation_key: "capture_read_only_inventory",
      },
      "blocked",
      false,
    ),
    true,
  );
  assert.equal(
    managementControlAvailable(CLIENT_NAME_META, "available", true),
    true,
  );
});

test("unavailable reasons accept only reviewed backend codes and safe fallbacks", () => {
  const wpsMeta = {
    control: true,
    domain: "button",
    entity_id: "button.speedport_wps",
    translation_key: "wps",
  };
  const reasons = [
    [
      PRIVACY_SELECT_META,
      selectState("off", SELECT_CONTROL_OPTIONS.internet_privacy_level_control),
      "capability_not_proven",
    ],
    [
      RECEIVER_LED_SELECT_META,
      selectState("use_leds", SELECT_CONTROL_OPTIONS.receiver_led_mode_control),
      "firmware_not_supported",
    ],
    [wpsMeta, { attributes: {}, state: "unknown" }, "disabled_by_setting"],
    [wpsMeta, { attributes: {}, state: "unknown" }, "wps_in_progress"],
  ];

  for (const [meta, state, reason] of reasons) {
    state.attributes.control_unavailable_reason = reason;
    assert.equal(
      controlUnavailableReason(meta, state, "available", true),
      reason,
    );
  }
  assert.equal(
    controlUnavailableReason(
      wpsMeta,
      {
        attributes: { control_unavailable_reason: "router_internal_error" },
        state: "unknown",
      },
      "available",
      true,
    ),
    undefined,
  );
  assert.equal(
    controlUnavailableReason(PRIVACY_SELECT_META, undefined, "available", true),
    "state_readback_unavailable",
  );
  assert.equal(
    controlUnavailableReason(
      PRIVACY_SELECT_META,
      selectState("off", SELECT_CONTROL_OPTIONS.internet_privacy_level_control),
      "blocked",
      false,
    ),
    "management_session_unavailable",
  );
});

test("read-only action bypass rejects colliding entity domains", () => {
  for (const key of [
    "capture_read_only_inventory",
    "retry_protected_data",
  ]) {
    for (const domain of ["switch", "text", "update"]) {
      assert.equal(
        managementControlAvailable(
          {
            control: true,
            domain,
            entity_id: `${domain}.speedport_${key}`,
            translation_key: key,
          },
          "available",
          true,
        ),
        false,
      );
    }
  }
});

test("typed control allowlist rejects missing permission and unrelated text", () => {
  assert.equal(isSupportedTextControl(CLIENT_NAME_META), true);
  assert.equal(
    textControlServiceCall(
      { ...CLIENT_NAME_META, control: false },
      "Hidden",
      "Old-Name",
      "Old-Name",
    ),
    undefined,
  );
  assert.equal(
    textControlServiceCall(
      { ...CLIENT_NAME_META, translation_key: "router_password" },
      "Hidden",
      "Old-Name",
      "Old-Name",
    ),
    undefined,
  );
});

test("client rename validates live Home Assistant constraints", () => {
  const constraints = textControlConstraints({
    attributes: {
      min: 1,
      max: 28,
      pattern: "^[A-Za-z0-9-]{1,28}$",
    },
  });
  assert.deepEqual(constraints, {
    min: 1,
    max: 28,
    pattern: "^[A-Za-z0-9-]{1,28}$",
    invalidPattern: false,
  });
  assert.equal(validateTextControlValue("Kitchen-AP", constraints), undefined);
  assert.equal(validateTextControlValue("-Kitchen-AP-", constraints), undefined);
  assert.equal(
    validateTextControlValue("", constraints),
    "error.text_too_short",
  );
  assert.equal(
    validateTextControlValue("A".repeat(29), constraints),
    "error.text_too_long",
  );
  assert.equal(
    validateTextControlValue("invalid name", constraints),
    "error.text_pattern",
  );
});

test("invalid or oversized patterns fail closed without evaluation", () => {
  const invalid = textControlConstraints({ attributes: { pattern: "[" } });
  assert.equal(
    validateTextControlValue("Name", invalid),
    "error.text_pattern",
  );
  const oversized = textControlConstraints({
    attributes: { pattern: "x".repeat(257) },
  });
  assert.equal(oversized.pattern, undefined);
  assert.equal(
    validateTextControlValue("Name", oversized),
    "error.text_pattern",
  );
});
