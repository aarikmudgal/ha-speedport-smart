# Administration read-only validation

## Scope and limits

The September 3, 2026 audit used the installed `v0.3.0-beta.51.1` dashboard with
a Speedport Smart 4R Type A. It inspected the 69 Administration navigation pages
and their configuration editors, including the additional action forms. The
checks opened forms and read their current values or prerequisites. They did not
submit changes, select new setting values, start operations, upload files, link
accounts, or restart anything.

A form loading successfully is **not** evidence that its write has been verified
on a real router. Write testing remains a separate, user-controlled step. This
document contains no addresses, credentials, client names, call records, or
router identifiers.

## Observed read coverage

| Area | Read results on the audited router |
| --- | --- |
| Internet connection | Provider, PPPoE and DNS fields loaded. Public IP information loaded through the private administration view. |
| Mobile receiver | The typed LED editor failed despite the native entity having a state. Bonding and USB tethering encountered router prerequisites. Receiver eSIM-restore prerequisites loaded; firmware-update prerequisites did not provide an eligible offer. No operation was executed. |
| Access rules | Parental profiles, routing exceptions, new forwarding rules, new port-blocking rules and Dynamic DNS forms loaded. Some existing-rule inventories explicitly returned no editable target. |
| Wi-Fi | Names/security, radios/channels, schedules, guest and prioritized Wi-Fi, and access-control fields loaded. WPS availability was inspected without starting pairing. |
| LAN and DNS | IPv4/subnet, DHCP, device/voice prioritization, DNS rebind protection and exception creation loaded. Existing exception targets were explicitly empty. |
| Mesh and powerline | Rename, identification and disconnected-node deletion target reads returned no editable target. Maintenance operations remained guarded. Missing inventory is not proof that a capability is unsupported. |
| VPN | Peer-creation prerequisites loaded. Existing peer targets were explicitly empty. Shared-key replacement was rejected by its IPsec/peer prerequisites. |
| Smart Home | Activation prerequisites loaded; deactivation was rejected by its state guard. Nothing was activated or deactivated. |
| USB, NAS and media | Workgroup settings loaded. Share/folder creation, existing-target editing, media-index rebuilding and safe-removal forms lacked required state or inventories. No empty inventory was fabricated. |
| Telephone providers | Manual provider-creation forms loaded. Existing-provider editing and number-addition target reads returned no editable target. This does not establish that automatically provisioned telephony is absent. |
| Telephone devices | Number assignment, analog socket, DECT base/PIN/power/Eco and IP-PBX fields loaded. Handset/IP-phone target inventories and new-IP-phone prerequisites were unavailable. |
| Telephone behavior | Number usage, security, HD Voice, dial delay, status announcements, speed dial and learned-number-clear prerequisites loaded. No clear action was submitted. |
| Call lists | Missed, received and outgoing call reads were incomplete. Their clear-action forms remained disabled. An incomplete response is not an empty list. |
| Phonebooks | Update interval, rename, local-book creation, contact creation, deletion prerequisites and online-link form reads loaded. Disconnect and existing-contact target inventories were explicitly empty. Handset assignment lacked the required target inventory. No contacts or accounts changed. |
| System configuration | Password form, EasySupport, front-display schedule, energy, cloud-backup, logging/filtering, email-notification, secure-access and external-modem fields loaded. Passwords were not entered. |
| System maintenance | BNG activation/deactivation prerequisites loaded. Router/mesh firmware and mesh restart/reset forms remained subject to inventory, management or update-offer guards. Backup, restore and firmware screens were inspected without transfer or execution. |

## Corrections resulting from the audit

- Normalize the proven receiver LED read spellings `On`, `Timer` and `Off` to
  the same numeric values already supported by native controls. Keep writes
  numeric and preserve receiver-identity and readback checks.
- Preserve fixed, value-free prerequisite errors through the private HTTP and
  frontend layers. Explain EasySupport-managed bonding, active-receiver
  tethering restrictions, USB state, mesh eligibility, managed firmware,
  missing firmware offers, VPN key prerequisites, Smart Home state and
  incomplete call lists.
- Classify a missing NAS target inventory as unavailable, not as an empty list
  or a generic management-connection failure.
- Automatically load a newly available sibling section without discarding
  existing drafts or verified save results. Defer that recovery while a write
  is in progress, and cancel it if the page, user, entry or permissions change.
- Refresh the frontend asset version so installed clients receive these fixes.

The corrections are covered by offline contract, HTTP and frontend regression
tests. They do not bypass router restrictions or relax completeness checks for
destructive operations.

## Remaining validation

1. Install the next beta and confirm receiver LEDs load and prerequisite errors
   are specific in the real dashboard.
2. Capture a complete, sanitized response shape for unavailable call/device/
   storage inventories before considering parser changes. Do not replace
   missing collections with empty ones.
3. Have the user validate selected configuration writes separately. No real
   router write was tested during this audit.

This is an observed read audit, not a claim of complete firmware control parity
or a guarantee that every setting is available on every router configuration.
