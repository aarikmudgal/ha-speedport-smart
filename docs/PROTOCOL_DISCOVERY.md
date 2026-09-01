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
