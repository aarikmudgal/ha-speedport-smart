const CLIENT_NAME_CONTROL = "client_name";
export const CLIENT_NAME_PATTERN = "^[A-Za-z0-9-]{1,28}$";
export const SELECT_CONTROL_OPTIONS = Object.freeze({
  internet_privacy_level_control: Object.freeze([
    "off",
    "level_1",
    "level_2",
  ]),
  receiver_led_mode_control: Object.freeze([
    "use_leds",
    "off_after_timeout",
    "disabled",
  ]),
});
const WIFI_TYPED_CONFIRMATIONS = Object.freeze({
  on: "TURN OFF WI-FI",
  off: "TURN ON WI-FI",
});
const READ_ONLY_BUTTON_CONTROLS = new Set([
  "capture_read_only_inventory",
  "retry_protected_data",
]);
const CONTROL_UNAVAILABLE_REASONS = new Set([
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
]);

function finiteInteger(value) {
  const numeric = Number(value);
  return Number.isInteger(numeric) && numeric >= 0 ? numeric : undefined;
}

export function isSupportedTextControl(meta) {
  return Boolean(
    meta?.control === true &&
      meta.domain === "text" &&
      meta.translation_key === CLIENT_NAME_CONTROL &&
      typeof meta.entity_id === "string" &&
      meta.entity_id.startsWith("text."),
  );
}

export function textControlConstraints(state) {
  const attributes = state?.attributes || {};
  const minimum = finiteInteger(attributes.min);
  const maximum = finiteInteger(attributes.max);
  // Only compile the integration's fixed, reviewed pattern. Router state must
  // never be able to introduce an arbitrary regular expression in the panel.
  const pattern =
    attributes.pattern === CLIENT_NAME_PATTERN
      ? CLIENT_NAME_PATTERN
      : undefined;
  const invalidPattern =
    typeof attributes.pattern === "string" &&
    attributes.pattern.length > 0 &&
    attributes.pattern !== CLIENT_NAME_PATTERN;
  return {
    min: minimum,
    max:
      maximum !== undefined &&
      (minimum === undefined || maximum >= minimum)
        ? maximum
        : undefined,
    pattern,
    invalidPattern,
  };
}

export function validateTextControlValue(value, constraints) {
  const draft = String(value ?? "");
  if (constraints.invalidPattern) return "error.text_pattern";
  if (constraints.min !== undefined && draft.length < constraints.min) {
    return "error.text_too_short";
  }
  if (constraints.max !== undefined && draft.length > constraints.max) {
    return "error.text_too_long";
  }
  if (constraints.pattern) {
    try {
      if (!new RegExp(constraints.pattern, "u").test(draft)) {
        return "error.text_pattern";
      }
    } catch (_error) {
      return "error.text_pattern";
    }
  }
  return undefined;
}

export function textControlServiceCall(
  meta,
  value,
  observedState,
  currentState,
) {
  if (
    !isSupportedTextControl(meta) ||
    typeof observedState !== "string" ||
    currentState !== observedState
  ) {
    return undefined;
  }
  return {
    domain: "text",
    service: "set_value",
    data: {
      entity_id: meta.entity_id,
      value: String(value ?? ""),
    },
  };
}

export function selectControlOptions(meta, state) {
  if (
    meta?.control !== true ||
    meta.domain !== "select" ||
    typeof meta.entity_id !== "string" ||
    !meta.entity_id.startsWith("select.")
  ) {
    return undefined;
  }
  const expected = Object.hasOwn(
    SELECT_CONTROL_OPTIONS,
    meta.translation_key,
  )
    ? SELECT_CONTROL_OPTIONS[meta.translation_key]
    : undefined;
  const observed = state?.attributes?.options;
  if (
    !expected ||
    !Array.isArray(observed) ||
    observed.length !== expected.length ||
    !observed.every((option, index) => option === expected[index]) ||
    typeof state?.state !== "string" ||
    !expected.includes(state.state)
  ) {
    return undefined;
  }
  return expected;
}

export function isSupportedSelectControl(meta, state) {
  return selectControlOptions(meta, state) !== undefined;
}

export function selectControlServiceCall(
  meta,
  option,
  observedState,
  currentState,
) {
  const options = selectControlOptions(meta, currentState);
  if (
    typeof option !== "string" ||
    typeof observedState !== "string" ||
    currentState?.state !== observedState ||
    !options?.includes(option)
  ) {
    return undefined;
  }
  return {
    domain: "select",
    service: "select_option",
    data: {
      entity_id: meta.entity_id,
      option,
    },
  };
}

export function managementControlAvailable(
  meta,
  managementState,
  controlsAvailable,
) {
  if (READ_ONLY_BUTTON_CONTROLS.has(meta?.translation_key)) {
    return (
      meta.control === true &&
      meta.domain === "button" &&
      typeof meta.entity_id === "string" &&
      meta.entity_id.startsWith("button.")
    );
  }
  if (typeof controlsAvailable === "boolean") return controlsAvailable;
  return managementState === "available";
}

export function controlUnavailableReason(
  meta,
  state,
  managementState,
  controlsAvailable,
) {
  const observed = state?.attributes?.control_unavailable_reason;
  if (
    typeof observed === "string" &&
    CONTROL_UNAVAILABLE_REASONS.has(observed)
  ) {
    return observed;
  }
  if (!managementControlAvailable(meta, managementState, controlsAvailable)) {
    return "management_session_unavailable";
  }
  if (!state || state.state === "unavailable") {
    return "state_readback_unavailable";
  }
  if (
    (meta?.domain === "select" && !isSupportedSelectControl(meta, state)) ||
    (meta?.domain === "switch" && !["on", "off"].includes(state.state)) ||
    (meta?.domain === "text" && state.state === "unknown")
  ) {
    return "state_readback_unsupported";
  }
  return undefined;
}

export function controlConfirmationPhrase(meta, observedState) {
  if (meta?.confirmation !== "typed") return undefined;
  if (
    meta.control === true &&
    meta.domain === "switch" &&
    meta.translation_key === "wifi" &&
    typeof meta.entity_id === "string" &&
    meta.entity_id.startsWith("switch.") &&
    Object.hasOwn(WIFI_TYPED_CONFIRMATIONS, observedState)
  ) {
    return WIFI_TYPED_CONFIRMATIONS[observedState];
  }
  return undefined;
}

export function typedConfirmationMatches(expectedPhrase, draft) {
  return (
    typeof expectedPhrase === "string" &&
    expectedPhrase.length > 0 &&
    draft === expectedPhrase
  );
}

export function controlConfirmationPolicyMatches(
  meta,
  observedState,
  expectedConfirmation,
  expectedRisk,
  expectedPhrase,
) {
  return (
    meta?.confirmation === expectedConfirmation &&
    meta?.risk === expectedRisk &&
    controlConfirmationPhrase(meta, observedState) === expectedPhrase
  );
}

export function switchControlServiceCall(meta, observedState, currentState) {
  if (
    meta?.control !== true ||
    meta.domain !== "switch" ||
    typeof meta.entity_id !== "string" ||
    !meta.entity_id.startsWith("switch.") ||
    !["on", "off"].includes(observedState) ||
    currentState !== observedState
  ) {
    return undefined;
  }
  return {
    domain: "switch",
    service: observedState === "on" ? "turn_off" : "turn_on",
    data: { entity_id: meta.entity_id },
  };
}
