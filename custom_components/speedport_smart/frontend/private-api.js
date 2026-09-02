/** Private administrator transport. Never send these payloads over logged WebSockets. */
const PREFIX = "speedport_smart/panel/";
export const PRIVATE_COMMAND_TYPES = Object.freeze([
  "admin_read", "settings/targets", "settings/read", "settings/save", "phonebook_link/finish",
  "maintenance", "call_history", "ip_pbx_refresh", "phonebook_search", "phonebook_contact",
  "action/dect_handset_targets", "action/voip_line_targets", "action/dect_handset_enroll",
  "action/dect_repeater_enroll", "action/dect_handset_set_paging", "action/voip_line_set_active",
  "action/dect_handset_disconnect_targets", "action/dect_repeater_disconnect_targets",
  "action/voip_provider_delete_targets", "action/voip_line_delete_targets",
  "action/ip_pbx_client_delete_targets", "action/phonebook_entry_delete_targets",
  "action/nas_share_delete_targets", "action/dect_handset_disconnect",
  "action/dect_repeater_disconnect", "action/voip_provider_delete", "action/voip_line_delete",
  "action/ip_pbx_client_delete", "action/phonebook_entry_delete", "action/nas_share_delete",
].map((suffix) => PREFIX + suffix));
const COMMANDS = new Set(PRIVATE_COMMAND_TYPES);
const ENTRY_ID = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_REQUEST_BYTES = 256 * 1024;
// A private call export can contain both a complete list and its UTF-8 CSV.
const MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
const SAFE_CODES = new Set([
  "administrator_required", "unauthorized", "invalid_input", "invalid_request", "entry_not_found",
  "entry_not_loaded", "management_unavailable", "query_unavailable", "rate_limited",
  "action_rate_limited", "confirmation_required", "action_busy", "action_rejected",
  "action_unavailable", "action_outcome_unknown", "action_verification_failed", "action_failed",
  "rejected", "command_rejected", "stale_revision", "stale_settings", "invalid_settings",
  "invalid_settings_target", "setting_unavailable", "settings_failed", "settings_busy",
  "settings_inventory_unavailable", "settings_capacity_reached", "settings_target_unavailable",
  "private_transport_required", "private_transport_failed",
]);

class PrivateApiError extends Error {
  constructor(code = "private_transport_failed") {
    super("The private router operation could not be completed. Check the router before retrying.");
    this.name = "PrivateApiError";
    this.code = SAFE_CODES.has(code) ? code : "private_transport_failed";
  }
}

const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

async function boundedJson(response) {
  if (response.redirected || response.headers?.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
    throw new PrivateApiError();
  }
  const declared = response.headers.get("content-length");
  const encoding = response.headers.get("content-encoding")?.trim().toLowerCase();
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) < 1 || Number(declared) > MAX_RESPONSE_BYTES)) {
    await response.body?.cancel().catch(() => {});
    throw new PrivateApiError();
  }
  const reader = response.body?.getReader();
  if (!reader) throw new PrivateApiError();
  const chunks = [];
  let size = 0, complete = false;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array) || size + value.byteLength > MAX_RESPONSE_BYTES) throw new PrivateApiError();
      size += value.byteLength; chunks.push(value);
    }
    complete = true;
    // Browser fetch decompresses the body; Content-Length may describe its
    // compressed representation rather than the bytes exposed by this reader.
    if (size === 0 || ((!encoding || encoding === "identity") && declared !== null && Number(declared) !== size)) throw new PrivateApiError();
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try {
      return JSON.parse(new TextDecoder("utf-8", {fatal:true}).decode(bytes));
    } finally { bytes.fill(0); }
  } finally {
    if (!complete) await reader.cancel().catch(() => {});
    reader.releaseLock();
    for (const chunk of chunks) chunk.fill(0);
    chunks.length = 0;
  }
}

/** One authenticated POST; the caller still owns router/navigation lifecycle checks. */
export async function requestPrivateApi(hass, command) {
  let options;
  try {
    if (hass?.user?.is_admin !== true || typeof hass.user.id !== "string" || !hass.user.id) {
      throw new PrivateApiError("administrator_required");
    }
    if (typeof hass.fetchWithAuth !== "function" || !record(command) ||
        !COMMANDS.has(command.type) || typeof command.entry_id !== "string" ||
        !ENTRY_ID.test(command.entry_id) || Object.hasOwn(command, "id")) throw new PrivateApiError("invalid_input");
    const userId = hass.user.id, entryId = command.entry_id, type = command.type;
    let body = JSON.stringify(command);
    if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) throw new PrivateApiError("invalid_input");
    const serialized = JSON.parse(body);
    if (!record(serialized) || serialized.type !== type || serialized.entry_id !== entryId ||
        Object.hasOwn(serialized, "id")) throw new PrivateApiError("invalid_input");
    options = {method:"POST",headers:{"Content-Type":"application/json","Accept":"application/json"},
      body,cache:"no-store",redirect:"error"};
    body = "";
    const response = await hass.fetchWithAuth(`/api/speedport_smart/private/${encodeURIComponent(entryId)}`, options);
    const envelope = await boundedJson(response);
    if (hass.user?.is_admin !== true || hass.user.id !== userId) throw new PrivateApiError("administrator_required");
    if (!record(envelope)) throw new PrivateApiError();
    if (!response.ok) throw new PrivateApiError(record(envelope.error) ? envelope.error.code : undefined);
    if (Object.keys(envelope).length !== 1 || !Object.hasOwn(envelope, "result")) throw new PrivateApiError();
    return envelope.result;
  } catch (error) {
    // Fetch, JSON and server message text may contain private fields. Never forward them.
    throw error instanceof PrivateApiError ? error : new PrivateApiError();
  } finally {
    if (options) options.body = "";
  }
}
