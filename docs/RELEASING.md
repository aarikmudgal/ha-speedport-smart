# Release process

Telekom Speedport Smart uses GitHub releases and one HACS archive named
**speedport_smart.zip**. Stable releases come from **main**. Pushes to branches
matching <code>feat/*</code> create beta prereleases.

This document describes the intended remote automation. A local workflow file
does not prove that a GitHub release exists or that its checks passed.

## Version source

The stable version must match in:

- **custom_components/speedport_smart/manifest.json**
- **pyproject.toml**
- the matching section in **CHANGELOG.md**

Each stable version also requires **docs/releases/X.Y.Z.md**. This is the
human-written release summary, upgrade guidance and known limitations attached
to the GitHub release before its generated change list. The stable validator
requires a nonempty UTF-8 regular file and rejects symlinks in this path.
Beta publication does not require or publish these stable notes.
Release titles contain only the version tag, such as **v0.3.0** or
**v0.3.0-beta.RUN.ATTEMPT**; feature descriptions belong in the release body.

Use a three-part Semantic Version such as **1.2.3** in source. Do not put a
beta suffix in either source version; the feature-branch workflow applies that
suffix only to its staged package.

CI tests both the minimum supported Home Assistant fixture and a separately
pinned current fixture in
**requirements/current-home-assistant/requirements.txt**. Dependabot maintains
the current fixture separately so it cannot change the minimum pin. Confirm
which stable Home Assistant release a proposed fixture represents before
merging it because the fixture project also publishes versions for Home
Assistant betas.

The pinned fixtures target Home Assistant **2025.12.0** and **2026.8.3**.
These are the versions covered by the configured CI jobs, not a claim about
the newest upstream release. When updating a fixture, inspect its declared
Home Assistant dependency, choose a stable release, and run CI again before
claiming compatibility with that version.

## Stable release from main

1. Choose the next Semantic Version.
2. Update both source version files to the exact same value.
3. Move the relevant changelog entries under that version and add the date and
   comparison link. Write **docs/releases/X.Y.Z.md**, including upgrade steps,
   entity retirements, recovery guidance and any unverified behavior.
4. Open a pull request and wait for CI, Hassfest, HACS validation, and tests.
5. Merge the reviewed pull request to **main**.
6. Let the release workflow create:
   - immutable tag **vX.Y.Z**
   - full non-prerelease GitHub release **vX.Y.Z**
   - asset **speedport_smart.zip**
7. Inspect the release page and install the asset through a HACS custom
   repository before announcing it.

For 0.3.0, use the [release checklist](releases/0.3.0-checklist.md). Preparing a
PR is not publication. A reviewed merge and successful **push** CI on main
trigger the stable release; pull-request CI alone never publishes.

A published version is immutable. If **vX.Y.Z** already exists, do not replace
or move it. A later **main** push that still declares that version and builds
the identical integration package validates the existing release and exits
successfully without publishing again. Any packaged integration change must
use a new version; fix a released defect in a new patch version.

## Beta release from a feature branch

Use a maintainer-owned branch matching <code>feat/*</code>, for example
**feat/live-bandwidth**. Each eligible workflow run creates:

- package version **X.Y.Z-beta.&lt;run_number&gt;.&lt;run_attempt&gt;**
- tag **vX.Y.Z-beta.&lt;run_number&gt;.&lt;run_attempt&gt;**
- a GitHub prerelease with **speedport_smart.zip**

The workflow modifies the manifest only in its staging directory. The branch's
source version remains **X.Y.Z**. Run number plus run attempt makes a rerun
unique without rewriting a published prerelease.

Before the first beta, update both source version files to the next intended
stable **X.Y.Z**. If stable tag **vX.Y.Z** already exists, that beta line would
sort below the stable release and the workflow rejects it; choose the next
version instead.

Beta releases are integration test artifacts, not stable support commitments.
Delete obsolete feature branches after merge, but do not rewrite published
tags. HACS users receive prereleases only after enabling this repository's HACS
prerelease switch.

## Archive contract

The archive must contain integration runtime files at its root:

~~~text
speedport_smart.zip
├── __init__.py
├── manifest.json
├── strings.json
├── translations/
├── frontend/
├── brand/
└── ...
~~~

It must not add a **custom_components/speedport_smart** wrapper inside the ZIP.
The packaged manifest version must equal the release version. Tests, caches,
local environments, diagnostics, repository documents, and development scripts
do not belong in the runtime archive.

Before publishing, verify:

- the expected top-level archive layout
- valid JSON in the packaged manifest and HACS manifest
- stable or beta version parity, as applicable
- exactly one integration domain
- no credentials, local diagnostics, or generated cache files

The release summary is a repository document, not a runtime archive asset.
The dashboard modules and both themes' brand assets must remain in the archive.

## Release permissions and recovery

The release job needs **contents: write** for the GitHub-provided token; other
jobs should remain read-only. Releases must run only for pushes within the
repository, never for untrusted fork pull requests.

If validation fails, fix the branch and push again. If packaging fails before
a release is created, rerun after fixing the cause. If an incomplete release
was already published, preserve its evidence, publish a corrected patch
version, and explain the replacement in the changelog and release notes.

## Channel summary

| Source | Version/tag | GitHub type | HACS behavior |
| --- | --- | --- | --- |
| **main** | **vX.Y.Z** | Stable release | Normal update channel |
| <code>feat/*</code> | **vX.Y.Z-beta.RUN.ATTEMPT** | Prerelease | Requires repository prerelease switch |
