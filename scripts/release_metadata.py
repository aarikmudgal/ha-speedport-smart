"""Validate repository metadata and derive stable or beta release versions."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DOMAIN: Final = "speedport_smart"
INTEGRATION_NAME: Final = "Telekom Speedport Smart"
STABLE_SEMVER: Final = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FEATURE_BRANCH: Final = re.compile(r"^feat/[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class ReleaseMetadata:
    """Resolved release identifiers consumed by GitHub Actions."""

    base_version: str
    channel: str
    prerelease: bool
    release_name: str
    tag: str
    version: str


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object or fail with a useful path."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        msg = f"Unable to read valid JSON from {path}: {err}"
        raise ValueError(msg) from err
    if not isinstance(value, dict):
        msg = f"Expected a JSON object in {path}"
        raise TypeError(msg)
    return value


def _require_nonempty_string(data: dict[str, Any], key: str, path: Path) -> str:
    """Return a required non-empty string value."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"{path}: {key!r} must be a non-empty string"
        raise ValueError(msg)
    return value


def validate_repository(root: Path) -> str:
    """Validate release-critical HACS and Home Assistant metadata."""
    root = root.resolve()
    component_root = root / "custom_components"
    if component_root.is_symlink():
        raise ValueError("custom_components must not be a symlink")
    expected_component = component_root / INTEGRATION_DOMAIN
    if expected_component.is_symlink():
        msg = f"custom_components/{INTEGRATION_DOMAIN} must not be a symlink"
        raise ValueError(msg)
    component_directories = sorted(
        path
        for path in component_root.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    if component_directories != [expected_component]:
        found = ", ".join(str(path.relative_to(root)) for path in component_directories)
        msg = f"Expected exactly custom_components/{INTEGRATION_DOMAIN}; found: {found}"
        raise ValueError(msg)
    manifests = sorted(component_root.glob("*/manifest.json"))
    expected_manifest = expected_component / "manifest.json"
    if manifests != [expected_manifest]:
        found = ", ".join(str(path.relative_to(root)) for path in manifests)
        msg = f"Expected exactly custom_components/{INTEGRATION_DOMAIN}; found: {found}"
        raise ValueError(msg)

    manifest = _read_json(expected_manifest)
    if manifest.get("domain") != INTEGRATION_DOMAIN:
        msg = f"{expected_manifest}: domain must be {INTEGRATION_DOMAIN!r}"
        raise ValueError(msg)
    if manifest.get("name") != INTEGRATION_NAME:
        msg = f"{expected_manifest}: name must be {INTEGRATION_NAME!r}"
        raise ValueError(msg)
    for key in ("documentation", "integration_type", "iot_class", "issue_tracker"):
        _require_nonempty_string(manifest, key, expected_manifest)
    codeowners = manifest.get("codeowners")
    if (
        not isinstance(codeowners, list)
        or not codeowners
        or not all(
            isinstance(owner, str) and owner.startswith("@") for owner in codeowners
        )
    ):
        msg = f"{expected_manifest}: codeowners must contain GitHub @handles"
        raise ValueError(msg)

    version = _require_nonempty_string(manifest, "version", expected_manifest)
    if STABLE_SEMVER.fullmatch(version) is None:
        msg = f"Source manifest version {version!r} must be canonical stable SemVer"
        raise ValueError(msg)

    pyproject_path = root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project_version = pyproject["project"]["version"]
    except (KeyError, OSError, tomllib.TOMLDecodeError) as err:
        msg = f"Unable to read project.version from {pyproject_path}: {err}"
        raise ValueError(msg) from err
    if project_version != version:
        msg = (
            "Version mismatch: custom_components/speedport_smart/manifest.json "
            f"has {version!r}, pyproject.toml has {project_version!r}"
        )
        raise ValueError(msg)

    hacs_path = root / "hacs.json"
    hacs = _read_json(hacs_path)
    expected_hacs = {
        "country": "DE",
        "filename": "speedport_smart.zip",
        "hide_default_branch": True,
        "homeassistant": "2025.12.0",
        "name": INTEGRATION_NAME,
        "zip_release": True,
    }
    for key, expected in expected_hacs.items():
        if hacs.get(key) != expected:
            msg = f"{hacs_path}: {key!r} must be {expected!r}"
            raise ValueError(msg)

    return version


def resolve_release(
    base_version: str,
    *,
    branch: str,
    channel: str,
    run_attempt: int | None,
    run_number: int | None,
) -> ReleaseMetadata:
    """Resolve one stable or CI-unique beta release."""
    resolved_channel = channel
    if channel == "auto":
        resolved_channel = "stable" if branch == "main" else "beta"

    if resolved_channel == "stable":
        if branch and branch != "main":
            msg = f"Stable releases are only allowed from main, not {branch!r}"
            raise ValueError(msg)
        version = base_version
        release_name = f"{INTEGRATION_NAME} v{version}"
        prerelease = False
    else:
        if FEATURE_BRANCH.fullmatch(branch) is None:
            msg = f"Beta releases require a feat/<name> branch, not {branch!r}"
            raise ValueError(msg)
        if run_number is None or run_number < 1:
            raise ValueError("Beta releases require a positive GitHub run number")
        if run_attempt is None or run_attempt < 1:
            raise ValueError("Beta releases require a positive GitHub run attempt")
        version = f"{base_version}-beta.{run_number}.{run_attempt}"
        release_name = f"{INTEGRATION_NAME} v{version} ({branch})"
        prerelease = True

    return ReleaseMetadata(
        base_version=base_version,
        channel=resolved_channel,
        prerelease=prerelease,
        release_name=release_name,
        tag=f"v{version}",
        version=version,
    )


def validate_stable_changelog(root: Path, version: str) -> None:
    """Require a dated release section and link before stable publication."""
    changelog_path = root.resolve() / "CHANGELOG.md"
    try:
        changelog = changelog_path.read_text(encoding="utf-8")
    except OSError as err:
        msg = f"Stable release requires a readable {changelog_path}"
        raise ValueError(msg) from err

    escaped_version = re.escape(version)
    heading = re.compile(
        rf"^## \[{escaped_version}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
        re.MULTILINE,
    )
    if heading.search(changelog) is None:
        msg = (
            f"Stable release {version} requires a dated CHANGELOG.md section; "
            "leave changes under [Unreleased] only for beta validation"
        )
        raise ValueError(msg)

    release_link = re.compile(rf"^\[{escaped_version}\]: \S+$", re.MULTILINE)
    if release_link.search(changelog) is None:
        msg = f"Stable release {version} requires a CHANGELOG.md comparison link"
        raise ValueError(msg)


def resolve_repository_release(
    root: Path,
    *,
    branch: str,
    channel: str,
    run_attempt: int | None,
    run_number: int | None,
) -> ReleaseMetadata:
    """Validate repository state and derive one publishable release."""
    base_version = validate_repository(root)
    metadata = resolve_release(
        base_version,
        branch=branch,
        channel=channel,
        run_attempt=run_attempt,
        run_number=run_number,
    )
    if metadata.channel == "stable":
        validate_stable_changelog(root, base_version)
    return metadata


def _write_github_output(path: Path, metadata: ReleaseMetadata) -> None:
    """Append trusted single-line release values to a GitHub output file."""
    values = {
        "base_version": metadata.base_version,
        "channel": metadata.channel,
        "prerelease": str(metadata.prerelease).lower(),
        "release_name": metadata.release_name,
        "tag": metadata.tag,
        "version": metadata.version,
    }
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=ROOT,
        help="Repository root to validate (defaults to this script's repository).",
    )
    parser.add_argument(
        "--channel",
        choices=("auto", "beta", "check", "stable"),
        default="check",
        help="Release channel to derive; check only validates source metadata.",
    )
    parser.add_argument("--branch", default="", help="Source branch name.")
    parser.add_argument("--run-number", type=int, help="GitHub workflow run number.")
    parser.add_argument("--run-attempt", type=int, help="GitHub workflow run attempt.")
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Append derived values to this GitHub Actions output file.",
    )
    return parser


def main() -> int:
    """Validate the repository and optionally emit release metadata."""
    parser = _parser()
    args = parser.parse_args()
    if args.channel == "check" and args.github_output is not None:
        parser.error("--github-output requires a release channel")
    try:
        if args.channel == "check":
            base_version = validate_repository(args.repository_root)
            message = f"Repository release metadata is valid ({base_version}).\n"
            sys.stdout.write(message)
            return 0
        metadata = resolve_repository_release(
            args.repository_root,
            branch=args.branch,
            channel=args.channel,
            run_attempt=args.run_attempt,
            run_number=args.run_number,
        )
        if args.github_output is not None:
            _write_github_output(args.github_output, metadata)
    except (OSError, TypeError, ValueError) as err:
        parser.error(str(err))

    sys.stdout.write(json.dumps(asdict(metadata), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
