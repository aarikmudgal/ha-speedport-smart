"""Tests for release metadata, archive building, and archive comparison."""

from __future__ import annotations

import json
import stat
import zipfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.build_release import _build_archive, _validate_archive
from scripts.compare_release import compare_archives
from scripts.release_metadata import (
    ReleaseMetadata,
    resolve_release,
    resolve_repository_release,
    validate_repository,
)


def _metadata_repository(root: Path) -> Path:
    """Create the smallest repository accepted by the metadata validator."""
    manifest_path = root / "custom_components" / "speedport_smart" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "codeowners": ["@owner"],
                "documentation": "https://example.test/docs",
                "domain": "speedport_smart",
                "integration_type": "hub",
                "iot_class": "local_polling",
                "issue_tracker": "https://example.test/issues",
                "name": "Telekom Speedport Smart",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "hacs.json").write_text(
        json.dumps(
            {
                "country": "DE",
                "filename": "speedport_smart.zip",
                "hide_default_branch": True,
                "homeassistant": "2025.12.0",
                "name": "Telekom Speedport Smart",
                "zip_release": True,
            }
        ),
        encoding="utf-8",
    )
    return root


def _release_source(root: Path) -> Path:
    """Create a minimal integration source with all required runtime entries."""
    source = root / "custom_components" / "speedport_smart"
    payloads = {
        "__init__.py": b'"""Integration."""\n',
        "brand/dark_icon.png": b"test-dark-icon",
        "brand/dark_icon@2x.png": b"test-dark-icon-2x",
        "brand/icon.png": b"test-icon",
        "brand/icon@2x.png": b"test-icon-2x",
        "frontend/accessibility.js": b"export {};\n",
        "frontend/controls.js": b"export {};\n",
        "frontend/entity-state.js": b"export {};\n",
        "frontend/render-state.js": b"export {};\n",
        "frontend/speedport-smart-panel.js": b"export {};\n",
        "frontend/configuration-editor.js": b"export {};\n",
        "frontend/maintenance-editor.js": b"export {};\n",
        "frontend/file-transfer-editor.js": b"export {};\n",
        "frontend/file-digest.js": b"export {};\n",
        "frontend/call-history-view.js": b"export {};\n",
        "frontend/private-api.js": b"export {};\n",
        "frontend/translations.js": b"export {};\n",
        "icons.json": b"{}\n",
        "manifest.json": b'{"domain": "speedport_smart", "version": "0.1.0"}\n',
        "strings.json": b"{}\n",
        "translations/en.json": b"{}\n",
        "translations/de.json": b"{}\n",
    }
    for name, payload in payloads.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return source


def _write_zip(
    path: Path,
    entries: Sequence[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
    timestamp: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
) -> None:
    """Write test entries with controlled ZIP representation metadata."""
    with zipfile.ZipFile(path, mode="w", compression=compression) as archive:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.compress_type = compression
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, payload)


def test_validate_repository_rejects_version_mismatch(tmp_path: Path) -> None:
    """Source versions must agree before a release can be derived."""
    root = _metadata_repository(tmp_path)
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.2.1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Version mismatch"):
        validate_repository(root)


def test_resolve_stable_and_beta_release_metadata() -> None:
    """Stable and beta channels derive their documented identifiers."""
    assert resolve_release(
        "0.1.0",
        branch="main",
        channel="auto",
        run_attempt=None,
        run_number=None,
    ) == ReleaseMetadata(
        base_version="0.1.0",
        channel="stable",
        prerelease=False,
        release_name="Telekom Speedport Smart v0.1.0",
        tag="v0.1.0",
        version="0.1.0",
    )
    assert resolve_release(
        "0.3.0",
        branch="feat/live-polling",
        channel="auto",
        run_attempt=2,
        run_number=41,
    ) == ReleaseMetadata(
        base_version="0.3.0",
        channel="beta",
        prerelease=True,
        release_name=("Telekom Speedport Smart v0.3.0-beta.41.2 (feat/live-polling)"),
        tag="v0.3.0-beta.41.2",
        version="0.3.0-beta.41.2",
    )


def test_repository_release_requires_changelog_only_for_stable(
    tmp_path: Path,
) -> None:
    """Beta remains publishable while stable requires its dated changelog entry."""
    root = _metadata_repository(tmp_path)

    beta = resolve_repository_release(
        root,
        branch="feat/router-management",
        channel="auto",
        run_attempt=1,
        run_number=42,
    )
    assert beta.version == "0.1.0-beta.42.1"

    with pytest.raises(ValueError, match=r"dated CHANGELOG\.md section|readable"):
        resolve_repository_release(
            root,
            branch="main",
            channel="auto",
            run_attempt=None,
            run_number=None,
        )

    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [0.1.0] - 2026-09-01\n\n"
        "- Initial release.\n\n"
        "[Unreleased]: https://example.test/compare/v0.1.0...HEAD\n"
        "[0.1.0]: https://example.test/releases/tag/v0.1.0\n",
        encoding="utf-8",
    )
    stable = resolve_repository_release(
        root,
        branch="main",
        channel="auto",
        run_attempt=None,
        run_number=None,
    )

    assert stable.version == "0.1.0"


def test_stable_changelog_requires_version_link(tmp_path: Path) -> None:
    """A dated heading alone cannot publish an unlinked stable changelog."""
    root = _metadata_repository(tmp_path)
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] - 2026-09-01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="comparison link"):
        resolve_repository_release(
            root,
            branch="main",
            channel="stable",
            run_attempt=None,
            run_number=None,
        )


@pytest.mark.parametrize("branch", ["feature/name", "feat/name/nested", "feat/Upper"])
def test_resolve_beta_rejects_invalid_branch(branch: str) -> None:
    """Only the exact lowercase feat/<name> convention can publish betas."""
    with pytest.raises(ValueError, match=r"feat/<name>"):
        resolve_release(
            "0.1.0",
            branch=branch,
            channel="beta",
            run_attempt=1,
            run_number=1,
        )


def test_build_archive_is_deterministic_and_stages_beta(tmp_path: Path) -> None:
    """Repeated beta builds are byte-identical without mutating source metadata."""
    source = _release_source(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    version = "0.3.0-beta.17.1"

    first_names = _build_archive(source, first, version)
    second_names = _build_archive(source, second, version)
    _validate_archive(first, first_names, version)
    _validate_archive(second, second_names, version)

    assert first_names == second_names
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == version
    assert json.loads((source / "manifest.json").read_bytes())["version"] == "0.1.0"


def test_build_archive_rejects_symlink(tmp_path: Path) -> None:
    """Release input symlinks cannot escape or alias packaged runtime files."""
    source = _release_source(tmp_path)
    (source / "linked.py").symlink_to(source / "__init__.py")

    with pytest.raises(ValueError, match="must not contain symlinks"):
        _build_archive(source, tmp_path / "release.zip", "0.1.0")


def test_build_archive_rejects_symlinked_component_root(tmp_path: Path) -> None:
    """A feature branch cannot redirect the complete release source tree."""
    source = _release_source(tmp_path / "real")
    linked_source = tmp_path / "linked-component"
    linked_source.symlink_to(source, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        _build_archive(linked_source, tmp_path / "release.zip", "0.1.0")


def test_validate_repository_rejects_symlinked_component_root(
    tmp_path: Path,
) -> None:
    """Metadata validation must not follow a feature-controlled component link."""
    root = _metadata_repository(tmp_path)
    component = root / "custom_components" / "speedport_smart"
    target = root / "component-target"
    component.rename(target)
    component.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symlink"):
        validate_repository(root)


def test_compare_archives_ignores_zip_representation_metadata(tmp_path: Path) -> None:
    """Equivalent payloads match despite compression, order, and timestamp changes."""
    published = tmp_path / "published.zip"
    candidate = tmp_path / "candidate.zip"
    entries = [("manifest.json", b"{}\n"), ("nested/data.txt", b"payload")]
    _write_zip(published, entries, compression=zipfile.ZIP_STORED)
    _write_zip(
        candidate,
        list(reversed(entries)),
        compression=zipfile.ZIP_DEFLATED,
        timestamp=(2026, 8, 31, 12, 0, 0),
    )

    assert published.read_bytes() != candidate.read_bytes()
    assert compare_archives(published, candidate) == 2


def test_compare_archives_rejects_changed_content(tmp_path: Path) -> None:
    """A same-name runtime file with changed bytes prevents a release no-op."""
    published = tmp_path / "published.zip"
    candidate = tmp_path / "candidate.zip"
    _write_zip(published, [("manifest.json", b"old")])
    _write_zip(candidate, [("manifest.json", b"new")])

    with pytest.raises(ValueError, match=r"contents differ: manifest.json"):
        compare_archives(published, candidate)


def test_compare_archives_rejects_duplicate_entry(tmp_path: Path) -> None:
    """Duplicate archive names are rejected instead of ambiguously compared."""
    published = tmp_path / "published.zip"
    candidate = tmp_path / "candidate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_zip(published, [("manifest.json", b"first"), ("manifest.json", b"last")])
    _write_zip(candidate, [("manifest.json", b"last")])

    with pytest.raises(ValueError, match="duplicate entry"):
        compare_archives(published, candidate)


def test_compare_archives_rejects_unsafe_entry(tmp_path: Path) -> None:
    """Traversal-style entries cannot participate in release comparison."""
    published = tmp_path / "published.zip"
    candidate = tmp_path / "candidate.zip"
    _write_zip(published, [("../manifest.json", b"{}")])
    _write_zip(candidate, [("manifest.json", b"{}")])

    with pytest.raises(ValueError, match="unsafe entry"):
        compare_archives(published, candidate)
