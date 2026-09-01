# Contributing

Thank you for helping improve Telekom Speedport Smart. Contributions should
preserve local operation, firmware-aware capability discovery, stable Home
Assistant entity identity, and safe router behavior.

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
Security vulnerabilities must follow [Security](SECURITY.md), not a public
issue.

## Before starting

Search existing
[issues](https://github.com/aarikmudgal/ha-speedport-smart/issues) and pull
requests. Open a focused issue before a large feature, protocol expansion, or
behavioral redesign so scope and router evidence can be agreed first.

Use a branch matching <code>feat/*</code>, for example
**feat/live-bandwidth**, for feature work. Pushes to a maintainer-owned feature
branch can publish an automated beta prerelease; never include credentials, raw
router payloads, or private identifiers in a branch.

Before the first beta, set both source version files to the next intended
stable version. A feature branch based on an already released version is not a
valid beta line.

## Development setup

Python 3.13.2 or newer is required.

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[test]'
~~~

Run the local quality gates before opening a pull request:

~~~bash
ruff check .
ruff format --check .
mypy custom_components/speedport_smart
python scripts/check_translations.py
node --test tests/frontend/*.test.mjs
pytest
~~~

The automated tests do not require a real router and must not perform network
or router-setting changes.

## Protocol and firmware contributions

Speedport endpoints vary by model and firmware. A new capability needs:

1. sanitized evidence that the endpoint and value exist
2. protocol handling at the narrowest appropriate client layer
3. normalization into a stable semantic field
4. capability detection based on real evidence
5. an entity only when the source is usable
6. tests for supported, absent, and temporarily failing behavior
7. documentation of validated hardware and firmware

Never commit raw router responses. Replace passwords, cookies, challenge
material, public IP addresses, MAC addresses, phone numbers, SSIDs, client
names, serial numbers, SIM identifiers, VPN data, and other household
information with unmistakably synthetic values.

Raw HAR files, browser network logs, copied cURL requests, and packet captures
are equally sensitive and must never be attached to an issue or pull request.
For one explicitly authorized reversible scalar operation, follow the
[offline control-capture workflow](docs/PROTOCOL_DISCOVERY.md#user-operated-reversible-control-capture)
and submit only its reviewed sanitized JSON. A complete report is evidence for
manual review, not permission to generate a runtime command.

Read-only discovery comes first. A router-changing contribution also requires
a specific allowlisted command, capability proof, serialized execution, a
post-action state refresh, clear user-facing wording, and explicit maintainer
review. Do not add arbitrary endpoint execution, factory reset, credential
changes, secret export, or another destructive shortcut.

## Home Assistant behavior

- Keep the domain **speedport_smart** unchanged.
- Use config entries; do not add YAML configuration.
- Preserve unique IDs and entity-registry compatibility.
- Prefer Home Assistant device classes, state classes, units, and translations
  over custom presentation logic.
- Keep all user-facing text in **strings.json**, every integration translation,
  and the English and German panel dictionaries in sync.
- Keep runtime dependencies inside the integration manifest and package all
  required runtime files under **custom_components/speedport_smart**.
- Do not make a router call from the frontend panel.

## Pull requests

A pull request should:

- explain the user-visible outcome and affected firmware
- stay focused on one coherent change
- update tests and documentation with behavior
- include sanitized screenshots for panel changes
- pass Ruff, mypy, translations, pytest, Hassfest, and HACS validation
- preserve both the minimum and current Home Assistant CI compatibility lanes
- avoid unrelated formatting or generated-file churn
- update the **Unreleased** changelog when user-visible behavior changes

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
