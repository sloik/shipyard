"""Closed, privacy-preserving public protocol for observational extensions.

The module has no extension import/callback surface.  Core writes immutable facts
and durable jobs; an out-of-process supervisor consumes them independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class ProtocolError(ValueError):
    pass


class EventName(StrEnum):
    RUN_STARTED = "run.started"
    WORK_COMPLETED = "work.completed"
    VERIFICATION_REQUESTED = "verification.requested"
    VERIFICATION_COMPLETED = "verification.completed"
    RUN_COMPLETED = "run.completed"


class Capability(StrEnum):
    ARTIFACT_REFS_READ = "artifact_refs.read"
    ARTIFACTS_WRITE = "artifacts.write"
    STATE_READ_WRITE = "state.read_write"
    BACKGROUND_CONTINUE = "background.continue"
    NETWORK_LOOPBACK = "network.loopback"


class JobState(StrEnum):
    PLANNED = "planned"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    INVALID = "invalid"
    ABANDONED = "abandoned"
    COMPLETED_AFTER_RUN = "completed-after-run"


EVENTS = frozenset(x.value for x in EventName)
CAPABILITIES = frozenset(x.value for x in Capability)
TERMINAL_STATES = frozenset(
    x.value
    for x in JobState
    if x not in {JobState.PLANNED, JobState.CLAIMED, JobState.RUNNING}
)

# Every stable payload is closed and categorical/content-addressed.
PAYLOAD_FIELDS = {
    EventName.RUN_STARTED.value: {"run_kind", "spec_id", "config_digest"},
    EventName.WORK_COMPLETED.value: {"spec_id", "outcome", "artifact_refs"},
    EventName.VERIFICATION_REQUESTED.value: {"spec_id", "artifact_refs"},
    EventName.VERIFICATION_COMPLETED.value: {"spec_id", "outcome", "artifact_refs"},
    EventName.RUN_COMPLETED.value: {"run_kind", "outcome", "artifact_refs"},
}
RUN_KINDS = frozenset({"run", "kickoff"})
OUTCOMES = frozenset({"passed", "failed", "blocked", "cancelled", "unknown"})


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return sha256_bytes(canonical(value))


def identifier(value: Any, label: str = "identifier") -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProtocolError(f"invalid {label}")
    return value


def semantic_version(value: Any, label: str = "version") -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ProtocolError(f"invalid {label}")
    return value


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProtocolError(f"{label} must be a positive integer")
    return value


def safe_relative(value: Any, label: str = "path") -> str:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        raise ProtocolError(f"unsafe {label}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ProtocolError(f"unsafe {label}")
    return value


def resolve_beneath(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    """Resolve beneath a non-symlink root, rejecting every symlink ancestor."""
    relative = safe_relative(relative)
    root = Path(root)
    if root.is_symlink():
        raise ProtocolError("root may not be a symlink")
    root_resolved = root.resolve(strict=must_exist)
    current = root_resolved
    for component in PurePosixPath(relative).parts:
        current = current / component
        if current.is_symlink():
            raise ProtocolError("symlink path component")
    if must_exist and not current.exists():
        raise ProtocolError("path unavailable")
    resolved = current.resolve(strict=must_exist)
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ProtocolError("path escapes root")
    return resolved


def _artifact_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"name", "sha256", "size"}:
        raise ProtocolError("artifact reference schema is closed")
    name = safe_relative(value["name"], "artifact name")
    if not isinstance(value["sha256"], str) or not _SHA.fullmatch(value["sha256"]):
        raise ProtocolError("artifact reference is not content addressed")
    size = positive_int(value["size"], "artifact size")
    return {"name": name, "sha256": value["sha256"], "size": size}


def validate_envelope(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "event_id",
        "run_id",
        "sequence",
        "event",
        "timestamp",
        "payload",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ProtocolError("event envelope schema is closed")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ProtocolError("unsupported event schema")
    try:
        uuid.UUID(value["event_id"])
    except (TypeError, ValueError) as exc:
        raise ProtocolError("invalid event id") from exc
    run_id = identifier(value["run_id"], "run id")
    sequence = positive_int(value["sequence"], "sequence")
    event = value["event"]
    if event not in EVENTS:
        raise ProtocolError("unstable event")
    timestamp = value["timestamp"]
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ProtocolError("timestamp must be UTC")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ProtocolError("timestamp is not strict ISO-8601 UTC") from exc
    if parsed_timestamp.utcoffset() != datetime.now(UTC).utcoffset():
        raise ProtocolError("timestamp must be UTC")
    payload = value["payload"]
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS[event]:
        raise ProtocolError("stable payload schema is closed")
    clean = dict(payload)
    if "run_kind" in clean and clean["run_kind"] not in RUN_KINDS:
        raise ProtocolError("invalid run kind")
    if "outcome" in clean and clean["outcome"] not in OUTCOMES:
        raise ProtocolError("invalid outcome")
    if "spec_id" in clean:
        identifier(clean["spec_id"], "spec id")
    if "config_digest" in clean and (
        not isinstance(clean["config_digest"], str)
        or not _SHA.fullmatch(clean["config_digest"])
    ):
        raise ProtocolError("invalid config digest")
    if "artifact_refs" in clean:
        if not isinstance(clean["artifact_refs"], list):
            raise ProtocolError("artifact_refs must be a list")
        clean["artifact_refs"] = [
            _artifact_ref(item) for item in clean["artifact_refs"]
        ]
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": value["event_id"],
        "run_id": run_id,
        "sequence": sequence,
        "event": event,
        "timestamp": timestamp,
        "payload": clean,
    }


def make_envelope(
    *,
    run_id: str,
    sequence: int,
    event: str,
    payload: Mapping[str, Any],
    event_id: str | None = None,
) -> dict[str, Any]:
    return validate_envelope(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id or str(uuid.uuid4()),
            "run_id": run_id,
            "sequence": sequence,
            "event": event,
            "timestamp": now(),
            "payload": dict(payload),
        }
    )


def atomic_write(path: Path, data: bytes, *, limit: int | None = None) -> None:
    if limit is not None and len(data) > limit:
        raise ProtocolError("atomic output exceeds limit")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Check the complete parent chain after mkdir; a symlink anywhere is fatal.
    anchor = path.parent
    while anchor != anchor.parent:
        if anchor.is_symlink():
            raise ProtocolError("symlink write ancestor")
        anchor = anchor.parent
    if path.is_symlink():
        raise ProtocolError("symlink write target")
    fd, temporary = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_json(path: Path, value: Any, *, limit: int | None = None) -> None:
    atomic_write(path, canonical(value), limit=limit)


@dataclass(frozen=True)
class Limits:
    max_concurrency: int
    max_queue: int
    max_processes: int
    deadline_s: int
    max_output_bytes: int
    max_memory_bytes: int
    max_cpu_s: int

    @classmethod
    def parse(cls, value: Any) -> Limits:
        names = {
            "max_concurrency",
            "max_queue",
            "max_processes",
            "deadline_s",
            "max_output_bytes",
            "max_memory_bytes",
            "max_cpu_s",
        }
        if not isinstance(value, dict) or set(value) != names:
            raise ProtocolError("resource limits schema is closed")
        return cls(**{name: positive_int(value[name], name) for name in names})

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class Admission:
    extension_id: str
    source: str
    subscriptions: tuple[str, ...]
    capabilities: tuple[str, ...]
    limits: Limits
    config_digest: str
    executable: Path
    executable_sha256: str
    network_endpoint: str | None = None

    @property
    def namespace(self) -> str:
        """Stable filesystem/scheduler identity preserving both identity fields."""
        return f"{self.source}--{self.extension_id}"
