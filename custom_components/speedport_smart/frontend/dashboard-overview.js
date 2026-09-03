// Read-only overview: only entities already advertised to this Home Assistant user.
const READ_DOMAINS = new Set(["sensor", "binary_sensor", "device_tracker"]);
const ENTITY_ID = /^(sensor|binary_sensor|device_tracker)\.[a-z0-9_]+$/;
const INVALID_STATES = new Set(["", "unknown", "unavailable", "none", "null"]);
const LINK_SPEED_UNITS = Object.freeze({
  "bit/s": 1, bps: 1, "kbit/s": 1e3, kbps: 1e3,
  "Mbit/s": 1e6, Mbps: 1e6, "Gbit/s": 1e9, Gbps: 1e9, "Tbit/s": 1e12,
  "B/s": 8, "kB/s": 8e3, "MB/s": 8e6, "GB/s": 8e9,
});

function linkBitsPerSecond(value, unit = "bit/s") {
  if (!Object.hasOwn(LINK_SPEED_UNITS, unit) || !["string", "number"].includes(typeof value)) return null;
  if (typeof value === "string" && (value.length > 64 || !/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim()))) return null;
  const speed = Number(value) * LINK_SPEED_UNITS[unit];
  return Number.isFinite(speed) && speed > 0 && speed <= Number.MAX_SAFE_INTEGER ? speed : null;
}

function formatLinkSpeed(speed) {
  const units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s", "Tbit/s"];
  const index = Math.min(units.length - 1, Math.max(0, Math.floor(Math.log10(speed) / 3)));
  return `${new Intl.NumberFormat("en", {maximumFractionDigits: 2}).format(speed / 1000 ** index)} ${units[index]}`;
}

function clientLinkSpeed(meta, state, entities, states) {
  const findSpeed = (key) => {
    const child = entities.find((candidate) => candidate.domain === "sensor" && candidate.translation_key === key &&
      candidate.child_device?.kind === "client" && candidate.child_device.device_id === meta.child_device.device_id);
    const value = currentState(states, child);
    // Sensor units are required. The tracker attribute is explicitly named in bits/s.
    return typeof value?.attributes?.unit_of_measurement === "string"
      ? linkBitsPerSecond(value.state, value.attributes.unit_of_measurement) : null;
  };
  const download = findSpeed("download_link_speed");
  const upload = findSpeed("upload_link_speed");
  if (download !== null && upload !== null && download === upload) {
    const label = formatLinkSpeed(download);
    return {label, description: `Link speed ${label}`};
  }
  if (download !== null || upload !== null) {
    const directions = [["↓", "download", download], ["↑", "upload", upload]].filter(([, , value]) => value !== null);
    return {
      label: directions.map(([arrow, , value]) => `${arrow} ${formatLinkSpeed(value)}`).join(" · "),
      description: `Link speed ${directions.map(([, direction, value]) => `${direction} ${formatLinkSpeed(value)}`).join(", ")}`,
    };
  }
  const generic = findSpeed("link_speed") ?? linkBitsPerSecond(state.attributes?.link_speed_bps);
  if (generic === null) return {label: "Link speed not reported", description: "Link speed not reported"};
  const label = formatLinkSpeed(generic);
  return {label, description: `Link speed ${label}`};
}

function escape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[character]);
}

function currentState(states, meta) {
  return states instanceof Map ? states.get(meta?.entity_id) : states?.[meta?.entity_id];
}

function available(state, numeric = false) {
  const raw = state?.state;
  if (typeof raw !== "string" && typeof raw !== "number") return false;
  if (raw === undefined || raw === null || INVALID_STATES.has(String(raw).trim().toLowerCase())) return false;
  return !numeric || (typeof raw !== "boolean" && Number.isFinite(Number(raw)));
}

function fallbackFormat(state) {
  const unit = state.attributes?.unit_of_measurement;
  return unit ? `${state.state} ${unit}` : String(state.state);
}

/** Render supplied metadata and current states; trafficMarkup must be trusted local graph HTML. */
export function renderDashboardOverview({router, states = {}, trafficMarkup = "", formatState = fallbackFormat, entityName} = {}) {
  const seen = new Set();
  const entities = (Array.isArray(router?.entities) ? router.entities : []).filter((meta) => {
    if (!meta || !READ_DOMAINS.has(meta.domain) || !ENTITY_ID.test(meta.entity_id) ||
        !meta.entity_id.startsWith(`${meta.domain}.`) || meta.control || meta.control_supported ||
        meta.disabled || meta.disabled_by || seen.has(meta.entity_id)) return false;
    seen.add(meta.entity_id);
    return true;
  });
  const roots = entities.filter((meta) => !meta.child_device);
  const find = (key) => roots.find((meta) => meta.translation_key === key);
  const labelFor = (meta, state, label) => entityName?.(meta, state) || meta?.custom_name || state?.attributes?.friendly_name || label;
  const metric = (key, label, {numeric = true, prominent = false} = {}) => {
    const meta = find(key);
    if (!meta) return "";
    const state = currentState(states, meta);
    const valid = available(state, numeric);
    const value = valid ? formatState(state, meta) : state?.state === "unknown" ? "Unknown" : "Unavailable";
    return `<button type="button" class="overview-metric${prominent ? " overview-metric-large" : ""}${valid ? "" : " is-unavailable"}"
      data-more-info="${escape(meta.entity_id)}" aria-label="${escape(labelFor(meta, state, label))}: ${escape(value)}">
      <span>${escape(label)}</span><strong>${escape(value)}</strong></button>`;
  };
  const has = (keys) => keys.some((key) => find(key));
  const degraded = (keys) => keys.some((key) => {
    const meta = find(key);
    return meta && !available(currentState(states, meta));
  }) ? '<span class="overview-degraded">Some data unavailable</span>' : "";
  const header = (title, icon, subtitle = "", badge = "") => `<header class="overview-card-heading">
    <span class="overview-heading-icon" aria-hidden="true"><ha-icon icon="${icon}"></ha-icon></span>
    <div><h2>${escape(title)}</h2>${subtitle ? `<p>${escape(subtitle)}</p>` : ""}</div>${badge}</header>`;
  const band = (suffix, title) => {
    const keys = [`wifi_${suffix}_enabled`, `wifi_${suffix}_clients`, `wifi_${suffix}_channel`];
    if (!has(keys)) return "";
    const enabled = find(keys[0]);
    const state = currentState(states, enabled);
    const status = state?.state === "on" ? "On" : state?.state === "off" ? "Off" : "Status unavailable";
    return `<section class="overview-wifi-band" aria-label="${title} Wi-Fi">
      <div class="overview-band-heading"><h3>${title}</h3>${enabled ? `<button type="button" class="overview-state${available(state) ? "" : " is-unavailable"}"
        data-more-info="${escape(enabled.entity_id)}" aria-label="${title} Wi-Fi: ${status}">${status}</button>` : ""}</div>
      <div class="overview-metrics">${metric(keys[1], "Connected devices", {prominent: true})}${metric(keys[2], "Channel")}</div>
      ${degraded(keys)}</section>`;
  };
  const wifi = [band("2_4", "2.4 GHz"), band("5", "5 GHz")].filter(Boolean);
  const wifiCard = wifi.length ? `<section class="overview-card overview-wifi" data-overview-section="wifi">
    ${header("Wi-Fi", "mdi:wifi", "Your wireless network")}
    <div class="overview-wifi-bands">${wifi.join("")}</div></section>` : "";

  const dslKeys = ["dsl_connected", "dsl_downstream", "dsl_upstream", "wan_download_capacity", "wan_upload_capacity"];
  const dslCard = has(dslKeys) ? `<section class="overview-card" data-overview-section="dsl">
    ${header("DSL & line capacity", "mdi:transit-connection-variant", "Link speed, not current traffic", degraded(dslKeys))}
    <div class="overview-metrics">${metric("dsl_connected", "DSL status", {numeric: false})}
      ${metric("dsl_downstream", "Download sync", {prominent: true})}${metric("dsl_upstream", "Upload sync", {prominent: true})}</div>
    ${has(["wan_download_capacity", "wan_upload_capacity"]) ? `<div class="overview-metrics overview-secondary-metrics">
      ${metric("wan_download_capacity", "WAN download capacity")}${metric("wan_upload_capacity", "WAN upload capacity")}</div>` : ""}
    </section>` : "";

  const mobileKeys = ["mobile_connected", "mobile_network_type", "mobile_operator", "mobile_rsrp", "mobile_rsrq", "mobile_sinr", "mobile_band", "mobile_frequency", "mobile_lte_signal", "mobile_lte_band", "mobile_nr_signal", "mobile_nr_band", "receiver_model"];
  const mobileCard = has(mobileKeys) ? `<section class="overview-card" data-overview-section="mobile">
    ${header("Mobile receiver", "mdi:antenna", "Cellular connection", degraded(mobileKeys))}
    <div class="overview-metrics">${metric("mobile_connected", "Connection", {numeric: false})}
      ${metric("mobile_network_type", "Network", {numeric: false})}
      ${metric("mobile_rsrp", "Signal · RSRP", {prominent: true})}${metric("mobile_sinr", "Signal quality · SINR")}${metric("mobile_rsrq", "Signal quality · RSRQ")}
      ${metric("mobile_lte_signal", "LTE signal strength", {prominent: true})}
      ${!find("mobile_rsrp") ? metric("mobile_nr_signal", "5G signal", {prominent: true}) : ""}
      ${metric("mobile_lte_band", "LTE band", {numeric: false})}
      ${metric("mobile_band", "Band", {numeric: false})}${!find("mobile_band") ? metric("mobile_nr_band", "5G band", {numeric: false}) : ""}
      ${metric("mobile_frequency", "Frequency")}${metric("mobile_operator", "Operator", {numeric: false})}
      ${metric("receiver_model", "Receiver", {numeric: false})}</div></section>` : "";

  // Medium is canonical runtime tracker data. Never infer Ethernet from absent Wi-Fi fields.
  const clients = entities.filter((meta) => meta.domain === "device_tracker" && meta.child_device?.kind === "client");
  const wired = [];
  const wiredIds = new Set();
  for (const meta of clients) {
    const state = currentState(states, meta);
    const id = meta.child_device.device_id;
    if (typeof id !== "string" || !id || wiredIds.has(id) || state?.attributes?.medium !== "lan") continue;
    wiredIds.add(id);
    wired.push({meta, state});
  }
  wired.sort((a, b) => String(a.meta.child_device.name || "").localeCompare(String(b.meta.child_device.name || "")));
  const connected = wired.filter(({state}) => state?.state === "home").length;
  const unknown = wired.some(({state}) => !["home", "not_home"].includes(state?.state));
  const lanCard = clients.length || find("lan_linked_ports") ? `<section class="overview-card overview-lan" data-overview-section="lan">
    ${header("Wired devices", "mdi:lan", wired.length ? `${connected} connected · ${wired.length} reported${unknown ? " · some status unavailable" : ""}` : "Wired-device details not reported")}
    ${metric("lan_linked_ports", "Linked LAN ports")}
    ${wired.length ? `<ul class="overview-device-list">${wired.map(({meta, state}) => {
      const name = meta.child_device.name || labelFor(meta, state, "Network device");
      const online = state.state === "home";
      const status = online ? "Connected" : state.state === "not_home" ? "Disconnected" : "Unavailable";
      const speed = online ? clientLinkSpeed(meta, state, entities, states) : null;
      return `<li><button type="button" data-more-info="${escape(meta.entity_id)}" class="overview-device" aria-label="${escape(name)}: ${status}${speed ? `; ${escape(speed.description)}` : ""}">
        <ha-icon icon="mdi:ethernet" aria-hidden="true"></ha-icon><span>${escape(name)}</span>
        <i class="overview-connection-dot${online ? " is-online" : ""}" title="${status}" aria-hidden="true"></i>
        <small class="overview-device-link-speed"${online ? ' title="Negotiated link speed, not current traffic"' : ""}>${escape(speed?.label || status)}</small></button></li>`;
    }).join("")}</ul>` : '<p class="overview-empty">Only devices explicitly reported as Ethernet appear here.</p>'}</section>` : "";
  const cards = [wifiCard, dslCard, mobileCard, lanCard].filter(Boolean).join("");
  return `<div class="dashboard-overview">
    ${trafficMarkup ? `<section class="overview-traffic" aria-label="Live WAN traffic">${trafficMarkup}</section>` : ""}
    ${cards ? `<div class="overview-grid">${cards}</div>` : '<p class="overview-empty">No overview telemetry is available for this router yet.</p>'}
    </div>`;
}

export const DASHBOARD_OVERVIEW_STYLES = `
  .dashboard-overview { display: grid; gap: 20px; min-width: 0; width: 100%; }
  .dashboard-overview * { box-sizing: border-box; }
  .overview-traffic { width: 100%; min-width: 0; }
  .overview-grid { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; min-width: 0; }
  .overview-grid > .overview-card { flex: 1 1 380px; max-width: 100%; }
  .overview-card { min-width: 0; padding: clamp(18px, 2vw, 28px); border: 1px solid var(--divider-color); border-radius: 22px; background: var(--ha-card-background, var(--card-background-color)); color: var(--primary-text-color); }
  .overview-card-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
  .overview-card-heading > div { flex: 1; min-width: 0; }
  .overview-card h2 { font-size: 18px; line-height: 1.3; margin: 0; font-weight: 650; }
  .overview-card h3 { font-size: 17px; margin: 0; font-weight: 650; }
  .overview-card-heading p, .overview-empty { font-size: 13px; line-height: 1.5; color: var(--secondary-text-color); margin: 5px 0 0; }
  .overview-heading-icon { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 14px; color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 9%, transparent); }
  .overview-grid > .overview-wifi { flex-basis: 100%; }
  .overview-wifi-bands { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 16px; }
  .overview-wifi-band { border: 1px solid var(--divider-color); border-radius: 16px; padding: 18px; min-width: 0; }
  .overview-band-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
  .overview-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 138px), 1fr)); gap: 8px 16px; }
  .overview-metric { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; text-align: start; min-width: 0; padding: 10px 0; border: 0; background: none; color: inherit; cursor: pointer; font: inherit; }
  .overview-metric > span { color: var(--secondary-text-color); font-size: 12px; line-height: 1.4; }
  .overview-metric strong { font-size: 17px; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
  .overview-metric-large strong { font-size: clamp(20px, 2.1vw, 28px); letter-spacing: -.025em; }
  .overview-secondary-metrics { border-top: 1px solid var(--divider-color); margin-top: 10px; padding-top: 8px; }
  .overview-state { font: inherit; color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 999px; background: none; padding: 5px 12px; font-size: 12px; cursor: pointer; }
  .overview-degraded { color: var(--warning-color, var(--secondary-text-color)); font-size: 11px; line-height: 1.4; }
  .overview-metric.is-unavailable strong, .overview-state.is-unavailable { color: var(--secondary-text-color); }
  .overview-device-list { list-style: none; margin: 10px 0 0; padding: 0; max-height: 340px; overflow: auto; scrollbar-width: thin; }
  .overview-device-list li + li { border-top: 1px solid var(--divider-color); }
  .overview-device { display: flex; align-items: center; width: 100%; min-width: 0; gap: 12px; padding: 14px 0; border: 0; background: none; text-align: start; color: inherit; cursor: pointer; font: inherit; }
  .overview-device > span { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: 14px; }
  .overview-device > ha-icon { color: var(--secondary-text-color); flex: none; }
  .overview-device small { color: var(--secondary-text-color); font-size: 12px; }
  .overview-device-link-speed { text-align: end; overflow-wrap: anywhere; max-width: 60%; font-variant-numeric: tabular-nums; }
  .overview-connection-dot { flex: none; width: 6px; height: 6px; border-radius: 50%; background: var(--secondary-text-color); }
  .overview-connection-dot.is-online { background: var(--success-color, var(--primary-color)); }
  .dashboard-overview button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 4px; border-radius: 6px; }
  @media (hover: hover) { .dashboard-overview button:hover { color: var(--primary-color); } }
  @media (max-width: 600px) { .dashboard-overview, .overview-grid { gap: 14px; } .overview-card { border-radius: 18px; } .overview-wifi-band { padding: 14px; } }
`;
