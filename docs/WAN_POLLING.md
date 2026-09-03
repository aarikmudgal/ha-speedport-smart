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

The dashboard footer and the **WAN polling state** entity show Learning,
Cooldown, or Stable. The footer also shows learning progress and an approximate
retry countdown. Countdown updates use the dashboard's existing metadata refresh;
they do not send additional requests to the router.

Manual mode keeps the configured interval rather than learning a faster one. It
uses the same 60-second cooldown after a failed WAN read. Public status and other
polling groups keep their existing schedules. Unsupported WAN endpoints remain
excluded instead of being retried indefinitely.

Intervals are minimum delays after requests complete. Request duration, the
coordinator schedule, and other serialized operations can make actual samples
farther apart. After a failed read, current rates are unavailable until enough
fresh counter samples arrive; retained or historical data is not presented as a
new live measurement. WAN traffic history remains enabled. The changing retry
countdown and learning counter are diagnostic attributes excluded from Recorder.
