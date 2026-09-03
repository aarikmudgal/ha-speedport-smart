# Internet and network administration evidence

This review used saved firmware JavaScript and sanitized form inventories only.
It sent no router requests or mutations. The v4 form inventory was supplied by
the parent task during the review; it supersedes v3's missing-form conclusions.
The paths below identify local evidence, not redistributable source copies.

Current implementation includes scalar LAN/DHCP/radio/identity/DDNS/schedule,
guest/office settings, Wi-Fi/QoS device selection, DNS/forwarding/blocking/parental
CRUD, VPN lifecycle/credential delivery, powerline rename, tethering/receiver
controls, and existing routing-exception toggles/deletion. The current summary
is [the management matrix](MANAGEMENT_CAPABILITY_MATRIX.md). Later implemented
sections supersede the historical v4 discovery notes below. Offline tests prove
contract behavior, not successful live writes.

The v5 sources are `/private/tmp/speedport-page-contracts-v5.json:47068`
(DDNS), `:83864` (DHCP), `:106244` (schedule), `:120425` (identity/security),
and `:131662` (radio). Shared attachment behavior is resolved by
`/private/tmp/speedport-jquery-addons.js:410`: radio controls disable attached
text fields and hide attached branches. Selects remain serialized by the form
engine. Schedule weekday-use checkboxes are inside `display:none` wrappers and
are not submitted; weekly clock fields are in a radio-parent, not a
check-parent. Resulting schedule payloads have one field when disabled, four
for daily mode, and sixteen for weekly mode. End times may be `24:00`
(`/private/tmp/speedport-jquery-templateforms.js:1363`).

The new custom-DDNS editor separates update hostname and private path/query.
This produces the same post-preaction wire fields while preventing host-only
edits from erasing the saved path. It requires explicit private replacements
when transferring configuration to a new provider or update hostname. It
rejects missing/masked paths and never projects the path or password. Revision
dependencies cover hidden paths, sibling SSIDs, LAN geometry, and preserved LAN
IPv6 fields so those changes invalidate an earlier administrator draft.

## Shared submission contract

- The template engine obtains its POST endpoint from the form's direct child
  `address > span.form-action`, not from `JSONSource` or an HTML `action`
  attribute (`/private/tmp/speedport-jquery-templateforms.js:408`).
- It serializes HTML `name` attributes. Checkboxes become `1`/`0`, only checked
  radios are retained, and text/password fields retain their values. Visibility,
  `.dontsubmit`, default text, disabled text fields, `.alwaysSubmit`, and
  `.keep-suffix` affect the payload (`speedport-jquery-templateforms.js:964`;
  `speedport-jquery-addons.js:1789`). A list of every DOM field is therefore not
  necessarily one valid full POST payload.
- Cloning appends bracket suffixes to original names; nested cloning extends
  the existing suffix before appending another. The inner form strips its own
  terminal suffix. These positions are not router row identities
  (`speedport-jquery-addons.js:989`; `speedport-jquery-templateforms.js:974`).
- `getNormalizedName()` reads `name` and removes the terminal numeric bracket
  suffix unless `.keep-suffix` is present. It does not derive a name from the
  element ID (`speedport-jquery-templateforms.js:1552`).
- `preaction` can change the field map before built-in and custom validation
  (`speedport-jquery-templateforms.js:740`). Flattening creates bracketed wire
  fields; the token is added before encrypted POST (`:816`, `:855`).
- Template success requires exact `getStatus(response, "status") == "ok"`;
  `input_error` and other statuses fail (`:883`). Its `updateStatus` event is not
  an independent persistence check (`:928`). Direct `$.postJSON` callbacks do
  **not** inherit that success test (`speedport-jquery-addons.js:1592`). Generic
  template deletion also lacks an explicit positive ACK check (`:555` in
  `speedport-jquery-templateforms.js`).

## Inventory corrections

The static inventory explicitly calls selector-derived fields candidates, not
proven POST keys (`/private/tmp/speedport-static-management-contracts.json:17`).
V3 contains 49 pages but zero forms and zero form markers. Its page endpoint
lists collect literal endpoint occurrences; they do not retain page alias
assignments (`/private/tmp/speedport_readonly_discover.py:835`, `:1478`, `:1484`).
V3 remains historical evidence, not evidence that the router has no forms.

V4 (`/private/tmp/speedport-page-contracts-v4.json`) captures actual form actions,
field names, types, and numeric option metadata. The associated scripts are in
`/private/tmp/speedport-page-js-v4/`. V4 still omits validators, visibility and
serialization classes, static hidden values, and some nested-form boundaries.
Its `options_incomplete` field describes its separate sanitized form record;
consult `field_metadata` for the numeric enums retained by the newer capture.
The classifier labels forwarding `*_private_*` fields as secrets, although they
are internal port numbers; this is a heuristic, not protocol semantics.

## Historical v4 findings, superseded where implemented below

This section records the initial discovery state. Its earlier requirements for
DHCP labels/disabled fields, schedule visibility, Wi-Fi secret handling, DDNS
branches, device compounds and forwarding/blocking CRUD were subsequently
resolved. Guest/office parsing and tethering aliases were also resolved. Current
unresolved work is limited to the explicit exclusions in the matrix and final
sections, including LAN IPv6 semantics and routing-exception create/full editing.

### LAN IPv4 and ULA

`lan--lan.js:158` constructs an exact eleven-field direct POST to `data/LAN.json`:
`lan_ipv4_1..4`, `lan_mask_2..4`, `lan_ip_v6_used`, `lan_ip_v6`,
`lan_ip_v6_pext`, and `lan_ip_v6_arec`. It explicitly requires `status=ok` at
line 184. It expects a reboot and redirects to the new IPv4 address or retained
`speedport.ip` hostname (`:200`). Mask octets must be contiguous; the router and
the preserved DHCP suffix range must remain usable and nonoverlapping
(`:327`, `:380`). Private IPv4 families are 10, 172.16–31, and 192.168 (`:461`).
V4 LAN markup begins at line 4625 and confirms the form endpoint and IPv4
choices. The direct builder, not the eleven DOM field names, determines the
wire payload: the DOM has separate second-octet inputs and does not expose the
two undocumented IPv6 flags.

The standalone `lan_management.py` implements only IPv4 changes. It preserves
all four IPv6 fields and both DHCP suffixes, never invents a missing value,
rejects a subnet extending outside RFC1918, and compares the whole resulting
state. It has no I/O. Router/firmware capability checks, requester-bound
authorization, preflight freshness, positive ACK, bounded reconnect, new-host
identity verification, cache refresh, and session cleanup belong to the caller.
The current adapter requires manual reconnect; it does not automatically follow
the new address.
ULA input grammar and the semantics of `pext`/`arec` remain unproven; those are
not exposed as setters.

### DHCP

V4 line 4367 resolves the exact form to `data/LAN.json` in the DHCP page context:
`lan_use_dhcp` (`0`/`1`), `lan_dhcp_from`, `lan_dhcp_to`, and
`lan_dhcp_validtime` (`0` through `9`). `optvar_lan_use_dhcp` is the **off** radio,
so `dhcp.js:21` validates the pool when that radio is unchecked. The apparent
inversion in the old selector-only inventory is now resolved. The suffixes use
the router's first three IPv4 octets; validate ordering, subnet membership,
network/broadcast exclusions, and exclusion of the router (`lan--dhcp.js:29`).
Remaining: lease option human labels, exact disabled-branch serialization, and
independent observed state after writes. Do not invent durations for enum IDs.

### Wi-Fi radio and scheduling

V4 `wlan_sendset.html` resolves nine fields to `data/WLANBasic.json`:
`wlan_band` (0/1/2), `wlan_power` (0/1/2), `wlan_mode` (0/2/3),
`wlan_speed` (0/1), `wlan_channel`, `wlan_channel_dir` (0/1/2),
`wlan_5ghz_mode` (0/1/2), `wlan_5ghz_speed` (0/1/2/3), and
`wlan_5ghz_channel`. `lan--wlan_sendset.js:157` sets 2.4 GHz direction to 2 for
auto, 0 for channels 1–4, and 1 for channels 10–13; channels 5–9 permit selection.
Five GHz mode 0 permits only bandwidth IDs 0/1; other modes also permit 2/3
(`:269`). Channel bundles use the first channel in each bundle (`:222`) from
`speedport-global.js:67`; auto is 0. Do not use automatically selected actual
channel fields to verify configured channel values (`:119`).

V4 line 5346 resolves scheduling to `data/WLANBasic.json`: `wlan_timerule`
(0/1/2), daily `wlan_dfrom`/`wlan_dto`, `wlan_fdis`, and seven
`wlan_time_{mo,di,mi,do,fr,sa,so}_{use,from,to}` groups. Weekly overlap checks wrap
Sunday into Monday (`lan--wlan_basic.js:43`). The global `use_wlan` checkbox is
outside the scheduling form; direct radio enable sends only `use_wlan`
(`:14`). Remaining: preserve inactive schedule branches and reproduce visible
field selection; validate time metadata and exact daily/weekly semantics.

### Wi-Fi identity, guest, office, and WPS

V4 `wlan_name_enc.html` resolves exactly eight fields to
`data/WLANBasicAss.json`: `wlan_ssid`, `wlan_visible`, `wlan_5ghz_ssid`,
`wlan_5ghz_visible`, `wlan_enc`, `wlan_pmf`, `wlan_wpa_key`, and
`wlan_display_key`. Visibility is 0/1; encryption options are 0/4/5/6.
`br_active` is outside that form. Encryption 0 hides key controls, 4 exposes PMF,
and 6 exposes WPA3 guidance (`lan--wlan_name_enc.js:227`). Server rejection
reasons include key length/quality and duplicate SSIDs (`:137`). Full secret
replacement/preservation and conditional serialization require dedicated handling.

Guest v4 line 5858 exposes active, lifetime, forced disconnect, SSID, encryption,
PMF, key, key display, WPS, and Internet-access fields. Lifetime IDs are
0, 60, 120, 180, 240, 300, 360, 720, 1080, 1440, 2160, 2880. Office v4 line 6284
exposes active, SSID, encryption, PMF, and key. Both encryption selects use
0/4/5/6. Both inventories currently flag nested form parsing, so row device
metadata must not be merged into the settings save. QR generation from POST
data is not readback (`lan--wlan_guest.js:81`; `lan--wlan_office.js:72`).

WPS v4 line 6702 resolves its start form to `data/WLANAccess.json` with
`wlan_add` and `wps_key`; `use_wps` is outside the form. Hidden values were not
retained by v4. `lan--wlan_wps.js:32` polls `data/WPSStatus.json`: 1 pending,
-1/-2 failure, 0 success. Bound this polling in the integration. PIN support is
not established merely because old JavaScript has PIN validation (`:214`).

### Access control, QoS, DNS exceptions

WLAN access v4 line 5224 resolves `data/WLANAccess.json` and confirms the radio
values and actual checkbox/hidden names. Its explicit lockout-confirmation
payload is `wlan_allow_all` plus paired `mdevice_name[<n>1]` and `sid[<n>1]`
(`lan--wlan_access.js:71`). Here `mdevice_name` is selected membership (0/1),
not a device display name. Match every selected row to an exact firmware SID;
the requesting session SID is explicitly protected at line 43. The native
callback is optimistic; integration verification must not be.

QoS v4 line 5136 resolves a form with `mdevice_name` and `sid` to `data/QOS.json`;
the script limits priority to two selected devices (`lan--qos.js:31`). The
`device_view` POST is only navigation (`:20`). `use_priovoip` is outside the
form and needs its separate binding. DNS exceptions v4 line 4536 resolves
`dns_except` and hidden `id` to `data/DNSExcept.json`, maximum ten rows
(`lan--dns_rebind.js:14`). `use_dnsrebind` is outside that row form.
Remaining for collections: exact clone/row mapping, stable IDs, bounded full
inventory, create versus edit/delete distinction, and fresh exact readback.

### Dynamic DNS

V4 line 1523 resolves `data/DynDNS.json` with eight named form fields:
`use_dyndns`, provider, domain, user, password, update server, protocol, port.
Provider options are 0–4; protocol 0/1 sets port 80/443
(`internet--dyn_dns.js:164`). Provider 4 is custom. Its `preaction` **adds**
`dyndns_updurl` after splitting the input URL into hostname and path/query
(`:84`). A registry built only from DOM field names would omit a real payload
field. Standard and custom domain/user/password inputs share names and alternate
visibility. Delete is a distinct `{delprov:"true"}` direct action (`:298`).
Remaining: explicit branch serialization and secret preserve/replace policy;
fresh configuration or absence verification, not POST response echo.

### VPN and firewall rules

VPN is actually `html/content/network/vpn.html` (v4 line 9813), not the missing
Internet page in v3. Its form endpoint is `data/VPN.json` with `id`, `vpn_name`,
`vpn_password`, `vpn_status`. A row toggle uses those exact ID/status bindings
plus `switchStatus:true` (`lan--vpn.js:478`). Creation reads `newestID` and matches
it against returned row `id` (`:132`); do not use row position. Renewal sends
`renewvpn:"true"` and replaces displayed key material (`:54`). WireGuard versus
IPsec branches exist in the script, but captured markup does not establish an
editable type selector. Key/password/QR outputs require secret-only handling;
the script's `eval` of QR text must never be copied (`:164`).

Forwarding v4 line 2126 resolves `data/PortuwMain.json`: outer `id`, active,
device, name, preset; nested TCP/UDP public-from/public-to/private-destination/
private-to and their `portuwtcp_id`/`portuwudp_id`. Presets are 0–9. Device option
0 is a placeholder, not a target. Maximum 32 rules and 32 ports; script reports
reserved/duplicate port conflicts (`internet--port_forwarding.js:294`). Its
range check accidentally uses `>0 || <65536`; implementation must validate
proper bounded integers, not reproduce that bug (`:119`).

Blocking v4 line 1868 resolves `data/ExtendedRules.json`: row ID, active, name,
TCP/UDP port lists, preset (0–13), and SID-bound selected devices. Maximum 64
rules. Port lists contain comma-separated ports/ranges and require at least one
selected device (`internet--portblocking.js:33`). Exceptions v4 line 9971 resolves
`data/Except.json`, type 0–5 and IP type 0/1, with URL, IP parts/ranges, ports,
ID, and SID-bound device selection. Its type controls which branches are visible
(`internet--except.js:83`). Toggle payloads are `id` plus the normalized active
field, posted to the exact form endpoint (`:104`; forwarding `:472`; blocking
`:183`). Remaining: branch semantics, stable collection identities, hidden
create sentinels, exact nested serialization, and independent CRUD readback.

### USB tethering and mobile receiver

USB v4 line 2450 confirms `use_tethering` is outside a form. Direct activation
is `{activate_teth:"true"}` (`internet--usb_tethering.js:36`); the callback does
not test status. The read endpoint is `data/INetTeth.json`; confirm the actual
page alias assignment before binding the direct action. Hardware checking only
refreshes status; it is not a second mutation (`:32`).

LTE mode v4 line 1799 establishes `use_bonding` as the real checkbox name.
`internet--lte_mode.js:20` posts its normalized name with 0/1; LED writes are
explicit `ex5g_led_mode` 0/1/2 (`:51`). V3 had already resolved their direct
endpoint to `data/LTE.json` at line 177. These callbacks do not require ACK.
Firmware v4 line 1747 and `internet--lte_firmware.js:18` establish
`auto_update:"true"`; reset uses `restore:"0"/"1"` depending on the eSIM checkbox
(`:34`). Both explicitly check `status=ok`. The update UI reads the new firmware
field after `neededTime` (`:104`), but does not compare versions. Reset reads
again without proving factory/eSIM outcome (`:146`). Keep maintenance outcomes
unknown unless an independent exact outcome is observed.

## Implemented Internet form: v5 structure plus v6 validators

`configuration_internet.py` exports `INTERNET_SETTINGS`, containing the typed
`internet_connection` contract. Its only write target is `data/INetIP.json`,
with referer `html/content/internet/connection.html`. The v5 form-action span
establishes this target; no JSONSource-to-write inference is used. The shared
template engine retains the provider select and emits only visible text and
checkbox branches (`speedport-jquery-templateforms.js:1018-1047`). All four
provider options are captured: manual Telekom 0, Zuhause Start 89, Other 1,
automatic Telekom 99. Automatic mode additionally requires character 2 of
`provis_inet` to equal `4` (`internet--isp_option.js:13-27`).

The separately sanitized static validator capture is
`/private/tmp/speedport-static-validators-v6.json:228-428`; it contains field
classes, never field values. Exact constraints are:

- Telekom access number and connection ID: 1-12 numeric characters; four
  co-user inputs: exactly one numeric character each; password: 1-8 characters.
- Zuhause Start user: 1-56 numeric characters; password: 1-32 characters.
- Other provider label/user: 0-255 characters; password: 1-255 characters.
- MTU: 1440-1492; enabled VLAN: 1-4094. These ranges are independently stated
  in the bundled language source (`speedport-lang-en.js:920-924`).
- Fixed IPv4 and primary IPv4 DNS: four required, bounded octets. Secondary
  IPv4 DNS: all empty or all four bounded octets. IPv6 DNS fields: at most
  39 characters, required primary and optional secondary.

Payloads contain the complete active provider branch plus the two global DNS
toggles and their active address fields. Neither DNS toggle is inside an ISP
branch. Other-provider payloads contain 9 fields with all advanced features
disabled, or 24 with VLAN, fixed IPv4 and both DNS families enabled. Manual
Telekom has 10 fields with DNS disabled; Zuhause Start has 5; automatic has 3.
Composite address editor fields expand only to the exact captured octet names.
No arbitrary endpoint, extra form name, or raw JSON payload is accepted.

Provider switches require explicit complete credentials; account changes also
require a replacement password. Newly enabled address/VLAN branches require
explicit relevant values. An unedited optional secondary resolver starts empty
when enabling DNS, matching its empty inactive editor state rather than silently
restoring an undisplayed old resolver. Existing active values are preserved;
masked, missing or redacted credentials never become a password. Current secret
values stay in memory and outside public reads. Revision dependencies include
all preserved wire fields and automatic-provider prerequisites, not uptime or
online status. Canonical unicast IP validation rejects URLs, scopes, multicast,
loopback and unspecified addresses.

Native `connection.js:10-25` calls `changeConnectionOnline` after success **and
failure**. `internet_connection.js:42-46` then posts `req_connect:"online"` to
`data/Connect.json`; its status loop can trigger another save (`:98-101`). The
implementation performs neither automatic connection nor POST replay. It
requires positive settings ACK and uses `reconnect_required` policy; saved
settings are not proof that PPPoE is online. Provider deletion remains a
separate action (`connection.js:41-77`) and is not included in this editor.

Offline tests exercise every provider, exact payload sets, stale dependencies,
masked secrets, branch activation, literal addresses, bounds and inactive input
rejection. They make no router requests. These tests prove builder behavior,
not successful live writes. The current read transport must normalize identical
duplicate scalar records and use the confirmed INetIP token/referer pair.

### DDNS inactive-state correction

Disabled firmware can return an unrecognized/blank provider and omit the custom
update path. Its reader now exposes explicit metadata-valid unconfigured
sentinels: empty provider/transport choice and port 0. These are display values,
never payload defaults. Enabling requires valid selections and explicit new
credentials. Active unknown providers remain rejected. Provider and transport
selects remain serialized even while hidden; custom-provider preaction still
preserves host/path while disabled. A missing inactive custom path does not
prevent reading a standard-provider configuration.

## Implemented selected-device compound editors

Wi-Fi access control and QoS cannot infer checked state from the normalized
`sid` list. The firmware's `parseCompound` matches a compound record's `varvalue`
against an exact hidden SID, then applies its child option to that device's
checkbox (`speedport-jsonvariables.js:439-463`). The private configuration GET
now opts into compound-preserving decoding; the general codec behavior remains
unchanged. Available device labels and SID inventory alone are not proof of
selected membership. The v7 capture confirms each compound child is the exact
`mdevice_name` option with value 0/1; Wi-Fi and QoS typed reads pass against the
real read-only shape. `configuration_device_selection.py` implements both forms.

The closed Wi-Fi form is `data/WLANAccess.json` with referer
`html/content/network/wlan_access.html`. Restricted mode is `wlan_allow_all=1`;
allow-all is 0. For each available row at one-based position `z`, restricted
mode sends `mdevice_name[z1]` (0/1) and `sid[z1]` (exact current SID), with no
device label in the payload (`lan--wlan_access.js:71-82`). At least one device
must be selected (`:21-40`). Excluding `loginedSid` triggers the firmware's
lockout warning (`:43-65`); the integration should reject that outcome. In
allow-all mode, hidden SID fields remain serialized but hidden checkbox fields
do not (`speedport-jquery-templateforms.js:1018-1025`). `selectall` is
`dontsubmit`; outer template position 1 is serialization context, not a device
identity. The implementation requires strict one-to-one compound/SID coverage,
rejects missing flags and duplicate/mixed rows, and prevents administrator
lockout in restricted mode. A shared dynamic checkbox editor exposes current
names with distinct SID labels, never MAC addresses.

QoS uses the same SID/checkbox form pattern at `data/QOS.json`, referer
`html/content/network/qos.html` (v5 page begins at line 100737). Its only form
fields are indexed `mdevice_name` and `sid`; `use_priovoip` is an
`attatch-status` checkbox outside that form. The native maximum is two selected
devices (`lan--qos.js:34-39`, also saved as `speedport-public-qos.js`). A complete
checked-state adapter now preserves every available row, rejects unknown or
duplicate SIDs, and revalidates order and membership before one POST. Private
revision context includes ordered SID, full name and MAC identity; volatile
RSSI, connection and speed telemetry is excluded. MAC identity is also checked
after saving, preventing SID reuse from passing verification. Private identity
context is HMAC-bound, never returned in public settings snapshots.

## Implemented DNS exception CRUD

The exact form is
`data/DNSExcept.json` with `{id, dns_except}` and referer
`html/content/network/dns_rebind.html`; domain text is 1-255 characters
(`/private/tmp/speedport-static-validators-v6.json:1370-1389`). Maximum entries
is 10 (`speedport-global.js:95`). Generic deletion resolves the hidden stable
ID and sends `{id, deleteEntry:"delete"}`
(`speedport-jquery-change-v5.js:105-137`,
`speedport-jquery-templateforms.js:555-567`). The native callback does not test
ACK. The v7 static capture confirms hidden create `id=-1`. The generic JSON
template parser maps `template_adddnsexcept` to `adddnsexcept` rows with the
named hidden ID and `dns_except` field (`speedport-jsonvariables.js:315-350`).
The real empty GET returns only `use_dnsrebind`; missing collection is accepted
only alongside a valid protection flag. Present malformed collections fail.

`configuration_network_rules.py` exports create plus exact-ID edit/delete
contracts. Create sends `{id:"-1", dns_except}`, edit sends `{id,dns_except}`,
delete sends `{id,deleteEntry:"delete"}`. The editor conservatively supports
literal ASCII DNS names, rejects URLs/wildcards/IP addresses and duplicate
domains, and enforces the ten-entry limit. Typed create has a blank draft,
never a fabricated existing target. Verification requires exactly one new ID
with the submitted canonical domain, or the exact existing row edit/removal;
every sibling and the global protection flag must remain unchanged. Positive
ACK is required but never substitutes for this independent readback. No live
writes have been performed or claimed; populated live write outcomes remain
unverified. Tests use synthetic collections and the real one-shot session seam.

## Implemented port-forward and nested-range CRUD

Port forwarding requires a larger nested-row contract. `data/PortuwMain.json`
contains outer stable `id`, name, active flag, selected device SID, preset, plus
TCP/UDP public-start/end, private-start/end and per-range
`portuwtcp_id`/`portuwudp_id`. Name is 1-20 `Pattern.ASCIIwoHtml` characters;
ports are at most five digits (v6 line 586 onward). Public-end determines
private-end by equal range width (`internet--port_forwarding.js:250-265`).
Limits are 32 rules and 32 ranges per protocol; reserved/duplicate ranges are
separately rejected (`:294-329`). V9 confirms the custom preset `-1`, all three
hidden create IDs `-1`, and comma-separated reserved integer/range syntax
(`/private/tmp/speedport-admin-read-shapes-v9.json:550-655`). V10 confirms both
`tcp_private_to` and `udp_private_to` are disabled text inputs, not posted
(`/private/tmp/speedport-admin-read-shapes-v10.json:967-1000`;
`speedport-jquery-templateforms.js:1022`,
`speedport-jquery-addons.js:1789-1792`). Their derived bounds are still validated
and included in normalized readback comparisons.

Nested template parsing is explicit: `parseVarData` finds
`template_<varid>`, clones it, then recursively parses its `varvalue`
(`speedport-jsonvariables.js:315-350`). The HTML names
`template_addportuw`, `template_addtcpportuw`, `template_addudpportuw`, exact
hidden IDs and four visible range fields prove the normalized row structure.
The codec is tested against synthetic nested firmware records. New parent
creation automatically adds one TCP and one UDP input row
(`internet--port_forwarding.js:78-85`), so an unused protocol contributes its
hidden `-1` ID and three blank text fields, not an invented deletion marker.
The shared clone/suffix engine concatenates parent ordinal and child ordinal;
the internal form serializer removes the trailing template suffix
(`speedport-jquery-addons.js:989-1008`,
`speedport-jquery-templateforms.js:971-993`). Exact examples are covered in tests.

`configuration_port_rules.py` provides a new parent rule with one TCP and/or UDP
range, existing parent name/device/active editing that preserves every range,
and exact parent deletion. Additional target-bound forms append ranges or edit
and delete any existing range. A range target is the tuple of parent stable ID,
protocol and range stable ID; list positions only determine serialization.
There is no generic JSON editor, arbitrary path or caller-defined wire key.

Range deletion uses the native full-form blank-row route: prevalidation allows
all three fields of a current range to be empty while requiring at least one
populated range elsewhere (`internet--port_forwarding.js:114-237`). Its existing
range ID remains in the payload. The generic post-success assigned-ID handler
explicitly understands a `deleted` result and removes the matching hidden-ID
row (`speedport-jquery-change-v5.js:278-313`). There is no nested delete control
in this page, so no separate nested `deleteEntry` request is invented. Deleting
the final range requires the explicitly confirmed whole-parent deletion instead.
An ACK or `deleted` echo is never sufficient: fresh readback must show exactly
the selected range absent, every sibling unchanged, and the parent intact.

All operations reject duplicate/missing IDs, invalid ports, reversed or
overflowing ranges, reserved-port intersections and overlapping public ranges
within the same protocol. Choices bind the current SID/name/MAC identity;
private revisions exclude RSSI and speed telemetry. New range verification
requires exactly one newly assigned range ID; new rule verification requires
exactly one newly assigned parent ID and exact complete range values. No write
is retried after failure or ambiguous persistence.

Current evidence limitations remain explicit: the actual router has no current
forwarding rules, so populated live GET shapes and successful writes have not
been observed. Unknown current shapes fail closed. Existing full-form editing
also requires a current recognized `portuw_template`; an omitted preset is not
silently invented. Preset shortcuts are not exposed, but explicit numeric
ranges support their functionality. Offline tests prove contracts and strict
readback, not successful live mutation.

## Implemented port-blocking and parental profile CRUD

`configuration_port_blocking.py` binds `data/ExtendedRules.json` to the native
`internet/portblocking.html` form. It creates and edits the complete fixed name,
active flag, TCP/UDP port lists, hidden preset selector, and exact device
selection; deletion uses the current stable ID and `deleteEntry=delete`.
The native script requires a nonempty TCP or UDP list and at least one device
(`internet--portblocking.js:33-104`). Names are 1-20 ASCII-without-HTML characters,
and port lists have a 255-character limit (v6 validators, lines 541-574). The
all-ports preset explicitly uses `0-65535`; port zero is therefore accepted for
blocking lists, unlike forwarding ranges. The editor rejects malformed,
reversed or overlapping comma-separated ranges. V12 lines 912-995 prove preset
options 0-13 with no selected option, making the first option, custom 0, the
native default when no JSON value exists. A present recognized preset is
preserved. No preset shortcuts or unrelated payload fields are exposed.

`configuration_parental.py` binds `data/TimeRules.json` to
`internet/chd_timerules.html`. The v12 GET shape proves the current `addtime`
singleton, all scalar schedule fields, and exact SID/checked-state compounds
(lines 704-900). V12 also proves both form create IDs are -1 and the parental
`show_day` values 0, mo, di, mi, do, fr, sa, so (lines 1001-1048). The full parental
form always submits six time fields and one budget for each of the daily and
seven weekday groups: 56 schedule fields plus ID, name, active, shared-budget
flag and `show_day`, then two fields per available device. All schedule inputs
are `alwaysSubmit` (v6 lines 2651-3036); inactive values cannot be silently
omitted. Daily/weekly mode is a typed editor choice that derives the exact
native selector and clears the other mode's fields. Unchanged dormant values
are otherwise preserved.

Native validation requires complete ordered pairs, 00:00 through 24:00 bounds,
no overlapping or touching windows, at least one populated active day, and
budgets from 1 to 1440 minutes (`internet--chd_timerules.js:340-552,671-737`). The
public integer zero explicitly means the native empty budget string, not a
zero-minute wire budget. Entering a budget into a day without windows creates
00:00-24:00, exactly matching the native blur handler (`:293-315`); explicit
expected-value callbacks include this derived change in independent readback.
The shared-budget flag means one aggregate budget across assigned devices,
otherwise each device receives its own budget (`speedport-lang-en.js:1016-1018`).

`configuration_rule_devices.py` validates the complete available inventory and
one exact SID/0-or-1 compound per device. Device labels are disambiguated by SID;
MACs remain private revision and readback identity evidence. These global device
templates clone before the parent rule, producing device-first then parent
ordinal suffixes, unlike the forwarding page's nested range rows
(`internet--chd_timerules.js:827-832`, shared template suffix engine cited above).
Parent ordinals serialize the form but never identify the mutation target.
Every profile assignment is exclusive, including disabled profiles, matching
the native checkbox disabling behavior (`:35-56,559-606`). Limits are 32 parental
profiles, 64 blocking rules and 253 inventory devices
(`speedport-global.js:79-97`). The script mentions `maxTimeRulesHost` but that
property is absent from the captured complete global configuration; no smaller
per-profile limit is invented.

Both families use requester-bound one-shot confirmation, exact full payload
validation, positive ACK and independent whole-family readback. Every sibling
and physical device identity must remain unchanged. Revisions preserve stable
assignment context and exclude changing RSSI, traffic or speed telemetry. The
native direct active toggles are covered through the typed full edit forms.
Disabling a parental rule removes its schedule restriction; it is not an
Internet pause operation. No supported per-device pause/resume endpoint was
found, so no such action is fabricated. The live blocking collection is empty;
populated blocking records and all successful mutations remain unverified.
Tests are synthetic and make no router requests or live writes.

The later v19 read-only check successfully validated the existing parental
profile and all 61 public fields. The actual 36-device inventory uses complete
hyphen-delimited MAC addresses; canonical colon and hyphen spellings are now
accepted and normalized to one lowercase colon identity. Mixed separators,
missing values and malformed octets still fail closed. This normalization is
also applied to Wi-Fi/QoS and forwarding inventories, with regression tests
showing that spelling alone cannot stale a draft or hide a changed physical MAC.
V20 validated the empty blocking-rule and parental-create readers; v21 validated
the Wi-Fi access, QoS device selection and forwarding-create readers after this
same MAC normalization. These were authenticated GET-only checks performed by
the main task, with its own session closed afterward. They prove readable
current contracts, not mutation success. No further live checks were performed.

## VPN controls, creation and IPsec key rotation

`configuration_vpn.py` implements exact existing-peer enable/disable and deletion
against `data/VPN.json`, with the actual `network/vpn.html` referer. Native toggle
code posts only stable `id`, boolean `switchStatus=true`, and numeric
`vpn_status=0|1` (`lan--vpn.js:466-481`). Deletion uses the shared exact-ID form.
The peer limit is five (`speedport-global.js:93`), and names have the native
1-20 ASCII-without-HTML validator (v6 lines 3091-3094). Current mode must be the
observed WireGuard 0 or the script's explicit IPsec 1. No mode-change request is
invented: the actual HTML has no mode input despite dormant generic JavaScript.

Private revisions and whole-collection readback retain peer IDs, names, enabled
flags, observed credentials and the global key. Connected user IPs and other
telemetry are excluded; credentials are never exposed in public typed reads,
target labels or metadata. Every non-target peer and known credential must be
unchanged. These are one-shot, positively acknowledged mutations, with no POST
retry on ambiguous outcomes. V15 lines 1045-1053 prove current mode 0 and an empty
peer collection, not a successful live mutation.

Creation requires a separate secret-delivery path. Native `newestID` identifies
the newly created row (`lan--vpn.js:137-157`), and WireGuard `vpn_qrcode` is returned
in the creation response (`:169-183`), then exported as `Wireguard.conf`
(`:245-257`). The native JavaScript uses `eval`; that behavior must not be copied.
Returned configuration must remain inert data, bound to the exact newly
persisted row and delivered only to the requesting administrator without logs,
persistent storage or broad cache publication. A save that drops this one-time
result is not a complete creation workflow. IPsec's explicit password branch
requires 12-32 allowed characters and at least three of four character classes
(`:85-108,386-458`; exact `Pattern.CharsForPwd` is in
`speedport-jquery-templateforms.js:1501`). Global `renewvpn=true` is shown only for
IPsec (`lan--vpn.js:48-60,117,211-217`), so it must not be offered in WireGuard
mode. The actual form contains no VPN configuration import; no import request
or existing WireGuard credential recovery is claimed.

The implemented create contract posts the exact hidden `id=-1`, `vpn_name`, and
checked-default `vpn_status=1` proven by v16. The IPsec password is included only
when the router already reports mode 1; the hidden inactive WireGuard password
is omitted. Fresh global connectivity is supplied in the private
`vpn_connectivity` namespace and checked using the native online/external-modem
predicate. Tethering-only connectivity does not enable creation. At most five
peers may exist; every old peer and credential must survive unchanged, and
readback must add exactly one enabled peer with the approved name and IPsec
password when applicable. The global key can be initialized only for a previously
empty peer collection with an empty key.

`extract_vpn_credentials` releases a `repr=False` credential result only after
that full readback and exact response `newestID` binding. WireGuard newline
escapes are decoded as JSON string data, never evaluated. The download parser
accepts only the expected Interface/Peer configuration fields and rejects
unknown sections, duplicate fields and executable wg-quick hooks. IPsec export
is explicitly a JSON credential document, not an invented import format.

The mode-1-only rotation contract posts precisely `renewvpn=true`. It requires
existing peers and a readable, non-masked key. Independent readback must prove a
different non-masked global key while preserving every peer ID, name, enabled
flag and login credential; only derived IPsec QR strings may change.
`extract_vpn_rotated_credentials` additionally matches the response key to that
fresh state before returning the new key and at most five peer credentials.
The shared verified-result callback runs only after readback, so response data
can remain local across GET retries without repeating the mutation. Tests cover
successful one-time delivery, stale/newest-ID mismatches, missing credentials,
script-shaped strings, failed persistence and lost-response non-retry behavior.
No successful VPN mutation has been live tested or claimed.

## Powerline rename

`configuration_powerline.py` reads the complete private `addpwlinedevice`
collection from `data/DeviceList.json`, with `network/devices.html` as referer,
then posts only the native rename form to `data/PWLineDevice.json`. The actual
DOM binds that action at v5 line 73051 and includes hidden `pwline_downspeed`,
`pwline_upspeed`, `id` and `pwline_mac`, followed by `pwline_name`
(v5 lines 73232-73343). The existing-device hidden ID has explicit static value
0, retained only when JSON does not replace it. Names use 1-28 characters from
the exact letters/digits/hyphen grammar (v6 lines 799-801;
`speedport-jquery-templateforms.js:1497`).

The target is the exact canonical physical MAC, so repeated default ID-zero
rows cannot select the wrong adapter. The fresh native ID and original MAC
spelling are preserved in the payload. Both speed values come from the fresh
pre-write read and are serialized without appearing in revision fingerprints.
The script treats these as changing link-rate display values
(`devices.js:1325-1346`), not editable settings. Revision and independent readback
compare every device's stable ID, MAC and name, rejecting sibling renames,
missing targets or physical replacement while allowing telemetry changes.
The inventory has a defensive complete-read bound of 253; this is not a claimed
powerline-specific firmware capacity. No identify, pairing or removal request
is exposed because this bound form proves only rename. Tests use synthetic
inventory and the real requester-bound one-shot session; no powerline mutation
was tested live.

## Remaining native Internet controls and explicit exclusions

`configuration_network_controls.py` adds five exact bindings. USB tethering
enable is not posted to the page JSON source: the actual checkbox has
`attatch-status` (v5 line 65529), bound by the addon at line 298 to
`appendStatusForm`, which posts the normalized one-field `use_tethering=0|1` to
`JSON_Modules` (`speedport-jquery-templateforms.js:1566-1583`). The global resolves
that endpoint to `data/Modules.json` (`speedport-global.js:173`). Its read source
is `data/INetTeth.json`. The separate forced-switch button posts exactly
`activate_teth=true` to that read source
(`internet--usb_tethering.js:35-41`). Both actions require usable USB and reject
the native external-5G/hybrid exclusions (`:3-25`); activation additionally needs
enabled tethering and a detected device. The page's check-again/rescan button
only invokes a GET refresh (`:31-33,64`); no rescan mutation is invented. No
editable automatic failover timeout is present: `neededTime` is a returned
countdown, not an input.

Forced switching uses a fresh action confirmation, not an inferred active-route
checkbox. `tethering_status=2` does not prove the current Internet path: native
rendering checks DSL and external-modem routes first (`:75-104`). A connected
USB device therefore does not suppress the explicitly requested action as an
already-active no-op.

The receiver page directly posts `use_bonding=0|1` and `ex5g_led_mode=0|1|2` to
`data/LTE.json` (`internet--lte_mode.js:20-70`; v5 page `JSONSource`). Bonding is
shown only when `easy_support_deactive=1` (`:4-9`); this prerequisite is enforced,
not silently changed. LED options are use LEDs, switch off after timeout, and
do not use LEDs (`speedport-lang-en.js:215-219`). Both controls bind the observed
receiver serial/model privately. These direct callbacks do not inspect a
positive ACK, so all five controls use the `readback` acknowledgement policy.
Link-changing tethering/bonding actions return `outcome_unknown` with
`verification=reconnect_required`, never a claim of verified Internet
connectivity. LED changes require exact readback against the same receiver.
Missing physical hardware or prerequisite state fails closed. Supplemental
fixed context can be merged by the private reader in `network_prerequisites`;
changing counters are excluded from authorization fingerprints. Native
`getVar` searches only the current JSON result (`speedport-jsonvariables.js:149`):
the tethering page expects `use_usb`, `use_lte`, `auto_external_modem`,
`extwan_typ`, and `hybrid_tunnel` from `data/INetTeth.json` itself. Missing
prerequisites are not inferred from other mode flags. For receiver bonding,
the v15 `LTE.json` shape omits `easy_support_deactive`; the private reader can
obtain only this fixed prerequisite from `data/EasySupport.json`, with referer
`html/content/config/easy_support.html`, and place it in the namespace above.
No extra GET is needed by the receiver LED or DDNS deletion contracts.

Dynamic DNS deletion has a real native confirmation handler posting only
`delprov=true` to `data/DynDNS.json` (`internet--dyn_dns.js:292-333`). Verification
requires DDNS disabled, domain/user/password/update host empty, and no retained
custom update path. Merely disabling DDNS is not deletion proof. Provider and
transport selector defaults can remain after credential removal; they are not
claimed to be erased. No dedicated force-update/refresh POST exists in the
captured page or companion. Existing DDNS configuration remains handled by its
full reviewed editor.

`configuration_routing_exceptions.py` reads `data/INetExcept.json` and binds the
actual `Except.json` internal form. Existing enable/disable posts exactly the
stable `id` and numeric `except_status=0|1`
(`internet--except.js:107-130`); exact deletion uses the shared generic ID route.
Neither direct callback proves a positive ACK, so both actions require exact
independent readback before success is reported.
Private revisions/readback retain all known current routing fields, checked
device compounds and stable physical device identities, with complete sibling
preservation. The six native types are LAN devices, domain, IP address, IPv4
range, fixed target port and marked DiffServ traffic
(`speedport-lang-en.js:947-952`), with a 64-rule limit
(`speedport-global.js:77`). These existing-record controls do not manufacture a
full create/edit payload. That form has conditional branches, hidden device
SIDs, a hidden negative create ID whose literal was not preserved by the v5
sanitizer, and range-to inputs 1-3 whose disabled/read-only attributes were not
retained in v5/v6. Their exact submitted key set needs additional static
evidence before full-form editing or creation. The IPv6 branch exposes four
hextets, not an arbitrary full-address field; its semantics are not guessed.

The captured actual HTML pages and their JavaScript companions contain no
UPnP-IGD editor, mapping mutation or complete mapping identity schema. Generic
UPnP standards and UPnP-AV media sharing do not prove such a router-specific
write contract. These controls remain unavailable. Likewise LAN IPv6 routing
semantics, a VPN mode-change/import request, and per-device Internet pause are
not inferred from generic labels or unrelated status fields. This tranche used
saved static evidence and offline tests only; no additional live router calls
were made after the main task closed the v21 read-only session.

## Separate voice-priority and DNS-protection flags

`configuration_small_controls.py` now includes `qos_voice_priority` and
`dns_rebind_protection`. Their inputs are not fields in the device/exception
collection forms: the actual `use_priovoip` and `use_dnsrebind` checkboxes have
the `attatch-status` class (v5 lines 102182-102185 and 88329-88332). The addon
binding at `speedport-jquery-addons-root-v14.js:298` invokes
`speedport-jquery-templateforms.js:1566-1583`, whose exact POST is the one
normalized flag string `0` or `1` to `JSON_Modules`. The latter resolves to
`data/Modules.json` (`speedport-global.js:173`). No positive ACK is checked by
that callback, so both contracts use independent readback, not HTTP success.

Fresh state comes from `data/QOS.json` with
`html/content/network/qos.html`, or `data/DNSExcept.json` with
`html/content/network/dns_rebind.html`. Voice-priority changes bind the existing
complete checked SID compounds and stable device identities. DNS-protection
changes bind the complete canonical exception-ID/domain collection. Both
require unchanged preserved context after the exact flag change. Counter/IP
telemetry does not invalidate the private revision. Disabling protection has
an explicit security warning; adding a specific exception remains separate.

The same small-control module includes two independently bound native actions:

- Learned-number clear posts only `speeddial_delete=true` (string) to
  `data/PhoneLineset.json`, with `phone/phone_linespeeddial.html` referer.
  `phone--phone_linespeeddial.js:2-8` binds the actual button and does not inspect
  an ACK. Current `use_speeddial` binds the draft, but no learned-list, count or
  generation is returned. The typed destructive confirmation authorizes one
  POST only; the result always remains `outcome_unknown/manual_required`.
  This does not delete or claim to verify phonebook contents.
- System-message filter posts to `data/SystemMessages.json`, with
  `config/system_log.html` referer. `settings--system_log.js:40-67,97-100`
  builds `search=true` plus selected `search1..7` values in the fixed order
  `inet,tel,wifi,sys,shom,esup,sec`. Clearing all editor selections explicitly
  disables filtering via the native `search=false` request at lines 34-42.
  Lines 146-167 decode `filter_log` as the seven-bit category mask; zero is
  unfiltered. The editor accepts only these seven names and verifies the exact
  mask through a separate GET. It exposes no log message contents, does not
  clear messages, and does not substitute for the private Syslog download or
  an in-panel raw-message viewer. Native callbacks do not prove an ACK.

All four controls are registered and linked in the panel. Synthetic tests
cover exact payloads, every valid filter bitmask, malformed/missing state,
preserved context, requester/confirmation/staleness checks, independent
readback, and the no-replay/manual-outcome clear behavior. No live mutation or
additional router request was made for these controls.
