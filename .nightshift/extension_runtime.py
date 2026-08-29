"""Durable publication, brokered output, and restartable extension supervision."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import resource
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from extension_protocol import (
    TERMINAL_STATES,
    Admission,
    Capability,
    EventName,
    JobState,
    ProtocolError,
    atomic_json,
    atomic_write,
    canonical,
    digest,
    make_envelope,
    now,
    resolve_beneath,
    safe_relative,
    sha256_bytes,
    validate_envelope,
)
from extension_sandbox import SandboxBackend, host_backend

OUTPUT_FIELDS = {
    "schema_version",
    "operation_key",
    "state",
    "artifacts",
    "state_operations",
    "network_requests",
}
ARTIFACT_FIELDS = {"name", "content", "sha256"}
STATE_OPERATION_FIELDS = {"key", "value", "expected_sha256"}
NETWORK_REQUEST_FIELDS = {"endpoint", "request_b64", "max_response_bytes"}


def _process_identity(pid: int) -> str | None:
    """Return a PID-reuse-resistant identity for a live process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        if proc_stat.exists():
            fields = proc_stat.read_text(encoding="utf-8").split()
            return f"{pid}:{fields[21]}"
        started = subprocess.check_output(
            ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
            text=True,
            env={"PATH": "/usr/bin:/bin"},
            stderr=subprocess.DEVNULL,
        ).strip()
        return f"{pid}:{started}" if started else None
    except (OSError, IndexError, subprocess.SubprocessError):
        return None


def _append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ProtocolError("unsafe append target")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        data = canonical(value) + b"\n"
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json(path: Path, *, max_bytes: int = 1_048_576) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ProtocolError("expected regular JSON file")
    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise ProtocolError("JSON file oversized")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("JSON root must be object")
    return value


class ExtensionSpool:
    """Immutable source events and durable jobs; notification happens afterwards."""

    def __init__(self, root: Path, run_id: str):
        # Resolve the trusted spool anchor once. On macOS `/var` is the
        # platform alias for `/private/var`; treating that system alias as an
        # attacker-controlled in-boundary symlink rejects every normal temp
        # root. All subsequent paths use the canonical anchor, while symlinks
        # created beneath it remain fatal at each read/write operation.
        self.root = Path(root).resolve(strict=False)
        self.run_id = run_id
        self.run_root = self.root / "runs" / run_id
        self.events_path = self.run_root / "source-events.jsonl"

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        values = []
        for raw in self.events_path.read_bytes().splitlines():
            try:
                values.append(validate_envelope(json.loads(raw.decode("utf-8"))))
            except (UnicodeDecodeError, json.JSONDecodeError, ProtocolError) as exc:
                raise ProtocolError("corrupt source event spool") from exc
        return values

    def append_event(self, envelope: Mapping[str, Any]) -> None:
        event = validate_envelope(envelope)
        previous = self.events()
        if previous and (
            event["sequence"] != previous[-1]["sequence"] + 1
            or event["event_id"] in {item["event_id"] for item in previous}
        ):
            raise ProtocolError("event order/id violation")
        if not previous and event["sequence"] != 1:
            raise ProtocolError("first sequence must be one")
        _append_fsync(self.events_path, event)

    def create_job(self, admission: Admission, envelope: Mapping[str, Any]) -> Path:
        event = validate_envelope(envelope)
        if event["event"] not in admission.subscriptions:
            raise ProtocolError("event not subscribed")
        job_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL, admission.config_digest + ":" + event["event_id"]
            )
        )
        job = self.run_root / "extensions" / admission.namespace / "jobs" / job_id
        input_value = {
            "schema_version": "1.0.0",
            "job_id": job_id,
            "operation_key": digest(
                {"admission": admission.config_digest, "event_id": event["event_id"]}
            ),
            "admission": {
                "id": admission.extension_id,
                "source": admission.source,
                "digest": admission.config_digest,
                "subscriptions": list(admission.subscriptions),
                "capabilities": list(admission.capabilities),
                "limits": admission.limits.as_dict(),
                "executable_sha256": admission.executable_sha256,
                "network_endpoint": admission.network_endpoint,
            },
            "event": event,
        }
        input_path = job / "input.json"
        if input_path.exists():
            if _read_json(input_path) != input_value:
                self.quarantine(job, "divergent-input")
                raise ProtocolError("divergent replay quarantined")
            return job
        atomic_json(input_path, input_value)
        self.transition(job, JobState.PLANNED.value, producer="publisher")
        return job

    def ingest_artifact_refs(
        self, payload: Mapping[str, Any], artifact_root: Path | None
    ) -> None:
        """Verify private approved inputs before any stable event is published."""
        references = payload.get("artifact_refs", [])
        if not references:
            return
        if artifact_root is None:
            raise ProtocolError("artifact references require private artifact root")
        artifact_root = Path(artifact_root)
        if artifact_root.is_symlink():
            raise ProtocolError("private artifact root may not be a symlink")
        root = artifact_root.resolve(strict=True)
        if not root.is_dir():
            raise ProtocolError("private artifact root unavailable")
        verified: list[tuple[str, bytes]] = []
        for reference in references:
            if (
                not isinstance(reference, dict)
                or set(reference) != {"name", "sha256", "size"}
                or isinstance(reference["size"], bool)
                or not isinstance(reference["size"], int)
                or reference["size"] <= 0
                or not isinstance(reference["sha256"], str)
            ):
                raise ProtocolError("artifact reference schema is closed")
            source = resolve_beneath(root, reference["name"])
            if source.is_symlink() or not source.is_file():
                raise ProtocolError("artifact source unavailable")
            raw = source.read_bytes()
            if (
                len(raw) != reference["size"]
                or sha256_bytes(raw) != reference["sha256"]
            ):
                raise ProtocolError("artifact source hash/size mismatch")
            verified.append((reference["name"], raw))
        for name, raw in verified:
            target = resolve_beneath(
                self.run_root / "immutable-artifacts", name, must_exist=False
            )
            if target.exists():
                if target.read_bytes() != raw:
                    raise ProtocolError("divergent immutable artifact replay")
                continue
            atomic_write(target, raw, limit=len(raw))

    def transition(
        self, job: Path, state: str, *, producer: str, detail: str | None = None
    ) -> None:
        if state not in {x.value for x in JobState}:
            raise ProtocolError("unknown job state")
        record = {
            "schema_version": "1.0.0",
            "job_id": job.name,
            "state": state,
            "producer": producer,
            "timestamp": now(),
        }
        if detail:
            record["detail"] = detail
        _append_fsync(job / "events.jsonl", record)
        atomic_json(job / "latest.json", record)

    def record_admission_failures(self, failures: list[dict[str, str]]) -> None:
        for failure in failures:
            _append_fsync(
                self.run_root / "admission-failures.jsonl",
                {
                    "schema_version": "1.0.0",
                    "id": failure.get("id", "unknown"),
                    "reason": failure.get("reason", "admission-failed"),
                    "timestamp": now(),
                },
            )

    def record_checkpoint_failure(self, reason: str) -> None:
        """Persist one controlled private diagnostic without raw exception data."""
        _append_fsync(
            self.run_root / "checkpoint-diagnostics.jsonl",
            {
                "schema_version": "1.0.0",
                "reason": reason,
                "timestamp": now(),
            },
        )

    def quarantine(self, job: Path, reason: str) -> None:
        self.transition(job, JobState.INVALID.value, producer="broker", detail=reason)
        atomic_json(
            job / "quarantine.json",
            {"schema_version": "1.0.0", "reason": reason, "timestamp": now()},
        )

    def mark_run_completed(self, envelope: Mapping[str, Any]) -> None:
        event = validate_envelope(envelope)
        if event["event"] != "run.completed":
            raise ProtocolError("run terminal marker requires run.completed")
        marker = {
            "schema_version": "1.0.0",
            "run_id": self.run_id,
            "event_id": event["event_id"],
            "timestamp": event["timestamp"],
        }
        path = self.run_root / "run-terminal.json"
        if path.exists() and _read_json(path) != marker:
            raise ProtocolError("divergent run terminal marker")
        if not path.exists():
            atomic_json(path, marker)


class ExtensionBroker:
    """Validates declarative child output and owns all namespaced writes."""

    def __init__(self, spool: ExtensionSpool):
        self.spool = spool

    def seal(
        self, job: Path, admission: Admission, *, run_completed: bool = False
    ) -> str:
        data = _read_json(
            job / "input.json", max_bytes=admission.limits.max_output_bytes
        )
        output = _read_json(
            job / "output.json", max_bytes=admission.limits.max_output_bytes
        )
        if (
            set(output) != OUTPUT_FIELDS
            or output["schema_version"] != "1.0.0"
            or output["operation_key"] != data["operation_key"]
        ):
            raise ProtocolError("output schema/operation mismatch")
        if (
            output["state"] != "completed"
            or not isinstance(output["artifacts"], list)
            or not isinstance(output["state_operations"], list)
        ):
            raise ProtocolError("invalid output state")
        if (
            output["artifacts"]
            and Capability.ARTIFACTS_WRITE.value not in admission.capabilities
        ):
            raise ProtocolError("artifact capability denied")
        if (
            output["state_operations"]
            and Capability.STATE_READ_WRITE.value not in admission.capabilities
        ):
            raise ProtocolError("state capability denied")
        if not isinstance(output["network_requests"], list):
            raise ProtocolError("network_requests must be a list")
        if (
            output["network_requests"]
            and Capability.NETWORK_LOOPBACK.value not in admission.capabilities
        ):
            raise ProtocolError("network capability denied")
        state = (
            JobState.COMPLETED_AFTER_RUN.value
            if run_completed
            else JobState.COMPLETED.value
        )
        output_identity = digest(output)
        terminal_path = job / "terminal.json"
        if terminal_path.exists():
            existing = _read_json(terminal_path)
            if existing.get("output_identity") == output_identity:
                return existing["state"]
            evidence_path = job / "replay-quarantine.json"
            if not evidence_path.exists():
                atomic_json(
                    evidence_path,
                    {
                        "schema_version": "1.0.0",
                        "reason": "divergent-terminal-replay",
                        "terminal_state": existing.get("state"),
                        "original_output_identity": existing.get("output_identity"),
                        "presented_output_identity": output_identity,
                        "timestamp": now(),
                    },
                )
                self.spool.transition(
                    job,
                    existing["state"],
                    producer="broker",
                    detail="divergent-terminal-replay-quarantined",
                )
            return "replay-quarantined"
        manifest = []
        total = 0
        for item in output["artifacts"]:
            if not isinstance(item, dict) or set(item) != ARTIFACT_FIELDS:
                raise ProtocolError("artifact schema is closed")
            name = safe_relative(item["name"], "artifact name")
            if not isinstance(item["content"], str):
                raise ProtocolError("artifact content must be UTF-8 text")
            raw = item["content"].encode("utf-8")
            total += len(raw)
            if (
                total > admission.limits.max_output_bytes
                or sha256_bytes(raw) != item["sha256"]
            ):
                raise ProtocolError("artifact size/hash violation")
            path = job / "artifacts" / name
            atomic_json(
                path.with_suffix(path.suffix + ".json"),
                {"schema_version": "1.0.0", "content": item["content"]},
                limit=admission.limits.max_output_bytes,
            )
            manifest.append({"name": name, "sha256": item["sha256"], "size": len(raw)})
        for operation in output["state_operations"]:
            if (
                not isinstance(operation, dict)
                or set(operation) != STATE_OPERATION_FIELDS
            ):
                raise ProtocolError("state operation schema is closed")
            key = safe_relative(operation["key"], "state key")
            if not isinstance(operation["value"], dict):
                raise ProtocolError("state value must be object")
            state_path = job.parent.parent / "state" / (key + ".json")
            current = digest(_read_json(state_path)) if state_path.exists() else None
            if operation["expected_sha256"] != current:
                raise ProtocolError("state compare-and-swap mismatch")
            atomic_json(
                state_path, operation["value"], limit=admission.limits.max_output_bytes
            )
        network_responses = []
        for request in output["network_requests"]:
            network_responses.append(self._network_request(request, admission))
        artifact_manifest = {
            "schema_version": "1.0.0",
            "producer": {
                "id": admission.extension_id,
                "source": admission.source,
            },
            "job_id": job.name,
            "artifacts": manifest,
            "network_responses": network_responses,
            "timestamp": now(),
        }
        artifact_manifest["hash"] = digest(artifact_manifest)
        atomic_json(job / "artifact-manifest.json", artifact_manifest)
        result = {
            "schema_version": "1.0.0",
            "operation_key": data["operation_key"],
            "output_identity": output_identity,
            "state": state,
            "manifest_sha256": digest(artifact_manifest),
            "timestamp": now(),
        }
        atomic_json(terminal_path, result)
        self.spool.transition(job, state, producer="broker")
        return state

    @staticmethod
    def _network_request(request: Any, admission: Admission) -> dict[str, Any]:
        if not isinstance(request, dict) or set(request) != NETWORK_REQUEST_FIELDS:
            raise ProtocolError("network request schema is closed")
        if request["endpoint"] != admission.network_endpoint:
            raise ProtocolError("network target differs from admitted endpoint")
        maximum = request["max_response_bytes"]
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or maximum <= 0
            or maximum > admission.limits.max_output_bytes
        ):
            raise ProtocolError("invalid network response bound")
        try:
            payload = base64.b64decode(request["request_b64"], validate=True)
            host, port_text = request["endpoint"].rsplit(":", 1)
            port = int(port_text)
        except (TypeError, ValueError) as exc:
            raise ProtocolError("invalid broker request") from exc
        # Admission already proved a numeric loopback address. No resolver,
        # proxies, HTTP client, redirects, ambient headers, or credential source.
        with socket.socket(
            socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM
        ) as conn:
            conn.settimeout(min(admission.limits.deadline_s, 5))
            conn.connect((host, port))
            conn.sendall(payload)
            conn.shutdown(socket.SHUT_WR)
            response = conn.recv(maximum + 1)
        if len(response) > maximum:
            raise ProtocolError("broker response oversized")
        return {
            "endpoint": request["endpoint"],
            "sha256": sha256_bytes(response),
            "size": len(response),
            "response_b64": base64.b64encode(response).decode("ascii"),
        }


def _preexec(limits: Any) -> None:
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU, (limits.max_cpu_s, limits.max_cpu_s))
    # Darwin rejects finite RLIMIT_AS/RSS/DATA. Its supervisor polls RSS and
    # kills the owned process group instead; Linux enforces address space here.
    if sys.platform != "darwin":
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.max_memory_bytes, limits.max_memory_bytes)
        )
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (limits.max_output_bytes, limits.max_output_bytes)
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))


class ExtensionSupervisor:
    """One real scheduler with bounded queue/concurrency and durable recovery."""

    def __init__(
        self,
        spool: ExtensionSpool,
        *,
        backend: SandboxBackend | None = None,
        global_concurrency: int = 4,
        global_queue: int = 64,
    ):
        if (
            isinstance(global_concurrency, bool)
            or global_concurrency <= 0
            or global_queue <= 0
        ):
            raise ProtocolError("supervisor limits must be positive")
        self.spool = spool
        self.backend = backend or host_backend()
        self.global_concurrency = global_concurrency
        self.global_queue = global_queue
        self.executor = ThreadPoolExecutor(
            max_workers=global_concurrency, thread_name_prefix="nightshift-extension"
        )
        self.capacity = threading.BoundedSemaphore(global_queue)
        self._extension_queue: dict[str, threading.BoundedSemaphore] = {}
        self._extension_active: dict[str, threading.BoundedSemaphore] = {}
        self._active: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def notify(self, job: Path, admission: Admission, *, run_completed: bool = False):
        terminal = job / "terminal.json"
        if terminal.exists():
            return self._resolved_future(_read_json(terminal)["state"])
        dispatch = self._acquire_dispatch(job)
        if dispatch is None:
            return self._resolved_future(JobState.CLAIMED.value)
        with self._lock:
            extension_queue = self._extension_queue.setdefault(
                admission.config_digest,
                threading.BoundedSemaphore(admission.limits.max_queue),
            )
            self._extension_active.setdefault(
                admission.config_digest,
                threading.BoundedSemaphore(admission.limits.max_concurrency),
            )
        global_slot = self._acquire_durable_slot(
            "queue-global", "global", self.global_queue, job.name
        )
        if global_slot is None:
            self._release_durable_slot(dispatch)
            return self._terminal_future(job, JobState.FAILED, "queue-full")
        extension_slot = self._acquire_durable_slot(
            "queue-extension",
            admission.namespace,
            admission.limits.max_queue,
            job.name,
        )
        if extension_slot is None:
            self._release_durable_slot(global_slot)
            self._release_durable_slot(dispatch)
            return self._terminal_future(job, JobState.FAILED, "extension-queue-full")
        if not self.capacity.acquire(blocking=False):
            self._release_durable_slot(extension_slot)
            self._release_durable_slot(global_slot)
            self._release_durable_slot(dispatch)
            return self._terminal_future(job, JobState.FAILED, "queue-full")
        if not extension_queue.acquire(blocking=False):
            self.capacity.release()
            self._release_durable_slot(extension_slot)
            self._release_durable_slot(global_slot)
            self._release_durable_slot(dispatch)
            return self._terminal_future(job, JobState.FAILED, "extension-queue-full")
        future = self.executor.submit(
            self._execute_bounded, Path(job), admission, run_completed
        )
        future.add_done_callback(
            lambda _: (
                extension_queue.release(),
                self.capacity.release(),
                self._release_durable_slot(extension_slot),
                self._release_durable_slot(global_slot),
                self._release_durable_slot(dispatch),
            )
        )
        return future

    @staticmethod
    def _resolved_future(result: str) -> Future[str]:
        future: Future[str] = Future()
        future.set_result(result)
        return future

    def _acquire_dispatch(self, job: Path) -> Path | None:
        marker = job / "dispatch.json"
        lock_fd = os.open(job / ".dispatch.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if marker.exists():
                record = _read_json(marker)
                recorded = record.get("owner_identity")
                if (
                    isinstance(recorded, str)
                    and recorded
                    and recorded == _process_identity(record.get("owner_pid"))
                ):
                    return None
                marker.unlink(missing_ok=True)
            identity = _process_identity(os.getpid())
            if identity is None:
                raise ProtocolError("cannot establish dispatch owner identity")
            atomic_json(
                marker,
                {
                    "schema_version": "1.0.0",
                    "owner_pid": os.getpid(),
                    "owner_identity": identity,
                    "job_id": job.name,
                    "timestamp": now(),
                },
            )
            return marker
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def _acquire_durable_slot(
        self, kind: str, namespace: str, limit: int, job_id: str
    ) -> Path | None:
        root = self.spool.run_root / "capacity" / kind / namespace
        root.mkdir(parents=True, exist_ok=True)
        identity = _process_identity(os.getpid())
        if identity is None:
            raise ProtocolError("cannot establish supervisor process identity")
        lock_path = root / ".allocation.lock"
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            for number in range(limit):
                slot = root / f"{number}.json"
                if slot.exists():
                    try:
                        record = _read_json(slot)
                        recorded_identity = record.get("owner_identity")
                        alive = (
                            isinstance(recorded_identity, str)
                            and bool(recorded_identity)
                            and recorded_identity
                            == _process_identity(record.get("owner_pid"))
                        )
                    except ProtocolError:
                        alive = False
                    if not alive:
                        slot.unlink(missing_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                try:
                    fd = os.open(slot, flags, 0o600)
                except FileExistsError:
                    continue
                with os.fdopen(fd, "wb") as handle:
                    handle.write(
                        canonical(
                            {
                                "schema_version": "1.0.0",
                                "owner_pid": os.getpid(),
                                "owner_identity": identity,
                                "job_id": job_id,
                                "timestamp": now(),
                            }
                        )
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                return slot
            return None
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    @staticmethod
    def _release_durable_slot(slot: Path) -> None:
        slot.unlink(missing_ok=True)

    def _terminal_future(self, job: Path, state: JobState, detail: str) -> Future[str]:
        with self._lock:
            terminal = job / "terminal.json"
            if terminal.exists():
                result = _read_json(terminal)["state"]
            else:
                # Persist the execution veto before its history projection. A
                # crash at either boundary can never make recovery execute it.
                atomic_json(
                    terminal,
                    {
                        "schema_version": "1.0.0",
                        "state": state.value,
                        "timestamp": now(),
                    },
                )
                self.spool.transition(
                    job, state.value, producer="supervisor", detail=detail
                )
                result = state.value
        return self._resolved_future(result)

    def _execute_bounded(
        self, job: Path, admission: Admission, run_completed: bool
    ) -> str:
        global_slot = None
        extension_slot = None
        while global_slot is None or extension_slot is None:
            if global_slot is None:
                global_slot = self._acquire_durable_slot(
                    "active-global", "global", self.global_concurrency, job.name
                )
            if global_slot is not None and extension_slot is None:
                extension_slot = self._acquire_durable_slot(
                    "active-extension",
                    admission.namespace,
                    admission.limits.max_concurrency,
                    job.name,
                )
                if extension_slot is None:
                    self._release_durable_slot(global_slot)
                    global_slot = None
            if global_slot is None or extension_slot is None:
                time.sleep(0.02)
        try:
            with self._extension_active[admission.config_digest]:
                return self._execute(job, admission, run_completed)
        finally:
            self._release_durable_slot(extension_slot)
            self._release_durable_slot(global_slot)

    def claim(self, job: Path) -> bool:
        claim = job / "claim.json"
        owner_identity = _process_identity(os.getpid())
        if owner_identity is None:
            raise ProtocolError("cannot establish claim owner identity")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(claim, flags, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "wb") as handle:
            record = canonical(
                {
                    "schema_version": "1.0.0",
                    "owner_pid": os.getpid(),
                    "owner_identity": owner_identity,
                    "timestamp": now(),
                }
            )
            handle.write(record)
            handle.flush()
            os.fsync(handle.fileno())
        self.spool.transition(job, JobState.CLAIMED.value, producer="supervisor")
        return True

    def _execute(self, job: Path, admission: Admission, run_completed: bool) -> str:
        if (job / "terminal.json").exists():
            return _read_json(job / "terminal.json")["state"]
        if not self.claim(job):
            return JobState.CLAIMED.value
        proc: subprocess.Popen[bytes] | None = None
        try:
            input_value = _read_json(job / "input.json")
            event_name = input_value["event"]["event"]
            if self._must_cancel(event_name, admission):
                return self._cancel(job)
            if (
                sha256_bytes(admission.executable.read_bytes())
                != admission.executable_sha256
            ):
                raise ProtocolError("executable changed after admission")
            # Child gets a sealed execution directory, never an ancestor of the
            # durable source spool. Relative ../../ attacks cannot reach it.
            execution = job / "execution"
            execution.mkdir(mode=0o700)
            atomic_json(execution / "input.json", input_value)
            self._materialize_capability_inputs(execution, job, input_value, admission)
            launch = self.backend.launch(
                admission.executable,
                execution,
                admission.capabilities,
                admission.network_endpoint,
            )
            self.spool.transition(job, JobState.RUNNING.value, producer="supervisor")
            proc = subprocess.Popen(
                launch.argv,
                cwd=execution,
                stdin=subprocess.DEVNULL,
                # Domain output is the bounded JSON file contract. Raw child
                # stdout/stderr are discarded so a flood cannot consume parent
                # memory or enter any public log/projection.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=launch.env,
                close_fds=True,
                start_new_session=False,
                preexec_fn=lambda: _preexec(admission.limits),  # noqa: PLW1509 -- child rlimits before exec
            )
            with self._lock:
                self._active[job.name] = proc
            process_identity = _process_identity(proc.pid)
            if process_identity is None:
                raise ProtocolError("cannot establish child process identity")
            atomic_json(
                job / "owner.json",
                {
                    "schema_version": "1.0.0",
                    "process_group": proc.pid,
                    "process_identity": process_identity,
                    "timestamp": now(),
                },
            )
            try:
                deadline = time.monotonic() + admission.limits.deadline_s
                while True:
                    if self._must_cancel(event_name, admission):
                        self._terminate_group(proc)
                        return self._cancel(job)
                    try:
                        proc.wait(timeout=0.05)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            self._terminate_group(proc)
                            self.spool.transition(
                                job, JobState.TIMED_OUT.value, producer="supervisor"
                            )
                            atomic_json(
                                job / "terminal.json",
                                {
                                    "schema_version": "1.0.0",
                                    "state": JobState.TIMED_OUT.value,
                                    "timestamp": now(),
                                },
                            )
                            return JobState.TIMED_OUT.value
                        if (
                            sys.platform == "darwin"
                            and self._rss_bytes(proc.pid)
                            > admission.limits.max_memory_bytes
                        ):
                            self._terminate_group(proc)
                            self.spool.transition(
                                job,
                                JobState.FAILED.value,
                                producer="supervisor",
                                detail="memory-limit",
                            )
                            atomic_json(
                                job / "terminal.json",
                                {
                                    "schema_version": "1.0.0",
                                    "state": JobState.FAILED.value,
                                    "timestamp": now(),
                                },
                            )
                            return JobState.FAILED.value
            finally:
                with self._lock:
                    self._active.pop(job.name, None)
            # Completion of the direct child is not completion of its owned
            # process group. Kill/reap forked descendants on every terminal path.
            self._reap_descendants(proc.pid)
            if proc.returncode != 0:
                state = JobState.FAILED.value
                self.spool.transition(job, state, producer="supervisor")
                atomic_json(
                    job / "terminal.json",
                    {"schema_version": "1.0.0", "state": state, "timestamp": now()},
                )
                return state
            # run.completed can become durable after the last wait-loop check
            # but before output sealing. Only background.continue work and the
            # run.completed event's own observer may deliberately finish late.
            if self._must_cancel(event_name, admission):
                return self._cancel(job)
            output = execution / "output.json"
            if not output.exists() or output.is_symlink() or not output.is_file():
                raise ProtocolError("child produced no declarative output")
            # Broker copies one validated bounded file into the durable job.
            raw = output.read_bytes()
            if len(raw) > admission.limits.max_output_bytes:
                raise ProtocolError("child output oversized")
            atomic_json(
                job / "output.json",
                json.loads(raw.decode("utf-8")),
                limit=admission.limits.max_output_bytes,
            )
            late = run_completed or (self.spool.run_root / "run-terminal.json").exists()
            return ExtensionBroker(self.spool).seal(job, admission, run_completed=late)
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ProtocolError,
        ) as exc:
            # Popen may have succeeded before owner persistence, output
            # validation, or broker sealing failed. No exception path may
            # leave the owned process group alive.
            if proc is not None:
                self._terminate_group(proc)
            self.spool.quarantine(job, type(exc).__name__)
            atomic_json(
                job / "terminal.json",
                {
                    "schema_version": "1.0.0",
                    "state": JobState.INVALID.value,
                    "timestamp": now(),
                },
            )
            return JobState.INVALID.value
        finally:
            with self._lock:
                self._active.pop(job.name, None)
            (job / "claim.json").unlink(missing_ok=True)
            (job / "owner.json").unlink(missing_ok=True)
            execution = job / "execution"
            self._cleanup_execution(job)

    def _materialize_capability_inputs(
        self,
        execution: Path,
        job: Path,
        input_value: dict[str, Any],
        admission: Admission,
    ) -> None:
        references = input_value["event"]["payload"].get("artifact_refs", [])
        if references and Capability.ARTIFACT_REFS_READ.value in admission.capabilities:
            for reference in references:
                source = resolve_beneath(
                    self.spool.run_root / "immutable-artifacts", reference["name"]
                )
                raw = source.read_bytes()
                if (
                    len(raw) != reference["size"]
                    or sha256_bytes(raw) != reference["sha256"]
                ):
                    raise ProtocolError("immutable artifact reference mismatch")
                target = execution / "artifact-refs" / reference["name"]
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(target, raw, limit=admission.limits.max_output_bytes)
        if Capability.STATE_READ_WRITE.value in admission.capabilities:
            state_root = job.parent.parent / "state"
            if state_root.exists():
                for source in sorted(state_root.glob("*.json")):
                    if source.is_symlink() or not source.is_file():
                        raise ProtocolError("unsafe state snapshot")
                    value = _read_json(
                        source, max_bytes=admission.limits.max_output_bytes
                    )
                    atomic_json(
                        execution / "state" / source.name,
                        value,
                        limit=admission.limits.max_output_bytes,
                    )

    @staticmethod
    def _terminate_group(proc: subprocess.Popen[bytes]) -> None:
        def _already_gone() -> bool:
            # Our own Popen handle is the authority on whether this child has
            # exited. A PermissionError against a pid/pgid this handle has
            # already observed as reaped is pid/pgid reuse under load, not a
            # live process we lack rights to signal. A PermissionError against
            # a pid/pgid this handle still considers live is a genuine
            # permission failure and must propagate.
            return proc.poll() is not None

        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            proc.wait()
            return
        except PermissionError:
            if not _already_gone():
                raise
            proc.wait()
            return
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        # The direct child can exit on TERM while a descendant in its process
        # group ignores TERM. Probe and escalate the group independently of
        # the direct child's return state.
        try:
            os.killpg(proc.pid, 0)
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if not _already_gone():
                raise
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

    def _must_cancel(self, event_name: str, admission: Admission) -> bool:
        return (
            event_name != EventName.RUN_COMPLETED.value
            and Capability.BACKGROUND_CONTINUE.value not in admission.capabilities
            and (self.spool.run_root / "run-terminal.json").exists()
        )

    def _cancel(self, job: Path) -> str:
        self.spool.transition(job, JobState.CANCELLED.value, producer="supervisor")
        atomic_json(
            job / "terminal.json",
            {
                "schema_version": "1.0.0",
                "state": JobState.CANCELLED.value,
                "timestamp": now(),
            },
        )
        return JobState.CANCELLED.value

    @staticmethod
    def _reap_descendants(group_id: int) -> None:
        try:
            os.killpg(group_id, 0)
        except ProcessLookupError:
            return
        try:
            os.killpg(group_id, signal.SIGTERM)
            time.sleep(0.02)
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def _rss_bytes(pid: int) -> int:
        try:
            value = subprocess.check_output(
                ["/bin/ps", "-o", "rss=", "-p", str(pid)],
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            return int(value.strip() or "0") * 1024
        except (OSError, ValueError, subprocess.SubprocessError):
            # Fail closed: inability to measure an active Darwin child is
            # treated as over-limit, never as evidence that it is safe.
            return 2**63 - 1

    def recover(self, admissions: Mapping[str, Admission]) -> list[Any]:
        futures = []
        for job in sorted(self.spool.run_root.glob("extensions/*/jobs/*")):
            try:
                future = self._recover_one(job, admissions)
                if future is not None:
                    futures.append(future)
            except Exception as exc:  # noqa: BLE001 -- per-job corruption boundary
                try:
                    self._contain_recovery_failure(job, type(exc).__name__)
                except Exception:  # noqa: BLE001 -- continue independent jobs
                    # The corrupt filesystem object itself may prevent durable
                    # quarantine. It still cannot abort independent jobs.
                    for name in ("claim.json", "owner.json", "dispatch.json"):
                        try:
                            (job / name).unlink(missing_ok=True)
                        except OSError:
                            pass
        return [future for future in futures if future is not None]

    def _recover_one(
        self, job: Path, admissions: Mapping[str, Admission]
    ) -> Future[str] | None:
        if (job / "terminal.json").exists():
            self._reconcile_terminal(job)
            return None
        projected_terminal = self._projected_terminal_state(job)
        if projected_terminal is not None:
            atomic_json(
                job / "terminal.json",
                {
                    "schema_version": "1.0.0",
                    "state": projected_terminal,
                    "timestamp": now(),
                    "recovered_from_projection": True,
                },
            )
            self._reconcile_terminal(job)
            return None
        admission = admissions.get(job.parent.parent.name)
        if admission is None:
            self.spool.transition(job, JobState.ABANDONED.value, producer="recovery")
            atomic_json(
                job / "terminal.json",
                {
                    "schema_version": "1.0.0",
                    "state": JobState.ABANDONED.value,
                    "timestamp": now(),
                },
            )
            self._cleanup_execution(job)
            return None
        claim = job / "claim.json"
        if claim.exists():
            claim_record = _read_json(claim)
            owner = claim_record.get("owner_pid")
            owner_identity = claim_record.get("owner_identity")
            if (
                isinstance(owner_identity, str)
                and owner_identity
                and owner_identity == _process_identity(owner)
            ):
                return None
            owner_path = job / "owner.json"
            self._kill_exact_owner(owner_path)
            claim.unlink(missing_ok=True)
            self.spool.transition(job, JobState.ABANDONED.value, producer="recovery")
            atomic_json(
                job / "terminal.json",
                {
                    "schema_version": "1.0.0",
                    "state": JobState.ABANDONED.value,
                    "timestamp": now(),
                },
            )
            owner_path.unlink(missing_ok=True)
            self._cleanup_execution(job)
            return None
        return self.notify(job, admission)

    def _contain_recovery_failure(self, job: Path, reason: str) -> None:
        """Quarantine one corrupt job without aborting independent recovery."""
        try:
            self._kill_exact_owner(job / "owner.json")
        except (OSError, ProtocolError):
            pass
        for name in ("terminal.json", "events.jsonl", "latest.json"):
            path = job / name
            if not path.exists() or path.is_symlink():
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                continue
            evidence = job / ("corrupt-" + name)
            if not evidence.exists():
                os.replace(path, evidence)
            else:
                path.unlink(missing_ok=True)
        atomic_json(
            job / "recovery-quarantine.json",
            {"schema_version": "1.0.0", "reason": reason, "timestamp": now()},
        )
        atomic_json(
            job / "terminal.json",
            {
                "schema_version": "1.0.0",
                "state": JobState.INVALID.value,
                "timestamp": now(),
            },
        )
        self.spool.transition(
            job, JobState.INVALID.value, producer="recovery", detail=reason
        )
        for name in ("claim.json", "owner.json", "dispatch.json"):
            (job / name).unlink(missing_ok=True)
        self._cleanup_execution(job)

    @staticmethod
    def _projected_terminal_state(job: Path) -> str | None:
        states = []
        history = job / "events.jsonl"
        if history.exists():
            lines = history.read_bytes().splitlines()
            if lines:
                try:
                    states.append(json.loads(lines[-1].decode("utf-8")).get("state"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError("corrupt job history") from exc
        latest = job / "latest.json"
        if latest.exists():
            states.append(_read_json(latest).get("state"))
        terminals = [state for state in states if state in TERMINAL_STATES]
        if len(set(terminals)) > 1:
            raise ProtocolError("conflicting terminal projections")
        return terminals[0] if terminals else None

    def _reconcile_terminal(self, job: Path) -> None:
        terminal = _read_json(job / "terminal.json")
        state = terminal.get("state")
        if state not in TERMINAL_STATES:
            raise ProtocolError("terminal file has non-terminal state")
        latest_path = job / "latest.json"
        latest_state = (
            _read_json(latest_path).get("state") if latest_path.exists() else None
        )
        history_state = None
        history = job / "events.jsonl"
        if history.exists():
            lines = history.read_bytes().splitlines()
            if lines:
                try:
                    history_state = json.loads(lines[-1].decode("utf-8")).get("state")
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProtocolError("corrupt job history") from exc
        if latest_state != state or history_state != state:
            self.spool.transition(
                job, state, producer="recovery", detail="terminal-reconcile"
            )
        self._kill_exact_owner(job / "owner.json")
        (job / "claim.json").unlink(missing_ok=True)
        (job / "owner.json").unlink(missing_ok=True)
        (job / "dispatch.json").unlink(missing_ok=True)
        self._cleanup_execution(job)

    @staticmethod
    def _cleanup_execution(job: Path) -> None:
        execution = job / "execution"
        if execution.exists():
            shutil.rmtree(execution)

    @staticmethod
    def _kill_exact_owner(owner_path: Path) -> None:
        if not owner_path.exists():
            return
        record = _read_json(owner_path)
        group_id = record.get("process_group")
        recorded_identity = record.get("process_identity")
        current_identity = _process_identity(group_id)
        # A live reused leader PID must match its recorded start identity. If
        # the leader is gone but its process group still exists, it can only be
        # the orphaned owned descendants and remains safe to reap by PGID.
        if current_identity is not None and recorded_identity != current_identity:
            return
        try:
            os.killpg(group_id, signal.SIGKILL)
        except (ProcessLookupError, TypeError):
            pass

    def shutdown(self) -> None:
        with self._lock:
            processes = list(self._active.values())
        for process in processes:
            self._terminate_group(process)
        self.executor.shutdown(wait=True, cancel_futures=True)


class ExtensionRuntime:
    """Official checkpoint publication: durable first, optional notify second."""

    def __init__(
        self,
        *,
        spool_root: Path,
        run_id: str,
        admissions: Iterable[Admission],
        supervisor: ExtensionSupervisor | None = None,
    ):
        self.spool = ExtensionSpool(spool_root, run_id)
        self.admissions = tuple(admissions)
        self.supervisor = supervisor

    def publish(
        self, *, sequence: int, event: str, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[Path]]:
        envelope = make_envelope(
            run_id=self.spool.run_id, sequence=sequence, event=event, payload=payload
        )
        self.spool.append_event(envelope)  # fsync-before-job-before-notify
        if event == "run.completed":
            self.spool.mark_run_completed(envelope)
        jobs = [
            self.spool.create_job(a, envelope)
            for a in self.admissions
            if event in a.subscriptions
        ]
        if self.supervisor:
            for job in jobs:
                admission = next(
                    a for a in self.admissions if a.namespace == job.parent.parent.name
                )
                self.supervisor.notify(
                    job, admission, run_completed=event == "run.completed"
                )
        return envelope, jobs
