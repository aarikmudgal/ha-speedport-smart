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

Live rates use the byte difference between consecutive valid counter samples,
divided by their actual elapsed monotonic time. They are not smoothed over a
ten-second window. A delayed read therefore represents traffic averaged over
that longer sampling interval, not a fabricated one-second measurement.

After a failed read, current rates are unavailable until enough fresh counter
samples arrive; retained or historical data is not presented as a new live
measurement. WAN traffic history remains enabled. Missed slots are not filled
with invented readings. Changing scheduler diagnostic attributes are excluded
from Recorder; the WAN rate and cumulative-counter entities retain their history.
