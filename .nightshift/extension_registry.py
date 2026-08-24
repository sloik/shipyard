"""Exact two-root discovery and fail-contained extension admission."""

from __future__ import annotations

import ipaddress
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from extension_protocol import (
    CAPABILITIES,
    EVENTS,
    PROTOCOL_VERSION,
    Admission,
    Limits,
    ProtocolError,
    digest,
    identifier,
    resolve_beneath,
    semantic_version,
    sha256_bytes,
)

SOURCES = frozenset({"project", "user"})
MANIFEST_FIELDS = {
    "id",
    "extension_version",
    "protocol_version",
    "entry_point",
    "entry_point_sha256",
    "events",
    "capabilities",
    "input_schema_version",
    "output_schema_version",
    "integrity",
}
REQUEST_FIELDS = {
    "id",
    "source",
    "subscriptions",
    "capabilities",
    "limits",
    "network_endpoint",
}


def _unique_strings(
    value: Any, *, allowed: frozenset[str], label: str, nonempty: bool = False
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(x, str) for x in value)
    ):
        raise ProtocolError(f"{label} must be a string list")
    if len(value) != len(set(value)):
        raise ProtocolError(f"duplicate {label}")
    if set(value) - allowed:
        raise ProtocolError(f"undeclared {label}")
    return tuple(value)


def parse_manifest(path: Path, source: str, root: Path) -> dict[str, Any]:
    if source not in SOURCES:
        raise ProtocolError("unknown manifest source")
    if (
        path.is_symlink()
        or not path.is_file()
        or path.parent.resolve() != root.resolve()
    ):
        raise ProtocolError(
            "manifest must be a direct regular child of its declared root"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid manifest JSON") from exc
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise ProtocolError("manifest schema is closed")
    identifier(value["id"], "extension id")
    semantic_version(value["extension_version"], "extension version")
    semantic_version(value["protocol_version"], "protocol version")
    semantic_version(value["input_schema_version"], "input schema version")
    semantic_version(value["output_schema_version"], "output schema version")
    if value["protocol_version"].split(".")[0] != PROTOCOL_VERSION.split(".")[0]:
        raise ProtocolError("incompatible protocol major")
    events = _unique_strings(
        value["events"], allowed=EVENTS, label="manifest events", nonempty=True
    )
    capabilities = _unique_strings(
        value["capabilities"], allowed=CAPABILITIES, label="manifest capabilities"
    )
    declared = dict(value)
    integrity = declared.pop("integrity")
    if not isinstance(integrity, str) or integrity != digest(declared):
        raise ProtocolError("manifest integrity mismatch")
    executable = resolve_beneath(root, value["entry_point"])
    if not executable.is_file() or executable.is_symlink():
        raise ProtocolError("entry point unavailable")
    executable_digest = sha256_bytes(executable.read_bytes())
    if executable_digest != value["entry_point_sha256"]:
        raise ProtocolError("entry point digest mismatch")
    return {
        **value,
        "events": events,
        "capabilities": capabilities,
        "source": source,
        "manifest_path": path,
        "executable": executable,
        "executable_digest": executable_digest,
    }


class ExtensionRegistry:
    def __init__(self, project_root: Path, user_root: Path):
        self.roots = {"project": Path(project_root), "user": Path(user_root)}

    def discover(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        found: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        for source, root in self.roots.items():
            if not root.exists():
                continue
            if root.is_symlink() or not root.is_dir():
                rejected.append(
                    {"source": source, "file": "root", "reason": "unsafe-root"}
                )
                continue
            for path in sorted(root.iterdir()):
                if path.suffix != ".json":
                    continue
                try:
                    found.append(parse_manifest(path, source, root))
                except ProtocolError as exc:
                    # One unrelated malformed manifest never aborts official dispatch.
                    rejected.append(
                        {"source": source, "file": path.name, "reason": str(exc)}
                    )
        return found, rejected

    def admit(
        self, config: Mapping[str, Any], *, sandbox_backend: Any
    ) -> tuple[list[Admission], list[dict[str, str]]]:
        enabled = config.get("extensions", [])
        if enabled is None:
            enabled = []
        if not isinstance(enabled, list):
            return [], [{"id": "unknown", "reason": "extensions config must be a list"}]
        manifests, rejected = self.discover()
        failures = [{"id": item["file"], "reason": item["reason"]} for item in rejected]
        admissions: list[Admission] = []
        seen_requests: set[tuple[str, str]] = set()
        request_counts = Counter(
            (item.get("id"), item.get("source"))
            for item in enabled
            if isinstance(item, dict)
        )
        for raw in enabled:
            extension_id = (
                raw.get("id", "unknown") if isinstance(raw, dict) else "unknown"
            )
            try:
                if not isinstance(raw, dict) or set(raw) != REQUEST_FIELDS:
                    raise ProtocolError("enablement schema is closed")
                extension_id = identifier(raw["id"], "extension id")
                source = raw["source"]
                if source not in SOURCES:
                    raise ProtocolError("ambiguous source")
                key = (extension_id, source)
                if request_counts[key] > 1:
                    raise ProtocolError("duplicate enablement")
                if key in seen_requests:
                    raise ProtocolError("duplicate enablement")
                seen_requests.add(key)
                matches = [
                    m
                    for m in manifests
                    if m["id"] == extension_id and m["source"] == source
                ]
                if len(matches) != 1:
                    raise ProtocolError("identity unavailable or ambiguous")
                manifest = matches[0]
                subscriptions = _unique_strings(
                    raw["subscriptions"],
                    allowed=EVENTS,
                    label="subscriptions",
                    nonempty=True,
                )
                capabilities = _unique_strings(
                    raw["capabilities"], allowed=CAPABILITIES, label="capabilities"
                )
                if set(subscriptions) - set(manifest["events"]):
                    raise ProtocolError("subscription not declared by manifest")
                if set(capabilities) - set(manifest["capabilities"]):
                    raise ProtocolError("capability not declared by manifest")
                limits = Limits.parse(raw["limits"])
                endpoint = raw["network_endpoint"]
                if "network.loopback" in capabilities:
                    try:
                        host, port_text = endpoint.rsplit(":", 1)
                        address, port = ipaddress.ip_address(host), int(port_text)
                    except (AttributeError, ValueError) as exc:
                        raise ProtocolError(
                            "loopback endpoint must be numeric host:port"
                        ) from exc
                    if not address.is_loopback or port <= 0 or port > 65535:
                        raise ProtocolError(
                            "loopback endpoint must be private numeric loopback"
                        )
                elif endpoint is not None:
                    raise ProtocolError("endpoint requires network.loopback")
                sandbox_backend.require(capabilities=capabilities, endpoint=endpoint)
                material = {
                    "id": extension_id,
                    "source": source,
                    "subscriptions": subscriptions,
                    "capabilities": capabilities,
                    "limits": limits.as_dict(),
                    "manifest_integrity": manifest["integrity"],
                    "executable_sha256": manifest["executable_digest"],
                    "network_endpoint": endpoint,
                }
                admissions.append(
                    Admission(
                        extension_id,
                        source,
                        subscriptions,
                        capabilities,
                        limits,
                        digest(material),
                        manifest["executable"],
                        manifest["executable_digest"],
                        endpoint,
                    )
                )
            except (ProtocolError, TypeError) as exc:
                failures.append({"id": str(extension_id), "reason": str(exc)})
        return admissions, failures
