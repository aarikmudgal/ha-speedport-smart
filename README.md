# Telekom Speedport Smart

![Telekom Speedport Smart icon](custom_components/speedport_smart/brand/icon.png)

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=aarikmudgal&repository=ha-speedport-smart&category=integration)

Telekom Speedport Smart is a local, capability-driven Home Assistant custom
integration for Telekom Speedport routers. It combines the router's encrypted
local JSON API with its local ToTR64 service to provide live WAN traffic,
connection data, router services, supported controls, and a responsive
Home Assistant dashboard without a cloud account.

The integration domain is **speedport_smart**. The public integration name is
**Telekom Speedport Smart**.

This documentation covers the 0.3.0 code line, including its prerelease builds.
For available downloads, use the versions offered by HACS or the
[published releases](https://github.com/aarikmudgal/ha-speedport-smart/releases).
The [upgrade guidance](#upgrading-and-removal) covers both 0.2.0 and 0.3.0 beta
installations.

> [!IMPORTANT]
> This repository is prepared for installation as a HACS custom repository and
> for submission to the HACS default catalog. It must not be described as
> officially listed until the HACS submission has been accepted.

## Highlights

- Local polling only; router data is not sent to an integration cloud
- Aggregate WAN bytes received/sent and derived live download/upload rates
- Active WAN-interface discovery instead of a fixed interface index
- Internet, DSL, Hybrid/mobile, Wi-Fi, Mesh, client, LAN, telephony, system,
  security, VPN, USB, and diagnostic entities when the router exposes them
- Capability-driven entity creation across different models and firmware
- Explicit management-session status and read-only recovery
- Bundled, responsive Home Assistant sidebar dashboard
- Home Assistant sensors, binary sensors, device trackers, switches, selects,
  buttons, text controls, and firmware update entities
- Privacy-redacted diagnostics
- Configurable fast, normal, and slow polling groups

## Dashboard preview

The bundled dashboard follows Home Assistant's active light or dark theme and
adapts to both desktop and mobile layouts. These current dark-theme previews use
only synthetic names, traffic and connection data, rendered by the actual
dashboard. No private router or household information is shown. The captures
focus on the shared-window WAN traffic and transferred-data graphs; see the
[dashboard guide](docs/dashboard.md) for the remaining connection cards and
Administration navigation.

### Desktop

![Telekom Speedport Smart dashboard in the Home Assistant dark theme on desktop](docs/images/dashboard-dark-desktop.jpg)

### Mobile

<img src="docs/images/dashboard-dark-mobile.jpg" alt="Telekom Speedport Smart dashboard in the Home Assistant dark theme on mobile" width="430">

## Compatibility

The read-only validated router and supported Home Assistant requirements are:

- **Router:** Speedport Smart 4R Typ A
- **Firmware:** 010152.5.0.001.0
- **Home Assistant:** 2025.12.0 or newer
- **Languages:** English and German for the integration and main dashboard;
  Administration navigation and structured editors currently use English.

That live validation covers read-only discovery and polling. The administrator
actions described below target this exact router and firmware. Their
implementations use downloaded firmware request contracts and automated tests.
Development validation did not execute those actions on the router. Firmware
evidence and offline tests do not certify every live change/readback/restoration
cycle; the router owner must test the controls they intend to use.

Other Speedport models or firmware may expose a different set of endpoints and
entities. An entity appears only when both the integration implements it and
the connected router supplies evidence for that capability. Missing
firmware-specific features are omitted; a temporarily failed supported entity
remains registered and becomes unavailable until fresh data succeeds.

Home Assistant must be able to reach the router on the local network. The
router password is required during setup. HACS is optional when installing
manually.

## Installation

### HACS custom repository

Until the integration is accepted into the HACS default catalog:

1. In HACS, open the three-dot menu and select **Custom repositories**.
2. Add
   **https://github.com/aarikmudgal/ha-speedport-smart** as an
   **Integration** repository.
3. Find **Telekom Speedport Smart** in HACS and install the latest stable
   version.
4. Restart Home Assistant.
5. Open **Settings > Devices & services > Add integration**.
6. Select **Telekom Speedport Smart**.

After default-catalog acceptance, the custom-repository step is no longer
needed and the integration can be found directly in HACS.

### Manual stable release

1. Download **speedport_smart.zip** from the desired full GitHub release.
2. Extract its contents to
   **/config/custom_components/speedport_smart**.
3. Confirm that
   **/config/custom_components/speedport_smart/manifest.json** exists.
4. Restart Home Assistant.
5. Add **Telekom Speedport Smart** from **Settings > Devices & services**.

Do not install GitHub's automatically generated source archive as the HACS
package. Use the attached **speedport_smart.zip** release asset.

### Beta releases

Beta builds are created from branches matching <code>feat/*</code>, for example
**feat/live-bandwidth**, and use versions such as
**X.Y.Z-beta.RUN.ATTEMPT**. They may be less stable than a release from
**main**.

To receive them through HACS, enable the disabled HACS switch entity for this
repository, then turn that prerelease switch on. With the switch off, HACS
tracks only stable releases. Return to a stable release by turning the switch
off and selecting the latest stable version in HACS.

## Setup

Before initial setup, use **Logout** in every open Speedport web interface.
Closing a browser tab alone can leave its router management lease active.
Disable any other Home Assistant integration or local polling tool connected
to the same Speedport; competing clients can contend for its single protected
management lease.

Home Assistant can propose routers announced by a `speedport*` DHCP hostname or
the captured Deutsche Telekom SSDP fingerprint (`Speedport Smart 4 R Typ A` in
the SSDP `modelName`, including its spacing, plus the WLAN access-point device
type). Announcements are hints only. Before prompting, the integration reads
only public status over HTTP and requires the Status API itself to report
`Speedport Smart 4R Typ A` plus a stable serial number. Confirmation then runs
the same read-only connection validation as manual setup and requires the model
and serial to remain equal. Adjacent Smart models and other Telekom or
Speedport products are rejected.

Discovery never changes an existing entry's host and never sends a stored
password to a newly announced address. If the router address changes, use the
explicit reconfigure flow and enter the password there.

Enter:

- **Host:** router hostname or IP address; **speedport.ip** is the default
- **Router password:** the device password used by the Speedport web interface
- **Use HTTPS:** normally off unless HTTPS is configured and reachable
- **Verify TLS certificate:** enable only when Home Assistant trusts the
  router certificate

Many Speedport routers use a self-signed certificate. A normal local setup
therefore commonly uses HTTP, or HTTPS with certificate verification disabled.
The password is stored in the Home Assistant config entry; never place it in
YAML, logs, diagnostics, terminal history, or an issue report.

## Built-in Home Assistant dashboard

Installation adds **Telekom Speedport Smart** to the Home Assistant sidebar.
This is a native Home Assistant custom panel bundled with the integration, not
a separate website or Lovelace card. No additional frontend repository is
required.

The panel:

- follows the active Home Assistant light or dark theme
- adapts to desktop and mobile layouts
- keeps **Dashboard** focused on live traffic graphs, paired Wi-Fi band
  summaries, DSL link speeds, mobile receiver signal and wired devices
- supports graph hover, touch and keyboard sample inspection, and displays
  actual reported LAN link speeds rather than a generic connected label
- offers 5, 15, 30 and 60-minute graph windows, with 15 minutes selected initially
- shows downloaded and uploaded volume from valid recorded byte-counter
  segments in a separate graph, using the same selected window and automatic
  decimal MB, GB or TB units without additional router requests
- presents reviewed controls and detailed router settings in **Administration**
- keeps all entities and their recorded history available in Home Assistant's
  standard device pages, linked from Dashboard
- uses live Home Assistant entity states; router names and values are not
  hardcoded
- respects the signed-in user's entity permissions
- requires confirmation before every router-changing action and an exact typed
  phrase for destructive administrator actions

Administration follows the six router tabs **Overview**, **Status**,
**Internet**, **Telephony**, **Network** and **System**, with contextual left
navigation on desktop and a page menu on mobile. Its 69 content pages and 13
navigation groups make 82 navigation entries, mapping 120 router feature entries
and 110 settings editors. Those counts describe navigation coverage, not 120
writable or universally supported capabilities.
The organization follows a [read-only audit of the real router's complete
navigation](docs/NATIVE_ADMIN_NAVIGATION.md),
adapted to Home Assistant rather than copied pixel for pixel.

Opening a page reads its available existing-setting sections automatically,
with each form displayed inline and requests paced to protect the router
session. Selecting another existing target reads that target; it never saves
it. Contextual creation, deletion and maintenance actions remain explicit.
**Save changes** still requires the exact typed confirmation,
and expired sessions or revisions require a fresh read. Secrets are not
prefilled. **Refresh** reloads current state; **Cancel changes** restores the
last loaded values without sending a router request. When management access
recovers, invalidated sections automatically read again without navigating away
and back. A session change during a save preserves the dispatched operation's
result, then clears stale sibling drafts and reloads those sections at their
previous targets. If a section becomes available without a session change, it
loads alongside the existing forms without discarding their drafts. Its read
waits for any active save to finish. Neither recovery path repeats the save. See the
[Dashboard and Administration guide](docs/dashboard.md) for navigation, privacy
and outcome details. No live writes were tested for this redesign; router
owners must validate writes explicitly.

The router device page also links directly to the configured local Speedport
web interface through Home Assistant's standard **Visit** action.

Home Assistant administrators can also open reviewed structured details for
clients, Mesh nodes, port-forward and port-block rules, DNS-rebind exceptions,
traffic-priority slots, private Wi-Fi SSIDs, DDNS domain/update-server identity,
VPN peers, telephony providers and lines, DECT handsets and repeaters, IP phones
and PBX clients, USB and storage devices, NAS shares, mobile receivers, and
Powerline devices. These details are projected from the integration's existing
cached normalized state; reading that cached projection does not send another
router request. A settings form opened on the same Administration page performs
its own fresh read as described above.
The response is allowlisted, bounded, loaded only on demand, kept in browser
memory, and cleared when the router selection, connection, or administrator
access changes. It is never written to browser storage.

The cached administrator view includes exact per-radio Mesh MAC addresses,
opaque VPN peer and NAS-share identifiers, storage serials, and opaque VoIP
line-to-provider relationships when the router returns their exact fields.
Phonebook search additionally reports the router's bounded total and remaining
entry capacity. These private details do not become Recorder-backed entities.

All entities remain available through the standard **Devices & services**
pages for dashboards, automations, history, and statistics. Disabling an entity
in Home Assistant also removes it from the bundled panel.

## Data and polling

One serialized client owns encrypted JSON authentication, ToTR64 SOAP, and the
router management lease so polling groups do not compete with each other.

An internal one-second scheduler checks which live data is due; a scheduler tick
does not necessarily send a router request. Public status and WAN counters use
separate due-time gates, so changing one cadence does not force the other to use
the same interval.

| Data path | Default | Allowed or behavior | Typical data |
| --- | ---: | ---: | --- |
| Public status (Fast) | 5 seconds | 1 to 60 seconds | Browser-independent live connection state |
| WAN counters | Auto (`0`) | Auto, or an advanced target from 1 to 60 seconds | Cumulative byte and packet counters, derived rates, utilization |
| Normal | 30 seconds | 15 to 300 seconds | Wi-Fi, clients, telephony, operational status |
| Slow | 5 minutes | 1 to 60 minutes | Configuration, topology, firmware, slow-changing services |

Change these values from **Settings > Devices & services > Telekom Speedport
Smart > Configure**. The Fast setting controls public status only. The advanced
WAN counter setting uses `0` for Auto or `1` to `60` for a requested target.
Auto starts at five seconds. Five consecutive, complete successful WAN polls
at each cadence move it one step faster: `5 → 4 → 3 → 2 → 1` seconds. Five
successful polls at one second mark it **Stable**. These are short learning
windows, not a guarantee that every router will sustain the selected speed.

Any WAN read failure, including ToTR64 fault `9801` (session busy), resets the
success count and starts a fixed **60-second Cooldown** after that request
finishes. Polling then retries at the same cadence. Each later failure starts
another 60-second cooldown; the delay never increases. Unsupported endpoints
remain excluded rather than being retried indefinitely.
Previously confirmed cumulative totals remain available with their last-success
freshness information while retrying; derived live rates resume from valid
samples after recovery. A manually selected WAN target uses the same fixed
cooldown. Normal and Slow retain their configured intervals and data scopes,
but wait while Dashboard or Administration has focus.

The dashboard footer shows the target cadence, the latest observed sample
interval, **Learning**, **Cooldown** or **Stable**, plus learning progress or
an approximate retry countdown. WAN polling targets fixed slots rather than waiting
another interval after a response completes. Requests never overlap; missed
slots are skipped, not queued. Request duration, scheduling jitter and other
serialized router operations can still make samples farther apart, so selecting
one second does not promise a fresh sample every second.
See [WAN polling](docs/WAN_POLLING.md) for the complete timing and recovery rules.

The router supplies cumulative byte counters. Rates use the **latest two valid
observations** and their actual monotonic elapsed time, without a rolling
average or a held nonzero value. The actual sample span is available in the
rate-entity attributes. Repeated totals can mean idle traffic or delayed
router-side accounting; polling every second does not prove the source updates
every second. The integration rejects negative values,
reboot resets, and false reset spikes. Totals use Home Assistant's
total-increasing statistics model, allowing Home Assistant to select a readable
unit and retain long-term statistics. Use Home Assistant's Utility Meter
integration for daily, weekly, monthly, or yearly consumption.

While the connected panel is visible and focused, Dashboard gives WAN work
priority and Administration gives explicit settings operations priority.
Automatic Normal and Slow reads wait without making their cached data appear
fresh. Leaving or hiding the panel, losing focus or disconnecting releases that
priority; a 45-second expiry also handles lost clients. Background reads then
resume without replaying missed updates. An active router transaction always
finishes before the next operation begins, so focus cannot interrupt a write,
readback or logout and cannot guarantee immediate one-second samples.

Live rate is aggregate WAN traffic, not packet capture and not per-client
throughput. On validated Hybrid firmware, the active BONDING/habond interface
already represents combined traffic, so LTE tunnel counters are not added a
second time.

## Router management access

Protected Speedport endpoints may permit only one active management owner. The
diagnostic **Management access** entity reports whether protected data is
available, blocked by another session, locked by a cooldown, recovering, or
unknown. When supplied by the router, its attributes include the competing
owner's IP address, browser logout guidance, retry delay, and last successful
protected update.

If the web interface owns the lease:

1. Select **Logout** in the router web interface.
2. Return to Home Assistant.
3. Press **Retry protected data (log out of the router first)** or complete the
   Home Assistant Repair flow.

The retry performs read-only discovery. It does not change router settings or
force another session to disconnect. Public data that the firmware exposes
without a protected lease can continue updating while protected entities are
temporarily unavailable. Restarting the router should not be a routine
recovery step.

For support and capability development, administrators can use
**Administration → Overview → Home Assistant integration tools → Read-only capability discovery → Capture
inventory**. This explicit action checks every known safe candidate data source
in one serialized session. It uses only the required login/logout lifecycle and
JSON reads: it does not run WAN/TR-064 polling, submit a router setting, invoke
a management command, or reload the integration. Endpoints that may trigger a
Wi-Fi scan, update check, or other router activity are deliberately excluded.
Log out of every Speedport web interface before starting it.

An observed candidate remains evidence only. Capturing its value-free shape does
not add a runtime capability, normalize its fields, create an entity, or enable
a router control.

The resulting diagnostics contain only bounded endpoint metadata and
value-free field paths and shapes. They also report whether the scan completed,
was partial, or failed, plus safe attempted/succeeded/unsupported/failure and
excluded counts. Raw values and payloads are never retained. Review the
diagnostics file before sharing it.

## Router controls

Controls are shown only when the router reports a matching capability and the
integration has a specific implementation for that command. Supported controls
are enabled by default so users can access the complete reviewed control set
available for their exact model and firmware. Other reported or statically
discovered capabilities remain read only unless they have their own reviewed
write contract. Controls remain idle during setup, polling, discovery, retry,
reload, and diagnostics.

The 0.3.0 code line includes structured Administration editors for Internet and
LAN configuration, Wi-Fi, schedules, forwarding and blocking rules, parental
controls, telephony, phonebooks, VPN peers, storage shares, receivers and system
settings. It also provides explicit maintenance actions and private file
transfers. These complex operations live in the Administration panel, not in
generic services or placeholder entities. The exact implemented and incomplete
areas are listed in the [capability matrix](docs/MANAGEMENT_CAPABILITY_MATRIX.md).

An editor first reads the current configuration. Saving requires a fresh,
short-lived approval bound to the administrator, login session, router entry,
setting and target. The backend validates every submitted field, rechecks the
current configuration and sends at most one mutation. Independent readback
checks supported results; interrupted, secret-only or externally completed
actions report their limited verification explicitly. Ambiguous writes are
never retried automatically. Destructive actions require a typed phrase and
show recovery guidance.

Password changes, VPN credentials, phonebooks, call history, Router-Pass and
configuration files use private administrator-only flows. Private JSON travels
over authenticated, non-cached HTTP rather than Home Assistant's WebSocket
logging path. Use HTTPS for Home Assistant when entering credentials or
downloading private files. Never share a configuration backup, Router-Pass or
VPN configuration publicly.

The bundled dashboard asks for confirmation before an action. Native buttons,
switches, updates, services, scripts, and automations elsewhere in Home
Assistant follow normal Home Assistant behavior, so review automations
carefully. Administrator actions are panel-only and cannot be invoked as native
entities or general services. Controls can be hidden completely from the
integration options.

Router-changing commands were not executed during development validation.
These implementations have static firmware evidence and offline tests, not a
live change/readback/rollback certification. The reviewed write boundary is
Speedport Smart 4R Typ A firmware `010152.5.0.001.0`; other firmware remains
read-only unless explicitly supported. Review each action before testing
it. Factory resets, firmware updates, restores, credentials, network modes and
deletions can interrupt access or remove working configuration.

The integration does not invent undocumented settings or expose arbitrary
JSON, SOAP or router endpoints. Firmware pages with incomplete request or
identity evidence remain explicitly partial or read-only. A visible catalog
entry does not guarantee that the connected router exposes that capability.

See [Router management support](docs/MANAGEMENT.md) for exact implemented
requests, readback behavior, deferred areas, and permanent exclusions.

## Diagnostics and privacy

Download diagnostics from the integration's device page before opening a
support issue. The diagnostics layer redacts credentials, public addresses,
phone numbers, MAC addresses, SIM identifiers, VPN secrets, and raw router
payloads. Review the file yourself before sharing it.

Never publish raw router responses. Firmware pages can contain passwords,
telephone data, public IP addresses, client identifiers, and other private
material. See [Security](SECURITY.md) for private vulnerability reporting.

## Upgrading and removal

Read the release notes and make a Home Assistant backup before upgrading. Wait
for any router-changing operation to finish, then close its editor. Upgrading
the integration does not apply router settings or test its controls.

For a HACS installation, select the intended published version, install it and
restart Home Assistant. You do not need to remove and re-add the integration.

- From **0.2.0**, select **0.3.0** when that stable release is available. The
  existing config entry and options remain in use; the expanded Administration
  panel comes in the same package.
- From any **0.3.0 beta**, use the same update process.
  To leave the beta channel, turn off the repository's prerelease switch and
  explicitly select the intended stable version. Turning the switch off alone
  does not establish which version is installed.
- After the restart, reload the dashboard page. If it still shows an older
  layout or a private-transport warning, hard-refresh the browser or close and
  reopen the panel in the Home Assistant app. Cached private WebSocket commands
  are no longer accepted, and no interrupted operation is replayed.

Supported entities and their recorded history remain in Home Assistant.
Upgrades remove retired beta placeholders, including unproven router-global
NAS sensors and obsolete router-control entities. These are not replacements
for the target-specific Administration editors. Check any custom cards or
automations that referenced retired entities; see the [changelog](CHANGELOG.md)
for the cleanup details. Removing and re-adding the integration is not a
remedy for an unsupported firmware capability.

For a manual installation, replace the complete
**/config/custom_components/speedport_smart** directory with the contents of
one release asset, then restart Home Assistant. Do not mix files from two
versions.

To remove the integration:

1. Delete its config entry from **Settings > Devices & services**.
2. Remove **Telekom Speedport Smart** from HACS, or delete the manual component
   directory.
3. Restart Home Assistant.

Home Assistant may retain entity history and long-term statistics according to
its recorder settings.

## Support and development

- Start with [Support and troubleshooting](SUPPORT.md).
- Report reproducible bugs through
  [GitHub Issues](https://github.com/aarikmudgal/ha-speedport-smart/issues).
- Read [Contributing](CONTRIBUTING.md) before submitting changes.
- Read [Release process](docs/RELEASING.md) for stable and beta channels.
- Maintainers can use the [HACS submission checklist](docs/HACS_SUBMISSION.md).
- Protocol and lifecycle design is documented in
  [Architecture](ARCHITECTURE.md).
- Firmware feature coverage and remaining proof requirements are tracked in
  [Management capability matrix](docs/MANAGEMENT_CAPABILITY_MATRIX.md).
- Normalized data ownership and publication lineage are documented in the
  [Read-surface registry](docs/READ_SURFACE_REGISTRY.md).
- Changes are recorded in [Changelog](CHANGELOG.md).

## License and trademark notice

This project is licensed under the [MIT License](LICENSE).

This is an independent, unofficial community integration. It is not affiliated
with, endorsed by, or supported by Deutsche Telekom AG. Telekom, Speedport, and
related marks are the property of their respective owners and are used only to
identify compatible products.
