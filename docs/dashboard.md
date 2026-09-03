# Dashboard and Administration

The bundled Home Assistant panel has two separate views. **Dashboard** is a
compact connection overview. **Administration** organizes router settings into
pages within that same panel. It does not embed the router website or replace
Home Assistant's standard device and entity pages.

This guide describes the 0.3.0 code line. Install a published version through
HACS or a release asset, restart Home Assistant, then reload the panel. See the
[upgrade guide](../README.md#upgrading-and-removal) when moving from 0.2.0 or a
0.3.0 beta; the dashboard does not need a separate installation.

## Dashboard overview

- A full-width download/upload graph defaults to the last 15 minutes, followed by
  incoming Home Assistant samples. Its two series use distinct colors and solid
  lines. The current sample values remain visible above the graph.
- A separate transferred-volume graph shows downloaded and uploaded byte-counter
  differences for the same selected window, with automatic decimal MB, GB or
  TB units. It uses recorded cumulative counters and observed live counters,
  not estimated volume from the rate graph or new router requests.
- Hover or touch the graph to inspect observed speeds and their timestamps.
  Keyboard users can focus the graph, move between samples with the arrow
  keys, jump with Home / End and dismiss with Escape. The tooltip does not
  invent speeds between missing samples or across gaps. Live updates preserve
  the selected sample's timestamp rather than moving it to the latest point.
- Separate 2.4 GHz and 5 GHz Wi-Fi blocks show status, channel and connected
  device counts.
- DSL sync speeds and WAN capacity are labeled separately from consumed
  bandwidth. Mobile receiver details include the reported network type, band,
  frequency and signal metrics when those entities exist, including separate
  LTE signal strength and LTE band alongside 5G measurements.
- Wired devices are grouped in a compact list. Only trackers explicitly
  identified as LAN appear; missing Wi-Fi information is not treated as proof
  that a device uses Ethernet. Rows show the device's reported negotiated link
  speed, with separate download / upload values when they differ. This is
  Ethernet link capacity, not consumed traffic. An unreported link rate says
  **Link speed not reported** rather than substituting WAN speed or port
  capacity. Disconnected devices retain their connection status.

Choose **5, 15, 30 or 60 minutes** using the selector in the graph header.
Changing the timeframe reads that window once from Home Assistant Recorder,
using only the selected router's rate and cumulative byte entities. Both graphs
also consume the
existing live state stream. Each series retains at most 1,024 observations;
longer windows use wider sampling buckets while preserving actual observation
timestamps and gaps. Leaving the view resets the selected window to 15 minutes.
It does not add router polling, alter polling cadence, or change Recorder
configuration. Missing history is reported explicitly; live samples can still
accumulate while the view is open. Unknown and unavailable values are not
converted to zero. History availability depends on the user's permissions,
Recorder configuration and retention. Leaving the view clears its in-memory
graph state, not recorded data.

Volume is the sum of nonnegative differences between usable consecutive counter
observations inside the window. The first observation establishes a baseline;
it is not lifetime transferred data, and the window edge is not interpolated.
Counter resets, explicit unavailable or stale samples and long gaps break a
segment. Later valid segments can still add to a subtotal marked **Partial**.
The subtotal remains partial if the latest source is stale. Internal counter
samples are bounded before the chart's 1,024-point display limit is applied.

The footer below the overview cards distinguishes the target WAN cadence from
the latest observed sample interval and shows
**Learning**, **Cooldown** or **Stable**. Learning adds progress such as **Successful polls
3/5**; Cooldown shows an approximate **Retry in ~45 s**. The countdown comes from
existing metadata refreshes, so it does not tick every second and is not an
exact request-time promise. Stable has no redundant progress counter.

Auto starts at five seconds and moves through `5 → 4 → 3 → 2 → 1` after five
consecutive complete successful polls at each cadence. A failed WAN read starts
a fixed 60-second cooldown, then retries at that same cadence. Every later
failure restarts the same 60-second wait; it never increases. The target uses
fixed polling slots, not response completion plus another interval. Busy slots
are skipped without overlapping requests or a catch-up queue. Router response
time and other serialized operations can still make actual samples farther
apart. Rates use the latest two valid counter observations and their actual
elapsed monotonic time, without a rolling average or smoothed tail. The actual
sample span is available in the native rate entities. Repeated totals can
represent idle traffic or delayed source accounting; a one-second request
target does not prove a one-second router-counter refresh. Missing data is not
filled with invented values.
See [WAN polling](WAN_POLLING.md) for timing and Manual mode.

The footer also reports panel priority and deferred background refreshes.
Dashboard focus prioritizes WAN work; Administration focus prioritizes explicit
settings operations. Automatic Normal and Slow reads wait while either view is
connected, visible and focused, keeping their original data timestamps. Leaving
or hiding the panel, losing focus or disconnecting releases this priority, with
a 45-second server expiry for lost clients. Already-running router operations
finish before another begins, and missed background refreshes are not replayed.

During Cooldown, cached samples are not labeled as current live rates. WAN
traffic history stays enabled; the panel adds no router requests. Detailed
entities, history and diagnostics remain available through **All entities in
Home Assistant**. The router device's Diagnostic section includes **WAN polling
mode**, **WAN polling interval**, **WAN polling state** and **WAN fastest proven
interval**.

The overview follows the current Home Assistant theme and fills the available
width on desktop and mobile. Router-specific values are never demo data.

## Administration navigation

Administration has six router tabs, in this order: **Overview**, **Status**,
**Internet**, **Telephony**, **Network** and **System**. On desktop, the left
navigation shows the pages belonging to the selected tab, including nested
Internet, 5G receiver, Wi-Fi, telephony, storage and system pages. On smaller
screens, the contextual page navigation is available through the mobile menu.

The navigation follows the [read-only audit of all 69 native screens](NATIVE_ADMIN_NAVIGATION.md),
including the sidebar-only Prioritization page omitted by the router's sitemap.
It uses Home Assistant's theme and responsive controls; it is not intended to
reproduce every router screen pixel for pixel.
Other router models and firmware versions may expose different capabilities.

The current navigation contains **69 content pages** and 13 navigation groups
(82 navigation entries). It maps **120 router feature entries** and
**110 settings editors** to their relevant pages without duplicating editor
ownership. These are navigation counts,
not a claim that 120 features are writable, that every page has an editor, or
that every feature is supported by the connected router. Entries can contain
read-only information, an unavailable action, or an explanation of an
unsupported operation. The [capability matrix](MANAGEMENT_CAPABILITY_MATRIX.md)
describes the implemented subsets and remaining limits.

An available editor also needs a complete current read for the selected
object. For example, a share editor needs an attached storage device and an
identified share; a telephony editor needs the corresponding line or handset.
Missing hardware, unsupported firmware, provider-managed settings, incomplete
fields or missing readback evidence can prevent an operation. The panel does
not manufacture a target or treat a failed read as an empty inventory.

Home Assistant-specific recovery and inventory actions remain in the separate
**Home Assistant integration tools** section on Overview. They are not presented
as native router settings.

## Reading and editing a page

Opening a page automatically reads its available existing-setting sections.
Pages such as phone-number assignment and prioritization display their related
forms together, without a second settings-launcher selection. Each section
keeps its own current values, revision, draft and Save control. Reads are
serialized and paced to respect the router's admission limits; they are not
launched concurrently or for unvisited pages.

Existing-object forms first read their targets, then the selected existing
target. The target picker reads a newly selected target automatically. Create,
delete, reset and other contextual operations still require an explicit
selection. None of these navigation or selection operations saves settings.

Opening Missed calls, Received calls or Dialed outgoing calls loads that page's
private list automatically. It stays out of Recorder and is cleared when the
page closes. Refresh reads the same category again; export and clearing the
router's list remain separate, explicit actions. Category reads and exports
share a one-second minimum interval after the previous request completes.
Changing pages cancels a queued read before it is sent.

If a management-session change invalidates an idle form, the visible page
automatically reads again after access recovers. This is a guarded read for
each recovered section, not a retry on every telemetry update. Page, router and
permission changes cancel pending navigation reads. In-flight writes are not
replaced or replayed. If the session changes during a save, the panel retains
that operation's result, then clears the other sections' stale drafts and
reloads their previous targets. A failed read still provides a manual Refresh
fallback.

If a section becomes available without a session change, it loads alongside
the existing forms without replacing their drafts or revisions. That read waits
for an active save to finish and preserves the save result. Leaving the page,
changing routers or changing the signed-in administrator cancels the pending
read. A failed section still waits for an explicit Refresh rather than retrying
on every metadata update.

The form groups related fields together. For example, Wi-Fi name and encryption
shows the 2.4 GHz network, the 5 GHz network, then shared security settings.
Schedules group daily or weekday fields and preserve supported `24:00` end
times. Wi-Fi schedule mode shows only its relevant time fields: none when the
schedule is off, the daily pair for Daily, or the seven weekday groups for
Weekly. Changing this mode updates visibility locally without erasing hidden
time values or typed confirmation; it sends no router request. Small
multiple-choice lists use labeled checkboxes.

Use the page's controls deliberately:

- **Refresh** reads current values again. For a targeted form, it also refreshes
  the target list and keeps the same exact target when it still exists. A
  disappeared target is not silently replaced with another device or record.
- **Save changes** requires the form's exact typed confirmation. Only an
  explicitly confirmed save can submit changed settings. The operation uses
  the current revision and follows the existing backend verification policy.
- **Cancel changes** restores the last loaded values locally and clears entered
  credentials and confirmation text. It sends no router request and does not
  undo a change already submitted to the router.

Changing targets with unsaved changes asks before discarding the draft. If
discarding is not confirmed, the current selection and draft remain in place.
An in-flight write cannot be replaced by a target change. Late read responses
from a previous page, router or target cannot populate the new form.

## Sessions, credentials and outcomes

Reads create short-lived, requester-bound revisions. An expired read or changed
router state requires a fresh **Refresh** before saving. Refreshing or changing
a section's target clears that section's private draft; opening a sibling
section does not discard other sections' drafts. Leaving the page clears all
its private editors. Live WAN updates preserve open forms and their drafts.
A refresh does not extend an old approval: it obtains current state again.

The backend keeps at most 32 short-lived settings revisions. When navigating
through more settings, a successful read can replace the oldest revision owned
by the same Home Assistant user and login session. Another user's or session's
revisions are never evicted for it. An older open form may therefore require
Refresh before saving; a discarded revision cannot authorize a write.

Passwords and other secret fields are never prefilled with router credentials.
Leave them blank when no credential change is intended, unless the form
explicitly requires re-entry for that operation. Entered secrets and typed
confirmation are kept out of ordinary snapshots and browser storage. Private
requests use authenticated administrator-only, no-store HTTP. Use HTTPS for
the connection between your browser and Home Assistant when entering secrets;
enabling router HTTPS does not secure that separate connection.

Saving remains one-shot. Readback may verify the resulting readable state, or
the form may report an unverified credential, a reconnect requirement or an
unknown outcome. A page change, refresh or failed response never repeats a
write automatically. Check the router before retrying an uncertain operation.
If another section is already saving, the panel rejects a second save before
sending it and reports that the change was not sent. Wait for the active
operation to finish, then refresh the blocked section before trying again.
For disruptive changes, follow the warnings and recovery requirements in the
[management guide](MANAGEMENT.md).

The navigation audit used the real router read-only; editing behavior and
rendering were checked with offline tests and a synthetic preview. No live
router writes were tested for this work. Router acceptance,
change/readback/restoration and recovery still require explicit validation by
the router owner. Automatic reads and navigation coverage do not provide that
evidence.
