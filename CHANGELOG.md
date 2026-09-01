# Changelog

All notable changes to Telekom Speedport Smart are documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses the
structure recommended by [Keep a Changelog](https://keepachangelog.com/).
Automated feature-branch prereleases are intentionally not listed one by one.

## [Unreleased]

### Added

- Central immutable risk, dashboard-confirmation, and execution-surface metadata
  for every reviewed router command. Destructive commands cannot be exposed as
  native entities and must use a future admin-only backend grant flow.
- Read-only mesh topology details from the proven DeviceList endpoint, including
  directional link speeds and Wi-Fi generation metadata for managed clients.
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
- A responsive Administration catalog covering 73 router-management features
  across Internet, telephony, Wi-Fi, LAN, Mesh, Powerline, security, storage,
  mobile receivers, and system services. Every entry distinguishes reviewed
  controls, related read-only evidence, blocked contracts, and unsupported
  local management.
- Expanded privacy-bounded read models for LAN/DHCP, Wi-Fi identities and radio
  configuration, managed clients, Mesh and Powerline nodes, port forwarding
  and blocking, DNS exceptions, traffic-priority slots, DDNS, telephony, DECT,
  PBX, USB storage, NAS, and mobile receivers when the firmware returns them.

### Fixed

- Wi-Fi generation is no longer mistaken for a radio band, and firmware link
  speeds are no longer presented as live traffic throughput.
- Unproven router-global parental-time and phonebook-entry entities are withheld
  until their separate read-only request contracts are implemented.
- Read-authorized users without control permission retain reporting placement
  for reviewed entity state instead of losing it from both panel views.
- Client and mobile-receiver child entities now appear in their matching
  Administration sections, and port-block totals aggregate distinct firmware
  rule groups consistently without merging colliding rule IDs.
- Unknown Wi-Fi channel-width codes, malformed DNS exception names, free-form
  telephony failure text, and phone-like line identifiers now fail closed.

### Security

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

[Unreleased]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/aarikmudgal/ha-speedport-smart/releases/tag/v0.1.0
