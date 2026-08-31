# Architecture

Telekom Speedport Smart is an English-first, local-polling Home Assistant
integration. Its stable domain is **speedport_smart**. The first validated
target is the Speedport Smart 4R Typ A, while runtime discovery avoids assuming
that every model and firmware exposes the same endpoints.

## Runtime contract

- UI setup requires a reachable router host and its device password.
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
device trackers, switches, buttons, and update entities backed by the shared
runtime.

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

| Group | Default | Allowed range | Responsibility |
| --- | ---: | ---: | --- |
| Fast | 5 seconds | 1–60 seconds | WAN counters, derived rate/utilization, live connection data |
| Normal | 30 seconds | 15–300 seconds | Operational state, Wi-Fi, clients, telephony |
| Slow | 5 minutes | 1–60 minutes | Configuration, topology, firmware, slow-changing services |

Each endpoint family is isolated. A protocol or management-session failure in
one family does not automatically invalidate unrelated data. Once support has
been established, the affected entities become unavailable until a fresh value
succeeds instead of continuing to display stale state.

## WAN counters and rates

The client enumerates ToTR64 **Device.IP.Interface** objects and selects the
active aggregate WAN interface instead of hardcoding an object index. On the
validated Hybrid router, **BONDING/habond** already includes combined WAN
traffic; LTE tunnel counters are therefore not added again.

Router-provided **BytesReceived** and **BytesSent** values are cumulative
64-bit counters. The hub derives live download and upload rates from counter
differences over monotonic time and a short rolling window. It rejects negative
deltas, counter resets, stale epochs, and reboot spikes. The result is
aggregate WAN throughput, not per-client traffic or packet capture.

Total byte entities use Home Assistant's total-increasing statistics model.
Longer consumption periods belong to Home Assistant long-term statistics and
Utility Meter helpers rather than a second persistence engine inside this
integration.

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

Command descriptors are separate from read-only polling. A control is created
only when all of these conditions hold:

- the integration option permits controls
- the firmware capability is present
- a specific semantic command handler exists
- the source state required to verify the result is available

Every command executes through the shared arbiter, then refreshes its owning
poll group to verify returned state. The bundled panel adds a confirmation
dialog, with stronger language for disruptive actions. Other Home Assistant
callers retain normal entity semantics, so an automation invoking a control is
itself the deliberate action.

Factory reset, configuration restore, administrator/Wi-Fi/SIP credential
changes, SIM PIN/PUK operations, VPN secret export, firewall disable, arbitrary
SOAP execution, raw NAT-session export, and destructive Mesh or telephone
deletion are excluded.

## Native panel

The integration registers one Home Assistant custom panel at
**/speedport-smart**. Its JavaScript and static assets ship inside the
integration package. It is not a Lovelace resource and requires no separate
HACS frontend repository.

The backend WebSocket command returns permission-filtered entity metadata,
router identity, capability families, and management status without performing
router I/O. Live states come from Home Assistant's state model. The frontend
groups them by functional hierarchy and child device, follows Home Assistant
theme variables, and adapts to mobile layouts.

Static-route and WebSocket registration are process-scoped because Home
Assistant has no supported unregister API for them. Config-entry reloads leave
those global registrations in place; panel ownership itself is tracked to
avoid duplicate registration.

## Diagnostics and privacy

The diagnostics layer recursively redacts credentials, public addresses,
telephone numbers, client MAC addresses, SIM identifiers, VPN material, raw
logs, and router payloads. Protocol fixtures and issue reports must be
sanitized independently; raw firmware responses are never acceptable public
test data.

Router communication remains on the local network. The bundled panel consumes
Home Assistant registry and state data rather than opening an independent
browser-to-router connection.

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

- Cloud control or telemetry
- Packet capture or traffic inspection
- Inferred per-client throughput from aggregate WAN counters
- A second history, database, or statistics engine
- Forced management-session takeover
- Automatic router-setting changes
- Placeholder entities for absent firmware capabilities
- Claims of support for unvalidated model/firmware combinations
