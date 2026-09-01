# Read-only protocol descriptor discovery

`scripts/discover_service_descriptors.py` inventories only the UPnP/TR-064
services that a router advertises in a device description and its SCPD files.
It is a developer evidence tool, not part of the Home Assistant runtime.

The utility performs unauthenticated HTTP `GET` requests only. It never sends a
SOAP action, subscribes to events, authenticates, executes a control URL, or
changes a router setting. Redirects are not followed. Root and linked SCPD
documents must remain on the exact same HTTP(S) origin with an explicit port.
DTD/entity declarations, malformed XML, oversized documents, excessive XML
depth, and excessive service counts fail closed.

Run with the bounded family-context candidates:

```console
python -m scripts.discover_service_descriptors --host speedport.ip
```

Or provide one or more exact same-host root URLs. Supplying a `--root-url`
replaces the defaults:

```console
python -m scripts.discover_service_descriptors \
  --host speedport.ip \
  --root-url https://speedport.ip:8443/tr64desc.xml \
  --out service-descriptors.json
```

Use `--no-verify-ssl` only when the router uses a local certificate that the
machine does not trust.

## Output and privacy boundary

The deterministic JSON contains:

- `advertised_only: true`
- sanitized root path, scheme, explicit port, HTTP status, SHA-256, and service
  count
- advertised service type and ID plus SCPD, control, and event **paths only**
- SCPD action names and arguments
- SCPD state-variable names, data types, enums, ranges, and event flags
- sanitized partial-failure codes with URL paths only

It deliberately omits the target host, raw XML, headers, cookies, device names,
model names, serial numbers, addresses, and all values outside the advertised
service schema.

Advertisement is discovery evidence only. It does not prove that an action is
authorized, safe, or executable, and the output must never generate runtime
entities or generic router commands. A management control still requires a
static reviewed implementation, complete authentication and request contract,
positive acknowledgement semantics, independent readback, stable identity,
and an explicit user-authorized validation roundtrip.

## User-operated reversible control capture

`scripts/sanitize_control_capture.py` converts one browser Network-panel HAR
into a privacy-safe contract report. The script is offline and stdin-only. It
does not connect to the router or send a request. It supports one reversible,
scalar setting at a time; it is not a proxy, recorder, generic router client,
or authorization to exercise destructive and secret-bearing operations.

The browser capture itself is highly sensitive. It can contain encrypted
request and response bodies, cookies, session identifiers, login proof,
CSRF/HTTP tokens, addresses, device identifiers, Wi-Fi names, telephone data,
and other household information. A browser's own “sanitized HAR” option is not
the security boundary for this workflow.

### Capture sequence

1. Disable other router integrations and use a disposable browser profile.
2. Open the Network panel before logging in. Clear it and retain only the
   router origin. Starting before login is required because the sanitizer uses
   the captured challenge to decode the temporary AES-CCM session in memory;
   it never needs the router password.
3. Load the setting page and refresh its exact read endpoint to record the
   baseline.
4. Change exactly one reversible scalar setting in the router UI. Do not use
   the tool for reset, delete, credential, key, upload, restore, firmware, or
   other destructive/private operations.
5. Refresh the independent read endpoint, restore the original value in the
   router UI, refresh the same endpoint again, and log out.
6. Filter the Network panel to the one router origin and copy the HAR with
   response content to the clipboard. Prefer piping it directly to the
   sanitizer instead of exporting a raw HAR file.

On macOS, a capture for a reviewed binary scalar can be sanitized as follows.
All command-line arguments are non-secret contract selectors:

```console
pbpaste | .venv/bin/python -m scripts.sanitize_control_capture \
  --operation set_hybrid_bonding \
  --post-path data/LTE.json \
  --state-field use_bonding \
  --state-value 0 \
  --state-value 1 \
  --readback-path data/LTE.json \
  --readback-field use_bonding \
  --ack-field status \
  --out /private/tmp/speedport-control-contract-sanitized.json
printf '' | pbcopy
```

The output file is created with mode `0600`, refuses symlinks and overwrites,
and contains only:

- HTTP method, relative endpoint, Referer path, and media type
- complete submitted field names, value roles, occurrence counts, and whether
  non-state fields stayed equal across apply and rollback
- exact state codes only from the explicit bounded `--state-value` allowlist
- HTTP status plus a fixed positive acknowledgement value
- the selected baseline, applied, and restored readback state
- fixed proof blockers when acknowledgement, form equality, readback, or
  restoration does not match

It omits the router origin, raw headers and bodies, ciphertext, cookies,
password/proof material, challenges and session keys, CSRF/HTTP tokens, and all
subscriber values. Identifier, address, SSID, name, email, telephone, serial,
and secret field names remain structural evidence, but their values never do.
Review the JSON before sharing it. A complete report is evidence for manual
review only; it never creates or promotes a runtime command automatically.

The sanitizer requires exactly two target POSTs and three fresh, non-cached
GET windows showing baseline, applied, and restored state. Missing login-key
evidence, ambiguous POSTs, missing independent readback, off-origin traffic,
unsafe selectors, oversized input, and malformed encryption fail closed with a
fixed error that does not echo capture content.

Version 1 additionally accepts only `set_*` operations for the reviewed state
fields `use_bonding`, `lan_privacy_policy`, `ex5g_led_mode`, `use_wlan`,
`wlan_guest_active`, `wlan_office_active`, `portuw_active`, and
`mdevice_fix_dhcp`. Selector names for credentials, secrets,
identifiers, addresses, reset, reboot, delete, restore, backup, upload,
firmware, update, import/export, or similar high-risk operations fail before
HAR extraction. Expanding the exact field allowlist requires a separate
security review; changing command-line text cannot bypass it.
