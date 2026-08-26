"""Deterministic, data-only packaging for reusable Nightshift extensions.

Inspection never imports, executes, or extracts package payloads.  Installation
is owned separately by :mod:`extension_registry` and consumes only a successful
inspection result.
"""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path
from typing import Any

from extension_protocol import (
    CAPABILITIES,
    EVENTS,
    ProtocolError,
    canonical,
    digest,
    identifier,
    safe_relative,
    semantic_version,
    sha256_bytes,
)

PACKAGE_SCHEMA_VERSION = "1.0.0"
CATALOGUE_SCHEMA_VERSION = "1.0.0"
PACKAGE_METADATA = "nightshift-extension-package.json"
PACKAGE_FIELDS = {
    "schema_version",
    "id",
    "version",
    "protocol_range",
    "manifest",
    "inventory",
    "migrations",
    "catalogue",
}
INVENTORY_FIELDS = {"path", "sha256", "size", "role"}
ROLES = frozenset(
    {"manifest", "payload", "schema", "documentation", "test", "license", "provenance"}
)
REQUIRED_PATHS = frozenset(
    {
        "manifest.json",
        "schemas/input.json",
        "schemas/output.json",
        "docs/README.md",
        "LICENSE",
        "PROVENANCE.json",
    }
)
MAX_PACKAGE_FILES = 2048
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
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


class PackageError(ValueError):
    """A package or catalogue failed its closed validation contract."""


def _role(path: str, entry_point: str) -> str:
    if path == "manifest.json":
        return "manifest"
    if path == "LICENSE":
        return "license"
    if path == "PROVENANCE.json":
        return "provenance"
    if path == entry_point or path.startswith("payload/"):
        return "payload"
    if path.startswith("schemas/"):
        return "schema"
    if path.startswith("docs/"):
        return "documentation"
    if path.startswith("tests/"):
        return "test"
    raise PackageError(f"unclassified package file: {path}")


def _manifest(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("invalid manifest JSON") from exc
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise PackageError("manifest schema is closed")
    try:
        identifier(value["id"], "extension id")
        for name in (
            "extension_version",
            "protocol_version",
            "input_schema_version",
            "output_schema_version",
        ):
            semantic_version(value[name], name)
        entry_point = safe_relative(value["entry_point"], "entry point")
    except ProtocolError as exc:
        raise PackageError(str(exc)) from exc
    if not isinstance(value["events"], list) or len(value["events"]) != len(
        set(value["events"])
    ):
        raise PackageError("manifest events must be unique")
    if set(value["events"]) - EVENTS:
        raise PackageError("manifest declares unstable event")
    if not isinstance(value["capabilities"], list) or len(value["capabilities"]) != len(
        set(value["capabilities"])
    ):
        raise PackageError("manifest capabilities must be unique")
    if set(value["capabilities"]) - CAPABILITIES:
        raise PackageError("manifest declares unknown capability")
    declared = dict(value)
    integrity = declared.pop("integrity")
    if integrity != digest(declared):
        raise PackageError("manifest integrity mismatch")
    value["entry_point"] = entry_point
    return value


def _regular_nonexecutable(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    if info.create_system != 3:
        return False
    return stat.S_ISREG(mode) and not (mode & 0o111)


def _load_archive(path: Path) -> tuple[dict[str, bytes], str]:
    try:
        raw = Path(path).read_bytes()
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_PACKAGE_FILES:
                raise PackageError("package contains too many files")
            if (
                any(item.file_size > MAX_MEMBER_BYTES for item in infos)
                or sum(item.file_size for item in infos) > MAX_PACKAGE_BYTES
            ):
                raise PackageError("package exceeds inspection size limits")
            if len({item.filename for item in infos}) != len(infos):
                raise PackageError("duplicate package path")
            files: dict[str, bytes] = {}
            for info in infos:
                try:
                    name = safe_relative(info.filename, "package path")
                except ProtocolError as exc:
                    raise PackageError(str(exc)) from exc
                if info.is_dir() or not _regular_nonexecutable(info):
                    raise PackageError(
                        "package members must be regular non-executable files"
                    )
                files[name] = archive.read(info)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError("invalid extension archive") from exc
    return files, sha256_bytes(raw)


def inspect_package(path: Path) -> dict[str, Any]:
    """Validate an archive using bytes and schemas only; never extract or execute."""
    files, package_sha = _load_archive(Path(path))
    if PACKAGE_METADATA not in files:
        raise PackageError("package metadata missing")
    try:
        metadata = json.loads(files[PACKAGE_METADATA].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("invalid package metadata") from exc
    if not isinstance(metadata, dict) or set(metadata) != PACKAGE_FIELDS:
        raise PackageError("package metadata schema is closed")
    if metadata["schema_version"] != PACKAGE_SCHEMA_VERSION:
        raise PackageError("unsupported package schema")
    try:
        identifier(metadata["id"], "package id")
        semantic_version(metadata["version"], "package version")
    except ProtocolError as exc:
        raise PackageError(str(exc)) from exc
    protocol_range = metadata["protocol_range"]
    if not isinstance(protocol_range, dict) or set(protocol_range) != {"min", "max"}:
        raise PackageError("protocol range schema is closed")
    try:
        semantic_version(protocol_range["min"], "minimum protocol")
        semantic_version(protocol_range["max"], "maximum protocol")
    except ProtocolError as exc:
        raise PackageError(str(exc)) from exc
    if _version(protocol_range["min"]) > _version(protocol_range["max"]):
        raise PackageError("protocol range is inverted")
    manifest_path = metadata["manifest"]
    if manifest_path != "manifest.json":
        raise PackageError("package manifest must be manifest.json")
    manifest = _manifest(files.get(manifest_path, b""))
    if (
        manifest["id"] != metadata["id"]
        or manifest["extension_version"] != metadata["version"]
    ):
        raise PackageError("package identity does not match manifest")
    inventory = metadata["inventory"]
    if not isinstance(inventory, list) or not inventory:
        raise PackageError("package inventory missing")
    seen: set[str] = set()
    clean_inventory: list[dict[str, Any]] = []
    for item in inventory:
        if not isinstance(item, dict) or set(item) != INVENTORY_FIELDS:
            raise PackageError("inventory schema is closed")
        try:
            name = safe_relative(item["path"], "inventory path")
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc
        if name in seen or name == PACKAGE_METADATA:
            raise PackageError("duplicate or self-referential inventory path")
        seen.add(name)
        data = files.get(name)
        if (
            data is None
            or item["sha256"] != sha256_bytes(data)
            or item["size"] != len(data)
        ):
            raise PackageError("inventory digest or size mismatch")
        expected_role = _role(name, manifest["entry_point"])
        if item["role"] not in ROLES or item["role"] != expected_role:
            raise PackageError("inventory role mismatch")
        clean_inventory.append(dict(item))
    if seen != set(files) - {PACKAGE_METADATA}:
        raise PackageError("inventory is not complete")
    if not REQUIRED_PATHS <= seen or manifest["entry_point"] not in seen:
        raise PackageError("required package content missing")
    if manifest["entry_point_sha256"] != sha256_bytes(files[manifest["entry_point"]]):
        raise PackageError("entry point digest mismatch")
    for schema_path in ("schemas/input.json", "schemas/output.json", "PROVENANCE.json"):
        try:
            parsed = json.loads(files[schema_path].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"invalid JSON document: {schema_path}") from exc
        if not isinstance(parsed, dict):
            raise PackageError(f"JSON document must be an object: {schema_path}")
    migrations = metadata["migrations"]
    if not isinstance(migrations, list) or len(migrations) != len(set(migrations)):
        raise PackageError("migrations must be a unique version list")
    try:
        for version in migrations:
            semantic_version(version, "migration version")
    except ProtocolError as exc:
        raise PackageError(str(exc)) from exc
    catalogue = metadata["catalogue"]
    if catalogue is not None:
        _catalogue_entry(catalogue, optional_fields=())
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "id": metadata["id"],
        "version": metadata["version"],
        "protocol_range": dict(protocol_range),
        "events": sorted(manifest["events"]),
        "capabilities": sorted(manifest["capabilities"]),
        "entry_point": manifest["entry_point"],
        "entry_point_sha256": manifest["entry_point_sha256"],
        "manifest_integrity": manifest["integrity"],
        "files": sorted(clean_inventory, key=lambda item: item["path"]),
        "migrations": list(migrations),
        "catalogue": catalogue,
        "package_sha256": package_sha,
        "inventory_digest": digest(clean_inventory),
    }


def _version(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def build_package(
    source: Path,
    output: Path,
    *,
    protocol_min: str,
    protocol_max: str,
    migrations: list[str] | None = None,
    catalogue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build byte-for-byte deterministic package bytes from a closed source tree."""
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise PackageError("package source must be a regular directory")
    content: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise PackageError("package source may not contain symlinks")
        if path.is_dir():
            continue
        relative = path.relative_to(source).as_posix()
        try:
            safe_relative(relative)
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc
        if path.stat().st_mode & 0o111:
            raise PackageError("source members must be non-executable during packaging")
        content[relative] = path.read_bytes()
    manifest = _manifest(content.get("manifest.json", b""))
    inventory = [
        {
            "path": name,
            "sha256": sha256_bytes(data),
            "size": len(data),
            "role": _role(name, manifest["entry_point"]),
        }
        for name, data in sorted(content.items())
    ]
    package_catalogue = None
    if catalogue is not None:
        package_catalogue = {
            **catalogue,
            "id": manifest["id"],
            "version": manifest["extension_version"],
        }
    metadata = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "id": manifest["id"],
        "version": manifest["extension_version"],
        "protocol_range": {"min": protocol_min, "max": protocol_max},
        "manifest": "manifest.json",
        "inventory": inventory,
        "migrations": migrations or [],
        "catalogue": package_catalogue,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info(PACKAGE_METADATA), canonical(metadata))
        for name, data in sorted(content.items()):
            archive.writestr(_zip_info(name), data)
    return inspect_package(output)


def _catalogue_entry(value: Any, *, optional_fields: tuple[str, ...]) -> dict[str, Any]:
    required = {"id", "version", "summary"}
    allowed = required | set(optional_fields) | {"schema_version", "tags"}
    if not isinstance(value, dict) or not required <= set(value):
        raise PackageError("catalogue entry is incomplete")
    unknown = set(value) - allowed
    if unknown:
        raise PackageError("unknown catalogue fields: " + ", ".join(sorted(unknown)))
    try:
        identifier(value["id"], "catalogue id")
        semantic_version(value["version"], "catalogue version")
    except ProtocolError as exc:
        raise PackageError(str(exc)) from exc
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        raise PackageError("catalogue summary is required")
    if "tags" in value and (
        not isinstance(value["tags"], list)
        or not all(isinstance(x, str) for x in value["tags"])
    ):
        raise PackageError("catalogue tags must be strings")
    return {name: value[name] for name in sorted(required | ({"tags"} & set(value)))}


def inspect_catalogue(
    value: Any, *, optional_fields: list[str] | None = None
) -> list[dict[str, Any]]:
    """Validate informational catalogue data without touching installation state."""
    if not isinstance(value, dict) or set(value) not in (
        {"schema_version", "entries"},
        {"schema_version", "optional_fields", "entries"},
    ):
        raise PackageError("catalogue schema is closed")
    if value["schema_version"] != CATALOGUE_SCHEMA_VERSION or not isinstance(
        value["entries"], list
    ):
        raise PackageError("unsupported catalogue schema")
    declared_optional = value.get("optional_fields", [])
    if not isinstance(declared_optional, list) or not all(
        isinstance(item, str) for item in declared_optional
    ):
        raise PackageError("catalogue optional_fields must be strings")
    # The argument is retained for API compatibility but cannot grant fields the
    # catalogue schema itself did not mark optional.
    requested = set(optional_fields or declared_optional)
    optional = tuple(item for item in declared_optional if item in requested)
    return [
        _catalogue_entry(item, optional_fields=optional) for item in value["entries"]
    ]
