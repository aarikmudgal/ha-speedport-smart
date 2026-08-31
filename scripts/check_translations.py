"""Verify English translation file matches integration strings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STRINGS = ROOT / "custom_components" / "speedport_smart" / "strings.json"
ENGLISH = ROOT / "custom_components" / "speedport_smart" / "translations" / "en.json"


def _shape(value: Any) -> Any:
    """Return nested key shape while ignoring translated leaf text."""
    if isinstance(value, dict):
        return {key: _shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(child) for child in value]
    return None


def main() -> int:
    """Validate both JSON files and their nested key shapes."""
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    english = json.loads(ENGLISH.read_text(encoding="utf-8"))
    if _shape(strings) != _shape(english):
        message = "translations/en.json key shape differs from strings.json"
        raise SystemExit(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
