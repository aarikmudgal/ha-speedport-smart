# HACS publication checklist

This is the maintainer checklist for
**https://github.com/aarikmudgal/ha-speedport-smart**. It separates files that
can be prepared in this repository from actions that require the public GitHub
repository or a pull request to HACS.

Do not claim that Telekom Speedport Smart is in the HACS default catalog until
the **hacs/default** pull request has been accepted and the next scheduled scan
has included it.

## Repository-side readiness

- [ ] Exactly one directory exists below **custom_components**:
      **speedport_smart**.
- [ ] Every runtime dependency and frontend asset is inside that integration
      directory.
- [ ] **manifest.json** includes the stable domain, public name, version,
      documentation URL, issue tracker, code owner, config-flow flag,
      integration type, and local-polling class.
- [ ] Root **hacs.json** names **Telekom Speedport Smart**, selects
      **speedport_smart.zip**, enables ZIP releases, hides the default branch
      from normal installs, sets the minimum Home Assistant version, and
      identifies Germany as the target country.
- [ ] **brand/icon.png** and **brand/icon@2x.png** are valid 256 × 256 and
      512 × 512 square PNG files.
- [ ] **brand/dark_icon.png** and **brand/dark_icon@2x.png** are valid 256 ×
      256 and 512 × 512 square PNG files and remain legible on dark themes.
- [ ] README, license, changelog, security policy, support guidance, code of
      conduct, and contribution guide are current.
- [ ] CI includes minimum and current Home Assistant tests, Ruff, mypy,
      English and German translation parity, frontend syntax and behavior
      tests, Hassfest, and the HACS Action without ignored checks.
- [ ] Release automation produces a full GitHub release and attaches
      **speedport_smart.zip**.

## Public GitHub settings

Configure the exact repository:

- **Owner:** aarikmudgal
- **Repository:** ha-speedport-smart
- **URL:** https://github.com/aarikmudgal/ha-speedport-smart
- **Visibility:** Public
- **Default branch:** main
- **Archived:** No
- **Issues:** Enabled

Suggested description:

> Local Home Assistant integration and native dashboard for Telekom Speedport
> Smart routers.

Add repository topics. HACS requires topics to exist; a useful set is:

- **home-assistant**
- **hacs**
- **telekom**
- **speedport**
- **router**
- **local-polling**

Enable GitHub Actions and permit the release workflow's GitHub token to write
repository contents. Protect **main** with pull requests and the required
minimum-Home-Assistant, current-Home-Assistant, Hassfest, and HACS checks.
Disable force pushes and branch deletion.

Enable **Private vulnerability reporting** under **Settings > Security >
Code security and analysis** so the private reporting link in **SECURITY.md**
works before the repository is announced publicly.

These settings cannot be proven by files in a local checkout.

## Brand delivery

The release archive includes the light icons **brand/icon.png** and
**brand/icon@2x.png**, plus the dark icons **brand/dark_icon.png** and
**brand/dark_icon@2x.png**. Home Assistant supports bundled brand assets for
custom integrations starting with Home Assistant 2026.3. Local assets take
precedence over the Brands CDN on those versions.

The **custom_integrations** folder in **home-assistant/brands** is now legacy,
so do not open a new Brands pull request for this custom integration. On Home
Assistant 2025.12 through 2026.2 the integration remains functional, but its
locally bundled icon may be shown as a generic placeholder. Home Assistant's
brand endpoint also returns a placeholder when an image is unavailable. A
placeholder on the minimum supported Home Assistant version is therefore not
an integration failure. Verify the light and dark bundled icons on Home
Assistant 2026.3 or newer, and check HACS repository presentation separately
during the clean-install smoke test.

Reference: **https://developers.home-assistant.io/docs/core/integration/brand_images/**

## Version 0.2.0 release

Version **v0.2.0-beta.20.1** completed the feature-branch validation cycle.
The stable pull request promotes the identical runtime source to **v0.2.0**;
its changelog section is dated and both source version files declare
**0.2.0**.

1. Push the tested <code>feat/*</code> branch only when it is ready to publish
   a beta prerelease.
2. Wait for the minimum Home Assistant, current Home Assistant, frontend,
   package, Hassfest, and HACS checks to pass.
3. Confirm the release workflow publishes a full
   **v0.2.0-beta.RUN.ATTEMPT** prerelease containing **speedport_smart.zip**
   and **SHA256SUMS**.
4. Install that beta through HACS and test setup, reload, upgrade, removal,
   light and dark themes, translations, dashboard behavior, and every exposed
   router control.
5. Confirm the stable pull request contains the dated **0.2.0** changelog
   section and no unvalidated runtime changes after the approved beta.
6. Merge only after all required checks pass. The successful **main** run must
   publish the full stable release **v0.2.0** with both release assets.
7. Install the stable asset through HACS and repeat the clean-install smoke
   test before updating the default-catalog submission.

If any remote check is red, fix it before publishing or promoting a release.
Do not update the default-catalog request with claims about unreleased code.

## Submit to the HACS default catalog

Only the repository owner or a major contributor should submit.

The catalog request may remain open during release promotion. Update it only
after the stable **v0.2.0** release and its install smoke test are complete.

1. Fork **https://github.com/hacs/default** under a personal account.
2. Create a fresh branch from its **master** branch.
3. Add **aarikmudgal/ha-speedport-smart** alphabetically to the
   **integration** file.
4. Open a pull request using the HACS template.
5. Complete every statement accurately, allow maintainer edits, and keep the PR
   out of draft only when every requirement is satisfied.

HACS review checks:

- bundled brand or matching Home Assistant Brands domain
- valid integration manifest
- HACS repository validation
- valid **hacs.json** with the expected name
- active, public, non-archived GitHub repository
- at least one full GitHub release
- submitter ownership or major contribution
- repository description, enabled issues, and topics
- valid JSON and alphabetical placement in the default list
- **country** in the released HACS manifest for the Germany-specific target

Reviews can take months. After merge, inclusion occurs on a later scheduled
HACS scan.

## Final external sign-off

- [ ] Public repository exists at the exact manifest URLs.
- [ ] Required GitHub settings are visible.
- [ ] Private vulnerability reporting is enabled and its report form opens.
- [ ] All remote checks pass without ignores.
- [ ] Stable release and ZIP asset install cleanly.
- [ ] A generic brand placeholder is accepted on Home Assistant 2025.12
      through 2026.2, and light and dark icons are confirmed on Home Assistant
      2026.3 or newer.
- [ ] No credentials or private router data exist in commits, Actions logs,
      issues, or release assets.
- [ ] **hacs/default** submission PR is open and accurately completed.
- [ ] README wording is updated only after default-catalog acceptance.

## Primary references

- [HACS integration requirements](https://hacs.xyz/docs/publish/integration/)
- [HACS default inclusion](https://hacs.xyz/docs/publish/include/)
- [HACS GitHub Action](https://hacs.xyz/docs/publish/action/)
- [HACS repository metadata](https://hacs.xyz/docs/publish/start/)
- [Home Assistant integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Home Assistant Brands](https://github.com/home-assistant/brands)
