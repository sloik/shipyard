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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

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
SYNC_RECONCILED = "sync-reconciled"
UNRESOLVED_DIVERGENCE = "unresolved-divergence"
MARKER = "release-marker.json"
# BUG-339: ``nightshift-sync.py canonical`` writes this receipt (path -> sha256 of the
# canonical bytes it delivered) beside ``release-marker.json``. Unlike the marker it is
# never sealed by a release, so a SPEC-356 ``sync_files``-narrowed install can commit a
# sync without a whole-kit release. Deliberately not a managed payload path.
SYNC_MANIFEST = "sync-manifest.json"
INTEGRITY_SCHEMA_VERSION = "1.0.0"
RECEIPT_DIR = Path("reports/_wip/managed-payload-integrity/receipts")
ACCEPTANCE_DIR = Path("reports/_wip/managed-payload-integrity/acceptance")
AUTHORING_RESULTS_DIR = Path("reports/_wip/managed-payload-integrity/authoring-results")
AUTHORING_POLICY = "canonical-authoring-v1"
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
    {"path": "nightshift_coordinator.py", "marker": "_accept_managed_payload", "kind": "executable"},
    {"path": "nightshift-instructions.py", "marker": "verify_terminal_integrity", "kind": "executable"},
    {"path": "parallel_executor.py", "marker": "terminal_gate", "kind": "executable-callback"},
    {"path": "run_validation.py", "marker": "verify_terminal_integrity", "kind": "executable"},
    {"path": "LOOP.md", "marker": "verify_terminal_integrity", "kind": "instruction"},
    {"path": "ORCHESTRATOR.md", "marker": "verify_terminal_integrity", "kind": "instruction"},
    {"path": "BOOTSTRAP.md", "marker": "verify_terminal_integrity", "kind": "instruction"},
    {"path": "Skills/nightshift/SKILL.md", "marker": "verify_terminal_integrity", "kind": "instruction"},
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
class AuthoringAnchor:
    """Parent-injected authority coordinates, never deserialized from worker output.

    The parent retains the expected digest and authoritative main ref before
    acceptance. An external pathname is containment, not authentication: the
    callable supplying this anchor is the trust boundary. Hosts sharing a UID
    must separately retain and validate the user authorization and verifier.
    """

    authority_path: Path
    authority_sha256: str
    main_ref: str = "refs/heads/main"


AuthoringProvider = Callable[[Path, str], AuthoringAnchor]


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
    synced_sha256: str | None = None


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


def _authoring_path(value: Any) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or ":" in value
            or any(ord(char) < 32 for char in value)
            or any(part in {"", ".", "..", ".nightshift"} for part in value.split("/"))):
        raise MetadataError("unsafe authoring path")
    return value


def _authoring_git(repo: Path, *args: str) -> str:
    result = _run_git(repo, *args)
    if result.returncode:
        raise MetadataError("authoring Git binding unavailable")
    return result.stdout.decode("utf-8", errors="strict").strip()


def _authoring_record(install: Path, spec_id: str, provider: AuthoringProvider) -> tuple[dict, AuthoringAnchor]:
    if not callable(provider):
        raise MetadataError("authoring authority requires a parent provider")
    anchor = provider(install, spec_id)
    if not isinstance(anchor, AuthoringAnchor):
        raise MetadataError("invalid parent authoring anchor")
    path = Path(anchor.authority_path)
    repo = _git_root(install)
    if (not path.is_absolute() or path.is_symlink() or repo in path.resolve().parents
            or not re.fullmatch(r"[0-9a-f]{64}", anchor.authority_sha256)
            or not anchor.main_ref.startswith("refs/heads/")):
        raise MetadataError("invalid external authoring anchor")
    body = path.read_bytes()
    if len(body) > MAX_ACCEPTANCE_BYTES or _sha256_bytes(body) != anchor.authority_sha256:
        raise MetadataError("parent-held authority digest mismatch")
    record = json.loads(body)
    fields = {"schema_version", "authorization_id", "policy", "user_authorization_sha256",
              "binding", "source_relative", "spec_id", "spec_path", "receipt_sha256",
              "invocation_id", "receipt_run_id", "baseline_revision", "baseline_manifest_fingerprint",
              "baseline_inventory_sha256", "scope_revision", "scope", "main_revision",
              "candidate_commit", "candidate_tree", "candidate_manifest_fingerprint", "independent_verification"}
    if not isinstance(record, dict) or set(record) != fields:
        raise MetadataError("invalid authoring authority schema")
    if (record["schema_version"] != "1.0.0" or record["policy"] != AUTHORING_POLICY
            or not isinstance(record["authorization_id"], str)
            or SAFE_ID.fullmatch(record["authorization_id"]) is None
            or record["spec_id"] != spec_id):
        raise MetadataError("invalid authoring policy or identity")
    for key in ("user_authorization_sha256", "receipt_sha256", "baseline_manifest_fingerprint",
                "baseline_inventory_sha256", "candidate_manifest_fingerprint"):
        if not isinstance(record[key], str) or re.fullmatch(r"[0-9a-f]{64}", record[key]) is None:
            raise MetadataError("invalid authoring digest")
    for key in ("baseline_revision", "scope_revision", "main_revision", "candidate_commit", "candidate_tree"):
        if not isinstance(record[key], str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", record[key]) is None:
            raise MetadataError("authoring requires full immutable Git identities")
    return record, anchor


def _authoring_candidate(install: Path, record: dict, anchor: AuthoringAnchor) -> Path:
    repo = _git_root(install)
    source = _authoring_path(record["source_relative"])
    _authoring_path(record["spec_path"])
    if (install != repo / source or record["binding"] != _git_binding(install)
            or (install / MARKER).exists() or (install / MARKER).is_symlink()):
        raise MetadataError("authoring authority does not own this source root")
    if (_authoring_git(repo, "rev-parse", anchor.main_ref) != record["main_revision"]
            or _authoring_git(repo, "rev-parse", "HEAD") != record["candidate_commit"]
            or _authoring_git(repo, "rev-parse", "HEAD^{tree}") != record["candidate_tree"]
            or _authoring_git(repo, "status", "--porcelain=v1", "--untracked-files=all")):
        raise MetadataError("dirty candidate or moved Git identity")
    for ancestor, descendant in ((record["main_revision"], record["candidate_commit"]),
                                 (record["scope_revision"], record["main_revision"]),
                                 (record["baseline_revision"], record["main_revision"])):
        if _run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode:
            raise MetadataError("authoring Git lineage mismatch")
    changed = _authoring_git(repo, "diff", "--name-only", "-z", record["main_revision"], record["candidate_commit"])
    if any(".nightshift" in PurePosixPath(path).parts for path in changed.split("\0") if path):
        raise MetadataError("source authoring cannot include dogfooded install edits")
    return repo


def _authoring_verdict(record: dict) -> None:
    # This normalized binding is retained only AFTER the parent independently
    # validates the original verdict's schema, identity, independence and clean
    # footprint. A worker boolean or green suite cannot populate this authority.
    verdict = record["independent_verification"]
    expected = {"verifier_identity_sha256", "verdict_sha256", "candidate_commit", "candidate_tree", "policy"}
    if not isinstance(verdict, dict) or set(verdict) != expected:
        raise MetadataError("external independent verification is required")
    for key in ("candidate_commit", "candidate_tree", "policy"):
        if verdict[key] != record[key]:
            raise MetadataError("independent verification candidate mismatch")
    for key in ("verifier_identity_sha256", "verdict_sha256"):
        if not isinstance(verdict[key], str) or re.fullmatch(r"[0-9a-f]{64}", verdict[key]) is None:
            raise MetadataError("invalid independent verification binding")


def _authoring_manifest_at(repo: Path, record: dict, revision: str) -> dict:
    manifest = json.loads(_authoring_git(repo, "show", f"{revision}:{record['source_relative']}/release-manifest.json"))
    _authoring_inventory(manifest)
    return manifest


def _authoring_inventory(manifest: dict) -> dict[str, dict]:
    _manifest_index(manifest, label="authoring manifest")
    for row in manifest["files"]:
        _authoring_path(row["path"])
        if type(row.get("executable")) is not bool or is_ignored_python_cache_path(row["path"]):
            raise MetadataError("invalid authoring inventory mode or generated entry")
    return {row["path"]: row for row in _manifest_inventory(manifest)}


def _authoring_scope(repo: Path, install: Path, record: dict):
    import scope_guard
    import yaml

    spec_text = _authoring_git(repo, "show", f"{record['scope_revision']}:{record['spec_path']}")
    metadata = yaml.safe_load(spec_text.split("---", 2)[1])
    if not isinstance(metadata, dict) or metadata.get("id") != record["spec_id"] or not metadata.get("scope"):
        raise MetadataError("explicit approved main scope required")
    scope = scope_guard.scope_from_main(repo, record["spec_path"], record["scope_revision"])
    if asdict(scope) != record["scope"] or not scope.write:
        raise MetadataError("parent scope does not match approved main")
    return scope


def _authoring_committed_inventory(repo: Path, source: str, revision: str, inventory: dict) -> None:
    """Prove retained baseline/main manifests describe the actual Git objects."""
    result = _run_git(repo, "ls-tree", "-rz", revision, "--", source)
    if result.returncode:
        raise MetadataError("retained Git tree unavailable")
    tree = {}
    for entry in result.stdout.split(b"\0"):
        if entry:
            info, path = entry.split(b"\t", 1)
            tree[path.decode()] = info.decode().split()
    objects = []
    for path, row in inventory.items():
        mode, kind, oid = tree.get(f"{source}/{path}", ("", "", ""))
        if kind != "blob" or mode != ("100755" if row["executable"] else "100644"):
            raise MetadataError("retained managed path missing or wrong mode")
        objects.append((oid, row["sha256"]))
    result = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                            input="".join(oid + "\n" for oid, _digest in objects).encode(),
                            capture_output=True, check=False)
    if result.returncode:
        raise MetadataError("retained managed blobs unavailable")
    offset = 0
    for oid, digest in objects:
        end = result.stdout.index(b"\n", offset)
        observed_oid, kind, length = result.stdout[offset:end].decode().split()
        start, size = end + 1, int(length)
        content = result.stdout[start:start + size]
        if observed_oid != oid or kind != "blob" or _sha256_bytes(content) != digest:
            raise MetadataError("retained manifest does not describe committed bytes")
        offset = start + size + 1
    if offset != len(result.stdout):
        raise MetadataError("unexpected retained blob response")


def _compare_authoring_payload(install: Path, repo: Path, record: dict, receipt: dict) -> tuple[list[str], str]:
    import scope_guard
    import release
    from validate_install import runtime_closure_gaps

    baseline = _authoring_manifest_at(repo, record, record["baseline_revision"])
    if (baseline["fingerprint"] != record["baseline_manifest_fingerprint"]
            or baseline["fingerprint"] != receipt["release"]["manifest_fingerprint"]
            or baseline["fingerprint"] != receipt["release"]["release_fingerprint"]
            or _inventory_digest(baseline) != record["baseline_inventory_sha256"]
            or _inventory_digest(baseline) != receipt["release"]["manifest_inventory_sha256"]):
        raise MetadataError("retained baseline does not reconstruct original admission")
    candidate = load_manifest(install / "release-manifest.json")
    committed = _authoring_manifest_at(repo, record, record["candidate_commit"])
    if candidate != committed or candidate["fingerprint"] != record["candidate_manifest_fingerprint"]:
        raise MetadataError("candidate manifest binding mismatch")
    old, new = _authoring_inventory(baseline), _authoring_inventory(candidate)
    _authoring_committed_inventory(repo, record["source_relative"], record["baseline_revision"], old)
    if not old.keys() <= new.keys():
        raise MetadataError("baseline managed coverage cannot be removed")
    scope = _authoring_scope(repo, install, record)
    changed = sorted(path for path in new if old.get(path) != new[path])
    main = _authoring_inventory(_authoring_manifest_at(repo, record, record["main_revision"]))
    _authoring_committed_inventory(repo, record["source_relative"], record["main_revision"], main)
    # Main can change an admitted file that the candidate restores unchanged,
    # or add coverage that the candidate omits. Neither appears in `changed`.
    for path in old.keys() | main.keys() | new.keys():
        if old.get(path) != main.get(path) and main.get(path) != new.get(path):
            raise MetadataError("conflicting integration-base managed change")
    for path in changed:
        relative = f"{record['source_relative']}/{path}"
        if not scope_guard.classify_write(relative, scope, repo, install, record["spec_path"]).allowed:
            raise MetadataError("managed change outside approved main scope")
    observations, observed_sha = _observe_payload(install, candidate)
    if any(row["observed_kind"] != "file" or row["observed_sha256"] != row["expected_sha256"]
           or row["observed_executable"] != row["expected_executable"] for row in observations):
        raise MetadataError("candidate payload differs from complete manifest")
    # Ignored/untracked managed files and Git symlinks cannot hide behind a
    # clean status. Verify every actual payload against the pinned Git tree.
    tree_result = _run_git(repo, "ls-tree", "-rz", record["candidate_commit"], "--", record["source_relative"])
    if tree_result.returncode:
        raise MetadataError("candidate tree unavailable")
    tree = {}
    for entry in tree_result.stdout.split(b"\0"):
        if entry:
            info, path = entry.split(b"\t", 1)
            tree[path.decode()] = info.decode().split()
    object_format = _authoring_git(repo, "rev-parse", "--show-object-format")
    for path, row in new.items():
        content = (install / path).read_bytes()
        blob = hashlib.new(object_format, f"blob {len(content)}\0".encode() + content).hexdigest()
        expected = ["100755" if row["executable"] else "100644", "blob", blob]
        if tree.get(f"{record['source_relative']}/{path}") != expected:
            raise MetadataError("managed payload is not the pinned committed blob")
    names = sorted(new)
    if (_release_owned_aliases(install, candidate) or runtime_closure_gaps(install, names)
            or release.managed_local_resource_gaps(install, names) or terminal_entrypoint_gaps(install)):
        raise MetadataError("candidate runtime-resource closure is incomplete")
    return changed, observed_sha


def _verify_authoring_integrity(install: Path, *, spec_id: str, receipt_ref: str,
                               receipt_sha256: str, run_id: str | None,
                               authoring_provider: AuthoringProvider) -> AcceptanceResult:
    record = None
    anchor = None
    changed: list[str] = []
    observed = None
    outcome, reason = INDETERMINATE, "NS-MPI-AUTHORING-INVALID"
    try:
        record, anchor = _authoring_record(install, spec_id, authoring_provider)
        repo = _authoring_candidate(install, record, anchor)
        _authoring_verdict(record)
        receipt, _body = _load_receipt(install, receipt_ref, receipt_sha256)
        if (receipt_sha256 != record["receipt_sha256"] or receipt["invocation_id"] != record["invocation_id"]
                or receipt["binding"] != record["binding"]
                or receipt["identity"] != {"project_sha256": record["binding"]["git_common_dir_sha256"],
                                           "run_sha256": _digest_text(record["receipt_run_id"]),
                                           "spec_sha256": _digest_text(spec_id)}
                or (run_id is not None and run_id != record["receipt_run_id"])
                or receipt["release"]["release_marker_sha256"] is not None):
            raise MetadataError("authoring receipt identity mismatch")
        changed, observed = _compare_authoring_payload(install, repo, record, receipt)
        # Recheck the serialized main/candidate pin after reading all payloads.
        _authoring_candidate(install, record, anchor)
        outcome, reason = ALLOW, "NS-MPI-AUTHORING-CLEAN"
    except Exception:
        # Provider/storage/parser exceptions are private diagnostics, never
        # public acceptance evidence or a reason to fall back to strict success.
        pass
    if record is None or anchor is None:
        return AcceptanceResult(outcome, reason, None, None)
    artifact = {"schema_version": "1.0.0", "authorization_id": record["authorization_id"],
                "authority_sha256": anchor.authority_sha256, "outcome": outcome, "reason_code": reason,
                "receipt_sha256": record["receipt_sha256"], "policy": AUTHORING_POLICY,
                "baseline_revision": record["baseline_revision"], "scope_revision": record["scope_revision"],
                "main_revision": record["main_revision"], "candidate_commit": record["candidate_commit"],
                "candidate_tree": record["candidate_tree"], "baseline_reconstruction": "retained-git-manifest",
                "observed_inventory_sha256": observed, "changed_paths": changed,
                "privacy": {"relative_paths_only": True, "content_included": False}}
    body = _canonical_json(artifact)
    try:
        root = _safe_artifact_root(install, AUTHORING_RESULTS_DIR)
        dest = root / f"{record['authorization_id']}.json"
        digest, _replayed = _atomic_write_new(dest, body, limit=MAX_ACCEPTANCE_BYTES)
        return AcceptanceResult(outcome, reason, dest.relative_to(install).as_posix(), digest, tuple(changed[:MAX_REPORTED_PATHS]))
    except FileExistsError:
        try:
            quarantine = _safe_artifact_root(install, AUTHORING_RESULTS_DIR / "quarantine")
            _atomic_write_new(quarantine / f"{record['authorization_id']}-{_sha256_bytes(body)}.json", body, limit=MAX_ACCEPTANCE_BYTES)
        except (OSError, MetadataError):
            pass
        return AcceptanceResult(INDETERMINATE, REASON_DUPLICATE_CONTRADICTION, None, None)
    except (OSError, MetadataError, ValueError):
        return AcceptanceResult(INDETERMINATE, REASON_ARTIFACT_FAILURE, None, None)


def verify_terminal_integrity(
    install: Path,
    *,
    spec_id: str,
    receipt_ref: str,
    receipt_sha256: str,
    run_id: str | None = None,
    authoring_provider: AuthoringProvider | None = None,
) -> AcceptanceResult:
    """Compare the admitted manifest payload before any result acceptance action."""
    install = install.resolve()
    if authoring_provider is not None:
        return _verify_authoring_integrity(install, spec_id=spec_id, receipt_ref=receipt_ref,
                                          receipt_sha256=receipt_sha256, run_id=run_id,
                                          authoring_provider=authoring_provider)
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


def sync_receipt_index(install: Path) -> dict[str, str]:
    """Return the path -> sha256 index of the last ``nightshift-sync.py`` delivery (BUG-339).

    Only ever *widens* what the hook-path guard accepts, so unlike ``retained_manifest`` it
    is tolerant: a missing, unreadable or malformed receipt (or entry) yields no exemption.
    """
    try:
        payload = json.loads((install / SYNC_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, dict):
        return {}
    return {
        path: digest
        for path, digest in files.items()
        if isinstance(path, str)
        and path
        and not PurePosixPath(path).is_absolute()
        and ".." not in PurePosixPath(path).parts
        and isinstance(digest, str)
        and len(digest) == 64
        and all(char in "0123456789abcdef" for char in digest)
    }


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
    hook_path = current_manifest is None
    sync_index: dict[str, str] = {}
    if retained is not None:
        _manifest_index(retained, label="recovered historical release manifest")
    if current_manifest is not None:
        current_index = _manifest_index(current_manifest, label="current manifest")
        candidate_paths = set(current_index)
    else:
        # Installed hooks use the exact release manifest retained in the marker.
        # BUG-339: that marker is only ever written by a whole-kit release, so it cannot
        # vouch for bytes ``nightshift-sync.py`` delivered later (SPEC-356 AC4 forbids a
        # narrowed sync from touching it, and a never-released install has none). The
        # sync receipt is the delivering process's own record of those bytes; it is read
        # on this path only, where no live canonical manifest exists to compare against.
        sync_index = sync_receipt_index(install)
        try:
            retained = retained_manifest(install)
        except MetadataError:
            if not sync_index:
                raise
            retained = None
        current_manifest = retained
        current_index = (
            _manifest_index(current_manifest, label="current manifest")
            if current_manifest is not None
            else {}
        )
        candidate_paths = set(current_index) | set(sync_index)

    selected = staged if staged_only else dirty
    managed_dirty: list[tuple[str, str]] = []
    for managed_path in sorted(candidate_paths):
        repo_path = f"{install_prefix}/{managed_path}" if install_prefix else managed_path
        if repo_path in selected:
            managed_dirty.append((managed_path, repo_path))
    if not managed_dirty:
        return []

    if retained is None and not hook_path:
        retained = retained_manifest(install)
    retained_index = (
        _manifest_index(retained, label="retained release manifest") if retained is not None else {}
    )

    rows: list[PathProvenance] = []
    for managed_path, repo_path in managed_dirty:
        actual = _sha256_file(install / managed_path)
        current = current_index.get(managed_path)
        prior = retained_index.get(managed_path)
        synced = sync_index.get(managed_path)
        if actual is not None and actual == current:
            classification = EXACT_CURRENT
        elif actual is not None and actual == synced:
            classification = SYNC_RECONCILED
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
                synced_sha256=synced,
            )
        )
    return rows


def _index_entry(repo: Path, repo_relative: str) -> tuple[str, bytes] | None:
    """Return ``(mode, bytes)`` of a path's single stage-0 index entry, else ``None``."""
    listed = _run_git(repo, "ls-files", "-s", "-z", "--", repo_relative)
    if listed.returncode:
        return None
    records = [record for record in listed.stdout.split(b"\0") if record]
    if len(records) != 1:  # absent, or an unresolved merge with stages 1-3
        return None
    meta, _, _name = records[0].partition(b"\t")
    fields = meta.split()
    if len(fields) != 3 or fields[2] != b"0":
        return None
    shown = _run_git(repo, "show", f":{repo_relative}")
    return (fields[0].decode(), shown.stdout) if shown.returncode == 0 else None


def _is_canonical_origin_update(install: Path, row: PathProvenance) -> bool:
    """SPEC-364: is ``row`` the canonical source's own same-commit dogfood update?

    The hook-path guard (no ``current_manifest``) treats the marker's retained
    release as "current", so a dogfooded install can never accept bytes newer than
    its last release -- even when they arrive together with the canonical source
    they were copied from. That is only legitimate where the install *is* the
    canonical origin, established structurally: ``install`` is a ``.nightshift/``
    directly beneath a directory holding a ``release-manifest.json`` that registers
    the path. Provenance is the commit itself: the path's stage-0 index bytes and
    mode must equal those of ``<origin>/<path>``, which must also be changed by
    this same commit. No environment variable or signoff is consulted, and any
    other divergence (including an unchanged canonical source) is not admitted.
    """
    if row.classification != UNRESOLVED_DIVERGENCE or not row.staged or row.actual_sha256 is None:
        return False
    install = install.resolve()
    origin = install.parent
    if install.name != ".nightshift":
        return False
    try:
        repo = _git_root(install)
        origin_prefix = "" if origin == repo else origin.relative_to(repo).as_posix()
        install_prefix = install.relative_to(repo).as_posix().rstrip("/")
    except (MetadataError, ValueError):
        return False

    def repo_path(prefix: str, relative: str) -> str:
        return f"{prefix}/{relative}" if prefix else relative

    registry = _index_entry(repo, repo_path(origin_prefix, "release-manifest.json"))
    installed = _index_entry(repo, repo_path(install_prefix, row.path))
    source_path = repo_path(origin_prefix, row.path)
    source = _index_entry(repo, source_path)
    if registry is None or installed is None or source is None:
        return False
    try:
        registered = _manifest_index(json.loads(registry[1].decode("utf-8")), label="origin manifest")
    except (UnicodeDecodeError, json.JSONDecodeError, MetadataError):
        return False
    installed_sha = _sha256_bytes(installed[1])
    source_sha = _sha256_bytes(source[1])
    return (
        row.path in registered
        and installed_sha == row.actual_sha256  # the commit carries what is on disk
        and installed_sha == source_sha
        and installed[0] == source[0]
        and source_sha != _head_hash(repo, source_path)  # authored by this same commit
    )


def guard_staged_install(install: Path) -> list[PathProvenance]:
    """Return staged managed paths that are not exact release payload bytes.

    SPEC-364: a byte-identical same-commit canonical + dogfood update in the
    canonical origin repository is not a divergence (see ``_is_canonical_origin_update``).

    BUG-339: bytes that match the ``nightshift-sync.py`` delivery receipt
    (``SYNC_RECONCILED``) are a sanctioned delivery, not a divergence; an edit that matches
    neither a release nor the receipt still is.
    """
    return [
        row
        for row in audit_git_install(install, staged_only=True)
        if row.classification not in (EXACT_CURRENT, SYNC_RECONCILED)
        and not _is_canonical_origin_update(install, row)
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
        synced = f"synced={_short(row.synced_sha256)}; " if row.synced_sha256 else ""
        lines.append(
            f"{row.path}: {row.classification}; actual={_short(row.actual_sha256)}; "
            f"current={_short(row.current_sha256)}; retained={_short(row.retained_sha256)}; "
            f"{synced}"
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
    if args.staged and any(row.classification not in (EXACT_CURRENT, SYNC_RECONCILED) for row in rows):
        print(format_guidance(rows), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
