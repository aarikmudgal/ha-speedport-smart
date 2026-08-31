"""Build and verify a deterministic HACS ZIP release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[1]
DOMAIN: Final = "speedport_smart"
SEMVER: Final = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
EXCLUDED_NAMES: Final = frozenset({".DS_Store"})
EXCLUDED_SUFFIXES: Final = frozenset({".pyc", ".pyo"})
REQUIRED_ENTRIES: Final = frozenset(
    {
        "__init__.py",
        "brand/icon.png",
        "frontend/speedport-smart-panel.js",
        "icons.json",
        "manifest.json",
        "strings.json",
        "translations/en.json",
    }
)
ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)


def _manifest(source: Path) -> dict[str, object]:
    """Load the component manifest."""
    manifest_path = source / "manifest.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        msg = f"Unable to read {manifest_path}: {err}"
        raise ValueError(msg) from err
    if not isinstance(value, dict):
        msg = f"Expected a JSON object in {manifest_path}"
        raise TypeError(msg)
    return value


def _release_files(source: Path) -> tuple[Path, ...]:
    """Return sorted runtime files while rejecting unsafe symlinks."""
    files: list[Path] = []
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if path.is_symlink():
            msg = f"Release source must not contain symlinks: {relative}"
            raise ValueError(msg)
        if (
            "__pycache__" in relative.parts
            or path.name in EXCLUDED_NAMES
            or path.suffix in EXCLUDED_SUFFIXES
        ):
            continue
        if path.is_file():
            files.append(path)
    files.sort(key=lambda path: path.relative_to(source).as_posix())
    names = {path.relative_to(source).as_posix() for path in files}
    missing = sorted(REQUIRED_ENTRIES - names)
    if missing:
        msg = f"Release source is missing required runtime files: {', '.join(missing)}"
        raise ValueError(msg)
    return tuple(files)


def _zip_info(name: str) -> zipfile.ZipInfo:
    """Create reproducible regular-file metadata."""
    info = zipfile.ZipInfo(filename=name, date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _manifest_payload(source: Path, version: str) -> bytes:
    """Render a staged manifest with the release version."""
    manifest = _manifest(source)
    manifest["version"] = version
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()


def _build_archive(source: Path, output: Path, version: str) -> tuple[str, ...]:
    """Write a deterministic archive and return its expected entry names."""
    files = _release_files(source)
    names = tuple(path.relative_to(source).as_posix() for path in files)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent,
        delete=False,
        prefix=f".{output.name}.",
        suffix=".tmp",
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path, name in zip(files, names, strict=True):
                payload = (
                    _manifest_payload(source, version)
                    if name == "manifest.json"
                    else path.read_bytes()
                )
                archive.writestr(_zip_info(name), payload, compresslevel=9)
        temporary_path.replace(output)
        output.chmod(0o644)
    finally:
        temporary_path.unlink(missing_ok=True)
    return names


def _validate_archive(
    output: Path, expected_names: tuple[str, ...], version: str
) -> None:
    """Verify archive integrity, layout, file types, and staged version."""
    with zipfile.ZipFile(output) as archive:
        names = tuple(archive.namelist())
        if names != expected_names:
            raise ValueError("Archive entries differ from the sorted release source")
        if archive.testzip() is not None:
            raise ValueError("Archive CRC validation failed")
        for info in archive.infolist():
            path = Path(info.filename)
            mode = info.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                msg = f"Unsafe archive entry: {info.filename}"
                raise ValueError(msg)
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("version") != version:
            msg = "Archive manifest version does not match the requested release"
            raise ValueError(msg)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for one file."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _release_version(source: Path, requested_version: str | None) -> str:
    """Return and validate the requested or source manifest version."""
    source_version = _manifest(source).get("version")
    version = requested_version or source_version
    if not isinstance(version, str) or SEMVER.fullmatch(version) is None:
        msg = f"Release version is not canonical SemVer: {version!r}"
        raise ValueError(msg)
    return version


def _validate_output_paths(source: Path, output: Path, checksums: Path) -> None:
    """Reject outputs that could overwrite or pollute release input."""
    resolved_source = source.resolve()
    if output.is_relative_to(resolved_source):
        raise ValueError("Release output must be outside the integration directory")
    if checksums == output:
        raise ValueError("Checksum output must differ from the release archive")
    if checksums.is_relative_to(resolved_source):
        raise ValueError("Checksum output must be outside the integration directory")


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--version", help="Version staged into the ZIP manifest.")
    parser.add_argument("--output", type=Path, help="Output ZIP path.")
    parser.add_argument("--checksums", type=Path, help="Output SHA256SUMS path.")
    return parser


def main() -> int:
    """Build, verify, and checksum the release archive."""
    parser = _parser()
    args = parser.parse_args()
    repository_root = args.repository_root.resolve()
    source = repository_root / "custom_components" / DOMAIN
    output = (args.output or repository_root / "dist" / f"{DOMAIN}.zip").resolve()
    checksums = (args.checksums or output.with_name("SHA256SUMS")).resolve()
    try:
        version = _release_version(source, args.version)
        _validate_output_paths(source, output, checksums)
        names = _build_archive(source, output, version)
        _validate_archive(output, names, version)
        checksums.parent.mkdir(parents=True, exist_ok=True)
        digest = _sha256(output)
        checksums.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    except (OSError, TypeError, ValueError, zipfile.BadZipFile) as err:
        parser.error(str(err))

    sys.stdout.write(
        f"Built {output} ({len(names)} files, version {version}, sha256 {digest}).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
