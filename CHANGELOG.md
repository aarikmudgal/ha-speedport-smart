# Changelog

All notable changes to Telekom Speedport Smart are documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses the
structure recommended by [Keep a Changelog](https://keepachangelog.com/).
Automated feature-branch prereleases are intentionally not listed one by one.

## [Unreleased]

### Added

- Evidence-backed router management controls for capabilities exposed by the
  installed Speedport firmware.
- Guarded Hybrid bonding, Internet privacy-level, and 5G receiver LED controls
  for the exact reviewed Smart 4R Typ A firmware, staged for user roundtrip
  validation.
- German integration and dashboard translations.
- Expanded management safety, dashboard, and protocol regression coverage.

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
- Known session contention immediately clears cumulative WAN and optional DSL
  telemetry, while indeterminate command timeouts back off before another
  action can be sent.
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

[Unreleased]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/aarikmudgal/ha-speedport-smart/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/aarikmudgal/ha-speedport-smart/releases/tag/v0.1.0
