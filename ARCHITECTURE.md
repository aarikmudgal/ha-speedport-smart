# Architecture

Telekom Speedport Smart is a local-polling Home Assistant integration with
English and German integration translations; the newer administration editors
currently use English. Its stable domain is
**speedport_smart**. The first validated
target is the Speedport Smart 4R Typ A, while runtime discovery avoids assuming
that every model and firmware exposes the same endpoints.

## Runtime contract

- UI setup requires a reachable router host and its device password.
- DHCP and SSDP announcements are untrusted discovery hints. SSDP matching uses
  the captured `Speedport Smart 4 R Typ A` `modelName` spelling plus the exact
  Telekom manufacturer and WLAN access-point device type. An unauthenticated
  public-status read over HTTP must then prove the Status API's exact
  allowlisted `Speedport Smart 4R Typ A` model spelling and a stable serial.
  User confirmation runs the normal read-only connection validation and must
  return the same identity.
  Discovery never changes an existing entry's host or reuses its stored
  password against a newly announced address; address changes require explicit
  reconfiguration.
- One serialized protocol client owns encrypted JSON authentication, ToTR64
  SOAP requests, cookies, and the management lease.
- Fast, normal, and slow coordinators isolate different polling cadences.
- Initial entity creation requires an implemented descriptor and discovered
  capability evidence.
- A confirmed absent capability is omitted. A temporary failure of an already
  supported source preserves the entity identity and marks it unavailable.
- Diagnostics expose runtime health only after privacy redaction.
- Router mutation occurs only after an explicit Home Assistant user action.
- Setup, polling, capability discovery, recovery, diagnostics, and panel
  rendering never invoke a router-changing command.

Home Assistant config entries own normal setup, reload, reauthentication,
reconfiguration, and unload behavior. Platforms expose sensors, binary sensors,
device trackers, switches, selects, buttons, text controls, and update entities
backed by the shared runtime. Text entities expose only bounded,
firmware-reviewed editable values.

## Protocol and session ownership

**SpeedportClient** owns transport, authentication, encrypted JSON decoding,
ToTR64 SOAP, bounded retries, owned-session logout, and request serialization.
**SpeedportHub** owns polling groups, normalization, capability discovery, rate
calculation, management state, Repair issues, and semantic commands.

The integration uses Home Assistant's shared HTTP connector with a private
cookie jar. This prevents unrelated integrations from acquiring or leaking the
router management cookie while preserving normal Home Assistant connection
management. Authenticated batches release their owned session in finalization
paths. Read requests may retry only when replay is safe; write requests are
never blindly replayed.

## Polling groups

| Data path | Default | Allowed range or behavior | Responsibility |
| --- | ---: | ---: | --- |
| Internal live scheduler | 1 second | Fixed; a tick sends a request only when that source is due | Coordinates independent public-status and WAN-counter due times |
| Public status (Fast option) | 5 seconds | 1 to 60 seconds | Browser-independent live connection data |
| WAN counters | Auto (`0`) | Auto learning, or an advanced target from 1 to 60 seconds | Cumulative counters and derived rate/utilization |
| Normal | 30 seconds | 15 to 300 seconds | Operational state, Wi-Fi, clients, telephony |
| Slow | 5 minutes | 1 to 60 minutes | Configuration, topology, firmware, slow-changing services |

Each endpoint family is isolated. A protocol or management-session failure in
one family does not automatically invalidate unrelated data. Once support has
been established, the affected entities become unavailable until a fresh value
succeeds instead of continuing to display stale state. Cumulative WAN counters
are the narrow exception described below.

Panel focus is a connection-scoped, expiring scheduling lease. Dashboard gives
WAN priority; Administration gives explicit settings operations priority.
Automatic Normal and Slow polling waits while a panel is focused, without
changing its data timestamps. Hidden, disconnected or expired panels release the
lease. The operation gate never preempts an active transaction or allows two
router operations to overlap. See [WAN polling](docs/WAN_POLLING.md) for timing
and background-refresh tradeoffs.

## WAN counters and rates

The client enumerates ToTR64 **Device.IP.Interface** objects and selects the
active aggregate WAN interface instead of hardcoding an object index. On the
validated Hybrid router, **BONDING/habond** already includes combined WAN
traffic; LTE tunnel counters are therefore not added again.

Router-provided **BytesReceived** and **BytesSent** values are cumulative
64-bit counters. The hub derives live download and upload rates from counter
differences between the latest two valid observations over their actual monotonic
interval, without a rolling smoothing window. It rejects negative
deltas, counter resets, stale epochs, and reboot spikes. The result is
aggregate WAN throughput, not per-client traffic or packet capture.

Total byte entities use Home Assistant's total-increasing statistics model.
Longer consumption periods belong to Home Assistant long-term statistics and
Utility Meter helpers rather than a second persistence engine inside this
integration.

Auto WAN polling starts at five seconds. The hub counts five consecutive,
complete successful counter polls at each cadence before stepping through
`5 → 4 → 3 → 2 → 1` seconds. Five successful polls at the target mark the
cadence as proven. Manual mode keeps its requested target and uses the same
five-poll validation window without stepping faster.

A failed WAN read resets that success streak and enters **Cooldown** for a
fixed 60 seconds measured from completion of the failed request. The effective
cadence does not roll back or acquire a slower runtime floor. When the deadline
passes, the hub retries that same cadence; another failure restarts the same
60-second delay. Unsupported endpoints are still excluded. Public status and
the Normal and Slow polling groups keep their independent schedules.

WAN due times follow anchored slots rather than response completion plus another
interval. The FAST coordinator schedules against the next due time instead of
allowing Home Assistant's phase rounding to skip otherwise eligible WAN reads.
The existing operation and client locks prevent overlapping router requests.
Missed slots are skipped, not accumulated or replayed in catch-up bursts. Slow
valid responses are accepted. Transport time, scheduling jitter and other
serialized operations can still extend the actual sample spacing. See
[WAN polling](docs/WAN_POLLING.md) for the user-facing timing contract.

When the router temporarily refuses a ToTR64 telemetry lease, the last confirmed
cumulative byte, packet, error, and discard counters remain valid historical
readings. They retain their value and original sample time; detailed telemetry
can identify them as **last confirmed**, not live samples. The minimal dashboard
does not show cumulative counters by default. Derived
rates, utilization, and live WAN-interface state become unavailable. A fresh
counter read clears the source error, refreshes interface state and totals, and
starts a new rate baseline; a second sample is required before rates are shown.
This telemetry-only retry does not block protected JSON management access or
create a Router problem.

Five default-enabled diagnostic sensors expose the scheduler to Home Assistant
automations: configured mode, effective interval, learning state, fastest
successfully proven interval, and last successful sample time. The dashboard
reads the same diagnostics and never infers or hardcodes the polling cadence.
The current state is **Learning**, **Cooldown** or **Stable**. The footer uses
reported progress, the observed interval between consecutive successful samples,
and an approximate countdown from existing metadata updates;
it adds no timer or router request. Changing success-count and countdown
attributes are excluded from Recorder while WAN traffic history remains enabled.

## Capability and entity lifecycle

Capability discovery separates three states:

1. **Supported:** a usable endpoint and source value have been observed.
2. **Unsupported:** the router has confirmed that the endpoint or value does
   not exist.
3. **Temporarily unavailable:** support was previously established, but the
   current read failed or a competing session owns protected access.

Only supported capabilities create entities. The registry remains stable
through temporary errors. Dynamic child devices use stable router identifiers
for clients, Mesh nodes, mobile receivers, telephone lines, DECT handsets, IP
phones, and USB devices when the source provides one.

Version 0.3.0 intentionally retires the router-event entity, three router-global
NAS binary sensors and nine router-level control placeholders. Setup removes
only their exact integration-owned registry matches; temporary source failures
do not trigger those migrations. Remaining entities and user options are not
bulk-replaced. The [management guide](docs/MANAGEMENT.md#entity-retirements)
lists the retired keys and automation implications.

Fixed sensor and binary-sensor platforms also listen for newly proven values.
This lets a provisional WAN capability that was busy during setup add its fixed
entities after the first successful sample without requiring an integration
reload.

Every fixed native scalar sensor and binary sensor is also classified by an
immutable read-contract registry containing its entity key, normalized data
path, platform, and capability gates. The registry makes accidental native read
surface growth visible in review; it does not normalize router data, create an
entity, perform I/O, or authorize a write. Collection entities and the bounded
administrator projection retain their own explicit reviewed schemas.

Feature families include internet/WAN, DSL, Hybrid/mobile, Wi-Fi/Mesh, clients,
LAN/DHCP/NAT, telephony, system/firmware, security, DDNS/VPN, parental controls,
USB, and integration diagnostics. Their presence is firmware-dependent and is
never inferred merely because a descriptor exists in source code.

## Management-session state machine

Protected Speedport endpoints may permit one owner. The diagnostic
**Management access** enum reports:

- **available:** protected access last succeeded
- **other_session:** the router reported another owner
- **blocked:** access is busy without an owner address
- **locked:** the router imposed a login cooldown
- **recovering:** a user-requested read-only retry is running
- **unavailable** or **unknown:** protected access is not currently confirmed

Safe attributes can include **owner_ip_address**,
**browser_logout_required**, **retry_after_seconds**, **last_changed**, and
**last_successful_update**.

When another session owns the lease, the hub creates one persistent
per-config-entry Home Assistant Repair issue. The Repair flow tells the user to
select **Logout** in the router web interface because closing a tab may retain
the lease. Successful protected access clears the issue.

The **Retry protected data (log out of the router first)** button performs
read-only rediscovery and schedules a clean integration reload after success.
There is no forced takeover path: the integration cannot safely invalidate a
browser session whose cookie and challenge it does not own.

## Router control boundary

Command descriptors are separate from read-only polling. A native entity
control is created only when all of these conditions hold:

- the integration option permits controls
- authenticated JSON management is supported
- an immutable native-entity command contract exists
- the router model and firmware exactly match that contract
- the contract's semantic capability is present
- the contract names an available client handler
- the source state required to verify the result is available

The command decision retains those support reasons independently. Current
management-session state, retry backoff, and the firmware write-block latch gate
execution availability without changing whether the control is supported. Home
Assistant entity permissions remain a separate authorization boundary. Each
contract also binds one semantic feature ID, the exact client handler, and the
accepted parameter-name set; missing or extra parameters fail closed before
router I/O.

Stateful commands execute through the shared arbiter, then refresh their owning
poll group to verify returned state. Reboot and Internet reconnect are explicit
exceptions: their expected network interruption makes immediate readback
impossible, so they require a positive router acknowledgement and let normal
polling prove recovery. The bundled panel adds a confirmation dialog, with
stronger language for disruptive actions. Other Home Assistant callers retain
normal entity semantics, so an automation invoking a control is itself the
deliberate action.

Structured, private and destructive operations use separate closed
administrator contracts, not generic native entities. These include reviewed
credential changes, record deletion, reset, restore and private-file flows.
Approvals bind the administrator, active Home Assistant login session, loaded
router entry, exact operation/target and fresh private state. They expire and
are single-use. Authorization is checked again immediately before router
mutation, including after lock and authentication waits. Owned-session logout
remains permitted for cleanup after authorization is lost.

Each approved operation sends at most one mutation. Bounded independent
readback can verify readable state; it never resends the write. Disruptive,
asynchronous or secret-only outcomes remain unverified, reconnect-required or
unknown where the firmware cannot provide complete proof. Router-password
change uses isolated sessions and updates the Home Assistant credential only
after the new password proves the same router identity. An uncertain outcome
suspends protected credential retries until reauthentication.

SIM PIN/PUK operations, global firewall disable, arbitrary SOAP/endpoint
execution and raw NAT-session export remain excluded. The
[capability matrix](docs/MANAGEMENT_CAPABILITY_MATRIX.md) separates implemented
contracts from unsupported operations and untested live writes. Preparing a
stable release does not turn static evidence or offline tests into live-write
certification.

## Native panel

The integration registers one Home Assistant custom panel at
**/speedport-smart**. Its JavaScript and static assets ship inside the
integration package. It is not a Lovelace resource and requires no separate
HACS frontend repository.

The primary backend WebSocket command returns permission-filtered entity
metadata, router identity, capability families, and management status without
performing router I/O. Live states come from Home Assistant's state model. The
minimal dashboard's bounded traffic graph reads ordinary Recorder
history for the selected router's two rate entities once per view scope and
once per explicit timeframe change, then adds observed live samples. Its
5, 15, 30 and 60-minute windows retain at most 1,024 observations per series,
using wider buckets for longer windows without averaging or inventing values.
The default is 15 minutes. It uses the successful WAN sample clock for
unchanged rates, leaves missing/stale samples as gaps and inspects actual sample
times and values without interpolation. This adds no custom history store.

A separate transferred-volume graph uses the existing cumulative byte entities,
not integration of the rate graph. It adds nonnegative differences between
usable consecutive observations inside the selected window, using the same 5,
15, 30 and 60-minute selection and automatic decimal MB, GB or TB units.
Recorded history and the existing live state stream supply its samples. It does
not interpolate a window boundary. Missing, stale, reset and long-gap segments
do not create traffic; valid segments can still produce an explicitly partial
subtotal. Neither graph adds router requests or changes Recorder configuration.

Administration uses native-style top tabs, left menus and page-local forms.
Its navigation accounts for all 69 screens in the observed firmware audit;
navigation coverage does not imply that every operation is implemented.
Entering a page reads its supported settings automatically; selecting an
existing target reads that record. The three call-list pages similarly read
only their selected private category. Saves, destructive actions and downloads
remain explicit. Ordinary WAN rendering preserves editor drafts, focus and
private views; changing scope clears them. Management-session changes discard
stale idle drafts and allow a dispatched write to report its outcome before
refreshing other page forms. A newly available sibling section can also load
without replacing existing forms or drafts. If a write is active, that read is
deferred until the result is available and is cancelled when its page, router or
administrator scope changes. Failed sections are not retried on every metadata
or WAN update.

Value-bearing administrator JSON operations use the closed authenticated HTTP
adapter at **/api/speedport_smart/private/{entry_id}**, with bounded JSON and
**no-store** responses. This includes the allowlisted normalized-cache
projection, which itself performs no router I/O, and separate fresh settings,
target and private-query operations. Private payloads do not pass through Home
Assistant's WebSocket logging path. File transfers use separate authenticated,
bounded HTTP prepare/execute routes with single-use size/digest-bound grants,
not large base64 WebSocket payloads. Browser code never connects to the router.

The Administration catalog also lists static firmware candidates and planned
features. Those entries are evidence and navigation metadata only: they do not
create a capability, normalized field, entity, command contract, or generic
mutation endpoint. Only registered reviewed contracts have an executor, and
their current firmware, capability, identity and form prerequisites still gate
availability.

Static-route, HTTP-view and WebSocket registration are process-scoped.
Config-entry reloads leave those global registrations in place; panel ownership
itself is tracked to avoid duplicate registration. Private routes require a
currently loaded entry. Legacy private WebSocket commands reject before router
work; users must hard-refresh stale frontend code after upgrading.

## Diagnostics and privacy

The diagnostics layer recursively redacts credentials, public addresses,
telephone numbers, client MAC addresses, SIM identifiers, VPN material, raw
logs, and router payloads. Protocol fixtures and issue reports must be
sanitized independently; raw firmware responses are never acceptable public
test data.

Router communication remains on the local network. Private records, credentials
and download contents do not become entity state, Recorder data or persistent
browser application storage. Private views can display identifiers needed for
administration, and explicit private downloads can contain secrets; those are not redacted
diagnostics. Home Assistant HTTPS is required to protect the separate
browser-to-Home-Assistant connection, and external request-body logging must
remain disabled.

## Repository and release contract

Runtime files live under
**custom_components/speedport_smart** so the repository contains one HACS
integration. The release archive is named **speedport_smart.zip** and places
the contents of that directory at the archive root.

The version in **manifest.json** and **pyproject.toml** is the stable source
version and must match:

- a **main** build creates stable tag **vX.Y.Z** when that source version has
  not already been released; otherwise it validates that the existing release
  has identical package content and performs a successful no-op
- a branch matching <code>feat/*</code> packages
  **X.Y.Z-beta.RUN.ATTEMPT** and creates a GitHub prerelease without modifying
  the source files

CI, Hassfest, HACS validation, release archive inspection, and the test suite
are release gates. The presence of local workflows is not evidence that remote
checks have passed; GitHub must run them successfully on the public repository.

## Deliberate non-goals

- Independent cloud control or telemetry; reviewed local EasySupport flags and
  user-configured online-phonebook flows are separate
- Packet capture or traffic-content inspection
- Inferred per-client throughput from aggregate WAN counters
- A second history, database, or statistics engine
- Forced management-session takeover
- Automatic router-setting changes
- Placeholder entities for absent firmware capabilities
- Claims of support for unvalidated model/firmware combinations
