# Support and troubleshooting

Telekom Speedport Smart is an unofficial community integration. Deutsche
Telekom and the Home Assistant project do not provide support for it.

For installation and upgrades from 0.2.0 or a 0.3.0 beta, follow the
[README upgrade guide](README.md#upgrading-and-removal). Use a version published
in HACS or GitHub Releases; a version mentioned in documentation is not itself
a downloadable release.

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

Rates use the latest two valid cumulative-counter readings without averaging.
An unchanged pair produces zero, but repeated totals alone cannot distinguish
idle traffic from delayed router-side accounting. There is no verified fixed
source-refresh interval. Use **Advanced WAN counter interval =
0 (Auto)** in the integration options. Auto starts at five seconds, tests
four, three, two and one second after five consecutive complete successful
polls at each cadence, and pauses after a failed WAN read.
The separate **Fast polling interval** controls public status, not WAN counters.
Changing it does not fix a busy WAN-counter source.

Check **WAN polling mode**, **WAN polling interval**, **WAN polling state** and
**WAN fastest proven interval** in the router's entities. Report these values
with any recurring problem. A one-second scheduler tick does not guarantee a
fresh one-second router sample. The data is aggregate WAN traffic, not
per-device throughput.

### WAN polling shows Learning or Cooldown

Scroll to the bottom of **Dashboard**, just above **All entities in Home
Assistant**. The footer shows the effective interval and current state:

- **Learning** counts successful polls at the current cadence, for example
  **Successful polls 3/5**. Auto tries the next faster cadence after five;
  Manual keeps its configured cadence.
- **Cooldown** pauses WAN reads for 60 seconds after a failure. The approximate
  countdown uses existing metadata updates and does not count down every second.
  When it ends, polling retries the same cadence. Another failure starts another
  60-second pause, never a longer one.
- **Stable** means five consecutive complete polls succeeded at the target.
  It does not guarantee that later requests will succeed.

For example, a failure at a three-second cadence pauses WAN polling for 60
seconds, then retries that three-second cadence. It does not switch back to five
seconds or retry a router setting. WAN Cooldown can follow any failed WAN read;
it does not by itself prove that the router's management session is busy.
Public status, Normal and Slow retain their separate schedules, with automatic
Normal and Slow work deferred while the panel is focused.

WAN intervals target anchored slots, not minimum waits after requests complete.
Router response time and other serialized operations can make actual samples
farther apart. Missed slots are skipped, not replayed. Retained
counters and historical samples are not new live readings. See
[WAN polling](docs/WAN_POLLING.md) for the timing contract. Include the effective
interval, state and approximate failure time in a support report rather than
repeatedly changing options or restarting the router.

### Wi-Fi, clients or configuration look older while the panel is open

A visible, focused Dashboard or Administration view defers automatic Normal
and Slow reads. Dashboard prioritizes WAN samples; Administration prioritizes
its explicit settings operations. Deferred data keeps its original timestamp.
Leave the panel, hide it or move focus elsewhere to allow background work to
resume. A disconnected client also loses its lease, with a 45-second expiry as
a fallback. Active router operations finish normally before priorities change.

### The traffic graph has gaps or no history

The dashboard reads the selected history window, initially 15 minutes, for the
router's download and upload rate entities and cumulative byte counters, then
uses incoming Home Assistant states. The transferred-volume graph adds usable
nonnegative counter differences within the selected window; it does not
estimate volume by integrating the rate graph or interpolate a window boundary.
Resets, unavailable or stale samples and long gaps break a segment, so a valid
subtotal can be marked partial. Confirm the relevant entities are enabled,
readable by your user and included in Recorder.
Retention and Recorder availability also affect history. The panel does not
change Recorder settings or poll the router separately.

Missing or stale samples remain gaps, not zero traffic. New live samples can
appear even when stored history is unavailable. Hover, touch or use the keyboard
to inspect an observed sample and its timestamp. Leaving Dashboard clears its
temporary graph state, not Home Assistant history.

### A LAN device says "Link speed not reported"

The router has not supplied a usable negotiated rate for that device. The
dashboard does not substitute the port's maximum speed, another device's rate
or WAN throughput. Reported download and upload link rates describe link
capacity, not current traffic. Devices without explicit wired-network evidence
are not added to the LAN list.

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

### An Administration page has no usable editor

The 69 content pages and 13 navigation groups follow the audited router menu.
They are not a promise that every operation exists on every firmware. A page
may have read-only state, contextual actions or an explanation of an unsupported
operation. Editors require current capability evidence and exact targets;
missing storage, handsets, lines or provider prerequisites can make them
unavailable. See the [capability matrix](docs/MANAGEMENT_CAPABILITY_MATRIX.md).

Opening an existing-settings page reads its available forms automatically. If
one fails, use that section's **Refresh** after checking management access.
Refresh keeps the same target if it still exists; it does not silently choose
another record. Do not test a destructive action just to investigate whether
an editor is available.

Read the specific unavailable reason. EasySupport or the provider may manage a
setting, USB or receiver prerequisites may prevent an operation, or the router
may not return a complete target inventory. A missing firmware offer does not
prove that firmware is up to date. These guards deliberately keep editing
disabled; they are not instructions to change other router settings.

### A form says the revision expired or another request is running

Wait for any active save to finish, then refresh the affected section. Reads
have short-lived approvals tied to your Home Assistant login, router, setting
and target. Moving through many editors can retire an older approval belonging
to your session. Reloading current values obtains a new approval.

A second save blocked by an active request is reported as **not sent**. An
**unknown outcome** is different: the router may have changed. Check its state
before retrying; the integration does not replay uncertain writes automatically.
Refreshing or cancelling a draft does not undo a submitted router change.

### The sidebar panel is missing

- Confirm the integration is loaded without an error.
- Perform the Home Assistant restart required after install or upgrade.
- Confirm another custom panel is not already using **/speedport-smart**.
- Clear the browser cache only after the Home Assistant checks above.

### The panel looks old or reports a private-transport warning after upgrading

Restart Home Assistant after updating, then hard-refresh the dashboard page or
close and reopen the panel in the Home Assistant app. The integration and panel
must come from the same release. For manual installations, replace the complete
component directory rather than mixing old and new files.

Private Administration requests use authenticated HTTP. Older cached pages
using the retired private WebSocket commands cannot execute them. Do not delete
the integration or repeatedly submit an action to work around a stale page.
If necessary, clear the frontend cache only after confirming the installed
version and restart.

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
- the Administration tab, page and section, if relevant; include the exact
  outcome wording but omit private field values
- sanitized Home Assistant logs
- downloaded integration diagnostics when relevant

Diagnostics are designed to redact sensitive data, but review the file before
uploading it. Remove any remaining household or network identifiers. Never
attach raw router JSON/XML, a password, cookie, challenge, full packet capture,
phone number, public address, MAC address, SSID, serial number, SIM identifier,
or VPN material.

Private exports are not anonymized diagnostics. Do not attach Router-Pass,
configuration backups, VPN files, phonebook or call-list exports, or downloaded
system logs to a public issue. Crop or redact screenshots that show private
editor values. Use HTTPS between your browser and Home Assistant when entering
credentials; router HTTPS is a separate connection.

For a suspected security vulnerability, stop and follow
[Security](SECURITY.md) instead of filing a public issue.

## Scope of support

The read-only validated target is Speedport Smart 4R Typ A firmware
010152.5.0.001.0. The new Administration write contracts have firmware evidence
and offline tests, but this work did not perform live router changes or validate
every write/readback/restoration cycle. Navigation coverage and a release
version do not establish that evidence. Reports from other Speedport hardware
are welcome, but support requires sanitized endpoint evidence and may take
additional work.
Router controls are firmware-sensitive and should be tested only by the router
owner.
