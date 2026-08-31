"""Compare the safe runtime contents of two HACS release ZIP archives."""

from __future__ import annotations

import argparse
import stat
import sys
import zipfile
from pathlib import Path
from typing import Final

CHUNK_SIZE: Final = 1024 * 1024


def _validated_entries(
    archive: zipfile.ZipFile,
    *,
    label: str,
) -> dict[str, zipfile.ZipInfo]:
    """Return safe, unique regular-file entries from one archive."""
    entries: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename
        parts = name.split("/")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or "\x00" in name
            or any(part in {"", ".", ".."} for part in parts)
            or info.is_dir()
            or stat.S_ISLNK(mode)
            or (file_type not in {0, stat.S_IFREG})
        ):
            msg = f"{label} archive contains unsafe entry: {name!r}"
            raise ValueError(msg)
        if info.flag_bits & 0x1:
            msg = f"{label} archive contains encrypted entry: {name!r}"
            raise ValueError(msg)
        if name in entries:
            msg = f"{label} archive contains duplicate entry: {name!r}"
            raise ValueError(msg)
        entries[name] = info
    if not entries:
        msg = f"{label} archive contains no runtime files"
        raise ValueError(msg)
    return entries


def _entry_summary(names: set[str]) -> str:
    """Render a concise sorted entry-name summary."""
    return ", ".join(sorted(names))


def _compare_entry_bytes(
    published: zipfile.ZipFile,
    published_info: zipfile.ZipInfo,
    candidate: zipfile.ZipFile,
    candidate_info: zipfile.ZipInfo,
) -> bool:
    """Compare decompressed entry bytes without loading whole files into memory."""
    if published_info.file_size != candidate_info.file_size:
        return False
    with (
        published.open(published_info) as published_file,
        candidate.open(candidate_info) as candidate_file,
    ):
        while published_chunk := published_file.read(CHUNK_SIZE):
            if published_chunk != candidate_file.read(CHUNK_SIZE):
                return False
        return candidate_file.read(1) == b""


def compare_archives(published_path: Path, candidate_path: Path) -> int:
    """Compare archive names and decompressed bytes, returning the file count."""
    with (
        zipfile.ZipFile(published_path) as published,
        zipfile.ZipFile(candidate_path) as candidate,
    ):
        published_entries = _validated_entries(published, label="Published")
        candidate_entries = _validated_entries(candidate, label="Candidate")
        published_names = set(published_entries)
        candidate_names = set(candidate_entries)
        if published_names != candidate_names:
            missing = published_names - candidate_names
            added = candidate_names - published_names
            details: list[str] = []
            if missing:
                details.append(f"missing from candidate: {_entry_summary(missing)}")
            if added:
                details.append(f"added to candidate: {_entry_summary(added)}")
            raise ValueError(f"Archive entry names differ ({'; '.join(details)})")

        changed = [
            name
            for name in sorted(published_names)
            if not _compare_entry_bytes(
                published,
                published_entries[name],
                candidate,
                candidate_entries[name],
            )
        ]
        if changed:
            msg = f"Archive entry contents differ: {_entry_summary(set(changed))}"
            raise ValueError(msg)
        return len(published_entries)


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--published",
        type=Path,
        required=True,
        help="Previously published release ZIP.",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Freshly built release ZIP to compare.",
    )
    return parser


def main() -> int:
    """Compare two release archives and report a concise result."""
    parser = _parser()
    args = parser.parse_args()
    try:
        file_count = compare_archives(args.published, args.candidate)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as err:
        parser.error(str(err))
    sys.stdout.write(f"Release archive contents match ({file_count} files).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
