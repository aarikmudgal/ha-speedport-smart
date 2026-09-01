export function entityAvailability(meta, state) {
  if (!state || state.state === "unavailable") return "unavailable";
  if (state.state === "unknown" && meta?.domain !== "button") return "unknown";
  return "available";
}

export function aggregateAvailability(values) {
  if (values.includes("available")) return "available";
  if (values.includes("unknown")) return "unknown";
  return "unavailable";
}

export function entityDisplayName(meta, state, translatedName, fallbackName) {
  const friendlyName = state?.attributes?.friendly_name;
  return (
    meta?.custom_name ||
    (meta?.translation_key === "port_forward_rule" ? friendlyName : undefined) ||
    translatedName ||
    friendlyName ||
    fallbackName
  );
}
