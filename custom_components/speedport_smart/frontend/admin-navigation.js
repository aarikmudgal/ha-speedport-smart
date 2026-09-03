/** Native router navigation; presentation IDs only, never transport endpoints.
 *
 * Main/sidebar ordering follows the observed, authenticated Smart 4R sitemap.
 * Native paths document parity only; they must never select an API endpoint.
 * This model does not infer that a displayed feature is supported or writable.
 */

// Earlier leaf pages completed from the authenticated navigation audit. Paths
// outside /html/content remain absolute rather than being silently rewritten.
const NATIVE_PAGE_PATHS = Object.freeze({
  overview: "/html/content/overview/index.html",
  status: "/html/login/status.html",
  internet_access_data: "internet/connection.html",
  internet_usb_tethering: "internet/usb_tethering.html",
  internet_ip_information: "internet/con_ipdata.html",
  internet_privacy: "internet/con_privacy.html",
  internet_parental: "internet/chd_timerules.html",
  internet_port_forwarding: "internet/portforwarding.html",
  internet_port_blocking: "internet/portblocking.html",
  internet_ddns: "internet/dyn_dns.html",
  telephony_registration: "phone/phone_internet.html",
  telephony_assignment: "phone/phone_number.html",
  telephony_socket: "phone/phone_analog.html",
  telephony_dect_settings: "phone/phone_dect_settings.html",
  telephony_dect_handsets: "phone/phone_dect_mobiles.html",
  telephony_dect_repeaters: "phone/phone_dect_repeater.html",
  telephony_pbx: "phone/phone_ippbx.html",
  network_devices: "network/devices.html",
  network_wifi_basic: "network/wlan_basic.html",
  network_wifi_identity: "network/wlan_name_enc.html",
  network_wifi_transmission: "network/wlan_sendset.html",
  network_wifi_office: "network/wlan_office.html",
  network_wifi_guest: "network/wlan_guest.html",
  network_wifi_environment: "network/wlan_environ.html",
  network_dns_rebind: "network/dns_rebind.html",
  network_vpn: "network/vpn.html",
  network_smarthome: "network/smarthome.html",
  system_password: "config/change_password.html",
  system_easysupport: "config/easy_support.html",
  system_energy: "config/energy.html",
  system_backup: "config/save_settings.html",
  system_notifications: "config/notify.html",
  system_dsl_modem: "config/internal_modem.html",
  system_protection: "config/protect.html",
  system_external_modem: "config/external_modem.html",
});

function page(id, title, features = [], options = {}) {
  const nativePath = options.nativePath || NATIVE_PAGE_PATHS[id];
  return Object.freeze({
    id, title,
    ...(options.parentId ? {parentId: options.parentId} : {}),
    ...(nativePath ? {nativePath} : {}),
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
    page("internet_connection", "Internet connection"),
    page("internet_access_data", "Access data", ["internet_provider_configuration", "internet_dns_servers", "internet_reconnect", "internet_connection_diagnostics"], {parentId: "internet_connection", entityGroups: ["connection_internet", "bandwidth_interface"], readSections: ["internet_status_technical"]}),
    page("internet_usb_tethering", "Via cellular device", ["internet_usb_tethering"], {parentId: "internet_connection", entityGroups: ["system_usb_tethering"]}),
    page("internet_ip_information", "IP address information", ["internet_ip_information"], {parentId: "internet_connection", entityGroups: ["connection_addressing"]}),
    page("internet_privacy", "Telekom Privacy Policy", ["internet_privacy"], {parentId: "internet_connection", entityGroups: ["connection_privacy"]}),
    page("internet_receiver", "5G outdoor unit"),
    page("internet_receiver_connection", "Connection", [], {parentId: "internet_receiver", nativePath: "internet/lte.html", entityGroups: ["mobile_connection", "mobile_tunnel", "mobile_radio", "mobile_signal", "mobile_receiver_status", "mobile_receivers"], readSections: ["receivers"]}),
    page("internet_receiver_mode", "Mode settings", ["internet_hybrid_bonding", "internet_receiver_led", "internet_receiver_mode"], {parentId: "internet_receiver", nativePath: "internet/lte_mode.html"}),
    page("internet_receiver_firmware", "Firmware and reset", ["internet_receiver_firmware_update", "internet_receiver_factory_esim_restore"], {parentId: "internet_receiver", nativePath: "internet/lte_firmware.html", entityGroups: ["mobile_receiver_firmware"]}),
    page("internet_receiver_exceptions", "Routing exceptions", ["internet_receiver_routing_exceptions"], {parentId: "internet_receiver", nativePath: "internet/except.html"}),
    page("internet_parental", "Child protection - Time rules", ["internet_parental_controls", "system_local_display_settings"], {entityGroups: ["system_parental", "system_local_display"]}),
    page("internet_port_forwarding", "Port activation", ["internet_port_forward_toggle", "internet_port_forward_editor", "internet_upnp"], {entityGroups: ["clients_forwarding", "clients_upnp"], readSections: ["port_forward_rules"]}),
    page("internet_port_blocking", "Port blocking", ["internet_port_blocking"], {entityGroups: ["system_security_port_block"], readSections: ["port_block_rules"]}),
    page("internet_ddns", "Dynamic DNS", ["internet_ddns_management", "internet_ddns_configuration_delete"], {entityGroups: ["system_ddns"], readSections: ["ddns_identity"]}),
  ]),
  tab("telephony", "Telephony", "mdi:phone-outline", [
    page("telephony_registration", "Telephony", ["telephony_provider_registration", "telephony_provider_delete", "telephony_number_delete", "telephony_number_activation"], {entityGroups: ["telephony_registration", "telephony_lines", "telephony_voip"], readSections: ["telephony_providers", "telephone_lines"]}),
    page("telephony_assignment", "Phone number assignment", ["telephony_number_assignment"]),
    page("telephony_socket", "Telephone socket", ["telephony_analog_socket_name", "telephony_analog_number_assignment", "telephony_analog_device_type", "telephony_analog_call_waiting"]),
    page("telephony_dect", "DECT base station"),
    page("telephony_dect_settings", "Settings for DECT", ["telephony_dect_base", "telephony_dect_base_pin", "telephony_dect_transmit_power", "telephony_dect_full_eco"], {parentId: "telephony_dect", entityGroups: ["telephony_dect", "telephony_dect_base"]}),
    page("telephony_dect_handsets", "Registered handsets", ["telephony_dect_handset_enrollment", "telephony_dect_handset_configuration", "telephony_dect_handset_call_waiting", "telephony_dect_handset_disconnect", "telephony_dect_handset_paging"], {parentId: "telephony_dect", entityGroups: ["telephony_dect_scan", "telephony_dect_handsets", "telephony_dect_paging"], readSections: ["dect_handsets"]}),
    page("telephony_dect_repeaters", "Registered repeaters", ["telephony_dect_repeater_enrollment", "telephony_dect_repeater_disconnect"], {parentId: "telephony_dect", entityGroups: ["telephony_dect_repeaters"], readSections: ["dect_repeaters"]}),
    page("telephony_pbx", "IP PBX", ["telephony_ip_pbx", "telephony_ip_phone_enrollment", "telephony_ip_phone_configuration", "telephony_ip_phone_disconnect", "telephony_ip_pbx_client_delete"], {entityGroups: ["telephony_pbx", "telephony_ip"], readSections: ["ip_phones", "pbx_clients"]}),
    page("telephony_number_settings", "Phone number settings"),
    page("telephony_number_usage", "Phone number usage", ["telephony_number_use"], {parentId: "telephony_number_settings", nativePath: "phone/phone_lineset.html"}),
    page("telephony_number_security", "Security settings", ["telephony_call_encryption"], {parentId: "telephony_number_settings", nativePath: "phone/phone_linevosip.html", entityGroups: ["telephony_call_encryption"]}),
    page("telephony_number_hd_voice", "High voice quality (HD Voice)", ["telephony_hd_voice"], {parentId: "telephony_number_settings", nativePath: "phone/phone_linehdvoice.html", entityGroups: ["telephony_hd_voice"]}),
    page("telephony_number_dial_delay", "Dial delay", ["telephony_dialing_delay"], {parentId: "telephony_number_settings", nativePath: "phone/phone_linedialdelay.html"}),
    page("telephony_number_status_message", "Status message", ["telephony_status_messages"], {parentId: "telephony_number_settings", nativePath: "phone/phone_linestataudio.html"}),
    page("telephony_number_speeddial", "Number memory (Speeddial)", ["telephony_automatic_speed_dial"], {parentId: "telephony_number_settings", nativePath: "phone/phone_linespeeddial.html"}),
    page("telephony_calls", "Call lists"),
    page("telephony_calls_missed", "Missed calls", ["telephony_call_lists", "telephony_keypad_functions"], {parentId: "telephony_calls", nativePath: "phone/phone_call_missed.html", entityGroups: ["telephony_calls"]}),
    page("telephony_calls_taken", "Received calls", [], {parentId: "telephony_calls", nativePath: "phone/phone_call_taken.html", settings: ["call_history_clear_taken"], entityGroups: ["telephony_calls"]}),
    page("telephony_calls_dialed", "Dialed outgoing calls", [], {parentId: "telephony_calls", nativePath: "phone/phone_call_dialed.html", settings: ["call_history_clear_dialed"], entityGroups: ["telephony_calls"]}),
    page("telephony_phonebook", "Phone book"),
    page("telephony_phonebook_basic", "Basic settings", [], {parentId: "telephony_phonebook", nativePath: "phone/phone_book_basic.html", settings: ["telephony_phonebook_update_interval", "telephony_phonebook_rename", "telephony_phonebook_delete", "telephony_phonebook_disconnect", "telephony_phonebook_account_create", "telephony_phonebook_link"], entityGroups: ["telephony_phonebooks"]}),
    page("telephony_phonebook_entries", "Entries", ["telephony_phonebook_management", "telephony_phonebook_entry_delete"], {parentId: "telephony_phonebook", nativePath: "phone/phone_book_entries.html"}),
    page("telephony_phonebook_assignment", "Assignment", [], {parentId: "telephony_phonebook", nativePath: "phone/phone_book_assign.html", settings: ["telephony_handset_phonebook"]}),
  ]),
  tab("network", "Network", "mdi:lan", [
    page("network_devices", "Connected devices", [
      "network_client_rename", "network_client_fixed_dhcp", "network_client_inventory", "network_client_manual_add", "network_client_delete",
      "network_mesh_management", "network_mesh_node_rename", "network_mesh_identify", "network_mesh_node_delete", "network_powerline_management", "network_powerline_node_rename",
    ], {entityGroups: ["clients_devices", "wireless_mesh", "wireless_mesh_nodes"], readSections: ["clients", "mesh_nodes", "powerline_nodes"]}),
    page("network_wifi", "Wi-Fi settings"),
    page("network_wifi_basic", "Basic settings", ["network_wifi_main", "network_wifi_schedule"], {parentId: "network_wifi", entityGroups: ["wireless_general", "wireless_schedule"]}),
    page("network_wifi_identity", "Name and encryption", ["network_wifi_identity_security"], {parentId: "network_wifi", settings: ["wifi_identity"], entityGroups: ["wireless_2_4", "wireless_5"], readSections: ["wifi_2_4_identity", "wifi_5_identity"]}),
    page("network_wifi_transmission", "Send settings", ["network_wifi_radio_settings"], {parentId: "network_wifi", entityGroups: ["wireless_2_4", "wireless_5", "wireless_radios"]}),
    page("network_wifi_office", "Prioritized Wi-Fi", ["network_wifi_office"], {parentId: "network_wifi", settings: ["wifi_office_settings"], entityGroups: ["wireless_office"], readSections: ["wifi_office_identity"]}),
    page("network_wifi_guest", "Guest access", ["network_wifi_guest", "network_wifi_guest_access_pass"], {parentId: "network_wifi", settings: ["wifi_guest_settings"], entityGroups: ["wireless_guest"], readSections: ["wifi_guest_identity"]}),
    page("network_wifi_environment", "Environment scan", ["network_wifi_environment_scan"], {parentId: "network_wifi"}),
    page("network_wifi_access", "Wi-Fi access (WPS)"),
    page("network_wifi_wps", "Add device via WPS", ["network_wifi_wps_start", "network_wifi_wps_enablement", "network_wifi_wps_pin_mode"], {parentId: "network_wifi_access", nativePath: "network/wlan_wps.html", entityGroups: ["wireless_wps"]}),
    page("network_wifi_access_limit", "Access limit", ["network_wifi_allowlist"], {parentId: "network_wifi_access", nativePath: "network/wlan_access.html", entityGroups: ["wireless_access"]}),
    page("network_addresses", "Network addresses"),
    page("network_lan_addresses", "Router addresses", ["network_lan_identity"], {parentId: "network_addresses", nativePath: "network/lan.html", entityGroups: ["clients_lan"], readSections: ["lan_ipv6_technical"]}),
    page("network_lan_dhcp", "Address assignment (DHCP)", ["network_lan_dhcp"], {parentId: "network_addresses", nativePath: "network/dhcp.html", entityGroups: ["clients_dhcp"]}),
    page("network_prioritization", "Prioritization", ["network_traffic_prioritization"], {nativePath: "network/qos.html", entityGroups: ["system_security_qos"], readSections: ["qos_prioritized_clients"]}),
    page("network_dns_rebind", "DNS rebind protection", ["network_dns_rebind"], {entityGroups: ["system_security_dns"], readSections: ["dns_rebind_exceptions"]}),
    page("network_vpn", "Virtual network (VPN)", ["network_vpn_management"], {entityGroups: ["system_vpn"], readSections: ["vpn_peers"]}),
    page("network_smarthome", "SmartHome", ["network_smarthome_activation"], {entityGroups: ["network_smarthome"]}),
    page("network_storage", "USB storage and printers"),
    page("network_storage_usb", "USB port", ["network_usb_printer_media", "network_usb_safe_remove"], {parentId: "network_storage", nativePath: "network/nas_overview.html", entityGroups: ["system_usb"], readSections: ["usb_devices", "storage_devices"]}),
    page("network_storage_sharing", "Sharing", ["network_nas_shares", "storage_nas_share_delete"], {parentId: "network_storage", nativePath: "network/nas_share.html", entityGroups: ["system_nas"], readSections: ["nas_shares"]}),
    page("network_storage_workgroup", "Workgroup", [], {parentId: "network_storage", nativePath: "network/nas_workgroup.html", settings: ["nas_workgroup"]}),
    page("network_storage_media", "Media playback", ["network_media_folders"], {parentId: "network_storage", nativePath: "network/nas_mediareplay.html"}),
  ]),
  tab("system", "System", "mdi:cog-outline", [
    page("system_password", "Change device password", ["system_router_password"], {entityGroups: ["system_security"]}),
    page("system_easysupport", "EasySupport", ["system_easysupport_automatic_setup", "system_easysupport_automatic_firmware", "system_easysupport_remote_support", "system_device_manager"], {entityGroups: ["system_support", "system_easysupport", "system_easysupport_firmware", "system_remote_support"]}),
    page("system_energy", "Energy-saving mode", ["system_front_led_schedule", "system_energy_settings"], {entityGroups: ["wireless_general", "wireless_radios"]}),
    page("system_backup", "Save settings", ["system_configuration_backup", "system_configuration_restore", "system_easysupport_wifi_backup"]),
    page("system_recovery", "Problem handling"),
    page("system_recovery_restart", "Restart", ["system_reboot"], {parentId: "system_recovery", nativePath: "config/restart.html"}),
    page("system_recovery_reset", "Reset", ["system_factory_reset"], {parentId: "system_recovery", nativePath: "config/reset.html"}),
    page("system_recovery_dect", "DECT", ["system_dect_reset"], {parentId: "system_recovery", nativePath: "config/problem_handling_dect.html", entityGroups: ["telephony_dect"]}),
    page("system_recovery_mesh", "Mesh", ["system_mesh_restart", "system_mesh_reset"], {parentId: "system_recovery", nativePath: "config/problem_handling_mesh.html", entityGroups: ["wireless_mesh", "wireless_mesh_nodes"], readSections: ["mesh_nodes"]}),
    page("system_firmware", "Firmware updates"),
    page("system_firmware_speedport", "Speedport", ["system_router_firmware"], {parentId: "system_firmware", nativePath: "config/check_for_updates.html", entityGroups: ["system_firmware"]}),
    page("system_firmware_mesh", "Mesh", ["system_mesh_firmware"], {parentId: "system_firmware", nativePath: "config/check_for_updates_mesh.html", entityGroups: ["wireless_mesh_nodes"], readSections: ["mesh_nodes"]}),
    page("system_information", "System information"),
    page("system_information_data", "Data and version numbers", ["system_lan_port_status", "system_web_ui_version"], {parentId: "system_information", nativePath: "config/system_info.html", entityGroups: ["system_health", "system_lan_ports"], readSections: ["status_technical"]}),
    page("system_information_services", "Active services", ["system_information_services"], {parentId: "system_information", nativePath: "config/system_services.html", entityGroups: ["system_services"]}),
    page("system_information_messages", "System messages", ["system_messages"], {parentId: "system_information", nativePath: "config/system_log.html"}),
    page("system_notifications", "E-mail notification", ["system_email_notifications"]),
    page("system_dsl_modem", "DSL modem", ["system_dsl_modem_mode"], {entityGroups: ["dsl_status", "connection_internet"]}),
    page("system_protection", "Guard functions", ["system_https_access", "system_firewall", "system_safe_mail_allowlist"], {entityGroups: ["system_security"]}),
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
  call_history_clear_missed: "telephony_calls_missed",
  call_history_clear_taken: "telephony_calls_taken",
  call_history_clear_dialed: "telephony_calls_dialed",
  telephony_phonebook_update_interval: "telephony_phonebook_basic",
  telephony_phonebook_rename: "telephony_phonebook_basic",
  telephony_phonebook_delete: "telephony_phonebook_basic",
  telephony_phonebook_disconnect: "telephony_phonebook_basic",
  telephony_phonebook_account_create: "telephony_phonebook_basic",
  telephony_phonebook_link: "telephony_phonebook_basic",
  telephony_handset_phonebook: "telephony_phonebook_assignment",
  nas_workgroup: "network_storage_workgroup",
});

// These reviewed contracts edit existing configuration. Target-bound forms stay
// inline too: their selector chooses an existing row, never a new router object.
// Creation, deletion, resets, enrollment and other one-shot actions remain
// explicit contextual operations. Unknown future contracts are not auto-opened.
const INLINE_SETTING_IDS = new Set([
  "internet_connection", "usb_tethering_enabled", "receiver_bonding", "receiver_led_mode",
  "parental_profile_edit", "port_forward_edit", "port_forward_range_edit", "port_blocking_edit", "dynamic_dns", "routing_exception_enabled",
  "telephony_provider_telekom", "telephony_provider_regio", "telephony_provider_other",
  "telephony_incoming_assignment", "telephony_outgoing_assignment", "telephony_analog_socket",
  "telephony_dect_enabled", "telephony_dect_settings", "telephony_dect_handset", "telephony_ip_pbx_enabled", "telephony_ip_phone",
  "telephony_line_options", "telephony_voice_encryption", "telephony_hd_voice", "telephony_dial_delay", "telephony_status_audio", "telephony_automatic_speed_dial",
  "telephony_phonebook_update_interval", "telephony_phonebook_rename", "telephony_phonebook_contact", "telephony_handset_phonebook",
  "network_mesh_node_rename", "powerline_rename", "wifi_schedule", "wifi_identity", "wifi_radio", "wifi_office_settings", "wifi_guest_settings", "wifi_access",
  "lan_ipv4", "dhcp", "qos_devices", "qos_voice_priority", "dns_rebind_protection", "dns_exception_edit", "vpn_peer_enabled",
  "storage_nas_share", "nas_workgroup", "storage_media_folder",
  "system_router_password_change", "system_easysupport", "system_led_schedule", "system_energy", "system_oled_display_rule", "system_cloud_backup",
  "system_extended_logging", "system_log_filter", "system_email_notifications", "system_https", "system_external_modem",
]);

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

/** Split existing settings from explicitly launched actions without changing authority. */
export function adminPageSettingSections(selectedPage, advertisedSettings, featureLinks) {
  const mapped = adminPageSettings(selectedPage, advertisedSettings, featureLinks);
  return {
    inline: mapped.filter((item) => INLINE_SETTING_IDS.has(item.id)),
    contextual: mapped.filter((item) => !INLINE_SETTING_IDS.has(item.id)),
  };
}

export function adminPageInlineSettings(selectedPage, advertisedSettings, featureLinks) {
  return adminPageSettingSections(selectedPage, advertisedSettings, featureLinks).inline;
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
