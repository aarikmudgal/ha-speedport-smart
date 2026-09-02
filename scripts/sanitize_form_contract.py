"""
Extract value-free contracts from Speedport ``.form-internal`` HTML.

The parser is deliberately offline. It accepts HTML already supplied by the
operator, performs no network requests, and retains only sanitized action
paths plus form field names and types. Current values, option values,
human-readable text, secret values, and raw HTML never enter the result.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlsplit

_MAX_INPUT_BYTES: Final = 8 * 1024 * 1024
_MAX_NODES: Final = 100_000
_MAX_FORMS: Final = 256
_MAX_FIELDS_PER_FORM: Final = 512
_MAX_ACTION_LENGTH: Final = 256
_SAFE_FIELD_NAME: Final = re.compile(r"^[A-Za-z_$][A-Za-z0-9_.$:-]{0,127}(?:\[\])*$")
_SAFE_ACTION_PATH: Final = re.compile(r"^data/[A-Za-z0-9_.-]+\.json$")
_VOID_ELEMENTS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_INPUT_TYPES: Final = frozenset(
    {
        "checkbox",
        "color",
        "date",
        "datetime-local",
        "email",
        "file",
        "hidden",
        "month",
        "number",
        "password",
        "radio",
        "range",
        "search",
        "tel",
        "text",
        "time",
        "url",
        "week",
    }
)
_IGNORED_INPUT_TYPES: Final = frozenset({"button", "image", "reset", "submit"})
_AUTHENTICATION_PARTS: Final = frozenset(
    {
        "auth",
        "challenge",
        "cookie",
        "csrf",
        "httoken",
        "login",
        "nonce",
        "proof",
        "session",
        "token",
    }
)
_SECRET_PARTS: Final = frozenset(
    {
        "credential",
        "key",
        "pass",
        "passphrase",
        "passwd",
        "password",
        "pin",
        "private",
        "preshared",
        "psk",
        "puk",
        "pwd",
        "secret",
    }
)
_IDENTIFIER_PARTS: Final = frozenset(
    {
        "address",
        "dns",
        "gateway",
        "host",
        "id",
        "imei",
        "imsi",
        "ip",
        "mac",
        "network",
        "serial",
        "subnet",
        "uid",
        "uuid",
    }
)
_PRIVATE_PARTS: Final = frozenset(
    {
        "caller",
        "contact",
        "domain",
        "email",
        "label",
        "name",
        "number",
        "phone",
        "ssid",
        "title",
        "user",
    }
)

type FieldClassification = Literal[
    "authentication", "secret", "identifier", "private", "opaque"
]


class FormContractError(ValueError):
    """Fixed-code rejection that cannot include captured HTML."""

    def __init__(self, code: str) -> None:
        """Initialize one non-sensitive fixed rejection code."""
        super().__init__(code)
        self.code = code


def classify_field_name(
    name: str,
    *,
    input_type: str | None = None,
) -> FieldClassification:
    """Classify one field name without inspecting or retaining its value."""
    if (input_type or "").casefold() == "password":
        return "secret"
    parts = _name_parts(name)
    if parts & _AUTHENTICATION_PARTS or any(
        part.startswith(("auth", "csrf", "login"))
        or part.endswith(("nonce", "proof", "session", "token"))
        for part in parts
    ):
        return "authentication"
    if parts & _SECRET_PARTS or any(
        part.endswith(
            (
                "pass",
                "passphrase",
                "passwd",
                "password",
                "preshared",
                "psk",
                "puk",
                "pwd",
                "secret",
            )
        )
        for part in parts
    ):
        return "secret"
    if parts & _IDENTIFIER_PARTS:
        return "identifier"
    if parts & _PRIVATE_PARTS:
        return "private"
    return "opaque"


def sanitize_form_contracts(html: str) -> dict[str, Any]:
    """Return deterministic, value-free contracts from Speedport form HTML."""
    if not isinstance(html, str):
        raise FormContractError("invalid_html_type")
    if len(html.encode("utf-8")) > _MAX_INPUT_BYTES:
        raise FormContractError("html_input_limit_exceeded")

    parser = _SpeedportFormParser()
    try:
        parser.feed(html)
        parser.close()
    except FormContractError:
        raise
    except Exception as err:  # pragma: no cover - defensive parser boundary
        raise FormContractError("invalid_html") from err
    forms = [builder.contract() for builder in parser.forms]
    forms.sort(key=_form_sort_key)
    field_count = sum(len(form["fields"]) for form in forms)
    sensitive_count = sum(
        field["classification"] in {"authentication", "secret"}
        for form in forms
        for field in form["fields"]
    )
    return {
        "format": 1,
        "kind": "speedport_form_internal_contracts",
        "safety": {
            "action_paths_only": True,
            "field_values_retained": False,
            "human_text_retained": False,
            "option_values_retained": False,
            "secret_values_retained": False,
        },
        "summary": {
            "forms": len(forms),
            "fields": field_count,
            "sensitive_fields": sensitive_count,
        },
        "forms": forms,
    }


@dataclass(slots=True)
class _FieldBuilder:
    name: str
    types: set[str] = field(default_factory=set)
    classification: FieldClassification = "opaque"
    options_incomplete: bool = False

    def add_type(self, field_type: str) -> None:
        """Record one normalized HTML control type."""
        self.types.add(field_type)
        detected = classify_field_name(self.name, input_type=field_type)
        if _classification_rank(detected) < _classification_rank(self.classification):
            self.classification = detected
        if field_type in {"checkbox", "radio", "select-multiple", "select-one"}:
            self.options_incomplete = True

    def contract(self) -> dict[str, Any]:
        """Return the immutable JSON projection for this field."""
        return {
            "name": self.name,
            "types": sorted(self.types),
            "classification": self.classification,
            "options": [],
            "options_incomplete": self.options_incomplete,
        }


@dataclass(slots=True)
class _FormBuilder:
    actions: set[str] = field(default_factory=set)
    unsafe_action_seen: bool = False
    fields: dict[str, _FieldBuilder] = field(default_factory=dict)

    def add_action(self, value: str) -> None:
        """Record one sanitized action path without retaining rejected text."""
        action = _safe_action(value)
        if action is None:
            self.unsafe_action_seen = True
            return
        self.actions.add(action)

    def add_field(self, name: str | None, field_type: str) -> _FieldBuilder | None:
        """Record one named form control and ignore anonymous controls."""
        if name is None:
            return None
        safe_name = name.strip()
        if _SAFE_FIELD_NAME.fullmatch(safe_name) is None:
            raise FormContractError("unsafe_form_field_name")
        existing = self.fields.get(safe_name)
        if existing is None:
            if len(self.fields) >= _MAX_FIELDS_PER_FORM:
                raise FormContractError("form_field_limit_exceeded")
            existing = _FieldBuilder(name=safe_name)
            self.fields[safe_name] = existing
        existing.add_type(field_type)
        return existing

    def contract(self) -> dict[str, Any]:
        """Return one deterministic form contract with fixed blocker codes."""
        blockers: list[str] = []
        action: str | None = None
        if len(self.actions) == 1:
            action = next(iter(self.actions))
        elif not self.actions:
            blockers.append("missing_action")
        else:
            blockers.append("conflicting_actions")
        if self.unsafe_action_seen:
            blockers.append("unsafe_action_omitted")
        return {
            "action": action,
            "fields": [self.fields[name].contract() for name in sorted(self.fields)],
            "blockers": sorted(blockers),
        }


class _SpeedportFormParser(HTMLParser):
    """Minimal structural parser for Speedport's custom internal forms."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_FormBuilder] = []
        self._active_form: _FormBuilder | None = None
        self._tag_stack: list[tuple[str, bool, bool, bool]] = []
        self._action_fragments: list[str] | None = None
        self._active_select: _FieldBuilder | None = None
        self._nodes = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Inspect structural tags and discard all display data."""
        self._handle_start(tag, attrs, self_closing=False)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Inspect one self-closing structural tag."""
        self._handle_start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        """Close the most recent matching structural context."""
        normalized = tag.casefold()
        match = next(
            (
                index
                for index in range(len(self._tag_stack) - 1, -1, -1)
                if self._tag_stack[index][0] == normalized
            ),
            None,
        )
        if match is None:
            return
        closing = self._tag_stack[match:]
        del self._tag_stack[match:]
        for _name, starts_form, starts_action, starts_select in reversed(closing):
            if starts_select:
                self._active_select = None
            if starts_action:
                self._finish_action()
            if starts_form:
                if self._active_form is not None:
                    self.forms.append(self._active_form)
                self._active_form = None

    def handle_data(self, data: str) -> None:
        """Retain text only transiently while locating a form action path."""
        if self._action_fragments is not None:
            if sum(len(part) for part in self._action_fragments) + len(data) > (
                _MAX_ACTION_LENGTH
            ):
                if self._active_form is not None:
                    self._active_form.unsafe_action_seen = True
                self._action_fragments = None
                return
            self._action_fragments.append(data)

    def close(self) -> None:
        """Finish parsing and reject a truncated internal form."""
        super().close()
        if self._active_form is not None:
            raise FormContractError("unterminated_form_internal")

    def _handle_start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        self._nodes += 1
        if self._nodes > _MAX_NODES:
            raise FormContractError("html_node_limit_exceeded")
        normalized = tag.casefold()
        attributes = {name.casefold(): value for name, value in attrs}
        classes = frozenset((attributes.get("class") or "").split())
        starts_form = "form-internal" in classes
        starts_action = self._active_form is not None and "form-action" in classes
        starts_select = False

        if starts_form:
            if self._active_form is not None:
                raise FormContractError("nested_form_internal")
            if len(self.forms) >= _MAX_FORMS:
                raise FormContractError("form_count_limit_exceeded")
            self._active_form = _FormBuilder()

        if starts_action:
            if self._action_fragments is not None:
                raise FormContractError("nested_form_action")
            self._action_fragments = []

        if self._active_form is not None:
            if normalized == "input":
                self._handle_input(attributes)
            elif normalized == "select":
                # The control type is structural evidence; option values are not.
                field_type = (
                    "select-multiple" if "multiple" in attributes else "select-one"
                )
                self._active_select = self._active_form.add_field(
                    attributes.get("name"), field_type
                )
                starts_select = True
            elif normalized == "textarea":
                self._active_form.add_field(attributes.get("name"), "textarea")

        is_void = self_closing or normalized in _VOID_ELEMENTS
        if is_void:
            if starts_select:
                self._active_select = None
            if starts_action:
                self._finish_action()
            if starts_form:
                if self._active_form is not None:
                    self.forms.append(self._active_form)
                self._active_form = None
            return
        self._tag_stack.append((normalized, starts_form, starts_action, starts_select))

    def _handle_input(self, attributes: Mapping[str, str | None]) -> None:
        if self._active_form is None:  # pragma: no cover - guarded by caller
            raise FormContractError("input_outside_active_form")
        raw_type = (attributes.get("type") or "text").casefold()
        if raw_type in _IGNORED_INPUT_TYPES:
            return
        field_type = raw_type if raw_type in _INPUT_TYPES else "other"
        field_builder = self._active_form.add_field(attributes.get("name"), field_type)
        if field_builder is None:
            return
        # Checkbox and radio submission values are deliberately ignored. Their
        # value contract cannot be inferred safely from HTML control type alone.

    def _finish_action(self) -> None:
        fragments = self._action_fragments
        self._action_fragments = None
        if self._active_form is not None and fragments is not None:
            self._active_form.add_action("".join(fragments))


def _name_parts(name: str) -> frozenset[str]:
    """Split snake, kebab, dotted, and camel-case names into exact tokens."""
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return frozenset(re.findall(r"[a-z0-9]+", camel_split.casefold()))


def _classification_rank(classification: FieldClassification) -> int:
    return {
        "authentication": 0,
        "secret": 1,
        "identifier": 2,
        "private": 3,
        "opaque": 4,
    }[classification]


def _safe_action(value: str) -> str | None:
    """Return one local JSON path, never an origin, query, or fragment."""
    candidate = value.strip()
    if not candidate or len(candidate) > _MAX_ACTION_LENGTH or "\\" in candidate:
        return None
    try:
        split = urlsplit(candidate)
    except ValueError:
        return None
    if split.scheme or split.netloc or split.query or split.fragment:
        return None
    path = split.path
    while path.startswith("../"):
        path = path[3:]
    path = path.removeprefix("./").lstrip("/")
    normalized = posixpath.normpath(path)
    if normalized != path or _SAFE_ACTION_PATH.fullmatch(normalized) is None:
        return None
    return normalized


def _form_sort_key(form: Mapping[str, Any]) -> tuple[str, str]:
    fields = form.get("fields")
    names = (
        ",".join(str(item.get("name", "")) for item in fields)
        if isinstance(fields, list)
        else ""
    )
    return str(form.get("action") or ""), names


def _write_private_json(path: Path, document: Mapping[str, Any]) -> None:
    """Create one private sanitized artifact without following a symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as err:
        raise FormContractError("output_already_exists") from err
    except OSError as err:
        raise FormContractError("output_could_not_be_created") from err
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(document, output, indent=2, sort_keys=True)
            output.write("\n")
    except OSError as err:
        raise FormContractError("output_could_not_be_written") from err


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sanitize Speedport .form-internal HTML from standard input without "
            "making network requests."
        )
    )
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args()


def _load_stdin_html() -> str:
    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(raw) > _MAX_INPUT_BYTES:
        raise FormContractError("html_input_limit_exceeded")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as err:
        raise FormContractError("invalid_html_encoding") from err


def main() -> None:
    """Read HTML from stdin and write only sanitized contract evidence."""
    args = _arguments()
    try:
        evidence = sanitize_form_contracts(_load_stdin_html())
        _write_private_json(args.out, evidence)
    except FormContractError as err:
        raise SystemExit(f"Form contract rejected safely: {err.code}") from err
    sys.stdout.write("Sanitized form-contract evidence written.\n")


if __name__ == "__main__":
    main()
