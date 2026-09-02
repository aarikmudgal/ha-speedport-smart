# Router management capability matrix

Current repository coverage, reviewed 2 September 2026, for the **unreleased
version 0.3 branch**. This replaces the earlier implementation plan. The reviewed
write target is **Speedport Smart 4R Typ A, firmware 010152.5.0.001.0**; equivalent
support on every Smart 4, 4R, 4R2 or firmware variant is not claimed.

The branch contains broad bidirectional administration, not only read-only
status. It does **not** cover every native menu or every operation within a
covered family. Registered editors can remain unavailable when the current
router omits required fields, hardware, identity, capacity or provider prerequisites.

## Coverage and live validation are separate

| Coverage | Meaning |
| --- | --- |
| **Interactive** | Closed editor, command or private-file implementation present and registered; runtime preflight and outcome policy still apply. |
| **Partial** | A named subset exists; other operations in the family are absent or blocked. |
| **Read only** | Allowlisted returned state is displayed; no write claimed. |
| **In progress** | Components exist, but wiring or end-to-end verification is incomplete. |
| **Missing** | No usable integration implementation, even if a possible native request is known. |
| **Excluded** | Physical/keypad/account-only, intentionally non-editable, unsupported or unbound behavior is not exposed as a local control. |

**Interactive does not mean live-write validated.** No controlled live
mutation/readback/restoration evidence is claimed here for the new beta
families. Their metadata continues to mark live-write verification false.

| Evidence layer | Established | Not established |
| --- | --- | --- |
| Native contract | Actual HTML actions, companion scripts, serializer, defaults and validators inspected. | Field lists alone are not complete requests; unbound handlers are not usable controls. |
| Offline tests | Payloads, bounds, requester/target binding, preservation, API/session/file paths and frontend state. | Router acceptance, persistent credentials, connectivity or hardware recovery. |
| Live read-only observations | Selected scalar forms, Wi-Fi/QoS device forms, parental profile, analog/global assignments and empty creation inventories. | Every populated schema, successful writes or other variants. |
| Live writes/restoration | Not validated by this work; evidence captures sent no configuration mutation. | Stable promotion needs an explicitly authorized reversible roundtrip or maintenance/recovery test. |

Exact readback verifies requested readable state; an ACK alone cannot.
Credential edits can leave secrets unverified. Router-password change instead
requires independent new-password login before HA persistence. Link changes,
resets and firmware installation may require reconnect/manual inspection:
timers, missing rows and HTTP success do not prove recovery. Phonebook import
acceptance/counters do not prove imported contents. Uncertain writes are never
automatically replayed.

## Shared owners and privacy

Closed registries are [`configuration.py`](../custom_components/speedport_smart/configuration.py),
[`configuration_targets.py`](../custom_components/speedport_smart/configuration_targets.py),
[`management.py`](../custom_components/speedport_smart/management.py), and
[`admin_actions.py`](../custom_components/speedport_smart/admin_actions.py).
They are not generic endpoint or JSON-payload editors.

Approvals bind administrator/login session, exact setting/target, typed values,
dynamic choices and private dependency fingerprints. Fresh reads precede the
one permitted write. Polling, queries and mutations share the runtime owner;
cache/draft invalidation and cleanup belong to execution. File transfers also
bind approved bytes, length and SHA-256 digest.

Safe telemetry remains native when returned. Structured inventories use bounded
administrator views. Passwords, VPN files, contacts/call records, backups and
private logs use explicit private transactions/downloads, not ordinary entity
state, Recorder, diagnostics, logs or general panel snapshots. Router-Pass and
Syslog files intentionally contain private information, not redacted diagnostics.
Private browser data is cleared on close or view change. Sensitive panel
transactions use authenticated administrator-only, no-store HTTP rather than
Home Assistant WebSocket frames that core debug logging could capture.

Detailed evidence: [network](ADMIN_NETWORK_EVIDENCE.md),
[telephony/storage](ADMIN_TELEPHONY_STORAGE_EVIDENCE.md),
[system/maintenance](ADMIN_SYSTEM_EVIDENCE.md), and
[private call history](ADMIN_CALL_HISTORY_EVIDENCE.md).
Code owners below are within `custom_components/speedport_smart/`.

## Internet and routing

| Capability | Coverage | Implemented subset and remaining limit | Owner |
| --- | --- | --- | --- |
| Reconnect Internet | Interactive | Confirmed command/deferred recovery; no promise of a different public address. | `management.py` |
| ISP/PPPoE | Interactive | Manual Telekom, Zuhause Start, Other and eligible automatic Telekom branches; full active forms, explicit changed credentials. Not first-boot wizard or separate Internet-provider deletion. | `configuration_internet.py` |
| MTU/VLAN/fixed IPv4 | Interactive | Exact active Other-provider branches, bounds and prerequisites. Saved settings do not prove connectivity. | Internet editor |
| Preferred IPv4/IPv6 DNS | Interactive | Primary/secondary fields and toggles. Not LAN IPv6/ULA administration. | Internet editor |
| Telekom privacy level | Interactive | Existing select and independently reported level. | `management.py` |
| USB tethering | Interactive | Exact enable/forced switch and fresh prerequisites. Route changes require recovery; connected USB status alone is not active-route proof. | `configuration_network_controls.py` |
| Tethering rescan/failover timing | Partial | Status reads exist. Native Check is GET refresh, not rescan POST; countdown is not editable failover timing. | Network evidence |
| Bonding/receiver LEDs | Interactive | Exact flag/enum with physical identity; bonding requires EasySupport not to manage it. | Network controls; native commands |
| Hybrid routing exceptions | Partial | Existing enable/disable/delete. Create/full destination/device editing still lacks complete conditional payload, create-sentinel and range-input proof. | `configuration_routing_exceptions.py` |
| Port forwarding/redirection | Interactive | Parent create/edit/enable/delete and nested TCP/UDP range create/edit/delete; exact IDs, reserved ports, overlaps and siblings checked. Last-range removal requires parent delete; preset shortcuts not separately exposed. | `configuration_port_rules.py` |
| Port blocking | Interactive | Full name/active/port-list/device rule create/edit/delete; not global firewall disable. | `configuration_port_blocking.py` |
| Parental schedules/budgets | Interactive | Profiles, daily/weekly windows, shared/per-device budgets and exclusive assignments. | `configuration_parental.py` |
| Per-device Internet pause | Missing | No independent pause endpoint. Disabling a parental profile removes restrictions; it is not pause. | Network evidence |
| Dynamic DNS | Partial | Standard/custom settings, private credential/path preservation and provider deletion. No dedicated force-refresh/update POST proven. | Network editor/controls |
| UPnP-IGD/mappings | Read only / excluded writes | Optional state/count only; no complete mapping view/identity or bound write schema. Generic standards are not substituted. | Normalizers; network evidence |
| VPN | Partial | Peer enable/delete, creation in current WireGuard/IPsec mode, IPsec-only key rotation and one-time private creation/rotation download. No mode switch, import or existing WireGuard secret recovery/export. | `configuration_vpn.py` |
| Receiver firmware/reset | Interactive | Offered update and separately confirmed factory reset with supported explicit eSIM-reset choice; fresh identity/offer and recovery attestations. Final installation/factory/eSIM state not immediately verified. | `system_actions.py` |
| Independent eSIM lifecycle | Excluded | No profile download/add/select/enable/delete editor; reset's eSIM choice is separate. | System evidence |

## Wi-Fi, LAN and devices

| Capability | Coverage | Implemented subset and remaining limit | Owner |
| --- | --- | --- | --- |
| Client rename/fixed DHCP | Interactive | Existing identified-client name and fixed-DHCP flag; no arbitrary reservation-address CRUD inferred. | `management.py` |
| Main/guest/prioritized Wi-Fi power | Interactive | Guarded on/off, main shutdown lockout handling. | Native commands |
| Radio bands/modes/channels/power | Interactive | Complete form/branch constraints; configured and actual channels distinguished. | `configuration_network.py` |
| Main Wi-Fi identity/security | Interactive | Per-band SSID/visibility, encryption/PMF/key/display-key policy and sibling-network preservation. | Network editor |
| Wi-Fi schedules | Interactive | Disabled/daily/weekly modes, exact time fields and forced-disconnect choice. | Network editor |
| Guest Wi-Fi settings | Interactive | Active, identity/security, lifetime/disconnect, display-key, WPS and Internet-access branches. | `configuration_wifi_extra.py` |
| Prioritized/office settings | Interactive | Active, identity/security through its separate form; device inventory is not another settings write. | Wi-Fi extra editor |
| Push-button WPS | Partial | Confirmed start/lifecycle refresh, not send-equals-paired; no general WPS-mode editor. | `management.py` |
| Legacy WPS PIN | Excluded | Old handlers unbound in actual page; no guessed PIN request. | System evidence |
| Wi-Fi environment scan | Missing | Channel telemetry does not implement user-triggered environment scan. | Registry absence |
| Credential reset/QR printing | Partial | Key editing/private Router-Pass text exist; no display-reset action or QR-print parity. | Wi-Fi editor/file transfer |
| Wi-Fi allowlist | Interactive | Exact SID/checked-state, whole inventory/identity readback and administrator-device lockout protection. | `configuration_device_selection.py` |
| Priority devices | Interactive | Up to two devices, exact compounds and identity-preserving readback. | Device-selection editor |
| VoIP priority flag | Interactive | Separate `Modules.json` flag with exact readback, preserving device membership and physical identity. Not part of device-choice form. | `configuration_small_controls.py` |
| LAN IPv4/subnet | Interactive | Eleven-field command changes IPv4 only, preserves IPv6/DHCP. Reconnect required; no automatic host migration. | `lan_management.py`, network editor |
| DHCP server/pool/lease | Interactive | Complete form/enums and fresh subnet/router/pool checks. | Network editor |
| LAN IPv6/ULA | Read only / missing writes | Preserve/read reviewed returned fields. ULA grammar and `lan_ip_v6_pext`/`lan_ip_v6_arec` semantics remain undocumented. | LAN/network evidence |
| DNS-rebind exceptions | Interactive | Domain create/edit/delete, exact IDs/capacity and sibling/protection preservation. | `configuration_network_rules.py` |
| Global DNS-rebind flag | Interactive | Separate `Modules.json` setter and exact flag/exception preservation readback; disabling removes a security safeguard. | Small-control editor |
| LAN links/speeds | Read only | Per-port/aggregate diagnostics; no arbitrary port-speed/mode setter. | Read contracts/entities |
| Mesh topology/rename/delete | Partial | Topology/metrics, existing rename/disconnected-node delete. No general optimization/pairing request. | `configuration_mesh.py` |
| Mesh identify | Interactive | Exact start/stop, manual-inspection outcome; closing does not auto-stop or prove blinking ended. | Mesh editor |
| Mesh-wide maintenance | Interactive | Restart/reset/online/manual updates; not per-node restart. Recovery proof separate. | System actions/file transfer |
| Powerline | Partial | Topology/rates and rename; no identify/pair/remove/optimization mutation proven. | `configuration_powerline.py` |

## Telephony and private histories

| Capability | Coverage | Implemented subset and remaining limit | Owner |
| --- | --- | --- | --- |
| Manual VoIP providers | Interactive | Create Telekom/Regio/Other with number, edit credentials, delete. Automatically managed providers excluded; persistence is not SIP registration. | Provider modules/admin actions |
| Telephone numbers | Partial | Add to manual provider; activate/deactivate/delete and call options. Standalone existing-number digit editing missing. | Number/target modules/admin actions |
| Incoming/outgoing/backup assignment | Interactive | Full exact matrices, branch prerequisites and sibling preservation. | `configuration_phone_assignments.py` |
| Analog sockets | Interactive | Name/type, assignments and conditional call waiting. | `configuration_phone_targets.py` |
| DECT base | Interactive | Enable/PIN/power/Eco with repeater restrictions. | `configuration_telephony.py` |
| DECT handsets | Interactive | Enroll/page/disconnect and name/assignment/call-waiting editor. Physical pairing user-operated. | Admin actions/target editor |
| DECT repeaters | Partial | Guarded enrollment/disconnect and attestations; no unrelated tuning inferred. | Admin actions |
| IP phones/PBX | Interactive | Enable, exact-ID allocation, existing credentials/settings/assignments, private refresh/delete. No allocation replay on missing identity. | IP-phone/target modules |
| Voice/dialing behavior | Interactive | VoSIP, HD Voice, dial delay, announcements, CLIR and busy/multiple-call behavior. | Telephony/basic/target editors |
| Automatic number memory | Partial | Learning switch and one-shot learned-number clear. Clear always requires manual inspection: no learned-list/count/generation proof, no verified-deletion claim. No arbitrary entry editing. | Telephony/small-control editors |
| Call aggregates | Read only | Safe returned count/last-call metadata, not private records. | Native normalizers/entities |
| Private call view/CSV/clear | Interactive | Explicit private load, local CSV export and three one-shot category clears wired/tested. Complete selected collection required; global-only replies remain unavailable, not empty. | Call-history modules/view |
| Local contacts | Interactive | Private search/detail and guarded create/edit/delete with complete readback; no general contact cache. | Phonebook modules |
| Local books/handset assignment | Interactive | Create/rename/delete, assignment and update interval where fresh choices permit. Exact local indexes/capacity from current registries. | Account/assignment modules |
| Phonebook import/export | Partial | Private native local-book transfers. Import counters/acceptance leave contents unverified; merge semantics/populated live transfers unvalidated. | File-transfer transaction |
| Online book linking | Interactive | Multi-step account/link/session flow wired and tested offline; disconnect/rename/interval available. First registration alone is not completed linking/merging; live provider success remains unvalidated. | Phonebook link/flow/session modules |
| Keypad-only functions | Excluded | No HTTP equivalent invented for keypad/service-code behavior. | Official manual |

## Storage and services

| Capability | Coverage | Implemented subset and remaining limit | Owner |
| --- | --- | --- | --- |
| USB/storage/printer state | Read only | Presence/mount/capacity/printer metadata; USB power through Energy, no unbound printer-enable form. | Native surfaces/system editor |
| Existing NAS share | Interactive | Enable/path/read-only/authentication/credentials and delete. Fresh protected passwords; secret verification distinguished. | NAS/storage modules/admin actions |
| New NAS share | Interactive | Empty disabled-form lifecycle, prerequisites and exact new-ID proof. Missing identity is not fabricated empty form. | `configuration_nas_create.py` |
| NAS directory picker/mkdir | Missing | Validated absolute path text is editable, but no picker/filesystem directory creation. Static request names do not prove full node/path/ACK/readback. | Telephony/storage evidence |
| Safe storage removal | Interactive | Supported ID/serial, complete absence/sibling proof; missing inventory is not unmount success. | `storage_lifecycle.py` |
| SMB workgroup | Interactive | Typed form/same-endpoint readback. | `configuration.py` |
| Media folders/index | Interactive | Configuration create/edit/enable/delete and reindex/progress. Not filesystem deletion; Finished-to-Finished is not new-run proof. | `configuration_media.py` |
| Smart Home service | Interactive | Activation-code/deactivation, state/lock checks and service readback; not every attached device. | `system_actions.py` |

## System, maintenance and private files

| Capability | Coverage | Implemented subset and remaining limit | Owner |
| --- | --- | --- | --- |
| Initial setup wizard | Missing | Setup/password/write-blocked diagnostics only; provider editor is not first boot. | Native diagnostics |
| Router password | Interactive | Isolated old/new login proof, exact ACK, requester-bound confirmation, proven HA persistence/recovery latch; no credential cycling. | Password transaction modules |
| Router-Pass | Partial | Private text from fresh Wi-Fi data; optional entered router password unverified, no QR-print parity/persistent card. | File-transfer transaction |
| Front LED schedule | Interactive | Native mode/interval; not general display timeout. | System editor |
| Wi-Fi/USB Energy | Interactive | Separate full form, wired prerequisites and native hidden/select preservation. | System editor |
| Display parental rule | Interactive | None or exact current profile, revision-bound choices. | System-extra editor |
| Automatic cloud backup | Interactive | Eligible EasySupport-dependent flag; not local backup/hotline consent. | System editor |
| Local backup | Interactive | Private bounded native download/password/no-store/cleanup; not restorability certificate. | File-transfer transaction |
| Restore backup | Interactive | Approved digest-bound upload, native status and recovery; no redirect-based configuration proof. | File-transfer transaction |
| Reboot | Interactive | Guarded command/deferred recovery. | `management.py` |
| Factory reset | Interactive | Fresh typed one-shot preflight/backup/physical attestations. Attestations are not verified backups; recovery manual. | `maintenance.py` |
| DECT reset | Interactive | Explicit retain/remove covers handsets/repeaters, fresh state/recovery. | Maintenance |
| Router firmware | Interactive | Fresh offered image/digest or manual upload. Accepted is not installed-version proof. | System actions/file transfer |
| Mesh firmware | Interactive | Mesh-wide offered/manual update with identified-node preflight; unsupported/local-only offers excluded. | System actions/file transfer |
| System information/services | Read only | Returned identity/version/uptime/DSL/WAN/health/service summaries. Service lists not writable; unknown fields not auto-exposed. | Read contracts/surfaces |
| Distinct web-UI build version | Missing | Exact normalized source absent; device firmware cannot be relabeled. | Firmware-history distinction |
| Detailed logging | Interactive | Exact module flag, no messages in settings result. | System editor |
| System log download/clear/filter | Partial | Native private Syslog download, complete unfiltered-list clear and exact seven-category filter editor. No in-panel raw-message viewer. Missing/filtered lists cannot authorize clear. | File transfer/maintenance/small controls |
| Email notifications | Interactive | Conditional account/recipient/events; fresh changed credentials. Readback not delivery/password proof. | System-extra editor |
| HTTPS access | Interactive | Exact flag, explicit reconnect/certificate/HA scheme handling; no automatic TLS downgrade. | System editor |
| External modem/Link-LAN1 | Interactive | Native flag/mobile-cabling prerequisites/reconnect; not arbitrary port/routing editor. | System editor |
| DSL modem mode | Interactive | Disruptive maintenance and backup/wiring/physical/firewall-loss attestations; router-mode recovery physical. | Maintenance |
| Local EasySupport/updates | Interactive | Standard/eligible BNG branches and dependencies; account/hotline separate. | System-extra editor |
| Global firewall switch | Read only / excluded writes | Returned state; no documented editable switch. Port rules separate. | Official manual/native state |
| Safe-mail-server allowlist | Excluded | Model unsupported; separate from email notifications. | [Telekom guidance](https://www.telekom.de/hilfe/geraete/router/speedport/e-mail-server-bearbeiten) |
| Device Manager/hotline/account | Excluded | Account login/consent/remote password/reconfiguration external and user-operated. | Official EasySupport documentation |
| Physical display/keys/speed test | Partial / excluded | Proven web equivalents above; no display-only speed test/keypad/unbound reset invented. | Official manual/native forms |

## Remaining work and promotion

1. Resolve routing full/create and NAS picker/mkdir lifecycle evidence.
2. An in-panel raw system-message viewer remains absent; private native log
   download and category filtering are available. Unobservable learned-number
   clearing must not report verified deletion.
3. Keep undocumented IPv6, legacy WPS PIN, UPnP mappings, VPN mode/import,
   per-device pause and unsupported physical/account functions unavailable.
4. Obtain explicit permission for real change/readback/restoration tests,
   including online phonebook linking and category-history behavior.
   Destructive/firmware work needs maintenance window, backup, exact target and
   physical recovery. No percentage or fixture replaces that validation.

## Primary references and limits

References are retained from prior review; this documentation update made no
router requests and did not refresh online sources. Manuals document behavior,
not private JSON schemas.

- [Smart 4R manual](https://www.telekom.de/hilfe/downloads/bedienungsanleitung-speedport-smart-4r).
- [Smart 4R/4R2 Typ A firmware history](https://www.telekom.de/hilfe/downloads/firmware-aenderungen-speedport-smart-4r-4r2-typ-a).
- [Smart-series support](https://www.telekom.de/hilfe/geraete/router/speedport/smart-serie) and [manual configuration](https://www.telekom.de/hilfe/hilfe-bei-stoerungen/speedport-manuell-konfigurieren).
- [EasySupport functions](https://www.telekom.de/hilfe/geraete/service/einrichtung-support/easy-support-funktion) and [firmware guidance](https://www.telekom.de/hilfe/geraete/router/speedport/firmware-update).
- [Telekom developer catalogue](https://developer.telekom.com/en/products), not a local advertised API/form substitute.
- [TR-064 Issue 2](https://www.broadband-forum.org/pdfs/tr-064-2-0-0.pdf), [TR-181 Device:2](https://device-data-model.broadband-forum.org/), [UPnP ConfigurationManagement:2](https://www.upnp.org/specs/dm/UPnP-dm-ConfigurationManagement-v2-Service-20120216.pdf), [BasicManagement:2](https://upnp.org/specs/dm/UPnP-dm-BasicManagement-v2-Service.pdf) and [IGD 2](https://openconnectivity.org/developer/specifications/upnp-resources/upnp/internet-gateway-device-igd-v-2-0/) are generic standards, not proof of this firmware's actions.

Actual contracts derive from reviewed firmware HTML/JavaScript and code/tests.
V3 missing-form conclusions were superseded by actual v4/v5 forms and v6
validators. Candidate names/third-party projects grant no generic write
authority. No captured private identities, credentials, addresses, SSIDs,
contacts, call records or log contents appear in this matrix.
