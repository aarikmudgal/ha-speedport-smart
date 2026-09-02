# Router management support

Telekom Speedport Smart exposes a control only when the integration has an
exact request contract and the connected router reports the required source
data. A source-code descriptor alone does not create an entity.

The stable version 0.2 baseline targets the public behavior documented for a
Speedport Smart 4R Typ A with firmware `010152.5.0.001.0`. Version 0.3 work adds
only capability-gated behavior that meets the evidence and safety rules below.
This document combines repository code
and tests with static review of public manuals, firmware history, public web
resources, and non-official implementations. That static review is not live
router verification. Other models and firmware versions may expose a smaller
set.

## Evidence classes

| Class | Meaning |
| --- | --- |
| Implemented read-only | A discovered response is normalized and exposed without sending a setting request. |
| Implemented writable | An allowlisted request has a complete endpoint and form contract, positive acknowledgement handling, independent readback where the action permits it, and stable target identity when it addresses a row. |
| Staged guarded writable | The current firmware proves one exact scalar endpoint, field, value domain, and read source. The beta control additionally requires a fresh pre-read, positive acknowledgement, and matching post-write readback at runtime, but still needs one user-authorized change and rollback before promotion. |
| Executable beta administrator action | One fixed panel-only operation is bound to the exact reviewed model, firmware, endpoint, Referer, capability, handlers, typed parameters, confirmation policy, preflight, and independent readback. Static firmware evidence and automated tests support the implementation, but it remains unproven on a live router until a user-authorized roundtrip succeeds. |
| Firmware-evidenced but blocked | Public firmware material names a page, field, endpoint candidate, or request shape, but at least one required proof is missing. No control is exposed. |
| Destructive, private, or deferred | The operation can erase configuration, interrupt recovery, or reveal credentials or key material, or it lacks a safe Home Assistant interaction model. It is excluded from the stable version 0.2 baseline. Version 0.3 beta exposes only the seven fixed destructive administrator actions documented below; every other destructive/private operation remains excluded. |

No write is promoted as proven without a complete endpoint, form,
acknowledgement, readback, and stable-identity contract. Static reconnaissance
alone never creates a generic request or form. Three exact reversible scalar
controls and eleven fixed administrator actions are staged for explicit user
roundtrips. A state-changing request is never replayed. The administrator
executor rejects explicit negative replies, treats an ambiguous mutation
outcome as unknown, and reports success only after bounded independent readback.

Read coverage is independent of write eligibility. A missing write contract does
not by itself suppress an independently reviewed read field, but returned data
is exposed only after an explicit normalizer and presentation contract exists.
Unknown fields and inventory-only families remain absent even when a candidate
endpoint returns them. Reviewed settings and measurements are exposed as
read-only entities or through the bounded administrator-only cached view
according to their privacy and persistence requirements. Passwords, keys,
recovery material, and raw private records are never copied into entity state,
diagnostics, logs, or dashboard metadata.

Version 0.3 development uses immutable safety policies for backend contracts and
dashboard controls. Each reviewed command binds a semantic feature ID, exact
client handler and parameter-name set, model/firmware and capability boundary,
execution surface, risk tier, confirmation policy, and readback cadence.
Support, current session availability, Home Assistant permission, and
presentation confirmation remain separate gates. The dashboard receives only
semantic metadata, never router endpoints or request fields.

Native entities remain callable through Home Assistant services and
automations. The separate administrator-action executor is panel-only and
requires an administrator, entry-scoped control permission, exact server-side
confirmation, strict parameter validation, and serialized execution.
Targeted operations use 60-second single-use grants bound to the action, target
identity, private context, management generation, and current session. Those
grants are consumed before one fresh preflight and at most one mutation.
Destructive commands are forbidden from native entity exposure and require a
fixed typed phrase plus recovery guidance. Unknown control-shaped entities fail
closed as read only.

## Implemented stable-baseline controls

Stable version 0.2 enables write contracts only for the reviewed Speedport Smart 4R
Typ A firmware `010152.5.0.001.0`, and only when the current response also
proves the required capability. An unknown or newly updated firmware remains
read-only until its write contract is reviewed.

| Home Assistant control | Router request | Verification | Notes |
| --- | --- | --- | --- |
| Internet reconnect button | `data/Connect.json`, `req_connect=reconnect` | Normal polling resumes after the connection returns | Interrupts the Internet connection |
| Router reboot button | `data/Reboot.json`, `reboot_device=true` | Polling resumes after the router returns | Interrupts the router and local network |
| Wi-Fi switch | `data/Modules.json`, `use_wlan=0` or `1` | Fresh `wifi.enabled` state | Can disconnect Home Assistant when it uses Wi-Fi |
| Guest Wi-Fi switch | `data/Modules.json`, `wlan_guest_active=0` or `1` | Fresh `wifi.guest.enabled` state | Changes only the guest radio state |
| Prioritized Wi-Fi switch | `data/Modules.json`, `wlan_office_active=0` or `1` | Fresh `wifi.office.enabled` state | Available only on firmware that exposes prioritized Wi-Fi; the internal `office` key is retained for compatibility |
| WPS button | `data/WLANAccess.json`, `wlan_add=on` and `wps_key=connect` | Refreshes `data/WPSStatus.json` | Opens the router's normal WPS window |
| Existing port-forward switch | Fresh `data/PortuwMain.json` rule with the same ID, name, and non-state rule fingerprint, then `portuw_active=0` or `1` | Fresh state for the same unchanged rule semantics | Does not create, edit, delete, or mutate a reused or retargeted rule ID |
| Client name text entity | Fresh complete managed-device row with only `mdevice_name` changed | Same row kind, row ID, required MAC address, and new name | Accepts 1 to 28 letters, numbers, or hyphens |
| Fixed DHCP switch | Fresh complete managed-device row with only `mdevice_fix_dhcp` changed | Same row and fresh fixed-DHCP flag | Keeps all current address fields unchanged |
| Hybrid bonding switch (staged) | Fresh `data/LTE.json`, then only `use_bonding=0` or `1` | Positive acknowledgement plus fresh `hybrid.enabled` | May interrupt Internet traffic; requires user change/readback/rollback validation |
| Internet privacy select (staged) | Fresh `data/IPPrivacy.json`, then only `lan_privacy_policy=0`, `1`, or `2` | Positive acknowledgement plus fresh `internet.privacy_level` | Options are Off, Level 1, and Level 2; requires user change/readback/rollback validation |
| Receiver LED mode select (staged) | Fresh `data/LTE.json`, then only `ex5g_led_mode=0`, `1`, or `2` | Positive acknowledgement plus fresh `receiver.led_mode` | Options are Use LEDs, switch off after timeout, and Do not use LEDs; requires user change/readback/rollback validation |

Stateful switches skip a request when the router already reports the desired
state. After a request, the integration performs serialized read-only
verification at approximately 0, 0.5, 1, and 2 seconds, stopping when the exact
requested value appears. It never replays the mutation. Exhausted mismatches or
read failures raise a Home Assistant error. Reboot and Internet reconnect cannot
use an immediate readback because the requested action deliberately breaks the
connection.

Client rename and fixed DHCP preserve the complete current row returned by
`data/DeviceList.json`. Both require the same stable row ID and nonempty MAC
address. The integration rejects incomplete rows, unknown form fields,
duplicate matches, changed identities, and unsupported row types before sending
a request.

The staged scalar controls reject missing, duplicated, nested, wrong-type,
case-shifted, or out-of-range current values before a POST. Their entities are
created only for the exact reviewed model and firmware, only when the matching
read capability and current state exist, and only when management controls are
enabled. For these native scalar controls, the dashboard sends standard Home
Assistant switch/select service calls; it never receives router endpoints,
field names, or numeric codes.

## Executable beta administrator actions

The current version 0.3 beta exposes the following fixed actions only for the
exact reviewed model and firmware. Their request shapes come from downloaded
firmware resources and their behavior is covered by automated tests. No action
in this table has completed a live mutation/readback/rollback roundtrip on a
physical router, so none is promoted as stable proof.

| Administrator action | Exact mutation and independent readback | Additional guard |
| --- | --- | --- |
| Enroll DECT handset | `POST data/DECT.json` with `scan_dect=scan dect phones`, then fresh `DECTInfo.json` scan state | Explicit confirmation; refuses an already-active scan |
| Enroll DECT repeater | `POST data/DECTRepeater.json` with `scan_repeater=scan dect repeater`, then fresh `DECTInfo.json` scan state | Separate confirmations that the DECT PIN is `0000`, full DECT transmit power is enabled, and Full Eco Mode is off; refuses an already-active scan |
| Start or stop handset paging | `POST data/DECT.json` with the fixed paging command and exact handset ID, then fresh handset membership and `DECTInfo.json` paging state | 60-second single-use target grant and explicit confirmation |
| Activate or deactivate VoIP line | `POST data/IPPhoneNumbers.json` with exact line ID, `no_delete=keep`, and closed active state, then fresh line state | 60-second single-use target grant and disruptive confirmation |
| Disconnect DECT handset | One exact `DECT.json` disconnect, then fresh absence in `DECTStation.json` | Single-use target grant, `DISCONNECT DECT HANDSET`, and re-enrollment recovery guidance |
| Disconnect DECT repeater | One exact `DECTRepeater.json` disconnect, then fresh absence in the repeater inventory | Single-use target grant, admin-visible opaque repeater reference, `DISCONNECT DECT REPEATER`, and re-enrollment recovery guidance |
| Delete VoIP provider | One exact `IPPhone.json` deletion, then fresh provider-list absence | Single-use target grant, `DELETE VOIP PROVIDER`, and calling recovery guidance |
| Delete VoIP number | One exact `IPPhoneNumbers.json` deletion, then fresh line-list absence | Single-use target grant, `DELETE VOIP NUMBER`, and calling recovery guidance |
| Delete IP-PBX client | One exact `IPClients.json` deletion, then fresh client-list absence | Single-use target grant, `DELETE IP PBX CLIENT`, and client re-enrollment guidance |
| Delete phonebook entry | One exact `PhoneBook.json` deletion in its bound phonebook, then complete fresh book-list absence | Single-use target grant, `DELETE PHONEBOOK ENTRY`, and backup/recreation guidance |
| Delete NAS share | One exact `NASFolder.json` deletion, then fresh share-list absence | Single-use target grant, `DELETE NAS SHARE`, and share-recreation guidance |

All actions recheck capability and identity under the shared operation lock,
send at most one mutation, perform bounded read-only verification, and release
their authenticated session. Explicit router rejection fails immediately;
transport or decoding ambiguity produces an outcome-unknown error and is never
retried. Target fingerprints, full telephone numbers, and private target context
stay backend-only. Target selectors return only contract-bounded fields to the
requesting administrator, including bounded exact router row IDs as opaque
`reference` values and masked four-digit VoIP `number_suffix` values, plus
single-use tokens. These ephemeral results never enter persistent Home Assistant
state.

## Implemented read-only coverage

Read-only fields do not imply a matching write. In particular:

- `wlan_band=0`, `1`, and `2` mean both bands, 2.4 GHz only, and 5 GHz only.
  Dedicated per-radio fields remain authoritative when present.
- `use_dyndns` is interpreted as DDNS enablement.
- `vpn_status` is interpreted as VPN profile enablement, not tunnel
  connectivity. Connectivity requires a separate connection field.
- Client `access_possible` is exposed as read-only Internet-access allowance.
  It is not inverted into an unproven pause state or writable switch.
- Initial-setup completion, device-password-changed, router HTTPS, and
  SmartHome linked state are diagnostics only. They do not prove or enable the
  corresponding setup, password, HTTPS, or activation writes.

| Area | Current read-only coverage |
| --- | --- |
| Internet, WAN, DSL, and Hybrid | Connection state, addressing, firmware-reported connection-start timestamp, independent uptime duration, DSL metrics, WAN totals, packets, errors, live rate, and utilization |
| Wi-Fi | Correct global and per-band state, channels, client counts, guest and prioritized-network state, and Mesh topology; bounded 2.4 GHz, 5 GHz, guest, and prioritized-network SSIDs in the administrator-only cached view, with keys excluded |
| LAN and DHCP | Clients, presence, signal, links, DHCP state, leases, pool/lease summaries, IPv4/IPv6 state, aggregate linked ports, per-port LAN 1-4 link and negotiated speed, and client access allowance when returned |
| NAT, DNS, traffic prioritization, and security | Port-forward counts plus bounded rule name, state, target, and TCP/UDP mapping summaries; port-block state/counts plus bounded rule-group, ID, state, and validated port-list rows, aggregating distinct extended and extra groups without merging colliding IDs; DNS-rebind state/count plus bounded exception-domain rows; traffic-priority count plus exact slot flags without inferred client identity; firewall, remote-management, and router-side HTTPS state when returned |
| Mesh and Powerline | Mesh topology and node metrics, including exact per-radio 2.4 GHz and 5 GHz MAC identities in the administrator-only cached view; bounded Powerline ID, name, parent, manufacturer, MAC, firmware, mode, and upload/download link-rate rows |
| Telephony and DECT | Registration, provider/line summaries, opaque line-to-provider relationships in the administrator-only cached view, missed-call count and latest call timestamp without call identities or records, paging state, handsets, PBX/IP-phone counts and rows, DECT repeater count and bounded membership rows, and phonebook count plus bounded total and remaining-entry counts in the ephemeral administrator search when returned; analog-socket fields remain absent pending an exact read contract |
| USB and NAS | Device state, mount state, aggregate capacity/free space, media/temperature, NAS safe flags, and bounded storage-device/share rows with exact storage serial and share identifiers in the administrator-only cached view when returned; the private share name/folder identifier can be path-like, while users and credentials are excluded |
| DDNS, VPN, and parental controls | DDNS enablement and status plus bounded domain/update-server identity in the administrator-only cached view; VPN profile enablement, connection, type, peer counts and bounded peer rows with opaque peer identifiers; and parental profile state when returned |
| Setup, SmartHome, system, energy, and update | Initial-setup/password prerequisite flags, SmartHome linked state, operating mode, uptime, health, temperature, device firmware, and update metadata when exposed |
| Mobile and 5G | Connection, radio type, signal measurements, band, frequency, cell, and receiver state when exposed |

## Firmware-evidenced but blocked

Public firmware material can narrow investigation but cannot satisfy a write
contract by itself. Blockers below are exact missing proof categories:

The offline corpus currently contains 73 candidate request contracts. Thirty-five
have a resolved endpoint and 38 do not; none satisfies every required proof.
The scanner also cannot be trusted to identify every secret field, so it is
never used to generate runtime schemas or a generic router editor.

| Area | Static evidence | Blocking proof |
| --- | --- | --- |
| Client Internet pause/resume | `access_possible` reports whether access is allowed. | `ENDPOINT`, `FORM`, `ACK`, and independent `READBACK`; the read-only allowance must not be treated as an inverse pause command. |
| Per-band Wi-Fi changes | `wlan_band` proves read semantics for both, 2.4 GHz-only, and 5 GHz-only modes. | Complete shared `FORM`, positive `ACK`, independent per-band `READBACK`, and disconnect recovery. |
| DDNS create/edit/provider changes and deletion | `DDNS.json` and `DynDNS.json` plus `use_dyndns` provide read endpoint and state candidates. Static deletion code posts `delprov=true` through an unresolved page-local `JSONSource`; it does not prove that the mutation uses `DynDNS.json`. No proven manual “update now” action exists. | Exact mutation `ENDPOINT` and Referer, complete provider `FORM`, `ACK`, independent `READBACK`, and `SECRET` handling for credentials. |
| VPN and WireGuard changes | `VPN.json`, `WireGuard.json`, `vpn_status`, and peer rows provide endpoint and state candidates. The observed switch is per profile, while `renewvpn` renews generated access material; neither is a global VPN restart. | Exact save `ENDPOINT`, complete `FORM`, `ACK`, separate enabled/connected `READBACK`, stable peer `IDENTITY`, and private-key or pre-shared-key `SECRET` handling. |
| UPnP, parental controls, and media server | Read-only fields and source descriptors exist. `internet_timerule_active` is aggregate parental-rule state, and the media server becomes active through enabled shared folders; neither proves a global switch. | Exact write `ENDPOINT`, complete `FORM`, `ACK`, and independent `READBACK`. |
| DSL restart | No discrete DSL-restart operation was found in the captured firmware UI. Router reboot and mode-changing reboot flows are different operations. | An exact firmware action plus positive `ACK` and DSL-specific `READBACK`; it must not be aliased to router reboot. |
| Mesh node rename | The page reads rows from authenticated `GET data/DeviceList.json`. Its static form names candidate action `data/MeshDevice.json` and the apparent row fields `id`, `mesh_connected`, `mesh_device_type`, `mesh_downspeed`, `mesh_ipv4`, `mesh_mac`, `mesh_mac_wlan`, `mesh_mac_wlan5`, `mesh_name`, `mesh_rssi`, `mesh_type`, and `mesh_upspeed`; the name is constrained to 1-28 ASCII letters, digits, or hyphens. | The captured form has only a reset button and no bound save/submit action. Therefore an accepted POST/positive `ACK` and the exact `id`/MAC-to-child identity retained by a fresh collection `READBACK` are unproven. The endpoint string and field list alone are not executable evidence. |
| Powerline node rename | The page reads rows from authenticated `GET data/DeviceList.json`. Its static form names candidate action `data/PWLineDevice.json` and the apparent row fields `id`, `pwline_downspeed`, `pwline_name`, and `pwline_upspeed`; the name uses the same 1-28 character constraint. | The captured form has only a reset button and no bound save/submit action. Therefore an accepted POST/positive `ACK` and the exact `id`-to-child identity retained by a fresh collection `READBACK` are unproven. The endpoint string and field list alone are not executable evidence. |
| Mesh identify | Static firmware proves `POST data/ActiveNode.json` with `mesh_paging=0/1` and `mesh_mac`. | Stable node `IDENTITY`, positive `ACK`, bounded lifetime, stop recovery, independent `READBACK`, and a user-operated disruptive-action roundtrip. |
| Powerline identify | Static resources suggest identify behavior but do not resolve a complete request. | Exact `ENDPOINT` and `FORM`, stable node `IDENTITY`, positive `ACK`, bounded lifetime, and independent `READBACK`. |
| Mesh node delete | Static firmware proves `deleteEntry=delete` and `mesh_serial_number`; the endpoint is read from the row's dynamic form action. | Exact `ENDPOINT`, stable serial `IDENTITY`, positive `ACK`, independent collection `READBACK`, typed confirmation, recovery, and a user-operated roundtrip. |
| USB storage safe remove | Static firmware proves `deleteEntry=delete`, storage `serial`, row `id`, and a returned `status` check; the endpoint is read from the row's dynamic form action. | Exact `ENDPOINT`, stable target `IDENTITY`, positive `ACK`, independent unmounted-state `READBACK`, failure recovery, and a user-operated disruptive-action roundtrip. |
| 5G receiver firmware update | Static firmware proves `auto_update=true` on the page's dynamic `JSONSource`. | Exact `ENDPOINT`/Referer, positive `ACK`, progress and reconnect `READBACK`, maintenance recovery, and a user-operated disruptive-action roundtrip. |
| 5G receiver factory/eSIM restore | Static firmware proves the separate `restore=0/1` request; `1` is selected only when the eSIM-reset checkbox is checked. | Exact `ENDPOINT`/Referer, explicit eSIM scope, positive `ACK`, progress/reconnect `READBACK`, typed confirmation, physical recovery, and a user-operated destructive-action roundtrip. |
| Remaining structured creation, editing, or deletion | Firmware pages expose clients, port rules, schedules, peers, shares, and telephony records. The eleven fixed beta actions above are the only exceptions. | Stable target `IDENTITY`, complete collection `FORM`, conflict behavior, `ACK`, and full-list `READBACK`; deletion also needs recovery and confirmation. |

`ENDPOINT` includes method, path, authentication, token, and Referer. `FORM`
includes every submitted and hidden field, allowed value, and dependency. `ACK`
means an explicit positive success response. `READBACK` is a fresh independent
state source. `IDENTITY` means one stable, unambiguous target. `SECRET` means
credentials or key material must never become entity state, attributes,
diagnostics, logs, or dashboard data.

The Mesh and Powerline rename cards are explicit blocked candidates. No Home
Assistant text entity or router command is created from these static forms.
Model or firmware gating cannot replace the missing submit, acknowledgement,
and independently verified collection-readback identity contracts.
Mesh identify has a start and stop request shape, but it remains deferred until
the firmware provides a dependable lifetime and readback contract. It will be
a bounded action, not a persistent switch.

The Administration catalog shows these candidates separately so their impact
is not hidden inside broad setup cards. Candidate badges use the same five risk
tiers as backend write contracts: `normal`, `sensitive`, `disruptive`,
`lockout`, and `destructive`. A badge is informational only; blocked candidates
still contain no executable control.

The four guarded and seven destructive actions above are executable only in the
version 0.3 beta Administration view. Their static request shapes, runtime
guards, and automated tests do not prove router acceptance. Promotion still
requires an explicitly authorized roundtrip and, where reversible, restoration
of the original state.

## Destructive, private, or deferred operations in the stable baseline

Stable version 0.2 does not expose:

- factory reset, configuration restore, or storage erase
- router, Wi-Fi, SIP, NAS, VPN, APN, or SIM credential changes
- private keys, pre-shared keys, recovery data, or secret export
- SIM PIN or PUK operations
- firewall disable
- arbitrary JSON, SOAP, or endpoint execution
- destructive client, Mesh, telephone, or storage deletion

These operations either risk unrecoverable loss, expose secrets through Home
Assistant, or cannot be verified safely.

## Structured admin operation contract

The native panel already provides a separate **Administration** view. Reviewed
native entities appear there as ordinary Home Assistant controls, while the
main **Dashboard** remains a reporting surface. An administrator-only WebSocket
read method additionally projects bounded, allowlisted fields from the
integration's current normalized cache for these collections:

- clients and Mesh nodes
- existing port-forward and port-block rules
- DNS-rebind exception domains and traffic-priority slot flags
- 2.4 GHz, 5 GHz, guest, and office SSIDs
- DDNS domain and update-server identity
- VPN peers
- telephony providers and lines, DECT handsets and repeaters, IP phones, and
  PBX clients
- USB devices, mobile receivers, storage devices, and NAS shares
- Powerline devices

This cached read method cannot contact the router and cannot execute an action.
It accepts only a loaded Speedport config-entry ID, returns only fixed,
explicitly allowlisted scalar fields, and limits each collection to 256 source
rows. A bounded identifier is included only where the reviewed view needs it to
distinguish otherwise anonymous rows. Raw source records, hidden form/request
details, passwords, keys, and other secret material are never returned. The
frontend requests the data only when an administrator opens the Administration
view, keeps it only in memory, and clears it when access or the selected router
changes. This read surface remains separate from the administrator-action
executor below.

Two firmware reads cannot be represented safely as Recorder-backed entities:
an IP-PBX client refresh and phonebook contact data. The Administration view
therefore provides administrator-only, on-demand read forms under the existing
IP-PBX and phonebook capability cards. Inputs are restricted to the firmware's
five phonebook indexes, an optional single-letter prefix, and bounded opaque
row identifiers. Phonebook results also include bounded total and remaining
entry counts when those exact fields are returned. Results pass through fixed field allowlists and are escaped
again before rendering. They never enter coordinator data, entities,
diagnostics, logs, URLs, or browser storage. A result remains only in the
current panel and is cleared when the user leaves Administration, changes
router, loses administrator context, disconnects the panel, starts a
replacement query, or explicitly clears it. Per-query and global rate limits
protect the router session. These reads never call a Home Assistant service or
change a router setting.

The Administration view also exposes an explicit **Read-only capability
inventory** diagnostic action. It performs a fresh, bounded pass over every
registered JSON candidate contract, using the exact endpoint, authentication,
and Referer tuple. Identical tuples are read once and shared across the feature
families that reference them. The action never runs during setup or polling,
never calls Status/TR-064/WAN telemetry, never invokes a reviewed management
command, and never reloads the config entry. It is serialized with polling and
commands through the same operation lock.

Only successful value-free response schemas are retained. Unsupported sources
and isolated protocol failures are counted without storing response bodies or
error text. Authentication, connection, decoding, session-busy, or final
session-release failure aborts publication and preserves the previous
inventory atomically. Diagnostics distinguish complete, partial, and failed
attempts and expose only safe counts, timestamps, and an exception class for a
fatal failure.

The integration ships a fixed administrator-action executor for the eleven beta
operations above; it is not a generic editor. Native scalar and bounded action
entities continue to use ordinary Home Assistant services. List, secret,
upload, delete, reset, and maintenance operations can enter this executor only
as fixed, reviewed operations with these invariants:

1. A static internal descriptor binds one exact operation to its model,
   firmware, capability, input schema, direct client method, risk class,
   identity rules, sensitive fields, and readback verifier. A request can
   never supply an endpoint, Referer, method, router command, or arbitrary
   field name.
2. The backend requires a Home Assistant administrator and entry-scoped
   control permission. It resolves a loaded integration entry, never a
   user-supplied host or address.
3. Targeted actions first return a bounded label and a 60-second, single-use
   token. The server binds that token to the user, entry, operation, target,
   private context, management generation, and current session. Untargeted
   enrollment actions do not use a target token.
4. Execute consumes the token before mutation, repeats support, schema,
   identity, capability, session, and stale-state checks under the integration
   operation lock, then performs a fresh target/state preflight and sends at
   most one exact request. An explicit negative response is rejected. A
   transport or decoding ambiguity is reported as outcome unknown and is never
   retried. Bounded independent readback must verify the result, and the router
   session is released on every path.
5. Guarded actions require explicit confirmation. Delete operations require
   their fixed operation phrase and display target-specific recovery guidance.
   Reset, restore, upload, and other maintenance operations remain blocked
   until their additional recovery prerequisites are proven. Frontend
   confirmation alone is never an authorization boundary.
6. Secrets are write-only one-shot inputs with explicit keep-existing or
   replace semantics. They never enter config-entry options, entity state,
   attributes, coordinator data, diagnostics, logs, Repair issues, WebSocket
   results, or dashboard state. Private downloads use authenticated,
   no-store, expiring, single-use delivery bound to the requesting admin.

Successful administrator operations return only a fixed verified status and a
value-free result field: `active`, `deleted`, or an enrollment lifecycle.
Unknown operations, extra fields, changed targets, expired or reused tokens,
explicit rejection, ambiguous outcomes, and mismatched readback fail closed.
No generic Home Assistant service is provided.

## Development and testing policy

Setup, discovery, polling, diagnostics, dashboard rendering, and automated
tests never change router settings. A native write runs only after a Home
Assistant user invokes its specific entity or service. A beta administrator
action runs only after an administrator opens its panel card, completes its
server-enforced confirmation, and submits it. Development validation against a
physical router has been limited to read requests plus the router's required
login and logout lifecycle; none of the eleven administrator actions has been
sent to the router.

The first validation of a staged control is always user-driven: record the
current value, change exactly one setting, require a positive acknowledgement,
read the same state independently, restore the original value, and read it a
second time. A failed or ambiguous acknowledgement is never retried. Internet,
Wi-Fi, telephony, firmware, LAN-address, or rebooting operations require an
appropriate maintenance window and recovery path.
