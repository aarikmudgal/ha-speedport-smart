# Changelog

All notable changes to Telekom Speedport Smart are documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses the
structure recommended by [Keep a Changelog](https://keepachangelog.com/).
Automated feature-branch prereleases are intentionally not listed one by one.

## [Unreleased]

## [0.3.0] - 2026-09-03

### Upgrade notes

- Update the existing integration through HACS, restart Home Assistant, then
  reload the dashboard browser page. Do not delete and recreate the integration.
  The domain remains `speedport_smart`; retained entity identifiers, configured
  options and their existing Recorder history are preserved.
- Obsolete beta control and router-global NAS placeholders are removed during
  upgrade. Adjust automations that referenced them; supported replacements live
  in Administration. The removed router event stream is not restored.
- The expanded Administration editors are English-only and exact-firmware
  gated. A stable integration release does not certify untested live router
  writes. Their warnings, explicit confirmations and verification limits remain
  in force. Review the [0.3.0 release notes](docs/releases/0.3.0.md) before using
  network, credential, firmware or reset operations.

### Added

- A compact Dashboard with a download/upload history graph offering 5-, 15-,
  30- and 60-minute windows, defaulting to 15 minutes, live
  sample values, paired Wi-Fi band summaries, DSL sync/capacity, mobile receiver
  signal/details and an explicitly identified wired-device list. Graph history
  comes from Home Assistant Recorder; it adds no router polling and preserves
  existing entity history and statistics.
  Explicit timeframe changes read the selected Home Assistant history; plotted
  points keep actual observed values and timestamps rather than invented data.
- A separate downloaded/uploaded volume graph adds valid nonnegative differences
  between recorded cumulative-byte observations and the existing live stream.
  It shares the rate graph's 5-, 15-, 30- and 60-minute window selection and
  chooses decimal MB, GB or TB units automatically. Resets, stale/unavailable
  samples and long gaps break a segment and mark valid subtotals partial. It
  does not integrate rate estimates, interpolate the window boundary, change
  Recorder configuration or add router requests.
- Automatic selected-page settings recovery after management-session changes
  or restored access, with stale-read cancellation and no automatic writes.
- Mouse, touch and keyboard inspection of WAN history samples, showing observed
  speeds and timestamps without filling gaps with invented values.
- Larger download/upload readouts that open the corresponding Home Assistant
  entity details, including when a live rate is temporarily unavailable. Both
  readouts remain side by side on mobile, with each value and its unit kept on
  one stable line and numeric space for four integer digits plus two decimals. The redundant
  "Latest sample" subtitle is removed; missing-sample warnings remain.
- Separate reported LTE signal strength and LTE band in the Mobile receiver
  overview, linked to their actual Home Assistant entities.
- Actual per-device LAN link rates in the overview, with directional rates
  when reported and an explicit missing-speed state.

- DHCP and SSDP discovery hints with private-unicast IPv4 filtering, an exact
  captured SSDP fingerprint, a public HTTP status preflight, user confirmation,
  exact host/serial deduplication, and a second read-only identity check. Only
  the Status API's exact validated Speedport Smart 4R Typ A model is accepted;
  discovery never relocates an entry or sends stored credentials to a newly
  announced host.
- A standard Home Assistant device-configuration link to the normalized local
  Speedport web-interface URL.
- The exact public-Status `domain_name` value as bounded administrator-only
  technical text, without treating it as a router model, DNS setting, or
  control.
- Two exact `LAN.json` IPv6 firmware flags in the administrator-only technical
  view. Their undocumented semantics are not guessed, and they do not create
  native entities or controls.
- Four guarded Administration actions for DECT handset and repeater
  enrollment, per-handset paging, and VoIP line activation, plus seven typed
  destructive actions for DECT handset/repeater disconnect and VoIP provider,
  VoIP number, IP-PBX client, phonebook entry, or NAS share deletion.
- A distinct diagnostic timestamp for the firmware-reported Internet
  connection start, while preserving the independent online-duration sensor.
  Ambiguous timestamps without an explicit UTC offset remain unavailable.
- An immutable conformance registry for all fixed native read entities, binding
  each sensor and binary sensor to its normalized path and capability gates.
- Exact semantic Administration ownership for every reviewed control and
  administrator-only cached read section, with accessible expandable groups.
- Central immutable risk, dashboard-confirmation, and execution-surface metadata
  for every reviewed router command. Destructive commands cannot be exposed as
  native entities and use an administrator-only backend action flow.
- A fixed administrator-action executor with exact model, firmware, endpoint,
  Referer, capability, handler, input, confirmation, and readback contracts.
  Targeted actions use 60-second single-use grants, repeat a fresh identity
  preflight under the operation lock, send at most one mutation, perform bounded
  independent readback, and release the router session.
- Read-only mesh topology details from the proven DeviceList endpoint, including
  directional link speeds, exact per-node 2.4/5 GHz MAC identities, and Wi-Fi
  generation metadata for managed clients.
- An offline, stdin-only browser-capture sanitizer that verifies one explicit
  reversible scalar apply/readback/rollback sequence and emits only bounded,
  privacy-safe contract evidence.
- An explicit, candidate-only capability inventory action that reads every
  registered JSON request contract once, stores only value-free response
  shapes, preserves active runtime capabilities, and reports safe
  complete/partial/failure diagnostics without reloading the integration.
- Separate Dashboard and Administration views in the native Home Assistant
  panel, with administrator-only, on-demand structured details projected from
  the existing normalized cache without additional router traffic.
- Administrator-only, rate-limited, ephemeral read forms for one IP-PBX client
  status refresh and bounded phonebook search/contact details, including the
  router's exact bounded total and remaining-entry counts. Private results never
  enter entities, Recorder, coordinator data, diagnostics, URLs, or browser
  storage.
- A private IP address information screen with the native IPv4/IPv6 addresses,
  gateways, DNS servers and reported IPv6 prefixes. Opening the page performs
  a bounded, authenticated read for the exact reviewed firmware; missing values
  remain explicitly unreported. These results add no entities or background
  polling and stay out of Recorder, diagnostics and browser storage.
- A responsive Administration view organized into the six router tabs Overview,
  Status, Internet, Telephony, Network and System, with contextual left
  navigation and a mobile page menu. Its 69 content pages and 13 navigation
  groups map 120 existing router
  feature entries and 110 existing settings editors. These navigation counts
  do not imply that every feature is writable or supported. The organization
  follows a read-only audit of all 69 real-router screens, including the
  sidebar-only Prioritization page, while using Home Assistant's theme.
- Page-local automatic reads for each existing settings section and selected
  target, with separate inline forms, paced requests, independent drafts,
  grouped Wi-Fi and schedule fields, and explicit Refresh, Save changes
  and Cancel changes controls. Saves retain exact typed confirmation,
  requester-bound revisions and expiry checks; secrets are never prefilled.
  Dirty target changes require discard confirmation. Navigation and failed
  responses never repeat writes. No live writes were tested for this redesign;
  router owners still need to validate writes and recovery explicitly. See the
  [Dashboard and Administration guide](docs/dashboard.md).
- Structured, revision-bound editors for Internet providers, DNS, LAN/DHCP,
  Wi-Fi identities/radios/security/schedules, forwarding ranges, blocking rules,
  parental rules, DNS exceptions, prioritization and Dynamic DNS configuration.
- Telephony provider/number/client creation and editing, DECT and analog-line
  settings, number assignments, local phonebook lifecycle and contacts, and a
  two-step online-phonebook link with a separate merge/replace confirmation.
- Private call-history viewing and CSV export, separate category clearing,
  local phonebook import/export, system-log download and Router-Pass download.
- VPN peer creation/deletion and credential rotation with explicit, temporary
  private configuration downloads after supported readback verification.
- Storage share and media-folder editors, USB safe removal, Mesh maintenance,
  Powerline rename, mobile receiver actions and system settings where the
  complete fixed firmware request is evidenced.
- Guarded router password changes, backup/restore, firmware file transfers,
  factory reset and reviewed network-mode maintenance. Lockout and destructive
  operations require explicit readiness checks and typed confirmation.
- A firmware-specific coverage matrix that separates implemented operations,
  read-only reporting, incomplete contracts and live write testing still owed
  by the router owner. No router settings were changed during development.
- Expanded privacy-bounded read models for LAN/DHCP, Wi-Fi identities and radio
  configuration, managed clients, Mesh and Powerline nodes, port forwarding
  and blocking, DNS exceptions, traffic-priority slots, DDNS, telephony, DECT,
  PBX, USB storage, NAS, and mobile receivers when the firmware returns them.
- Seven exact administrator-only read additions: two Mesh radio MACs, storage
  serial, NAS-share ID, VPN-peer ID, VoIP line-to-provider ID, and phonebook
  remaining-entry count. None becomes a Recorder-backed native scalar.
- Exact automatic-family routing for VoIP-provider and PBX-client responses, so
  their reviewed safe rows reach the existing normalized administrator view
  while names, numbers, usernames, and credentials remain excluded.

### Changed

- Auto WAN polling starts at 5 seconds and steps through 4, 3, 2 and 1 second
  after five consecutive successful WAN reads at each cadence. The final
  1-second cadence also requires five successes before being marked Stable.
  Any polling failure for a supported WAN source resets the success count and
  enters a fixed 60-second Cooldown before retrying the same cadence. Repeated
  failures restart the same cooldown, without incremental backoff or a sticky
  slower floor. Manual mode never polls faster than requested and uses the
  same failure cooldown. Other groups retain their configured cadences and
  data scopes, subject to the panel priority described below.
- A visible, focused panel claims an expiring priority lease: Dashboard
  prioritizes WAN samples, while Administration prioritizes explicit settings
  operations. Automatic Normal and Slow reads wait without refreshing cached
  timestamps. Hiding or leaving the panel, losing focus or disconnecting
  releases the lease; a 45-second expiry covers lost clients. Existing router
  transactions remain atomic, and missed background updates are not replayed.

### Fixed

- WAN scheduling uses anchored polling slots instead of response completion
  plus another interval, avoiding skipped one-second reads caused by coordinator
  phase rounding. Requests remain serialized; missed slots are skipped rather
  than queued or replayed. The dashboard distinguishes target and observed
  sample intervals. Rates use the latest two valid counter observations and
  their actual monotonic elapsed time, without a rolling average. Repeated
  totals do not establish a guaranteed router refresh interval. Recorder
  history remains enabled.
- WAN reads remain exclusively in the Fast sequence. Normal and Slow no longer
  insert a WAN read immediately after a protected web session, preventing a
  transient session-handoff rejection from repeatedly restarting WAN Cooldown.
  Normal DSL reads retain bounded busy retries. Poll diagnostics separate
  lock-wait and work duration; long active operations can still delay samples.
- Concurrent coordinator refreshes share in-flight work, including timer calls
  waiting behind Home Assistant's refresh debounce lock. Deferred work is not
  replayed as duplicate router reads, failures are handled by their owning
  refresh, and cancellation of a waiting caller does not cancel that owner.
- Supported Administration settings now use one styled editor instead of
  duplicate editor and legacy entity controls. An offline audit covers all
  110 advertised settings contracts and 454 fields, checking input types,
  disabled editing before a valid read, secret non-prefill and no automatic
  saves. Read-only information no longer carries an inappropriate write warning.
- Receiver LED and bonding settings can obtain missing serial/model identity
  from a fresh, fixed receiver-information read while preserving the original
  mode values. Missing or conflicting identity still rejects the read.
- The typed receiver LED editor now accepts the firmware's symbolic `On`,
  `Timer` and `Off` values as well as numeric codes. This fixes a separate
  parser mismatch that rejected valid current settings before editing.
- Confirmed EasySupport, USB, receiver, Mesh, firmware, VPN, Smart Home and
  call-list prerequisites now have specific, privacy-safe loading messages.
  Missing target inventories remain unavailable rather than being treated as
  empty. Failed reads still provide no editing revision, and absent firmware
  offers are not labelled as proof that firmware is up to date.
- A newly available inline section now loads even when another form is open,
  without discarding its draft or revision. Reads wait for an in-flight save,
  preserve its result, and are cancelled on page or identity changes. Repeated
  metadata and WAN updates do not retry failed sections or repeat writes.
- Dashboard summary cards now fill each row after the full-width Wi-Fi section,
  including partial rows on tablets, without reserving empty desktop columns.
- WAN graph freshness now prefers the newest valid successful sample timestamp
  instead of the minute-rounded diagnostic sensor. Live observations tolerate
  a Home Assistant clock up to five seconds ahead of the browser without
  rewriting timestamps; larger clock leads, genuinely stale values and
  unavailable samples still produce gaps. This chart fix does not change the
  WAN polling policy described above.
- Native call-list pages load their own category automatically. Concurrent
  settings saves blocked before dispatch now explicitly report that nothing
  was sent; session recovery preserves the outcome of an active save.
- Rapid navigation no longer exhausts settings revisions left by previously
  visited pages: the bounded store replaces only the oldest revision owned by
  the same administrator and login session. Failed read projections preserve
  existing approvals; expired or discarded revisions never authorize writes.
- The parental-rule display setting now appears under Child protection - Time
  rules, matching the router's Display switch, instead of Energy-saving mode.
- Structured private drafts and call-history results survive ordinary WAN
  telemetry rendering, but are cleared on navigation, router/user changes and
  disconnect. Exact schedule end time `24:00` is supported without accepting
  invalid times such as `24:01`.
- Phonebook target selection uses actual book membership rather than invented
  slots, and configuration approvals bind stable target identity as well as
  current values. Creation verification follows the router-assigned row ID.
- Page-scoped Internet privacy, WPS configuration, Wi-Fi access, and 5G
  receiver reads now include the firmware's current HTTP page token. A
  decoded-empty startup response receives one bounded retry per reviewed
  endpoint, while unrelated reads retain their existing request cadence. The
  separate WPS transaction-status poll remains tokenless as required by the
  firmware.
- The 5G receiver LED control now accepts the firmware's exact semantic
  readback values (`On`, `Timer`, and `Off`) and maps them to the existing
  numeric command contract without widening accepted fields or values.
- Internet privacy and 5G receiver LED controls now use their exact firmware
  fields and capability families, so valid current-state readback no longer
  leaves the controls unavailable.
- WPS availability now follows the router's stable radio, visibility,
  encryption, guest-network, and firmware prerequisites while its transient
  lifecycle is read independently. Unavailable controls report a bounded,
  localized reason instead of failing silently.
- Public Status failures no longer make healthy WAN counters appear available
  merely because both sources share the fast coordinator.
- The Recorder-backed WAN sample timestamp now advances at minute precision to
  avoid high-frequency Activity and history churn; the native dashboard keeps
  the exact live sample time from runtime telemetry.
- Immediate management commands now verify the exact scalar or collection
  identity/value readback before reporting success; transient and disruptive
  commands are explicitly refresh-only or deferred.
- Device names, identifiers, MAC addresses, and certificate fingerprints now
  use the same strict preflight validation as their router handlers, rejecting
  invalid input before any router request.
- Normalized cross-family data now publishes native entities only after the
  router actually returns that semantic root; read-only projections can no
  longer unlock an unrelated management command.
- The Administration tab now renders cached data immediately, refreshes it on
  re-entry, and coalesces a forced post-action refresh behind any active read
  instead of dropping the newest state.
- Native command execution rechecks the exact authenticated capability,
  endpoint family, and management-session gate after acquiring the router
  operation lock, closing a capability-loss race before router I/O.
- Dashboard and Administration navigation now uses the full panel width, with
  a single visible tab spanning the complete selector.
- Temporary router-session contention no longer changes whether a reviewed
  control is supported; current execution availability remains a separate gate.
- Administration controls and shared cached collections render under one
  deterministic feature owner instead of appearing in multiple sections.
- Wi-Fi generation is no longer mistaken for a radio band, and firmware link
  speeds are no longer presented as live traffic throughput.
- Unproven router-global parental-time and phonebook-entry native entities remain
  withheld. Phonebook search/detail and deletion instead use bounded ephemeral
  administrator flows that never publish contacts to Recorder.
- Read-authorized users without control permission retain reporting placement
  for reviewed entity state instead of losing it from both panel views.
- Client and mobile-receiver child entities now appear in their matching
  Administration sections, and port-block totals aggregate distinct firmware
  rule groups consistently without merging colliding rule IDs.
- Unknown Wi-Fi channel-width codes, malformed DNS exception names, free-form
  telephony failure text, and phone-like line identifiers now fail closed.
- NAS folder enablement, access, and read-only flags now remain scoped to
  identified administrator-only share rows. The three unproven router-global
  NAS binary sensors are retired and removed from the entity registry on
  upgrade, preventing permanent unavailable entries.
- Nine retired beta router-control placeholders are removed from the entity
  registry on upgrade, preventing permanent unavailable button and switch
  entries while preserving unrelated and user-managed entities.
- Administrator actions now refresh every affected cached capability family
  before the panel reloads, and invalidate protected cached data if that refresh
  fails. Phonebook target selection also reloads independently of any open
  confirmation dialog.
- Repeated human-readable target names now remain unambiguous through bounded
  opaque row references, including distinct accessible button names for screen
  readers and action-specific truncation limits.

### Security

- Private administrator reads, settings, targets and results use bounded,
  authenticated, non-cached HTTP to avoid Home Assistant WebSocket debug and
  queue-error payload logging. The legacy private WebSocket commands no longer
  execute router operations. Reload the panel after upgrading.
- Configuration approvals bind the administrator, active login session, entry,
  target and private revision, expire in memory and are consumed before any
  mutation. Stale configuration and ambiguous writes are never replayed.
- Password changes use isolated sessions and update Home Assistant's stored
  credential only after a fresh login verifies the same router. An uncertain
  change suspends protected credential retries until reauthentication.
- Private transfers are bounded, single-use and administrator-session-bound;
  uploads bind the confirmed file digest. Restore, firmware and external-sync
  results do not claim independently verified completion when it is unknown.
- Subscriber telephone identifiers, telephone credentials, call identifiers,
  and authenticated login-state metadata are now explicitly rejected at the
  normalization boundary.
- Dashboard controls now derive their warning and confirmation policy from the
  same exact-firmware write registry used by backend command gating. Unknown
  switch-, button-, select-, text-, or update-shaped entities remain read only.
- Confirmation policy, risk, target state, and typed phrase are rechecked at
  execution time so a metadata refresh or concurrent state change fails closed.
- Raw HAR bodies, browser headers, authentication material, router origins,
  subscriber identifiers, and non-allowlisted values never enter sanitized
  control-contract evidence.
- Administrator structured details use fixed field allowlists and collection
  limits, remain browser-memory-only, and are cleared on router, connection, or
  permission changes.
- SSID and DDNS identity values are excluded from Recorder-backed native
  entities and exposed only to Home Assistant administrators through the
  bounded in-memory view. Prototype-inherited section IDs are rejected.
- A latched firmware write-block state cannot be cleared by transient missing
  status, while explicit safe readback and existing session backoff continue to
  gate all mutating requests.
- Administrator-action target fingerprints, full telephone numbers, and private
  target context remain backend-only. The requesting administrator's in-memory
  panel receives only contract-bounded selector fields, including exact router
  row IDs as opaque `reference` values and masked four-digit VoIP suffixes, plus
  single-use action tokens. Fixed typed phrases, one-mutation execution, no
  ambiguous-write retry, and strict session cleanup apply to every destructive
  action.
- Target grants are bound to the requesting Home Assistant administrator and
  refresh-token session, erased on use, management-generation change, expiry,
  unload, or shutdown, and never published when final session cleanup fails.
  Exact-ACK actions treat missing or malformed acknowledgement as an unknown
  outcome even when a later read happens to match.
- The expanded administrator actions are based on exact downloaded firmware
  contracts and automated tests. No live router mutation or
  change/readback/rollback roundtrip was performed during development. Their
  inclusion in 0.3.0 does not change that evidence level or certify successful
  changes on a physical router.

## [0.2.0] - 2026-09-01

### Added

- Evidence-backed router management controls for capabilities exposed by the
  installed Speedport firmware.
- Guarded Hybrid bonding, Internet privacy-level, and 5G receiver LED controls
  for the exact reviewed Smart 4R Typ A firmware, staged for user roundtrip
  validation.
- German integration and dashboard translations.
- Expanded management safety, dashboard, and protocol regression coverage.
- Adaptive WAN-counter polling that learns the fastest proven cadence, exposes
  its live mode and state, and backs off safely when the router reports a busy
  telemetry lease.
- A bounded, GET-only developer utility for sanitized UPnP/TR-064 service
  descriptor inventory.

### Changed

- Management controls are capability-gated, serialized, verified by state
  readback, and grouped by function in the native dashboard.
- Enumerated controls use native Home Assistant select entities with fixed
  semantic options; the dashboard never receives router endpoint or payload
  details.
- Protected-session failures invalidate cached authenticated-family values
  while preserving current public status, preventing stale protected data.
- Managed-client and port-forward writes now fail closed unless fresh rows
  match strict stable identity, complete-form, and rule-fingerprint checks.
- Per-band Wi-Fi state now follows the firmware `wlan_band` contract: `0` for
  both bands, `1` for 2.4 GHz only, and `2` for 5 GHz only.
- DDNS `use_dyndns` is interpreted as enablement, while VPN `vpn_status`
  represents profile enablement rather than tunnel connectivity.
- Client `access_possible` is exposed only as read-only Internet-access
  allowance and is not inverted into an unproven pause control.
- Write controls now require both a current capability and the exact reviewed
  Smart 4R Typ A firmware contract; unknown firmware remains read-only.
- WAN and public-status polling use independent due times, so a failure in one
  source cannot starve the other. Confirmed cumulative WAN counters retain
  their last sample while live rates and interface state become unavailable.
- Fixed controls and telemetry entities discovered after a degraded startup
  are added without requiring an integration reload.
- Dynamic child entities use localized names, distinct port-forwarding rules
  retain their router-provided labels, and invalid legacy client names remain
  safely read-only.

### Security

- Router discovery and automated validation remain read-only. Commands run
  only after an explicit Home Assistant user action; unsafe credential,
  factory-reset, restore, and destructive-delete operations remain excluded.

## [0.1.1] - 2026-08-31

### Fixed

- Client presence entities now report `home` or `not_home` from router
  connectivity instead of remaining `unknown`.

## [0.1.0] - 2026-08-31

### Added

- Responsive native Home Assistant sidebar dashboard with theme-aware,
  hierarchical capability and child-device grouping.
- Configurable fast, normal, and slow polling intervals.
- Capability-driven entities across WAN, DSL, Hybrid/mobile, Wi-Fi, Mesh,
  clients, telephony, router services, controls, and diagnostics.
- Live aggregate WAN byte totals, packet/error counters, download/upload rates,
  and utilization.
- Management-session diagnostics, Home Assistant Repairs, and a safe read-only
  retry action.
- Privacy-redacted downloadable diagnostics.
- Privacy-safe dark-theme desktop and mobile dashboard previews.
- HACS release archive configuration, repository validation, community files,
  and stable/beta release automation.

### Changed

- Public integration name standardized as **Telekom Speedport Smart** while
  retaining the stable **speedport_smart** domain.
- Supported entities and controls are enabled by default and remain
  capability-gated.
- Temporary source failures preserve registered entities and report them as
  unavailable instead of removing them or presenting stale state.
- Byte totals and elapsed durations use Home Assistant-friendly semantic
  metadata and adaptive display formatting.

### Security

- Router controls remain idle unless explicitly invoked.
- Diagnostics redact credentials and sensitive network, telephony, client,
  mobile, and VPN data.

[Unreleased]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/aarikmudgal/ha-speedport-smart/releases/tag/v0.1.0
