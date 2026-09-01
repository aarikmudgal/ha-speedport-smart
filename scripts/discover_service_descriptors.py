"""
Discover advertised UPnP/TR-064 service contracts without executing them.

This developer utility performs unauthenticated HTTP GET requests for device
descriptions and their advertised SCPD documents.  Its output is deliberately
structural: it never retains raw XML, HTTP metadata, router identity fields, or
an executable endpoint contract.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TypedDict, cast
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import aiohttp

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
_DEFAULT_ROOTS: Final = (
    ("http", 49000, "/tr64desc.xml"),
    ("https", 49443, "/tr64desc.xml"),
    ("http", 5543, "/tr64desc.xml"),
    ("https", 8443, "/tr64desc.xml"),
)
_MAX_BODY_BYTES: Final = 512 * 1024
_HTTP_SUCCESS_MIN: Final = 200
_HTTP_REDIRECT_MIN: Final = 300
_HTTP_CLIENT_ERROR_MIN: Final = 400
_MAX_ROOTS: Final = 12
_MAX_SERVICES: Final = 128
_MAX_XML_DEPTH: Final = 32
_MAX_XML_ELEMENTS: Final = 10_000
_MAX_TOKEN_LENGTH: Final = 1_024
_MIN_CONTROL_CODE: Final = 32
_MAX_TCP_PORT: Final = 65_535
_READ_CHUNK_BYTES: Final = 16 * 1024
_XML_DECLARATION_PATTERN: Final = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)\b",
    flags=re.IGNORECASE,
)


class DiscoveryError(ValueError):
    """Raised when no safe root descriptor can be inspected."""


class _DocumentError(ValueError):
    """A sanitized descriptor or transport failure."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Bounded response returned by a GET-only document fetcher."""

    body: bytes
    status: int


class DocumentFetcher(Protocol):
    """Transport boundary that exposes GET and nothing else."""

    def get(self, url: str) -> Awaitable[FetchResult]:
        """Fetch one exact URL without redirects."""


class _Locator(TypedDict):
    """Sanitized URL locator that deliberately omits the host."""

    path: str
    port: int
    scheme: str


class AiohttpDocumentFetcher:
    """GET-only aiohttp transport with redirects and large bodies rejected."""

    def __init__(self, session: aiohttp.ClientSession, *, verify_ssl: bool) -> None:
        """Initialize a stateless descriptor transport."""
        self._session = session
        self._verify_ssl = verify_ssl

    async def get(self, url: str) -> FetchResult:
        """Fetch one descriptor using GET without redirects or cookie state."""
        try:
            async with self._session.get(
                url,
                allow_redirects=False,
                ssl=self._verify_ssl,
            ) as response:
                _validate_response_status(response.status)

                content_length = response.content_length
                _validate_content_length(content_length, status=response.status)

                body = bytearray()
                async for chunk in response.content.iter_chunked(_READ_CHUNK_BYTES):
                    _extend_bounded_body(body, chunk, status=response.status)
                return FetchResult(body=bytes(body), status=response.status)
        except _DocumentError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise _DocumentError("transport_error") from err


async def discover_service_descriptors(
    host: str,
    *,
    fetcher: DocumentFetcher,
    root_urls: Sequence[str] | None = None,
) -> dict[str, object]:
    """Return a sanitized inventory of advertised services and SCPD actions."""
    normalized_host, rendered_host = _normalize_host(host)
    candidates = list(root_urls or _default_root_urls(rendered_host))
    if not candidates:
        raise DiscoveryError("At least one root descriptor URL is required")
    if len(candidates) > _MAX_ROOTS:
        raise DiscoveryError(f"At most {_MAX_ROOTS} root descriptor URLs are allowed")

    validated_roots = [
        _validate_root_url(url, expected_host=normalized_host) for url in candidates
    ]
    roots: list[dict[str, object]] = []
    services: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []

    for root_url in sorted(set(validated_roots), key=_url_sort_key):
        root_locator = _locator(root_url)
        try:
            root_response = await _safe_get(fetcher, root_url)
            root_element = _parse_xml(root_response.body)
            advertised, advertisement_errors = _advertised_services(
                root_element,
                root_url=root_url,
                expected_host=normalized_host,
            )
        except _DocumentError as err:
            errors.append(_error("root", root_locator["path"], err))
            continue

        errors.extend(advertisement_errors)

        if len(services) + len(advertised) > _MAX_SERVICES:
            errors.append(
                {
                    "path": root_locator["path"],
                    "reason": "service_limit_exceeded",
                    "stage": "root",
                }
            )
            continue

        roots.append(
            {
                **root_locator,
                "response_sha256": _sha256(root_response.body),
                "response_status": root_response.status,
                "service_count": len(advertised),
            }
        )

        for advertised_service in advertised:
            service = dict(advertised_service)
            scpd_url = str(service.pop("_scpd_url"))
            try:
                response = await _safe_get(fetcher, scpd_url)
                scpd_root = _parse_xml(response.body)
                actions, state_variables = _parse_scpd(scpd_root)
            except _DocumentError as err:
                service.update(
                    {
                        "actions": [],
                        "response_sha256": None,
                        "response_status": err.status,
                        "state_variables": [],
                    }
                )
                errors.append(_error("scpd", str(service["scpd_path"]), err))
            else:
                service.update(
                    {
                        "actions": actions,
                        "response_sha256": _sha256(response.body),
                        "response_status": response.status,
                        "state_variables": state_variables,
                    }
                )
            services.append(service)

    if not roots:
        raise DiscoveryError("No safe root descriptor could be read")

    return {
        "advertised_only": True,
        "errors": sorted(errors, key=_mapping_sort_key),
        "format_version": 1,
        "roots": sorted(roots, key=_mapping_sort_key),
        "services": sorted(services, key=_service_sort_key),
    }


async def _safe_get(fetcher: DocumentFetcher, url: str) -> FetchResult:
    """Fetch and re-apply the body bound at the transport-independent layer."""
    response = await fetcher.get(url)
    if not _HTTP_SUCCESS_MIN <= response.status < _HTTP_REDIRECT_MIN:
        raise _DocumentError("http_status", status=response.status)
    if len(response.body) > _MAX_BODY_BYTES:
        raise _DocumentError("response_too_large", status=response.status)
    return response


def _advertised_services(
    root: ET.Element,
    *,
    root_url: str,
    expected_host: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Extract service advertisements while ignoring device identity fields."""
    base_url = root_url
    url_base = next(
        (
            _clean_text(element.text)
            for element in root.iter()
            if _local_name(element.tag) == "URLBase" and element.text
        ),
        None,
    )
    if url_base:
        base_url = _resolve_service_url(
            root_url,
            url_base,
            expected_host=expected_host,
        )

    services: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for element in root.iter():
        if _local_name(element.tag) != "service":
            continue
        scpd_reference: str | None = None
        try:
            fields = {
                _local_name(child.tag): _clean_text(child.text)
                for child in element
                if child.text
            }
            service_type = fields.get("serviceType")
            service_id = fields.get("serviceId")
            scpd_reference = fields.get("SCPDURL")
            service_type, service_id, scpd_reference = _required_service_fields(
                service_type,
                service_id,
                scpd_reference,
            )

            scpd_url = _resolve_service_url(
                base_url,
                scpd_reference,
                expected_host=expected_host,
            )
            control_url = _optional_service_url(
                base_url,
                fields.get("controlURL"),
                expected_host=expected_host,
            )
            event_url = _optional_service_url(
                base_url,
                fields.get("eventSubURL"),
                expected_host=expected_host,
            )
        except _DocumentError as err:
            errors.append(
                _error(
                    "advertisement",
                    _reference_path(scpd_reference, fallback=root_url),
                    err,
                )
            )
            continue
        services.append(
            {
                "_scpd_url": scpd_url,
                "advertised_only": True,
                "control_path": _path_or_none(control_url),
                "event_path": _path_or_none(event_url),
                "root_path": _locator(root_url)["path"],
                "scpd_path": _locator(scpd_url)["path"],
                "service_id": service_id,
                "service_type": service_type,
            }
        )
    return sorted(services, key=_service_sort_key), errors


def _parse_scpd(
    root: ET.Element,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Extract the advertised action and state-variable schema from one SCPD."""
    actions: list[dict[str, object]] = []
    state_variables: list[dict[str, object]] = []

    for element in root.iter():
        local_name = _local_name(element.tag)
        if local_name == "action":
            name = _direct_child_text(element, "name")
            if not name:
                raise _DocumentError("incomplete_action")
            arguments: list[dict[str, object]] = []
            for argument in _direct_descendants(element, "argument"):
                argument_name = _direct_child_text(argument, "name")
                direction = _direct_child_text(argument, "direction")
                related = _direct_child_text(argument, "relatedStateVariable")
                if not argument_name or direction not in {"in", "out"} or not related:
                    raise _DocumentError("incomplete_action_argument")
                arguments.append(
                    {
                        "direction": direction,
                        "name": argument_name,
                        "related_state_variable": related,
                    }
                )
            actions.append(
                {
                    "arguments": sorted(arguments, key=_mapping_sort_key),
                    "name": name,
                }
            )
        elif local_name == "stateVariable":
            name = _direct_child_text(element, "name")
            data_type = _direct_child_text(element, "dataType")
            if not name or not data_type:
                raise _DocumentError("incomplete_state_variable")
            allowed_values = sorted(
                {
                    value
                    for allowed_list in _direct_children(
                        element,
                        "allowedValueList",
                    )
                    for allowed in _direct_children(allowed_list, "allowedValue")
                    if (value := _clean_text(allowed.text))
                }
            )
            range_data: dict[str, str] = {}
            for allowed_range in _direct_children(element, "allowedValueRange"):
                for source_name, output_name in (
                    ("minimum", "minimum"),
                    ("maximum", "maximum"),
                    ("step", "step"),
                ):
                    value = _direct_child_text(allowed_range, source_name)
                    if value is not None:
                        range_data[output_name] = value
            state_variables.append(
                {
                    "allowed_values": allowed_values,
                    "data_type": data_type,
                    "evented": _evented(element),
                    "name": name,
                    "range": range_data or None,
                }
            )

    return (
        sorted(actions, key=_mapping_sort_key),
        sorted(state_variables, key=_mapping_sort_key),
    )


def _parse_xml(body: bytes) -> ET.Element:
    """Parse bounded XML after rejecting DTD/entity declarations and deep trees."""
    if b"\x00" in body:
        raise _DocumentError("unsupported_xml_encoding")
    if _XML_DECLARATION_PATTERN.search(body):
        raise _DocumentError("xml_entity_or_doctype_rejected")

    parser: ET.XMLPullParser[ET.Element[str]] = ET.XMLPullParser(
        events=("start", "end")
    )
    depth = 0
    element_count = 0
    root: ET.Element[str] | None = None
    try:
        for offset in range(0, len(body), _READ_CHUNK_BYTES):
            parser.feed(body[offset : offset + _READ_CHUNK_BYTES])
            for item in parser.read_events():
                event, element = cast("tuple[str, ET.Element[str]]", item)
                if event == "start":
                    depth += 1
                    element_count += 1
                    if root is None:
                        root = element
                    _validate_xml_bounds(depth, element_count)
                else:
                    depth -= 1
        parser.close()
    except _DocumentError:
        raise
    except ET.ParseError as err:
        raise _DocumentError("invalid_xml") from err
    if root is None or depth != 0:
        raise _DocumentError("invalid_xml")
    return root


def _resolve_service_url(base_url: str, reference: str, *, expected_host: str) -> str:
    """Resolve a descriptor URL and require it to remain on the root origin."""
    if any(ord(character) < _MIN_CONTROL_CODE for character in reference):
        raise _DocumentError("unsafe_url")
    resolved = urljoin(base_url, reference)
    base = _split_url(base_url)
    candidate = _split_url(resolved)
    if (
        candidate.scheme not in _ALLOWED_SCHEMES
        or candidate.scheme != base.scheme
        or _normalized_url_host(candidate) != expected_host
        or _normalized_url_host(candidate) != _normalized_url_host(base)
        or _explicit_port(candidate) != _explicit_port(base)
        or candidate.username is not None
        or candidate.password is not None
        or candidate.query
        or candidate.fragment
        or not candidate.path.startswith("/")
    ):
        raise _DocumentError("unsafe_url")
    return urlunsplit(candidate)


def _optional_service_url(
    base_url: str,
    reference: str | None,
    *,
    expected_host: str,
) -> str | None:
    """Resolve an optional control or event URL under the same origin."""
    if not reference:
        return None
    return _resolve_service_url(base_url, reference, expected_host=expected_host)


def _validate_root_url(url: str, *, expected_host: str) -> str:
    """Validate an explicit-port same-host HTTP(S) root descriptor URL."""
    candidate = _split_url(url)
    if (
        candidate.scheme not in _ALLOWED_SCHEMES
        or _normalized_url_host(candidate) != expected_host
        or candidate.username is not None
        or candidate.password is not None
        or candidate.query
        or candidate.fragment
        or not candidate.path.startswith("/")
    ):
        raise DiscoveryError("Root descriptor URLs must be same-host HTTP(S) URLs")
    try:
        _explicit_port(candidate)
    except _DocumentError as err:
        raise DiscoveryError("Root descriptor URLs require an explicit port") from err
    return urlunsplit(candidate)


def _normalize_host(host: str) -> tuple[str, str]:
    """Return comparison and URL-rendering forms for a host-only value."""
    value = host.strip()
    if not value or any(
        character.isspace() or character in "/?#@" for character in value
    ):
        raise DiscoveryError("--host must contain only a hostname or IP address")
    try:
        parsed = urlsplit(f"http://{value}")
        parsed_port = parsed.port
    except ValueError as err:
        raise DiscoveryError("IPv6 addresses must be enclosed in brackets") from err
    if parsed.hostname is None or parsed_port is not None:
        raise DiscoveryError("--host must not include a port")
    normalized = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    rendered = f"[{normalized}]" if ":" in normalized else normalized
    return normalized, rendered


def _default_root_urls(rendered_host: str) -> tuple[str, ...]:
    """Return the fixed, bounded family-context root candidates."""
    return tuple(
        f"{scheme}://{rendered_host}:{port}{path}"
        for scheme, port, path in _DEFAULT_ROOTS
    )


def _split_url(url: str) -> SplitResult:
    """Split a URL while mapping malformed port syntax to a safe error."""
    try:
        result = urlsplit(url)
        _ = result.port
    except ValueError as err:
        raise _DocumentError("unsafe_url") from err
    return result


def _explicit_port(parts: SplitResult) -> int:
    """Return an explicit, valid TCP port or reject the URL."""
    try:
        port = parts.port
    except ValueError as err:
        raise _DocumentError("unsafe_url") from err
    if port is None or not 1 <= port <= _MAX_TCP_PORT:
        raise _DocumentError("unsafe_url")
    return port


def _normalized_url_host(parts: SplitResult) -> str:
    """Normalize a URL host for same-host comparisons."""
    if parts.hostname is None:
        return ""
    return parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()


def _locator(url: str) -> _Locator:
    """Describe a URL without retaining its hostname, query, or fragment."""
    parts = _split_url(url)
    return {
        "path": parts.path,
        "port": _explicit_port(parts),
        "scheme": parts.scheme,
    }


def _path_or_none(url: str | None) -> str | None:
    """Return only the safe path portion of an optional URL."""
    return _locator(url)["path"] if url else None


def _clean_text(value: str | None) -> str | None:
    """Return one bounded XML token without control characters."""
    if value is None:
        return None
    result = value.strip()
    if not result:
        return None
    if len(result) > _MAX_TOKEN_LENGTH or any(
        ord(character) < _MIN_CONTROL_CODE for character in result
    ):
        raise _DocumentError("invalid_descriptor_token")
    return result


def _local_name(tag: str) -> str:
    """Return an XML local name without retaining namespaces in output."""
    return tag.rsplit("}", maxsplit=1)[-1]


def _direct_children(element: ET.Element, local_name: str) -> list[ET.Element]:
    """Return direct children matching one namespace-independent local name."""
    return [child for child in element if _local_name(child.tag) == local_name]


def _direct_child_text(element: ET.Element, local_name: str) -> str | None:
    """Return the first direct child text for a local name."""
    for child in _direct_children(element, local_name):
        return _clean_text(child.text)
    return None


def _direct_descendants(element: ET.Element, local_name: str) -> list[ET.Element]:
    """Return matching descendants below direct container elements."""
    return [
        descendant
        for child in element
        for descendant in child
        if _local_name(descendant.tag) == local_name
    ]


def _evented(element: ET.Element) -> bool:
    """Parse the UPnP sendEvents spelling without retaining other attributes."""
    raw_value = next(
        (
            value
            for name, value in element.attrib.items()
            if _local_name(name) in {"sendEvents", "sendEventsAttribute"}
        ),
        "no",
    )
    return raw_value.strip().lower() in {"1", "true", "yes"}


def _sha256(body: bytes) -> str:
    """Return a deterministic integrity digest for one sanitized source record."""
    return hashlib.sha256(body).hexdigest()


def _validate_response_status(status: int) -> None:
    """Reject redirects and all non-success statuses before reading a body."""
    if _HTTP_REDIRECT_MIN <= status < _HTTP_CLIENT_ERROR_MIN:
        raise _DocumentError("redirect_rejected", status=status)
    if not _HTTP_SUCCESS_MIN <= status < _HTTP_REDIRECT_MIN:
        raise _DocumentError("http_status", status=status)


def _validate_content_length(content_length: int | None, *, status: int) -> None:
    """Reject a declared body length above the hard descriptor limit."""
    if content_length is not None and content_length > _MAX_BODY_BYTES:
        raise _DocumentError("response_too_large", status=status)


def _extend_bounded_body(body: bytearray, chunk: bytes, *, status: int) -> None:
    """Append one response chunk while preserving the hard body limit."""
    body.extend(chunk)
    if len(body) > _MAX_BODY_BYTES:
        raise _DocumentError("response_too_large", status=status)


def _validate_xml_bounds(depth: int, element_count: int) -> None:
    """Reject XML structures that exceed the fixed parser bounds."""
    if depth > _MAX_XML_DEPTH:
        raise _DocumentError("xml_depth_exceeded")
    if element_count > _MAX_XML_ELEMENTS:
        raise _DocumentError("xml_element_limit_exceeded")


def _required_service_fields(
    service_type: str | None,
    service_id: str | None,
    scpd_reference: str | None,
) -> tuple[str, str, str]:
    """Require the three fields needed for a non-executable advertisement."""
    if not service_type or not service_id or not scpd_reference:
        raise _DocumentError("incomplete_service_advertisement")
    return service_type, service_id, scpd_reference


def _reference_path(reference: str | None, *, fallback: str) -> str:
    """Return only a path from an unsafe reference for sanitized diagnostics."""
    if reference:
        try:
            path = urlsplit(reference).path
        except ValueError:
            path = ""
        if path.startswith("/"):
            return path
    return _locator(fallback)["path"]


def _error(stage: str, path: str, err: _DocumentError) -> dict[str, object]:
    """Build a sanitized error that cannot expose a host or response body."""
    result: dict[str, object] = {
        "path": path,
        "reason": err.reason,
        "stage": stage,
    }
    if err.status is not None:
        result["response_status"] = err.status
    return result


def _mapping_sort_key(value: Mapping[str, object]) -> str:
    """Return a stable key for sanitized output mappings."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _service_sort_key(value: Mapping[str, object]) -> tuple[str, ...]:
    """Return a stable service order independent of XML document ordering."""
    return (
        str(value.get("root_path", "")),
        str(value.get("service_type", "")),
        str(value.get("service_id", "")),
        str(value.get("scpd_path", "")),
    )


def _url_sort_key(url: str) -> tuple[str, int, str]:
    """Return a stable URL order without using its host."""
    locator = _locator(url)
    return (
        str(locator["scheme"]),
        int(locator["port"]),
        str(locator["path"]),
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect advertised UPnP/TR-064 device and SCPD descriptors using "
            "bounded, unauthenticated GET requests only."
        )
    )
    parser.add_argument("--host", required=True, help="Router hostname or IP only")
    parser.add_argument(
        "--root-url",
        action="append",
        default=None,
        help=(
            "Explicit-port same-host root descriptor URL; repeat for multiple "
            "candidates. Supplying any value replaces the bounded defaults."
        ),
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Allow a router-local self-signed HTTPS certificate.",
    )
    parser.add_argument("--out", type=Path, help="Write sanitized JSON to this file")
    return parser.parse_args()


async def _async_main(args: argparse.Namespace) -> dict[str, object]:
    """Run discovery with a stateless, proxy-free HTTP session."""
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=timeout,
        trust_env=False,
    ) as session:
        fetcher = AiohttpDocumentFetcher(
            session,
            verify_ssl=not args.no_verify_ssl,
        )
        return await discover_service_descriptors(
            args.host,
            fetcher=fetcher,
            root_urls=args.root_url,
        )


def main() -> None:
    """Print or save a deterministic, sanitized advertised-service inventory."""
    args = _arguments()
    try:
        result = asyncio.run(_async_main(args))
    except (DiscoveryError, _DocumentError) as err:
        message = f"Discovery failed safely: {type(err).__name__}: {err}"
        raise SystemExit(message) from err

    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        sys.stdout.write(payload)
        return
    descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(payload)


if __name__ == "__main__":
    main()
