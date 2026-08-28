#!/usr/bin/env python3
"""Read-only provenance and commit admission for managed Nightshift payloads.

The release manifest is the only managed-path authority.  A release marker keeps
the complete manifest that produced an install, so a later audit can prove a
per-file prior-release match instead of guessing from an aggregate fingerprint.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:
    from release import is_ignored_python_cache_path
except ImportError:
    # Narrow scanner/provenance deployments may intentionally omit the release
    # module. Keep the canonical policy exact in that supported standalone shape.
    def is_ignored_python_cache_path(path: str | os.PathLike[str]) -> bool:
        candidate = PurePosixPath(str(path).replace("\\", "/"))
        return "__pycache__" in candidate.parts or candidate.suffix in {".pyc", ".pyo"}


EXACT_CURRENT = "exact-current"
RETAINED_PRIOR_RELEASE = "retained-prior-release"
UNRESOLVED_DIVERGENCE = "unresolved-divergence"
MARKER = "release-marker.json"
INTEGRITY_SCHEMA_VERSION = "1.0.0"
RECEIPT_DIR = Path("reports/_wip/managed-payload-integrity/receipts")
ACCEPTANCE_DIR = Path("reports/_wip/managed-payload-integrity/acceptance")
MAX_RECEIPT_BYTES = 16 * 1024
MAX_ACCEPTANCE_BYTES = 256 * 1024
MAX_REPORTED_PATHS = 128
MAX_RECEIPT_AGE = timedelta(hours=24)
MAX_RECEIPT_CLOCK_SKEW = timedelta(minutes=5)
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")

ALLOW = "allow"
DENY = "deny"
INDETERMINATE = "indeterminate"

INSTALL_PATH_MANAGED = "managed-payload"
INSTALL_PATH_UNCLAIMED = "unclaimed"
INSTALL_PATH_IGNORED = "ignored-generated-cache"

REASON_CLEAN = "NS-MPI-CLEAN"
REASON_PAYLOAD_DRIFT = "NS-MPI-PAYLOAD-DRIFT"
REASON_RECEIPT_MISSING = "NS-MPI-RECEIPT-MISSING"
REASON_RECEIPT_INVALID = "NS-MPI-RECEIPT-INVALID"
REASON_RECEIPT_MISMATCH = "NS-MPI-RECEIPT-MISMATCH"
REASON_METADATA_INVALID = "NS-MPI-METADATA-INVALID"
REASON_ARTIFACT_FAILURE = "NS-MPI-ARTIFACT-FAILURE"
REASON_DUPLICATE_CONTRADICTION = "NS-MPI-DUPLICATE-CONTRADICTION"

TERMINAL_ENTRYPOINT_INVENTORY: tuple[dict[str, str], ...] = (
    {"path": "nightshift_coordinator.py", "marker": "_accept_managed_payload"},
    {"path": "nightshift-instructions.py", "marker": "verify_terminal_integrity"},
    {"path": "parallel_executor.py", "marker": "terminal_gate"},
    {"path": "run_validation.py", "marker": "verify_terminal_integrity"},
    {"path": "LOOP.md", "marker": "verify_terminal_integrity"},
    {"path": "ORCHESTRATOR.md", "marker": "verify_terminal_integrity"},
    {"path": "BOOTSTRAP.md", "marker": "verify_terminal_integrity"},
    {"path": "Skills/nightshift/SKILL.md", "marker": "verify_terminal_integrity"},
)
SUPPORTED_RESULT_ACCEPTANCE_ENTRYPOINTS: tuple[str, ...] = (
    "nightshift_coordinator.py",
    "nightshift-instructions.py",
    "parallel_executor.py",
    "run_validation.py",
    "LOOP.md",
    "ORCHESTRATOR.md",
    "BOOTSTRAP.md",
    "Skills/nightshift/SKILL.md",
)


def terminal_entrypoint_gaps(
    install: Path,
    *,
    supported: Sequence[str] = SUPPORTED_RESULT_ACCEPTANCE_ENTRYPOINTS,
    inventory: Sequence[Mapping[str, str]] = TERMINAL_ENTRYPOINT_INVENTORY,
) -> list[str]:
    """Fail canonical closure when an official acceptance surface lacks the gate."""
    inventoried = {entry.get("path") for entry in inventory}
    gaps: list[str] = [path for path in supported if path not in inventoried]
    for entry in inventory:
        path = install / entry["path"]
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            gaps.append(entry["path"])
            continue
        if entry["marker"] not in text:
            gaps.append(entry["path"])
    return sorted(set(gaps))


class MetadataError(ValueError):
    """Managed provenance cannot be established from trustworthy metadata."""


@dataclass(frozen=True)
class PathProvenance:
    path: str
    classification: str
    actual_sha256: str | None
    current_sha256: str | None
    retained_sha256: str | None
    head_sha256: str | None
    differs_from_head: bool
    staged: bool


@dataclass(frozen=True)
class AcceptanceResult:
    """Privacy-safe terminal integrity decision returned to acceptance owners."""

    outcome: str
    reason_code: str
    artifact_path: str | None
    artifact_sha256: str | None
    changed_paths: tuple[str, ...] = ()
    ownership: str = "canonical-release"
    remediation: str = "preserve-and-route-canonical-release"

    @property
    def ok(self) -> bool:
        return self.outcome == ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "changed_paths": list(self.changed_paths),
            "ownership": self.ownership,
            "remediation": self.remediation,
        }


def render_terminal_result(result: AcceptanceResult) -> str:
    """Return the complete privacy-safe console projection for this decision."""
    artifact = result.artifact_path or "unavailable"
    return (
        "MANAGED_PAYLOAD_ACCEPTANCE "
        f"outcome={result.outcome} reason_code={result.reason_code} "
        f"changed_count={len(result.changed_paths)} artifact={artifact}"
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "fingerprint"}
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(normalized).hexdigest()


def _manifest_index(manifest: Mapping[str, Any], *, label: str) -> dict[str, str]:
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != _manifest_fingerprint(manifest):
        raise MetadataError(f"{label} fingerprint is missing or corrupt")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise MetadataError(f"{label} has no managed file list")
    index: dict[str, str] = {}
    for entry in files:
        if not isinstance(entry, Mapping):
            raise MetadataError(f"{label} contains an invalid managed file entry")
        path = entry.get("path")
        digest = entry.get("sha256")
        candidate = PurePosixPath(path) if isinstance(path, str) else None
        if (
            candidate is None
            or candidate.is_absolute()
            or ".." in candidate.parts
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise MetadataError(f"{label} contains invalid per-file hash metadata")
        if path in index:
            raise MetadataError(f"{label} contains duplicate managed path: {path}")
        index[path] = digest
    return index


def load_manifest(path: Path, *, label: str = "current manifest") -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(f"{label} is missing or corrupt: {path.name}") from exc
    if not isinstance(data, dict):
        raise MetadataError(f"{label} is not a JSON object")
    _manifest_index(data, label=label)
    return data


def managed_payload_paths(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Return the manifest-authoritative managed paths for a release payload.

    Consumers that need to distinguish release-owned files from project-owned
    files must use this projection rather than maintaining a second path list.
    ``_manifest_index`` keeps the same validation boundary as provenance
    admission: corrupt metadata cannot silently broaden an exemption.
    """
    return frozenset(
        path
        for path in _manifest_index(manifest, label="managed payload manifest")
        if not is_ignored_python_cache_path(path)
    )


def classify_install_path(path: str, manifest: Mapping[str, Any]) -> str:
    """Classify a path without inventing mutable bytecode ownership."""
    relative = path.removeprefix(".nightshift/")
    if is_ignored_python_cache_path(relative):
        return INSTALL_PATH_IGNORED
    if relative in managed_payload_paths(manifest):
        return INSTALL_PATH_MANAGED
    return INSTALL_PATH_UNCLAIMED


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _digest_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _manifest_inventory(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the exact, deterministic path/hash/mode inventory."""
    _manifest_index(manifest, label="managed payload manifest")
    return sorted(
        (
            {
                "path": str(entry["path"]),
                "sha256": str(entry["sha256"]),
                "executable": bool(entry.get("executable", False)),
            }
            for entry in manifest["files"]
            if not is_ignored_python_cache_path(str(entry["path"]))
        ),
        key=lambda entry: entry["path"],
    )


def _inventory_digest(manifest: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_json({"files": _manifest_inventory(manifest)}))


def _active_manifest(install: Path) -> dict[str, Any]:
    """Load the manifest that authoritatively owns this exact install."""
    canonical_manifest = install / "release-manifest.json"
    if install.name == "canonical" and canonical_manifest.is_file():
        return load_manifest(canonical_manifest)
    return retained_manifest(install)


def _git_binding(install: Path) -> dict[str, str]:
    repo = _git_root(install)
    common_result = _run_git(repo, "rev-parse", "--git-common-dir")
    if common_result.returncode:
        raise MetadataError("Git common-dir is unavailable")
    common_raw = common_result.stdout.decode("utf-8", errors="strict").strip()
    common = Path(common_raw)
    if not common.is_absolute():
        common = repo / common
    try:
        install_rel = install.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise MetadataError("managed install is outside its Git worktree") from exc
    return {
        "git_common_dir_sha256": _digest_text(str(common.resolve())),
        "worktree_sha256": _digest_text(str(repo.resolve())),
        "install_relative_sha256": _digest_text(install_rel),
    }


def _safe_artifact_root(install: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise MetadataError("unsafe artifact path")
    current = install
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise MetadataError("symlinked artifact directory")
    current.mkdir(parents=True, exist_ok=True)
    current.resolve().relative_to(install.resolve())
    return current


def _atomic_write_new(path: Path, body: bytes, *, limit: int) -> tuple[str, bool]:
    """Atomically write once; return digest and whether identical history existed."""
    if len(body) > limit:
        raise MetadataError("artifact exceeds size limit")
    if path.is_symlink():
        raise MetadataError("symlinked artifact destination")
    lock = path.parent / ".managed-payload-integrity.lock"
    if not hasattr(os, "O_NOFOLLOW"):
        raise MetadataError("no no-follow file-open support")
    lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock_handle = os.fdopen(lock_fd, "a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if path.exists():
            previous = path.read_bytes()
            if previous == body:
                return _sha256_bytes(body), True
            raise FileExistsError(errno.EEXIST, "contradictory duplicate artifact", str(path))
        fd, temp_name = tempfile.mkstemp(prefix=".managed-payload-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()
    return _sha256_bytes(body), False


def write_integrity_receipt(
    install: Path,
    *,
    spec_id: str,
    invocation_id: str,
    run_id: str | None = None,
    manifest: Mapping[str, Any] | None = None,
    admitted_artifact_sha256: str,
) -> tuple[str, str]:
    """Persist a bounded baseline receipt after a successful SPEC-229 admission."""
    if SAFE_ID.fullmatch(spec_id) is None or SAFE_ID.fullmatch(invocation_id) is None:
        raise MetadataError("unsafe receipt identity")
    if not isinstance(admitted_artifact_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", admitted_artifact_sha256):
        raise MetadataError("invalid admission artifact digest")
    install = install.resolve()
    active = dict(manifest or _active_manifest(install))
    marker_sha = _sha256_file(install / MARKER)
    if install.name != "canonical" and marker_sha is None:
        raise MetadataError("release marker is missing")
    receipt = {
        "schema_version": INTEGRITY_SCHEMA_VERSION,
        "invocation_id": invocation_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": {
            "project_sha256": _git_binding(install)["git_common_dir_sha256"],
            "run_sha256": _digest_text(run_id or invocation_id),
            "spec_sha256": _digest_text(spec_id),
        },
        "binding": _git_binding(install),
        "release": {
            "kit_version": active.get("kit_version"),
            "release_fingerprint": active.get("fingerprint"),
            "manifest_fingerprint": active.get("fingerprint"),
            "manifest_inventory_sha256": _inventory_digest(active),
            "release_marker_sha256": marker_sha,
        },
        "admission_artifact_sha256": admitted_artifact_sha256,
    }
    body = _canonical_json(receipt)
    root = _safe_artifact_root(install, RECEIPT_DIR)
    dest = root / f"{invocation_id}.json"
    digest, _replayed = _atomic_write_new(dest, body, limit=MAX_RECEIPT_BYTES)
    return dest.relative_to(install).as_posix(), digest


def _load_receipt(install: Path, receipt_ref: str, receipt_sha256: str) -> tuple[dict[str, Any], bytes]:
    candidate = PurePosixPath(receipt_ref)
    if candidate.is_absolute() or ".." in candidate.parts or not receipt_ref.startswith(RECEIPT_DIR.as_posix() + "/"):
        raise MetadataError("receipt path is unsafe")
    path = install / candidate
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError("integrity receipt is missing")
    path.resolve().relative_to(install.resolve())
    body = path.read_bytes()
    if len(body) > MAX_RECEIPT_BYTES or _sha256_bytes(body) != receipt_sha256:
        raise MetadataError("integrity receipt digest mismatch")
    try:
        receipt = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError("integrity receipt encoding or JSON is invalid") from exc
    required = {"schema_version", "invocation_id", "generated_at", "identity", "binding", "release", "admission_artifact_sha256"}
    if not isinstance(receipt, dict) or set(receipt) != required:
        raise MetadataError("integrity receipt schema is invalid")
    if receipt.get("schema_version") != INTEGRITY_SCHEMA_VERSION or SAFE_ID.fullmatch(str(receipt.get("invocation_id", ""))) is None:
        raise MetadataError("integrity receipt version or invocation is invalid")
    try:
        generated_at = datetime.strptime(receipt["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise MetadataError("integrity receipt timestamp is invalid") from exc
    now = datetime.now(timezone.utc)
    if generated_at < now - MAX_RECEIPT_AGE or generated_at > now + MAX_RECEIPT_CLOCK_SKEW:
        raise MetadataError("integrity receipt is stale or future-dated")
    for group, keys in (
        (receipt.get("identity"), {"project_sha256", "run_sha256", "spec_sha256"}),
        (receipt.get("binding"), {"git_common_dir_sha256", "worktree_sha256", "install_relative_sha256"}),
        (receipt.get("release"), {"kit_version", "release_fingerprint", "manifest_fingerprint", "manifest_inventory_sha256", "release_marker_sha256"}),
    ):
        if not isinstance(group, dict) or set(group) != keys:
            raise MetadataError("integrity receipt nested schema is invalid")
    digests = [*receipt["identity"].values(), *receipt["binding"].values(), receipt["release"]["release_fingerprint"], receipt["release"]["manifest_fingerprint"], receipt["release"]["manifest_inventory_sha256"], receipt["admission_artifact_sha256"]]
    if receipt["release"]["release_marker_sha256"] is not None:
        digests.append(receipt["release"]["release_marker_sha256"])
    if any(not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None for item in digests):
        raise MetadataError("integrity receipt contains invalid digest fields")
    return receipt, body


def _observe_payload(install: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    observations: list[dict[str, Any]] = []
    for expected in _manifest_inventory(manifest):
        path = install / expected["path"]
        observed_hash: str | None = None
        observed_mode: bool | None = None
        observed_kind = "missing"
        try:
            components = [install.joinpath(*PurePosixPath(expected["path"]).parts[:index]) for index in range(1, len(PurePosixPath(expected["path"]).parts) + 1)]
            if any(component.is_symlink() for component in components):
                observed_kind = "symlink"
            elif path.is_file():
                observed_kind = "file"
                observed_hash = _sha256_file(path)
                observed_mode = bool(path.stat().st_mode & 0o111)
            elif path.exists():
                observed_kind = "replaced"
        except OSError:
            observed_kind = "unreadable"
        observations.append({
            "path": expected["path"],
            "expected_sha256": expected["sha256"],
            "observed_sha256": observed_hash,
            "expected_executable": expected["executable"],
            "observed_executable": observed_mode,
            "observed_kind": observed_kind,
        })
    digest_projection = {
        "files": [
            {
                "path": row["path"],
                "sha256": row["observed_sha256"],
                "executable": row["observed_executable"],
                "kind": row["observed_kind"],
            }
            for row in observations
        ]
    }
    return observations, _sha256_bytes(_canonical_json(digest_projection))


def _release_owned_aliases(install: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Detect aliases to release-owned files while ignoring Python cache."""
    managed = set(managed_payload_paths(manifest))
    managed_targets = {(install / path).resolve(strict=False): path for path in managed}
    managed_inodes: dict[tuple[int, int], str] = {}
    for path in managed:
        candidate = install / path
        try:
            if candidate.is_file() and not candidate.is_symlink():
                info = candidate.stat()
                managed_inodes[(info.st_dev, info.st_ino)] = path
        except OSError:
            continue
    mutable_roots = {"reports", "metrics", "specs", "knowledge", "runs", "evidence", ".migrations", ".board-venv"}
    aliases: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(install, followlinks=False):
        relative_root = Path(root).relative_to(install)
        if relative_root == Path("."):
            dirs[:] = [name for name in dirs if name not in mutable_roots]
        dirs[:] = [
            name
            for name in dirs
            if not is_ignored_python_cache_path((relative_root / name).as_posix())
        ]
        for name in [*dirs, *files]:
            candidate = Path(root) / name
            relative = candidate.relative_to(install).as_posix()
            if is_ignored_python_cache_path(relative):
                continue
            if relative in managed or not candidate.is_symlink():
                if relative in managed or not candidate.is_file():
                    continue
                try:
                    info = candidate.stat()
                    target_owner = managed_inodes.get((info.st_dev, info.st_ino))
                except OSError:
                    target_owner = None
                observed_kind = f"release-owned-hardlink:{target_owner}" if target_owner is not None else None
            else:
                target_owner = managed_targets.get(candidate.resolve(strict=False))
                observed_kind = f"release-owned-alias:{target_owner}" if target_owner is not None else None
            if target_owner is not None:
                aliases.append({
                    "path": relative,
                    "expected_sha256": None,
                    "observed_sha256": None,
                    "expected_executable": None,
                    "observed_executable": None,
                    "observed_kind": observed_kind,
                })
    return sorted(aliases, key=lambda row: row["path"])


def _quarantine_duplicate(root: Path, invocation_id: str, body: bytes) -> str | None:
    try:
        quarantine = _safe_artifact_root(root, ACCEPTANCE_DIR / "quarantine")
        digest = _sha256_bytes(body)
        target = quarantine / f"{invocation_id}-{digest}.json"
        _atomic_write_new(target, body, limit=MAX_ACCEPTANCE_BYTES)
        return target.relative_to(root).as_posix()
    except (OSError, MetadataError, FileExistsError):
        return None


def verify_terminal_integrity(
    install: Path,
    *,
    spec_id: str,
    receipt_ref: str,
    receipt_sha256: str,
    run_id: str | None = None,
) -> AcceptanceResult:
    """Compare the admitted manifest payload before any result acceptance action."""
    install = install.resolve()
    invocation_id = "unknown"
    receipt_body = b""
    outcome = INDETERMINATE
    reason_code = REASON_RECEIPT_INVALID
    differences: list[dict[str, Any]] = []
    observed_inventory_sha = None
    receipt: dict[str, Any] | None = None
    try:
        receipt, receipt_body = _load_receipt(install, receipt_ref, receipt_sha256)
        invocation_id = receipt["invocation_id"]
        if SAFE_ID.fullmatch(spec_id) is None:
            raise MetadataError("unsafe selected spec identity")
        expected_binding = _git_binding(install)
        expected_identity = {
            "project_sha256": expected_binding["git_common_dir_sha256"],
            "run_sha256": _digest_text(run_id or invocation_id),
            "spec_sha256": _digest_text(spec_id),
        }
        if receipt["binding"] != expected_binding or receipt["identity"] != expected_identity:
            reason_code = REASON_RECEIPT_MISMATCH
            raise MetadataError("integrity receipt does not bind this run/spec/worktree")
        # From this point onward the receipt itself is trusted. Any missing or
        # corrupt active manifest/marker is observed payload drift, not a
        # receipt parse failure.
        outcome, reason_code = DENY, REASON_PAYLOAD_DRIFT
        manifest = _active_manifest(install)
        marker_sha = _sha256_file(install / MARKER)
        release = receipt["release"]
        if (
            manifest.get("fingerprint") != release["manifest_fingerprint"]
            or _inventory_digest(manifest) != release["manifest_inventory_sha256"]
        ):
            outcome, reason_code = INDETERMINATE, REASON_RECEIPT_MISMATCH
            raise MetadataError("integrity receipt binds a different manifest")
        if marker_sha != release["release_marker_sha256"]:
            outcome = DENY
            reason_code = REASON_PAYLOAD_DRIFT
            differences.append({
                "path": MARKER,
                "expected_sha256": release["release_marker_sha256"],
                "observed_sha256": marker_sha,
                "expected_executable": False,
                "observed_executable": bool((install / MARKER).stat().st_mode & 0o111) if (install / MARKER).is_file() else None,
                "observed_kind": "file" if (install / MARKER).is_file() else "missing_or_replaced",
            })
        observations, observed_inventory_sha = _observe_payload(install, manifest)
        differences.extend(
            row for row in observations
            if row["observed_kind"] != "file"
            or row["observed_sha256"] != row["expected_sha256"]
            or row["observed_executable"] != row["expected_executable"]
        )
        differences.extend(_release_owned_aliases(install, manifest))
        if differences:
            outcome, reason_code = DENY, REASON_PAYLOAD_DRIFT
        else:
            outcome, reason_code = ALLOW, REASON_CLEAN
    except FileNotFoundError:
        reason_code = REASON_RECEIPT_MISSING
    except MetadataError:
        if reason_code not in {REASON_RECEIPT_MISMATCH, REASON_PAYLOAD_DRIFT}:
            reason_code = REASON_RECEIPT_INVALID
    except (OSError, ValueError):
        reason_code = REASON_METADATA_INVALID

    receipt_result_hash = _sha256_bytes(receipt_body) if receipt_body else receipt_sha256 if isinstance(receipt_sha256, str) else None
    artifact = {
        "schema_version": INTEGRITY_SCHEMA_VERSION,
        "invocation_id": invocation_id,
        "generated_at": (
            receipt.get("generated_at")
            if isinstance(receipt, dict)
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        ),
        "outcome": outcome,
        "reason_code": reason_code,
        "receipt_sha256": receipt_result_hash,
        "observed_inventory_sha256": observed_inventory_sha,
        "differences": differences,
        "ownership": "canonical-release",
        "remediation": "preserve-and-route-canonical-release",
        "privacy": {"relative_paths_only": True, "content_included": False},
    }
    artifact["result_sha256"] = _sha256_bytes(_canonical_json({
        "outcome": artifact["outcome"],
        "reason_code": artifact["reason_code"],
        "receipt_sha256": artifact["receipt_sha256"],
        "observed_inventory_sha256": artifact["observed_inventory_sha256"],
        "differences": artifact["differences"],
    }))
    body = _canonical_json(artifact)
    artifact_ref = None
    artifact_sha = None
    try:
        out_dir = _safe_artifact_root(install, ACCEPTANCE_DIR)
        if SAFE_ID.fullmatch(invocation_id) is None:
            invocation_id = uuid.uuid4().hex
            artifact["invocation_id"] = invocation_id
            body = _canonical_json(artifact)
        dest = out_dir / f"{invocation_id}.json"
        artifact_sha, _replayed = _atomic_write_new(dest, body, limit=MAX_ACCEPTANCE_BYTES)
        artifact_ref = dest.relative_to(install).as_posix()
    except FileExistsError:
        _quarantine_duplicate(install, invocation_id, body)
        outcome, reason_code = INDETERMINATE, REASON_DUPLICATE_CONTRADICTION
        artifact_ref = None
        artifact_sha = None
    except (OSError, MetadataError, ValueError):
        outcome, reason_code = INDETERMINATE, REASON_ARTIFACT_FAILURE
        artifact_ref = None
        artifact_sha = None
    return AcceptanceResult(
        outcome=outcome,
        reason_code=reason_code,
        artifact_path=artifact_ref,
        artifact_sha256=artifact_sha,
        changed_paths=tuple(sorted({str(row["path"]) for row in differences})[:MAX_REPORTED_PATHS]),
    )


def retained_manifest(install: Path) -> dict[str, Any]:
    marker_path = install / MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError("release marker is missing or corrupt; retained per-file evidence is unavailable") from exc
    if not isinstance(marker, dict) or not isinstance(marker.get("release_manifest"), dict):
        raise MetadataError("release marker has no retained per-file release manifest")
    manifest = marker["release_manifest"]
    _manifest_index(manifest, label="retained release manifest")
    if (
        marker.get("fingerprint") != manifest.get("fingerprint")
        or marker.get("kit_version") != manifest.get("kit_version")
        or marker.get("schema_version") != manifest.get("schema_version")
    ):
        raise MetadataError("release marker and retained manifest disagree")
    return manifest


def recover_historical_manifest(install: Path, canonical: Path) -> dict[str, Any]:
    """Recover exact old per-file evidence from canonical Git by marker fingerprint."""
    try:
        marker = json.loads((install / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError("release marker is missing or corrupt") from exc
    fingerprint = marker.get("fingerprint") if isinstance(marker, dict) else None
    if not isinstance(fingerprint, str):
        raise MetadataError("release marker has no historical fingerprint")
    repo = _git_root(canonical)
    try:
        manifest_path = (canonical / "release-manifest.json").resolve().relative_to(repo)
    except ValueError as exc:
        raise MetadataError("canonical manifest is outside its Git repository") from exc
    history = _run_git(repo, "log", "--all", "--format=%H", "--", manifest_path.as_posix())
    if history.returncode:
        raise MetadataError("canonical manifest history is unavailable")
    for commit in history.stdout.decode().splitlines():
        shown = _run_git(repo, "show", f"{commit}:{manifest_path.as_posix()}")
        if shown.returncode:
            continue
        try:
            candidate = json.loads(shown.stdout.decode())
            _manifest_index(candidate, label="historical release manifest")
        except (UnicodeDecodeError, json.JSONDecodeError, MetadataError):
            continue
        if candidate.get("fingerprint") == fingerprint:
            return candidate
    raise MetadataError("no exact canonical Git manifest matches the retained fingerprint")


def recover_exact_installed_manifest(
    install: Path,
    canonical: Path,
    *,
    current_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Find a historical manifest whose complete managed payload matches disk."""
    repo = _git_root(canonical)
    manifest_path = (canonical / "release-manifest.json").resolve().relative_to(repo)
    history = _run_git(repo, "log", "--all", "--format=%H", "--", manifest_path.as_posix())
    if history.returncode:
        raise MetadataError("canonical manifest history is unavailable")
    current_paths = set(_manifest_index(current_manifest, label="current manifest"))
    for commit in history.stdout.decode().splitlines():
        shown = _run_git(repo, "show", f"{commit}:{manifest_path.as_posix()}")
        if shown.returncode:
            continue
        try:
            candidate = json.loads(shown.stdout.decode())
            candidate_index = _manifest_index(candidate, label="historical release manifest")
        except (UnicodeDecodeError, json.JSONDecodeError, MetadataError):
            continue
        entries = {entry["path"]: entry for entry in candidate["files"]}
        matched = True
        for path in current_paths:
            installed = install / path
            entry = entries.get(path)
            if entry is None:
                if installed.exists():
                    matched = False
                    break
                continue
            if (
                _sha256_file(installed) != candidate_index[path]
                or bool(installed.stat().st_mode & 0o111) != bool(entry["executable"])
            ):
                matched = False
                break
        if matched:
            return candidate
    raise MetadataError("installed payload does not exactly match canonical Git history")


def recover_exact_canonical_snapshot(
    install: Path,
    canonical: Path,
    *,
    current_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove an install is an exact canonical Git snapshot when no manifest exists."""
    repo = _git_root(canonical)
    prefix = canonical.resolve().relative_to(repo).as_posix().rstrip("/")
    paths = sorted(_manifest_index(current_manifest, label="current manifest"))
    present = [path for path in paths if (install / path).is_file()]
    if not present:
        raise MetadataError("installed payload has no managed file to anchor Git history")
    anchor = "BOOTSTRAP.md" if "BOOTSTRAP.md" in present else present[0]
    anchor_repo_path = f"{prefix}/{anchor}" if prefix else anchor
    history = _run_git(repo, "log", "--all", "--format=%H", "--", anchor_repo_path)
    if history.returncode:
        raise MetadataError("canonical Git history is unavailable")
    for commit in history.stdout.decode().splitlines():
        entries: list[dict[str, Any]] = []
        matched = True
        for path in paths:
            repo_path = f"{prefix}/{path}" if prefix else path
            shown = _run_git(repo, "show", f"{commit}:{repo_path}")
            installed = install / path
            if shown.returncode:
                if installed.exists():
                    matched = False
                    break
                continue
            if not installed.is_file() or _sha256_bytes(shown.stdout) != _sha256_file(installed):
                matched = False
                break
            tree = _run_git(repo, "ls-tree", commit, "--", repo_path)
            mode = tree.stdout.decode().split(maxsplit=1)[0] if tree.returncode == 0 else ""
            executable = mode == "100755"
            if bool(installed.stat().st_mode & 0o111) != executable:
                matched = False
                break
            entries.append(
                {"path": path, "sha256": _sha256_bytes(shown.stdout), "executable": executable}
            )
        if matched and entries:
            payload = {"canonical_commit": commit, "files": entries}
            normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            return {**payload, "fingerprint": hashlib.sha256(normalized).hexdigest()}
    raise MetadataError("installed payload does not exactly match a canonical Git snapshot")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )


def _git_root(install: Path) -> Path:
    result = _run_git(install, "rev-parse", "--show-toplevel")
    if result.returncode:
        raise MetadataError("managed install is not inside a Git repository")
    return Path(result.stdout.decode().strip()).resolve()


def _status(repo: Path) -> tuple[set[str], set[str]]:
    result = _run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode:
        raise MetadataError("git status failed during managed provenance audit")
    dirty: set[str] = set()
    staged: set[str] = set()
    records = result.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or len(record) < 4:
            continue
        xy = record[:2].decode("ascii", errors="replace")
        path = record[3:].decode("utf-8", errors="surrogateescape")
        dirty.add(path)
        if xy[0] not in {" ", "?"}:
            staged.add(path)
        if "R" in xy or "C" in xy:
            index += 1  # porcelain -z appends the source name after a rename/copy
    return dirty, staged


def _head_hash(repo: Path, repo_relative: str) -> str | None:
    result = _run_git(repo, "show", f"HEAD:{repo_relative}")
    return _sha256_bytes(result.stdout) if result.returncode == 0 else None


def audit_git_install(
    install: Path,
    *,
    current_manifest: Mapping[str, Any] | None = None,
    staged_only: bool = False,
    retained_override: Mapping[str, Any] | None = None,
) -> list[PathProvenance]:
    """Classify dirty managed paths without modifying files or the Git index."""
    install = install.resolve()
    repo = _git_root(install)
    install_prefix = install.relative_to(repo).as_posix().rstrip("/")
    dirty, staged = _status(repo)

    retained: Mapping[str, Any] | None = retained_override
    if retained is not None:
        _manifest_index(retained, label="recovered historical release manifest")
    if current_manifest is not None:
        current_index = _manifest_index(current_manifest, label="current manifest")
        candidate_paths = set(current_index)
    else:
        # Installed hooks use the exact release manifest retained in the marker.
        retained = retained_manifest(install)
        current_manifest = retained
        current_index = _manifest_index(current_manifest, label="current manifest")
        candidate_paths = set(current_index)

    selected = staged if staged_only else dirty
    managed_dirty: list[tuple[str, str]] = []
    for managed_path in sorted(candidate_paths):
        repo_path = f"{install_prefix}/{managed_path}" if install_prefix else managed_path
        if repo_path in selected:
            managed_dirty.append((managed_path, repo_path))
    if not managed_dirty:
        return []

    if retained is None:
        retained = retained_manifest(install)
    retained_index = _manifest_index(retained, label="retained release manifest")

    rows: list[PathProvenance] = []
    for managed_path, repo_path in managed_dirty:
        actual = _sha256_file(install / managed_path)
        current = current_index.get(managed_path)
        prior = retained_index.get(managed_path)
        if actual is not None and actual == current:
            classification = EXACT_CURRENT
        elif (
            actual is not None
            and actual == prior
            and retained.get("fingerprint") != current_manifest.get("fingerprint")
        ):
            classification = RETAINED_PRIOR_RELEASE
        else:
            classification = UNRESOLVED_DIVERGENCE
        head = _head_hash(repo, repo_path)
        rows.append(
            PathProvenance(
                path=managed_path,
                classification=classification,
                actual_sha256=actual,
                current_sha256=current,
                retained_sha256=prior,
                head_sha256=head,
                differs_from_head=actual != head,
                staged=repo_path in staged,
            )
        )
    return rows


def guard_staged_install(install: Path) -> list[PathProvenance]:
    """Return staged managed paths that are not exact release payload bytes."""
    return [
        row
        for row in audit_git_install(install, staged_only=True)
        if row.classification != EXACT_CURRENT
    ]


def classify_partial_install(
    install: Path, *, current_manifest: Mapping[str, Any]
) -> list[PathProvenance]:
    """Classify every managed file in a partial apply without changing Git state."""
    install = install.resolve()
    repo = _git_root(install)
    prefix = install.relative_to(repo).as_posix().rstrip("/")
    _dirty, staged = _status(repo)
    current_index = _manifest_index(current_manifest, label="current manifest")
    try:
        prior_manifest = retained_manifest(install)
        prior_index = _manifest_index(prior_manifest, label="retained release manifest")
        prior_fingerprint = prior_manifest.get("fingerprint")
    except MetadataError:
        prior_index = {}
        prior_fingerprint = None
    rows: list[PathProvenance] = []
    for managed_path, current in sorted(current_index.items()):
        repo_path = f"{prefix}/{managed_path}" if prefix else managed_path
        actual = _sha256_file(install / managed_path)
        prior = prior_index.get(managed_path)
        if actual is not None and actual == current:
            classification = EXACT_CURRENT
        elif (
            actual is not None
            and actual == prior
            and prior_fingerprint != current_manifest.get("fingerprint")
        ):
            classification = RETAINED_PRIOR_RELEASE
        else:
            classification = UNRESOLVED_DIVERGENCE
        head = _head_hash(repo, repo_path)
        rows.append(
            PathProvenance(
                path=managed_path,
                classification=classification,
                actual_sha256=actual,
                current_sha256=current,
                retained_sha256=prior,
                head_sha256=head,
                differs_from_head=actual != head,
                staged=repo_path in staged,
            )
        )
    return rows


def _short(value: str | None) -> str:
    return value[:12] if value else "missing"


def format_rows(rows: Sequence[PathProvenance]) -> str:
    lines = []
    for row in rows:
        lines.append(
            f"{row.path}: {row.classification}; actual={_short(row.actual_sha256)}; "
            f"current={_short(row.current_sha256)}; retained={_short(row.retained_sha256)}; "
            f"head={_short(row.head_sha256)}; differs_from_head={str(row.differs_from_head).lower()}; "
            f"staged={str(row.staged).lower()}"
        )
    return "\n".join(lines)


def format_guidance(rows: Sequence[PathProvenance] = ()) -> str:
    detail = f"\n{format_rows(rows)}" if rows else ""
    path_remedies = "".join(
        "\nPreserve the installed edit at "
        f".nightshift/{row.path}; implement canonical/{row.path} under a canonical "
        "Nightshift spec; then publish the complete managed payload through the "
        "whole-kit release flow."
        for row in rows
    )
    return (
        "Managed Nightshift payload divergence detected. Preserve every project delta in place, "
        "create or update a canonical Nightshift spec, and implement and release it through the "
        "canonical flow. Review each unresolved path individually; no provenance was inferred "
        f"from timestamps, similarity, or aggregate fingerprints.{detail}{path_remedies}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, default=Path(".nightshift"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="classify every managed path in a preserved partial apply (read-only)",
    )
    parser.add_argument("--verify-receipt", help="project-relative admitted receipt path")
    parser.add_argument("--receipt-sha256", help="externally retained receipt digest")
    parser.add_argument("--spec-id", help="selected spec bound to terminal acceptance")
    parser.add_argument("--run-id", help="optional stable run identity")
    args = parser.parse_args(argv)
    if args.verify_receipt:
        if not args.receipt_sha256 or not args.spec_id:
            parser.error("--verify-receipt requires --receipt-sha256 and --spec-id")
        result = verify_terminal_integrity(
            args.install,
            spec_id=args.spec_id,
            receipt_ref=args.verify_receipt,
            receipt_sha256=args.receipt_sha256,
            run_id=args.run_id,
        )
        print(json.dumps(result.to_dict(), sort_keys=True, ensure_ascii=False))
        return 0 if result.outcome == ALLOW else 1 if result.outcome == DENY else 2
    manifest = load_manifest(args.manifest) if args.manifest else None
    if args.recovery and manifest is None:
        parser.error("--recovery requires --manifest")
    try:
        rows = (
            classify_partial_install(args.install, current_manifest=manifest)
            if args.recovery
            else audit_git_install(
                args.install, current_manifest=manifest, staged_only=args.staged
            )
        )
    except MetadataError as exc:
        print(f"managed payload metadata error: {exc}", file=sys.stderr)
        print(format_guidance(), file=sys.stderr)
        return 2
    print(format_rows(rows))
    if args.staged and any(row.classification != EXACT_CURRENT for row in rows):
        print(format_guidance(rows), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
