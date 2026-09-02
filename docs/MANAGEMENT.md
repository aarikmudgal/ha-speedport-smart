# Router management support

Telekom Speedport Smart provides native Home Assistant controls for simple
operations and a structured **Administration** view for complex, private and
destructive operations. Every router command has a fixed implementation. The
dashboard cannot submit arbitrary router endpoints, SOAP actions or JSON forms.
The new beta editors use English while retaining Home Assistant's light/dark theme.

The current write contracts target **Speedport Smart 4R Typ A, firmware
`010152.5.0.001.0`**. A matching model is not sufficient by itself: the current
router response must also prove the required capability, target and form shape.
Other firmware remains read-only unless explicitly reviewed.

## Coverage and evidence

The [complete capability matrix](MANAGEMENT_CAPABILITY_MATRIX.md) lists supported
areas, partial implementations, read-only reporting and unresolved contracts.
It is the coverage reference; a catalog card is not a promise that every option
on a native router page has an executable Home Assistant equivalent.

| Status | Meaning |
| --- | --- |
| Implemented control | An exact firmware request is implemented with input validation, confirmation, conflict checks and the appropriate result policy. |
| Implemented read-only | A reviewed value or private query is available without applying settings. |
| Partial | Some operations in the feature are implemented; the matrix names what remains unproven. |
| Not exposed | A safe, complete local contract was not established. No speculative command is available. |
| Live write untested | The implementation has static evidence and offline tests, but the owner has not yet completed a change/readback/rollback test. |

**No router-setting mutations were executed during development validation.**
The expanded beta administration controls are implementations awaiting owner
testing, not a live certification. Read-only captures establish available
fields and identities; they do not establish that a write succeeds.

Detailed implementation evidence is recorded by area:

- [Internet and network](ADMIN_NETWORK_EVIDENCE.md)
- [Telephony and storage](ADMIN_TELEPHONY_STORAGE_EVIDENCE.md)
- [System and maintenance](ADMIN_SYSTEM_EVIDENCE.md)
- [Call history](ADMIN_CALL_HISTORY_EVIDENCE.md)

## Native controls and structured editors

Native entities cover simple actions such as Wi-Fi enablement, Internet
reconnect, reboot, WPS, supported Hybrid/receiver/privacy settings, existing
port-forward activation, client naming and fixed DHCP. These remain available
through normal Home Assistant services and automations. Dashboard confirmation
does not intercept service calls made elsewhere; configure automations carefully.

The Administration view adds closed editors for supported Internet/LAN settings,
Wi-Fi settings and schedules, network rules, prioritization, telephony,
phonebooks, VPN peers, storage shares, receivers and system settings. Complex
records and secrets are not split into unrelated native entities: they are read
and edited together so required fields and dependencies remain consistent.

To use a structured editor:

1. Open the relevant feature in **Administration**.
2. Select an existing target if required, then explicitly load its current state.
3. Change the intended fields. Secret fields require explicit entry when the
   firmware does not safely provide a reusable value.
4. Review the warning and enter the requested confirmation phrase.
5. Save once, then inspect the reported result before trying anything again.

Opening a card does not apply a setting. Routine polling, inventory discovery,
setup, reload and diagnostics never execute controls. Unsupported or currently
unavailable actions stay disabled with a reason. Temporarily losing a management
session does not turn an unsupported feature into a supported one.

## Confirmation, conflicts and outcomes

Settings approvals expire after 120 seconds. They bind the administrator, active
Home Assistant login session, router entry, setting, target and current private
revision. Targeted administrator actions use their separate 60-second grants.
Execution rechecks the same identity and state under the router operation lock.
Changed or incomplete records require a fresh load; stale forms are not merged
silently. A consumed or expired approval cannot be reused.

At most one mutation is sent for each approved operation. Where supported,
independent read-only verification runs at bounded intervals of approximately
0, 0.5, 1 and 2 seconds. Verification never repeats the mutation. Explicit router
rejection, transport uncertainty and a mismatching result are different outcomes.

| Result | What to do |
| --- | --- |
| Verified | The supported independent readback matches the requested result. |
| Secret not independently verified | The firmware accepted the action, but it does not expose proof of the secret itself. Check the affected service manually. |
| Reconnect required | The operation can intentionally interrupt access. Wait for the router or service to return and inspect its state. |
| Outcome unknown / manual verification required | Do not assume failure or success. Check the router before issuing another action. |
| Rejected, stale or unavailable | Reload the current state and resolve the stated prerequisite before proceeding. |

Online phonebook linking has two separate approvals. After account validation,
the dashboard asks whether to merge or replace existing entries and requires a
second typed confirmation. It never chooses that destructive policy implicitly.
The final result does not claim cloud synchronization is complete.

## Private data and files

Private settings, target lists, phonebooks, call history and command results use
authenticated, administrator-only HTTP requests with `no-store` responses.
They do not use Home Assistant's WebSocket payload logging path. Metadata alone
continues through the normal panel API. Private records and credentials are not
copied into entity attributes, Recorder, diagnostics or browser storage.

Use **HTTPS for Home Assistant** when entering credentials or retrieving private
files. Router HTTPS and Home Assistant HTTPS are separate connections; enabling
one does not encrypt the other. Do not configure external proxies or debugging
middleware to log request or response bodies.

The panel supports reviewed backup/restore and firmware-file transfers,
phonebook import/export, private system-log download and Router-Pass download.
File uploads bind a confirmation to the exact size and digest. Transfer grants
are short-lived and single-use. A configuration backup, phonebook, Router-Pass,
system log or VPN configuration may contain highly sensitive information; store
downloads privately and never attach them to a public issue.

Router-Pass is a locally generated text card from fresh Wi-Fi settings. An
optional router password entered for that card is sent to Home Assistant only
for file generation; it is not sent to or verified by the router. VPN credential
downloads are exposed only in the private result of the supported verified
operation and expire from the panel instead of becoming persistent entities.

Changing routers, leaving Administration, logging out, losing permission or
disconnecting the panel clears private views and drafts. Ordinary WAN telemetry
updates preserve an editor in progress. After upgrading, reload the dashboard:
old private WebSocket commands are retired and do not execute router operations.
Existing entities, integration options and recorded history are preserved.

## Password changes and destructive operations

Router password changes use isolated authentication sessions. Home Assistant's
stored credential is replaced only after the new password logs in successfully
and identifies the same router. If the outcome is uncertain, protected password
retries are suspended until reauthentication; this avoids repeatedly trying a
credential that may no longer be valid. Public and independent WAN sources can
continue when their own access remains available.

Factory reset, configuration restore, firmware updates, network-mode changes,
receiver restoration and record deletion are explicit administrator operations.
They include the relevant typed phrase and recovery/readiness checks. They can
interrupt Internet access, disconnect Home Assistant, invalidate credentials or
erase working configuration. Back up settings and ensure physical recovery
access before testing them. No automatic rollback is attempted.

## Remaining boundaries

Read coverage and write eligibility are separate. A feature without a proven
write may still expose reviewed read-only information. Unknown fields are not
automatically normalized or rendered simply because a JSON response contains
them. Incomplete collection schemas, undocumented flags and actions without a
complete bound form remain partial or unavailable as described in the matrix.

Examples include undocumented LAN IPv6 semantics, SIM PIN/PUK operations,
unproven routing-exception creation forms and NAS directory browsing/creation
without a proven directory-list contract. There is no generic raw-command
escape hatch. Filling these gaps requires new evidence, not fabricated values
or unconfirmed writes on a user's router.

For session contention and safe recovery, see [support](../SUPPORT.md). For beta
installation and versioned releases, see [the release process](RELEASING.md).
