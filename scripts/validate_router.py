"""Run a read-only, privacy-safe validation against a Speedport router."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final, cast

import aiohttp

from custom_components.speedport_smart.api import (
    SpeedportAuthenticationError,
    SpeedportClient,
    SpeedportError,
    SpeedportProtocolError,
    SpeedportUnsupportedError,
)
from custom_components.speedport_smart.coordinator import PollGroup
from custom_components.speedport_smart.hub import SpeedportHub
from custom_components.speedport_smart.normalizers import (
    normalize_feature_payload,
    normalize_status_payload,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_MIN_SAMPLES: Final = 2
_MIN_INTERVAL: Final = 1.0
_MAX_INTERVAL: Final = 30.0


class _ValidationHass:
    """Minimum event-loop surface used by the hub's read-only update path."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.data: dict[str, Any] = {}

    def verify_event_loop_thread(self, _action: str) -> None:
        """Accept calls made on the validator's owning asyncio thread."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate public status, WAN counters, DSL telemetry, and optional "
            "authenticated read endpoints without changing router state."
        )
    )
    parser.add_argument("--host", default="speedport.ip")
    parser.add_argument("--https", action="store_true")
    parser.add_argument("--verify-ssl", action="store_true")
    parser.add_argument(
        "--authenticated",
        action="store_true",
        help="Prompt securely for the router device password.",
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=5.0)
    return parser.parse_args()


async def async_validate_router(
    args: argparse.Namespace,
    *,
    password: str | None = None,
) -> dict[str, Any]:
    """Run the complete read-only validator with an optional memory-only password."""
    if args.samples < _MIN_SAMPLES:
        raise ValueError("--samples must be at least 2")
    if not _MIN_INTERVAL <= args.interval <= _MAX_INTERVAL:
        raise ValueError("--interval must be between 1 and 30 seconds")

    if args.authenticated and password is None:
        password = getpass.getpass("Router device password (input is hidden): ")
    if args.authenticated and not password:
        raise ValueError("Authenticated validation requires a non-empty password")

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    cookie_jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(
        connector=connector,
        cookie_jar=cookie_jar,
    ) as session:
        client = SpeedportClient(
            session,
            args.host,
            password=password,
            use_https=args.https,
            verify_ssl=args.verify_ssl,
        )
        stage = "router capability discovery"
        try:
            report = await client.setup()
            if args.authenticated and not report.authenticated_json:
                raise SpeedportAuthenticationError(
                    "Router did not establish an authenticated read session"
                )
            stage = "public status read"
            status = await client.get_status()
            normalized_status, inferred = normalize_status_payload(status)

            result: dict[str, Any] = {
                "read_only": True,
                "router": {
                    "model": status.info.model,
                    "firmware": status.info.firmware,
                },
                "capabilities": sorted(report.feature_endpoints),
                "inferred_status_capabilities": sorted(inferred),
                "authenticated": report.authenticated_json,
                "unsupported_or_failed_families": sorted(report.failures),
                "normalized_status_paths": _leaf_paths(normalized_status),
            }

            if report.wan_counters:
                samples = []
                for index in range(args.samples):
                    stage = f"WAN counter sample {index + 1}"
                    samples.append(await client.get_wan_counters())
                    if index + 1 < args.samples:
                        await asyncio.sleep(args.interval)
                first, last = samples[0], samples[-1]
                elapsed = (last.sampled_at - first.sampled_at).total_seconds()
                received_delta = last.bytes_received - first.bytes_received
                sent_delta = last.bytes_sent - first.bytes_sent
                result["wan"] = {
                    "interface_index": last.interface.index,
                    "interface_alias": last.interface.alias,
                    "interface_name": last.interface.name,
                    "interface_status": last.interface.status,
                    "bytes_received": last.bytes_received,
                    "bytes_sent": last.bytes_sent,
                    "download_rate_bps": (
                        received_delta * 8 / elapsed
                        if elapsed > 0 and received_delta >= 0
                        else None
                    ),
                    "upload_rate_bps": (
                        sent_delta * 8 / elapsed
                        if elapsed > 0 and sent_delta >= 0
                        else None
                    ),
                    "packets_received": last.packets_received,
                    "packets_sent": last.packets_sent,
                    "errors_received": last.errors_received,
                    "errors_sent": last.errors_sent,
                    "discard_packets_received": last.discard_packets_received,
                    "discard_packets_sent": last.discard_packets_sent,
                    "sample_window_seconds": elapsed,
                }

            stage = "DSL telemetry read"
            try:
                dsl = await client.get_dsl_metrics()
            except SpeedportUnsupportedError:
                result["dsl"] = {"supported": False}
            else:
                result["dsl"] = {"supported": True, **asdict(dsl)}
                result["dsl"].pop("sampled_at", None)

            feature_paths: dict[str, list[str]] = {}
            endpoint_cache: dict[tuple[str, bool, str | None], Mapping[str, Any]] = {}
            for family, capability in report.feature_endpoints.items():
                if capability.endpoint == "data/Status.json":
                    continue
                cache_key = (
                    capability.endpoint,
                    capability.authenticated,
                    capability.referer,
                )
                if cache_key not in endpoint_cache:
                    stage = f"feature read: {family}"
                    endpoint_cache[cache_key] = await client.get_json(
                        capability.endpoint,
                        authenticated=capability.authenticated,
                        referer=capability.referer,
                    )
                normalized = normalize_feature_payload(
                    family,
                    endpoint_cache[cache_key],
                )
                feature_paths[family] = _leaf_paths(normalized)
            result["normalized_feature_paths"] = feature_paths

            hub = SpeedportHub(
                cast("HomeAssistant", _ValidationHass()),
                client,
                fallback_identifier="read-only-validation",
            )
            stage = "Home Assistant hub setup"
            await hub.async_setup()
            stage = "Home Assistant fast update 1"
            await hub.async_update_group(PollGroup.FAST)
            await asyncio.sleep(args.interval)
            stage = "Home Assistant fast update 2"
            await hub.async_update_group(PollGroup.FAST)
            stage = "Home Assistant normal update"
            await hub.async_update_group(PollGroup.NORMAL)
            stage = "Home Assistant slow update"
            await hub.async_update_group(PollGroup.SLOW)
            result["hub"] = {
                "capabilities": sorted(hub.capabilities),
                "normalized_paths": _leaf_paths(hub.data),
                "download_rate_bps": hub.get("wan.download_rate_bps"),
                "upload_rate_bps": hub.get("wan.upload_rate_bps"),
                "dsl_downstream_bps": hub.get("dsl.downstream_bps"),
                "dsl_upstream_bps": hub.get("dsl.upstream_bps"),
                "dsl_snr_downstream_db": hub.get("dsl.snr_downstream_db"),
                "dsl_snr_upstream_db": hub.get("dsl.snr_upstream_db"),
            }
        except SpeedportError as err:
            raise SpeedportProtocolError(
                f"Read-only validation failed during {stage}: "
                f"{type(err).__name__}: {err}"
            ) from err
        else:
            return result
        finally:
            await client.close()


def _leaf_paths(value: Any, prefix: str = "") -> list[str]:
    """Return structure only, never router values or stable identifiers."""
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_leaf_paths(item, child))
        return sorted(set(paths))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        child = f"{prefix}[]"
        paths = [child]
        for item in value:
            paths.extend(_leaf_paths(item, child))
        return sorted(set(paths))
    return [prefix] if prefix else []


def main() -> None:
    """Run validation and print sanitized JSON."""
    try:
        result = asyncio.run(async_validate_router(_arguments()))
    except (SpeedportError, ValueError) as err:
        raise SystemExit(f"Validation failed: {type(err).__name__}: {err}") from err
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")


if __name__ == "__main__":
    main()
