# Private call-history configuration contracts

This offline tranche connects the existing `call_history.py` contracts to the
requester-bound, one-shot settings editor. It does not contact the router or
claim a successful live history clear.

## Exact bindings

The three actual pages use `data/PhoneCalls.json` as their JSON source. Their
companion scripts bind separate destructive endpoints:

| Settings ID | Category endpoint | Referer |
| --- | --- | --- |
| `call_history_clear_dialed` | `data/PhoneDialedCalls.json` | `html/content/phone/phone_call_dialed.html` |
| `call_history_clear_missed` | `data/PhoneMissedCalls.json` | `html/content/phone/phone_call_missed.html` |
| `call_history_clear_taken` | `data/PhoneTakenCalls.json` | `html/content/phone/phone_call_taken.html` |

Each body is exactly `action_clearlist=true` with the string value `true`.
The bindings are in saved `phone--phone_call_dialed.js:30,51`,
`phone--phone_call_missed.js:21,42`, and `phone--phone_call_taken.js:52,73`.
These callbacks clear the displayed template without checking a positive ACK;
the settings contracts therefore use `acknowledgement="readback"`. The clear
editor has only one boolean confirmation field. It does not expose call
records in standard settings state or metadata.

## Readback, privacy and missing evidence

Only an explicitly present, complete category can authorize a clear. All
observed records participate in the session's private HMAC revision. A new
call before saving invalidates the draft even though its public checkbox is
unchanged. After the sole POST, the selected category must be explicitly empty.
Other previously observed categories must retain their complete row multiset;
new calls in those other categories are permitted. A missing collection, a
retained row, or a new selected-category call produces an uncertain outcome.
Only readback GETs retry; a clear is never automatically sent again.

The saved live v11 replies lacked all three collections. As recorded in
`ADMIN_TELEPHONY_STORAGE_EVIDENCE.md`, that global fallback is not evidence of
empty call history. The contracts remain unavailable on those replies. There
is no new fallback, guessed alternate endpoint, or invented empty collection.

`call_history_read_source(category)` resolves the fixed GET and referer.
`call_history_private_read(raw, category)` returns only the selected private
list. `call_history_private_export(raw, category)` returns a `private_download`
object with `filename`, `media_type`, and `content`, matching the existing
ephemeral administrator download seam. CSV generation is local and protects
spreadsheet formula prefixes. There is no router export request, public URL,
server-side file, recorder entity, persistent history cache, or snapshot
publication.

The integrated `speedport_smart/panel/call_history` private command accepts only
the selected entry, one of `dialed`, `missed`, or `taken`, and an optional strict
boolean `export`. Administrator authorization occurs before entry lookup. The
client makes one authenticated `PhoneCalls.json` GET with that category's
referer. The hub uses the existing shared operation lock and private-query
cleanup, requires the exact authenticated `calls` capability, and applies the
shared one-second rate limit. Router controls need not be enabled for these
read-only requests. The authenticated administrator-only private HTTP transport
dispatches this closed command and returns a no-store response to that request.
It does not send private records through Home Assistant WebSocket frames or
their core debug logging, and does not replace coordinator data. Legacy
WebSocket clients receive an inert transport-upgrade error.

The isolated `frontend/call-history-view.js` controller never loads on opening
or rendering. Loading and CSV export require distinct explicit button actions;
export performs a fresh private read. Its ordinary snapshot contains only
category, count and status, not records or CSV. Private rendering escapes all
router strings. Close, category changes, entry changes and disposal clear the
private records and invalidate pending responses. A late export response after
close cannot trigger a download. Download URLs are local blob URLs, revoked
after the explicit click; CSV content is not retained in the controller.
The panel integration calls the binder's disposal function on navigation and
does not copy private-renderer records into the general panel snapshot. The
full route and view are wired and tested offline; this is not evidence of a
successful live read or clear for a previously unobserved category schema.
