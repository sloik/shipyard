"""Exact two-root discovery and fail-contained extension admission."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from extension_package import PackageError, inspect_package
from extension_protocol import (
    CAPABILITIES,
    EVENTS,
    PROTOCOL_VERSION,
    Admission,
    Limits,
    ProtocolError,
    atomic_json,
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
    def __init__(
        self, project_root: Path, user_root: Path, *, project_id: str | None = None,
        experiment_observer: Any | None = None,
    ):
        self.roots = {"project": Path(project_root), "user": Path(user_root)}
        self.project_id = (
            identifier(project_id, "project id") if project_id is not None else None
        )
        self.experiment_observer = experiment_observer
        self.capture_receipts: list[dict[str, Any]] = []

    def _observe_runtime(
        self, event_name: str, *, operation_id: str,
        correlations: Mapping[str, str], outcome: str, payload: Mapping[str, Any]
    ) -> None:
        if self.experiment_observer is None:
            return
        try:
            receipt = self.experiment_observer.emit(
                event_name, operation_id=operation_id, correlations=correlations,
                outcome=outcome, payload=payload, source_class="passive",
            )
            self.capture_receipts.append({"event": event_name, **dict(receipt)})
        except Exception:
            self.capture_receipts.append({"event": event_name, "status": "capture_failed"})

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
                if path.name == "install-ledger.json":
                    continue
                try:
                    found.append(parse_manifest(path, source, root))
                except ProtocolError as exc:
                    # One unrelated malformed manifest never aborts official dispatch.
                    rejected.append(
                        {"source": source, "file": path.name, "reason": str(exc)}
                    )
            ledger_path = root / "install-ledger.json"
            if ledger_path.is_file() and not ledger_path.is_symlink():
                try:
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(ledger, dict)
                        or set(ledger) != {"schema_version", "packages"}
                        or ledger["schema_version"] != LEDGER_SCHEMA_VERSION
                        or not isinstance(ledger["packages"], dict)
                    ):
                        raise ProtocolError("unsupported installation ledger")
                    for extension_id, record in sorted(ledger["packages"].items()):
                        identifier(extension_id, "installed extension id")
                        if not isinstance(record, dict):
                            raise ProtocolError("invalid installed package record")
                        version = record["active"]
                        semantic_version(version, "installed extension version")
                        installed_root = resolve_beneath(root, ".installed")
                        package_root = resolve_beneath(
                            installed_root, f"{extension_id}/{version}"
                        )
                        installed = parse_manifest(
                            package_root / "manifest.json", source, package_root
                        )
                        installed["installed_version"] = version
                        installed["approvals"] = record.get("approvals", {})
                        installed["package_digest"] = record["versions"][version]["package_sha256"]
                        installed["plan_digest"] = record.get("active_plan_digest")
                        found.append(installed)
                except (
                    OSError,
                    KeyError,
                    TypeError,
                    json.JSONDecodeError,
                    ProtocolError,
                ) as exc:
                    rejected.append(
                        {
                            "source": source,
                            "file": "install-ledger.json",
                            "reason": str(exc),
                        }
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
            operation_id = str(uuid.uuid4())
            manifest: Mapping[str, Any] | None = None
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
                if "installed_version" in manifest:
                    if self.project_id is None:
                        raise ProtocolError(
                            "installed package requires an explicit project identity"
                        )
                    approval = manifest["approvals"].get(self.project_id)
                    if (
                        not isinstance(approval, dict)
                        or approval.get("enabled") is not True
                        or approval.get("version") != manifest["installed_version"]
                    ):
                        raise ProtocolError(
                            "installed package is disabled pending project approval"
                        )
                    if set(subscriptions) - set(approval.get("events", [])) or set(
                        capabilities
                    ) - set(approval.get("capabilities", [])):
                        raise ProtocolError("enablement exceeds project approval")
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
                admission = Admission(
                        extension_id,
                        source,
                        subscriptions,
                        capabilities,
                        limits,
                        digest(material),
                        manifest["executable"],
                        manifest["executable_digest"],
                        endpoint,
                        manifest.get("package_digest"),
                        manifest.get("plan_digest"),
                    )
                admissions.append(admission)
                correlations = {
                    "subject_digest": digest(extension_id),
                    "admission_digest": admission.config_digest,
                    **({"package_digest": admission.package_digest} if admission.package_digest else {}),
                    **({"plan_digest": admission.plan_digest} if admission.plan_digest else {}),
                }
                self._observe_runtime(
                    "package.runtime.admitted", operation_id=operation_id,
                    correlations=correlations, outcome="succeeded", payload={"admitted": True},
                )
            except (ProtocolError, TypeError) as exc:
                failures.append({"id": str(extension_id), "reason": str(exc)})
                correlations = {"subject_digest": digest(str(extension_id))}
                if isinstance(manifest, Mapping):
                    if isinstance(manifest.get("package_digest"), str):
                        correlations["package_digest"] = manifest["package_digest"]
                    if isinstance(manifest.get("plan_digest"), str):
                        correlations["plan_digest"] = manifest["plan_digest"]
                self._observe_runtime(
                    "package.runtime.refused", operation_id=operation_id,
                    correlations=correlations, outcome="refused",
                    payload={"reason_digest": digest(type(exc).__name__)},
                )
        return admissions, failures


LEDGER_SCHEMA_VERSION = "1.0.0"


def _version_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


class ExtensionPackageManager:
    """Dry-run-first, two-scope extension installation lifecycle.

    The ledger is the activation authority.  Staged or orphaned package bytes are
    never discovered, so interruption exposes either the previous ledger state or
    a completely verified new state.
    """

    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        protocol_version: str,
        *,
        experiment_observer: Any | None = None,
    ):
        self.roots = {"project": Path(project_root), "user": Path(user_root)}
        self.protocol_version = semantic_version(protocol_version, "protocol version")
        self._plans: dict[str, dict[str, Any]] = {}
        self.experiment_observer = experiment_observer
        self.capture_receipts: list[dict[str, Any]] = []

    def _observe(
        self,
        event_name: str,
        *,
        operation_id: str,
        correlations: Mapping[str, str],
        outcome: str,
        payload: Mapping[str, Any],
        source_class: str = "passive",
    ) -> None:
        """Capture private evidence without changing the lifecycle result."""
        if self.experiment_observer is None:
            return
        try:
            receipt = self.experiment_observer.emit(
                event_name,
                operation_id=operation_id,
                correlations=correlations,
                outcome=outcome,
                payload=payload,
                source_class=source_class,
            )
            self.capture_receipts.append({"event": event_name, **dict(receipt)})
        except Exception:
            # The authoritative package operation remains truthful. Consumers
            # inspect this controlled receipt and classify instrumentation_gap;
            # no event is reconstructed from the successful operation later.
            self.capture_receipts.append({"event": event_name, "status": "capture_failed"})

    def _root(self, scope: str) -> Path:
        if scope not in SOURCES:
            raise PackageError("installation scope must be explicit")
        root = self.roots[scope]
        if root.is_symlink():
            raise PackageError("installation root may not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _ledger_path(self, scope: str) -> Path:
        return self._root(scope) / "install-ledger.json"

    def _installed_root(self, scope: str, *, must_exist: bool = False) -> Path:
        try:
            return resolve_beneath(
                self._root(scope), ".installed", must_exist=must_exist
            )
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc

    def _staging_root(self, scope: str) -> Path:
        try:
            return resolve_beneath(self._root(scope), ".staging", must_exist=False)
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc

    def _load(self, scope: str) -> dict[str, Any]:
        path = self._ledger_path(scope)
        if not path.exists():
            return {"schema_version": LEDGER_SCHEMA_VERSION, "packages": {}}
        if path.is_symlink():
            raise PackageError("installation ledger may not be a symlink")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError("invalid installation ledger") from exc
        if not isinstance(value, dict) or set(value) != {"schema_version", "packages"}:
            raise PackageError("installation ledger schema is closed")
        if value["schema_version"] != LEDGER_SCHEMA_VERSION or not isinstance(
            value["packages"], dict
        ):
            raise PackageError("unsupported installation ledger")
        return value

    def _write(self, scope: str, ledger: dict[str, Any]) -> None:
        atomic_json(self._ledger_path(scope), ledger)

    def _compatible(self, inspected: Mapping[str, Any]) -> None:
        current = _version_tuple(self.protocol_version)
        if not (
            _version_tuple(inspected["protocol_range"]["min"])
            <= current
            <= _version_tuple(inspected["protocol_range"]["max"])
        ):
            raise PackageError("package protocol range is incompatible")

    def _remember_plan(self, plan: dict[str, Any], **private: Any) -> dict[str, Any]:
        public = dict(plan)
        public["plan_digest"] = digest(public)
        operation_id = str(uuid.uuid4())
        self._plans[public["plan_digest"]] = {
            "public": public,
            "operation_id": operation_id,
            **private,
        }
        inspected = private.get("inspected")
        correlations = {
            "subject_digest": digest(public["id"]),
            "plan_digest": public["plan_digest"],
        }
        if isinstance(public.get("package_sha256"), str):
            correlations["package_digest"] = public["package_sha256"]
        if isinstance(inspected, Mapping):
            correlations.update({
                "package_digest": inspected["package_sha256"],
                "inventory_digest": inspected["inventory_digest"],
            })
            self._observe(
                "package.inspection.completed",
                operation_id=operation_id,
                correlations=correlations,
                outcome="succeeded",
                payload={"verified": True},
            )
        self._observe(
            "package.plan.created",
            operation_id=operation_id,
            correlations=correlations,
            outcome="eligible",
            payload={
                "operation": public["operation"],
                "scope": public["scope"],
                "authority_expanded": bool(
                    public["capability_changes"]["added_events"]
                    or public["capability_changes"]["added_capabilities"]
                ),
            },
        )
        return public

    def _base_plan(
        self,
        inspected: Mapping[str, Any],
        scope: str,
        old: Mapping[str, Any] | None,
        ledger: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "operation": "install" if old is None else "update",
            "scope": scope,
            "id": inspected["id"],
            "old_version": old.get("active") if old else None,
            "new_version": inspected["version"],
            "files": [item["path"] for item in inspected["files"]],
            "capability_changes": {
                "added_events": sorted(
                    set(inspected["events"]) - set(old.get("events", []) if old else [])
                ),
                "added_capabilities": sorted(
                    set(inspected["capabilities"])
                    - set(old.get("capabilities", []) if old else [])
                ),
                "removed_events": sorted(
                    set(old.get("events", []) if old else []) - set(inspected["events"])
                ),
                "removed_capabilities": sorted(
                    set(old.get("capabilities", []) if old else [])
                    - set(inspected["capabilities"])
                ),
            },
            "actions": ["stage", "verify", "activate", "ledger-write"],
            "package_sha256": inspected["package_sha256"],
            "ledger_digest": digest(ledger),
        }

    def plan_install(self, package: Path, *, scope: str) -> dict[str, Any]:
        self._root(scope)
        inspected = inspect_package(package)
        self._compatible(inspected)
        ledger = self._load(scope)
        if inspected["id"] in ledger["packages"]:
            raise PackageError("package-ID collision; use explicit update")
        return self._remember_plan(
            self._base_plan(inspected, scope, None, ledger),
            package=Path(package),
            inspected=inspected,
        )

    def plan_update(self, package: Path, *, scope: str) -> dict[str, Any]:
        self._root(scope)
        inspected = inspect_package(package)
        self._compatible(inspected)
        ledger = self._load(scope)
        old = ledger["packages"].get(inspected["id"])
        if old is None:
            raise PackageError("package is not installed in the explicit scope")
        if _version_tuple(inspected["version"]) <= _version_tuple(old["active"]):
            raise PackageError("version downgrade or non-monotonic update")
        if old["active"] not in inspected["migrations"]:
            raise PackageError("missing migration for installed version")
        return self._remember_plan(
            self._base_plan(inspected, scope, old, ledger),
            package=Path(package),
            inspected=inspected,
        )

    def plan_rollback(
        self, extension_id: str, *, scope: str, version: str
    ) -> dict[str, Any]:
        identifier(extension_id, "extension id")
        semantic_version(version, "rollback version")
        ledger = self._load(scope)
        record = ledger["packages"].get(extension_id)
        if record is None or version not in record.get("versions", {}):
            raise PackageError("rollback version is unavailable")
        return self._remember_plan(
            {
                "operation": "rollback",
                "scope": scope,
                "id": extension_id,
                "old_version": record["active"],
                "new_version": version,
                "files": [],
                "capability_changes": {
                    "added_events": [],
                    "added_capabilities": [],
                    "removed_events": [],
                    "removed_capabilities": [],
                },
                "actions": ["verify-target", "activate", "ledger-write"],
                "package_sha256": record["versions"][version]["package_sha256"],
                "ledger_digest": digest(ledger),
            }
        )

    def plan_remove(self, extension_id: str, *, scope: str) -> dict[str, Any]:
        identifier(extension_id, "extension id")
        ledger = self._load(scope)
        record = ledger["packages"].get(extension_id)
        if record is None:
            raise PackageError("package is not installed in the explicit scope")
        try:
            owned = resolve_beneath(
                self._installed_root(scope, must_exist=True), extension_id
            )
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc
        files: list[str] = []
        for path in sorted(owned.rglob("*")):
            if path.is_symlink():
                raise PackageError("installed package contains symlink")
            if path.is_file():
                files.append(path.relative_to(owned).as_posix())
        return self._remember_plan(
            {
                "operation": "remove",
                "scope": scope,
                "id": extension_id,
                "old_version": record["active"],
                "new_version": None,
                "files": files,
                "capability_changes": {
                    "added_events": [],
                    "added_capabilities": [],
                    "removed_events": sorted(record["events"]),
                    "removed_capabilities": sorted(record["capabilities"]),
                },
                "actions": [
                    "stage-removal",
                    "ledger-write",
                    "remove-owned-bytes",
                ],
                "package_sha256": record["versions"][record["active"]]["package_sha256"],
                "ledger_digest": digest(ledger),
            }
        )

    def _extract_staged(
        self, package: Path, staging: Path, inspected: Mapping[str, Any]
    ) -> None:
        with zipfile.ZipFile(package) as archive:
            for item in inspected["files"]:
                destination = staging / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(item["path"])
                if sha256_bytes(data) != item["sha256"]:
                    raise PackageError("package changed after dry run")
                destination.write_bytes(data)
                destination.chmod(0o644)
        entry = staging / inspected["entry_point"]
        entry.chmod(0o700)

    def apply(
        self, plan: Mapping[str, Any], *, interrupt_after_stage: bool = False
    ) -> dict[str, Any]:
        supplied = dict(plan)
        plan_digest = supplied.pop("plan_digest", None)
        if not isinstance(plan_digest, str) or digest(supplied) != plan_digest:
            raise PackageError("validated plan digest mismatch")
        private = self._plans.get(plan_digest)
        if private is None or private["public"] != dict(plan):
            raise PackageError("plan was not produced by this manager")
        scope, extension_id, operation = plan["scope"], plan["id"], plan["operation"]
        operation_id = private["operation_id"]
        correlations = {
            "subject_digest": digest(extension_id),
            "plan_digest": plan_digest,
        }
        if isinstance(plan.get("package_sha256"), str):
            correlations["package_digest"] = plan["package_sha256"]
        ledger = self._load(scope)
        if digest(ledger) != plan["ledger_digest"]:
            self._observe(
                "package.apply.rejected",
                operation_id=operation_id,
                correlations=correlations,
                outcome="refused",
                payload={"reason_digest": digest("ledger_changed")},
            )
            raise PackageError("installation ledger changed after dry run")
        if operation in {"install", "update"}:
            inspected = inspect_package(private["package"])
            if inspected["package_sha256"] != plan["package_sha256"]:
                self._observe(
                    "package.apply.rejected",
                    operation_id=operation_id,
                    correlations=correlations,
                    outcome="refused",
                    payload={"reason_digest": digest("package_changed")},
                )
                raise PackageError("package changed after dry run")
            stage_parent = self._staging_root(scope)
            stage_parent.mkdir(exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=f"{extension_id}-", dir=stage_parent)
            )
            try:
                self._extract_staged(private["package"], staging, inspected)
                if interrupt_after_stage:
                    self._observe(
                        "package.apply.interrupted",
                        operation_id=operation_id,
                        correlations=correlations,
                        outcome="interrupted",
                        payload={"prior_state_digest": digest(ledger), "staged": True},
                        source_class="controlled",
                    )
                    raise PackageError("interrupted after complete staging")
                installed_root = self._installed_root(scope, must_exist=False)
                installed_root.mkdir(exist_ok=True)
                destination = installed_root / extension_id / inspected["version"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_symlink():
                    raise PackageError("installed package destination may not be a symlink")
                backup_parent: Path | None = None
                backup: Path | None = None
                if destination.exists():
                    backup_parent = Path(
                        tempfile.mkdtemp(
                            prefix=f"{extension_id}-prior-", dir=stage_parent
                        )
                    )
                    backup = backup_parent / "package"
                    os.replace(destination, backup)
                os.replace(staging, destination)
                ledger_committed = False
                try:
                    record = ledger["packages"].get(extension_id)
                    if record is None:
                        record = {
                            "active": inspected["version"],
                            "versions": {},
                            "approvals": {},
                            "approval_required": [],
                        }
                        ledger["packages"][extension_id] = record
                    expanded = bool(
                        plan["capability_changes"]["added_events"]
                        or plan["capability_changes"]["added_capabilities"]
                    )
                    if operation == "update":
                        for project_id, approval in record["approvals"].items():
                            if expanded:
                                approval["enabled"] = False
                                record["approval_required"].append(project_id)
                            else:
                                approval["version"] = inspected["version"]
                    record["approval_required"] = sorted(
                        set(record["approval_required"])
                    )
                    record.update(
                        {
                            "active": inspected["version"],
                            "active_plan_digest": plan_digest,
                            "events": inspected["events"],
                            "capabilities": inspected["capabilities"],
                            "protocol_range": inspected["protocol_range"],
                        }
                    )
                    record["versions"][inspected["version"]] = {
                        "package_sha256": inspected["package_sha256"],
                        "inventory_digest": inspected["inventory_digest"],
                        "events": inspected["events"],
                        "capabilities": inspected["capabilities"],
                        "protocol_range": inspected["protocol_range"],
                    }
                    self._write(scope, ledger)
                    ledger_committed = True
                except Exception:
                    if destination.exists():
                        os.replace(destination, staging)
                    if backup is not None and backup.exists():
                        os.replace(backup, destination)
                    else:
                        try:
                            destination.parent.rmdir()
                        except OSError:
                            pass
                    raise
                finally:
                    if (
                        backup_parent is not None
                        and backup_parent.exists()
                        and (
                            ledger_committed
                            or backup is None
                            or not backup.exists()
                        )
                    ):
                        shutil.rmtree(backup_parent)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        elif operation == "rollback":
            record = ledger["packages"][extension_id]
            self._verify_directory(scope, extension_id, plan["new_version"])
            target = record["versions"][plan["new_version"]]
            record.update(
                {
                    "active": plan["new_version"],
                    "active_plan_digest": plan_digest,
                    "events": target["events"],
                    "capabilities": target["capabilities"],
                    "protocol_range": target["protocol_range"],
                }
            )
            for approval in record["approvals"].values():
                approval["enabled"] = False
            record["approval_required"] = sorted(record["approvals"])
            self._write(scope, ledger)
            self._observe(
                "package.rollback.completed",
                operation_id=operation_id,
                correlations=correlations,
                outcome="succeeded",
                payload={"verified": True},
            )
        elif operation == "remove":
            before = digest(ledger)
            try:
                owned = resolve_beneath(
                    self._installed_root(scope, must_exist=True), extension_id
                )
            except ProtocolError as exc:
                raise PackageError(str(exc)) from exc
            stage_parent = self._staging_root(scope)
            stage_parent.mkdir(exist_ok=True)
            tombstone_parent = Path(
                tempfile.mkdtemp(prefix=f"{extension_id}-remove-", dir=stage_parent)
            )
            tombstone = tombstone_parent / "package"
            os.replace(owned, tombstone)
            try:
                ledger["packages"].pop(extension_id)
                self._write(scope, ledger)
            except Exception:
                os.replace(tombstone, owned)
                shutil.rmtree(tombstone_parent)
                raise
            # The ledger is the activation authority and the owned tree has
            # already left .installed atomically. A failed best-effort cleanup
            # can leave only unreachable staging garbage, never an installed
            # package absent from the ledger.
            shutil.rmtree(tombstone_parent, ignore_errors=True)
            self._observe(
                "package.remove.completed",
                operation_id=operation_id,
                correlations=correlations,
                outcome="succeeded",
                payload={"before_state_digest": before, "after_state_digest": digest(ledger)},
            )
            self._observe(
                "package.preservation.checked",
                operation_id=operation_id,
                correlations=correlations,
                outcome="succeeded",
                payload={"preserved": True},
            )
        else:
            raise PackageError("unknown lifecycle operation")
        self._observe(
            "package.apply.completed",
            operation_id=operation_id,
            correlations=correlations,
            outcome="succeeded",
            payload={"operation": operation, "preserved": True},
        )
        return {
            "scope": scope,
            "id": extension_id,
            "operation": operation,
            "result": "applied",
        }

    def _verify_directory(
        self, scope: str, extension_id: str, version: str
    ) -> dict[str, Any]:
        try:
            root = resolve_beneath(
                self._installed_root(scope, must_exist=True),
                f"{extension_id}/{version}",
            )
        except ProtocolError as exc:
            raise PackageError(str(exc)) from exc
        metadata = self._load(scope)["packages"][extension_id]["versions"][version]
        if root.is_symlink() or not root.is_dir():
            raise PackageError("installed package directory unavailable")
        manifest = parse_manifest(root / "manifest.json", scope, root)
        inventory: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise PackageError("installed package contains symlink")
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                inventory.append(
                    {
                        "path": relative,
                        "sha256": sha256_bytes(data),
                        "size": len(data),
                        "role": self._installed_role(relative, manifest["entry_point"]),
                    }
                )
        if digest(inventory) != metadata["inventory_digest"]:
            raise PackageError("installed inventory does not match ledger")
        return manifest

    @staticmethod
    def _installed_role(path: str, entry_point: Path | str) -> str:
        entry_name = Path(entry_point).as_posix()
        marker = "/.installed/"
        if marker in entry_name:
            # parse_manifest returns an absolute path; only the package suffix matters.
            entry_name = entry_name.split(marker, 1)[1].split("/", 2)[-1]
        if path == "manifest.json":
            return "manifest"
        if path == "LICENSE":
            return "license"
        if path == "PROVENANCE.json":
            return "provenance"
        if path == entry_name or path.startswith("payload/"):
            return "payload"
        if path.startswith("schemas/"):
            return "schema"
        if path.startswith("docs/"):
            return "documentation"
        if path.startswith("tests/"):
            return "test"
        raise PackageError("installed package contains unclassified file")

    def verify(self, extension_id: str, *, scope: str) -> dict[str, Any]:
        record = self._load(scope)["packages"].get(extension_id)
        if record is None:
            raise PackageError("package is not installed in the explicit scope")
        self._verify_directory(scope, extension_id, record["active"])
        self._observe(
            "package.verify.completed",
            operation_id=str(uuid.uuid4()),
            correlations={
                "subject_digest": digest(extension_id),
                "package_digest": record["versions"][record["active"]]["package_sha256"],
            },
            outcome="succeeded",
            payload={"verified": True},
        )
        return {
            "id": extension_id,
            "scope": scope,
            "version": record["active"],
            "health": "verified",
        }

    def approve_project(
        self,
        extension_id: str,
        *,
        scope: str,
        project_id: str,
        version: str,
        events: list[str],
        capabilities: list[str],
    ) -> None:
        identifier(project_id, "project id")
        ledger = self._load(scope)
        record = ledger["packages"].get(extension_id)
        if record is None or version != record["active"]:
            raise PackageError("approval must name the exact installed version")
        if set(events) - set(record["events"]) or set(capabilities) - set(
            record["capabilities"]
        ):
            raise PackageError("approval exceeds declared package authority")
        record["approvals"][project_id] = {
            "version": version,
            "events": sorted(events),
            "capabilities": sorted(capabilities),
            "enabled": True,
        }
        record["approval_required"] = [
            item for item in record["approval_required"] if item != project_id
        ]
        self._write(scope, ledger)
        self._observe(
            "package.approval.changed",
            operation_id=str(uuid.uuid4()),
            correlations={
                "subject_digest": digest(extension_id),
                "package_digest": record["versions"][version]["package_sha256"],
                "approval_digest": digest(record["approvals"][project_id]),
                **({"plan_digest": record["active_plan_digest"]}
                   if isinstance(record.get("active_plan_digest"), str) else {}),
            },
            outcome="succeeded",
            payload={"enabled": True, "authority_expanded": False},
        )

    def list_installed(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for scope in sorted(SOURCES):
            for extension_id, record in sorted(self._load(scope)["packages"].items()):
                rows.append(self._public(extension_id, scope, record))
        return rows

    def _record(
        self, extension_id: str, scope: str | None
    ) -> tuple[str, dict[str, Any]]:
        if scope is not None:
            record = self._load(scope)["packages"].get(extension_id)
            if record is None:
                raise PackageError("package is not installed in the explicit scope")
            return scope, record
        matches = [
            (candidate, self._load(candidate)["packages"].get(extension_id))
            for candidate in sorted(SOURCES)
        ]
        matches = [
            (candidate, record) for candidate, record in matches if record is not None
        ]
        if len(matches) != 1:
            raise PackageError("package identity is ambiguous; specify scope")
        return matches[0]

    @staticmethod
    def _public(
        extension_id: str, scope: str, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": extension_id,
            "version": record["active"],
            "scope": scope,
            "compatibility": dict(record["protocol_range"]),
            "events": list(record["events"]),
            "capabilities": list(record["capabilities"]),
            "enabled_projects": sorted(
                name
                for name, approval in record["approvals"].items()
                if approval["enabled"]
            ),
            "approval_required_projects": sorted(record["approval_required"]),
            "health": "installed",
        }

    def inspect_installed(
        self, extension_id: str, *, scope: str | None = None
    ) -> dict[str, Any]:
        resolved_scope, record = self._record(extension_id, scope)
        return self._public(extension_id, resolved_scope, record)

    def status(self, extension_id: str, *, scope: str) -> dict[str, Any]:
        result = self.inspect_installed(extension_id, scope=scope)
        try:
            result["health"] = self.verify(extension_id, scope=scope)["health"]
        except PackageError:
            result["health"] = "invalid"
        return result

    def state_digest(self) -> str:
        return digest({scope: self._load(scope) for scope in sorted(SOURCES)})
