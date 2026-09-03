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

Rates use a **five-second average window**, independently of the polling
interval. Some router firmware returns the same cumulative counters for several
one-second requests, then advances them in a batch. Treating each duplicate as
instantaneous zero traffic creates misleading zero/spike readings. Faster
requests cannot recover one-second measurements that the source does not expose.

The average uses the actual byte difference from the retained valid sample
nearest five seconds earlier, divided by the real elapsed monotonic time. It
does not interpolate counters or hold a nonzero rate indefinitely. During startup
or slow polling, the available sample span can differ from five seconds. The
dashboard labels the configured window and shows the actual span when materially
different; the rate entities expose both as attributes. Once unchanged counters
fill the averaging window, the rate returns to zero.

NORMAL polling publishes any due WAN sample after its protected reads have
finished logout and session settling, before optional DSL telemetry. It uses the
same WAN deadline and cooldown as FAST polling, so a waiting FAST update does
not repeat that request. The operation lock stays held and administrator
transactions remain atomic; there are no concurrent SOAP and web sessions.
Scheduled DSL reads make one attempt on a busy response and use the existing
deferred retry policy instead of sleeping through up to 7.5 seconds of inline
retries. Discovery and explicitly requested DSL reads retain their retry defaults.

Slow individual requests and protected batches can still delay samples. This
change reduces avoidable blocking; it does not guarantee uninterrupted
one-second delivery. Downloaded diagnostics separate polling lock wait, router
work and total update time, plus NORMAL feature-read and DSL-read durations.

After a failed read, current rates are unavailable until enough fresh counter
samples arrive; retained or historical data is not presented as a new live
measurement. WAN traffic history remains enabled. Missed slots are not filled
with invented readings. Changing scheduler diagnostic attributes are excluded
from Recorder; the WAN rate and cumulative-counter entities retain their history.
