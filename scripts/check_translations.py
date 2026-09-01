"""Verify every translation file matches the English integration strings."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STRINGS = ROOT / "custom_components" / "speedport_smart" / "strings.json"
TRANSLATIONS = ROOT / "custom_components" / "speedport_smart" / "translations"
ENGLISH = TRANSLATIONS / "en.json"
PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def _shape(value: Any) -> Any:
    """Return nested key shape while ignoring translated leaf text."""
    if isinstance(value, dict):
        return {key: _shape(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(child) for child in value]
    return None


def _load(path: Path) -> Any:
    """Load one UTF-8 JSON document."""
    return json.loads(path.read_text(encoding="utf-8"))


def _placeholders(value: Any) -> Any:
    """Return nested placeholder names for translated leaf text."""
    if isinstance(value, dict):
        return {key: _placeholders(child) for key, child in sorted(value.items())}
    if isinstance(value, list):
        return [_placeholders(child) for child in value]
    if isinstance(value, str):
        return sorted(PLACEHOLDER.findall(value))
    return None


def main() -> int:
    """Validate integration strings and every locale against English."""
    strings = _load(STRINGS)
    english = _load(ENGLISH)
    if _shape(strings) != _shape(english):
        message = "translations/en.json key shape differs from strings.json"
        raise SystemExit(message)
    english_shape = _shape(english)
    english_placeholders = _placeholders(english)
    for translation in sorted(TRANSLATIONS.glob("*.json")):
        localized = _load(translation)
        if _shape(localized) != english_shape:
            message = (
                f"translations/{translation.name} key shape differs from "
                "translations/en.json"
            )
            raise SystemExit(message)
        if _placeholders(localized) != english_placeholders:
            message = (
                f"translations/{translation.name} placeholders differ from "
                "translations/en.json"
            )
            raise SystemExit(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
