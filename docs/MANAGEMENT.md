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

| Class | Stable version 0.2 baseline meaning |
| --- | --- |
| Implemented read-only | A discovered response is normalized and exposed without sending a setting request. |
| Implemented writable | An allowlisted request has a complete endpoint and form contract, positive acknowledgement handling, independent readback where the action permits it, and stable target identity when it addresses a row. |
| Staged guarded writable | The current firmware proves one exact scalar endpoint, field, value domain, and read source. The beta control additionally requires a fresh pre-read, positive acknowledgement, and matching post-write readback at runtime, but still needs one user-authorized change and rollback before promotion. |
| Firmware-evidenced but blocked | Public firmware material names a page, field, endpoint candidate, or request shape, but at least one required proof is missing. No control is exposed. |
| Destructive, private, or deferred | The operation can erase configuration, interrupt recovery, or reveal credentials or key material, or it lacks a safe Home Assistant interaction model. It is excluded from the stable version 0.2 baseline; version 0.3 can add it only through the structured admin contract below after all proof gates pass. |

No write is promoted as proven without a complete endpoint, form,
acknowledgement, readback, and stable-identity contract. Static reconnaissance
alone never creates a generic request or form. Three exact, reversible scalar
controls are staged for an explicit user roundtrip; they retain strict runtime
acknowledgement and readback gates and never retry a rejected or ambiguous
request.

Read coverage is independent of write eligibility. A missing write contract
never suppresses a safe, non-secret value that the router returns. Readable
settings and measurements will be normalized and exposed as read-only entities
or an administrator-only live view according to their privacy and persistence
requirements. Passwords, keys, recovery material, and raw private records are
never copied into entity state, diagnostics, logs, or dashboard metadata.

Version 0.3 development uses one immutable safety policy for both backend
contracts and dashboard controls. Each reviewed command has a normal,
sensitive, disruptive, lockout, or destructive risk tier plus a none, confirm,
or typed dashboard-confirmation presentation. The dashboard receives only
those semantic labels, never router endpoints or request fields, and revalidates
the current policy and target state immediately before invoking the native Home
Assistant service. This dialog is user-experience protection, not backend
authorization: native entities remain callable through Home Assistant services
and automations. Destructive commands are therefore forbidden from native
entity exposure. Before the first destructive command is added, its admin-only
action surface must require a single-use backend grant bound to the exact
command, target, parameters, current state, and documented recovery
prerequisites. Unknown control-shaped entities fail closed as read only.

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
| Office Wi-Fi switch | `data/Modules.json`, `wlan_office_active=0` or `1` | Fresh `wifi.office.enabled` state | Available only on firmware that exposes office Wi-Fi |
| WPS button | `data/WLANAccess.json`, `wlan_add=on` and `wps_key=connect` | Refreshes `data/WPSStatus.json` | Opens the router's normal WPS window |
| Existing port-forward switch | Fresh `data/PortuwMain.json` rule with the same ID, name, and non-state rule fingerprint, then `portuw_active=0` or `1` | Fresh state for the same unchanged rule semantics | Does not create, edit, delete, or mutate a reused or retargeted rule ID |
| Client name text entity | Fresh complete managed-device row with only `mdevice_name` changed | Same row kind, row ID, required MAC address, and new name | Accepts 1 to 28 letters, numbers, or hyphens |
| Fixed DHCP switch | Fresh complete managed-device row with only `mdevice_fix_dhcp` changed | Same row and fresh fixed-DHCP flag | Keeps all current address fields unchanged |
| Hybrid bonding switch (staged) | Fresh `data/LTE.json`, then only `use_bonding=0` or `1` | Positive acknowledgement plus fresh `hybrid.enabled` | May interrupt Internet traffic; requires user change/readback/rollback validation |
| Internet privacy select (staged) | Fresh `data/IPPrivacy.json`, then only `lan_privacy_policy=0`, `1`, or `2` | Positive acknowledgement plus fresh `internet.privacy_level` | Options are Off, Level 1, and Level 2; requires user change/readback/rollback validation |
| Receiver LED mode select (staged) | Fresh `data/LTE.json`, then only `ex5g_led_mode=0`, `1`, or `2` | Positive acknowledgement plus fresh `receiver.led_mode` | Options are Use LEDs, switch off after timeout, and Do not use LEDs; requires user change/readback/rollback validation |

Stateful switches skip a request when the router already reports the desired
state. After a request, the integration performs one serialized readback and
raises a Home Assistant error if the expected value is missing or different.
Reboot and Internet reconnect cannot use an immediate readback because the
requested action deliberately breaks the connection.

Client rename and fixed DHCP preserve the complete current row returned by
`data/DeviceList.json`. Both require the same stable row ID and nonempty MAC
address. The integration rejects incomplete rows, unknown form fields,
duplicate matches, changed identities, and unsupported row types before sending
a request.

The staged scalar controls reject missing, duplicated, nested, wrong-type,
case-shifted, or out-of-range current values before a POST. Their entities are
created only for the exact reviewed model and firmware, only when the matching
read capability and current state exist, and only when management controls are
enabled. The dashboard sends standard Home Assistant switch/select service
calls; it never receives router endpoints, field names, or numeric codes.

## Implemented read-only coverage

Read-only fields do not imply a matching write. In particular:

- `wlan_band=0`, `1`, and `2` mean both bands, 2.4 GHz only, and 5 GHz only.
  Dedicated per-radio fields remain authoritative when present.
- `use_dyndns` is interpreted as DDNS enablement.
- `vpn_status` is interpreted as VPN profile enablement, not tunnel
  connectivity. Connectivity requires a separate connection field.
- Client `access_possible` is exposed as read-only Internet-access allowance.
  It is not inverted into an unproven pause state or writable switch.

| Area | Current read-only coverage |
| --- | --- |
| Internet, WAN, DSL, and Hybrid | Connection state, addressing, uptime, DSL metrics, WAN totals, packets, errors, live rate, and utilization |
| Wi-Fi | Correct global and per-band state, channels, client counts, guest and office state, and Mesh topology |
| LAN, DHCP, and DNS | Clients, presence, signal, links, DHCP state, leases, LAN ports, and client access allowance when returned |
| Mesh and Powerline | Topology and node metrics |
| Telephony and DECT | Registration, lines, calls, handsets, IP phones, and phonebook counts when exposed |
| USB and NAS | Device state, mount state, capacity, free space, media state, and temperature when exposed |
| DDNS, VPN, parental controls, and security | DDNS enablement and status; VPN profile enablement, connection, type, and peer state; parental profile state; firewall, rebind-protection, and remote-management state when exposed |
| System, energy, update, and notifications | Uptime, health, temperature, firmware, and update metadata when exposed |
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
| DDNS changes | `DDNS.json` and `DynDNS.json` plus `use_dyndns` provide endpoint and state candidates. | Exact save `ENDPOINT`, complete provider `FORM`, `ACK`, independent `READBACK`, and `SECRET` handling for credentials. |
| VPN and WireGuard changes | `VPN.json`, `WireGuard.json`, `vpn_status`, and peer rows provide endpoint and state candidates. | Exact save `ENDPOINT`, complete `FORM`, `ACK`, separate enabled/connected `READBACK`, stable peer `IDENTITY`, and private-key or pre-shared-key `SECRET` handling. |
| UPnP, parental controls, and media server | Read-only fields and source descriptors exist. | Exact write `ENDPOINT`, complete `FORM`, `ACK`, and independent `READBACK`. |
| Mesh and Powerline rename or identify | Static resources suggest row forms and identify start/stop shapes. | Complete hidden `FORM`, stable node `IDENTITY`, `ACK`, and bounded lifetime plus independent `READBACK`. |
| Creation, editing, or deletion of structured records | Firmware pages expose clients, port rules, schedules, peers, shares, and telephony records. | Stable target `IDENTITY`, complete collection `FORM`, conflict behavior, `ACK`, and full-list `READBACK`; deletion also needs recovery and confirmation. |

`ENDPOINT` includes method, path, authentication, token, and Referer. `FORM`
includes every submitted and hidden field, allowed value, and dependency. `ACK`
means an explicit positive success response. `READBACK` is a fresh independent
state source. `IDENTITY` means one stable, unambiguous target. `SECRET` means
credentials or key material must never become entity state, attributes,
diagnostics, logs, or dashboard data.

Mesh and Powerline rename need proof of every hidden field in their
authenticated save forms. Mesh identify has a start and stop request shape, but
it remains deferred until the firmware provides a dependable lifetime and
readback contract. It will be a bounded action, not a persistent switch.

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

A structured editor will be added only with its first fully proven operation;
the integration does not ship an empty generic executor. Native scalar and
bounded action entities continue to use ordinary Home Assistant services.
List, secret, upload, delete, reset, and maintenance operations must instead
use an admin-only, typed transaction with these invariants:

1. A static internal descriptor binds one exact operation to its model,
   firmware, capability, input schema, direct client method, risk class,
   identity rules, sensitive fields, and readback verifier. A request can
   never supply an endpoint, Referer, method, router command, or arbitrary
   field name.
2. The backend requires a Home Assistant administrator and entry-scoped
   control permission. It resolves a loaded integration entry, never a
   user-supplied host or address.
3. A prepare phase performs a fresh read, validates the target and complete
   typed payload, and returns a short-lived, single-use challenge bound to the
   user, entry, operation, target, pre-state revision, and payload digest.
4. Execute consumes the challenge before mutation, repeats schema, identity,
   capability, session, and stale-state checks under the integration operation
   lock, sends one exact request, requires a positive acknowledgement, performs
   an independent readback, and always releases its router session. It never
   retries an ambiguous write.
5. Reversible edits require an explicit apply confirmation. Delete operations
   require the exact target phrase. Reset, mode, restore, upload, and other
   maintenance operations additionally require the exact router phrase plus
   proven backup and recovery prerequisites. Frontend confirmation alone is
   never an authorization boundary.
6. Secrets are write-only one-shot inputs with explicit keep-existing or
   replace semantics. They never enter config-entry options, entity state,
   attributes, coordinator data, diagnostics, logs, Repair issues, WebSocket
   results, or dashboard state. Private downloads use authenticated,
   no-store, expiring, single-use delivery bound to the requesting admin.

Successful structured operations return only a fixed verified status and an
opaque revision. Unknown operations, extra fields, changed targets, expired or
reused challenges, missing acknowledgements, and mismatched readback fail
closed. No generic Home Assistant service is provided; a proven operation that
needs automation receives its own named admin service and static schema.

## Development and testing policy

Setup, discovery, polling, diagnostics, dashboard rendering, and automated
tests never change router settings. A write runs only after a Home Assistant
user invokes its specific entity or service. Development validation against a
physical router is limited to read requests plus the router's required login
and logout lifecycle.

The first validation of a staged control is always user-driven: record the
current value, change exactly one setting, require a positive acknowledgement,
read the same state independently, restore the original value, and read it a
second time. A failed or ambiguous acknowledgement is never retried. Internet,
Wi-Fi, telephony, firmware, LAN-address, or rebooting operations require an
appropriate maintenance window and recovery path.
