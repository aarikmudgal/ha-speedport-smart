/** Native router navigation; presentation IDs only, never transport endpoints.
 *
 * Main/sidebar ordering follows the Smart 4R manual (April 2025), pages 73,
 * 115, 179, 191 and 250. Child pages also follow the captured firmware forms.
 * This model does not infer that a displayed feature is supported or writable.
 */

function page(id, title, features = [], options = {}) {
  return Object.freeze({
    id, title,
    ...(options.parentId ? {parentId: options.parentId} : {}),
    features: Object.freeze(features),
    settings: Object.freeze(options.settings || []),
    entityGroups: Object.freeze(options.entityGroups || []),
    readSections: Object.freeze(options.readSections || []),
  });
}

function tab(id, title, icon, pages) {
  return Object.freeze({id, title, icon, pages: Object.freeze(pages)});
}

export const NATIVE_ADMIN_TABS = Object.freeze([
  tab("overview", "Overview", "mdi:home-outline", [
    page("overview", "Overview", [
      "system_initial_setup", "system_router_pass", "system_physical_front_panel_actions",
    ], {entityGroups: ["connection_internet", "wireless_general", "telephony_registration", "system_health"]}),
  ]),
  tab("status", "Status", "mdi:gauge", [
    page("status", "Status", [], {
      entityGroups: ["system_health", "connection_internet", "connection_addressing", "dsl_status", "mobile_connection", "system_firmware"],
      readSections: ["status_technical", "internet_status_technical"],
    }),
  ]),
  tab("internet", "Internet", "mdi:web", [
    page("internet_connection", "Internet connection", ["internet_reconnect", "internet_connection_diagnostics"], {
      entityGroups: ["connection_internet", "bandwidth_interface"], readSections: ["internet_status_technical"],
    }),
    page("internet_access_data", "Access data", ["internet_provider_configuration", "internet_dns_servers"], {parentId: "internet_connection"}),
    page("internet_usb_tethering", "Via cellular device", ["internet_usb_tethering"], {parentId: "internet_connection", entityGroups: ["system_usb_tethering"]}),
    page("internet_ip_information", "IP address information", ["internet_ip_information"], {parentId: "internet_connection", entityGroups: ["connection_addressing"]}),
    page("internet_privacy", "Telekom Privacy Policy", ["internet_privacy"], {parentId: "internet_connection", entityGroups: ["connection_privacy"]}),
    page("internet_receiver", "5G outdoor unit", [
      "internet_hybrid_bonding", "internet_receiver_led", "internet_receiver_mode",
      "internet_receiver_routing_exceptions", "internet_receiver_firmware_update", "internet_receiver_factory_esim_restore",
    ], {entityGroups: ["mobile_connection", "mobile_tunnel", "mobile_radio", "mobile_signal", "mobile_receiver_status", "mobile_receiver_firmware", "mobile_receivers"], readSections: ["receivers"]}),
    page("internet_parental", "Child protection - Time rules", ["internet_parental_controls"], {entityGroups: ["system_parental"]}),
    page("internet_port_forwarding", "Port activation", ["internet_port_forward_toggle", "internet_port_forward_editor", "internet_upnp"], {entityGroups: ["clients_forwarding", "clients_upnp"], readSections: ["port_forward_rules"]}),
    page("internet_port_blocking", "Port blocking", ["internet_port_blocking"], {entityGroups: ["system_security_port_block"], readSections: ["port_block_rules"]}),
    page("internet_ddns", "Dynamic DNS", ["internet_ddns_management", "internet_ddns_configuration_delete"], {entityGroups: ["system_ddns"], readSections: ["ddns_identity"]}),
  ]),
  tab("telephony", "Telephony", "mdi:phone-outline", [
    page("telephony_registration", "Telephony", ["telephony_provider_registration", "telephony_provider_delete", "telephony_number_delete", "telephony_number_activation"], {entityGroups: ["telephony_registration", "telephony_lines", "telephony_voip"], readSections: ["telephony_providers", "telephone_lines"]}),
    page("telephony_assignment", "Phone number assignment", ["telephony_number_assignment"]),
    page("telephony_socket", "Telephone socket", ["telephony_analog_socket_name", "telephony_analog_number_assignment", "telephony_analog_device_type", "telephony_analog_call_waiting"]),
    page("telephony_dect", "DECT base station", ["telephony_dect_base"], {entityGroups: ["telephony_dect", "telephony_dect_base"]}),
    page("telephony_dect_settings", "Settings for DECT", ["telephony_dect_base_pin", "telephony_dect_transmit_power", "telephony_dect_full_eco"], {parentId: "telephony_dect"}),
    page("telephony_dect_handsets", "Registered handsets", ["telephony_dect_handset_enrollment", "telephony_dect_handset_configuration", "telephony_dect_handset_call_waiting", "telephony_dect_handset_disconnect", "telephony_dect_handset_paging"], {parentId: "telephony_dect", entityGroups: ["telephony_dect_scan", "telephony_dect_handsets", "telephony_dect_paging"], readSections: ["dect_handsets"]}),
    page("telephony_dect_repeaters", "Registered repeaters", ["telephony_dect_repeater_enrollment", "telephony_dect_repeater_disconnect"], {parentId: "telephony_dect", entityGroups: ["telephony_dect_repeaters"], readSections: ["dect_repeaters"]}),
    page("telephony_pbx", "IP PBX", ["telephony_ip_pbx", "telephony_ip_phone_enrollment", "telephony_ip_phone_configuration", "telephony_ip_phone_disconnect", "telephony_ip_pbx_client_delete"], {entityGroups: ["telephony_pbx", "telephony_ip"], readSections: ["ip_phones", "pbx_clients"]}),
    page("telephony_number_settings", "Phone number settings", ["telephony_number_use", "telephony_call_encryption", "telephony_hd_voice", "telephony_dialing_delay", "telephony_status_messages", "telephony_automatic_speed_dial"], {entityGroups: ["telephony_call_encryption", "telephony_hd_voice"]}),
    page("telephony_calls", "Call lists", ["telephony_call_lists", "telephony_keypad_functions"], {entityGroups: ["telephony_calls"]}),
    page("telephony_phonebook", "Phone book", ["telephony_phonebook_management", "telephony_phonebook_entry_delete"], {entityGroups: ["telephony_phonebooks"]}),
  ]),
  tab("network", "Network", "mdi:lan", [
    page("network_devices", "Connected devices", [
      "network_client_rename", "network_client_fixed_dhcp", "network_client_inventory", "network_client_manual_add", "network_client_delete",
      "network_mesh_management", "network_mesh_node_rename", "network_mesh_identify", "network_mesh_node_delete", "network_powerline_management", "network_powerline_node_rename",
    ], {entityGroups: ["clients_devices", "wireless_mesh", "wireless_mesh_nodes"], readSections: ["clients", "mesh_nodes", "powerline_nodes"]}),
    page("network_wifi", "Wi-Fi settings"),
    page("network_wifi_basic", "Basic settings", ["network_wifi_main", "network_wifi_schedule"], {parentId: "network_wifi", entityGroups: ["wireless_general", "wireless_schedule"]}),
    page("network_wifi_identity", "Name and encryption", ["network_wifi_identity_security"], {parentId: "network_wifi", settings: ["wifi_identity"], entityGroups: ["wireless_2_4", "wireless_5"], readSections: ["wifi_2_4_identity", "wifi_5_identity"]}),
    page("network_wifi_transmission", "Transmission settings", ["network_wifi_radio_settings"], {parentId: "network_wifi", entityGroups: ["wireless_2_4", "wireless_5", "wireless_radios"]}),
    page("network_wifi_office", "Prioritized Wi-Fi", ["network_wifi_office"], {parentId: "network_wifi", settings: ["wifi_office_settings"], entityGroups: ["wireless_office"], readSections: ["wifi_office_identity"]}),
    page("network_wifi_guest", "Guest access", ["network_wifi_guest", "network_wifi_guest_access_pass"], {parentId: "network_wifi", settings: ["wifi_guest_settings"], entityGroups: ["wireless_guest"], readSections: ["wifi_guest_identity"]}),
    page("network_wifi_environment", "Environment scan", ["network_wifi_environment_scan"], {parentId: "network_wifi"}),
    page("network_wifi_access", "Wi-Fi access (WPS)", ["network_wifi_wps_start", "network_wifi_wps_enablement", "network_wifi_wps_pin_mode", "network_wifi_allowlist"], {entityGroups: ["wireless_wps", "wireless_access"]}),
    page("network_addresses", "Network addresses", ["network_lan_identity", "network_lan_dhcp"], {entityGroups: ["clients_lan", "clients_dhcp"], readSections: ["lan_ipv6_technical"]}),
    page("network_prioritization", "Prioritization", ["network_traffic_prioritization"], {entityGroups: ["system_security_qos"], readSections: ["qos_prioritized_clients"]}),
    page("network_dns_rebind", "DNS rebind protection", ["network_dns_rebind"], {entityGroups: ["system_security_dns"], readSections: ["dns_rebind_exceptions"]}),
    page("network_vpn", "Virtual network (VPN)", ["network_vpn_management"], {entityGroups: ["system_vpn"], readSections: ["vpn_peers"]}),
    page("network_smarthome", "SmartHome", ["network_smarthome_activation"], {entityGroups: ["network_smarthome"]}),
    page("network_storage", "USB storage and printers", ["network_usb_printer_media", "network_usb_safe_remove", "network_nas_shares", "storage_nas_share_delete", "network_media_folders"], {entityGroups: ["system_usb", "system_nas"], readSections: ["usb_devices", "storage_devices", "nas_shares"]}),
  ]),
  tab("system", "System", "mdi:cog-outline", [
    page("system_password", "Change device password", ["system_router_password"], {entityGroups: ["system_security"]}),
    page("system_easysupport", "EasySupport", ["system_easysupport_automatic_setup", "system_easysupport_automatic_firmware", "system_easysupport_remote_support", "system_device_manager"], {entityGroups: ["system_support", "system_easysupport", "system_easysupport_firmware", "system_remote_support"]}),
    page("system_energy", "Energy-saving mode", ["system_front_led_schedule", "system_energy_settings", "system_local_display_settings"], {entityGroups: ["wireless_general", "wireless_radios", "system_local_display"]}),
    page("system_backup", "Back up settings", ["system_configuration_backup", "system_configuration_restore", "system_easysupport_wifi_backup"]),
    page("system_recovery", "Troubleshooting", ["system_reboot", "system_factory_reset", "system_dect_reset", "system_mesh_restart", "system_mesh_reset"], {entityGroups: ["telephony_dect", "wireless_mesh", "wireless_mesh_nodes"], readSections: ["mesh_nodes"]}),
    page("system_firmware", "Firmware updates", ["system_router_firmware", "system_mesh_firmware"], {entityGroups: ["system_firmware", "wireless_mesh_nodes"], readSections: ["mesh_nodes"]}),
    page("system_information", "System information", ["system_information_services", "system_lan_port_status", "system_web_ui_version", "system_messages"], {entityGroups: ["system_health", "system_services", "system_lan_ports"], readSections: ["status_technical"]}),
    page("system_notifications", "Email notification", ["system_email_notifications"]),
    page("system_dsl_modem", "DSL modem", ["system_dsl_modem_mode"], {entityGroups: ["dsl_status", "connection_internet"]}),
    page("system_protection", "Protection functions", ["system_https_access", "system_firewall", "system_safe_mail_allowlist"], {entityGroups: ["system_security"]}),
    page("system_external_modem", "External modem", ["system_external_modem"], {entityGroups: ["connection_internet", "mobile_receiver_status", "clients_lan"]}),
  ]),
]);

// Legacy broad catalog features share these forms. Each belongs to its native
// page, rather than appearing again under guest Wi-Fi or display settings.
const SETTING_PAGE_OWNERS = Object.freeze({
  internet_connection: "internet_access_data",
  wifi_identity: "network_wifi_identity",
  wifi_guest_settings: "network_wifi_guest",
  wifi_office_settings: "network_wifi_office",
});

const TAB_BY_ID = new Map(NATIVE_ADMIN_TABS.map((item) => [item.id, item]));
const PAGE_SET = new Set(NATIVE_ADMIN_TABS.flatMap((item) => item.pages));

/** Resolve a safe navigation target; never accept an arbitrary path or URL. */
export function resolveAdminPage(tabId, pageId) {
  const selectedTab = TAB_BY_ID.get(tabId) || NATIVE_ADMIN_TABS[0];
  let selectedPage = selectedTab.pages.find((item) => item.id === pageId) || selectedTab.pages[0];
  if (["features", "settings", "entityGroups", "readSections"].every((key) => selectedPage[key].length === 0)) {
    selectedPage = selectedTab.pages.find((item) => item.parentId === selectedPage.id) || selectedPage;
  }
  return {tab: selectedTab, page: selectedPage};
}

/** Return only advertised descriptors, keeping availability and contract flags. */
export function adminPageSettings(selectedPage, advertisedSettings, featureLinks) {
  if (!PAGE_SET.has(selectedPage) || !Array.isArray(advertisedSettings)) return [];
  const ids = [...selectedPage.settings];
  for (const featureId of selectedPage.features) {
    const linked = featureLinks?.[featureId]?.ids;
    if (Array.isArray(linked)) ids.push(...linked);
  }
  const descriptors = new Map();
  for (const item of advertisedSettings) {
    if (item && typeof item.id === "string" && !descriptors.has(item.id)) descriptors.set(item.id, item);
  }
  return [...new Set(ids)].filter((id) =>
    descriptors.has(id) && (!SETTING_PAGE_OWNERS[id] || SETTING_PAGE_OWNERS[id] === selectedPage.id)
  ).map((id) => descriptors.get(id));
}

/** Reuse original reviewed feature objects; this never changes action semantics. */
export function adminPageFeatures(selectedPage, existingAdminIA) {
  if (!PAGE_SET.has(selectedPage) || !Array.isArray(existingAdminIA)) return [];
  const features = new Map();
  for (const area of existingAdminIA) {
    if (area.id === "home_assistant") continue;
    for (const section of area.subsections || []) {
      for (const feature of section.features || []) features.set(feature.id, feature);
    }
  }
  return selectedPage.features.filter((id) => features.has(id)).map((id) => features.get(id));
}
