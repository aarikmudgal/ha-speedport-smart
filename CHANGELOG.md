# Changelog

All notable changes to Telekom Speedport Smart are documented here.

This project follows [Semantic Versioning](https://semver.org/) and uses the
structure recommended by [Keep a Changelog](https://keepachangelog.com/).
Automated feature-branch prereleases are intentionally not listed one by one.

## [Unreleased]

### Changed

- Nothing yet.

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
