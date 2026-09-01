# Architecture

Telekom Speedport Smart is a localized, local-polling Home Assistant
integration with English and German translations. Its stable domain is
**speedport_smart**. The first validated
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
runtime. Text entities expose only bounded, firmware-proven editable values.

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

When the router temporarily refuses a ToTR64 telemetry lease, the last confirmed
cumulative byte, packet, error, and discard counters remain valid historical
readings. They retain their value and original sample time; the dashboard marks
them amber as **last confirmed** instead of presenting them as live. Derived
rates, utilization, and live WAN-interface state become unavailable. A fresh
counter read clears the source error, refreshes interface state and totals, and
starts a new rate baseline; a second sample is required before rates are shown.
This telemetry-only retry does not block protected JSON management access or
create a Router problem.

Five default-enabled diagnostic sensors expose the scheduler to Home Assistant
automations: configured mode, effective interval, learning state, fastest
successfully proven interval, and last successful sample time. The dashboard
reads the same diagnostics and never infers or hardcodes the polling cadence.

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

Fixed sensor and binary-sensor platforms also listen for newly proven values.
This lets a provisional WAN capability that was busy during setup add its fixed
entities after the first successful sample without requiring an integration
reload.

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

Stateful commands execute through the shared arbiter, then refresh their owning
poll group to verify returned state. Reboot and Internet reconnect are explicit
exceptions: their expected network interruption makes immediate readback
impossible, so they require a positive router acknowledgement and let normal
polling prove recovery. The bundled panel adds a confirmation dialog, with
stronger language for disruptive actions. Other Home Assistant callers retain
normal entity semantics, so an automation invoking a control is itself the
deliberate action.

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
