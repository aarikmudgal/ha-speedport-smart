# Security policy

Telekom Speedport Smart handles a router password and local network data.
Please report security problems privately so users have time to update before
details are published.

## Supported versions

| Version | Support |
| --- | --- |
| Latest stable release | Security fixes |
| Current beta prerelease | Best effort |
| Older releases | No guaranteed fixes |

Users should reproduce a problem on the latest stable release before
reporting, unless upgrading would increase risk.

## Private reporting

Use
[GitHub's private vulnerability report](https://github.com/aarikmudgal/ha-speedport-smart/security/advisories/new).
If that page is unavailable, contact the maintainer
[@aarikmudgal](https://github.com/aarikmudgal) and request a private channel.
Do not open a public issue for a suspected vulnerability.

Include:

- affected integration and Home Assistant versions
- router model and firmware
- installation method
- impact and reproducible steps
- the smallest sanitized evidence needed to confirm the issue
- any mitigation already tested

Do not send a router password, session cookie, login challenge, private key,
raw router response, HAR file, browser network log, copied cURL request, full
packet capture, public IP address, phone number, MAC address, SSID, serial
number, client list, SIM identifier, or VPN secret. Coordinate privately before
sending material that cannot be fully sanitized.

The repository's offline control-capture sanitizer accepts raw HAR only through
standard input and emits structural evidence without raw values. Its output
still requires manual review before sharing. Never assume a browser's built-in
HAR redaction is sufficient.

The maintainer will acknowledge reports when available, investigate, coordinate
a fix and disclosure, and credit reporters who want attribution. No response or
fix deadline is guaranteed.

## Security boundaries

The integration:

- communicates directly with the configured router on the local network
- stores credentials in the Home Assistant config entry
- uses a private cookie jar over Home Assistant's shared HTTP connector
- serializes authentication, polling, and commands
- redacts diagnostics before export
- never runs router-changing commands during setup, polling, discovery,
  diagnostics, retry, or reload

Native entity services use normal Home Assistant permissions. Panel confirmation
does not intercept an automation or another caller invoking those services.
Structured writes, secret changes and destructive operations instead require
authenticated administrator-only HTTP routes, closed firmware-specific contracts and fresh
requester/target-bound approvals. Approvals are short-lived and single-use;
active authorization is checked again immediately before mutation. Writes are
not automatically retried, and incomplete proof is not reported as success.

Private settings, identifiers, contacts, call records and results use bounded
`no-store` HTTP responses, not Home Assistant's WebSocket payload logging path.
Opening a native administration page can automatically read its private data;
it never automatically saves, clears or exports it. In-memory panel data is
cleared when its view or authorization scope ends and is not copied into entity state,
Recorder, diagnostics or persistent browser storage. Ordinary telemetry and its
Home Assistant history are separate. After upgrades, hard-refresh the panel:
retired private WebSocket commands reject before router work, but a stale client
can still send its payload through core logging before rejection.

Use Home Assistant HTTPS for credentials and private files. Router HTTPS does
not secure the browser-to-Home-Assistant connection. Disable request/response
body logging in proxies and debugging middleware. Backups, Router-Pass cards,
phonebooks, VPN files and private system logs are sensitive downloads, not
sanitized diagnostics. A stable integration release does not certify untested
live writes; consult the [firmware and evidence limits](docs/MANAGEMENT.md).

Local network compromise, a compromised Home Assistant instance, physical
router access, router firmware vulnerabilities, and unsafe automations invoking
an exposed control are outside the integration's trust boundary. Reports that
show the integration worsens one of those conditions are still welcome.

Ordinary bugs, unsupported firmware, and feature requests belong in
[GitHub Issues](https://github.com/aarikmudgal/ha-speedport-smart/issues).
