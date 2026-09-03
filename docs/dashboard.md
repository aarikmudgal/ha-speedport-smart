# Dashboard and Administration

The bundled Home Assistant panel has two separate views. **Dashboard** retains
its existing reporting, live traffic graphs and device cards.
The new **Administration** layout organizes router settings into pages within
that same panel. It does not embed the router website or replace Home
Assistant's standard device and entity pages.

## Administration navigation

Administration has six router tabs, in this order: **Overview**, **Status**,
**Internet**, **Telephony**, **Network** and **System**. On desktop, the left
navigation shows the pages belonging to the selected tab, including nested
Internet-connection, Wi-Fi and DECT pages. On smaller screens, the contextual
page navigation is available through the mobile menu.

The navigation follows the organization shown in the official
[Speedport Smart 4R manual](https://www.telekom.de/hilfe/downloads/bedienungsanleitung-speedport-smart-4r)
and the reviewed firmware pages. It uses Home Assistant's theme and responsive
controls; it is not intended to reproduce every router screen pixel for pixel.
Other router models and firmware versions may expose different capabilities.

The current navigation contains **48 content pages** plus the Wi-Fi navigation
group (49 navigation entries). It maps **120 existing router
feature entries** and **110 existing settings editors** to their relevant
pages without duplicating those editor launchers. These are navigation counts,
not a claim that 120 features are writable, that every page has an editor, or
that every feature is supported by the connected router. Entries can contain
read-only information, an unavailable action, or an explanation of an
unsupported operation. The [capability matrix](MANAGEMENT_CAPABILITY_MATRIX.md)
describes the implemented subsets and remaining limits.

Home Assistant-specific recovery and inventory actions remain in the separate
**Home Assistant integration tools** section on Overview. They are not presented
as native router settings.

## Reading and editing a page

Opening a page automatically reads the selected available settings form.
When a page has several forms, choosing another form reads that form's current
values. This does not load every editor in the background. Existing-object
forms first read their available targets, then read the selected target; the
target picker reads a newly selected target automatically. None of these
navigation or selection operations saves router settings.

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
router state requires a fresh **Refresh** before saving. Loading another form,
changing targets, or leaving the editor clears its private draft state. A
refresh does not extend an old approval: it obtains current state again.

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
For disruptive changes, follow the warnings and recovery requirements in the
[management guide](MANAGEMENT.md).

The redesign was checked with offline tests. No live router writes were tested
for this work. Router acceptance, change/readback/restoration and recovery still
require explicit validation by the router owner. Automatic reads and navigation
coverage do not provide that evidence.
