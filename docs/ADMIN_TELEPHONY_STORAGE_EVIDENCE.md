# Telephony and storage write-contract evidence

This is a static review of the locally saved Smart 4R Type A firmware UI
scripts and subsequent sanitized v4/v5 page-contract captures.
This reviewer performed no router request, configuration change, or destructive
action. Source line references below use the saved files in `/private/tmp`.
An explicit browser request proves the intended payload, not that a write has
been accepted or persisted on this router.

## Shared form and transport contract

`speedport-jquery-templateforms.js:410-412` obtains the **write URL from the
form's own `address > span.form-action`**, not from `JSONSource`.
`speedport-jsonvariables.js:6-42` uses `JSONSource` for the initial read only.
Consequently, observing a page's read URL does not resolve its write URL.

The form engine collects `input`, `select`, and `textarea` fields
(`templateforms:487`), removes `:dontSubmit` and `:disabledTextfield`, and keeps
visible fields, hidden inputs, selects, and `.alwaysSubmit` fields
(`templateforms:1018-1025`). Checkboxes become numeric `1`/`0`; only selected
radio values are sent (`templateforms:1044-1058`). Cloned row forms strip the
last numeric name suffix unless `keep-suffix` is present
(`templateforms:964-988`; `jsonvariables:615-631`). Nested values are flattened
back to bracketed names before transmission (`templateforms:809-835`).

`preaction` and `prevalidate` can modify the payload after collection
(`templateforms:745-755`). `postbeforestatuscheck` can veto success. The generic
ACK requires decrypted `status == "ok"`; `assignedID` is independently exposed
for newly created records (`templateforms:869-891`). This does not perform an
independent readback.

Normal `$.postJSON` requests inject the current `httoken`, AES-CCM-encrypt the
payload, and decrypt the response (`speedport-jquery-addons.js:1592-1601`;
`speedport-global.js:143-145`). Uploads described below use a different transport.

## Newly resolved explicit requests

### NAS share create/edit/disable

`speedport-public-nas_share.js:125-155` supplies the complete object directly;
this path does **not** depend on missing form HTML:

| Condition | POST `data/NASFolder.json` fields |
|---|---|
| Always | `sid` from current hidden share identity; `nas_active`: `0` or `1` |
| Active | `nas_folder_name`; `nas_folder_nur_lesen`: `0`/`1`; `nas_secure`: `0`/`1` |
| Active and secure | `nas_user_name`; `nas_user_pwd` |

Do not send omitted conditional fields as empty strings: disabling deliberately
sends only `sid` and `nas_active`. A new empty share uses `sid == -1` after the
UI's delete/reset path (`nas_share:112`); creation with that sentinel still
requires user validation before treating it as confirmed on-device.

Validation: an active share needs a nonempty folder unless `printer_connected`
is nonzero (`nas_share:131-135`). Credentials are required when secure, using
the field's HTML `minlength`. The username uses
`^[0-9a-zA-Z\-\.]*$`; password uses
`^[0-9a-zA-Z\!\"\u00A7\$\%\&\/\(\)\=\*\+\#\,\;\.\:\-\_]*$`
(`templateforms:1499-1501`; `nas_share:170-213`). The v4/v5 NAS form confirms
the endpoint and seven fields. Firmware English validation messages separately
prove username length 6-32 and password length 8-32
(`speedport-lang-en.js:1433-1434`). No path length or safe directory-selection
contract is inferred. The existing-share editor preserves the current path.

The callback merely updates the UI; it does not inspect ACK status
(`nas_share:148-154`). Integration verification must independently read
`data/NASFolder.json` and compare exact `sid` and non-secret requested fields.
Never claim to verify a masked password by comparing the mask. No live returned
schema containing a share was reviewed in this pass; secret persistence and
empty-share creation remain user-test requirements.

### IP-PBX client allocation

`speedport-public-phone_ippbx.js:86-109` resolves a new action:

```text
POST data/IPClients.json
add_ipcl = "add ip phone"
```

The response contains `newestID` and `addipclient` records; the UI selects the
record whose hidden `id` equals `newestID`. Capacity comes from
`routerConfig.hardware.maxIPPBX` (`phone_ippbx:93`). The callback does not inspect
generic ACK status. A safe implementation needs a fresh before/after roster,
exact new identity matching, and no automatic replay after an uncertain write.

The existing refresh request is explicit:
`POST data/IPClients.json {refresh: id}` (`phone_ippbx:14-33`). It yields matching
`addipclient` record fields including `ipclient_status`, and when connected,
`ipclient_mdevice_name`, `ipclient_mdevice_ipv4`, `ipclient_mdevice_mac`
(`phone_ippbx:34-58`). Refresh is not an independent source if used only from the
allocation response: issue a separate request.

This allocation action **does not prove the entire PBX account editor**.
The v4 form now separately proves its `data/IPPBX.json` action and nine fields
(see below). Password rules visible in JS require at least
two character classes (digits/lower/upper/allowed punctuation), and
`Pattern.CharsForIPPBXPwd`; length/validation-class metadata still needs review
(`phone_ippbx:233-261,267-305`; `templateforms:1509`).

### Phonebook import

`speedport-public-phone_book.js:363-441,632-636` resolves both endpoint and the
computed multipart field:

```text
POST data/PhoneBookImport.json
Content-Type: multipart/form-data (browser-generated boundary)
file field: importfile-{book_index}
maximum file size: 2,097,152 bytes
```

`book_index` is the selected phonebook identifier, subtracting 100 for online
books. However, online books disable edit/import in the UI
(`phone_book:481-517`), so that arithmetic is not authorization to import into
an online book.

This upload uses raw `FormData`, not `$.postJSON`: no explicit `httoken` or
request encryption is added by this handler. The HTTP-200 response is decrypted
before parsing. Numeric ACK `status`: `0` success; `1` missing/false file;
`2` invalid format; `3` no space; `4` wrong columns; `5` wrong title;
`6` wrong column content; `7` wrong content; `8` other
(`phone_book:7-15,382-437`). Success also exposes `totalNum`, `ignoreNum`,
`fullNum`. The UI independently refreshes the list on status `0`.

Readback is `POST data/PhoneBook.json {search: "", obnr: book_index}`
(`phone_book:477-521`). The file's exact CSV column order/headers, encoding,
overwrite/deduplication semantics, and multipart session handling are not proved
by this JavaScript. Do not present import as verified until these are captured
and user-tested. An HTTP 200 or partial-import count is not full persistence.

### Create storage directory

`speedport-public-nas_folder.js:203-240` directly sends:

```text
POST data/NewDirectoryEntry.json
entry = selected_parent_path + "/" + new_name
```

The picker does not allow creating directly beneath a level-one disk/root
(`nas_folder:27-43`). Empty new names cancel creation. The callback treats any
status other than `"fail"` as success, which is weaker than the integration
should accept. Independent listing uses `data/DiskDirectoryEntry.json` with
`entry: parent_path`; the root starts with `{entry: "/", mc: "1"}`
(`nas_folder:7,100-104,126-134`). Returned Dynatree nodes expose names through
`node.data.title`, and directory selection reconstructs the path from parents.

The name validator and exact successful ACK/schema are missing. A write should
remain gated until exact parent selection, path traversal rejection, successful
ACK, and independent child existence can be established. This is directory
creation, **not NAS share creation or media-server configuration**.

## Newly resolved companion-page contracts (v4)

The earlier v3 inventory had no retained forms. **The v4 capture supersedes that
blocker**: the actual endpoints and form field sets below are now known.
References are page keys inside `speedport-page-contracts-v4.json`; new scripts
are under `speedport-page-js-v4/`.

| Page / capability | Proven write endpoint and fields | Values / independent read source |
|---|---|---|
| `phone_dect_settings.html` | `data/DECTSettings.json`: `dect_eco`, `dect_halb`, `dect_pin` | Both radios have literal values `0`,`1`. Read `DECTStation.json`; preserve unedited PIN privately, never forward a mask. Repeater presence changes power availability. |
| `phone_dect_mobiles.html` | `data/DECTStation.json`: `dect_cws`, `dect_mobile_name`, `id`, `plug_outgoing`, `ring_incoming`, `selectall_deselectnone`, `sid` | Exact handset row identity and dynamic phone-number options; independent `DECTStation.json` detailed row read. |
| `phone_analog.html` | `data/PhonePlugs.json`: `id`, `plug_name`, `plug_outgoing`, `plug_type`, `plug_use_out_of_order_signaling`, `ring_incoming`, `selectall_deselectnone`, `sid` | `plug_type`: `0`,`1`,`2`,`3`; default outgoing `0` plus dynamic number IDs. Detailed `PhonePlugs.json` read. |
| `phone_ippbx.html` | `data/IPPBX.json`: `id`, `ipclient_name`, `ipclient_password`, `ipclient_status`, `plug_outgoing`, `ring_incoming`, `selectall_deselectnone`, `sid` | Preserve read-only status and exact identity; dynamically bound assignment options. Password classes above; independent GET of IPPBX data. The separate IPClients refresh POST is not used as a readback. |
| `phone_lineset.html` | `data/PhoneLineset.json`: `clir`, `id`, `line`, `reject_on_busy` | `line`: `0`,`1`; checkboxes `0`,`1`; preserve target line identity. |
| `phone_linevosip.html` | `data/Phone.json`: `phone_vosip_policy` | Literal radio values `0`,`1`,`2`. |
| `phone_linehdvoice.html` | `data/Phone.json`: `hdvoice` | Checkbox `0`,`1`. |
| `phone_linedialdelay.html` | `data/Phone.json`: `dialdelay` | Literal options `0`,`1`,`2`,`3`. |
| `phone_linestataudio.html` | `data/Phone.json`: `stataudio` | Checkbox `0`,`1`. |
| `phone_linespeeddial.html` | `data/PhoneLineset.json`: `speeddial_delete:"true"` | `phone--phone_linespeeddial.js:5` uses `JSONSource`, now resolved by the page. This is clear/reset, not arbitrary per-entry speed-dial editing. |
| `phone_book_entries.html` / `phone_book_basic.html` | `data/PhoneBookEntry.json`: `adresse`, `geburtstag`, `id`, `name`, `number_a`, `number_m`, `number_n`, `number_p`, `obnr`, `ort`, `plz`, `vorname` | New `id=-1`; selected `obnr`; name-or-first-name and at least one phone number; space removal; valid optional `dd.mm.yyyy` birthday. Read back with `{obnr,chgid}` at same endpoint. |
| `phone_book_basic.html` | `data/DECTSettings.json`: `phonebook_int` | Internal-book configuration; capture static option semantics/validation before exposing. |
| `phone_book_basic.html` online account | `data/PhoneOnlbuch.json`: `id`, `onlbuch_bname`, `onlbuch_domain`, `onlbuch_name`, `onlbuch_pwd` | Registration is multi-step; generic form success alone does not complete contact merging. See `phone--phone_onlbuch.js:246-349`. |
| `phone_book_basic.html` existing online book | `data/PhoneOnlbuch.json`: `id`, `onlbuch_bname`, `onlbuch_name`, `onlbuch_nr` | Separate form from account registration; do not merge their schemas. |
| `nas_workgroup.html` | `data/NASWorkgroup.json`: `smb_workgroup` | Independent same-endpoint read; exact text validator still needs metadata. |
| `nas_mediareplay.html` | `data/NASMediaReplay.json`: `id`, `mediareplay_active`, `mediareplay_folder`, `mediareplay_name`, `mediareplay_status` | Active checkbox `0`,`1`; preserve status/identity; unique nonempty names and folder paths across rows (`lan--nas_mediareplay.js:108-173`). |
| `nas_overview.html` safe removal | `data/OtherDevice.json`: `{deleteEntry:"delete",serial,id}` | The actual dynamic action is now resolved. ACK exact `status=="ok"`; independently refresh `NASDevice.json` and match both device ID and serial before removal. |

### Number-assignment dynamic payloads

`phone_number.html` provides two `data/PhoneNumberAssignment.json` forms, but
their initial `option_inc` / `option_out` names are **placeholders**, not wire
field names. `phone--phone_number.js` resolves them:

- `incoming[plug_id][number_id] = 0|1` (`:321-340`). IDs derive from fresh
  `addglobalplug` and `addphonenumber` records (`:5-44,63-78`). Master `checkall`
  controls are explicitly excluded from submission (`:55-56`).
- `outgoing[plug_id] = number_id` (`:177-183,347-360`); `0` means automatic.
- `plug_alternative_number[plug_id] = number_id` (`:19,95`), preserved for every
  plug. When the outgoing type is `IP`, a different backup number must be
  selected in the follow-up dialog (`:108-173`). Do not drop untouched columns
  or assume list indices equal router IDs.

### Phonebook-to-handset dynamic payload

`phone_book_assign.html` initially declares `option` in its
`data/DECTSettings.json` form. `phone--phone_assign_onlbuch.js:58-65` rewrites it
to `dect_onlbuch_{handset_id} = onlbuch_nr`. The handset IDs come from
`DECTMobiles.json` / `adddectmobiles` (`:9-24`); allowed book IDs come from
`PhoneOnlbuch.json` / `addonlbuchentry` (`:40-69`). Current assignment is
independently read from each handset's `dect_onlbuch` (`:73-95`). Preserve all
unmodified handset assignments; no hardcoded book/handset numbers.

### Media actions distinct from full-row editing

`lan--nas_mediareplay.js:207-228` posts only `{id,mediareplay_active:0|1}` for
the immediate enable checkbox. Its form action now resolves to
`data/NASMediaReplay.json`. Do not require unrelated full-row fields for this
explicit shortcut.

`lan--nas_mediareplay.js:272-284` posts `{makeindex:"true"}` to `JSONSource`,
also `data/NASMediaReplay.json`. Here the callback explicitly requires
`status=="ok"` then reads `NASFileCount.json`, whose `DLNA_IndexStatus` and
`DLNA_IndexFileLeft` provide independently observed progress. Starting an index
is not equivalent to completed indexing.

## Remaining exact evidence requirements

- The v6 validator capture and complete template serialization now establish
  the selected telephone target editors' bounds, DOM exclusions and nested
  suffixes. Other full editors still need the same field-by-field proof;
  a sanitizer field list alone does not establish what is submitted.
- The v5 DOM capture confirms `attatch-status` bindings for module power flags
  including `use_dect` and `use_ippbx`; `appendStatusForm` posts their exact flag
  to `Modules.json` (`templateforms:1566-1583`). These bindings are implemented.
- VoIP `IPPhoneHandler.json` action is proven with 13 listed form fields:
  `areacode,id,ip_number,ipphonenumber_id,isp_selection,other_pass,other_phonename,
  other_phoneuser,other_port,other_registrar,show_t_mail,t_mail,t_phonepwd`.
  `show_t_mail` is explicitly `dontsubmit`. Existing-provider credentials now
  use separate Telekom, Regio and Other forms, preserving nested number rows.
  Provider creation and adding/editing numbers require separate contracts;
  they are not covered by the existing-provider credential editors.
- Phonebook export uses normal HTML form/link transport, not the generic
  `.form-internal` extractor. Capture its method/action and submitted fields.
  Import encoding/column headers and partial-merge semantics remain unproven.
- Online-book setup performs registration, optional merging and rollback-style
  disconnect steps; success at the first `postdone` is not final success.
- Independent detailed readbacks must contain all fields being changed or
  preserved; schema knowledge does not prove live availability. Secrets that
  cannot be independently verified must be explicitly reported as unverified.

The pure `nas_management.py` builder models only an **existing** NAS share,
preserves untouched submitted fields, binds the full non-secret snapshot,
rejects stale/ambiguous targets, never reuses returned passwords, and emits a
single-use payload. It is intentionally not an unrestricted endpoint executor.

The target-bound `configuration_storage.py` adapter exposes existing-share
enable, read-only access, login protection and credential edits. It is not in
the untargeted scalar registry: the server must resolve an exact existing `sid`
from a complete NASFolder response. The revision binds the identity, preserved
path, prerequisites and fields. Active protected shares require a freshly
entered password for each save. The UI reports credential persistence as
unverified even when all independently readable fields match. Every live write
remains for user testing.

DECT station radio/PIN reads now follow the actual template semantics:
`phone--phone_dect.js:468-473` counts `addrepeater` templates. A complete,
authenticated station response with no such template means zero repeaters;
partial payloads and explicit malformed containers remain unknown. A singleton
repeater mapping is one repeater, not zero. VoSIP similarly accepts the observed
singleton provider mapping without flattening arbitrary firmware tables.

## Existing telephone target editors: complete form evidence

`configuration_phone_targets.py` models four separately target-bound editors:
telephone-number call options, analog sockets, DECT handsets and existing IP
phones. Their static metadata never contains telephone numbers, credentials or
invented target IDs. Current choices require a fresh administrator-only read.

- `PhoneLineset.json` has one outer form containing every `addphonenumber`
  row. Its payload retains all rows as `id[n]`, `line[n]`, `clir[n]` and
  `reject_on_busy[n]`, where `n` is the one-based template ordinal, not the
  router's ID. `phone_lineset.js:35-48` forces single-call mode when busy
  rejection is enabled and multiple-call mode when it is disabled.
- Analog, DECT and IP phone forms are inside their outer row templates.
  `jquery-addons.js:708-713` enables `removeTemplateId` for these cloned forms;
  `:914-1013` concatenates nested template ordinals. Outer row 1, number 2
  therefore becomes `sid[12]` / `ring_incoming[12]`, not `sid[2]` or an
  arbitrary number ID. `jquery-templateforms.js:964-1012` removes only the
  final nested suffix. Submitted master `selectall_deselectnone` is derived
  from the complete current selection; it is not an independent user field.
- The private configuration decoder preserves `sid` compound records as
  `{sid,ring_incoming}`. The live analog response confirms that shape;
  ordinary scalar SID lists do not prove the incoming selection and are
  rejected. Labels join the exact top-level number inventory. No configured
  DECT handset or IP client was available for live read validation; those
  contracts remain statically verified and require user testing.
- Analog equipment enums are exactly `0` telephone, `1` answering machine,
  `2` fax and `3` multi-function. Call waiting is submitted only for a
  telephone. The page's type-change handler defaults telephone call waiting
  on; an explicit user override remains possible.
- Existing IP phone forms preserve `ipclient_status` and require a valid
  8–16-character password using the firmware `CharsForIPPBXPwd` character
  class. A mask or missing password must be re-entered. Password values never
  leave the private transaction, and changed credentials are reported as
  unverified even when all independent readable state matches.

Exact name bounds and character classes come from the v6 validator capture:
analog names 1–22 characters; DECT/IP names 1–15; `ASCIIwoHtml` excludes angle
brackets. The integration additionally rejects control characters. The generic
form callback requires `status == "ok"`; success then requires an independent
GET readback of the target and all sibling rows, preserving assignments and
telephone identity. There were no live write tests.

## Complete global assignment matrices

`configuration_phone_assignments.py` provides separate incoming and outgoing
editors, matching the two separate forms in `phone_number.html`. Each edit
selects one existing plug, sends the complete corresponding matrix, and
preserves every other plug. Unlike the per-device templates, matrix brackets
contain the actual router IDs, not DOM ordinals.

The live v7 response confirms `addglobalplug.sid` compound items with fields
`{sid,outg}`. Despite its name, the `outg` child is used by
`phone_number.js:35-43` to populate the incoming checkbox matrix. Top-level
`addphonenumber.id` identifies the exact number columns. A flattened SID list
or handset-style `ring_incoming` child is not sufficient evidence.

The backup literal `0` is explicitly **No alternative**, not an unknown number
(`lang/en.js:1181,1259-1260`). A nonzero backup must differ from the selected
outgoing Internet number. The backup editor rejects changes while the page's
IP-number/multiple-number prerequisite would hide that control; untouched
backups remain in the outgoing payload. Independent readback verifies both
matrices and all plug identities, including those not being edited.

## Existing manual provider credentials

The page's primary `JSONSource` is `data/IPPhoneHandler.json`; the companion
script's `IPPhone.json` URL is a provider-deletion shortcut, not the full page
reader. `configuration_phone_providers.py` uses the primary GET and same-page
POST contract. `phone_internet.js:864-903` removes inactive provider sections:

- Telekom (`isp_selection=0`): `t_mail`, `t_phonepwd`.
- MagentaZuhause Regio (`89`): `areacode`.
- Other (`1`): `other_phonename`, `other_phoneuser`, `other_pass`,
  `other_registrar`, `other_port`.

All forms preserve `id`, provider type, and every existing nested `ip_number`
and `ipphonenumber_id` pair. Number rows are not created or deleted implicitly.
The independent `InternetConnection.json` GET supplies the same online
prerequisite used by `phone_internet.js:179-213`. A missing prerequisite blocks
submission. Provider ID `99` is excluded because the firmware explicitly
hides its editing link (`:550`); it is automatically managed.

Passwords never appear in metadata, normal reads or UI snapshots. Existing
explicit empty passwords can be preserved, but missing or masked passwords
must be supplied afresh. Credential changes cannot be independently verified
as secrets and retain the corresponding unverified outcome. Provider/number
creation and online phonebook registration remain distinct lifecycle work.

## Existing local phonebook contact editor

`configuration_phonebook.py` binds a local book index `0`–`4` and one existing
contact ID. The server must supply a complete private detail response; missing
optional fields are not interpreted as empty strings. The editor preserves all
ten fields and posts the distinct write identity `{obnr,id}`, never the read
query's `{obnr,chgid}`. The actual page is `phone_book_entries.html`.

The v6 form confirms name/first-name maxima of 16, telephone numbers and
street/city maxima of 40, postal-code maximum 6, and birthday maximum 10.
`phone_book.js:249-289` requires a name and telephone number, removes spaces
from the four telephone-number fields, and validates optional birthdays as
real calendar dates in 1900–2099. The implementation applies these checks before
submission and verifies the complete contact by a new detail query afterwards.

The query transport is read-only despite using POST: the existing firmware
uses `PhoneBook.json {obnr,search}` for a bounded listing and
`PhoneBookEntry.json {obnr,chgid}` for details (`phone_book.js:172,200`). These
are not interchangeable with the save form. The normal public dashboard,
diagnostics and metadata must not cache private contacts.

Creation is a separate transaction: `phone_book.js:216-217` sets `id=-1`, and
the generic form framework reads an optional `assignedID`
(`jquery-templateforms.js:872-876`). The contact-specific code does not prove
that every successful create returns that ID. A create implementation must
validate its returned ID and independently query the exact new contact; it
must report an unknown outcome without retrying if that proof is absent.

`configuration_phonebook_lifecycle.py` now implements that guarded creation
contract. It binds a complete, unfiltered local-book inventory and free-entry
capacity to the transaction. A successful reply must contain an unambiguous
`status=ok` and new `assignedID`; independent reads must prove exactly one added
ID, unchanged existing list entries, and all ten fields of the new contact.
No ID is inferred from a row position or contact name. Empty local books were
confirmed by read-only queries in v10/v11, but no contact was created to obtain
a sample response. The address field `adresse` remains supported by the exact
HTML form; no live existing-contact detail was available for confirmation.

The existing contact-delete path now permits the complete bounded inventory
of up to 1,000 entries instead of silently limiting targets to 32. The firmware
`global.js` sets `maxPhoneBookEntries=1000` and `maxPhoneBooks=5`. This exception
is specific to phonebook deletion; other administrator target limits remain
unchanged. A missing `addbookentry` collection is considered empty only when
the response explicitly contains `status=ok`, `num_entries=0`, and valid
free-entry capacity. Partial inventories cannot prove that a contact vanished.

## Private call-history contracts and remaining readback proof

All three actual call-history pages declare `data/PhoneCalls.json` as their
primary source. `jsonvariables.js:6-17,42` adds cache-busting `_time` and `_rand`
parameters, optionally `_lang`, then invokes `loadJSON`. The category scripts
prove these distinct clear-only POST contracts:

| Category | Response collection | Clear endpoint | Body |
| --- | --- | --- | --- |
| Dialed | `adddialedcalls` | `data/PhoneDialedCalls.json` | `action_clearlist=true` |
| Missed | `addmissedcalls` | `data/PhoneMissedCalls.json` | `action_clearlist=true` |
| Answered | `addtakencalls` | `data/PhoneTakenCalls.json` | `action_clearlist=true` |

The corresponding `phone_call_*.js` callbacks remove displayed rows without
checking an endpoint-specific acknowledgement. Their print buttons only call
`window.print()`; no router CSV download endpoint is evidenced.

`call_history.py` supplies a closed category registry, strict private
projections, a locally generated formula-safe CSV export, the exact clear
payload, and independent clear verification. Caller and line strings remain
plain text, including the firmware's angle-bracket port notation. Readable
duration values are converted from validated wire seconds. Missing lists,
partial rows, ambiguous collection names and oversized inventories fail
closed; no list is silently truncated.

Live v11 GET responses for `PhoneCalls.json` and the category endpoints
contained only common router fields, without any call collection or explicit
call count. These replies do **not** prove an empty call history. Therefore the
helper contract is implemented, but live private reading/clearing must remain
unavailable unless the selected collection is explicitly present. An ACK or a
missing post-clear list cannot verify deletion. Other observed categories
must preserve their previous rows; newly arriving unrelated calls are allowed.
No real-router history was cleared. Contact and call data must never be placed
in public panel snapshots, normal entities, diagnostics or recorder history.

The authenticated `jquery-addons.js:1607-1650` capture confirms that `loadJSON`
performs GET with cache-busting parameters, decoding plaintext JSON or CCM.
There is no hidden call-category selector or read-only POST to substitute.

## Storage form expansion

The v6 authenticated validators resolve earlier bounds: NAS and media paths
have a maximum length of 512; media names require 1–20 characters matching
`ASCIIwoHtml`; new directory names require 1–512 characters. Existing NAS path
editing now uses this proven limit, rejects relative paths, traversal and
ambiguous separators, and preserves the exact untouched access/identity fields.
It changes a share's selected path, not the files themselves.

`configuration_media.py` models complete existing `NASMediaReplay.json` rows:
`id`, `mediareplay_active`, `mediareplay_name`, `mediareplay_folder`, and hidden
`mediareplay_status`. It preserves the hidden field in the submitted form and
checks every readable folder and sibling after the write. Names and paths
must remain unique, as the firmware's prevalidation requires. The fixed
16-folder bound comes from `global.js:99`, not an invented target limit.
Indexing uses the exact `makeindex=true` action and the independent
`NASFileCount.json` fields `DLNA_IndexStatus` and `DLNA_IndexFileLeft`; no
count-derived remaining-time estimate is presented as an actual router metric.

`storage_lifecycle.py` implements the safe-removal payload and verification
helpers from `nas_overview.js:70-96`. Only firmware types `NAS` and `adhoc` may
be removed. The exact current device ID and serial are bound before the
`OtherDevice.json {deleteEntry:"delete",serial,id}` POST. The page requires
`status=ok`; integration success additionally requires an explicit fresh
device inventory without that ID or serial and with other devices preserved.
An unavailable or omitted inventory cannot prove safe removal. The USB-enable
setting already exists in the complete energy-settings editor; there is no
separate proven printer-enable form to duplicate.

Safe removal now uses the existing `SettingsContract` target dispatcher and
revision-bound transaction, not another authorization-token mechanism.
`STORAGE_TARGET_SPECS` binds the `NASDevice.json` reader to the distinct
`OtherDevice.json` form. The explicit command checkbox and typed confirmation
never auto-submit.

`configuration_nas_create.py` adds the separate new-share lifecycle, reusing
`nas_management.py`'s conditional credential/path builder. Its preflight requires
an explicitly empty disabled form with `sid=-1`, USB enabled and no printer.
An independent read must show a fresh valid share ID and every submitted
readable field. The callback does not establish password correctness; entered
credentials remain separately unverified. Live v15 had no attached storage and
no share ID, so creation correctly remained unavailable on that captured state.

The media target registry also includes removing a folder configuration with
`{id,deleteEntry:"delete"}`. This invokes the firmware's generic form-delete
contract, not a filesystem deletion. Complete fresh inventory must prove the
selected configuration disappeared while other media folders remained intact.

The v17 media template further confirms new `id=-1` and hidden
`mediareplay_status="success"`. The new-media-folder contract submits those
exact literals and independently verifies one added configuration plus all
existing siblings. A separate reindex command requires a finished current
index and observes a fresh `Counting`, `Indexing`, or `reScanning` state after
the one-shot request. A rapid `Finished` to `Finished` sample is explicitly an
uncertain outcome, not fabricated proof that another indexing run occurred.

## New manual telephone providers and numbers

The v16 authenticated HTML confirms `id=-1` in the new provider container and
`ipphonenumber_id=-1` in its nested new-number template. The unrelated separate
form with `id=0` is not the provider creation form. `global.js` establishes
limits of ten providers and ten telephone numbers. Full capacity checks apply
before creation, including numbers belonging to automatically managed providers.

`configuration_phone_numbers.py` adds one number to a selected existing manual
provider. It reuses the existing complete credential payload, preserves all
existing nested IDs and numbers, and appends exactly one reviewed new-row
sentinel. No account spelling is changed merely to force payload construction.
The independent verifier requires exactly one new number identity, the expected
number, unchanged existing number options, and unchanged other providers.

`configuration_provider_create.py` creates a manual Telekom, MagentaZuhause
Regio, or Other provider with one initial number. It uses the same visible-field
validator as editing existing providers. Fresh readback must contain exactly one
new provider with one new number; all previous accounts and their number IDs
must remain unchanged. A number ID reused from another provider is rejected.
Provider account creation does not claim that SIP registration succeeded.

Number validation mirrors `phone_internet.js:248-379`: Other providers use the
`ASCIIwoHtml` pattern; Telekom/Regio use `VOIPPhoneNumber`. Only Telekom strips
the listed formatting characters, converts `00` to `+`, converts a leading
national `0` to `+49`, and requires a German country prefix. Duplicate national
and international aliases are rejected across all providers. Each save checks
the existing read-only Internet prerequisite; it never connects the Internet
or changes provider credentials as an implicit preparation step.

## Handset phonebook assignment

`phone_assign_onlbuch.js` resolves the formerly opaque radio field dynamically:
handsets come from `DECTMobiles.json` (`adddectmobiles`) and books from
`PhoneOnlbuch.json` (`addonlbuchentry`). Each radio name becomes
`dect_onlbuch_<actual handset ID>`, and its value is the actual `onlbuch_nr`.
The complete matrix is submitted to `DECTSettings.json`.

`configuration_phonebook_assignment.py` supplies the target-bound selector.
It binds the independently read book choices and all handset assignments to
the revision, changes only the selected handset, and checks all other rows and
book identities after submission. The firmware exposes assignment only with
at least one handset and more than one book; an absent list is not a fake
empty configuration.

## Phonebook transfer endpoint evidence

The actual entries page uses a native GET form for
`data/PhoneBookExport.json?sel_idx=<local book index>`. Import uses multipart
POST to `data/PhoneBookImport.json`, one file field named `importfile-<index>`,
and a 2 MiB limit. `phone_book.js:1-15,363-440,633-636` identifies numeric result
`status=0` as success and codes `1`–`8` as errors, with `totalNum`, `ignoreNum`
and `fullNum` counters. These are not the normal `status=ok` JSON form contract.
The CSV headers/encoding and independent import verification remain a distinct
file-transfer implementation requirement; no import was performed to infer them.

The file-transfer pipeline now implements twelve finite actions: import and export
for native book numbers 0–5. This is not a six-book capacity claim: the firmware
allows at most five actual books, and its allocator starts with number 1, so
number 5 can be used. Each one-use approval binds the book through its
action ID, along with requester, entry, file size and digest. Before transfer,
the existing strict private search must prove a complete inventory for that
exact book, and a fresh `PhoneOnlbuch.json` response must prove its actual
membership. No book number is assumed to exist; in particular, number 0 is not
invented as a default book. Local imports additionally require an unlinked book.
Empty exports are rejected before the native GET because the
read-only empty-book probe returned HTTP 500, not a CSV attachment. Full import
targets are rejected before upload. No online-book offset aliases are accepted.

An import is sent once and its bounded CCM response is decoded with the existing
session decoder. Status 0 is reported as `import_accepted`, with separate native
total/ignored/full counters and `contents_unverified`. No imported-contact count
is inferred from those counters. Codes 1–8 are reported as rejections, but every
attempted import invalidates protected cached data because a rejection may be
partial. The existing administrator authorization, no-replay grants, private
binary attachments, size/digest checks and session-cleanup gates remain intact.

Populated exports and actual imports remain untested on the router. The CSV
schema is not synthesized or rewritten. Downloads require a bounded attachment
with CSV or binary MIME type, never a login/error document. Contact data stays
outside entities, Recorder, diagnostics and public panel snapshots.

## Phonebook account lifecycle and online linking

`configuration_phonebook_accounts.py` models existing book name changes,
deletion and online-account disconnection. The complete account roster is
bounded to five actual books with unique native row IDs and book numbers.
Existing edits preserve the exact number and hidden account username. Deletion
must remove only the selected identity; disconnection must leave the same book
unlinked while preserving all other rows. Missing rosters remain unavailable,
not assumed empty.

The new local-book form uses `id=-1`, the first free number starting with 1,
the entered name, and an empty online username. Verification requires exactly
one new identity with the requested number and name and unchanged siblings.
The actual native number range 0–5 is shared by contact editors, membership
checks and private file transfers. A contact revision includes the private
book identity so replacement of a book at the same number cannot retain an
old editing authorization.

`phonebook_link.py` proves two separate online-linking requests: first the
explicit account credential form, then a separately approved decision about
merging existing contacts. The first response's count does not authorize the
second request. Its pending stage contains no password. The session owner
binds a short-lived one-use continuation to the Home Assistant requester,
login, router entry, selected account and complete contact inventory. The
two merge/replace decisions require different exact confirmation phrases.
Fresh account or contact changes invalidate that continuation. Final online
authentication and synchronization still require user testing; static numeric
domain choices 0, 1 and 2 are not assigned guessed provider labels.

`configuration_ip_phone_create.py` models the separate `IPClients.json`
allocation request rather than fabricating a full new account form. Capacity
is three clients. The response must contain a new, bounded `newestID`; an
independent `IPPBX.json` read must show exactly that added client and unchanged
existing rows. Credentials are never published through sensors or shared panel
state. Existing account editing separately follows the native 8–16-character
password rule with at least two of its character classes.

## Private system log and Router-Pass downloads

The captured `system_log.html` form uses an exact native GET to
`data/Syslog.json` with no form fields. `system_log_download` reuses the
administrator-only file-transfer route, one-use approval, bounded in-memory
attachment handling and session cleanup. It does not submit the separate
`SystemMessages.json` search/filter form or clear the log. A successful response
must be a nonempty text or binary attachment containing valid UTF-8 text, not
HTML, JSON or binary control data. The defensive download limit is 2 MiB;
the fixed local filename is `speedport-system-log.txt`. This limit is an
integration safeguard, not a claimed firmware limit.

`overview.js:112–219` implements Router-Pass printing locally: it reads
`WLANBasicAss.json`, decodes the Wi-Fi names and key, displays the serial number
and visibility settings, and includes a router password only when entered by
the user in that print dialog. There is no native Router-Pass export POST.
`system_router_pass_download` follows that distinction: one authenticated
read produces a bounded plain-text private card named `speedport-router-pass.txt`.
An optionally entered print password is not sent to the router, read from saved
integration credentials, or claimed verified. Missing or masked Wi-Fi credentials
fail closed. The local text card has no QR codes; it does not reproduce the
native print layout.

Both paths return private attachments, never entity states, shared snapshots,
diagnostics or public URLs. Responses use `no-store`, fixed filenames and
`nosniff`; cleanup failure or revoked authorization withholds the file. Their
native response formats and populated credential fields still require live
read-only validation. Offline tests exercise exact GETs, no password-bearing
router request, binary/HTML/JSON rejection, fixed filenames and cleanup.

## Remaining NAS directory chooser evidence

`nas_folder.js:7,101–131` requests `DiskDirectoryEntry.json` first with
`entry=/&mc=1`, then lazily with the selected absolute `entry` path. The new
directory action (`:215–238`) posts `NewDirectoryEntry.json` with one `entry`
constructed from the selected parent and entered directory name, then reloads
the tree. Its callback treats only `status=fail` as failure; it is not a
positive acknowledgement specification.

A safe executable directory creator still needs a proven, complete child-list
response and exact directory identity rules for the chooser and independent
readback. No populated `DiskDirectoryEntry.json` response was captured. Generic
global router data is not evidence of an empty directory. Existing NAS/media
path editors remain separate: they use validated absolute paths and do not
claim to create filesystem directories.
