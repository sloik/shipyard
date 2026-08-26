#!/usr/bin/env python3
"""Immutable, private Dropbox observability artifacts for Nightshift.

This module deliberately has no implicit configuration.  It is a storage boundary,
not a lifecycle store: callers opt in with ``observability.sink: private-dropbox``
and pass only already-redacted, allowlisted payloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from private_state import PrivateStateError, _merged_yaml

PRIVATE_DROPBOX = "private-dropbox"
SCHEMA_VERSION = 1
ARTIFACT_KINDS = frozenset({
    "origin",
    "location",
    "provenance",
    "event",
    "run_manifest",
    "experiment_event",
    "experiment_result",
})
_URL = re.compile(r"(?:https?://|ssh://|git@)", re.I)
_SECRET = re.compile(r"(?:api[_-]?key|secret|password|token|authorization|bearer)\\s*[:=]", re.I)


class ObservabilityStoreError(PrivateStateError):
    """Raised before private observability state can be exposed or corrupted."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def fingerprint(value: str | Path) -> str:
    """Return the only location representation permitted in stored artifacts."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def load_observability_sink(config_path: Path) -> str | None:
    """Read the explicit sink selector; absent means disabled, invalid fails closed."""
    config = _merged_yaml(Path(config_path))
    section = config.get("observability")
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ObservabilityStoreError("observability must be a mapping")
    sink = section.get("sink")
    if sink is None:
        return None
    if sink != PRIVATE_DROPBOX:
        raise ObservabilityStoreError("observability.sink must be private-dropbox")
    return PRIVATE_DROPBOX


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ObservabilityStoreError(result.stderr.strip() or "Git provenance query failed")
    return result.stdout.strip()


def _is_relative_to(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _validated_root(repo: Path, root: Path) -> Path:
    repo = repo.resolve()
    if not root.is_absolute():
        raise ObservabilityStoreError("NIGHTSHIFT_DROPBOX_ROOT must be absolute")
    root = root.resolve(strict=False)
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise ObservabilityStoreError("private Dropbox root must be an existing non-symlink directory")
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    protected = [repo, common.resolve()]
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            protected.append(Path(line.split(" ", 1)[1]).resolve())
    if any(_is_relative_to(root, path) or _is_relative_to(path, root) for path in protected):
        raise ObservabilityStoreError("private Dropbox root overlaps repository, common Git directory, or worktree")
    if (root / ".git").exists():
        raise ObservabilityStoreError("private Dropbox root may not be a public clone")
    return root


def _safe_component(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {"", ".", ".."}:
        raise ObservabilityStoreError("unsafe artifact path component")
    return path.parts[0]


def _sanitize(value: Any) -> Any:
    """Reject raw sensitive content instead of attempting lossy redaction."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\\\/]", value) or _URL.search(value) or _SECRET.search(value):
            raise ObservabilityStoreError("forbidden raw path, URL, or secret-shaped value")
        return value
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {str(_safe_component(str(key))): _sanitize(item) for key, item in value.items()}
    raise ObservabilityStoreError("observability payload contains unsupported value type")


@dataclass(frozen=True)
class StoreContext:
    root: Path
    repo: Path
    project_id: str
    common_fingerprint: str
    checkout_fingerprint: str


def enroll(config_path: Path, repo: Path, *, now: datetime | None = None) -> StoreContext:
    """Enroll one stable private project identity, preserving an immutable origin record."""
    if load_observability_sink(config_path) != PRIVATE_DROPBOX:
        raise ObservabilityStoreError("private Dropbox observability is not explicitly enabled")
    if not os.environ.get("NIGHTSHIFT_DROPBOX_ROOT"):
        raise ObservabilityStoreError("NIGHTSHIFT_DROPBOX_ROOT is required")
    repo = Path(repo).resolve()
    root = _validated_root(repo, Path(os.environ["NIGHTSHIFT_DROPBOX_ROOT"]))
    common = _git(repo, "rev-parse", "--git-common-dir")
    common_path = Path(common) if Path(common).is_absolute() else repo / common
    common_fp = fingerprint(common_path.resolve())
    checkout_fp = fingerprint(repo)
    registry = root / "nightshift-observability" / "registry" / f"{common_fp}.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    if registry.exists():
        if registry.is_symlink() or not registry.is_file():
            raise ObservabilityStoreError("private registry entry is not a regular file")
        try:
            project_id = str(json.loads(registry.read_text(encoding="utf-8"))["project_id"])
            uuid.UUID(project_id)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ObservabilityStoreError("private registry entry is invalid") from exc
    else:
        project_id = str(uuid.uuid4())
        _atomic_create(registry, _canonical({"schema_version": SCHEMA_VERSION, "project_id": project_id, "common_fingerprint": common_fp}))
    context = StoreContext(root, repo, project_id, common_fp, checkout_fp)
    existing_origins = read_artifacts(context, kind="origin")
    existing_origin = next(
        (record for record in existing_origins if record.get("artifact_id") == checkout_fp),
        None,
    )
    if existing_origin is None:
        origin = _origin_payload(context, repo, now=now)
        # A project can legitimately be observed from several linked or moved
        # checkouts. Keep each checkout's first provenance observation immutable.
        _put(context, "origin", checkout_fp, origin)
    else:
        origin = existing_origin.get("payload")
        expected_identity = {
            "project_id": project_id,
            "common_fingerprint": common_fp,
            "checkout_fingerprint": checkout_fp,
            "source_locator": f"git-common:{common_fp}",
        }
        if not isinstance(origin, dict) or any(
            origin.get(key) != expected for key, expected in expected_identity.items()
        ):
            raise ObservabilityStoreError("private origin identity does not match enrollment")
    _put(context, "location", checkout_fp, {"checkout_fingerprint": checkout_fp, "observed_at": origin["created_at"]})
    return context


def _origin_payload(context: StoreContext, repo: Path, *, now: datetime | None) -> dict[str, Any]:
    stamp = (now or datetime.now(UTC)).isoformat()
    return {
        "project_id": context.project_id, "common_fingerprint": context.common_fingerprint,
        "checkout_fingerprint": context.checkout_fingerprint, "base_revision_fingerprint": fingerprint(_git(repo, "rev-parse", "HEAD")),
        "head_revision_fingerprint": fingerprint(_git(repo, "rev-parse", "HEAD")),
        "source_locator": f"git-common:{context.common_fingerprint}",
        "kit_version": "unknown", "created_at": stamp,
    }


def _atomic_create(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            return
    finally:
        Path(name).unlink(missing_ok=True)


def _put(context: StoreContext, kind: str, object_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    _validated_root(context.repo, context.root)
    kind, object_id = _safe_component(kind), _safe_component(object_id)
    if kind not in ARTIFACT_KINDS:
        raise ObservabilityStoreError("artifact kind is not allowlisted")
    safe = _sanitize(dict(payload))
    record = {"schema_version": SCHEMA_VERSION, "artifact_id": object_id, "kind": kind, "payload": safe}
    # Timestamps prove observation time but are intentionally excluded from the
    # content address: the same controlled observation retried later is identical.
    hashable = {
        **record,
        "payload": {
            key: value for key, value in safe.items()
            if key not in {"created_at", "observed_at"}
        },
    }
    record["content_hash"] = hashlib.sha256(_canonical(hashable)).hexdigest()
    target = context.root / "nightshift-observability" / "projects" / context.project_id / "objects" / kind / f"{object_id}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("content_hash") == record["content_hash"]:
            return {"status": "idempotent", "content_hash": record["content_hash"]}
        quarantine = target.parent.parent.parent / "quarantine" / f"{object_id}-{record['content_hash']}.json"
        _atomic_create(quarantine, _canonical(record))
        raise ObservabilityStoreError("duplicate artifact ID has divergent content; quarantined")
    if kind in {"event", "experiment_event"}:
        for existing_path in target.parent.glob("*.json") if target.parent.exists() else []:
            if existing_path.is_symlink() or not existing_path.is_file():
                raise ObservabilityStoreError("event store contains invalid partial artifact")
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_payload = existing.get("payload", {})
            existing_sequence = existing_payload.get("run_sequence")
            candidate_sequence = safe.get("run_sequence")
            if existing_sequence == candidate_sequence:
                if kind == "experiment_event":
                    existing_event = existing_payload.get("experiment_event")
                    candidate_event = safe.get("experiment_event")
                    existing_experiment = (
                        existing_event.get("experiment_id")
                        if isinstance(existing_event, dict) else None
                    )
                    candidate_experiment = (
                        candidate_event.get("experiment_id")
                        if isinstance(candidate_event, dict) else None
                    )
                    if (
                        isinstance(existing_experiment, str)
                        and isinstance(candidate_experiment, str)
                        and existing_experiment != candidate_experiment
                    ):
                        continue
                quarantine = target.parent.parent.parent / "quarantine" / f"{object_id}-{record['content_hash']}.json"
                _atomic_create(quarantine, _canonical(record))
                raise ObservabilityStoreError("stream sequence conflicts with immutable event; quarantined")
    _atomic_create(target, _canonical(record))
    return {"status": "stored", "content_hash": record["content_hash"], "path_fingerprint": fingerprint(target)}


def write_artifact(context: StoreContext, *, kind: str, artifact_id: str, run_sequence: int, producer: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Store one immutable record; repeated UUIDs are idempotent only byte-for-byte."""
    try:
        uuid.UUID(artifact_id)
    except ValueError as exc:
        raise ObservabilityStoreError("artifact_id must be a UUID") from exc
    if not isinstance(run_sequence, int) or run_sequence < 0 or not producer:
        raise ObservabilityStoreError("run_sequence and producer are required controlled metadata")
    body = {"project_id": context.project_id, "run_sequence": run_sequence, "producer": _safe_component(producer), "created_at": datetime.now(UTC).isoformat(), **dict(payload)}
    return _put(context, kind, artifact_id, body)


def seal_to_outbox(context: StoreContext, record: Mapping[str, Any]) -> dict[str, str]:
    """Write an immutable fallback object outside the repository when Dropbox is unavailable."""
    raw = os.environ.get("NIGHTSHIFT_OUTBOX_ROOT")
    if not raw:
        raise ObservabilityStoreError("NIGHTSHIFT_OUTBOX_ROOT is required for sealed outbox")
    outbox = Path(raw).resolve(strict=False)
    if _is_relative_to(outbox, context.root):
        raise ObservabilityStoreError("outbox must be independent of Dropbox root")
    data = _canonical(_sanitize(dict(record)))
    digest = hashlib.sha256(data).hexdigest()
    _atomic_create(outbox / "nightshift-observability-outbox" / context.project_id / f"{digest}.json", data)
    return {"status": "awaiting_sync", "content_hash": digest}


def write_or_outbox(
    context: StoreContext, *, kind: str, artifact_id: str, run_sequence: int,
    producer: str, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Best-effort transport wrapper which never changes a caller's run outcome.

    Only transport/root failures are deferred.  Payload or provenance violations
    remain hard failures so unsafe material is never quietly retained in an outbox.
    """
    try:
        return write_artifact(
            context, kind=kind, artifact_id=artifact_id, run_sequence=run_sequence,
            producer=producer, payload=payload,
        )
    except ObservabilityStoreError as exc:
        if not any(word in str(exc) for word in ("root", "Git provenance", "No such file", "Dropbox")):
            raise
        return seal_to_outbox(context, {
            "artifact_id": artifact_id,
            "kind": kind,
            "payload": {
                "project_id": context.project_id,
                "run_sequence": run_sequence,
                "producer": _safe_component(producer),
                **dict(payload),
            },
        })


def read_artifacts(context: StoreContext, *, kind: str) -> list[dict[str, Any]]:
    """Read one allowlisted immutable-object collection in stable order.

    Callers still validate their domain payloads. This boundary verifies the
    private root, regular-file shape, object kind, and content address before
    returning any record.
    """
    _validated_root(context.repo, context.root)
    kind = _safe_component(kind)
    if kind not in ARTIFACT_KINDS:
        raise ObservabilityStoreError("artifact kind is not allowlisted")
    folder = (
        context.root
        / "nightshift-observability"
        / "projects"
        / context.project_id
        / "objects"
        / kind
    )
    records: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if path.is_symlink() or not path.is_file():
            raise ObservabilityStoreError("private object collection contains invalid entry")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObservabilityStoreError("private object is unreadable or corrupt") from exc
        if not isinstance(record, dict) or record.get("kind") != kind:
            raise ObservabilityStoreError("private object kind is invalid")
        hashable = {
            key: value for key, value in record.items() if key != "content_hash"
        }
        payload = hashable.get("payload")
        if isinstance(payload, dict):
            hashable["payload"] = {
                key: value
                for key, value in payload.items()
                if key not in {"created_at", "observed_at"}
            }
        expected = hashlib.sha256(_canonical(hashable)).hexdigest()
        if record.get("content_hash") != expected:
            raise ObservabilityStoreError("private object content hash mismatch")
        records.append(record)
    return records


def _relative_evidence_ref(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ObservabilityStoreError("evidence reference must be a safe relative path")
    return path.as_posix()


def project_run(
    context: StoreContext,
    *,
    run_id: str,
    spec_id: str,
    run_sequence: int,
    evidence: Mapping[str, Path],
    events: list[Mapping[str, Any]],
    kit_version: str = "unknown",
    schema_version: int = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Project a complete, hash-only run contract into the private store.

    The manifest deliberately contains references and content hashes, never file
    bodies or checkout paths.  This gives fleet analytics immutable provenance
    while preserving the public repository boundary.
    """
    if not run_id or not spec_id or run_sequence < 0:
        raise ObservabilityStoreError("run identity and sequence are required")
    approved = {"report", "metrics", "validation", "attempt", "events"}
    if set(evidence) - approved:
        raise ObservabilityStoreError("unapproved run evidence kind")
    entries: list[dict[str, str]] = []
    for kind, path in sorted(evidence.items()):
        evidence_ref = _relative_evidence_ref(Path(path).as_posix())
        source = context.repo / evidence_ref
        if source.is_symlink() or not source.is_file():
            raise ObservabilityStoreError("run evidence must be a regular file")
        entries.append({
            "kind": kind,
            "evidence_ref": evidence_ref,
            "content_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    approved_events = []
    from loop_events import RECOVERY_EVENT_TYPES, validate_recovery_event
    for event in events:
        event_type = str(event.get("event", ""))
        if event_type in RECOVERY_EVENT_TYPES:
            payload = {key: value for key, value in event.items() if key not in {"event", "run_id"}}
            validate_recovery_event(event_type, payload)
            approved_events.append({
                "event": event_type,
                "content_hash": hashlib.sha256(_canonical(payload)).hexdigest(),
            })
    artifact_id = str(uuid.uuid5(uuid.UUID(context.project_id), f"{run_id}:{spec_id}"))
    payload = {
        "project_id": context.project_id,
        "spec_id": _safe_component(spec_id),
        "run_id": _safe_component(run_id),
        "primary_origin": context.common_fingerprint,
        "execution_worktree": context.checkout_fingerprint,
        "kit_version": _safe_component(kit_version),
        "projection_schema": schema_version,
        "evidence": entries,
        "approved_events": approved_events,
    }
    return write_or_outbox(
        context, kind="run_manifest", artifact_id=artifact_id,
        run_sequence=run_sequence, producer="run_projection", payload=payload,
    )


def reconcile_outbox(context: StoreContext) -> dict[str, int]:
    raw = os.environ.get("NIGHTSHIFT_OUTBOX_ROOT")
    if not raw:
        raise ObservabilityStoreError("NIGHTSHIFT_OUTBOX_ROOT is required for reconciliation")
    folder = Path(raw).resolve() / "nightshift-observability-outbox" / context.project_id
    imported = 0
    for item in sorted(folder.glob("*.json")) if folder.exists() else []:
        if item.is_symlink() or not item.is_file():
            raise ObservabilityStoreError("outbox contains invalid partial artifact")
        payload = json.loads(item.read_text(encoding="utf-8"))
        artifact_id = str(payload.get("artifact_id", ""))
        kind = str(payload.get("kind", "event"))
        if not artifact_id:
            raise ObservabilityStoreError("outbox artifact lacks artifact_id")
        _put(context, kind, artifact_id, payload.get("payload", {}))
        imported += 1
    return {"imported": imported}
