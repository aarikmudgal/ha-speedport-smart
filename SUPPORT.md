# Support and troubleshooting

Telekom Speedport Smart is an unofficial community integration. Deutsche
Telekom and the Home Assistant project do not provide support for it.

## Quick checks

### Setup cannot connect

- Confirm Home Assistant can resolve or reach **speedport.ip** or the configured
  router IP.
- Confirm the router password in the Speedport web interface.
- Use **Logout** in every open router web interface before retrying setup.
- Disable any other integration or polling tool connected to this router while
  setting up Telekom Speedport Smart.
- Start with **Use HTTPS** off. If using HTTPS, leave certificate verification
  off unless Home Assistant trusts the router certificate.
- Confirm Home Assistant is 2025.12.0 or newer.

### Protected entities become unavailable

Another browser session or router integration may own the management lease.
Disable competing polling integrations, select **Logout** in the router web
interface, then press **Retry protected data (log out of the router first)** or
complete the Home Assistant Repair flow. Closing the browser tab is not always
enough. Do not routinely restart the router.

### Live bandwidth is zero or changes in steps

The router refreshes cumulative counters in batches. An unchanged sample
correctly produces zero throughput. Keep the recommended five-second fast
interval for a smoother and more reliable rolling rate. The data is aggregate
WAN traffic, not per-device throughput.

### Traffic totals become small after a reboot

The counters belong to the current router uptime and can reset on reboot. The
integration starts a new rate epoch so it does not publish a negative rate or a
false spike. Use Home Assistant Utility Meter helpers for billing-style daily
or monthly totals.

### An expected entity is absent

Entity creation is capability-driven. The current model or firmware may not
return that source, or a protected discovery pass may not have succeeded. Log
out of the router UI, retry protected data, wait for the relevant polling
group, and download diagnostics. An absent capability is not represented by a
permanently unavailable placeholder.

### The sidebar panel is missing

- Confirm the integration is loaded without an error.
- Perform the Home Assistant restart required after install or upgrade.
- Confirm another custom panel is not already using **/speedport-smart**.
- Clear the browser cache only after the Home Assistant checks above.

## Opening an issue

Use
[GitHub Issues](https://github.com/aarikmudgal/ha-speedport-smart/issues) for a
reproducible bug or supported-feature request. Include:

- Home Assistant version
- Telekom Speedport Smart version
- router model and firmware
- HACS stable, HACS beta, or manual installation
- expected and actual behavior
- whether the Speedport web interface was logged in
- the time and frequency of the problem
- sanitized Home Assistant logs
- downloaded integration diagnostics when relevant

Diagnostics are designed to redact sensitive data, but review the file before
uploading it. Remove any remaining household or network identifiers. Never
attach raw router JSON/XML, a password, cookie, challenge, full packet capture,
phone number, public address, MAC address, SSID, serial number, SIM identifier,
or VPN material.

For a suspected security vulnerability, stop and follow
[Security](SECURITY.md) instead of filing a public issue.

## Scope of support

The validated target is Speedport Smart 4R Typ A firmware
010152.5.0.001.0. Reports from other Speedport hardware are welcome, but
support requires sanitized endpoint evidence and may take additional work.
Router controls are firmware-sensitive and should be tested only by the router
owner.
