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
- [ ] README, license, changelog, security policy, support guidance, code of
      conduct, and contribution guide are current.
- [ ] CI includes tests, Ruff, mypy, translation parity, Hassfest, and the HACS
      Action without ignored checks.
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

Current HACS validation accepts the bundled
**custom_components/speedport_smart/brand/icon.png** directly. Because this
integration also supports Home Assistant 2025.12, submitting the same assets to
Home Assistant Brands is recommended for consistent icon delivery on versions
before local custom-integration brand support:

~~~text
home-assistant/brands/
└── custom_integrations/
    └── speedport_smart/
        ├── icon.png
        └── icon@2x.png
~~~

That is a separate pull request to
**https://github.com/home-assistant/brands**. Follow its current image
requirements and trademark guidance. The bundled brand directory remains
required for the integration package.

## First stable release

The current checkout already declares **0.1.0**. Bootstrap the empty GitHub
repository with its description, topics, Issues, Actions, and workflow-token
settings before the initial push. The first push of the initial commit to
**main** is the intended **v0.1.0** release run; do not create a manual tag or
release first.

1. Push the initial commit and confirm **main** is the default branch.
2. Wait for CI, HACS, and Hassfest to pass. The gated release workflow runs
   only after that successful push workflow.
3. Confirm GitHub shows a full stable release **v0.1.0**, not only a tag.
4. Confirm it contains **speedport_smart.zip** and **SHA256SUMS**.
5. Protect **main** using the now-visible successful checks, and configure tag
   and immutable-release protections.
6. Add the repository to HACS as a custom **Integration** and perform a clean
   install, restart, setup, reload, upgrade, and removal smoke test.
7. Confirm no HACS Action check uses an ignore.

If any remote check is red, fix it and publish a newer full release after all
checks pass. Do not submit the default-catalog request against an older failing
release.

## Submit to the HACS default catalog

Only the repository owner or a major contributor should submit.

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
- [ ] Brand presentation is confirmed on the minimum supported Home Assistant
      version.
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
