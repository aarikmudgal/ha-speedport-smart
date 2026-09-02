# Read-surface registry

`custom_components/speedport_smart/read_surfaces.py` is the declarative audit
boundary for data published from the normalized router snapshot. It does not
fetch data, create entities, or authorize router changes.

## Ownership model

Each normalized path has exactly one `ReadSurfaceContract`. That contract owns
the path's value kind, effective polling cadence, and privacy classification.
The same value may intentionally appear in more than one Home Assistant place,
so its owner contains one or more `ReadPublicationContract` records. A path
used only as a derivation input has the same first-class kind, cadence, and
privacy contract with no direct publication.

Publication surfaces currently cover:

- fixed native sensors and binary sensors;
- child-device sensors and binary sensors;
- client device trackers, including bounded tracker attributes;
- entity attributes;
- router and child `DeviceInfo` metadata;
- firmware update metadata;
- Administrator dashboard collection and record mirrors;
- private values and explicit raw-value exclusions.

`READ_SURFACES` indexes canonical paths. `DERIVED_READ_SURFACES` indexes every
path referenced by lineage, including source-only owners. `READ_PUBLICATIONS`
separately indexes each `(surface, publication_id)` and points it back to its
canonical owner. A duplicate publication identity therefore fails during
module construction, while a deliberate mirror remains visible and testable.

## Derived publications

`derived_from` records ordered alternate inputs used by one publication. Each
input owns its own source contract but gains no publication merely by being an
input. Examples include the client tracker falling back from `connected` to
`active`, receiver child entities falling back from `receiver.items[]` to the
singleton `receiver` record, and `DeviceInfo` choosing the first available
stable identifier.

A source-only path must be listed in `_REVIEWED_SOURCE_ONLY_METADATA` with an
explicit value kind, cadence, and privacy class. The builder never infers these
properties from the consuming publication. Both an unknown input and a stale
source-only classification fail registry construction.

The canonical path must not appear in its own `derived_from` list, and fallback
paths must be unique. Transformations such as converting an exception to its
class name or a progress number to a boolean are still owned by the original
canonical value; `output_kind` records the changed publication shape without
creating a second normalized owner. Cyclic or unclassified lineage fails while
the registry is built.

## Privacy boundary

Privacy is classified on the canonical owner. When publication declarations or
derivation inputs have different classifications, the registry folds the most
restrictive classification into the output owner. Effective cadence likewise
cannot claim to refresh faster than its slowest input. Personal, secret, and
internal paths cannot become native scalar entities. Private and excluded
publications document that a raw value is not directly emitted; an excluded raw
identifier may still have a separately declared derived `DeviceInfo` use.

No credential value, raw authentication response, or unrestricted router
payload belongs in this registry or in Home Assistant state.

The administrator-only IP-PBX refresh and phonebook search/contact queries are
intentionally outside `READ_SURFACES`: they are not normalized-snapshot
publications. Their fixed WebSocket commands return short-lived, independently
allowlisted projections only to the requesting administrator panel. Results
never enter coordinator data, entities, Recorder, diagnostics, URLs, browser
storage, or logs, and the panel clears them on context change or disconnect.
Exact discovered query-family capability plus a healthy protected session is
required before either the frontend or backend can issue a router request.

The administrator-only `system.domain_name` publication is an explicit example
of a raw technical mirror: it is bounded text from the already-polled public
Status source, classified as local-network data, and deliberately has no
semantic native entity or control.

`internet.failure_reason` follows the same source boundary but is stricter: the
firmware UI proves only the exact codes `user`, `net`, `dsl`, and `router`.
Only those values enter the cached administrator view; arbitrary failure text
is rejected rather than exposed or interpreted as a diagnosis.

## Conformance

`tests/test_read_surfaces.py` derives expected fixed native, child-device, and
Administrator publications from their runtime descriptor catalogs. It also
checks tracker fallbacks, entity-attribute ownership, `DeviceInfo`, update
metadata, intentional mirrors, publication identity uniqueness, value kinds,
privacy rules, complete source classification, acyclic lineage, effective
cadence, and current frontend feature references.

When a new normalized read is published, update its runtime descriptor or
allowlist and its registry declaration in the same change. When an existing
publication gains a fallback input, add that normalized path to `derived_from`
and give the input a truthful source classification. The registry will reject a
missing source or a lineage path that weakens privacy.
