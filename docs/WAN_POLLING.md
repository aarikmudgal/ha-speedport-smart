# WAN polling

In Auto mode, WAN polling starts at a five-second interval. After five consecutive
successful WAN reads at that interval, it moves one second faster: four seconds,
three seconds, two seconds, then one second. Five successful reads at one second
mark that cadence as stable. These are short validation windows, not a guarantee
that the router will always respond at that speed.

If a WAN read fails, the success count resets and WAN polling enters **Cooldown**
for a fixed 60 seconds, measured from the end of the failed request. It then
retries at the same interval. Another failure starts another 60-second cooldown;
the delay does not increase. A failed faster attempt does not permanently lock
Auto mode to a slower interval.

The dashboard footer distinguishes the target interval from the interval between
the latest two successful samples. It also shows Learning, Cooldown, or Stable,
learning progress and an approximate retry countdown. The **WAN polling state**
entity exposes the same learning state. Metadata updates do not send additional
requests to the router. An observed interval is unavailable until two valid
samples have arrived, including after a failure or counter reset.

Manual mode keeps the configured interval rather than learning a faster one. It
uses the same 60-second cooldown after a failed WAN read. Public status and other
polling groups keep their existing schedules. Unsupported WAN endpoints remain
excluded instead of being retried indefinitely.

WAN reads target fixed time slots, not an additional interval after each response
completes. At a one-second target, the schedule aims for successive one-second
slots. Home Assistant scheduling, router response time and other serialized
router operations can still delay a sample; this is not a real-time guarantee.
Only one router operation runs at a time. Missed slots are skipped rather than
queued or replayed in a burst. A valid slow response is accepted, not discarded
merely because another time slot passed. There are no overlapping WAN responses
that need to be reordered or backfilled into history.

Rates use the **latest two valid counter observations**, not a rolling average.
Each direction uses its actual byte difference multiplied by eight, divided by
the real elapsed monotonic time. A burst appears on the next observation, and
the first unchanged pair returns zero without a smoothed tail. The rate entities
expose `rate_method: consecutive_samples` and the actual
`rate_sample_span_seconds`. A pair spanning a delayed response measures that
longer interval; it is not an instantaneous or guaranteed one-second measurement.

The integration never interpolates counters or holds a previous nonzero rate to
hide missing readings. Repeated totals alone cannot distinguish no traffic from
delayed router-side accounting. If firmware returns totals in batches, removing
smoothing exposes their zero/jump pattern; faster requests cannot recover
measurements the router did not provide. Neither the local counter contract nor
the protocol specification supplies a guaranteed source refresh interval.

## Focus-based priority

The panel claims a short-lived focus lease only while it is connected, visible,
and focused. Dashboard focus gives WAN reads priority. Administration focus gives
explicit settings reads and user-requested operations priority; WAN continues
between those operations. Public status retains its existing FAST due time.

While either panel view has focus, automatic NORMAL and SLOW refreshes wait
outside the operation lock. Their retained data and last-success timestamps do
not become fresh merely because a refresh was deferred. Protected details can
therefore be older while watching traffic or editing a settings screen. The
dashboard exposes the active priority and deferred background refreshes.

Leaving the panel, hiding the page, losing window focus, changing router or
disconnecting releases the lease. A 45-second server expiry also handles lost
clients; active panels renew every 15 seconds without router requests. With
multiple panels, the most recently acquired focus wins; a heartbeat cannot
steal focus from another panel. Administration claims require an administrator;
dashboard claims require permission to read the router.

Without panel focus, background refreshes resume at their existing configured
cadences. Queued WAN work has priority over administration and background work.
Missed background refreshes are not accumulated into a replay queue. An operation
already running always finishes its atomic sequence before another begins;
focus changes never cancel a router write, logout, or readback. Consequently,
opening Dashboard during an existing protected batch can still initially wait
for that batch to finish.

WAN reads remain owned exclusively by the FAST polling sequence. NORMAL and
SLOW work can delay a waiting WAN read, but they never insert an opportunistic
WAN request immediately after an authenticated web session. This separation
avoids a transient post-logout TR-064 busy response becoming a 60-second WAN
cooldown. DSL retains its bounded busy retries inside the NORMAL sequence so a router
lease still settling after logout is not immediately handed to FAST. Exhausting
those retries uses the existing deferred DSL retry policy. Only a later FAST WAN
request can change WAN cooldown state.

Slow individual requests and already-running protected batches can still delay
samples. Busy DSL retries remain bounded and observable; uninterrupted
one-second delivery is not guaranteed. Downloaded diagnostics separate polling lock wait, router
work and total update time, plus NORMAL feature-read and DSL-read durations.

After a failed read, current rates are unavailable until enough fresh counter
samples arrive; retained or historical data is not presented as a new live
measurement. WAN traffic history remains enabled. Missed slots are not filled
with invented readings. Changing scheduler diagnostic attributes are excluded
from Recorder; focus leases are not persisted, and the WAN rate and
cumulative-counter entities retain their history.
