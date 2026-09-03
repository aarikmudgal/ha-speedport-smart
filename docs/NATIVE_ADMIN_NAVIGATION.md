# Native Administration navigation audit

Read-only inspection of the English Speedport Smart 4R Typ A web interface on
3 September 2026 covered every destination in its sitemap and every main
sidebar. The sitemap contained 68 destinations; **Prioritization** appeared in
the Network sidebar only. All **69 distinct screens** were opened.

The inspection collected navigation labels, section headings and form-control
types, not configuration values. No setting, checkbox, selection, Save, reset,
update, enrollment or other router action was changed or submitted. Opening a
configuration page is not evidence that its write operations work.

Paths below identify the observed web pages only. They are not API endpoints,
discovery matchers or permission to request arbitrary router URLs. The panel
continues to use its fixed, reviewed backend contracts and runtime capability
gates. Conditional controls remain conditional; navigation parity does not
imply that every firmware operation is available.

## Overview and Status

| Screen | Observed path | Visible sections |
| --- | --- | --- |
| Overview | `/html/content/overview/index.html` | Internet, Telephony, Network |
| Status | `/html/login/status.html` | Status information, Internet, Telephony, Network |

All paths in the following tables are relative to `/html/content/`.

## Internet

| Navigation | Page | Sections or existing settings |
| --- | --- | --- |
| Internet connection → Access data | `internet/connection.html` | Actual state; Access data; DNS server |
| Internet connection → Via cellular device | `internet/usb_tethering.html` | Connection via cellular device |
| Internet connection → IP address information | `internet/con_ipdata.html` | IPv4; IPv6; Change IP addresses |
| Internet connection → Telekom Privacy Policy | `internet/con_privacy.html` | Privacy policy; Change IP addresses |
| 5G outdoor unit → Connection | `internet/lte.html` | 5G / LTE status; SIM card; LAN connection |
| 5G outdoor unit → Mode settings | `internet/lte_mode.html` | Mode settings; Tunnel status; LEDs of the 5G outdoor unit |
| 5G outdoor unit → Firmware and reset | `internet/lte_firmware.html` | Firmware updates; Problem handling |
| 5G outdoor unit → Routing exceptions | `internet/except.html` | Existing exceptions and contextual rule editing |
| Child protection - Time rules | `internet/chd_timerules.html` | Display switch; existing time rules and contextual creation |
| Port activation | `internet/portforwarding.html` | Existing rule, target device, TCP / UDP ranges |
| Port blocking | `internet/portblocking.html` | Existing rule, ports and device assignments |
| Dynamic DNS | `internet/dyn_dns.html` | Service enablement and conditional provider settings |

## Telephony

| Navigation | Page | Sections or existing settings |
| --- | --- | --- |
| Telephony | `phone/phone_internet.html` | Current providers and numbers; contextual provider creation |
| Phone number assignment | `phone/phone_number.html` | Incoming calls and Outgoing calls, each with its own Save |
| Telephone socket | `phone/phone_analog.html` | Name, number assignment, device type and call waiting |
| DECT base station → Settings for DECT | `phone/phone_dect_settings.html` | DECT enablement and conditional base settings |
| DECT base station → Registered handsets | `phone/phone_dect_mobiles.html` | Current handsets; explicit enrollment |
| DECT base station → Registered repeaters | `phone/phone_dect_repeater.html` | Current repeaters; explicit enrollment |
| IP PBX | `phone/phone_ippbx.html` | PBX enablement and IP-phone configuration |
| Phone number settings → Phone number usage | `phone/phone_lineset.html` | Existing line usage, reject-on-busy and caller-ID options |
| Phone number settings → Security settings | `phone/phone_linevosip.html` | Security settings for Telekom phone numbers |
| Phone number settings → High voice quality (HD Voice) | `phone/phone_linehdvoice.html` | HD Voice |
| Phone number settings → Dial delay | `phone/phone_linedialdelay.html` | Dial delay |
| Phone number settings → Status message | `phone/phone_linestataudio.html` | Status message |
| Phone number settings → Number memory (Speeddial) | `phone/phone_linespeeddial.html` | Number memory; explicit memory deletion |
| Call lists → Missed calls | `phone/phone_call_missed.html` | History; internal-call inclusion; export and explicit clearing |
| Call lists → Received calls | `phone/phone_call_taken.html` | History; export and explicit clearing |
| Call lists → Dialed outgoing calls | `phone/phone_call_dialed.html` | History; export and explicit clearing |
| Phone book → Basic settings | `phone/phone_book_basic.html` | Phone books; online address-book request interval |
| Phone book → Entries | `phone/phone_book_entries.html` | Book selection, entries, import and export |
| Phone book → Assignment | `phone/phone_book_assign.html` | Phone-book assignment |

## Network

| Navigation | Page | Sections or existing settings |
| --- | --- | --- |
| Connected devices | `network/devices.html` | Existing devices; contextual device details and creation |
| Wi-Fi settings → Basic settings | `network/wlan_basic.html` | Actual state; Time rule |
| Wi-Fi settings → Name and encryption | `network/wlan_name_enc.html` | 2.4 GHz; 5 GHz; shared encryption and key |
| Wi-Fi settings → Send settings | `network/wlan_sendset.html` | Band and power; 2.4 GHz; 5 GHz |
| Wi-Fi settings → Prioritized Wi-Fi | `network/wlan_office.html` | Enablement and conditional prioritized-network settings |
| Wi-Fi settings → Guest access | `network/wlan_guest.html` | Enablement and conditional guest-network settings |
| Wi-Fi settings → Environment scan | `network/wlan_environ.html` | 2.4 GHz / 5 GHz views; explicit refresh |
| Wi-Fi access (WPS) → Add device via WPS | `network/wlan_wps.html` | WPS enablement and available enrollment methods |
| Wi-Fi access (WPS) → Access limit | `network/wlan_access.html` | Access policy and conditional device allowlist |
| Network addresses → Router addresses | `network/lan.html` | Router IPv4 address and mask; IPv6 configuration |
| Network addresses → Address assignment (DHCP) | `network/dhcp.html` | Enablement, pool and lease time |
| Prioritization | `network/qos.html` | Prioritization of Telephony; Prioritization of devices |
| DNS rebind protection | `network/dns_rebind.html` | Protection; List of Exceptions |
| Virtual network (VPN) | `network/vpn.html` | Existing peers and explicit activation / creation |
| SmartHome | `network/smarthome.html` | MagentaZuhause activation |
| USB storage and printers → USB port | `network/nas_overview.html` | USB enablement; connected USB devices |
| USB storage and printers → Sharing | `network/nas_share.html` | Sharing enablement and conditional share configuration |
| USB storage and printers → Workgroup | `network/nas_workgroup.html` | Workgroup name |
| USB storage and printers → Media playback | `network/nas_mediareplay.html` | Existing media-folder enablement, name and folder |

## System

| Navigation | Page | Sections or existing settings |
| --- | --- | --- |
| Change device password | `config/change_password.html` | Current and new password inputs; no credential prefill |
| EasySupport | `config/easy_support.html` | Support consent and conditional options |
| Energy-saving mode | `config/energy.html` | Display mode for LEDs; LAN port status; Wi-Fi and USB energy settings |
| Save settings | `config/save_settings.html` | Important settings; local backup; manual restore |
| Problem handling → Restart | `config/restart.html` | Explicit restart |
| Problem handling → Reset | `config/reset.html` | Explicit factory reset |
| Problem handling → DECT | `config/problem_handling_dect.html` | Explicit DECT reset and handset option |
| Problem handling → Mesh | `config/problem_handling_mesh.html` | Mesh settings |
| Firmware updates → Speedport | `config/check_for_updates.html` | Automatic, semi-automatic and manual firmware update |
| Firmware updates → Mesh | `config/check_for_updates_mesh.html` | Mesh firmware updates |
| System information → Data and version numbers | `config/system_info.html` | Data and version numbers |
| System information → Active services | `config/system_services.html` | Internet services; Network services |
| System information → System messages | `config/system_log.html` | Extended logging; filtering; export and explicit clearing |
| E-mail notification | `config/notify.html` | Enablement and conditional notification settings |
| DSL modem | `config/internal_modem.html` | Modem-mode information and explicit configuration action |
| Guard functions | `config/protect.html` | Secure access; Firewall |
| External modem | `config/external_modem.html` | External-modem mode |

## Panel behavior and deliberate differences

- Router tabs, sidebar ordering and leaf screens follow this observed hierarchy.
  Home Assistant integration tools remain separate from native router settings.
- Existing configuration sections load on page entry. Reads are serialized and
  paced; the panel does not open every configuration page in the background.
- Existing-object editors retain an exact target selector. They do not grant
  simultaneous write approvals for every device or row in a collection.
- Create, delete, reset, firmware, enrollment and similar actions require
  explicit user interaction. Opening a page never executes them.
- Modern Home Assistant styling, responsive navigation, explicit confirmations
  and private credential handling are retained. Router graphics, secret
  prefilling and its less explicit write behavior are not copied.
- Firmware-specific omissions and unverified writes are still documented in the
  [capability matrix](MANAGEMENT_CAPABILITY_MATRIX.md). This navigation audit is
  not a replacement for router-owner write testing.
